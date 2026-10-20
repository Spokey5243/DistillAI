# 后台运行技术调研

当前范围调整（2026-10-14）：用户将 OS 写隔离延至后续独立 Issue，本次不采用 MXC / restricted token 或继续沙箱 stdio 模型转发验证。四轮调研和此前探针保留历史证据，写隔离失败不再阻塞当前 G1；普通任务进程的模型调用、计数、停树、副本与冲突安全写回继续实施。当前范围见 [统一 Design M01](../../spec/v0.1.0/4-initial-development/design.md#agent-sandbox)，后续 Issue 尚未创建。

本专题为 Issue #4 提供后台执行选型依据，覆盖 Agent、本地 LLM、搜索、写沙箱、Windows、文件恢复和本机接口。第 4 轮经用户授权下载 DeepSeek Harness、Pi、Hermes 最新默认分支源码，按下面路由核对；未安装依赖或运行集成。

| 轮次 | 范围与结论 | 记录 |
| --- | --- | --- |
| 第 1 轮，2026-10-09 | Pi 支持 Python 经 JSONL RPC 控制；Pi 不提供权限隔离。MXC 提供 Windows ProcessContainer 和 Node SDK，需检查实际策略及隔离层；Anthropic srt 的公开说明采用 macOS / Linux 原语。本机 Windows 25H2 26200.9457 达到 MXC 文档列出的进程隔离最低版本，尚未 probe。任意命令与同期用户编辑使原地回退复杂，建议任务副本后校验写回。 | [核对过程与依据](round-1.md) |
| 第 2 轮，2026-10-10 | 用户选择 Node / TypeScript + Pi SDK 后核对资源加载、MXC 分进程、Graphology、MCP v2、Hook / compact、文件句柄与搜索路线；Koffi 窄适配及独立搜索 API 为提案。没有安装或集成实测。 | [收尾依据与待验证](round-2.md) |
| 第 3 轮，2026-10-10 | 用户重新开放框架 / 语言选择，沙箱只限写。DeepSeek / Pi 优先对照；补核 Hermes 官方 Python Library 与当前原生 Windows 支持，保留 Python 候选，不以旧快照降低优先级。框架及语言未选，搜索服务延后。 | [七框架比较、依据与边界](round-3.md) |
| 第 4 轮，2026-10-10 | 用户聚焦 DeepSeek / Pi / Hermes 并新增本地 LLM 需求；下载最新源码后按 SDK、搜索、写隔离、控制范围、安装负担、预算 / 中断及语言比较。DeepSeek 有现成 Windows 写隔离但仍需收紧边界；Pi 需补搜索与写沙箱；Hermes 有正式 Library，文件写保护不覆盖 Shell，64K 检查有 LM Studio 例外。三个候选均保留，由用户选型。 | [三项目同维度结果与固定 HEAD](round-4.md) |

当前正式维护入口为 [统一 Design](../../spec/v0.1.0/4-initial-development/design.md)。2026-10-12 用户确认 Hermes Python Library / `AIAgent`、Python 控制层 / Hook / MCP 与独立任务执行进程；2026-10-13 用户批准当前 Design / Prompt、[总 Plan](../../spec/v0.1.0/4-initial-development/plan.md)及八模块 Plan，进入 M01 能力验证。PM 应用环境的合成 AIAgent 流式工具调用及 503 恢复通过，完整开发激活失败；Job 停树、文件句柄及 MXC 文件边界取得部分实测，MXC 本机模型转发 loopback 未通，G1 保持未通过。细节见 [M01 执行记录](../../spec/v0.1.0/4-initial-development/modules/01-runtime/plan.md#2026-10-13task-1-开始执行)，不是新增调研轮次；真实模型、完整写隔离及 Desktop 仍待验证，搜索后端按用户要求延后。任务副本与恢复保留；沙箱只限写，读取不限制。Pi / TS 与原 [M01 技术方案](../../spec/v0.1.0/4-initial-development/modules/01-runtime/technical-proposal.md)保留历史依据，不能把旧权限表述或语言候选当最新要求。

2026-10-14 当前验证状态：官方 PM 应用准备退出 0，开发测试环境的 activate 失败保留；`deepseek-flash` 真实流式 echo 工具往返、16 / 17 次与重启预算、普通任务和无工具筛选并发通过。用户批准的 restricted token / Low integrity / Job 候选通过明确用户 ACL 合成目录的写 / 网络 / 停树 / 权限撤销，但 OWNER RIGHTS 读取反例影响当前 PM 底层 Python，Hermes 沙箱内启动失败。G1 未通过；MXC + stdio 模型转发为下一待批准验证候选，读取要求保持。细节见 [M01 2026-10-14 记录](../../spec/v0.1.0/4-initial-development/modules/01-runtime/plan.md#2026-10-14模型预算与替代隔离验证)；这是实施验证，不新增研究轮次或记为完整产品集成。

## 本地源码路由

2026-10-15 最新实施状态：修订 1 的 G1 已通过，固定本地 Hermes `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed` / 官方 PM 应用环境 / MCP 2.0.0；普通停树、真实模型预算及文件提交窗口取得证据，存储与 Win32 产品契约已开始实施。OS 写隔离继续延期，Desktop / 产品 MCP、后台启动及搜索服务尚待后续验收。版本和命令见 [M01 当前实施记录](../../spec/v0.1.0/4-initial-development/modules/01-runtime/plan.md#2026-10-15g1-冻结及存储实施)；不是新增调研轮次。

同日产品运行层继续验证：直接 AIAgent 子进程通过产品转发 / Job / Store 完成六场景、41 次合成生成，文件和 terminal 结果由程序发布；503 恢复计三次，第 16 次可成功，第 17 次未到 provider。Check / Serve / Stop 使用真实 PM 解释器跨命令通过，62 项标准库契约在两个解释器通过。Mcp / Web 与业务模块继续实施，尚不作为完整产品 / Desktop 验收；不新增研究轮次或扩展隔离路线。

| 对象 | 本地目录 | 入口 |
| --- | --- | --- |
| DeepSeek Harness，最新默认分支快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness` | `docs/architecture.md`；`packages/sdk/client/`、`packages/sdk/server/`、`python/sdk/`；`packages/llm/llm-pi-ai/`；`packages/bundle/base/`；`packages/web/`、`packages/fs/`、`packages/sandbox/` |
| Pi，最新默认分支快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/pi` | `packages/coding-agent/docs/`、`examples/sdk/`、`src/core/sdk.ts`、`model-runtime.ts`、`agent-session.ts`；`packages/agent/`、`packages/ai/` |
| Hermes，最新默认分支快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent` | `website/docs/guides/python-library.md`、`website/docs/integrations/providers.md`、`website/docs/user-guide/security.md`；`run_agent.py`、`agent/`、`tools/`、运行环境及依赖配置 |
| Codex | `E:/JourneyIntoAI/DL_and_LLM/projects/codex-main` | `sdk/typescript/README.md` 与 `src/exec.ts` / `threadOptions.ts`；`sdk/python/README.md`；`codex-rs/model-provider-info/src/lib.rs`；`codex-rs/windows-sandbox-rs/src/elevated_impl.rs`、`lib.rs`、`token.rs` |
| Hermes，旧历史快照 | `E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent-main/hermes-agent-main` | 第 3 轮历史核对；`README.md`、`pyproject.toml`、`run_agent.py`；`website/docs/guides/python-library.md`；`tools/web_tools.py`、`terminal_tool.py`、`environments/local.py` |

旧 Codex / Hermes 快照未发现 Git 元数据，文件 SHA256 与版本差异见第 3 轮。2026-10-10，用户授权下载三个重点候选的最新源码，使用上表新目录，不覆盖旧副本；实际分支、完整 Git HEAD 和发布版本见[第 4 轮](round-4.md#下载与核对版本)。缺失或版本不足时报告，不自行改用在线源码替换；官方当前公开接口与本地快照分开记录。
