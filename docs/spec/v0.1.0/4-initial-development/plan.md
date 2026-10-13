---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: draft
decision_mode: user-approved
---

# DistillAI 初版 Implementation Plan

> 执行者按模块 Plan 逐项推进，使用 `executing-plans`；默认由主 Agent 实施。遵循仓库 SDLC 的 Design / Plan 批准点，checkbox 只在取得实际结果后勾选。

## 来源与目标

2026-10-13，用户要求开始编写 Plan。本计划以[统一 Design](design.md)及四轮 grill 确认的九项决定为依据，沿用[Discussion](discussion.md)中按模块分别编写、批准和实施的安排。本文件管理跨模块依赖、技术验证和最终验收；实际任务在八份模块 Plan 中。

目标：在 Windows 上完成一个面向同一用户、接入 Codex Desktop 的本地常驻产品，贯通采集、episode、知识与关系、用户理解假设、主动外扩、上下文 / MCP、自然反馈和 Web 配置 / 查看 / 在线编辑。

架构：Python 控制层持有调度、权限、预算、版本和提交；独立任务子进程通过 Hermes `AIAgent.run_conversation()` 执行模型 / 工具循环。JSON / JSONL 是权威记录，图是可重建的名称 / 连接索引；Hook、MCP stdio 和同源静态 Web 复用一个本机后台。

技术基线：Python 标准库优先、Hermes 源码与 PM 环境、Python 官方 MCP SDK、Win32 句柄适配、原生 HTML / CSS / JS。OS 写隔离实现、固定依赖组合和搜索后端按下文门禁收敛，不把已有调研视为运行成功。

本次授权覆盖 Plan 草案编写。统一 Design / Prompt 保持现有 `draft`，各模块 Plan 也为 `draft`；写计划不自动批准 Design、运行验证或产品实现。

## 当前资产与文件映射

当前分支为 `codex/4-initial-development`。现有可运行资产只有 `plugins/distill-capture/`、`scripts/demo_capture.py`、`tests/test_capture.py` 和开发 Push Hook；没有产品包、pyproject、第三方生产依赖或产品测试。旧采集插件保存原始 payload 到 `.distallAI`，不是新队列契约，保持原位，不就地改成产品实现。

| 位置 | 实施时的职责 / 修改归属 |
| --- | --- |
| `src/distillai/__init__.py`、`__main__.py` | 产品包与命令入口；M01 |
| `runtime.py`、`config.py`、`server.py` | 任务 / 生命周期 / 预算、配置生效、本机 HTTP；M01 |
| `storage.py`、`windows.py` | 快照 / 版本 / 提交 / 恢复、窄范围句柄和进程树适配；M01 |
| `hermes.py`、`tools.py` | 直接库调用和任务工具授权；M01 建立，业务模块登记自身工具 |
| `capture.py`、`sources.py` | 新产品采集过滤 / cursor / 队列及来源解析；M02 |
| `episode.py`、`knowledge.py`、`cognition.py`、`expansion.py`、`context.py` | M03–M07 业务职责 |
| `mcp.py` | 官方协议 SDK 与后台桥接；M07 |
| `prompts/` | Design P01–P07 / P09-B；对应模块发布，实际全文版本入历史 |
| `web/` | 四入口静态页面、样式与交互；M08 |
| `plugins/distillai/hooks/`、`skills/distillai/` | Codex 产品 Hook 与 P08 / P09 接入说明；M02 / M03 / M07 协同 |
| `scripts/start.ps1` | 检查源码 / 环境、启动、退出、MCP 桥接和打开 Web；M01 |
| `pyproject.toml`、产品依赖锁文件 | 只声明实际使用的依赖，工具生成锁；M01 验证环境后创建 |
| `tests/test_*.py`、`tests/fixtures/` | 标准库 unittest 与审核后的合成 fixture；按模块分组 |
| `.github/workflows/ci.yml` | 保留现有 Windows job，增加离线产品契约检查；M01 / 最终验收 |
| `.gitignore`、`README.md`、`.agents/rules/python.md`、`github-actions.md` | 实施后同步真实目录、环境、命令与数据排除；M01 / 最终验收 |

上述源文件均位于 `src/distillai/`；文件名是本 Plan 的实施映射，不是已经存在的产物。仅在文件承担独立职责时创建，不建立八个包 / 服务。Hermes 源码保持在并列上游仓库，不复制或 vendor；产品不安装 Hermes CLI 来执行任务。

## 模块任务与依赖

| 模块 Plan | 完成结果 | 前置依赖 |
| --- | --- | --- |
| [M01 运行与保存](modules/01-runtime/plan.md) | 可恢复的本机后台、受控 AIAgent 执行、冲突安全提交 | G0；能力验证 G1 |
| [M02 采集与来源](modules/02-capture/plan.md) | 新产品队列、来源读取、通知 / 扫描补登记 | M01 本机接口和保存基础；Desktop 采集证据 |
| [M03 episode](modules/03-episode/plan.md) | 固定范围归属 / 缓冲、计时收尾、修订交接 | M01 + M02；生命周期验证 G2 |
| [M04 知识与图](modules/04-knowledge/plan.md) | 独立详情、名称图、查询和确定性重建 | M01 + M02 + M03 关闭记录 |
| [M05 用户模型](modules/05-cognition/plan.md) | 有来源观察、竞争假设、帮助条件与定性判断 | M04，包括正常空结果；原 episode 来源 |
| [M06 主动外扩](modules/06-expansion/plan.md) | 周期覆盖、逐主张核查、结果交 M04 | M04 + M05；搜索选择和接入 G3 |
| [M07 上下文与 MCP](modules/07-context/plan.md) | 两列表、只读检索、筛选 / compact、反馈关联 | M03 + M04 + M05；M06 结果可随后接入 |
| [M08 Web](modules/08-web/plan.md) | 配置、episode、知识 / 关系、历史查看和编辑 | M01 API；各写操作依赖归属模块；M07 历史 |

推荐执行顺序：G0 → M01 → M02 → M03 → M04 → M05 → M07 → M08 → M06 搜索接入 → 全链验收。M06 可在 G3 已闭合时提前；M07 不等待首次外扩，M08 只读页面可先做。没有搜索后端时保留 M06 未完成，不能把其他模块完成称为初版全部交付。

### grill 决定覆盖

| 已确认决定 | 实施与验证位置 |
| --- | --- |
| Q1：Python 控制层 / Hook / MCP，任务子进程直接 AIAgent | M01 Task 1 / 3 / 4；M02 / M07 接入 |
| Q2：episode 修订期间直接依赖判断等待重分析 | M03 Task 3、M05 Task 2、M07 Task 1；M08 版本展示 |
| Q3：知识 / 认知依赖变化触发准备 | M04 Task 3、M05 Task 2、M07 Task 1 |
| Q4：同任务程序评分工具往返 | M03 Task 2；工具后推理沿 M01 计数 |
| Q5：刷新 3 次、外扩 3600 秒 / 10 条可配置 | M01 Task 3、M06 Task 2、M07 Task 1 |
| Q6：旧版 M04 / M05 运行前 / 提交前防发布 | M01 Task 2 / 3、M03 Task 3、M05 Task 2 |
| Q7：末次允许生成可完成，新增超额请求拒绝 | M01 Task 1 / 3、M06 Task 3 |
| Q8：MCP 明确引用程序查询，自然语言只读 Agent | M04 Task 2、M07 Task 3 |
| Q9：筛选 / 查询 / 普通优先级，查询等待与定向取消 | M01 Task 3、M07 Task 3 / 4 |

## 技术验证门禁

| 门禁 | 验证动作与证据 | 放行标准 / 失败处理 |
| --- | --- | --- |
| G0：文档基线 | 审阅统一 Design 新增交接与 P01–P09，分别批准模块 Plan；记录日期和批准范围 | 未批准的模块不实施；本次仍可完成草案编写 |
| G1：运行边界 | M01 Task 1 实测 Hermes 环境 / 所有生成计数 / 写隔离 / 进程停止 / 文件句柄；记录上游 SHA、环境、命令、策略与输出 | 维护任务必须具备全进程写限制和可靠停止；失败保留证据并回到 Design 收敛，不能以 cwd / Prompt 代替 |
| G2：Desktop 生命周期 | M03 Task 1 与 M07 Task 4 取得真实 UserPromptSubmit、Stop、中断、SessionEnd、compact 时序 | 可靠终止依据支撑 30 分钟计时，compact 能恢复本轮快照；缺信号时明确保留未完成状态，不猜结束时间 |
| G3：外部检索 | 用户此前要求延后选择，M06 Task 1 到接入前收敛一种搜索 / 读取方法与实际凭证、错误、模型请求计数 | 不提前选供应商、不建设多供应商框架；未选择时不启动自动外扩，不消耗周期或覆盖进度 |
| G4：完整初版 | 八模块契约测试 + Windows 实测 + Desktop / Web / 自然反馈验收 | 四项验收都有可回查证据，不能用离线或模拟测试替代实机结果 |

本地 Hermes 当前 HEAD 在 2026-10-13 只读核对为 `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed`，与 Design 2026-10-12 官方查证提交 `97a9ae8ee55d31bebce49f1fb6b5ef775323976a` 不同。M01 先记录差异并选择经验证的固定提交；不自动更新、切换或把当前 HEAD 当发行基线。[本地源码路由](../../../research/runtime/README.md#本地源码路由)继续有效。

## 共用实施与验证约定

每个模块先写保护公开契约的合成用例，运行对应组确认暴露缺失行为，再实现并复跑；不为布局或一次性数据写永久测试。使用标准库 unittest，不因计划模板引入 pytest / Ruff。现有采集测试仍直接运行，产品测试命名与旧 `test_capture.py` 区分。

产品测试在仓库根目录、兼容的控制层解释器下执行；源目录通过进程环境加入：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m unittest discover -s tests -p 'test_product_*.py' -v
python tests/test_capture.py
python .codex/hooks/test_pre_push_guard.py
git diff --check
```

预期：unittest 以 `OK` 结束，已有两组脚本退出 0，空白检查退出 0。产品测试全部使用临时数据根、假时钟和本机合成响应，不使用个人会话、真实密钥或外部模型。每个命令单独核对退出码；真实 API / 沙箱 / Desktop 验证单独执行并记录，CI 不取得个人凭证。

统一启动脚本计划接口为 `-Action Check|Serve|Stop|Mcp|Web -HermesSource <绝对源码路径>`；路径由实际配置传入。`Check` 只报告现有环境，不触发 PM 安装；`Serve` 使用已准备环境并管理单例；`Stop` 停止任务后退出；`Mcp` 桥接；`Web` 交换一次性引导凭据。实现后将实际解释器和路径写入操作文档，不把开发机路径嵌入源码。

模块完成时记录真实变更、命令、结果、失败修复、来源版本及 Design 偏差；需要本地 Commit 时仅暂存该模块相关路径。2026-10-13 用户授权将当前文档按主题创建本地提交，草案批准状态不变；Push / PR / Review 发布 / Merge 仍沿独立授权边界。

## Task 9：完整闭环、文档和验收

**Files:** Modify `README.md`、`.agents/rules/python.md`、`.agents/rules/github-actions.md`、`.github/workflows/ci.yml` 及本目录 Plan 执行记录；一次性证据保留 `.artifacts/initial-development/`，不提交原始个人材料。

- [ ] **Step 1：运行离线契约检查。** 执行上面的全套命令；CI 延用 Windows job 和固定 action SHA，记录实际 PR head / base / tested SHA。OS 特权或 Desktop 组不伪造 CI 通过，离线失败先修复再进入验收。
- [ ] **Step 2：执行一条合成的端到端会话。** 在独立测试数据根使用 Codex Desktop：启动 → 连续交流 → 切换 / 收尾 → M04 / M05 → 子图 / 候选 → 新问题筛选 → MCP 查询 → 用户新表现 → 再分析；实际队列行号、各提交版本和交付状态都可追溯。不把模板的虚构引用当 fixture。
- [ ] **Step 3：验证外扩进入同一闭环。** 在 G3 已通过的服务上核查一个具体主张，保存读取原文 / 版本和未核查部分，交 M04；观察 M07 依赖刷新。确认外部结果没有自动写成用户掌握。
- [ ] **Step 4：执行异常恢复。** 在合成任务中分别丢通知、停止后台、撤销工作路径写权限、制造提交中断、同期编辑、取消排队 / 运行中的 MCP 查询；核对原材料、个人编辑、计数、处理位置及未发布文件保持契约。详细安全窗口由 M01 负责，此处只确认模块交接。
- [ ] **Step 5：验证 compact 与日常体验。** 当前轮已有选择时触发 compact 两次，核对同一文字 / 版本恢复且没有新筛选请求；后台繁忙仍有独立筛选名额。记录实际等待、调用次数、输入体量、失败继续回答，以及中立反馈没有诱导认可。耗时实测只报告，不自行加入未批准的 SLA。
- [ ] **Step 6：验证 Web。** 查看四入口，配置保存 / 待生效版本、知识编辑、episode / 认知纠错任务、来源 / 历史版本跳转；再检查键盘、窄屏、错误输入和并发冲突。截图用合成数据。
- [ ] **Step 7：回查四项验收并同步状态。** 按下表建立证据清单；只有对应实施和验收确实完成才标 `implemented`，保留未执行项和实际阻塞。不把“已写 Plan”记录为实施完成。

| 验收方向 | 必须看到的结果 | 证据位置 |
| --- | --- | --- |
| 功能完整 | 八模块所有实施任务完成，搜索、自然反馈和 Web 编辑均进入闭环 | 八份 Plan 执行记录与本 Task 记录 |
| 来源可靠 | 原始队列 → episode → 详情 / 假设 → 检索 / 外扩来源均可回查当时版本；修订 / 待关联有明确身份 | 来源引用、版本和提交 / 任务 ID |
| 认知更新有效 | 助手解释不记为用户能力，受助与独立表现区分，竞争解释可因有区分力的新表现修订；未知保留 | 同一对象的前后观察 / 假设 / 判断及人工审阅理由 |
| 日常体验合适 | 原任务可继续、素材可跳过、无候选空返回、错误明确、compact 恢复原选择、Web 失败保留输入 | Desktop 可观察记录、Web 截图和交互记录 |

## 回退与数据边界

先在合成数据根验证，再接入获准的真实会话。首次产品启用时关闭旧采集验证插件的相同会话触发，保留其文件，不自动删除、转换或把 `.distallAI` 数据搬入 `.distillAI`。用户退出产品时卸载 / 停用接入配置，显式停止后台；数据默认保留。

业务任务失败沿 M01 清单恢复，发生 `recovery_conflict` 暂停冲突范围并保留前后版本，不覆盖用户再次编辑。回退程序版本须先停止任务并核对记录兼容性；出现不兼容时保留数据及诊断，不用重建索引替代业务迁移，也不恢复成旧原始 payload 格式。

## 相对 Design 的实质偏差

当前无业务范围或公开契约偏差。本 Plan 在 Design 参考目录上增加 `config.py`、`server.py`、`windows.py`、`sources.py`，分别隔离配置、HTTP、Win32 和来源职责；这是实施文件分工，不增加服务或运行层。

Python 图查询拟先用标准库字典 / 邻接映射，HTTP 拟先用标准库线程服务；二者在 M01 / M04 验证现有契约，不能满足时记录事实再同步 Design。写隔离、MCP 版本、环境和搜索仍有明确验证 / 选择任务，不假设已选定。

## 执行记录与 Plan 状态

2026-10-13：创建总计划及八份模块草案，完成按 Design 八模块 / C01–C06 / P01–P09 和九项 grill 决定的覆盖核对。一次性文档检查覆盖 31 份 Markdown、367 个本地链接 / 锚点，错误为零；九份 Plan 元信息 / draft 状态、27 个任务、140 个未执行步骤及占位词检查通过。检查在忽略目录已有检查脚本上临时扩展，不新增永久文档测试。当前没有实施命令或产品验证结果；所有实施 checkbox 保持未勾选，批准记录由后续实际确认填写。

同日用户授权按主题提交实施前的当前改动。提交准备检查覆盖 52 份 Markdown、395 个本地链接 / 锚点，错误为零；全部 54 个待提交文件的凭证 / 个人会话引用扫描无发现，两个合成 JSON 可解析，九份 Plan 仍为 draft。个人原始会话仅保留本地忽略目录原件，C01 提交版改为合成场景。此授权仅覆盖本地归档，不执行产品实现或远端写入。
