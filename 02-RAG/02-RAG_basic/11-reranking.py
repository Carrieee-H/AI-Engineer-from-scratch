# =============================================================================
#  Step-back 检索  &  重排序（Reranking）
# =============================================================================
#
#  ── Step-back（两次检索拼上下文）────────────────────────────────────────────
#
#  原理：对用户原始问题生成一个更抽象的"退一步"问题，两路检索后合并上下文，
#        让 LLM 同时拥有具体细节与背景知识。
#
#       用户问题 ──────────────────────────────► 具体检索结果 (concrete_ctx)
#            │                                          │
#            │ LLM 生成抽象问题                         │ merge()
#            ▼                                          │
#       抽象问题 ──────────────────────────────► 背景检索结果 (background_ctx)
#                                                       │
#                                                       ▼
#                                               final_prompt → LLM
#
#  ── 重排序（Reranking）───────────────────────────────────────────────────────
#
#  原理：向量检索（Bi-Encoder）为速度对 query-doc 独立编码，交互信息不足；
#        Cross-Encoder 把 query 与 doc 拼在一起打分，精度更高但慢，
#        故放在 Top-K 之后做小范围重排。
#
#       ┌──────────────────────────────────────────────────┐
#       │                  Bi-Encoder                      │
#       │  encode(query) ──► q_vec                         │  快，可 ANN
#       │  encode(doc)   ──► d_vec   score = q_vec · d_vec │  精度低于 CE
#       └──────────────────────────────────────────────────┘
#
#       ┌──────────────────────────────────────────────────┐
#       │                 Cross-Encoder                    │
#       │  encode([query, doc]) ──► score                  │  精度高
#       │  query 与 doc 深度交互（Self-Attention）          │  慢，小批量
#       └──────────────────────────────────────────────────┘
#
#  流程：
#       Query ──► Bi-Encoder 向量检索 ──► Top-K 候选
#                                              │
#                                   Cross-Encoder 重排序
#                                              │
#                                         Top-N 结果（N < K）
#
# =============================================================================

from datetime import datetime
import sys

sys.stdout.reconfigure(encoding="utf-8")

corpus = [
    "公司成立于2010年，专注于人工智能领域的研发与应用。",
    "公司每月15日发放工资，提供五险一金、带薪年假。",
    "标准工作时间为周一至周五，每天9:00-18:00。",
    "年假：入职满1年可享受5天带薪年假，最多15天。",
    "员工应遵守职业道德，保护公司机密。",
    "报销应提交发票原件及审批单。",
    "年假按工龄累计，最长不超过15天。",
    "员工需遵守考勤制度，迟到需补卡。",
    "公司每月15日发放工资，提供五险一金、带薪年假。",
    "标准工作时间为周一至周五，每天9:00-18:00。",
    "年假：入职满1年可享受5天带薪年假，最多15天。",
    "员工应遵守职业道德，保护公司机密。",
    "报销应提交发票原件及审批单。",
    "年假按工龄累计，最长不超过15天。",
    "员工需遵守考勤制度，迟到需补卡。",
]

query = "发工资"


# ── Part 1: Step-back 查询生成 ────────────────────────────────────────────────

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # 从上级目录逐级查找 .env，SOCLAAS_API_KEY

# DeepSeek 兼容 OpenAI 接口，直接用 openai SDK 调用
llm_client = OpenAI(
    api_key=os.getenv("SOCLAAS_API_KEY"),
    base_url="https://soclaas-api.comp.nus.edu.sg/v1",
)
LLM_MODEL = os.getenv("SOCLAAS_MODEL", "default")

# few-shot 示例：教模型把具体问题"退一步"抽象成更上位的问题
STEP_BACK_PROMPT = """你是一个检索查询改写助手。请把用户的具体问题改写成一个更抽象、更通用的"退一步"问题，
用于检索回答原问题所需的背景知识或相关制度。只输出改写后的问题，不要输出任何解释。

示例：
具体问题：张三入职满3年，今年能休几天年假？
退一步问题：公司的年假制度是怎样规定的？

具体问题：迟到10分钟会扣多少钱？
退一步问题：公司的考勤与迟到处罚规定有哪些？

具体问题：{question}
退一步问题："""


def step_back_queries(user_question: str) -> tuple[str, str]:
    """
    调用 LLM 生成抽象的退步问题。
    返回 (具体问题, 抽象退步问题)
    """
    resp = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": STEP_BACK_PROMPT.format(question=user_question)}],
        temperature=0,  # 改写任务要稳定输出，不需要随机性
    )
    abstract_q = resp.choices[0].message.content.strip()
    return user_question, abstract_q


question = "公司每月几号发工资？"
q1, q2 = step_back_queries(question)

print("【Step-back 查询】")
print(f"  具体问题：{q1}")
print(f"  抽象问题：{q2}")



# ── Part 2: Bi-Encoder 召回 → Cross-Encoder 重排 ─────────────────────────────

# pip install sentence-transformers
import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

TOP_K = 4   # Bi-Encoder 粗召回数量
TOP_N = 2   # Cross-Encoder 精排后保留数量

print(" load bi-encoder and cross-encoder start time:")
time_start = datetime.now()
bi_encoder = SentenceTransformer("BAAI/bge-small-zh-v1.5")
cross_encoder = CrossEncoder("BAAI/bge-reranker-base")
print(" load bi-encoder and cross-encoder end time:")
time_end = datetime.now()
print(f" load bi-encoder and cross-encoder time: {time_end - time_start}")

#离线：建库时编码一次即可
doc_vecs = bi_encoder.encode(corpus, normalize_embeddings=True)
def bi_encoder_retrieve(
    query: str,
    corpus: list[str],
    doc_vecs: np.ndarray,
    model: SentenceTransformer,
    top_k: int,
) -> list[tuple[str, float]]:
    """Bi-Encoder 向量检索：query 与 doc 独立编码，按余弦相似度取 Top-K。"""
    q_vec = model.encode([query], normalize_embeddings=True)[0]
    scores = doc_vecs @ q_vec
    ranked_idx = np.argsort(scores)[::-1][:top_k]
    return [(corpus[i], float(scores[i])) for i in ranked_idx]


def cross_encoder_rerank(
    query: str,
    candidates: list[str], 
    reranker: CrossEncoder,
    top_n: int,
) -> list[tuple[str, float]]:
    """Cross-Encoder 精排：query 与 doc 联合编码，对 Top-K 候选重排取 Top-N。"""
    pairs = [[query, doc] for doc in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return ranked[:top_n]




# Step 1: Bi-Encoder 粗召回
print(" bi-encoder start time:")
time_start = datetime.now()
bi_results = bi_encoder_retrieve(query, corpus, doc_vecs, bi_encoder, top_k=TOP_K)

print(" bi-encoder end time:")
time_end = datetime.now()
print(f" bi-encoder time: {time_end - time_start}")
print(f"\n【Step 1】Bi-Encoder 粗召回 Top-{TOP_K}")
for rank, (doc, score) in enumerate(bi_results, start=1):
    print(f"  Top-{rank} (cos={score:.4f}): {doc}")

# Step 2: Cross-Encoder 精排
print(" cross-encoder start time:")
time_start = datetime.now()
candidate_docs = [doc for doc, _ in bi_results]
reranked = cross_encoder_rerank(query, candidate_docs, cross_encoder, top_n=TOP_N)
print(" cross-encoder end time:")
time_end = datetime.now()
print(f" cross-encoder time: {time_end - time_start}")
print(f"\n【Step 2】Cross-Encoder 精排 Top-{TOP_N}")
for rank, (doc, score) in enumerate(reranked, start=1):
    print(f"  Top-{rank} (ce={score:.4f}): {doc}")


# ── Part 3: Step-back 两路检索 → 合并 → Cross-Encoder 重排 ───────────────────
#
#   q1（具体）──► bi_encoder 召回 Top-K ──┐
#                                         ├─► merge 去重 ──► cross_encoder 用 q1 重排 ──► Top-N
#   q2（抽象）──► bi_encoder 召回 Top-K ──┘

def merge(*ctx_lists: list[tuple[str, float]]) -> list[str]:
    """合并多路检索结果，按出现顺序去重。"""
    seen, merged = set(), []
    for ctx in ctx_lists:
        for doc, _ in ctx:
            if doc not in seen:
                seen.add(doc)
                merged.append(doc)
    return merged


concrete_ctx   = bi_encoder_retrieve(q1, corpus, doc_vecs, bi_encoder, top_k=TOP_K)  # 具体细节
background_ctx = bi_encoder_retrieve(q2, corpus, doc_vecs, bi_encoder, top_k=TOP_K)  # 背景知识
merged_ctx = merge(concrete_ctx, background_ctx)

# 最终要回答的是原问题，所以用 q1 对合并后的候选重排
step_back_reranked = cross_encoder_rerank(q1, merged_ctx, cross_encoder, top_n=TOP_N)

print(f"\n【Step-back】合并去重后候选 {len(merged_ctx)} 条，重排后 Top-{TOP_N}：")
for rank, (doc, score) in enumerate(step_back_reranked, start=1):
    print(f"  Top-{rank} (ce={score:.4f}): {doc}")
