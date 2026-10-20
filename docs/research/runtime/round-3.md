# 后台运行技术第 3 轮：七个 Agent 框架比较

本文件保留七框架的历史比较。用户随后缩小范围并授权下载最新源码；DeepSeek Harness / Pi / Hermes 的当前接口、版本、写隔离及本地 LLM 判断以[第 4 轮](round-4.md)为准。其他四个项目未被用户正式排除。

2026-10-10，Issue #4，状态：`exploring`。用户要求基础 Agent 能力、web search 与 sandbox，在满足产品需求的前提下尽量薄；比较 DeepSeek Harness、Claude Agent SDK、Codex SDK、OpenAI Agents SDK、Pi、Deep Agents、Hermes，再决定 TS / Python。此前 Node / TypeScript + Pi SDK 选择因此重新开放。搜索方法和供应商延后确认，模型 API key 仍由用户填写本地配置。随后用户明确沙箱只限制写入，不要求读取隔离；本报告及统一 Design 采用此最新口径。

本轮核对官方文档，并读取已有 Codex / Hermes 本地源码快照；未安装、下载、更新、运行候选或修改主机 ACL。以下为选型依据，不是集成验收。业务要求以[统一 Design](../../spec/v0.1.0/4-initial-development/design.md)为准。

本报告随统一 Design 做一次性文档校验：21 份 Markdown 的本地相对链接 / 锚点、编码 / 围栏 / 空白检查无报错，八模块与九组 Prompt 完整性及合成 JSON 解析通过。该证据不替代框架、搜索或 Windows 写沙箱实测。

## 比较口径

“薄”同时看必须引入的运行时和需要自己补写的代码。一个很薄的 SDK 如果背后运行完整 CLI，不能算很薄的执行引擎；只有 Agent loop 而缺少搜索、命令隔离，也不能算最少接入工作。没有用仓库大小、工具数量或未经实测的速度排名。

| 来自 Design 的要求 | 对框架的实际要求 |
| --- | --- |
| M03 episode、M04 知识、M05 认知维护 | 工具循环、文件读取 / 编辑、结构化结果、具体校验错误后修正；程序保持角色证据、字段归属与来源契约 |
| M06 外扩 | 搜索找到来源，读取原文核查；保留 URL、读取时间和实际取得内容，摘要不能冒充全文 |
| M07 准备与筛选 | 准备任务使用图 / 文件工具；本轮筛选可以是无工具的一次模型调用，不需要另造完整 Agent |
| M01 任意命令、必要 Python / Shell 和文件工具 | 写隔离涵盖文件工具及整个子进程树；允许写任务副本 / 临时目录，禁止改动原始输入、原文件和程序状态；不要求 OS 限制读取 |
| M01 配置与取消 | 默认资源发现可关闭；不继承个人登录、会话、自动记忆和执行配置；权限收紧后停止进程树并阻止写回 |
| M01 调用额度 | 实际模型请求、重试、自动压缩、修正均计数，恢复不重置；max_turns / max_iterations 名称本身不证明满足这一口径 |
| 程序控制的后台 | 一个业务写名额、独立注入名额、任务副本校验提交、版本冲突与恢复；这些继续由 DistillAI 管理 |
| 本地 Windows 常驻 | 当前优先原生 Windows；Docker、WSL 或云沙箱是需要另行选择的执行平台，不自动引入 |

当前没有固定模型供应商或 API 协议。“支持兼容 endpoint”不代表支持所有供应商，也不代表能使用该供应商的托管搜索工具。程序不主动把凭证写进 Prompt、历史和 Web 输出；沙箱无需阻止读取本机文件。以下写隔离与业务提交控制分开核对。

## 七个候选总览

表中的“现成”指公开接口或已有快照展示的能力，不表示无需配置、凭证或部署。逐项来源与限制见后文。

| 框架 | 直接接入语言 / 运行形态 | 搜索与网页读取 | 沙箱及原生 Windows 差距 | 厚度与本项目判断 |
| --- | --- | --- | --- | --- |
| DeepSeek Harness | TS / Python SDK；启动插件化 dsh 子进程 | 完整 profile 有 web_search / web_fetch，可选供应商 | 原生 Windows ACL 命令写隔离 + 文件工具写限制；符合只限写方向，仍有链接 / ACL 边界待验 | 模块化，完整能力需完整 profile；sdk-minimal 不含 web / sandbox。现成能力优先验证候选，开发者预览 |
| Claude Agent SDK | TS / Python；完整 Claude Code 引擎 | 内置 WebSearch / WebFetch | 内置沙箱只保护 Shell；原生 Windows 无该沙箱，文件工具 / MCP / hooks 在外 | 接入功能全，但引擎与供应商约束较强；不列当前首选 |
| Codex SDK | TS CLI 包装；当前官方 Python app-server SDK | 引擎有 cached / live 等搜索模式 | 本地源码有 Windows 命令沙箱；全部写工具与子进程边界还需验证 | SDK 薄、Rust 引擎完整；模型协议及请求计数控制是主要门槛，保留条件候选 |
| OpenAI Agents SDK | TS / Python，直接库；SandboxAgent 可选 | 托管 WebSearchTool；换供应商时可注册独立搜索工具 | SandboxAgent 对接 Docker / 云提供商；官方 Windows 路线不是 UnixLocal | 核心较轻、现成能力多；接受 Docker / 托管平台时优先评估 |
| Pi | TS SDK 直接库；Python 通过 CLI / RPC | 默认文件 / 命令工具不含等价通用 web search，需注册 | 不提供 OS 沙箱，需 MXC 等外部隔离整个执行器 | 核心薄、资源边界可显式接管；原生 Windows 路线优先验证，但需补两项适配 |
| Deep Agents | TS / Python；LangChain + LangGraph harness | 注册供应商托管工具或自定义搜索 | 文件 backend 不等于 OS 隔离；可接沙箱服务，无已核对的原生 Windows MXC 后端 | 功能较多，持久状态 / 规划与现有 worker 重叠；当前不优先 |
| Hermes Agent | 官方支持 Python Library，直接嵌入 AIAgent，不需 CLI | 自带多搜索 / 抓取供应商适配，工具集可选择 | 旧快照 local 无 OS 写隔离；当前官方文档已有原生 Windows 安装，最新写后端仍待核对 | 可关闭记忆 / 上下文并选工具；不能因完整产品功能多就认定嵌入必需全部启动，保留 Python 候选 |

## 1. DeepSeek Harness

[官方架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)采用 Cordis 插件组合，提供不同 profile。TS / Python SDK 均控制 dsh 子进程，不是把全部功能直接嵌入业务进程。完整 profile 包含工具、持久化、沙箱、审批、配置与凭证等；能裁剪，但不能把 SDK 外壳的体积当运行时成本。

[web 包](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/web/README.md)提供搜索和网页获取接口，可接 Exa、Perplexity、DeepSeek 等搜索实现；网页获取不等于浏览器自动化。[LLM 包](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/README.md)有可替换供应商接口及 pi-ai 适配，并非只能调用 DeepSeek。实际模型工具协议仍需用用户配置验证。

[sandbox 包](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/README.md)有跨平台实现；[Windows ACL 后端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox-windows-acl/README.md)使用受限 token / Job 管命令，限制写入及删除，允许读取和联网。用户已明确只需写限制，这点符合需求，不再要求额外读隔离。文件工具的 [fs-sandbox](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/fs/README.md)提供 write / edit 范围约束。仍须验证两条路径的组合覆盖；文档说明目录 ACL 修改会持续存在、硬链接有别名边界，不能只凭 mode 名称宣告所有写路径均已通过。

[sdk-minimal](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/sdk-minimal/README.md)只保留基础命令 / 工作目录与会话路径，去掉 web、sandbox、文件工具、Skill、压缩等，使用 danger-full-access，要求外部隔离。采用它仍需自己补搜索和沙箱。[Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)要求显式 DSH_HOME，可避免个人默认目录发现；但不能据此认为全部资源与工具已隔离。

[完整 SDK profile](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/sdk-app/README.md)通过 stdio JSON-RPC 接入，继承 base 工具和策略，没有 GUI；关闭了模型生成会话标题，配置变化需重启。其 base 会话投影 / 持久化与 DistillAI 业务记录仍应分开，不能把框架会话日志当提交完成。

判断：按只限制写入的需求，它是现成功能最值得优先验证的候选之一，尤其是原生 Windows。使用无 GUI 的完整 SDK profile 并裁掉不需要的插件，比 sdk-minimal 后重补全部能力更合理；实际可裁剪范围仍需验证。[开发者预览状态](https://github.com/deepseek-ai/deepseek-harness)、Windows ACL / 链接限制和全部模型请求计数，是采用前的主要问题。Windows 文档还说明受限孙进程使用 libuv 管道捕获可能失败，需检查任意命令 / 子进程兼容性。已有写隔离后不必为读取再叠加 MXC；是否需要 MXC 取决于实际写路径验证结果。

## 2. Claude Agent SDK

[官方概览](https://code.claude.com/docs/en/agent-sdk/overview)提供 TS / Python，包含 Claude Code 的工具循环、文件 / 命令、网页工具、会话、权限和 MCP。它适合复用完整执行产品，业务代码较少，但不是仅有几个 Agent 原语的小库。官方接入以 Anthropic API 及支持的云平台为主，不能据任意 base_url 推断所有模型兼容。

[沙箱文档](https://code.claude.com/docs/en/sandboxing)明确只包住 Bash / PowerShell / Monitor 命令及其子进程；文件工具、MCP 和 hooks 在外。支持 macOS、Linux、WSL2，原生 Windows 命令无该沙箱。要实现 M01 仍须把完整执行器放入额外隔离环境。

[部署文档](https://code.claude.com/docs/en/agent-sdk/hosting)说明 SDK 配套 Claude Code 二进制和容器隔离方式；可以显式关闭 settings 来源，但自动记忆需要另行禁用。应设独立配置目录和任务 cwd，不能用一个空 settings 列表代替所有资源控制。

判断：若后续固定 Anthropic 并接受外部容器，这条路线可用；目前它没有为原生 Windows 免掉隔离适配，引入的完整引擎也较多，故不优先。

## 3. Codex SDK

本地 TS SDK README 与 exec.ts 显示，它是 bundled Codex CLI 的薄包装，运行流经 JSONL；threadOptions 提供 sandboxMode、网络、webSearchMode、审批及附加目录。SDK 外壳小，但仍运行完整 Rust 引擎。现有快照不能提供统一的生产版本号。

本地 model-provider-info 的 WireApi 只保留 Responses，存在 request / stream 重试参数；因此仅有 Chat Completions 兼容接口的模型不能直接视为可用。内置搜索也不能假定能随任意供应商工作。当前[官方配置](https://learn.chatgpt.com/docs/config-file/config-basic)公开 cached / indexed / live / disabled；它没有公开足够信息供本项目依赖某一内部搜索引擎。

本地 windows-sandbox-rs 存在 elevated capture、读写 roots 覆盖和受限 token 路径，说明原生 Windows 命令沙箱是真实实现。当前只核对它的写限制；尚未验证所有写文件工具、MCP、hooks 是否共用所需写策略，也未验证 SDK 取消是否终止所有子进程。读取不作为选型门槛。

版本差异：[当前官方 SDK 文档](https://developers.openai.com/codex/sdk)包含 Python `openai-codex` app-server SDK；本地 sdk/python 仍登记旧 experimental `codex-app-server-sdk` 0.2.0。此处报告差异，不更新副本，也不把本地旧接口写成当前官方发行接口。

判断：若用户模型满足其协议，且整套工具的权限与每次请求计数能受程序控制，Codex 可显著减少现成功能接入；当前不据熟悉 Codex 就优先定它。SDK 不是本项目另装旧 Codex CLI 的授权，技术验证入口仍遵守项目 Desktop 集成要求。

## 4. OpenAI Agents SDK

[核心 SDK](https://openai.github.io/openai-agents-python/)提供 Agent、Runner、工具与事件，TS / Python 均可直接嵌入。handoff、语音等能力不必启用；比完整 coding-agent 应用更便于让 DistillAI 保持调度与业务状态所有权。

[工具文档](https://openai.github.io/openai-agents-python/tools/)提供 OpenAI 托管 WebSearchTool 和 CodeInterpreterTool，后者是托管代码执行能力，不能直接代替本地任意命令沙箱。[模型接口](https://openai.github.io/openai-agents-python/models/)可接不同 Model / Provider 及兼容协议；换模型并不会让 OpenAI 托管搜索自动可用，必要时另接独立搜索 API。

当前 SDK 已提供 [SandboxAgent](https://openai.github.io/openai-agents-python/sandbox_agents/)：文件、Shell、Skill 与沙箱客户端组合，不能沿用“只有 Code Interpreter，没有通用 sandbox”的旧认识。[Python 客户端](https://openai.github.io/openai-agents-python/sandbox/clients/)包括 UnixLocal、Docker 和托管提供商；[TS 执行边界](https://openai.github.io/openai-agents-js/guides/sandbox-agents/concepts/)明确 Windows 使用 Docker 或托管提供商。UnixLocal 的工作目录、HOME 和 file API 授权不限制任意 Shell；必须依赖外部 OS 隔离。

判断：若接受 Docker / 托管沙箱，它最符合“较轻核心 + 现成能力”，值得优先；保持原生 Windows / MXC 时，仍要适配沙箱客户端或隔离整个执行器。SDK 的 memory、自动压缩和 tracing 应按本项目数据边界显式配置；不让它们替代 JSON 权威记录。具体请求 / 重试计数仍须验证。

## 5. Pi

[当前 SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)为 `@earendil-works/pi-coding-agent`，直接提供 TS AgentSession；可指定 ModelRuntime、SettingsManager、SessionManager、ResourceLoader 及工具。默认发现资源并持久会话，产品需要接管这些边界。当前文档还区分低层 agent_end 与最终 agent_settled：自动恢复 / 排队工作可能在前者后继续。

[默认工具](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md)提供读写编辑和命令等能力，不自动提供等价通用 web search。搜索与网页读取需要注册工具；OS 沙箱需外部执行层。SDK 内存会话 / 自定义资源加载降低与个人会话、配置混用的风险，取消 API 仍不等于 OS 进程树停止。

[跨语言集成](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli-integration.md)提供子进程方式。Python 可以控制 Pi，但会引入 RPC 与 TS 运行时；直接 SDK 采用 TS 最省连接层。当前 MCP 是可加载扩展，不能把“支持 MCP”当产品图查询、反馈关联与权限协议都已实现。

判断：Pi 是最值得保留的薄核心候选。代价清楚：必须实现搜索 / 网页工具，以及外部写隔离；不能称为开箱即用满足三项。其最终优势取决于这两块适配是否比采用 DeepSeek 完整 profile 更少。MXC 是已有候选，不再为了额外读限制要求它必经。

## 6. Deep Agents

[Python 概览](https://docs.langchain.com/oss/python/deepagents/overview)与 [TS 概览](https://docs.langchain.com/oss/javascript/deepagents/overview)均有对应实现。建立在 LangChain / LangGraph 之上，组合规划、文件系统、子 Agent、长上下文等能力；比基础 Agent loop 多一层 harness。这里没有把 JS 版误记成 Python 专属。

[后端文档](https://docs.langchain.com/oss/python/deepagents/backends)区分状态内文件、真实文件和命令后端。FilesystemBackend 的 root / virtual_mode 是文件工具范围，不是完整 OS 边界；LocalShellBackend 直接运行本地命令。[沙箱集成](https://docs.langchain.com/oss/python/deepagents/sandboxes)可接外部服务，但本轮未核对到原生 Windows MXC 适配。[快速开始](https://docs.langchain.com/oss/python/deepagents/quickstart)展示注册托管搜索或自定义搜索，不代表默认就有独立搜索服务。

判断：适合希望直接采用规划、子 Agent 与持久执行体系的项目。DistillAI 已有 worker、任务状态和提交恢复，首版会出现职责重叠；当前不需要为了工具循环增加这些层。

## 7. Hermes Agent

用户追问 SDK 后补核：Hermes **有官方支持的程序化库接入**。本地 `website/docs/guides/python-library.md` 与[当前官方 Python Library 文档](https://hermes-agent.nousresearch.com/docs/guides/python-library/)均说明，可 `from run_agent import AIAgent` 后调用 `chat()` 或 `run_conversation()`，不需要启动 CLI、网关或定时任务。它不只是一个只能通过终端使用的应用；此前仅写“AIAgent 接入点存在”没有充分体现官方支持。

`chat()` 返回最终文字，工具循环和重试由内部执行；`run_conversation()` 返回结果与消息历史。可用 enabled_toolsets / disabled_toolsets 控制工具，设置 quiet_mode、skip_context_files、skip_memory。当前官方文档要求每个并发任务独立 AIAgent，不能共享有状态实例。这与 DistillAI worker 管理任务并不冲突；需要比较的是实际导入依赖、关闭行为后的模型请求及写后端，而不是把消息网关、cron 等产品功能都计为必须启动。

分发边界也有版本变化：本地指南仍给出从 Git 仓库 pip 安装；当前官方指南要求在 PM 准备的源码环境中运行，不发布受支持的独立 wheel / sdist。因此可以做 SDK 式嵌入，但不能写成已核实存在可单独 pip 安装的轻量 Hermes SDK 包。本轮不执行安装，也不更新源码。

平台纠正：本地 pyproject 为 0.8.0 / Python >=3.11，旧 README 写原生 Windows 不支持；[当前官方 Quickstart](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart/)已提供 Windows native PowerShell 安装，以及 Blank Slate 最小配置，按需启用功能。此前将旧快照的 WSL2 要求用于当前选型是不准确的，现撤回；原生 Windows 已有公开支持，具体嵌入环境和写沙箱仍待验证。

web_tools.py 提供 search / extract / crawl，按配置或凭证选择 Firecrawl、Parallel、Tavily、Exa；读取内容可能使用辅助模型处理，必须把额外生成计入任务预算，并保留原始取得材料。terminal_tool 支持 local、Docker、SSH 和云环境；本地默认执行没有 OS 写隔离。local 环境有敏感环境变量过滤，与写沙箱是不同机制。

旧快照 run_agent.py 有 IterationBudget / api_call_count，但包含 grace call、计数修正与额外结束处理；不能直接把 max_iterations=16 当我们持久、所有请求均计数的契约。这是实际读过的旧源码行为，不据此声明当前版本保持同一内部实现。

修正后的判断：**Hermes 保留为正式 Python 嵌入候选**，不以“无 SDK”或“必须改用 WSL2”排除。当前轻量程度、写隔离和精确请求计数尚不能据旧快照定论；需要匹配当前版本的源码与实际环境再比较。本轮没有下载、更新或复制其代码。

## 结论与语言选择

按当前业务、原生 Windows 和只限写要求，建议保留两个优先验证方向，而不是立即确定最终框架：

1. **优先验证 DeepSeek Harness 完整 SDK profile 的必要插件组合。** 基础工具、搜索、Windows 命令写隔离已存在，少补功能；检验文件工具与子进程写限制、可裁剪范围、预览版本稳定性和模型计数。TS / Python 客户端都可选。
2. **对照 Pi + 搜索工具 + 外部写隔离。** 核心更薄、业务边界直接，TS SDK 最省桥接；检验补两项能力后的代码量和维护成本，不能只比较 SDK 本身。

若接受 Docker / 托管执行平台，OpenAI Agents SDK + SandboxAgent 进入优先范围；TS / Python 均成立。Codex SDK 能否优先验证取决于实际模型 Responses 能力和写权限 / 计数可控性。Claude SDK、Deep Agents 的额外引擎 / 上游层次较多。用户追问后补核了 Hermes 官方 Python Library 与当前 Windows 支持，保留其 Python 候选资格，轻量程度需用当前版本重新核对，不能凭旧快照降低优先级。

这不是所有候选的绝对性能排名。没有一个已通过本项目“原生 Windows + 所有写工具 / 子进程”的实测；读取不限制，也不新增读取验收。框架和开发语言仍待比较结果确认。

| 后续采用方向 | 语言影响 |
| --- | --- |
| Pi 直接 SDK + MXC Node API | TS 更省桥接；Python 业务后台也可行，但增加 Pi RPC 和隔离启动边界 |
| OpenAI Agents SDK | TS / Python 均可；框架本身不足以替用户决定语言 |
| DeepSeek / Claude / Codex SDK | 两种语言客户端可选，背后仍有独立引擎；不把客户端语言当引擎完全实现语言 |
| Deep Agents | 两种语言都有，但不减少其上游层次 |
| Hermes | 官方 Python Library 可直接嵌入，当前文档支持原生 Windows；具体环境与写后端待验证 |

Graphology、Koffi 和 TS MCP SDK 是 TS 路线下候选，不再称最终技术组合；若选 Python，按相同图、句柄与 MCP 契约选择对应实现。模型配置继续保留 api / base_url / model / api_key，由用户填写；选型时只核对协议需求，不要求提供密钥。

## 后续有界验证项目

以下是进入获批 Plan 后的验证范围，本轮不执行：

- 任务副本可写；文件工具、Shell、Python 和二级子进程都不能越界写原始输入、原文件或程序状态。读取不限制；重点验证链接、改名、删除和真实目标的写限制。
- 权限收紧 / 取消后终止整个进程树；未确认停止禁止写回；模型调用取消不等于 OS 验收。
- 实际模型请求可在发送前计数，包括重试、压缩、修正和辅助模型；中断恢复不重置计数，不能只验证 max_turns 参数。
- 搜索结果有可读取原文与可追溯来源；外部资料不成为程序指令；模型失败 / 抓取失败区分正常空结果，用户表现与助手解释仍分开。
- 同期用户修改不被任务副本覆盖；业务写名额和本轮注入名额不互相阻塞，已提交结果恢复不重跑模型。

优先验证数量控制在选中的一至两个方向，不先把七个框架都安装一遍。不增加产品依赖、Docker、新数据库或测试设施。

## 本地源码依据与版本边界

本地两份目录未发现 Git 元数据，本轮无法声明它们的提交 SHA 或当前远端版本。文件 SHA256 用于标识实际读过的快照，不是 Git 提交；官方在线文档的当前接口与本地旧快照分别报告。

| 对象 | 本地路由与核对入口 |
| --- | --- |
| Codex | `E:/JourneyIntoAI/DL_and_LLM/projects/codex-main`；`sdk/typescript/README.md`、`src/exec.ts`、`src/threadOptions.ts`、`src/codexOptions.ts`；`sdk/python/README.md` / `pyproject.toml`；`codex-rs/model-provider-info/src/lib.rs`；`codex-rs/windows-sandbox-rs/src/elevated_impl.rs`、`lib.rs`、`token.rs` |
| Hermes | `E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent-main/hermes-agent-main`；`README.md`、`pyproject.toml`、`run_agent.py`；`website/docs/guides/python-library.md`；`tools/web_tools.py`、`tools/terminal_tool.py`、`tools/environments/local.py` |

Codex `sdk/typescript/src/exec.ts` SHA256：`A38A799AA5CB296D6E09457F37DAA61071A9D8DD0B885471F8439BAB6BB7B4C6`。

Hermes `run_agent.py` SHA256：`8B5A946FB8666FF98927B56394CDB11FFC99154880D6B3204EF25052D0CD7BE1`。

未发现其余五个候选的对应已登记源码副本，采用上文官方文档 / 官方仓库文档核对。没有把未读源码、第三方评论或搜索摘要登记成实现事实；没有获取缺失的源码副本。源码副本不足处保留未验证，不擅自替换或更新已有目录。
