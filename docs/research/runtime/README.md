# 后台运行技术调研

本专题为 Issue #4 提供后台执行选型依据，覆盖 Agent、本地 LLM、搜索、写沙箱、Windows、文件恢复和本机接口。第 4 轮经用户授权下载 DeepSeek Harness、Pi、Hermes 最新默认分支源码，按下面路由核对；未安装依赖或运行集成。

| 轮次 | 范围与结论 | 记录 |
| --- | --- | --- |
| 第 1 轮，2026-10-09 | Pi 支持 Python 经 JSONL RPC 控制；Pi 不提供权限隔离。MXC 提供 Windows ProcessContainer 和 Node SDK，需检查实际策略及隔离层；Anthropic srt 的公开说明采用 macOS / Linux 原语。本机 Windows 25H2 26200.9457 达到 MXC 文档列出的进程隔离最低版本，尚未 probe。任意命令与同期用户编辑使原地回退复杂，建议任务副本后校验写回。 | [核对过程与依据](round-1.md) |
| 第 2 轮，2026-10-10 | 用户选择 Node / TypeScript + Pi SDK 后核对资源加载、MXC 分进程、Graphology、MCP v2、Hook / compact、文件句柄与搜索路线；Koffi 窄适配及独立搜索 API 为提案。没有安装或集成实测。 | [收尾依据与待验证](round-2.md) |
| 第 3 轮，2026-10-10 | 用户重新开放框架 / 语言选择，沙箱只限写。DeepSeek / Pi 优先对照；补核 Hermes 官方 Python Library 与当前原生 Windows 支持，保留 Python 候选，不以旧快照降低优先级。框架及语言未选，搜索服务延后。 | [七框架比较、依据与边界](round-3.md) |
| 第 4 轮，2026-10-10 | 用户聚焦 DeepSeek / Pi / Hermes 并新增本地 LLM 需求；下载最新源码后按 SDK、搜索、写隔离、控制范围、安装负担、预算 / 中断及语言比较。DeepSeek 有现成 Windows 写隔离但仍需收紧边界；Pi 需补搜索与写沙箱；Hermes 有正式 Library，文件写保护不覆盖 Shell，64K 检查有 LM Studio 例外。三个候选均保留，由用户选型。 | [三项目同维度结果与固定 HEAD](round-4.md) |

当前正式维护入口为 [统一 Design](../../spec/v0.1.0/4-initial-development/design.md)。2026-10-12 用户确认 Hermes Python Library / `AIAgent`、Python 控制层 / Hook / MCP 与独立任务执行进程；2026-10-13 [总 Plan](../../spec/v0.1.0/4-initial-development/plan.md)及模块草案已创建，环境 / 写隔离 / 文件句柄 / Desktop 仍待实测，搜索后端按用户要求延后。任务副本与恢复保留；沙箱只限写，读取不限制。Pi / TS 与原 [M01 技术方案](../../spec/v0.1.0/4-initial-development/modules/01-runtime/technical-proposal.md)保留历史依据，不能把旧权限表述或语言候选当最新要求。

## 本地源码路由

| 对象 | 本地目录 | 入口 |
| --- | --- | --- |
| DeepSeek Harness，最新默认分支快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness` | `docs/architecture.md`；`packages/sdk/client/`、`packages/sdk/server/`、`python/sdk/`；`packages/llm/llm-pi-ai/`；`packages/bundle/base/`；`packages/web/`、`packages/fs/`、`packages/sandbox/` |
| Pi，最新默认分支快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/pi` | `packages/coding-agent/docs/`、`examples/sdk/`、`src/core/sdk.ts`、`model-runtime.ts`、`agent-session.ts`；`packages/agent/`、`packages/ai/` |
| Hermes，最新默认分支快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent` | `website/docs/guides/python-library.md`、`website/docs/integrations/providers.md`、`website/docs/user-guide/security.md`；`run_agent.py`、`agent/`、`tools/`、运行环境及依赖配置 |
| Codex | `E:/JourneyIntoAI/DL_and_LLM/projects/codex-main` | `sdk/typescript/README.md` 与 `src/exec.ts` / `threadOptions.ts`；`sdk/python/README.md`；`codex-rs/model-provider-info/src/lib.rs`；`codex-rs/windows-sandbox-rs/src/elevated_impl.rs`、`lib.rs`、`token.rs` |
| Hermes，旧历史快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent-main/hermes-agent-main` | 第 3 轮历史核对；`README.md`、`pyproject.toml`、`run_agent.py`；`website/docs/guides/python-library.md`；`tools/web_tools.py`、`terminal_tool.py`、`environments/local.py` |

旧 Codex / Hermes 快照未发现 Git 元数据，文件 SHA256 与版本差异见第 3 轮。2026-10-10，用户授权下载三个重点候选的最新源码，使用上表新目录，不覆盖旧副本；实际分支、完整 Git HEAD 和发布版本见[第 4 轮](round-4.md#下载与核对版本)。缺失或版本不足时报告，不自行改用在线源码替换；官方当前公开接口与本地快照分开记录。
