# 第 6 轮 LLM API Call 分析

> 日志：`abd7c552-4d7b-4af1-875d-17a05b669f53.jsonl`  
> 对照：`claude_log_analysis.md` 调用 #6  
> 分析时间：2026-10-13

## 这次调用是什么

| 项 | 值 |
|----|----|
| 序号 | 第 6 次（按 message id 去重，全会话共 20 次） |
| Message ID | `msg_a398d505-3a5a-40de-8f56-d6ae77ee98b3` |
| 模型 | `deepseek-v4-flash`（会话登记的模型 id 是 `ctai-anthropic-deepseek-v4-flash`） |
| 时间 | 2026-10-12T02:37:05.944Z → 02:37:07（约 2 秒） |
| 日志行 | 48–51（4 个 `apiBlockIndex`：0 thinking、1 text、2 WebSearch、3 Bash） |
| 触发 | 第 5 轮 `ak.stock_zh_a_spot_em()` 返回 `ConnectionError` 之后 |
| 动作 | 改走 WebSearch，同时用 Bash 试新浪 `ak.stock_zh_a_spot()` |

调用前最后一条 reminder（第 47 行）是：

```text
<total_tokens>14960072 tokens left</total_tokens>
```

---

## 1. 上下文构成

Claude Code 没有把原始 HTTP body 写进 jsonl。能还原的是两次 `prompt_snapshot` 加上第 48 行之前的对话和 attachment。下面按「会进入这一次请求的内容」列出。日志里的 mode、permission-mode、atis-latch、file-history、ai-title、last-prompt 只是会话记账，不进模型上下文。

`prompt_snapshot` 记了两次（第 13 行无 tools，第 21 行带 27 个 tools）。第二次覆盖第一次，system prompt 只算一份。`total_tokens` 在 system prompt 里是一个槽位（part 9），后面的 reminder 是在改这个槽，不是把 15M、14.97M、14.96M 叠在一起。第 6 轮生效的是 **14,960,072**。

### 1.1 System prompt（6,066 字符，10 段）

前缀另外还有 `cliPrefix`（57 字符）：`You are Claude Code, Anthropic's official CLI for Claude.`

| # | 段落开头 | 字符数 | 内容 |
|---|----------|------:|------|
| 0 | You are an interactive agent… | 1,210 | 角色、安全边界、Harness（Markdown 输出、权限模式、专用工具优先、代码引用格式） |
| 1 | Write code that reads like… | 94 | 注释密度、命名、风格与周围代码一致 |
| 2 | When you use a pronoun… | 357 | 代词用 they/them |
| 3 | For actions that are hard to reverse… | 632 | 难撤销或对外动作先确认；如实报告 |
| 4 | # Session-specific guidance | 422 | `!` 前缀直接跑终端；Skill 用 `/skill-name` |
| 5 | # Memory | 2,120 | 持久记忆目录、user/feedback/project/reference、MEMORY.md 索引 |
| 6 | # Environment | 625 | 环境信息怎么用（指令，不是 cwd 本身） |
| 7 | # Context management | 280 | 长对话自动摘要，不必提前结束 |
| 8 | When you have enough information to act… | 277 | 信息够了就行动，不重复推导 |
| 9 | `<total_tokens>… tokens left` | 49 | 会话预算槽。快照里写的是初始 `15000000`；第 6 轮前已被更新为 `14960072` |

### 1.2 工具 schema（snapshot 登记 27 个，共 115,054 字符）

这是第 21 行 `prompt_snapshot.tools` 的全集。字符数是 schema JSON 的长度。服务端没有按工具拆 token，见第 2 节的差额说明。

| 工具 | 字符数 | 工具 | 字符数 |
|------|------:|------|------:|
| Agent | 4,976 | Grep | 3,867 |
| AskUserQuestion | 6,901 | ListAgents | 2,010 |
| Bash | 4,537 | NotebookEdit | 2,351 |
| CronCreate | 7,133 | Read | 2,476 |
| CronDelete | 665 | ReportFindings | 2,904 |
| CronList | 446 | ScheduleWakeup | 8,415 |
| DesignSync | 13,009 | SendMessage | 8,359 |
| Edit | 1,412 | Skill | 3,301 |
| EnterPlanMode | 8,488 | TaskOutput | 2,697 |
| EnterWorktree | 7,359 | TaskStop | 1,264 |
| ExitPlanMode | 4,417 | WebFetch | 1,392 |
| ExitWorktree | 4,554 | WebSearch | 1,241 |
| Glob | 945 | Workflow | 8,982 |
| | | Write | 953 |

### 1.3 开场 system-reminder（挂在第一条用户消息上，之后保留）

| 顺序 | attachment | 字符数 | 明细 |
|------|------------|------:|------|
| 1 | environment | 299 | cwd = `D:\AI-Engineer-from-scrach-main\AI-Engineer-from-scrach-main`；非 git；win32；bash；Windows 11 Pro 10.0.26200 |
| 2 | model | 99 | `You are powered by the model ctai-anthropic-deepseek-v4-flash.` |
| 3 | agent_listing_delta | 2,771 | 6 个 agent：`claude`（\*）、`claude-code-guide`、`Explore`、`general-purpose`、`Plan`、`statusline-setup`。本会话没有派生子 agent |
| 4 | skill_listing | 5,736 | 13 个 skill：`03-akshare-stock`、`dataviz`、`code-review`、`simplify`、`loop`、`claude-api`、`run`、`security-review`、`update-config`、`keybindings-help`、`fewer-permission-prompts`、`workflow-authoring`、`init` |
| 5 | date | 64 | Today's date is 2026-10-12 |
| 6 | remote_session_change | 341 | commit 末尾 `Co-Authored-By: Claude Code <noreply@anthropic.com>`；PR 末尾 Claude Code 署名 |
| 7 | total_tokens_reminder | 86 | 当前值 **14,960,072 tokens left**（第 47 行，紧挨这次请求） |

`command_permissions`（`allowedTools: []`，51 字符）没有 `rendered` 正文，不算进模型上下文。

### 1.4 对话历史（第 1–5 轮的输入，第 6 轮还没生成）

同一 message id 的 thinking / text / tool_use 在请求里是一条 assistant 消息的多个 content block。下表按轮合并，字符数是可见正文。

| 轮次 | 角色 | 字符数 | 内容 |
|------|------|------:|------|
| 用户 | user | 14 | `分析比亚迪股票，生成完整报告` |
| #1 | assistant | 739 | thinking：用 `03-akshare-stock` 做比亚迪分析（A 股 002594 / 港股 1211）。text 为空行。tool：`Skill("03-akshare-stock")` |
| #1 结果 | user | 33 + 1,991 | `Launching skill: 03-akshare-stock`，接着整份 SKILL.md（脚本表、用法、目录、API 说明） |
| #2 | assistant | 751 | thinking：002594.SZ / 01211.HK，准备并行跑脚本。text：说明将做全面分析。tool：`Bash` `get_realtime_quote.py 002594.SZ` |
| #2 结果 | user | 36 | `获取失败: 行情字段不足: 002594.SZ` |
| cwd 变更 | attachment | 247 | environment update：cwd 改为 `…\.claude\skills\03-akshare-stock` |
| #3 | assistant | 883 | thinking：实时行情失败，准备看脚本和依赖。text：说明要跑完整分析并检查环境。tool：`Bash` `ls scripts/`、`python --version`、`import akshare` |
| #3 结果 | user | 297 | 14 个脚本文件名；Python 3.12.10；akshare 1.19.1 |
| #4 | assistant | 621 | thinking：改跑 `stock_analyzer.py`。text 为空行。tool：`Bash` `python scripts/stock_analyzer.py 002594.SZ -o report/report.md` |
| #4 结果 | user | 1,759 | Exit code 1。基本信息、实时行情、K 线、估值、资金流向、股东全部失败，并带 `FileNotFoundError` |
| #5 | assistant | 879 | thinking：判断是东方财富网络问题。tool：`Bash` `ak.stock_zh_a_spot_em()` 过滤 `002594` |
| #5 结果 | user | 444 | tqdm 进度后 `ConnectionError: ('Connection aborted.', RemoteDisconnected(...))` |

对话正文合计约 **8,447** 字符。加上开场 reminder 约 **9,643** 字符、system prompt **6,066** 字符、cliPrefix **57** 字符、工具 schema **115,054** 字符，snapshot 侧总规模约 **14.0 万字符**。工具 schema 占其中大约 83%。

### 1.5 这次请求新追加的尾巴

相对第 5 轮，新内容只有两块：

1. 第 5 轮的 assistant（thinking + `stock_zh_a_spot_em` 的 Bash）
2. 该命令的 `ConnectionError` 工具结果（444 字符）

第 47 行的 token reminder 数字与第 43 行相同（都是 14,960,072），没有新增信息量。服务端把这截尾巴记成 **831** 个未缓存 input token，前面的稳定前缀记成 **24,064** 个 cache read。

---

## 2. Token 消耗

一次请求被拆成 4 个流式 block 写入日志。前 3 个 block 的 usage 不完整，且数字彼此相同。完整账单在最后一个 block。

| Block | 行 | 内容 | usage 里有什么 |
|------:|----|------|----------------|
| 0 | 48 | thinking，323 字符 | `input_tokens: 44142`，`output_tokens: 0`。无 cache 字段 |
| 1 | 49 | text：网络受限，改 Web 搜索并试其他 akshare 接口 | 同上，44142 / 0 |
| 2 | 50 | `WebSearch` query = `比亚迪 002594 股票 股价 2026年10月 最新行情` | 同上，44142 / 0 |
| 3 | 51 | `Bash`：`ak.stock_zh_a_spot()` 过滤代码 `002594`，timeout 60000 | **完整 usage，见下表** |

Block 3 的服务端 usage：

| 字段 | 值 | 含义 |
|------|---:|------|
| `input_tokens` | 831 | 未命中缓存的新输入 |
| `cache_read_input_tokens` | 24,064 | 命中缓存的前缀 |
| `cache_creation_input_tokens` | 0 | 没有新建缓存 |
| `ephemeral_5m_input_tokens` | 0 | |
| `ephemeral_1h_input_tokens` | 0 | |
| **上下文合计** | **24,895** | 831 + 24,064 |
| `output_tokens` | 315 | thinking + text + 两个 tool call 都算在这里 |
| `thinking_tokens` | 0 | 网关没有把 thinking 单列 |
| `server_tool_use.web_search_requests` | 0 | WebSearch 是模型发出的工具调用，还没执行，所以这一跳服务端搜索次数是 0 |
| `service_tier` / `speed` | standard | |

这一跳的服务端总 token = 24,895 + 315 = **25,210**。

输出 315 与正文规模相符：英文 thinking 约 80 token，中文说明约 50–80 token，WebSearch 参数很小，Bash 命令（含一段 Python）大约 150 token。

### 44,142 这个数

Block 0–2 上的 `44142` 是同一次请求的输入被重复写在每个分片上，不是每个 block 又花了 44,142。它没有 cache 字段，`output_tokens` 也停在 0，所以它不是结算值。

和第 6 轮的服务端上下文 24,895 对不上（44142 / 24895 ≈ 1.77）。第 2 轮也有同样的形态：中间帧 `input_tokens` 43,848，最后一个 block 的服务端 input 是 22,852。因此 44,142 是流式分片上的客户端或网关计数，不能当成这次请求的上下文长度，也不能当成剩余窗口。

snapshot 约 14 万字符、服务端只计 24,895 token，两边也不会逐项相加相等。工具 JSON 若按大约 4 字符/token 粗算，27 个完整 schema 本身就接近 2.9 万 token，已经高于 24,895。日志里没有原始 HTTP body，无法逐字段证明是分词更紧，还是实际发出去的工具集比 snapshot 全集短（Claude Code 会延迟加载一部分工具）。上下文明细以 snapshot 为准；token 以 block 3 为准。

---

## 3. 总 token left

第 6 轮发出之前，模型看到的剩余额度是：

**14,960,072**

来源是第 47 行 attachment：

```text
<system-reminder>
<total_tokens>14960072 tokens left</total_tokens>
</system-reminder>
```

从会话起点到这一刻的扣减：

| 时点 | 行 | tokens left | 相对上一次 |
|------|----|------------:|----------:|
| 会话开始，第一次 API 之前 | 10 | 15,000,000 | — |
| Skill 加载之后（第 1 轮结算） | 27 | 14,977,920 | −22,080 |
| 实时行情失败 + cwd 变更后 | 33 | 14,976,860 | −1,060 |
| `ls scripts` 结果之后 | 38 | 14,976,369 | −491 |
| `stock_analyzer.py` 失败报告之后 | 43 | 14,960,072 | −16,297 |
| **第 5 轮 ConnectionError 之后，即第 6 轮之前** | **47** | **14,960,072** | **0** |

已从 15,000,000 里划走的数量：

15,000,000 − 14,960,072 = **39,928**

第一笔 −22,080 与第 1 轮服务端 usage 逐位相等：`input_tokens 21,876 + output_tokens 204 = 22,080`。后面几笔是增量，不是把每一轮的完整 input 再扣一次。第 5 轮虽然服务端读了大量 cache，reminder 没有再降。第 6 轮自己的 25,210 也还没记入这个数：第 59、64、68 行仍然是 14,960,072。

---

## 4. 模型窗口是 1M，为什么 token left 是 15M

这是两个不同的计数器。15,000,000 不是「1M 窗口还剩多少」。

**1,000,000** 是 `deepseek-v4-flash` 一次请求能装下的上下文上限（system + tools + messages）。第 6 轮实际放进去的是 24,895 个 input token，大约占这个窗口的 2.5%。若按窗口来算剩余空间，大约是 1,000,000 − 24,895 = 975,105。日志里没有这个字段。

**15,000,000** 是 Claude Code 在发请求之前写进 system prompt 的会话预算。证据：

1. 它出现在第 10 行，时间戳 `2026-10-12T02:34:00.333Z`，第一条 assistant 消息在第 15 行 `02:34:09`。模型还没回复，这个数就已经是整整 15,000,000。窗口剩余不可能在请求发出前等于一个比窗口还大的整数。
2. 同一串字被放进 `prompt_snapshot.systemPrompt` 的第 10 段（part 9），标签是 `<total_tokens>… tokens left</total_tokens>`。这是 harness 的 reminder，不是 API 返回的 `context_window`。
3. 15,000,000 = 15 × 1,000,000。1M 窗口的模型，会话预算按 15 个窗口给。自动压缩会把单次请求清回 1M 以内，同一会话可以连续消耗多个窗口的 token。reminder 追踪的是这条会话还能再记多少，不是下一次请求还能再塞多少。
4. 计数方式对得上「会话预算」，对不上「窗口剩余」。每一轮都会把约 2.2 万–4.4 万的前缀重新送给模型（第 6 轮 cache read 就是 24,064）。如果 15M 是窗口剩余，每轮都要掉这么多。实际从 15,000,000 到第 6 轮之前只掉了 39,928，而且第 5 轮全是 cache hit 时数字不动。

所以第 6 轮同时成立的三个数是：

| 口径 | 数值 |
|------|-----:|
| 单次上下文上限 | 1,000,000 |
| 这次请求的真实上下文 | 24,895（缓存 24,064 + 新输入 831） |
| 这次请求的输出 | 315 |
| 会话预算初始值 | 15,000,000 |
| 这次请求前的 token left | 14,960,072 |
