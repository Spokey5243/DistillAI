# Honcho 调研

| 元信息 | 地址或范围 |
| --- | --- |
| 本地仓库 | `E:\JourneyIntoAI\DL_and_LLM\projects\honcho`；`E:\JourneyIntoAI\DL_and_LLM\projects\codex-honcho`（2026-10-04 经用户授权下载，仅作源码核对） |
| GitHub | [plastic-labs/honcho](https://github.com/plastic-labs/honcho)；[plastic-labs/codex-honcho](https://github.com/plastic-labs/codex-honcho) |
| 首轮核对范围 | Honcho 服务与 Codex 接入的公开文档、代码；不代表已接入 DistillAI |
| 首轮主要核对时间 | 2026-09-30 |

## 各轮调研简短结论

### 第 1 轮 · 已完成

- 原始 Message、明确事实、会话摘要与进一步推断分别处理；Deriver 主要提取明确事实，Dreamer 承担更高层的推断和整理。
- codex-honcho 用 Hook、队列和游标交付材料，并通过 Hook 回注或 MCP 查询使用后端结果；采集前的筛选与工具摘要会损失部分原始信息。
- 后台用户表征是重要参考；本轮核对的链路未展示 DistillAI 所需的完整竞争假设验证闭环。

详细过程、源码与实测依据：[第 1 轮调研记录](round-1.md)。

### 第 2 轮 · Hook 采集与本地文件核对完成

- 实际注册五个 Hook、对应四个处理函数：`SessionStart` / `UserPromptSubmit` 负责上下文，`PostToolUse` 负责工具摘要，`Stop` / `PreCompact` 共用 writeback。
- 配置未设置 `async: true`；writeback 在 Hook 进程内先采集，再 `await flush()` 上传。函数声明为 `async` 或注释称后台上传，不代表 Codex 无需等待 Hook。
- rollout 每次全量读取并筛选文本，再按已捕获的消息数量取增量；本地 JSONL 队列、捕获游标与 `.sent` 发送进度分别维护。
- DistillAI 已在 Discussion 确认复用 Honcho 的队列、`.sent`、交付锁与消息计数游标，按 AI 工具组织 `~/.distillAI`，分别表达采集、交付和后台处理；本轮早期自定义文件布局已撤下。Hook 同步短时落盘、交付触发与接收确认契约继续讨论，当前决定以 Discussion 为准。

详细源码、文件名与伪代码：[第 2 轮核对](round-2.md)。本轮只核对源码和官方文档，未安装或运行 Honcho 集成。

## 本地源码路由

| 仓库 | 本轮核对提交 | 入口 |
| --- | --- | --- |
| Honcho | `9d6fe8ca5dc666b99ef04bc00047fea4ca675017` | `src/routers/messages.py`、`src/models.py`、`src/deriver/enqueue.py`、`src/deriver/queue_manager.py` |
| codex-honcho | `c17cbb2b4c7cf12172213345ae4c0d2a093d707b` | `src/connectors/codex.ts`、`src/hooks/`、`src/transcript/codex.ts`、`src/queue.ts`、`src/cursor.ts`、`src/cache.ts`、`src/config.ts` |

后续核对直接读取上述本地路径；下载的仓库保持独立，不接入 DistillAI 插件或运行流程。
