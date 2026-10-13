# Honcho：后台推断与用户表征

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

本次调研是拆解 Honcho 的设计思想和实现方式，判断哪些机制可供 DistillAI 借鉴，不表示要把 Honcho 接入本项目。Honcho 本体是独立的记忆服务：HTTP API 同步接收和检索消息，后台 worker 异步生成结论、摘要及用户表征。自建 Agent 可通过 Python/TypeScript SDK（HTTP API 的客户端封装）或直接调用 REST API，在自己的对话流程中决定何时写入、何时读取；Agent 对外提供什么接口仍由其应用决定。参考：[Honcho 快速入门](https://github.com/plastic-labs/honcho/blob/main/docs/v3/documentation/introduction/quickstart.mdx)、[服务架构](https://github.com/plastic-labs/honcho#architecture)。

接入 Codex 等已有 Agent 时，Honcho 的 `codex-honcho` 安装程序组合了 Hook、MCP 和 Skill。Hook 负责自动采集及回注，MCP 给前台 Agent 提供按需搜索、询问用户表征和管理结论的工具，Skill 提示何时使用这些工具。仅注册 MCP 不会自动采集每轮会话。参考：[codex-honcho README](https://github.com/plastic-labs/codex-honcho)。

## Codex 端采集什么、何时采集

`codex-honcho` 没有另起常驻的本地采集服务。`Stop` 是每轮结束而非整个 session 关闭；`Stop`/`PreCompact` Hook 执行时，根据 `transcript_path` 读取 Codex 本地 rollout JSONL 的新增部分，提取 `response_item` 中用户与助手的文本消息，附带事件时间，写入本地追加式队列。解析器按角色与文本类型筛选，没有限定只保留助手最终回复；它会跳过工具调用、推理和非文本块，也会按已知标签过滤 Codex 自动注入的环境及指令文本，避免误当作用户原话。该过滤只覆盖代码列出的标签。参考：[会话解析器](https://github.com/plastic-labs/codex-honcho/blob/main/src/transcript/codex.ts)、[writeback Hook](https://github.com/plastic-labs/codex-honcho/blob/main/src/hooks/writeback.ts)。

`PostToolUse` Hook 不调用 LLM 总结工具结果，而是用固定代码规则生成一行活动摘要：跳过部分只读命令及 Honcho 自身调用；其他 shell 命令可记为 `ran: <命令前 120 个字符>`，补丁可记为 `edited: <文件名>`，其余工具通常记为 `used <工具名>`。代码没有使用完整 `tool_response` 生成摘要。该摘要先进入同一个本地队列，随后作为带 `tool` 元数据的消息上传。参考：[工具摘要规则](https://github.com/plastic-labs/codex-honcho/blob/main/src/hooks/observe.ts)、[消息映射](https://github.com/plastic-labs/codex-honcho/blob/main/src/hooks/flush.ts)。

```text
Codex 会话 JSONL ──Stop/PreCompact Hook──> 新增用户/助手文本 ─┐
PostToolUse Hook ──固定规则摘要───────────────────────────────┤
                                                              ▼
                                                   本地追加式 JSONL 队列
                                                              │
                                                 Stop Hook 内上传 Honcho API
                                                              ▼
                                                Honcho 后台 worker 异步推断
```

队列用读取位置和发送位置处理增量及重试；上传在 `Stop` Hook 的进程内完成，不依赖另一个常驻的本地上传服务。Honcho 服务端的异步推断 worker 是另一环节。`SessionStart` Hook 可取回并回注简短记忆；`UserPromptSubmit` 的逐轮回注为可选且默认关闭，MCP 则支持前台 Agent 按需查询。默认情况下，同一工作目录中的多个 Codex 会话会映射到同一个 Honcho session，也可改为按分支或按单次会话划分。参考：[上传实现](https://github.com/plastic-labs/codex-honcho/blob/main/src/hooks/flush.ts)、[Hook 与会话策略](https://github.com/plastic-labs/codex-honcho#how-it-works)。

## 从原始消息到用户表征

Codex rollout JSONL 是接入插件的读取来源；解析后上传给 Honcho 的是按 session 排列、标明发送者的消息，而不是把整份 rollout 当成一个 JSONL 文档交给推断模型。Honcho 把消息写入 PostgreSQL 的 `messages` 表，保留 `session_name`、`peer_name`、`content`、`metadata`、会话内顺序和时间等字段；随后将推断任务排队，由独立 worker 异步处理。原始消息、会话摘要和推断结论是不同的数据层。参考：[消息表模型](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/models.py)、[架构说明](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/docs/v3/documentation/core-concepts/architecture.mdx)。

例如，用户说“原型阶段暂不引入 Obsidian”。原始 `Message` 保存这句话及其作者、会话和时间；Deriver 可以产出“用户当前原型阶段决定暂不引入 Obsidian”这一带条件的结论；Summarizer 可以把围绕存储方案的整段讨论压缩为会话摘要；Dreamer 在之后有更多独立证据时才可能归纳更一般的取舍倾向。最后那种倾向是推断，不能反过来当作用户原话。实际调用中消息通常以 `content`、`peer` 和可选 `metadata` 等字段提交，服务端另行赋予 ID、会话内顺序和时间；本例仅说明数据层次，不声称这是某次真实 Honcho 输出。

| 阶段 | 输入与处理 | 产物及用途 |
| --- | --- | --- |
| Deriver | 读取新增消息组成的批次；提示词标明每条消息的作者、时间和是否属于目标用户，调用 LLM 提取关于该用户的独立、可自洽陈述。其他人的消息只作理解上下文，不作为目标用户事实的直接来源 | 一条结论作为一个 `Document`，保存文本、层级、向量、观察者与被观察者、时间及来源关联；这是语义结论的粒度，不是按固定长度切原始消息的 chunk |
| Summarizer | 根据消息数量触发独立的 LLM 摘要任务，用上一版摘要加上后续新消息递归压缩；短摘要与长摘要各有一个不断更新的 session 槽位 | 会话摘要用于重建较长对话的上下文，不等于用户特征或用户掌握程度 |
| Dreamer | 在积累新结论并满足调度条件后，于后台重新检查已有结论；先做演绎探索，再做跨结论模式归纳，可修订过时、重复或矛盾的内容，并更新 peer card | 更高层的结论和简短用户卡片；归纳判断需要多条来源支持，仍须回查证据 |
| Dialectic | 查询时启动的带工具调用能力的问答 Agent；按问题检索结论，必要时追溯来源结论或原始消息，再组织答案 | 有针对性的回答；可返回它**读过**的证据列表，但“读过”不证明答案确实依赖每条证据 |

需要区分文档对整体能力的概述与本次核对的具体代码：当前 `minimal_deriver_prompt` 主要要求提取用户消息支持的 **explicit atomic facts**（明确、原子化事实）；较高层的演绎和归纳还有 Dreamer 路径，不能把所有推断都归给逐消息 Deriver。`Document` 是结论记录，原始 `Message` 仍单独保留。参考：[Deriver 提示词](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/deriver/prompts.py)、[Deriver 调用与保存](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/deriver/deriver.py)、[摘要实现](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/utils/summarizer.py)、[Dreamer 编排](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/dreamer/orchestrator.py)、[证据返回说明](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/docs/v3/documentation/features/advanced/evidence.mdx)。

Dreamer 可选的 *surprisal* 是一项**探索采样**：利用已有结论的 embedding 和空间分布，优先选取相对异常、较少被现有结论覆盖的内容，形成探索提示，再交给演绎与归纳 specialist。它扩展了被检查的区域，但分数不表示“用户不懂”，也不能独自发现知识盲区。若借鉴这一思想，DistillAI 可以用它挑选值得验证的候选概念；是否为盲区仍要依据用户的独立解释或应用判断。参考：[surprisal 实现](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/dreamer/surprisal.py)、[Dreamer 编排](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/dreamer/orchestrator.py)。

## 记忆如何被读取并进入 Codex

Honcho 提供不同粒度的读取方式：`session.context()` 组合近期原始消息与会话摘要，需要时可包含指定用户的表征；结论查询按语义相似度返回相关 `Document`；`peer.chat()` 则由 Dialectic 先取相关结论，再按需调用工具读取更多结论、原始消息或推理来源，生成针对问题的回答。因此“存了记忆”不等于“每一轮都把所有记忆放进前台上下文”。参考：[Get Context](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/docs/v3/documentation/features/get-context.mdx)、[Chat](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/docs/v3/documentation/features/chat.mdx)、[Dialectic 实现](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/dialectic/core.py)。

`codex-honcho` 默认在 `SessionStart` 查询一份精简用户上下文并注入，同时提示 Codex 可用 MCP 进一步查询。查询结果作为本地 JSON 快照存于 `HONCHO_CONFIG_DIR/codex/context/`，未设置该变量时位于 `~/.honcho/codex/context/`；其中有 `representation`、`peerCard`、获取时间 `at` 和去重用的 `lastInjected`。`SessionStart` 读取此缓存时按 10 分钟判断是否过期并在需要时重新获取。`UserPromptSubmit` 在用户提交 prompt、模型处理该轮之前运行，但逐轮注入默认关闭；开启后也只读本地快照，不发起网络请求，并跳过简短确认、空缓存和与上次相同的内容。**Hook 被触发不等于每次都注入；MCP 是前台 Agent 按需调用的查询通道。**参考：[Codex Hook 时机与输出](https://developers.openai.com/de-DE/docs/hooks)、[SessionStart 回注](https://github.com/plastic-labs/codex-honcho/blob/main/src/hooks/recall.ts)、[UserPromptSubmit 处理](https://github.com/plastic-labs/codex-honcho/blob/main/src/hooks/prompt.ts)、[本地缓存](https://github.com/plastic-labs/codex-honcho/blob/main/src/cache.ts)。

## 对 DistillAI 的借鉴

值得借鉴的是职责划分：Hook 只负责发现并可靠交付新增材料，本地队列和游标处理重复、失败与重试，后端独立做语义分析，前台通过 Hook 回注或 MCP 查询使用分析结果。当前 DistillAI 已有原始 Hook 事件采集；是否进一步读取 Codex rollout JSONL、如何回注及提供查询工具，仍需结合实际证据需求决定。

数据选择不宜照搬。Honcho 的 Codex 接入在上传前筛掉大量原始事件，并把工具活动压缩为摘要；DistillAI 若要研究用户判断所依据的工具结果、问题如何形成以及假设如何被验证，应先保存可追溯的原始证据，再决定分析时如何筛选。Honcho 的接入链路是机制参考，不能由此推断它已经实现 DistillAI 所需的竞争假设验证。
