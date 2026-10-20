# Letta：记忆管理与后台整理

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

调研这些项目的目的是理解其机制、设计理由和代价，判断哪些设计可以为 DistillAI 所用；本节不构成引入组件的决定。Letta 将记忆、消息历史、工具与模型配置视为持续存在的 Agent 状态。这里的学习主要通过修改外部记忆影响未来上下文，并不要求更新模型权重。参考：[Stateful agents](https://docs.letta.com/concepts/stateful-agents)。

## 记忆分工与通用 Agent 的对应

需要区分两代资料：V1 SDK 的核心记忆块、归档记忆与历史消息，以及当前文档中的 MemFS 和 Dreaming。它们共享“少量重要内容常驻上下文，详细资料按需读取”的思想。

| Letta 设计 | 与通用 Agent 的对应 | 设计含义 |
| --- | --- | --- |
| V1 核心记忆块；当前 Letta Code MemFS 的常驻根文件 | 类似 AI 工具加载的 `AGENTS.md` 等上下文文件，但还可保存用户信息及动态状态 | 常驻内容不依赖临时检索命中，同时持续占用上下文；具体加载方式取决于实现。本次实测的根文件 `human.md` 被编译进 `<human>` 系统提示词段 |
| 归档记忆；MemFS 中按需读取的资料 | 外部文件或数据库中的长期资料，也可包含已持久化的工具结果 | 保存不等于进入上下文，需要检索或读取 |
| 历史消息 | 可搜索的原始交互记录 | 允许回查原话，和整理后的记忆具有不同用途 |
| Dreaming | 独立的后台整理任务 | 把部分回顾和整理移出前台响应过程 |

当前 MemFS 用 Markdown 文件保存记忆，默认通过普通文件工具读取和搜索，不要求向量索引。Git 用于整理后记忆的版本管理、同步和并发编辑；这与用 Git diff 发现原始会话新增事件是不同用途。已有的文件读写工具足以承载记忆，关键还在于维护规则。

参考：[V1 记忆块](https://docs.letta.com/v1-sdk/memory/memory-blocks)、[归档与历史消息](https://docs.letta.com/v1-sdk/memory/archival-memory)、[当前记忆设计](https://docs.letta.com/agent-sdk/memory)、[MemFS](https://docs.letta.com/concepts/memfs)、[Sleep-time Compute 的设计动机](https://www.letta.com/blog/sleep-time-compute/)。

## 什么时候记、怎样整理、何时修订

本次核对的 Letta Code 路径将程序调度与语义判断分开：程序安排检查，LLM 按提示词判断具体保存什么，并通过文件工具修改记忆。

前台提示词要求保存影响未来行为的知识，把常驻内容保持精简，详细材料放在外部。后台提示词优先筛选纠错、偏好、长期事实与可复用流程，排除临时和重复内容；没有值得保留的内容可以不改。没有看到这一流程使用独立的数值“长期价值评分”门槛。参考：[前台提示词](https://github.com/letta-ai/letta-code/blob/main/src/agent/prompts/letta_local_memfs.md)。

后台先了解已有记忆，再提取候选内容、筛选、整合、检查并提交。事实和偏好进入记忆，可复用的多步骤流程才进入 Skill。已有主题优先原位更新；冲突时修正旧条目，跨会话综合倾向较新的证据，退役但有历史价值的内容可归档。这些是提示词要求，不是语义正确性的保证。参考：[后台 reflection 提示词](https://github.com/letta-ai/letta-code/blob/main/src/agent/subagents/builtin/reflection-v2.md)。

用本次讨论举例，候选长期认识可以是“在 DistillAI 的组件调研中，用户关注机制、设计理由和代价”。若写成“用户从不关心接入方式”，就扩大了适用范围。这个例子说明：从经历中抽出规则时，需要保留场景与条件；生成并保存一句概括不等于完成验证。

## 后台整理如何触发

公开的 Letta Code 触发代码在一轮结束、记录写入后检查配置，支持关闭、按累计 Agent 步骤、按上下文压缩事件触发。计数比较的是距上次成功整理积累的步骤，不能直接等同于用户消息条数。运行器准备对话材料和记忆快照，在独立记忆工作树中启动整理并处理合并，也检查重复运行及无新增材料等情况。该说明限定于本次核对的公开路径，不推定所有云端部署使用完全相同的实现。

```text
一轮结束并记录材料 → 程序检查触发条件
  → 后台模型读取材料及已有记忆
  → 判断是否值得保留 → 修改记忆或不作修改
  → 保存并整合结果 → 后续模型请求使用更新后的上下文
```

参考：[触发入口](https://github.com/letta-ai/letta-code/blob/main/src/cli/helpers/post-turn-reflection.ts)、[计数及配置规则](https://github.com/letta-ai/letta-code/blob/main/src/cli/helpers/memory-reminder.ts)、[后台运行器](https://github.com/letta-ai/letta-code/blob/main/src/cli/helpers/reflection-launcher.ts)、[Dreaming 文档](https://docs.letta.com/configuration/memory)。源码链接跟随 `main`，实施时需重新核对并固定提交。

## 对 DistillAI 的启发与未解决的问题

可借鉴的是“普通事件规则负责调度，独立模型负责解释材料”，以及“少量当前判断供前台使用，原始证据和详细记录按需读取”。后台整理降低前台等待，但判断可能滞后；常驻记忆方便使用，也会让错误假设持续影响回答。版本历史有助于追查修改，不能证明结论正确。

Letta 的通用整理规则还不足以支撑用户心智假设的验证。比如“原型阶段 Obsidian 太重”和“以后需要图谱浏览界面”可以同时成立，不能仅因后一句更新就覆盖前一句。DistillAI 需要记录条件、证据及竞争解释，允许暂时无法确定。前台 Agent 的提问也应保留，以评估回答受到的影响。

当前仍待验证的是：什么材料足以形成假设、什么证据足以支持或推翻它，以及何时将更新提供给前台。本节记录设计参考；后台分析、记忆回注和假设验证尚未实现。

## Letta Code 专项调研收尾：一条记忆的实测生命周期

以下是 **Letta Code v0.33.6、本地源码提交 `2b95889`** 的运行结果，不把 V1 SDK、Letta 服务端或 Codex 集成的行为混写成同一条已验证链路。测试使用隔离的本地 backend 和 `anthropic/claude-haiku-4-5`；Agent ID 为 `agent-local-525ac681-a790-49d3-a76f-6ed8c4f2bda4`。原始测试数据暂存在 `C:\Users\11954\AppData\Local\Temp\letta-lifecycle-9eb26e14d79b43a9b01c7a41a5ee5df1`，该目录是临时证据，不作为长期档案；关键输入、输出与提交结果记录如下。

| 环节 | 实际输入 | 实际输出及持久化位置 |
| --- | --- | --- |
| 前台显式写入，`local-conv-2` | “请记住：我解释技术流程时，希望看到具体步骤和可核查的证据。请把这条长期偏好写入你的记忆……” | 前台 Agent 先读现有记忆，再用 `Write` 更新 `memory/human.md`，通过 `Bash` 执行 `git add`、`git commit`；提交 `0d75ab3 memory: record human preference for concrete steps and verifiable evidence`。原始用户消息、工具调用、工具结果和最终回复存于该会话的 `messages.jsonl`。这是**前台 Agent 根据明确请求主动写入**，不是后台自动提取。 |
| 普通对话与触发，`local-conv-6` | “这是记忆生命周期测试。请只回复‘收到’。我希望技术说明先给可复现的实际输入和输出，再给解释；如果已有类似记忆，请不要重复写入。”；测试配置 `reflection-trigger=step-count`、阈值 `1`，使用双向 `stream-json` headless 模式 | 前台仅答“收到”。Letta 将这一轮写入 `transcript.jsonl`：一条用户消息、一条助手消息；并生成 442 字节的 `payload-auto-4fre1h.json`，其消息数组为 `meta → user → assistant`。`state.json` 先记录 `total_completed_steps: 1`、`steps_since_last_successful_reflection: 1`，随后启动独立 reflection 子进程。 |
| 后台整理与合并 | Reflection Agent 的任务提示要求从环境变量 `TRANSCRIPT_PATH` 读取上述 payload、对照 `MEMORY_DIR` 中的已有记忆；只保留值得长期保存的新内容，已有主题优先原位修改，修改后提交。任务提示还内嵌了父 Agent 的记忆快照。 | 子 Agent 实际读取了 payload 和 `human.md`，判断“具体步骤、可核查证据”已保存，新增差异仅是“**先呈现可复现的实际输入和输出，再解释**”。它用 `Edit` 给 `human.md` 增加一行，并在独立记忆工作树提交 `a9e6958 chore(reflection): note I/O-first ordering for technical explanations`；运行器把提交合并回父 Agent 的 MemFS。最终 `state.json` 显示 `reflected_completed_steps: 1`、`steps_since_last_successful_reflection: 0`。子 Agent 的工具调用、结果和最终报告保留在其独立会话的 `messages.jsonl`。 |
| 新会话使用，`local-conv-7` | “解释技术流程时，你现在记住的内容顺序要求是什么？……不要修改记忆。” | 新会话准确答出“先给可复现的实际输入与输出，再做解释”。核对该会话保存的 `system-prompt.json`：更新后的 `human.md` 内容已进入 `<human>…</human>` 段；这一轮未调用历史搜索。故本例是**常驻记忆编入系统提示词后被使用**，不是每轮对完整历史或外部文件做检索。 |

这次运行把几类存储分开了：原始交互在本地 backend 的 `conversations/<编码后的会话键>/messages.jsonl`；供后台整理的一轮材料在 `transcripts/<agent-id>/<conversation-id>/transcript.jsonl` 和 `payload-auto-*.json`；提炼后的长期偏好在 MemFS Git 仓库的 `memory/human.md`；下一次模型请求所见的编译结果可从相应会话的 `system-prompt.json` 核查。测试临时目录中的具体证据为：`backend/conversations/Y29udmVyc2F0aW9uOmxvY2FsLWNvbnYtMg/messages.jsonl`（前台写入）、`transcripts/agent-local-525ac681-a790-49d3-a76f-6ed8c4f2bda4/local-conv-6/`（transcript、payload、state）、`backend/conversations/ZGVmYXVsdDphZ2VudC1sb2NhbC05ZWY4Mzc2YS0zMzcwLTQ2OTAtODUyMC0zNWJlODgzYzRjYjM/messages.jsonl`（reflection 子 Agent）、`backend/conversations/Y29udmVyc2F0aW9uOmxvY2FsLWNvbnYtNw/system-prompt.json`（新会话）。`human.md` 是文件，**并不意味着“核心记忆只是固定的一段系统提示词”**：文件是持久化源，运行时把常驻根文件编入提示词；其他外部记忆若未常驻，则需要主动读取。后台是否更新由 LLM 按提示词判断，Git 提交负责版本和合并，不负责发现原始对话事件，也不验证记忆语义的真假。

源码与实测相符：双向 headless 路径仅在成功且 `stop_reason=end_turn` 后追加 transcript、检查触发条件；launcher 构造 payload、父记忆快照和独立工作树，再启动 reflection 子 Agent；子 Agent 使用单独的模型上下文和受限工具。参考固定源码快照：[一轮结束后的入口](https://github.com/letta-ai/letta-code/blob/2b95889/src/headless.ts)、[触发判断](https://github.com/letta-ai/letta-code/blob/2b95889/src/cli/helpers/post-turn-reflection.ts)、[transcript 与 payload](https://github.com/letta-ai/letta-code/blob/2b95889/src/cli/helpers/reflection-transcript.ts)、[后台运行及合并](https://github.com/letta-ai/letta-code/blob/2b95889/src/cli/helpers/reflection-launcher.ts)、[reflection 系统提示词](https://github.com/letta-ai/letta-code/blob/2b95889/src/agent/subagents/builtin/reflection-v2.md)。

**接入边界与结论**：这次只实测 Letta Code 自身，没有让 Codex 经 MCP 或 A2A 向 Letta 发送消息，也没有验证 Letta 服务端所有部署形式或某组 MCP 工具的 description。Codex 不会因“发现一个 Letta 服务”便自动把完整 session 交出去；接入方需要明确决定发送原始消息、摘要还是提取结果，何时调用工具或 API，以及如何处理返回内容。实测可借鉴的机制是“原始消息与提炼记忆分存、后台 Agent 对照旧记忆做最小修订、提交后在下一轮编入上下文”；它没有证明自己能推断并验证用户的隐含思考过程。Letta 专项调研到此收尾，后续只在设计本项目的用户理解假设及证据更新流程时引用这些已核对机制。
