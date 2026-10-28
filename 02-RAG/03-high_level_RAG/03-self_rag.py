# =============================================================================
#  8.3 Self-RAG（自我反思的 RAG）
# =============================================================================
#
#  原理：生成前/后由 LLM 做四步自我反思（论文称 reflection tokens）：
#        Retrieve? → IsRel? → IsSup? → IsUse?
#
#  ── 核心流程 ─────────────────────────────────────────────────────────────────
#
#  整体思路：不盲目检索、不盲信检索结果。每一步都由 LLM 做一次「是/否」自省，
#  只有当前环节通过，才进入下一步；任一环节失败则走对应补救分支。
#
#  四步自省（论文称 reflection tokens）：
#
#    ① Retrieve? — 这个问题需要查资料吗？
#       · 否 → 跳过检索，直接用 LLM 生成（如寒暄、常识题）
#       · 是 → 进入向量检索
#
#    ② IsRel? — 检索到的文档真的和问题相关吗？
#       · 按相似度从高到低逐条检验
#       · 否 → 换下一条候选文档，直到找到相关文档或全部淘汰
#       · 全部不相关 → 返回「无法回答」
#
#    ③ IsSup? — 生成的答案是否完全有文档依据、没有编造？
#       · 否 → 带着「上一版答案 + 编造反馈」重新生成，并重新检查 ③④
#       · 是 → 进入下一步
#
#    ④ IsUse? — 答案是否完整、清晰地回答了问题？
#       · 否 → 带着「上一版答案 + 不完整反馈」重新生成，并重新检查 ③④
#       · 是 → 输出为最终答案
#
#    ③④ 最多重试 MAX_RETRIES 次；用尽后：有依据的答案照常返回，有编造的答案返回「无法回答」
#
#  流程图：
#
#       question
#          │
#       [Retrieve?] 要不要检索？ ──否──► 直接生成 → 最终答案
#          │ 是
#          ▼
#       FAISS 向量检索（取 top-k 候选）
#          │
#       [IsRel?]  文档相关吗？ ──否──► 换下一条文档（循环）
#          │ 是
#          ▼
#       基于该文档生成候选答案 ◄──────────────────────────┐
#          │                                             │ 带反馈重生成
#       [IsSup?]  有文档依据吗？ ──否──────────────────────┤ （最多 MAX_RETRIES 次）
#          │ 是                                           │
#          ▼                                             │
#       [IsUse?]  答案好用吗？ ──否────────────────────────┘
#          │ 是
#          ▼
#        最终答案
#
#  对比 Agentic RAG：Self-RAG 重点是「检索质量 + 答案质量」的自省，而非多工具编排。
#
#  依赖：langchain-deepseek sentence-transformers faiss-cpu python-dotenv
#  环境变量：DEEPSEEK_API_KEY
#
# =============================================================================

import os
import sys

import faiss
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from sentence_transformers import SentenceTransformer

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# ── 语料库 + 向量索引 ─────────────────────────────────────────────────────────

CORPUS = [
    "公司成立于2010年，专注于人工智能领域的研发与应用。",
    "标准工作时间为周一至周五，每天9:00-18:00，午休12:00-13:00。",
    "公司每月15日发放工资，提供五险一金、带薪年假、节日福利及年终奖金。",
    "员工应遵守职业道德，保护公司机密，禁止从事与公司利益相冲突的行为。",
    "年假：入职满1年可享受5天带薪年假，最多15天。",
    "报销应提交发票原件及审批单，审批通过后方可打款。",
]

_embed_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
_corpus_emb = _embed_model.encode(CORPUS, normalize_embeddings=True).astype("float32")
_index = faiss.IndexFlatIP(_corpus_emb.shape[1])
_index.add(_corpus_emb)


def vector_search(query: str, top_k: int = 3) -> list[tuple[float, str]]:
    q_emb = _embed_model.encode([query], normalize_embeddings=True).astype("float32")
    scores, indices = _index.search(q_emb, k=top_k)
    return [(float(scores[0][i]), CORPUS[indices[0][i]]) for i in range(top_k)]


# ── LLM 反思判断（替代论文中的 reflection tokens）────────────────────────────

def _parse_yes(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith("是") or t == "yes" or "yes" in t.split()


def _judge(llm: ChatOpenAI, prompt: str) -> tuple[bool, str]:
    """先让 LLM 说明理由再给结论（比只回一个字更稳定），返回 (结论, 理由)。"""
    text = llm.invoke(
        prompt + "\n先用一句话说明理由，最后一行只写：是 或 否"
    ).content.strip()
    lines = text.splitlines()
    return _parse_yes(lines[-1]), " ".join(lines[:-1]).strip()


def reflect_retrieve(llm: ChatOpenAI, question: str) -> tuple[bool, str]:
    """[Retrieve?] 是否需要检索文档。"""
    return _judge(
        llm,
        f"判断以下问题是否需要查阅公司员工手册才能准确回答。\n"
        f"问题：{question}",
    )


def reflect_relevant(llm: ChatOpenAI, question: str, doc: str) -> tuple[bool, str]:
    """[IsRel?] 检索文档是否与问题相关。"""
    return _judge(
        llm,
        f"判断以下文档是否有助于回答问题。\n"
        f"问题：{question}\n"
        f"文档：{doc}",
    )


def reflect_supported(llm: ChatOpenAI, doc: str, answer: str) -> tuple[bool, str]:
    """[IsSup?] 答案是否有文档依据。"""
    return _judge(
        llm,
        f"判断以下答案是否完全基于文档内容，没有编造。\n"
        f"文档：{doc}\n"
        f"答案：{answer}",
    )


def reflect_useful(llm: ChatOpenAI, question: str, answer: str) -> tuple[bool, str]:
    """[IsUse?] 答案是否完整有用。"""
    return _judge(
        llm,
        f"判断以下答案是否完整、清晰地回答了问题。\n"
        f"问题：{question}\n"
        f"答案：{answer}",
    )


def generate_answer(
    llm: ChatOpenAI,
    question: str,
    doc: str = "",
    prev_answer: str = "",
    feedback: str = "",
) -> str:
    if not doc:
        return llm.invoke(f"请回答：{question}").content.strip()

    prompt = (
        f"根据以下参考资料回答问题，不要编造资料中没有的内容。\n"
        f"参考资料：{doc}\n\n问题：{question}"
    )
    if prev_answer:
        # 重新生成时告诉 LLM 上一版答案及其问题，避免 temperature=0 时原样重复
        prompt += (
            f"\n\n你上一次的回答是：{prev_answer}\n"
            f"存在的问题：{feedback}\n"
            f"请针对该问题修正后重新回答。"
        )
    return llm.invoke(prompt).content.strip()


# ── Self-RAG 主流程 ───────────────────────────────────────────────────────────

MAX_RETRIES = 2   # IsSup / IsUse 未通过时最多重新生成的次数


def self_rag(question: str, llm: ChatOpenAI) -> str:
    print(f"问题：{question}")

    # ① Retrieve?
    need_retrieve, reason = reflect_retrieve(llm, question)
    if not need_retrieve:
        print(f"  [Retrieve?] 否 → 直接生成（{reason}）")
        return generate_answer(llm, question)

    print(f"  [Retrieve?] 是 → FAISS 向量检索（{reason}）")
    candidates = vector_search(question, top_k=3)

    # ② IsRel? — 逐条检验，取第一条相关文档
    doc = ""
    for score, text in candidates:
        print(f"  候选文档 (score={score:.3f}): {text[:40]}...")
        relevant, reason = reflect_relevant(llm, question, text)
        if relevant:
            doc = text
            print(f"  [IsRel?] 是 → 采用该文档（{reason}）")
            break
        print(f"  [IsRel?] 否 → 换下一条（{reason}）")

    if not doc:
        print("  无相关文档，无法回答")
        return "根据现有资料，无法回答该问题。"

    # ③④ IsSup? + IsUse? — 生成 → 验证 → 带反馈重生成，最多重试 MAX_RETRIES 次
    answer = generate_answer(llm, question, doc)
    for attempt in range(MAX_RETRIES + 1):
        supported = reflect_supported(llm, doc, answer)
        useful = supported and reflect_useful(llm, question, answer)  # 有编造的答案不必再评是否好用

        if useful:
            print(f"  第{attempt + 1}版：[IsSup?] 是  [IsUse?] 是 → 输出最终答案")
            return answer

        if not supported:
            print(f"  第{attempt + 1}版：[IsSup?] 否 → 带反馈重新生成")
            feedback = "答案中包含参考资料里没有的内容，请只使用资料中的事实。"
        else:
            print(f"  第{attempt + 1}版：[IsSup?] 是  [IsUse?] 否 → 带反馈重新生成")
            feedback = "答案没有完整、清晰地回答问题，请在资料范围内补充完整。"

        if attempt < MAX_RETRIES:
            answer = generate_answer(llm, question, doc, prev_answer=answer, feedback=feedback)

    # 重试用尽：有依据但不够完整的答案仍可返回；有编造的答案宁可不答
    print("  达到重试上限")
    return answer if supported else "根据现有资料，无法给出有可靠依据的答案。"


# ── 演示 ──────────────────────────────────────────────────────────────────────

llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL", "x-test-3"),
    temperature=0,
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)

print("【Self-RAG】示例 1：事实性问题（需检索）")
r1 = self_rag("公司年假最多几天？", llm)
print(f"最终答案：{r1}\n")

print("=" * 60)
print("【Self-RAG】示例 2：寒暄（无需检索）")
r2 = self_rag("你好，你是谁？", llm)
print(f"最终答案：{r2}")
