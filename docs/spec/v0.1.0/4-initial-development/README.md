# 初版设计与开发

2026-10-20 第十九批：用户批准 M06 原任务显式停机续接，统一 Design 当前为修订 4，M06-R2.1 已完成；234 项完整产品、5 项永久浏览器和实际 APScheduler / SQLite 重启通过。Desktop / 独立启动 / 物理休眠及 Push / PR 已获相应授权，物理休眠仅北京时间 02:00–08:00，真实操作和当前 SHA 的 CI 仍需证据；模型配置由本地 Web 保存，详见[待办](pending.md)。Goal 实际为 paused，半小时 heartbeat 为 ACTIVE；不将授权或配置视为实际验收完成。下方日期记录保留当时状态。

2026-10-17，用户已批准重写总 Plan 与八模块 Plan，统一 Design 修订 3 已同步；当前持续实施重构与新功能。Goal 与半小时续接检查已启用，需要用户决策的事项写入 pending.md。下方此前草案状态与旧完成比例保留为历史，当前以 Plan 的批准记录和执行证据为准。

2026-10-18 第十七批：M06 搜索配置 / 上游错误与逐项发布边界验收完成，实际 keyless 主要来源、M04 → M07 和 16 / 17 次生成边界取得证据；在途停机恢复策略待决。M08 完整浏览器、M03 修订交接、M04 三类维护链及 M07 查询取消已完成本地机械验收。真实模型、Desktop G2、独立冷启动、物理休眠与 PR / CI 仍未完成，详见[总 Plan](plan.md)与[待办](pending.md)。

关联 [Issue #4](https://github.com/Spokey5243/DistillAI/issues/4)，分支 `codex/4-initial-development`，采用 Exploratory 流程。

2026-10-16 当前入口：[重写后的总 Plan](plan.md)与八模块 Plan 均为 `draft`，取代旧 140 步及 R01 的继续执行安排。新稿明确复用 Hermes / FastAPI / Uvicorn / HTTPX / MCP / NetworkX、移除模型 HTTP 代理，旧代码与执行证据保留；具体 Design 差异写在总 Plan，尚未补造批准或实施。下方按日期保留的进度仅是重写前历史，不作为继续代码实施的授权。

同日用户同意加入 SQLite、Playwright、Ruff：M01-R6 规划控制状态事务、离线迁移与恢复，M08-R3 规划浏览器行为回归，M01-R3 维护开发依赖与 Ruff 检查。原始材料 / 领域内容继续保留文件，SQLite 具体权威划分随新稿审阅；这里只记录选型和计划，没有安装依赖或执行数据迁移。

2026-10-10，用户要求将八模块 Design 合并为一份，并明确 Design 与 Discussion 冲突时以 Design 为主。当前设计维护入口为 [统一 Design](design.md)。M01–M08 合并前版本均已批准，原文保留为来源快照；合并新增的交接、技术提案与 Prompt 文本保持 `draft`，不撤销已有批准。

2026-10-12，用户在框架比较后最终选择 Hermes SDK，即官方 Python Library / `AIAgent` API，作为后台 Agent 执行入口；选择依据新增后续采集 trajectory、蒸馏闭源模型能力与小模型 RLVR 的方向。同日 grill 第一轮确认控制层、Hook 和 MCP 均使用 Python，Hermes 任务在独立执行子进程调用 `AIAgent` API；环境是否拆分按依赖兼容验证决定。修订期间判断标记、依赖变化触发准备及程序评分工具往返也已确认。其余配套技术、交接、具体训练方案及搜索后端仍待收敛。沙箱只限制写入，读取不限制；API key 由用户填写。[三框架源码比较](../../../research/runtime/round-4.md)保留为历史依据，最终决定见 [统一 Design T05](design.md#technical-selection)。九组、十二段 Prompt 仍为审阅稿，工具映射随 Hermes 接入适配。2026-10-13，按用户要求创建总 Plan 与八份模块 Plan 草案，并授权按主题创建本地提交；尚无产品实施，文档批准状态不变。

## 阅读入口

2026-10-15 当前状态：统一 Design 修订 1 的 G1 已通过。M01 的存储、调度 / 配置 / 预算、Hermes 子进程和 HTTP / 单例已实施；78 项离线契约在两个解释器通过，真实 Library 的文件 / Shell 发布、503 恢复和第 16 / 17 次边界取得产品适配证据。Check / Serve / Stop 跨命令实测通过，Mcp / Web 动作和业务模块仍待对应后续步骤；整个 M01 和初版尚未完成。写隔离留待后续独立 Issue，尚未创建；下方旧阶段描述保留历史。

2026-10-13，用户要求“现在开始按照plan执行”，当前统一 Design / 交接 / P01–P09、总 Plan 和 M01–M08 Plan 均获实施批准。当前进入 M01 Task 1，先验证 Hermes PM 环境与 Windows 运行边界；下述历史段落保留当时状态，技术候选和搜索方法继续按 G1–G3 收敛。

grill 第二轮已确认：子图每 3 次有效更新刷新，外扩每 60 分钟触发、每批最多 10 个已有知识点，均为可配置初始值；旧版 M04 / M05 分析在运行前及提交前核对 episode 修订版本，被替代的输入不再发布当前结果，保留历史并接续最新修订。其余交接、配套技术及 Prompt 整体继续审阅。

grill 第三轮已确认：最后一次允许的模型生成可完成、校验并提交，仍需超额生成才预算失败；明确 ID / 名称查询由程序返回，自然语言 MCP 查询通过 Hermes `AIAgent` 的只读任务执行，先子图 / 上下文、必要时全图。查询预算与历史复用 M01；P06 增加 query 模式，Prompt 组数不变。

grill 第四轮已确认：当前轮注入最高优先、MCP 只读检索其次、普通后台最后；查询复用普通名额、不抢占运行中任务，MCP 等待结果，客户端取消或平台超时停止关联查询，错误不冒充无匹配。九项审查决定均已同步，统一 Design / Prompt 整体仍待批准；依赖与环境、写隔离、文件句柄和 Desktop 行为仍须后续验证，搜索后端按用户要求延后。

- [统一 Design](design.md)：整合核对、共用契约、八模块行为、交接、技术选择、Prompt 与验证。
- [总 Plan](plan.md)：跨模块顺序、能力验证门禁、九项 grill 决定覆盖和完整初版验收；模块任务见下表。
- [冲突核对](design.md#integration-review)：已修正的旧说法和仍需确认的交接缺口。
- [技术选择](design.md#technical-selection)与 [Prompt 草案](design.md#prompt-finalization)：收尾审阅入口。
- [项目结构与启动组织](design.md#project-structure)：Hermes / DistillAI 并列源码、Python 产品目录参考、启动职责和运行数据边界；控制层与执行进程分离，环境兼容待验证。
- [Discussion](discussion.md)：已批准的需求、范围及方向；具体契约随当前 Design 同步。
- [全流程案例 C01](references/c01-flow.md)：提交版使用审核后的合成会话与设计案例，个人原件保留在本地忽略目录；设计部分使用当前队列契约。
- [调研依据 R01–R06](references/research.md)及[后台技术专题](../../../research/runtime/README.md)：历史参考与本轮官方文档核对；调研结论不自动成为批准契约。
- [知识点合成模板](knowledge-point.example.json)与[关系合成模板](relation.example.json)：沿用 M04 / M05 记录组织，全部为合成数据。

<a id="module-roadmap"></a>

## 模块职责与 Plan 路线

统一 Design 按八模块组织职责；模块编号不表示独立服务、Agent 或包。原 Design 快照只保留批准历史，后续设计变化集中写入统一文件。2026-10-13 已按模块分别编写 Plan 草案，仍分别批准；总 Plan 只管理跨模块依赖和最终验收。

| 模块 | 当前 Design | 合并来源快照 | Plan |
| --- | --- | --- | --- |
| M01 | [后台运行、配置与持久化](design.md#runtime-contracts) | [原 Design](modules/01-runtime/design.md)、[技术方案](modules/01-runtime/technical-proposal.md) | [重写草案](modules/01-runtime/plan.md) |
| M02 | [Codex 采集与材料交付](design.md#data-capture) | [原 Design](modules/02-capture/design.md) | [重写草案](modules/02-capture/plan.md) |
| M03 | [episode 构建与维护](design.md#episode-model) | [原 Design](modules/03-episode/design.md) | [重写草案](modules/03-episode/plan.md) |
| M04 | [知识点、关系与图索引](design.md#cognitive-map-model) | [原 Design](modules/04-knowledge/design.md) | [重写草案](modules/04-knowledge/plan.md) |
| M05 | [用户理解估计与反馈](design.md#cognition-decisions) | [原 Design](modules/05-cognition/design.md) | [重写草案](modules/05-cognition/plan.md) |
| M06 | [外部搜索与知识扩充](design.md#knowledge-expansion) | [原 Design](modules/06-expansion/design.md) | [重写草案](modules/06-expansion/plan.md) |
| M07 | [检索、注入与 MCP 接入](design.md#context-retrieval) | [原 Design](modules/07-context/design.md) | [重写草案](modules/07-context/plan.md) |
| M08 | [本地 Web、配置维护与在线编辑](design.md#local-web-console) | [原 Design](modules/08-web/design.md) | [重写草案](modules/08-web/plan.md) |

## 依赖与推进顺序

执行中需要用户补充的信息和外部实测条件集中在[执行待办](pending.md)；用户未及时回复时继续不依赖它们的实施。

按用户 2026-10-13 的要求，先完成总 Plan 与模块 Plan 草案；实施前仍核对新增 Design / Prompt 和对应模块 Plan 的批准范围。Plan 在 `modules/<模块>/plan.md` 保存，引用统一 Design 的实际依赖契约；仍归属 Issue #4 与当前分支。运行条件、Desktop 生命周期和搜索接入分别在总 Plan 的 G1–G3 验证 / 收敛，未取得证据不假定通过。

实施依赖为 M01 → M02 → M03 → M04 / M05；M06、M07 使用知识与认知记录，M08 复用业务能力。M07 可查询已有记录，不必等待一次外扩；页面只读部分可使用已保存记录，编辑与纠错分别依赖归属模块。模块通过自身验证后，还需取得 Desktop、Web 与完整反馈闭环验收证据。

## 跨模块契约归属

| 契约 | 定义模块 | 主要使用者 |
| --- | --- | --- |
| 后台生命周期、任务执行、配置、保存与历史版本 | M01 | M02–M08 |
| 采集过滤、队列与来源行号 | M02 | M01 / M03 |
| 交流归属、边界、关闭与修订 episode | M03 | M04 / M05 / M07 / M08 |
| 知识、独立关系与名称图 | M04 | M05–M08 |
| 观察、假设、帮助条件与理解估计 | M05 | M06–M08 |
| 外扩发现、来源核查与候选排序 | M06 | M04 / M05 / M07 / M08 |
| 子图、两列表、MCP 与本轮上下文交付 | M07 | Codex 接入端 / M05 / M08 |
| 页面交互与 Web 请求反馈 | M08 | 本地用户，业务规则复用归属模块 |

一个字段、状态或业务规则只由归属模块维护；跨模块变化同步实际依赖方及 C01 受影响步骤。沿用 [Spec 工作流](../../README.md)和仓库 SDLC 规则。

2026-10-15 继续推进 M02：产品正文 / 工具采集、队列 / cursor、物理来源读取、轻量通知和可靠扫描已接入。M02 12 / 16 步完成，全计划累计 32 / 140；M03 处理位置、M07 实际工具前缀和真实 Desktop 仍待接续。真实 AIAgent 的来源工具往返及其余六个合成场景共 43 次请求通过。G2 测试插件已准备为本机可用条目，尚未安装 / 启用，不能视为 Desktop 验证通过。当前状态以 [总 Plan 执行记录](plan.md#执行记录与-plan-状态)及模块 checkbox 为准。

同日后续进度：M03 普通材料归属 / 缓冲 / 程序评分 / 原子处理位置，M04 详情约束 / 字段权限 / 名称多关系图 / 历史与一跳查询 / episode 分析已接通；累计 44 / 140 步，98 项离线契约在两个解释器通过。真实 AIAgent 的 M03 → M04 合成链路 17 次生成通过，M04 空结果仍交 M05。G2、生命周期收尾、修订等待、三类维护的外扩 / 用户编辑、M05 / M07 / Web 与语义质量仍按各 Plan 接续，模块不标 implemented。

同日继续：M05 的来源身份 / 字段权限 / 假设 / 定性判断和 episode 分析已实现；M07 准备 / 两列表 / 周期与直接依赖刷新、实际读取版本的只读查询、独立调用取消、无工具筛选 / compact 快照及反馈待关联已接入，累计 56 / 140 步完成。120 项产品契约在两个解释器通过，实际 SDK / AIAgent 的准备 / 查询 / 筛选 / 取消探针共 9 次请求。当前 MCP 要求先通过 Serve 启动后台；自动冷启动、真实 Desktop、修订等待解除、外部搜索与 Web 尚未完成。M06 搜索方案已按 Plan 发起选择，未擅自配置供应商或开启周期。

最新进度（2026-10-16）：累计 **112 / 140**；两个解释器各 **160 项产品测试通过**。M01 25 / 25、M08 16 / 16 的模块 Plan 已实施；M03 新材料直接修订、M05 同源反馈、M07 候选代次校验及 Web 关联回查 / 新依据重分析已接通。真实 AIAgent 新材料修订链 12 请求、真实 Tavily 外扩到 M07 和用户编辑链 14 请求、SDK / AIAgent 上下文链 9 请求通过。剩余真实 Desktop、生命周期和模型语义验收见[执行待办](pending.md)，整体仍为 approved / 执行中。
