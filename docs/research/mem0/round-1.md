# Mem0：采集、提取与回注

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

Mem0 的输入输出流程与预想中的 DistillAI 高度相似：采集交互，在后台处理并持久保存，再按当前任务检索并回注前台 Agent。现阶段已足以作为流程参考，后续重点转向用户理解假设的形成与验证。尚未决定把 Mem0 作为项目依赖；向量库、批次阈值和排序参数留到实现时选择。

## 整体流程与 Codex 接入

Mem0 有读取和写入两条路径。采集每轮对话，不等于每轮都立即调用提取模型；后台可在积累一定材料或生命周期事件发生时批量处理。

```text
读取：用户问题 → 检索相关记忆 → 加入 Codex 上下文 → Codex 回答
写入：问题、回复及可采集的工具结果 → 待处理记录
     → 后台使用提取提示词调用 LLM → 去重并追加记忆 → 供后续检索
```

| 接入环节 | Mem0 的做法 | 对 DistillAI 的参考 |
| --- | --- | --- |
| 自动采集 | Codex 插件通过 `UserPromptSubmit`、`Stop` 等 Hook 记录交互，并在后台批量提交 | 复用现有 Hook 与原始 JSONL，让语义分析独立运行 |
| 自动回注 | 在首次符合条件的用户提示时检索，脚本通过 `hookSpecificOutput.additionalContext` 返回记忆，由 Codex 加入下一次模型请求 | 可在回答前提供相关证据与必要的验证意图；选择何时触发需要另行设计 |
| 主动查询 | Codex 可调用 `search_memories`，结果作为 MCP 工具输出进入上下文 | 允许前台 Agent 按任务需要读取后台知识与判断 |
| 写入触发 | 自建应用可调用 SDK `add()`；MCP 工具可由模型选择调用；插件 Hook 也可直接请求 API | 区分模型自主调用与 AI 工具事件触发；仅连接 MCP 不会自动采集对话 |

官方 Mem0 Codex 插件的自动检索不等于每轮自动检索，其本地 MCP 服务主要提供搜索，自动写入走 Hook。不同 AI 工具插件的触发策略不同，不能把某个插件的行为推广到所有接入方式。Hook 回注无需用户手动粘贴；Codex 将 `additionalContext` 作为额外开发者上下文处理，接入层应明确区分应用规则与采集到的参考数据。

参考：[Codex 接入文档](https://github.com/mem0ai/mem0/blob/main/docs/integrations/codex.mdx)、[Codex Hooks 协议](https://learn.chatgpt.com/docs/hooks)。此前核对的固定源码快照为 [`94c3fe9`](https://github.com/mem0ai/mem0/tree/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd)，其中可追查 [Hook 注册](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/integrations/codex-plugin/hooks/hooks.json)、[检索回注](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/integrations/codex-plugin/core/hook_runner.py#L62-L94)与[后台提交](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/integrations/codex-plugin/core/memory_core.py#L1962-L2021)。

## 提取规则与模型分工

“值得记住”主要通过预先编写的提示词和 LLM 判断来决定。本次核对的开源主路径使用 `ADDITIVE_EXTRACTION_PROMPT`，输入新消息、近期对话、相关旧记忆和自定义指令，输出结构化记忆；没有独立的长期价值评分门槛。默认偏向保留具体事实、偏好、计划、经历和建议，跳过客套及重复信息，拿不准时倾向于提取。它保存的内容不自动代表用户理解了什么。

提取提示词用于后台独立的模型请求，不会直接注入正在与用户对话的 Codex。开源 Mem0 可以单独配置 provider、模型和凭据；即使与前台选用同一种型号，也仍有独立上下文。官方 Codex 插件连接 Mem0 云服务，由云端负责提取，本次资料未确认其具体模型或私有提示词。后端只能读取接入层传入的材料，不会自动获得 Codex 的全部上下文。

参考：[完整提取提示词](https://github.com/mem0ai/mem0/blob/main/mem0/configs/prompts.py#L418-L790)、[动态输入拼装](https://github.com/mem0ai/mem0/blob/main/mem0/configs/prompts.py#L853-L895)、[独立 provider 配置](https://github.com/mem0ai/mem0/blob/main/mem0/llms/configs.py)。这些链接跟随上游 `main`，实施时再固定参考提交。

## 存储、检索和记忆维护的关键结论

以下描述本次核对的开源主路径，作为理解实现方式的记录，不直接推定云服务的内部实现。

| 问题 | 已确认的机制及边界 |
| --- | --- |
| 是否使用 RAG | 检索记忆再供 Agent 回答符合检索增强的使用方式；写入前还增加了 LLM 提取整理步骤 |
| 如何切分 | 默认将 LLM 生成的一条完整记忆作为存储与检索单位，保留必要背景；并非按固定 token 数切原始对话。长对话分批提交与记忆条目的划分是两个环节 |
| 如何存储与检索 | 默认向量存储为 Qdrant，可替换 provider；对记忆文本生成 embedding 并保存文本、元数据。检索以向量召回为基础，可结合 BM25、实体加分和可选重排，具体能力取决于配置 |
| 如何去重 | LLM 比较召回的旧记忆与新消息，尽量跳过语义重复；程序再用文本哈希过滤本批及召回范围内的完全相同内容。它不是全库无重复保证 |
| 如何更新 | 当前默认 `add()` 去重后追加，不自动覆盖或删除旧记忆；显式 `update()` 根据指定 ID 替换文本并更新索引、记录历史。`infer=False` 会绕过语义提取，不能指望它完成同样的去重 |
| 如何处理矛盾 | 新内容可能表示事实变化、适用条件变化、历史误记或证据不足。追加或关联新旧记录不等于已经判定哪条有效；应用仍需决定如何处理 |

参考：[写入行为](https://docs.mem0.ai/core-concepts/memory-operations/add)、[更新行为](https://docs.mem0.ai/core-concepts/memory-operations/update)、[提取与去重实现](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py#L839-L948)、[存储配置](https://github.com/mem0ai/mem0/blob/main/mem0/vector_stores/configs.py)、[检索实现](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py#L1495-L1549)。仓库中保留的 `ADD / UPDATE / DELETE / NONE` 提示词不能代表当前默认写入行为，应以实际调用路径为准。
