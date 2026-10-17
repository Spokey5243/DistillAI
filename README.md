# DistillAI

项目已有初版实现。2026-10-16 按用户要求[重写总 Plan 与八模块 Plan](docs/spec/v0.1.0/4-initial-development/plan.md)：复用成熟依赖、移除模型 HTTP 转发、保留领域规则并补齐真实验收。2026-10-17 用户已批准新稿并授权持续实施；统一 Design 为修订 3，当前进度与证据见 Plan。

当前计划已按用户意见纳入 SQLite 控制状态事务、Playwright 浏览器回归和 Ruff 静态检查，具体见总 Plan、M01-R6 与 M08-R3。SQLite 控制状态与离线迁移工具已实现并通过合成数据验证；产品依赖与 Chromium 已安装，真实浏览器回归已运行。未迁移真实用户数据。

## GitHub 与标准开发流程

项目使用 Codex Desktop 开发，GitHub 管理 Issue / PR / CI，远端操作默认使用本机 GitHub CLI `gh`，不依赖 MCP。首次登录、workflow 权限、建仓、默认分支保护及 Desktop Hook 信任步骤见 [GitHub 配置指南](docs/development/github-setup.md)。

开发任务按 Direct、Medium、Intent、Exploratory 分类；非 Direct 保留 Issue 和对应文档批准点。完整行为规范见 [AGENTS.md](AGENTS.md)、[SDLC 规则](.agents/rules/sdlc.md)，目录说明和模板见 [Spec 工作流](docs/spec/README.md)。Spec 按 `docs/spec/<版本号>/<分支名>/` 管理。

- `$standard-development-flow status`：只读核对阶段、证据和下一门禁。
- `$standard-development-flow continue <Issue编号>`：推进已授权整体流程。
- `$github-pr-review <PR URL>`：默认只读 Analyze，发布当前 COMMENT review 需要明确授权。
- 本地 Push 检查与采集 Hook 是两个职责：`.codex/hooks.json` 检查 Push，`plugins/distill-capture` 保存原始会话；不会因为 GitHub 配置而增加采集事件。

GitHub Actions 的 `CI / Windows tests` 在 PR、默认分支 Push 和手动触发时执行同一套 Windows + Python 3.13 检查。普通分支 Push 的 job 跳过，不算 PR 通过。Actions 只有只读 Contents 权限，不需要 GitHub / 模型 secret，也不会自动创建 Issue / PR 或调用模型。

允许先发布开发规范、后发布插件：Push 检查始终执行；插件与采集测试均未提交时，CI 明确输出采集行为未验证。提交 `tests/test_capture.py` 后自动运行采集测试并传播失败；提交采集插件却遗漏测试时 CI 失败。CI 只验证已提交版本，不读取本机未跟踪文件。

完整本地检查：

```powershell
python tests/test_capture.py
python .codex/hooks/test_pre_push_guard.py
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -p 'test_product_*.py' -v
uv lock --check --offline
```

迁移与验证记录见 [迁移计划](docs/development/github-sdlc-plan.md)，Anthropic 文章的采用与暂缓项见 [AI-native SDLC 适配](docs/development/ai-native-sdlc.md)。

## Hook 采集可行性验证

已完成的验证记录、插件、演示脚本与测试见 [采集验证任务](docs/spec/v0.1.0/capture-validation/README.md)，运行和历史验证说明见 [使用说明](docs/spec/v0.1.0/capture-validation/usage.md)。这些资产后续可按产品设计需要移除。

## 产品调研、设计与实施计划

[领域词汇表](docs/CONTEXT.md)、[调研综述](docs/research/README.md)和[初版设计与开发](docs/spec/v0.1.0/4-initial-development/README.md)按主题归档维护。八模块的当前维护入口为 [统一 Design](docs/spec/v0.1.0/4-initial-development/design.md)，旧模块文件保留为批准历史快照；[总 Plan](docs/spec/v0.1.0/4-initial-development/plan.md)串起八份模块实施计划与验收。2026-10-13 用户授权按当前 Plan 开始实施，统一 Design / Prompt、总 Plan 与八份模块 Plan 已批准；当前从 M01 运行边界验证开始，具体进度见 Plan 执行记录。

2026-10-15，M01 已实现版本 / 副本、冲突安全发布与恢复、普通任务进程树、固定输入 / 排队合并、双名额调度、16 次生成预算、配置、Hermes 子进程、模型转发和本机 HTTP / 单例。98 项标准库契约在 Python 3.13.5 / PM Python 3.14.7 通过；真实 AIAgent 配合本机合成 provider 完成筛选、记录 / 原始来源查询、文件 / Shell 发布、503 恢复及第 16 / 17 次验证。业务模块、Desktop、MCP 和 Web 继续实施，当前不能把后台基础可启动等同于完整产品可用。

用户已将 OS 写隔离延至后续独立 Issue；当前普通任务拥有普通用户文件权限，保留副本、业务授权、预算、停树和冲突保护。程序不能保证拒绝或恢复自由命令的目录外直接写入。范围和实际证据见 [M01 执行记录](docs/spec/v0.1.0/4-initial-development/modules/01-runtime/plan.md#2026-10-15g1-冻结及存储实施)；后续 Issue 尚未创建。

产品 Python 要求 3.13+。控制 / Web / MCP 使用项目 `.venv`，由 uv 按锁安装；Hermes 任务使用官方 PM 准备的固定解释器，不往 PM 环境安装产品框架。检查分别核对产品依赖与 Hermes SHA / PM 归属 / AIAgent 导入，不要求两个环境的全部依赖版本相同。`scripts/start.ps1` 使用产品解释器，`-HermesPython` 仅指定任务解释器。

```powershell
uv sync --locked --group dev --group browser
$env:PYTHONPATH = 'src'
uv run --locked --group dev ruff check src/distillai plugins/distillai scripts tests .codex/hooks
uv run --locked python -m unittest discover -s tests -p 'test_product_*.py' -v
```

当前运行控制状态由 `state.sqlite3` 保存；任务 / 提交 JSON 和旧 `config.json` 不再是当前权威，私有配置历史仍在 `config/<version>.json`。新程序发现未迁移的旧数据根时明确拒绝启动。先停止后台、任务树和所有采集入口，等待在途 Hook 结束，再执行离线迁移；保持停采直到核验完成：

```powershell
uv run --locked python scripts/migrate_runtime_state.py --home <data-root> --confirm-writers-stopped
```

迁移备份为同目录旁的独立完整副本，脚本核对内容清单、数据库完整性、原调用次数及配置引用。只有控制数据库和全部内容（包括队列 / cursor）均未产生新写入时，才允许 `--rollback-backup <backup-root>` 恢复；有新写入须保留现状修复，不读取过期控制 JSON。新状态损坏时暂停业务读写，保留健康与停机入口；重启先恢复未完成发布，再开放业务。Desktop、真实模型语义与 CI 仍单独验收。


## 后台基础验证

先按 [M01 环境记录](docs/spec/v0.1.0/4-initial-development/modules/01-runtime/plan.md)准备官方 PM 应用环境，并将实际源码和应用解释器赋给 `$HermesSource` / `$HermesPython`。脚本检查固定 G1 SHA、PM 记录及 SDK 锁，不安装、下载或激活环境。首次启动保存这两个资源位置，后续同数据根可以省略；运行数据与源码分开。

```powershell
$DataHome = Join-Path $env:TEMP 'distillai-local-check'
.\scripts\start.ps1 -Action Check -HermesSource $HermesSource -HermesPython $HermesPython -DataHome $DataHome
.\scripts\start.ps1 -Action Serve -HermesSource $HermesSource -HermesPython $HermesPython -DataHome $DataHome
.\scripts\start.ps1 -Action Check -DataHome $DataHome
.\scripts\start.ps1 -Action Stop -DataHome $DataHome
```

`Serve` 隐藏启动并复用同一实例，`Check` 只报告环境和已校验的实例身份，`Stop` 等待停树与后台退出；均不在输出中打印后台授权。脚本同时提供 `Mcp` 和 `Web`，用法见下文。未设置数据根时默认 `~/.distillAI`；当前业务处理器继续按模块 Plan 实施，不启用个人会话或把合成模型结果当业务验收。

## 产品采集（M02，Desktop 待验收）

新插件位于 `plugins/distillai/`，与旧验证插件 `plugins/distill-capture/` 分开。新插件同步处理 Stop / PreCompact 的 rollout 正文增量及 PostToolUse 固定工具摘要，不调用模型。默认写入 `~/.distillAI/codex/queue/<key>.jsonl` 和 `codex/cursors/<key>.json`；开发测试可通过进程环境 `DISTILLAI_HOME` 指向独立目录。正文与工具共用从 1 开始的物理行号，来源只接受 connector / session_key / 包含端点的行范围。

首次启动后台会保存产品 `src`、Hermes 源码与解释器位置；插件安装缓存中的 dispatcher 由该本机记录找到产品代码，需保持这些目录可用，Python 3.13+ 仍须可从 Desktop 的 PATH 调用。插件启用前先在 Desktop 停用旧验证插件对此会话的采集，并审阅信任新插件的 Hook 定义；旧文件与数据保留，无自动迁移。配置与字段依据 [官方 Hook 文档](https://learn.chatgpt.com/docs/hooks)及[插件打包说明](https://developers.openai.com/plugins/build/plugins)，实际安装 / 触发证据仍按 M02 / G2 记录。

队列先同步，cursor 后替换。写锁竞争时正文等待后续 Hook 补读，本次工具摘要可能丢失；队列成功而 cursor 保存失败时可能重采到新行，不承诺跨位置去重。只修复尚未登记的残缺尾部，字段非法或中段损坏保留并停止，不重编号。错误诊断仅记录事件、session key、阶段、UTC 和错误码，不保存 payload / 正文 / 异常全文。

产品诊断使用 Loguru：数据根 logs 下每个后台 / MCP / 采集进程独占带时间和 PID 的文件。后台 / MCP 的 JSONL 达 5 MB 后轮转并 gzip；短生命周期采集诊断结束即压缩。7 天 retention 由 Loguru 在轮转（采集为结束）时执行；旧 capture-errors.log 保留。退出会排空日志队列，日志故障继续业务；stdout 保留给 MCP / Hook 协议。任务输入、输出和恢复依据仍在业务版本 / SQLite 中，诊断日志只用于定位错误。

采集通知只发送 connector / key，连接与发送共用 200ms 截止，不读响应、不重试、不启动后台。服务失效仍可采集；后台启动及轮询扫描 LF 完成的有效连续行，坏行之后暂不登记。任务登记与采集 cursor 分开，业务处理位置由 M03 结果提交后维护，通知 202 不代表业务处理完成。当前不启用个人会话，G2 的真实 Desktop 触发与 M03 生命周期仍待验证。

## episode 与知识基础（M03 / M04，实施中）

普通材料已接通单活跃 episode、真实轮次、待判断缓冲、程序评分及同事务的处理位置。明确用户归属纠错和新材料证明旧边界错误时的直接修订已接入：旧原文按固定范围读取，新引句经程序核查后才开放对应归属变更。首次没有旧记录时先处理首轮，来源行号不变；规范生命周期计时与不足窗口收尾核心已实现，并通过假时钟及真实 AIAgent 合成链验证；Desktop 事件适配和迟到材料身份判定仍待 G2。

M04 已有详情 / 来源 / 字段权限校验、程序稳定 ID、有向多关系名称图、精确名 / 别名、历史版本和一跳查询。只读 API 为 `GET /v1/knowledge/lookup?name=...`、`GET /v1/knowledge/<id>/neighbors?direction=in|out|both`、`GET /v1/records/<knowledge|relation>/<id>?version=...`，沿本机控制授权或同源浏览器会话。图只保存名称、ID、版本和两端，正文与用户判断留在详情。索引失败返回明确未就绪，详情仍可读取；已提交的后置登记可在恢复和轮询补建，不重跑模型。

M03 → M04 → M05 的真实 AIAgent 配本机合成 provider 已验证观察 / 假设维护；模型语义效果与真实 Desktop 分开验收。episode 分析包括正常空结果均登记 M05。具体进度见[总 Plan](docs/spec/v0.1.0/4-initial-development/plan.md)，需用户补充的信息见[执行待办](docs/spec/v0.1.0/4-initial-development/pending.md)；不将这些基础能力当作完整产品交付。

## 认知、上下文与 MCP 基础（M05 / M07，实施中）

M05 校验实际用户来源、帮助、观察 / 假设引用和定性理解，保护知识正文 / 关系核查。M07 已接通固定版本上下文准备、两列表、只读语义查询、无工具筛选和 compact 选择快照。查询返回实际读到的记录版本，取消只停止该次调用；同文的两个独立调用各有关联。反馈尚未取得可信原始位置时保留待关联，不凭文本相同制造用户表现。

`scripts/start.ps1 -Action Mcp` 使用产品项目解释器启动 FastMCP stdio 服务，公开 query_context / submit_feedback；先通过 `-Action Serve` 启动后台。实际 FastMCP PythonStdioTransport 已验证工具调用、严格输入、反馈幂等及独立后台在 stdio 退出后存活；MCP 自动冷启动在受限 Windows Job 中未通过，后台无法独立启动时明确返回 backend_not_started。退出 stdio 保留此前独立启动的后台，显式 `-Action Stop` 才请求停止。实际 Desktop 插件 MCP 注册 / 工具全名、Hook 注入、生命周期和反馈边界仍待 G2，当前不自动启用个人会话。

实际 SDK / AIAgent 的准备、查询、筛选和取消探针合计 9 次本机合成模型请求，两次 compact 不增加生成。明确 episode 纠错与直接依赖等待状态同清单提交，M03 不编辑认知字段。查询旧判断另附当前等待状态；当前修订对应的 M05 成功后解除直接等待并触发开放会话准备，不增加材料计数。旧候选须经 M07 重新准备才能新选材，compact 保留既定选择。模型语义质量和真实 Desktop 仍待验收。

## Tavily 外扩（M06）

用户已选择 Tavily。默认使用官方免费免 key Search / Extract；需要更高额度时，在本地 Web 保存 `search.api_key`，或在启动后台前设置 `TAVILY_API_KEY`。私有配置优先，环境凭证在本次后台进程启动时固定。实际请求固定到 Tavily 官方 API，复用已固定 Hermes 的请求头 / 结果归一化，不读取 Hermes 个人 `.env`、不启用其他供应商回退，也不引入额外依赖。keyless 的可用性与限流按实际返回处理，见 [Tavily 官方说明](https://docs.tavily.com/documentation/keyless)。

模型 endpoint / model 尚未配置时，不启动外扩等待或推进覆盖。就绪后默认每 3600 秒登记最多十个知识点的任务，以稳定 ID 循环游标避免频繁变化的对象挤掉旧节点；配置变化不清覆盖进度。成功提交才记完成依据，失败保留原任务 / 次数。搜索摘要只是候选，`fetch_page` 实际读到的片段才保存 external 来源，最多 16,000 字符并保留截断状态。限流 / 搜索失败 / 正文失败不能当作成功空结果；已取得依据的部分结果可以保留其余缺口。

后台接口 `POST /v1/expansion-requests` 接收 `client_request_id, knowledge_refs, question, reason`，供显式要求重新探索；相同请求 ID 重试复用原任务，不能用同一 ID 更换问题。`GET /v1/expansion-status` 返回覆盖与待办，`POST /v1/tasks/<id>/retry` 只重试已停止失败任务且不重置额度。网络请求返回较晚时仍核对任务有效性，不把本地取消声称为远端已经撤销。

外扩 → M04 只维护实际主张和来源，不因外部内容登记用户已掌握分析。实际 AIAgent + 真实 Tavily 免 key 的外扩 / M04 / 用户指定编辑链路共 11 次模型请求通过；该探针的模型响应为 localhost 合成数据，真实语义质量仍待验收。

## 本地 Web（M08，实施中）

```powershell
.\scripts\start.ps1 -Action Web -HermesSource $HermesSource -HermesPython $HermesPython -DataHome $DataHome
# 同一数据根已记录资源位置时：
.\scripts\start.ps1 -Action Web -DataHome $DataHome
```

`Web` 启动 / 复用同一后台，再打开一次性浏览器引导地址；后台 bearer 不进入 URL。地址只可交换一次，浏览器取得 HttpOnly / SameSite 会话后跳转到 `/`；后台重启或会话失效后重新执行 Web，不收藏引导 URL。四入口是知识 / 关系、交流片段、处理历史与配置。原生 HTML / CSS / JS 同源加载，无 npm / Vite 工程和外部资源请求；原文以文本展示。列表初始 20 条、最多 100 条，游标绑定筛选；来源只接受引用，历史版本只按完整 SHA-256 打开。

配置显示实际保存版本、运行任务使用的旧版本及字段错误。密钥不回传，空输入保留原值；勾选清除时用 JSON `null` 明确删除私有配置中的 key，环境凭证需另行调整并重启后台。密钥不进入页面持久缓存。配置写入检查 Origin / Host / CSRF，同期版本冲突保留输入。

知识 / 关系编辑提交指定字段、加载时版本与原因，登记异步 M04 任务；202 只表示登记，任务实际提交后才显示成功。失败和冲突保留输入，不自动合并。任务详情可回查当时输入 / 输出 / Prompt / 脱敏配置和实际生成请求；旧版本只读。

交流片段详情可载入同会话另一个已有片段，填写两者应归属的来源行及原因。`POST /v1/episode-corrections` 接收 `session_key, episode_refs, assignments, reason`，引用带加载时版本；完整保留原来源且同轮不拆分，不新增片段或跨会话搬动。修订后接续 M04 / M05。知识 / 关系详情中的“纠正关于我的判断”填写实际表现、帮助条件和原因；`POST /v1/cognition-corrections` 接收 `record_kind, record_id, expected_version, performance, help, reason`，使用独立 user_submission 来源，不伪造 episode。两个入口均返回 task_id，按实际提交确认保存；旧判断等待重新分析时明确提示。

合成浏览器验证覆盖四入口、分页 / 空状态 / 筛选、未知记录重试、脚本标签文本显示、来源和历史版本、两个窗口的实际提交 / 冲突、延迟详情 / 配置保存不覆盖新输入、Tab / Shift-Tab / Enter，以及 390 像素窄屏无横向溢出。页面维护执行器为合成回调，真实 AIAgent 提交链另有独立探针。五项 Playwright 永久回归保护冲突 / 失败留输入、迟到详情 / 保存和文本安全；布局、固定 DOM 与配色不写像素基线。

```powershell
uv run --locked --group browser python -m playwright install chromium
uv run --locked --group browser python -m unittest discover -s tests/browser -p 'test_*.py' -v
```

历史记录（重写前）：2026-10-16 为 **112 / 140 步**，两个解释器各 **160 项产品测试通过**。M01 运行基础和 M08 Web 的模块 Plan 已完成；整体仍在执行。新材料纠错链 12 次合成模型请求、真实 Tavily 外扩 → M04 → M07 → 用户编辑 14 次请求、SDK 查询 / 筛选 / compact / 取消 9 次请求均有独立证据。当前待办见[执行待办](docs/spec/v0.1.0/4-initial-development/pending.md)，证据和 checkbox 见[总 Plan](docs/spec/v0.1.0/4-initial-development/plan.md)。

关联回查使用 `GET /v1/related?record_id=<id>` 或 `?episode_id=<id>`，沿同源认证 / 分页读取实际保存的知识、外扩、子图 / 两列表和本轮选材版本；模型文本中偶然出现 ID 不构成关联。选材仅准备、Hook 已输出和平台 / 助手采用分别展示。等待状态下可显式“按最新依据重新分析”：`POST /v1/reanalysis-requests` 接收 client_request_id、record_id、reason，创建最新固定依据的 M04 → M05 任务；同请求复用，不重置或覆盖原失败任务。
