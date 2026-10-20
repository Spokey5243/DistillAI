# 后台运行技术第 4 轮：DeepSeek Harness、Pi、Hermes SDK / Library

2026-10-10，Issue #4，状态：`exploring`。用户将重点缩小到这三个项目，新增后期接入本地 LLM 服务的要求，并授权下载最新源码。本轮按相同维度核对本地源码与随仓官方文档，把结果交给用户决定框架和 TS / Python；没有替用户选定路线。

业务要求以[统一 Design](../../spec/v0.1.0/4-initial-development/design.md)为准。沙箱只限制写入，读取不限制；任意 Shell 及其子进程的写入仍在约束范围。任务副本、单业务写者、独立注入名额、实际模型请求最多 16 次、版本校验及提交恢复继续保留。Claude、Codex、OpenAI Agents、Deep Agents 不在本轮重点范围，其历史比较见[第 3 轮](round-3.md)，不记为正式排除。

## 下载与核对版本

下载的是查询时远端默认分支 HEAD，采用浅克隆，保留旧副本。发布版本单独列出；没有把默认分支当作发布包，也没有安装依赖、启动 Agent 或执行下载仓库的脚本。

| 项目 | 本地目录 | 分支 / 完整 HEAD | 查询到的最新发布 |
| --- | --- | --- | --- |
| DeepSeek Harness | `E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness` | `master` / `d743267388641bc76f17c45ce8b4c231aed1d32c` | `dsh-v0.2.1-alpha.2`，2026-10-09；预发布，查询 stable latest 返回 404 |
| Pi | `E:/JourneyIntoAI/DL_and_LLM/projects/pi` | `main` / `42a3497d03ad17e308a2299fa824727894f2c0ec` | `v1.1.0`，2026-10-07；下载 HEAD 比发布更新 |
| Hermes Agent | `E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent` | `main` / `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed` | `v0.21.6`，2026-10-08；下载 HEAD 比发布更新 |

来源：[DeepSeek 发布](https://github.com/deepseek-ai/deepseek-harness/releases)、[Pi 发布](https://github.com/earendil-works/pi/releases)、[Hermes 发布](https://github.com/NousResearch/hermes-agent/releases)，发布元数据通过 GitHub CLI 读取。后续源码统一使用[本地源码路由](README.md#本地源码路由)，不再取线上源码替代这些副本。

DeepSeek TS client 的源码包版本为 `0.2.1-alpha.2`，Python SDK / runtime-bin 的源码声明为 `0.0.0.dev0`；Hermes 根项目 / PM 的源码版本为 `0.0.0`。这些源码占位版本不能作为正式安装版本。Pi coding-agent / agent-core 源码版本为 `1.1.0`。选型后再固定发布包和对应提交，避免把更新中的 HEAD 直接作为实施基线。

## 同维度比较

表中的“现成”指源码已有能力或官方接口；运行行为尚未集成验证。薄度分别考察可接管的行为、必须携带的运行时，以及 DistillAI 需补的功能，不按仓库大小或 SDK 外壳行数排名。

| 维度 | DeepSeek Harness | Pi | Hermes SDK / Python Library |
| --- | --- | --- | --- |
| 程序接入 | 官方 TS / Python SDK；两者经 stdio JSON-RPC 控制 dsh 子进程 | 官方 TS SDK 直接 `createAgentSession`；Python 需要跨进程 RPC 等接法 | 官方 Python Library，直接 `from run_agent import AIAgent`，不需启动 CLI |
| 基础 Agent 能力 | 完整 `sdk` profile 有循环、文件、平台 Shell、事件与持久化；插件组合 | coding SDK 有循环、文件 / Bash、自定义工具、事件与会话；资源可显式替换 | 文件 / terminal、自定义工具、MCP、回调与会话；工具集可配置 |
| 本地 LLM 服务 | `llm-pi-ai` 配置自定义 provider、协议、baseURL、模型元数据；不限 DeepSeek | 自定义兼容 endpoint，明确列出 Ollama / LM Studio / vLLM / SGLang；可扩展 provider | 自定义 base_url / api_key / model / api_mode；官方支持 OpenAI 兼容本地服务 |
| 小上下文本地模型 | 要显式填实际 context / output；适配器缺省容量偏大 | 要显式填实际 context / output；仍受模型工具调用质量限制 | 通常启动时拒绝低于 64,000 token 的窗口；当前源码允许 LM Studio 显式正数 context 配置例外 |
| Web search / 页面读取 | 现成 `web_search` / `web_fetch`；Exa、Perplexity、DeepSeek 后端与 HTTP fetch | 默认 coding 工具不含通用联网搜索；需注册搜索和网页读取工具或接 MCP | 现成 `web_search` / `web_extract`，多后端；可分别固定搜索与提取后端 |
| Windows 只限写沙箱 | 自带命令 restricted token / Low integrity / Job；文件工具另有路径围栏；仍有边界缺口 | 没有自带 OS 写沙箱；需外部写隔离，覆盖文件工具与命令子进程 | 文件工具有 `HERMES_WRITE_SAFE_ROOT`；本地 terminal 同用户运行，仍需外部 OS 写隔离 |
| 资源 / 额外行为控制 | 用 profile / patch 配置插件树；完整 `sdk` 继承 base，需关掉业务不使用的功能 | SDK 可替换 ResourceLoader、settings、tools、session、models；控制入口清楚 | 可选工具集，关闭 memory、context files、background review；还需收紧 profile / plugin / auxiliary 配置 |
| 安装与运行负担 | TS 引擎 + Cordis 插件；Python SDK 携带 runtime-bin，免系统 Node 不等于没有 JS 引擎 | coding SDK 的 manifest 有 23 个直接依赖，包含 TUI / 图像 / MCP / codemode；较小 agent-core 不含完整 coding 工具层 | 当前源环境由 PM 管理，官方没有受支持的独立 wheel / sdist；根 manifest 有 45 个核心依赖条目，含平台条件 |
| 中断与完成状态 | SDK 有 enqueue / wait / shutdown；没有单会话 wire cancel，超时只放弃等待 | 有 `session.abort()`、settled 事件；进程树终止需配合写隔离层 | 有中断控制及流式回调；本地服务请求 / Shell 完全停止仍需核对 |
| 16 次实际请求预算 | 重试、compact、辅助搜索模型都需计数；SDK 事件不是请求前闸门 | 可在执行 / provider 路径接管，但 retry / compact / summary 都要纳入 | `max_iterations` 有内层重试和 grace call；不能当成严格 16 次请求上限 |
| DistillAI 主要补充 | 受控 profile、请求闸门、超时后停止策略、临时写根收紧、提交 / 恢复 | 搜索 / 抓取、OS 写沙箱、请求闸门、提交 / 恢复 | 受控源环境、功能关闭、OS 写沙箱、请求闸门、提交 / 恢复 |
| 语言影响 | TS / Python 都可；选择 Python 仍需维护 JS 运行时配置与插件 | TS 路线直接；Python 增加一层接口桥接 | Python 路线直接；TS 业务后台需再加 Python 进程服务 / RPC |

主要依据分组见文末 S01–S18。依赖条目数只是安装负担的线索：平台条件、optional extras、传递依赖和发布打包方式不同，不能据此计算三者最终体积、内存或启动时间。

## 本地 LLM：能接入和稳定完成任务分开看

### DeepSeek Harness

完整 base 已登记 `@deepseek-ai/dsh-llm-pi-ai`，默认没有配置 provider；新增本地路由需要 `api`、`baseURL`、非空 `models`，模型条目指定实际 `contextWindow` / 输出限制。`openai-completions` 在这里指 Chat Completions 适配，不是要求本地服务实现旧文本 completion 接口。可以和原生 DeepSeek adapter 共存，路由名冲突会拒绝加载。〔S02〕

Python SDK 的 `base_url` / `api_key` 快捷参数针对 DeepSeek 凭证环境变量；接自定义本地服务，应在运行时 profile 配置相应路由，再由 SDK 指定 provider / model。不能把“改 Python base_url”当作通用供应商接入的完整步骤。〔S03〕

未描述模型的 fallback 为 context 262,144、output 32,768；本地部署必须覆盖为服务实际容量。默认 normal retry 有五次重试，必要时下调。模型兼容开关能处理部分 reasoning、system role、输出字段差异；具体模型模板和流式 tool call 行为仍待验证。DeepSeek 这条接法复用了 Pi AI，二者的协议适配并非完全独立。〔S02、S08〕

### Pi

官方明确列出 Ollama、LM Studio、vLLM、SGLang 等兼容 endpoint，配置 baseUrl、API 类型、模型 ID 和凭证；本地无认证服务可以按文档用 dummy key。实际产品配置只接受用户填写的值 / 凭证引用，不启用 `models.json` 中可执行命令的配置形式。〔S09、S10〕

SDK 能把模型配置、认证、会话和资源加载切换到产品专用位置或内存，并显式替换所有自动发现资源。这与 DistillAI 的自有 Prompt、模型配置和状态较吻合。模型本身仍需支持可靠的结构化工具调用；模型 ID 能列出、普通聊天能回复，都不足以证明可维护文件和完成知识任务。〔S10、S11〕

### Hermes

`AIAgent` 当前构造参数有 `base_url`、`api_key`、`provider`、`api_mode`、`model`、`max_tokens`，可直连 Chat Completions 服务；无需云端账号作为框架的通用前提。local endpoint、压缩及 auxiliary model 也应显式配置，防止主模型换本地后辅助请求仍沿用其他路由。〔S13、S14〕

当前 `MINIMUM_CONTEXT_LENGTH = 64_000`，初始化 `_enforce_minimum_context` 通常拒绝更小窗口。本地 Ollama 的实际 `num_ctx` 参与检查；**LM Studio provider 设置显式正数 context_length 时允许低于门槛**。因此此前“所有 Hermes 本地模型都硬性至少 64K”的说法需要修正，但该例外不证明小窗口下工具任务可靠。不要把配置数值虚报到 64K 来绕过实际容量。〔S14〕

官网 / 随仓 provider 文档的部分命令配置说明与 Library 可用参数不同：本轮按构造函数确认 `max_tokens` 存在，不将 CLI 配置限制扩展到整个 Python API。官方源码环境目前实际支持方向为 Python 3.14；根项目允许更早解释器进入更新流程，不等于嵌入应用可任选旧 Python。〔S13、S14、S18〕

### 三者都需要的验证

选型后，用一个实际本地模型及服务验证以下四点即可，不先铺多模型兼容矩阵：

1. 正确的 tool-call 模板 / 服务解析器：模型返回合法工具名、参数及 call ID，不能只输出 JSON 文本冒充工具调用。
2. 流式分片与异常结束：参数 JSON 跨多个 delta、断流 / 超时、工具错误能被识别，失败任务不提交文件。
3. 实际容量：context、max output、reasoning tokens 与服务配置一致，压缩 / 重试计入任务额度。
4. 路由与抢占：全部生成请求走预期 endpoint；业务任务与当前轮注入共享本地模型时，单槽服务能否取消旧请求并及时服务注入。

“支持本地 LLM”不等于搜索也离线。搜索 / 抓取是独立网络工具；本轮不选择服务商，也不要求额外部署搜索服务。

## Web search 与内容读取

DeepSeek 完整 base 默认搜索路由是 `deepseek-official`，搜索本身是一条带服务端检索的辅助模型请求，使用单独的搜索 endpoint / 凭证逻辑；聊天模型改成本地不会自动改变它。若希望摆脱该模型供应商，可使用现成 Exa 或 Perplexity plugin 并明确选择路由；其中 Exa 返回来源 / snippet，不返回生成答案。`web_fetch` 是匿名 HTTP 页面获取，不是完整浏览器，也不保证所有动态页面提取效果。〔S01、S04〕

Pi 可以注册独立 `web_search` / `web_fetch` 两个 custom tool，或使用 MCP 扩展。前者要补供应商调用、超时、错误及 URL / 原文来源字段；不是补一个新的 Agent 框架。默认 `grep` / `find` 是本地文件能力，不能算联网搜索。〔S09、S10〕

Hermes 已有通用 `web_search` / `web_extract`，后端包括 Tavily、Exa、Parallel、Firecrawl、SearXNG、Brave、DDGS 等，并支持分别指定 search / extract backend。当前源码提取路径标注不使用 LLM；不能沿用旧版本结论，假定每次网页提取必定另调摘要模型。未固定后端时存在自动发现和失败救援逻辑，产品若要求固定外部来源，需要明确选择并审查 fallback 行为。〔S15〕

三者都能支持 M06 的“找来源 → 读取内容 → 判断能否支持知识更新”。来源验证、引用定位、失败处理和预算由 DistillAI 按业务契约安排；框架提供搜索结果不自动完成知识验证。

## 只限制写入的沙箱

### DeepSeek：现成组件最多，但还不是已验收边界

命令层 Windows backend 采用 restricted token、Low integrity 和 `KILL_ON_JOB_CLOSE` Job，限制写 / 删除；读取、网络与进程可见性不限制，符合用户的读取口径。文件工具通过 `fs-sandbox` 做写 / edit 路径检查，读取透传。默认 base 使用 `workspace-write`。〔S01、S05、S06〕

需要针对 M01 处理四个实际差异：

- Windows 命令层是 workspace + 私有 temp；文件工具共享的 `writableRoots` 包含 workspace、`/tmp`、`os.tmpdir()`。后者比“当前任务私有临时目录”宽，需要收紧或替换此策略，不能直接声称已覆盖 M01。
- 文件围栏是受信代码中的路径检查，源码明确保留 TOCTOU 风险；自定义工具直接用 Node fs 的写操作不会自动经过它。产品工具必须走受控写路径，控制程序的最终提交使用既有句柄 / 版本契约。
- Windows hard link 是同一个文件对象：工作区内授予写权限可通过外部硬链接别名影响对象。任务副本应避免继承外部 hard link；目录联接、链接替换及写回身份仍需实测。
- 受限孙进程使用 Node / libuv `stdio: 'pipe'` 可能 `EPERM`；继承 / 忽略 stdio 和 PowerShell 匿名管道有不同表现。workspace 的 ACL / Low label 会持续存在；只对可丢弃任务副本使用并检查回收，不修改用户工作目录 ACL。

审批或 escalation 不能让后台任务扩大写权限；受控 profile 必须关闭不允许的提权路径。SDK 承载进程和所有 plugin 并没有因此整体变成 OS 沙箱，任意新增执行插件的写入范围仍需检查。〔S05–S07〕

### Pi：需要补 OS 写隔离

Pi 官方 security 文档明确没有 OS sandbox。设置 cwd、project trust、禁用扩展、仅暴露 write / edit 工具，都不能阻止 Bash 或其子进程在其他路径写入。需要把具备任意执行能力的部分置于 OS 写隔离内；文件工具也要覆盖，不只包装 bash 命令。〔S12〕

MXC 等是可选实现，并非额外规定的必经层。只要覆盖 M01 的写边界即可，不要求读限制。独立注入筛选不带文件 / Shell 工具，可保持在受保护控制层。

### Hermes：文件写保护与命令隔离分开

`HERMES_WRITE_SAFE_ROOT` 支持多个根，Windows 用 `;` 分隔；file safety 会解析路径并在 `write_file` / `patch` 前检查。官方文档同时明确：terminal 与调用进程使用相同 OS 用户，Shell 可覆盖这些文件保护路径。因此该变量能减少误写，**不能单独满足任意命令的写沙箱**。〔S16〕

Hermes 有 Docker / 云等隔离 backend，但本轮没有授权增加 Docker 或托管基础设施。若选原生本地 Windows 路线，需补适合的 OS 写隔离或执行 backend；原生 Windows 可安装与已经具备只限写 OS 沙箱是两件事。读取不限制继续沿用户要求，不把读取能力作为排除理由。〔S16、S18〕

## 框架薄度、后台接入与恢复

### 可控制的范围

DeepSeek 的薄点是 Cordis 服务 / 插件可组合；完整 `sdk` profile 仍继承 base，带配置、凭证、job、subagent、compact 等。`sdk-minimal` 真正更小，却默认 `danger-full-access`，不带 web / sandbox / 文件工具 / compact 等，不能把它当作满足全部需求的现成方案。可通过 patch 关闭不使用功能，或组合必要插件；后者需要自己维护组合及升级兼容。Python SDK 打包 runtime-bin，所以不需要用户先装系统 Node，但部署仍包含 JS 引擎。〔S01–S03、S07〕

Pi 官方 full-control 示例明确替换 settings、tools、会话和整个 ResourceLoader，可关闭自动发现的 extensions / skills / Prompt / AGENTS，使用产品自己的状态。coding SDK manifest 仍包括 TUI、codemode、MCP、图像等包，直接依赖 23 个；SDK 不启动这些界面不代表 npm 不安装它们。更小的 `pi-agent-core` 可以避免部分上层依赖，但需要另装配文件 / Shell / 会话能力，不能用其小体积给完整 coding SDK 背书。〔S10、S11〕

Hermes 有正式 Python Library；直接 AIAgent 不要求启动 CLI、gateway 或 cron 调度器。可配置工具集、`quiet_mode=True`、`skip_memory`、`skip_context_files`、`skip_background_review`，不要把“完整产品有很多功能”写成“嵌入必定启用所有功能”。但它仍依赖 Hermes 源码环境及 PM，根 manifest 核心条目 45 个，含 CLI / cron / browser / Web 服务相关依赖和平台条件；激活源环境与独立轻量 SDK 安装的维护方式不同。〔S13、S14、S18〕

### 额度和取消不能只看高层参数

M01 上限是实际发出的生成请求总数，包括失败重试、修复、compact；辅助服务实际调用生成模型时也计入。搜索纯检索不计生成请求，返回生成答案的搜索后端需要单独确认。

- DeepSeek 的 provider retry 默认五次，compact 有自己的 summary 限制；协议仅六类请求，没有 per-session cancel。`requestTimeout` 放弃客户端等待，服务器工作仍继续。可以关闭整个 runtime，但会影响其中其他 session；业务写任务与高优先级注入的进程 / session 安排不能只依赖超时。日志 / 通知有助于追踪，不是请求发送前的预算闸门。〔S02、S07、S08〕
- Pi 有 `session.abort()`，完成判断有 `agent_settled`，能覆盖重试 / 自动恢复后的闲置。普通 `agent_end` 不能单独当任务彻底结束。compact / branch summary 另有生成与 retry 调用；provider 回调或主循环的包裹需要覆盖这些路径，避免只统计 `prompt()`。〔S10、S11〕
- Hermes 外层 iteration 还有内层 retry，并存在 `_budget_grace_call`，默认 `max_iterations` 近乎无上限；设置为 16 不能证明只发 16 次请求。源码有 LLM execution middleware 和 interrupt control，可作为接入候选，但要检查 auxiliary / compression / 内部 SDK 重试的实际发送路径与中断效果。〔S14、S17〕

三者的会话日志都不是 DistillAI 的最终提交记录。prepared / committed 状态、数据版本校验、错误后丢弃任务副本，以及“提交恢复不再调用模型”，仍由控制程序实现。无需为了框架自带状态库改变八模块的文件持久化设计。

## 供用户判断的取舍

| 你最看重的条件 | 相应取舍 |
| --- | --- |
| Windows 的只限写能力和联网工具尽量现成 | DeepSeek 已有最接近的组合；代价是 alpha、插件配置维护、取消接口缺口和写边界收紧 |
| Agent 行为、资源加载和业务状态由自己明确控制 | Pi SDK 的显式控制适合；代价是自己接搜索和 OS 写隔离，coding 包安装负担也要计入 |
| 后台以 Python 为主，并复用较多现成工具 | Hermes 正式 Library 可直接嵌入；代价是 PM / 源环境维护、写隔离补充，以及本地小窗口模型限制 |
| 希望框架选定后仍可在 TS / Python 间选择 | DeepSeek 两种 SDK 都有，但业务语言变化不消除底层 JS runtime；Pi / Hermes 各自的直接语言更明确 |

三个候选都保留，没有因本轮调研正式排除任何一个。当前不采用自动评分或总分：写隔离是否愿意自补、是否接受 alpha、TS / Python 的维护偏好，以及本地模型窗口，决定权重。具体服务商和本地模型可以稍后配置，本轮只比较接入能力和成本。

## 可复查的本地依据

以下全部对应本轮表中的固定 HEAD。链接指向已下载文件，随仓文档与实现一起核对；没有将仓库内开发指令作为 DistillAI 的规则。分组编号供上文定位。

| ID | 入口 | 核对内容 |
| --- | --- | --- |
| S01 | [base profile](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/bundle/base/cordis.patch.yml:124)、[sdk profile](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/bundle/sdk-app/cordis.patch.yml:1) | provider 注册、默认 workspace-write、搜索默认路由、SDK 继承 base |
| S02 | [llm-pi-ai](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/llm/llm-pi-ai/README.md:26) | 自定义路由、API / 模型元数据、容量缺省、重试 |
| S03 | [Python SDK](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/python/sdk/README.md)、[Python manifest](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/python/sdk/pyproject.toml:6) | Python 参数、子进程、runtime-bin 和源码版本 |
| S04 | [web 家族](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/web/README.md:12)、[Exa provider](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/web/web-search-exa/README.md:12) | 搜索 / HTTP fetch、非生成 Exa 来源结果 |
| S05 | [Windows ACL backend](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/sandbox/sandbox-windows-acl/README.md:12) | 写 token / Job、hard link、ACL 持续、孙进程 pipe 限制 |
| S06 | [fs-sandbox](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/fs/fs-sandbox/src/index.ts:1)、[writableRoots](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/sandbox/sandbox/src/roots.ts:47) | 文件围栏、TOCTOU、平台 temp 可写根 |
| S07 | [sdk-minimal](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/bundle/sdk-minimal/README.md:12)、[协议](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/sdk/protocol/README.md:40)、[client 取消说明](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/sdk/client/src/client.ts:176) | minimal 缺失功能、六请求、超时不取消 |
| S08 | [llm-retry](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/llm/llm-retry/README.md:12)、[TS client manifest](/E:/JourneyIntoAI/DL_and_LLM/projects/deepseek-harness/packages/sdk/client/package.json:1) | 重试语义、客户端依赖和版本 |
| S09 | [Pi models](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/docs/models.md:43)、[CLI 工具](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/docs/cli.md) | 本地服务 / 凭证 / 工具范围 |
| S10 | [Pi SDK](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/docs/sdk.md)、[full control](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/examples/sdk/12-full-control.ts:1) | 资源替换、自定义工具、接口控制 |
| S11 | [Pi manifest](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/package.json:56)、[session](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/src/core/agent-session.ts:203)、[summary 调用](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/src/core/compaction/compaction.ts:614) | 包依赖、settled / abort、独立压缩重试 |
| S12 | [Pi security](/E:/JourneyIntoAI/DL_and_LLM/projects/pi/packages/coding-agent/docs/security.md) | 无 OS sandbox、cwd 不是权限边界 |
| S13 | [Hermes Python Library](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/website/docs/guides/python-library.md:8)、[AIAgent](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/run_agent.py:236) | 正式嵌入接口、源码安装、功能关闭、构造参数 |
| S14 | [初始化](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/agent/agent_init.py:2044)、[64K 常量](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/agent/model_metadata.py:272)、[provider 文档](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/website/docs/integrations/providers.md) | 本地路由、LM Studio 例外、auxiliary / compression 配置 |
| S15 | [web tools](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/tools/web_tools.py:100)、[extract](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/tools/web_tools.py:393)、[rescue](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/tools/web_tools_rescue.py) | 多后端、无模型 extract、自动发现 / 救援 |
| S16 | [security](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/website/docs/user-guide/security.md:384)、[file safety](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/agent/file_safety.py:222)、[local backend](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/tools/environments/local.py) | 写工具围栏和 terminal 的不同边界 |
| S17 | [循环](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/agent/conversation_loop.py:1497)、[API 调用](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/agent/turn_api_call.py:121)、[middleware](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/hermes_cli/middleware.py:135)、[interrupt](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/agent/interrupt_control.py:128) | 内层 retry、grace、middleware、中断控制 |
| S18 | [Hermes manifest](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/pyproject.toml:5)、[PM](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/website/docs/reference/package-management.md:214)、[Windows](/E:/JourneyIntoAI/DL_and_LLM/projects/hermes-agent/website/docs/user-guide/windows-native.md) | 核心依赖、Python 环境、原生 Windows |

## 验证范围

已完成三个默认分支源码下载、origin / HEAD / 发布元数据核对、关键接口与配置调用链阅读、依赖声明计数；三个源码 checkout 保持干净。一次性文档检查通过：22 份 Markdown、317 个本地相对链接 / 锚点，八模块与九组 Prompt 完整性、两个合成 JSON 解析通过；`git diff --check` 无空白错误。本报告绝对路径的源码引用另核对文件存在及行号范围，不增加永久文档测试。

未安装 SDK / runtime / PM、未执行仓库测试、未连接本地 LLM / 搜索服务、未操作 ACL 或验证进程树隔离。实际性能、安装体积、模型兼容性和写隔离有效性尚无运行证据；选型后在批准的 Plan 中验证。
