# Graphiti：会话接入、episode 与检索

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

Graphiti 是接收数据并维护时序知识图谱的组件，不会自行监听 Codex 或其他 Agent 的会话。采集、写入、读取是不同环节：自建 Agent 可在对话程序中直接取得消息，通过 Python SDK 的 `add_episode()` 写入；Codex 这类成品 Agent 则需要先用 Hook 等 AI 工具提供的事件机制采集，再由独立后端写入 Graphiti。Graphiti 的 MCP Server 提供 `add_memory` 和图谱搜索等工具，但连接 MCP 本身不会自动转发每一轮原始会话；是否调用工具由接入方决定。当前 MCP Server 在官方文档中标为实验性实现。

对本项目，若试用 Graphiti，最直接的链路是 `Codex → 现有 Hook → 原始 JSONL → 后端读取器 → Graphiti SDK`。Hook 继续快速落盘，图谱处理在后台进行；需要让 Codex 使用图谱时，再考虑通过 MCP 查询或由接入层提供相关上下文。现有 `UserPromptSubmit`/`Stop` 只给出用户提示和最近助手回复，不能据此声称 Graphiti 得到了完整会话或工具轨迹。

Graphiti 的输入单位是一次数据摄入事件，称为 *episode*。调用 `add_episode()` 时传入 `name`、字符串 `episode_body`、`source`、`source_description` 和 `reference_time`；`source` 可为 `text`、`message` 或 `json`。`message` 的内容按 `角色或姓名: 消息` 组织，既可包含单条消息，也可包含多轮对话。为避免把用户发言与助手解释混为同一来源，DistillAI 更适合一条消息对应一个 episode，并保留原始 JSONL 作为采集记录。

保存后的 `EpisodicNode` 主要包含 `uuid`、`name`、`group_id`、`source`、`source_description`、`content`、`created_at`、`valid_at` 和相关实体边。写入时的 `episode_body` 成为 `content`，`reference_time` 成为 `valid_at`，而 `created_at` 是摄入时间。这里的 `valid_at` 表示原始事件发生时间，不表示某个用户观点已被验证。Graphiti 从 episode 提取实体与关系，并保留它们到原始 episode 的来源关联；它不能直接判定用户理解了什么。

参考：[Graphiti 添加 episode](https://help.getzep.com/graphiti/core-concepts/adding-episodes)、[EpisodicNode 源码](https://github.com/getzep/graphiti/blob/main/graphiti_core/nodes.py)、[Graphiti MCP Server](https://help.getzep.com/graphiti/getting-started/mcp-server)、[Codex Hooks](https://learn.chatgpt.com/docs/hooks)。

## Graphiti 的提取、检索与上下文回注（2026-09-30）

调用方决定何时提交 episode，Graphiti 在处理已提交的内容时调用 LLM 提取实体与事实、匹配已有节点并处理关系的时间变化。实体类型可使用默认提取方式，也可由接入方定义；“节点匹配”是判断新提到的实体是否对应图中已有实体，不等于从关键词中直接确定用户理解程度。episode 保留输入内容及来源关联，提取出的图谱节点和事实是派生结果。处理新 episode 时可以利用近期 episode 帮助消解指代，但这不是对所有跨会话指代都能正确识别的保证，也不要求改写原始 episode。

Graphiti 提供 `add_episode()` 写入与 `search()` 检索。检索结合语义相似度、BM25 关键词匹配，也可按图中节点距离重排，返回相关事实或节点；它不负责把结果自动放入正在运行的聊天模型上下文。何时检索、选取几条、如何标注来源并作为参考材料传入前台，都由接入应用决定。

| 接入方式 | 谁触发写入和检索 | 记忆如何进入前台上下文 |
| --- | --- | --- |
| 自建应用调用 Graphiti SDK | 应用代码按会话事件或自身策略调用；Graphiti 内部仍可使用 LLM 完成提取 | 应用在调用前台模型前检索并传入结果 |
| 给现有 Agent 注册 Graphiti MCP | Agent 可调用 `add_memory`、`search_memory_facts`、`search_nodes` 等工具；仅注册工具不保证每轮调用 | 搜索结果作为工具返回内容供模型使用 |
| Hook 配合后台程序 | AI 工具 Hook 触发采集或检索，后台调用 SDK 或 MCP | 由 AI 工具支持的上下文回注机制传入；Hook 本身不是 Graphiti 的组成部分 |

因此，SDK 与 MCP 是接入接口的选择；更重要的差异是调用时机由应用控制，还是交给前台模型选择。自建 Agent 也可以调用 MCP，现有 AI 工具也可以主动使用 SDK。对于 DistillAI，现有 Hook 已能采集原始事件；若希望静默、稳定地写入和检索，应由后台编排流程触发，不能只注册 MCP 后假定模型会主动调用。检索回注和后台图谱处理目前都尚未实现。

参考：[Graphiti 概览](https://help.getzep.com/graphiti/getting-started/overview)、[添加 episode](https://help.getzep.com/graphiti/core-concepts/adding-episodes)、[搜索图谱](https://help.getzep.com/graphiti/working-with-data/searching)、[Graphiti MCP Server 工具列表](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md)。
