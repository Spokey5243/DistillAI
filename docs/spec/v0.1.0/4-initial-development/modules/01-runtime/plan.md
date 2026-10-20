---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M01：SDK 直连、框架服务与共用运行 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、复用和文件

依据[统一 Design M01](../../design.md#runtime-contracts)及[总 Plan](../../plan.md)。在现有产品上替换基础设施；任务、快照、冲突提交、预算语义和普通任务停树继续复用。直连私有凭证边界已随 2026-10-17 统一 Design 修订 3 与本稿获批，实际验证仍逐项记录。

Modify：`src/distillai/hermes.py`、`tools.py`、`runtime.py`、`server.py`、`startup.py`、`config.py`、`__main__.py`、`scripts/start.ps1`、`pyproject.toml`、`uv.lock`。`storage.py` / `windows.py` 替换通用锁 / 系统绑定，发布、冲突恢复和 Job 停树策略保持；字段模型还涉及 `sources.py` 及各归属模块。复用 `tests/test_product_{runtime,config,http,startup,tools,storage,windows}.py`（花括号为文件组说明，运行命令见下）。

SQLite 增补：Create `src/distillai/state.py`（只封装具体控制状态 SQL / 事务，不建立通用 Repository）、`scripts/migrate_runtime_state.py`（离线导入旧控制状态）、`tests/test_product_state.py`（旧组遗漏的事务并发契约）。任务列表 / 历史读取、配置当前指针、提交清单与恢复调用同步经过 Store / Runtime 既有入口；测试中直接读取 `tasks/*.json` 的启动 fixture 改为公开状态查询。Ruff 的规则 / dev 组和 Playwright 的 browser 组由本模块统一写入 pyproject / uv.lock；浏览器用例由 M08-R3 实施。

## M01-R1：Hermes 直接调用模型，程序接管额度

- [x] **R1.1 固定适配证据。** 在已固定 Hermes 源码逐项核对 `run_agent.AIAgent`、`client_lifecycle._create_request_openai_client`、`agent_runtime_helpers.create_openai_client`；记录共享、请求专用、重建和重试链。先用既有 AIAgent 合成探针复现正常 / 503 / 第 16 与 17 次行为，不安装或修改上游。
- [x] **R1.2 接入唯一 SDK 客户端构造点。** 在 `hermes.py` 的窄 AIAgent 适配中覆盖固定版本 `_create_openai_client`，向上游 builder 提供带计数钩子的 HTTPX client，保留原 TLS / keepalive / 关闭方式。所有实际请求前取父进程持久预算许可，原 SDK 直连配置 endpoint、处理流 / 错误 / retry。SDK 隐式重试保持上游的 `max_retries=0`；Hermes 外层每次重试重新经过同一门禁。仅接公开 HTTPX 接口，不复制上游 request builder、provider transport 或流式解析。
- [x] **R1.2a 保留模型参数。** 原代理覆盖的配置改用 `AIAgent(max_tokens=..., request_overrides=...)`：max_tokens 走构造参数，temperature / top_p 走 request_overrides，当前允许的 DeepSeek thinking 配置走其 extra_body。以实际发送请求核对最终值和 model / endpoint；不让 Hermes 默认值覆盖固定任务配置，不在 HTTP 字节层重写 JSON。模型连接信息与实际参数取本任务私有配置版本，已启动任务不跟随新配置漂移。
- [x] **R1.3 复用标准库 Connection。** 使用 `multiprocessing.connection.Listener/Client(family='AF_PIPE')` 给单个任务建立认证的 Windows 管道连接，标准库处理分帧 / EOF / 握手；用 `send_bytes` / `recv_bytes(maxlength=8*1024*1024)` 传严格 JSON，不用 pickle send / recv，不自写 stdout 行协议或缓冲解析器。现有 stdin 仅送一次私有 pipe 地址 / authkey，Popen / PM 解释器与先入 Job 再 resume 保留；连接后交付配置、输入、预算确认、程序工具和结果。父进程绑定该任务、校验操作 / 阶段 / 尺寸、串行请求；stdout 不承载业务协议，模型响应仍由 SDK 处理。
- [x] **R1.3a 先证明阻塞等待可退出。** 在 R1.2 业务接入前，用实际 Windows 父子进程分别验证 accept 前子进程未连接、连接后不完成认证、认证后不回复、读写中取消和父进程死亡。连接 / 认证分别设置有限截止；消息等待按现有调用截止或取消信号结束，不新增模型总执行时限。连接由明确的通信执行单元持有，控制层负责发出取消、停止 Job 并确认等待线程退出；逐项记录所用公开接口、关闭 / 中止顺序和有界回收时间。poll / wait 只用于已建立连接的可读等待，不能当作 accept / 认证超时；关闭句柄能否唤醒实际阻塞操作必须由探针证明，不能仅取消 AnyIO 等待或遗弃后台线程。任一阶段不能有界退出则不进入 R1.2，也不把临时换成自写 RPC 当作完成。
- [x] **R1.4 保留数据和失败契约。** 连接配置只从固定私有配置经管道私有 bootstrap 交 SDK，不把 key 加入持久 `task.inputs`、`visible_inputs` / Prompt / 历史；请求快照沿现有脱敏方法，移除代理时把仍需使用的 `_history_request` 迁到执行适配处，保留真实 Prompt / 工具 / 请求 / 最终结果版本。额度许可必须先落盘再回复；父进程死亡 / EOF / 取消终止等待，Job 确认停止才回收名额。连接前可确认未发出用同 attempt_id 退额，其他未知失败保守计数；验证恢复沿原 Runtime，不用 finally 统一退额。
- [x] **R1.5 删除旧代理路径。** 直连探针通过后删除 `BackendServer.model_base`、`_Handler._model`、模型 `/internal/tasks/{id}/v1/*`、`_program_tool` HTTP 客户端和任务 proxy token 逻辑，仅在确无剩余调用者后删除相关方法。程序评分 / 读取审计 / ID / 来源工具改用管道上的原业务函数。全仓查调用者，不能留下“新 SDK → 本机代理”或第二套模型传输。
- [x] **R1.6 验证实际 AIAgent。** 同一真实执行器验证文件 / Shell 工具、评分往返、只读 query、无工具筛选；分别造 503 后恢复、客户端重建、断流、连接拒绝、重启续额、16 次完成和 17 次拒发。合成 provider 记录真实到达请求数，与任务账本核对；额外辅助生成无法覆盖就保持关闭。取得一次获准实际模型的流式工具往返，只报机械通过 / 语义未验的真实范围。

## M01-R2：FastAPI / Uvicorn 替换手写 HTTP

- [x] **R2.1 先保留路由契约。** 从现有 HTTP / Web / MCP 用例列出路径、method、业务载荷、status、error code 和授权要求；将测试启动 fixture 换为真实 ASGI 应用，原业务断言继续使用。FastAPI 默认 422 等若不同，按现有公开错误契约做窄映射，不让替换框架静默改 API。
- [x] **R2.2 使用框架能力。** `server.py` 提供 app 创建入口、明确路由、Pydantic 请求模型、Dependencies / 异常处理、JSONResponse / FileResponse；Host / Origin / CSRF 和读取 body 实际尺寸仍作边界检查，不仅相信 Content-Length。路由调用现有业务函数；移除 Handler、手动 headers / 状态行 / chunk 处理和字符串路由大分支。默认文档 / 静态子路由也必须遵守本机授权策略。
- [x] **R2.3 统一生命周期。** 用 FastAPI lifespan 与 Uvicorn 单进程启动 / 关闭；沿现有启动锁持有一个实例、一个业务 worker。服务 ready 后才发布 instance 信息；同步存储 / 业务工作不阻塞 ASGI event loop，沿现有 worker / 框架线程执行。停止先拒绝新任务、停树 / 恢复，再结束服务、清实例；不以 FastAPI BackgroundTasks 代替持久任务队列。
- [x] **R2.4 验证框架入口。** 无授权、非法 Host / Origin、超限 body、未知路由、失效任务、409、慢模型时 health / config、并发启动和显式停机复跑原用例；至少一项真实监听 socket 的探针核对绑定地址与启停，TestClient 结果不能替代操作系统生命周期。

## M01-R3：项目依赖环境和启动

- [x] **R3.1 按安装归属锁依赖。** 控制 / Web / MCP 由 uv 项目环境运行，Hermes 子进程由固定 PM 应用环境运行。实际直接导入的 FastAPI、Uvicorn、HTTPX、Pydantic、FastMCP、Loguru、NetworkX、AnyIO、jsonschema、Windows pywin32、Portalocker、ItsDangerous、pydantic-settings、APScheduler 3.x、pathvalidate、boltons 声明为直接依赖，由 uv 解析整组兼容版本并生成锁。候选 FastMCP 4.1.0 / Loguru 0.7.3，MCP SDK 不再独立于上层 FastMCP 强行冻结；只有直接使用底层 SDK 才保留直接声明。SQLite 使用标准库 sqlite3；Ruff 放 dev 组、Playwright 放 browser 组，均不进入产品运行依赖。先拆清 `task-child → hermes → runtime/storage/sources` 当前导入链，任务入口不能因父进程的 Store / schema 顶层 import 被迫加载产品环境包；确需共享的执行模型逐项核对 PM 已有版本，不能假定传递包兼容。Web / 图 / Loguru 不拖进 PM，不往 PM 安装产品框架、不复制整份 PM 依赖、不手改 lock。
- [x] **R3.2 修正环境检查和解释器路由。** `startup.check_environment` 拆清产品依赖检查与 Hermes SHA / PM receipt / AIAgent 导入检查；不要求 PM 匹配全产品锁。启动脚本由产品解释器执行，`-HermesPython` 只定位任务解释器；MCP / Web 不再自动切 PM。保存的 launch 配置按实际职责读取，Windows 底层解释器 / launcher / suspended → Job → resume 沿已有已验证实现。
- [x] **R3.3 统一普通本机客户端。** 启动和 MCP 复用 HTTPX 的 request / timeout / 错误映射，loopback 禁用环境代理、不跟随外部 redirect；不新建通用 HTTP 封装层。采集通知继续不读响应，200ms / 不启动后台语义不因客户端替换改变。
- [ ] **R3.4 同步本地与 CI。** 更新根 README、Python / Actions 规则、原 Windows CI job 的项目锁安装和测试命令；仍无模型 key / Hermes 下载 / Codex CLI。记录 Check / Serve / Web / Mcp / Stop 的实际解释器、退出和实例身份，不把未验冷启动写通过。
- [x] **R3.5 接入 Ruff。** pyproject 的 `[tool.ruff.lint]` 初始 select 为 `E9,F63,F7,F82,F401,F811`，检查 src/distillai、产品插件、scripts、tests 和 .codex/hooks。运行下列命令，修复命中的真实未定义名称 / 无用导入等；不启用全量风格规则或顺便 format 全仓，不用整体 ignore / noqa 掩盖问题。开发组安装与 CI 命令同步 Python / Actions 规则；规则配置核对是一次性验证，不新增检查配置字符串的永久测试。

## M01-R4：复用业务回归并清点删除

- [x] **R4.1 复跑任务 / 保存契约。** 固定输入、优先级（筛选 / 查询 / 普通）、普通单名额 + 筛选独立名额、最后允许生成、取消 / 授权收紧、旧 episode 输入不得发布、快照 / 提交 / recovery_conflict、配置版本各跑原组。不得为换 Web 框架重写 Store / Runtime 状态机。
- [x] **R4.2 删除重复基础设施并记录。** 一次性查无 BaseHTTPRequestHandler / ThreadingHTTPServer / 模型代理剩余调用；解释必须保留的 Windows 句柄代码和产品规则。记录新探针 / 测试 / 锁 / 环境和缺口，替换部分未验前保持本稿 draft / 未完成，不继承旧 M01 implemented。

## M01-R5：补齐通用能力复用

- [x] **R5.1 字段模型复用。** 配置、SourceRef / RecordRef、工具参数和各模块记录的结构用 Pydantic strict / extra=forbid 及 TypeAdapter；共用引用模型在 `sources.py`，领域结构留归属模块。工具 schema 由同一模型生成，已有上游 JSON Schema 用 jsonschema 校验；删除被替代的字段类型 / required / 枚举遍历，保留跨记录来源、权限、前后版本 / 业务判断。字段错误仍能映射原 API 路径，既有非整数 / bool / 非有限数 / 未知字段用例结果不变。
- [x] **R5.2 复用 pywin32 绑定。** 在 `windows.py` 用 win32job / win32file / win32api 已有封装替换覆盖到的 ctypes 声明与结构，保持原访问掩码 / share mode / flags；Job limits 用库的字典结构，句柄用 PyHANDLE 管理。对 NtCreateFile 根句柄相对打开 / rename、未覆盖的挂起恢复等列出残余窄适配和原因，不重写 ntdll SDK。复跑全部实际 Windows 组，覆盖路径替换、元数据 / ADS / 硬链接和父子孙停树；库能 import 不等于这些行为通过。
- [x] **R5.3 复用普通文件锁。** `Store.locked` 与启动 `_lease` 改用 Portalocker 的文件锁 / RLock，Store 外层仍用 threading.RLock 保证跨线程串行，启动竞争使用非阻塞获取。核对相同锁文件身份、嵌套计数、释放和异常；保留现有跨进程用例，补旧用例没有的嵌套 / 跨线程路径。不得用普通 sidecar lock 替换文件发布的句柄身份保护。
- [x] **R5.4 用 Loguru 写诊断。** 产品解释器内配置 `logger.add` 的 serialize、rotation / retention / compression，业务直接 `logger.bind` 附 task / session / stage / error_code；不写 Formatter、文件轮转 / 清理器或 Logger 抽象。显式 diagnose=False / backtrace=False，不记录任意异常正文、原文或 key。后台队列 sink 在退出 complete；产品 Hook / MCP 进程分别初始化独占 sink。PM 任务进程沿 Hermes 日志配置，产品诊断只传白名单字段给父进程落 Loguru，不在 PM 导入 Loguru，不把 enqueue=True 当跨解释器共享队列。MCP stdout 只协议，日志故障继续回答。Store.event 的持久事件保留原语义，SQLite 已接管的控制状态不能依靠诊断日志恢复。
- [x] **R5.5 用 FastAPI 官方测试工具。** API / Web / 授权 / 参数 / 错误 / Cookie 组直接 `from fastapi.testclient import TestClient`，`with TestClient(app)` 管理 lifespan；用 `app.dependency_overrides` 注入临时 Store / Runtime / 授权依赖，finally 清空。删除手写 HTTP 测试客户端 / 服务线程；HTTPX MockTransport 只替外部上游，不替被测 app。现有 unittest 可直接使用 TestClient，不因为官网示例用 pytest 就迁移全部测试。socket / 流式断开 / PM 跨进程计数 / Job 仍真实验证；Connection 验错 authkey / 超长消息 / EOF / 取消及跨解释器往返，断言公开结果和无副作用。
- [x] **R5.6 复用启动配置加载。** `startup.py` / `__main__.py` 用 pydantic-settings 的 BaseSettings 和内置 JSON source 读取启动位置；显式固定 CLI 参数 → 获准 DISTILLAI 环境 → 指定数据根 launch.json → 默认值优先级。关闭 dotenv 与未声明 secret 目录源，不读个人 Hermes 配置；原 CLI 由 argparse 解析后传入初始化源。版本化业务 Config 不用环境热更新，任务仍引用固定私有版本。复用 startup / config 用例验证路径优先级、缺参和敏感字段不输出。
- [x] **R5.7 复用定时触发。** FastAPI lifespan 中启动单个 APScheduler 3.x AsyncIOScheduler，用 IntervalTrigger 调用原扫描 / 外扩资格检查、DateTrigger 调用已有 episode 到期判定；修改配置 / 新轮开始分别 reschedule / remove_job。只用内存 job store，重启从原持久终止 UTC / 外扩进度重建并立即检查已到期事件，max_instances=1 / coalesce 防重复唤醒。episode 的一次性到期 job 显式设 misfire_grace_time=None，允许进程未重启但休眠 / 暂停跨过截止时间后补执行；仍使用原截止和事件代次，不从恢复时刻重新计时。周期扫描 / 外扩只合并唤醒并检查当前资格，不补造每个错过时刻的业务任务。回调仍复核来源、事件代次 / 权限 / 固定输入再登记 Runtime 任务；不复制 APScheduler 调度算法，不让 scheduler job 的成功状态代替业务提交，不另设 APScheduler 数据库或 Redis。
- [x] **R5.8 复用路径词法校验。** `storage._relative` 的保留设备名与非法字符检查改调用 pathvalidate Windows 校验；先对原始路径段拒绝空 / 绝对 / `.` / `..`，再调用库，避免路径规范化先吞掉这些输入。只 validate、不 sanitize；长度规则按已有合法路径回归核对，不静默截断。目录授权、句柄身份、junction / ADS / hard link 和恢复规则继续检查，库处理词法不等于具备文件权限保证。
- [x] **R5.9 复用原子单文件写入。** `storage.atomic_json` 采用 `boltons.fileutils.atomic_save` 的同目录临时文件 / fsync / 替换 / 异常清理，产品只负责严格 JSON 编码、UTF-8 LF 和既有锁。临时 part_file 使用任务唯一名称，不覆盖其他写者或盲删残留；核对 Windows 覆盖、占用和中断失败仍保留旧配置。仅替单文件保存通用部分，不把 AtomicSaver 当多文件事务 / 用户文件冲突恢复，复用 storage / config 用例验证。

## M01-R6：SQLite 运行控制状态与离线迁移

本节具体持久化与迁移方案已随 2026-10-17 重写稿获批。保留 Store / Runtime 对外返回的任务与提交结构，替换内部保存方式；不将模型、浏览器或 Hook 接到 SQL；真实用户数据迁移仍需明确授权。

- [x] **R6.1 固定权威状态与 SQL 约束。** `state.py` 在数据根管理 `state.sqlite3`。任务行保留稳定 ID、状态、顺序、额度及输入 / Prompt / 结果版本引用；任务去重键和合并别名用唯一键关联 task_id；依赖、生成 attempts、提交清单 / 阶段、当前配置指针同库保存。模型调用次数只保留一份权威值，返回 JSON 从该值组装，不能再维护磁盘任务 JSON 的第二份计数。attempt 用 `(task_id, attempt_id)` 唯一约束；重复 attempt 沿既有拒绝契约且不能再次扣额。领域内容、原始队列、采集 cursor、配置历史正文、不可变字节快照和原业务事件文件保持原格式。数据库、journal / wal / shm、迁移备份全部纳入私有路径保护，不能出现在 Agent 可发布范围或静态资源中。
- [x] **R6.2 使用短事务与明确线程归属。** 标准库 sqlite3 使用参数化 SQL、foreign_keys=ON、synchronous=FULL、有限 busy timeout（初始 5 秒）、显式事务模式。本轮使用本地磁盘数据库及默认回滚日志，不叠加 WAL 调优。通过 `isolation_level=None` 和显式 BEGIN IMMEDIATE / COMMIT / ROLLBACK 管理读后写单元，不混用隐式事务配置；schema 版本以 user_version 记录，较新未知版本明确拒绝打开。连接在执行该完整同步事务的工作线程内创建 / 使用 / 关闭，禁止跨线程复用和在 event loop 中直接等待 SQL。锁顺序统一为既有 Store 发布锁在前、短 SQL 事务在后；事务外调用模型、搜索、IPC 或等待 Job，避免长时间持写锁。取消协程后仍核对事务结果，不误报已回滚。
- [x] **R6.3 替换所有控制状态调用者。** Store.read_task / read_commit / 保存入口与 Runtime.tasks / register / register_increment / dispatch / reserve_generation / release_unissued_generation / retry / cancel / recover 接到同库；Config.read / private / update、Web 历史 / 启动检查及相关测试 fixture 同步，删除生产环境直接扫描 tasks / commits JSON 的路径。任务登记、去重键 / 别名、依赖在同一事务保存；额度与 attempt 在同一事务校验和更新，COMMIT 成功后才能回复生成许可，数据库忙 / 失败时拒发。配置更新全程持 Store 锁并核对 expected_version，选择未占用版本号，以不覆盖方式保存私有版本文件，再条件更新当前指针；数据库失败遗留的文件不复用覆盖，版本号允许跳号。两个更新竞争只允许一个生效，已引用的配置历史不能被失败更新改写。通过现有 API 返回相同结果，任务进程不直接打开数据库。
- [x] **R6.4 保留数据库之外的文件恢复。** 输入 / 结果不可变字节先完整落盘再保存哈希引用。发布前将意图和文件基线持久化到提交清单，文件替换仍使用既有句柄保护 / 冲突检测；全部目标核对完成后，把提交完成、任务结果和数据库归属的后续状态在短事务中更新。文件归属的处理位置仍通过原恢复协议关联提交 ID，不能在文件发布前推进。沿 Design 原有恢复规则：数据库未 committed 时，无论只写部分文件还是全部写完，均按清单校验文件身份 / 本次版本并撤销已应用部分；数据库已 committed 时，只补处理位置 / 后继登记 / 索引，不撤销已提交内容、不重跑模型或清额度。发现用户再编辑、内容缺失或不能安全撤销时进入 recovery_conflict，保留前后版本，暂停冲突范围后续写入；数据库标完成也不能掩盖缺失内容。运行中 sqlite3.Error 同样进入失败处理，不能只沿旧 OSError 分支；若数据库持续不可写而无法记录恢复进度，控制层先停止派发和发布，并阻止读取受影响的半成品。无法可靠确定范围时暂停该数据根的业务读写，仅保留健康 / 诊断 / 停机入口，保留已持久清单和文件，恢复可用后先完成恢复再开放。清理不得依赖下一次数据库写入成功才能停树或结束等待，亦不得谎报恢复成功。启动恢复完成前不开放可读半成品的业务接口；未引用的临时文件保留，不在本轮自动垃圾回收。
- [x] **R6.5 离线迁移与回退。** `scripts/migrate_runtime_state.py --home <data-root>` 要求后台与任务树已停、持有原数据根互斥且无未解决发布恢复；只先在合成副本演练。开始备份前还须暂停所有指向该数据根的采集入口，等待在途 Hook 结束，确认队列 / cursor 不再写入；Store 锁不覆盖 Hook 队列锁，不能据此声称数据根静止。保持停写直到数据库安装和核验结束，中途无法确认停写则中止迁移。备份整个数据根并记录包括队列 / cursor 在内的业务持久文件清单与哈希，源与备份逐项核验；在同目录临时数据库一次事务导入旧任务 / attempts / 别名 / 依赖 / 提交 / 配置指针，核对现有计数、顺序与内容引用，执行 integrity_check 与 foreign_key_check。全部通过、关闭连接后才安装 state.sqlite3；失败保留旧文件和错误，不能留下可用半库。再次运行在相同完整迁移标记时核验后退出，既有非迁移库或来源变化则拒绝覆盖。新程序发现旧控制文件但无库时要求显式迁移，不能当空库启动；迁移后只读 SQLite 权威状态。旧控制文件保留为只读证据，不双写；旧版本不得针对迁移后数据根启动。只有重新停止全部写入者、核对切换后零新写入时可恢复完整迁移前备份；核对必须包含 Hook 队列 / cursor 和领域文件，不能仅检查数据库。已有新写入或无法确认时保留现状修复 / 另定导出，不能用过期 JSON 回退。工具存在不授权本轮操作用户真实数据。
- [x] **R6.6 验证长期一致性。** 复用 storage / runtime / config / startup / web / corrections 组；仅在 test_product_state.py 增加旧文件实现组遗漏的并发事务用例：相同登记键只生成一个任务、两个连接竞争最后一个额度只放行一次、重复 attempt 不重复计数、数据库锁超时不发送模型请求、事务失败不留部分状态、重启保留预算。原发布中断用例改走真实数据库，分别核对部分文件已写 / 全部文件已写但 DB 未 committed 均安全撤销，以及 DB 已 committed 只补后续状态；保留外部改动导致 recovery_conflict 的覆盖。补现有组未覆盖的存活进程数据库写失败：使用真实数据库的写锁超时或容量限制触发失败，检查拒绝继续发布、半成品不可读、停树可结束、数据库恢复后可按清单恢复；不能只用 mock SQL 抛异常代替这些证据。迁移的停采 / 等待在途 Hook、备份与队列 / cursor 一致性、恢复采集后拒绝旧备份回退、旧 JSON 不再被读取和文件布局是合成副本上的一次性演练证据；数据库约束、取消 / 崩溃数据完整性保留为永久测试。

## 验证命令、测试必要性与依赖

先 G0，R3.1 准备环境 / 导入边界，R2 框架入口可独立验收，再 R6 SQLite → R1.1 / R1.3 / R1.3a 管道可取消探针 → R1.2 及剩余直连额度项 → R3 剩余启动项 → R5 → R4 回归。Ruff 随相关改动运行，R5 的文件锁 / atomic_save 只处理仍归属文件的状态。异步协调运行在 asyncio / AnyIO，阻塞事务与文件操作放工作线程；同步 AIAgent 留独立进程。HTTPX 钩子、Connection、SQLite 迁移和 pywin32 替换均未实测，未通过的组合不继承旧证据。

```powershell
$env:PYTHONPATH = 'src'
uv run --locked --group dev ruff check src/distillai plugins/distillai scripts tests .codex/hooks
uv run --locked python -m unittest discover -s tests -p 'test_product_state.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_http.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_runtime.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_startup.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_config.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_tools.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_storage.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_windows.py' -v
```

预期各 `OK` / 退出 0；Windows 关键能力 skip 不算通过。已有用例保护业务和安全契约；新增只补直连计数、客户端重建和管道断开这些旧代理用例不能覆盖的路径。类名 / 删除情况 / 环境 receipt 是一次性核对。实际 provider / Job / ASGI 证据单独记录，不复用旧代理探针的“通过”。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第一批重构证据

项目 uv 环境完成锁定安装，PM Python 3.14.7 / 固定 Hermes SHA 的 AIAgent 导入检查退出 0；产品环境与任务环境已拆开。FastAPI / Uvicorn 接管 HTTP，显式路由复用原业务；API / Web 以官方 TestClient 和 dependency_overrides 运行。旧 Handler、模型代理、HTTP 程序工具入口及任务 proxy token 已删除；请求历史脱敏转到执行适配。

SQLite 已接管任务、去重键 / 别名、依赖、attempt / 次数、提交清单和配置指针。原存储崩溃 / 冲突测试改走数据库；真实写锁超时测试验证未发送模型、停树可结束、业务不可读、重启恢复。离线迁移工具通过合成副本的完整备份、重复核验、预算保留、零新写入回退和新增 Hook 材料后拒绝回退；没有迁移真实数据。修复源读取中新建 Store 重入文件锁的死锁，现有纠错组复跑通过。NetworkX 替换手写邻接；Portalocker / pathvalidate / boltons 替换普通锁、路径词法和单文件保存，Loguru 记录白名单采集诊断。

TaskPipe 采用标准库认证 AF_PIPE / send_bytes / recv_bytes；阻塞 accept / 认证由归任务 Job 的通信进程持有，公开 Process 终止 / join 提供有界回收，不遗弃等待线程。连接前、认证未完成、错误密钥、断开和正常往返已在实际 Windows 通过；跨 PM 主调用与父进程程序工具通过。实际 AIAgent 新探针七场景通过：screening 1、query 2、source 2、文件 / Shell 维护 3、503 恢复 3、第 16 次有效完成 16、第 17 次拒发 16。发现 SDK 将任意发送钩子异常包成连接错误而重试；窄 HTTPX send 适配在额度拒绝时返回本地 400，不发送请求，重跑通过。模型请求编码 / TLS / SSE / 解析 / 模型循环仍由原 SDK 执行。

当前完整产品组 178 tests / OK（39.739s）；Ruff、uv lock --check --offline、git diff --check 退出 0。新增 SDK 组 4 项与 IPC 组 3 项，旧 HTTP 代理用例移至新 SDK 契约覆盖；没有为删除名称写断言。证据在 .artifacts/after-direct-all.log、direct-hermes-probe.log、direct-hermes-results.json 和 probe_state_migration.py。尚未完成全部 M01 / G1：模型参数探针、父进程死亡 / 大消息等完整 IPC 窗口、剩余通用能力、真实模型与 Desktop / 搜索新组合仍需后续证据。没有 Commit / Push 或远端写入。

## 2026-10-17 第二批：原生框架、真实 stdio 与浏览器回归

FastAPI lifespan 使用 APScheduler，Uvicorn 实际监听后才发布 instance。忙扫描时的新任务唤醒丢失已先用回归复现，再借框架完成事件合并补唤醒；扫描间隔设 3600 秒仍及时执行，启动组 6 项通过。HTTPX 启动 / MCP 客户端、pydantic-settings 优先级与官方 TestClient 均经现有组验证。实际 AIAgent 七场景再次通过，43 个真实到达的合成 provider 请求同时核对 model / max_tokens / temperature / top_p / DeepSeek thinking；登记后改配置不改变已登记任务参数。完整 IPC 窗口、剩余字段模型 / Win32 / 日志与休眠仍未全部完成。

完整证据、收尾测试结果与范围见[总 Plan](../../plan.md)第二批执行记录；本地通过不代替 GitHub CI，未迁移真实数据或执行远端写入。

## 2026-10-17 恢复后第三批：Windows、管道与到期恢复

Goal 恢复 active 后完成 pywin32 覆盖接口迁移；句柄相对打开 / rename、挂起恢复和精确 100ns FILETIME 保留为经实际探针确认的窄适配。库的日期类型损失末位精度，带 RootDirectory 的 rename 返回 WinError 87，原生方式成功；pywintypes.error 映射为原 OSError 契约。Windows 9、存储 23、采集 11 项通过。

IPC 六项实际 Windows 组覆盖未连 / 未认证 / 不回复、双向阻塞写、父进程死亡及有界回收，不能只以 poll 冒充 accept / 认证截止。Store 嵌套 / 跨线程和进程死亡释放补齐，SQLite 状态组 9 项通过。调度组 7 项验证进程暂停跨截止只登记一次、新 request 使旧截止失效；真实物理休眠仍属单独验收。完整产品 192 tests / OK、实际 PM AIAgent 七场景 43 个合成请求通过，原模型参数 / 次数固定契约保留。

证据与原生残余原因见[总 Plan](../../plan.md)第三批和 .artifacts/third-win32-gaps.json、ipc-complete-phases.log、third-scheduler-late.log。字段模型 / 工具 schema、日志整合、剩余故障窗口与接入仍未全部完成。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

共享引用与领域模型、工具参数及生成 schema 已接通；本轮 192 项完整产品与 5 项浏览器通过，实际 PM AIAgent 的 43 请求预算组、Episode / 认知链、新材料修订和真实 Tavily 扩展链复跑通过。R5.1 仍有 HTTP 请求 / 剩余记录清点，R2.2 / R5.4 / R6 故障闭环继续未勾；APScheduler 正常停机取消诊断待生命周期整理。细节与合成验证边界见[总 Plan](../../plan.md)。

## 2026-10-17 第五批：HTTP 与 MCP 请求模型

FastAPI 各写路由绑定 Pydantic 请求模型，先执行原认证 / 实际 body 字节限制再校验，业务仍在框架线程与 Store 锁内。配置版本非整数保留 409，部分配置错误仍返回字段路径，任务 / 重试 / 停机等旧错误码与无副作用回归通过。完整产品 193 项与浏览器 5 项通过，R2.2 完成；R5.1 剩余 IPC / 生命周期 / 交付 / 持久控制结构继续清点。见[总 Plan](../../plan.md)第五批。

## 2026-10-17 第六批：Loguru 进程日志与停机排空

后台 / Runtime / 父执行器采用 Loguru 独占进程 sink、白名单字段、UTC、排空、轮转 / 压缩 / retention；ChildDiagnostic 在父进程校验并只记录 code / stage，PM 实际导入未加载 Loguru 等产品框架。独立调度任务先由公开事件排空再 shutdown，新增回归由旧实现失败转通过，完整产品 197 项及浏览器 5 项通过，R5.4 完成。见[总 Plan](../../plan.md)第六批。

## 2026-10-18 第七批：存活进程数据库故障与文件恢复

补齐连接建立失败的隔离路径、已初始化数据根缺库拒绝重建、重复依赖合并及已提交输出缺失冲突。真实 SQLite 写锁超时分别覆盖部分 / 全部文件已写但未 committed；当前根 API 隔离，停止不依赖数据库写入恢复，重启按原清单撤销，预算与不可变版本保留。已 committed 缺失内容保留标记并暂停重叠写入，人工修复后只补登记，不重跑模型或覆盖用户正文。

完整产品 205 项 / 95.213s、Chromium 5 项 / 18.661s 通过；实际 PM AIAgent + 监听服务在真实 SQLite 写失败时零上游生成请求，数据库仍锁住时 Job / 子进程和服务均停止；合成离线迁移与回退复验通过。R6.4 / R6.6 完成，全部 R6 已取得本地证据。详见[总 Plan](../../plan.md)第七批。R5.1、启动接入及外部验收继续，不把本批完成等同整体完成。

## 2026-10-18 第八批：程序操作与生命周期结构

任务消息 / 生成 attempt / 请求 / 搜索包装 / 完成报告改用严格 TypeAdapter，复用 ChildDiagnostic 和 M07 读取审计参数；domain 校验与 AF_PIPE 分帧 / 鉴权 / Job 关闭继续原实现。空 attempt_id 不再自动分配并扣额，坏生命周期记录不推进或关闭。新增两项永久回归、原查询回归改走实际程序审计入口，详见[总 Plan](../../plan.md)第八批。R5.1 仍未全部完成，继续清点交付和持久控制记录；不以本批结构替换代表完整验收。

## 2026-10-18 第九批：原生入口与嵌套 Job

真实脚本 / FastMCP stdio 复现“BREAKAWAY 创建成功但仍属于外层 SDK Job，退出即杀后台”；新增 launcher 嵌套 Job 永久回归先失败。后台改为先挂起，确认 IsProcessInJob 为 false 后才恢复；拒绝时终止并等待子进程，后台入口不运行。普通任务 Job.resume 复用原 NtResumeProcess 代码，不改变其入 Job 后恢复 / 停树契约。

完整产品 208 项、启动 / 调度 9 项、Windows 9 项通过；原生 Check / Mcp 拒绝冷启动、既有服务 Serve / Web 复用及 Stop 已取得明确范围证据。测试服务归执行器回收，不伪装脱离全部 Job；真实拒绝回归在未替换的独立子进程运行。R3.4 仍缺普通终端的正向独立冷启动，不勾选；R5.1 后续结构工作继续。详见[总 Plan](../../plan.md)第九批与[待办](../../pending.md)。

## 2026-10-18 第十批：任务引导与回复模型

任务 stdin 引导、子进程固定 TaskInput、程序 result / error 回复及完成确认接入严格 TypeAdapter；模型连接复用 Config 的 ModelConnection，消息上限复用 TaskPipe.MAX_MESSAGE。非法 pipe / authkey 在连接前拒绝，布尔额度在私有配置 / AIAgent 前拒绝，坏输入关闭已建立连接；现有普通任务 / 认证 / 预算 / 停树不变。新增管道边界永久回归并扩展原 UTF-8 / stdout 用例，旧实现先失败后修复；M07 选材持久模型同时完成，详见[总 Plan](../../plan.md)第十批。

R5.1 保留未完成，后续继续任务 / 提交及其余事件控制记录清点，不重复已完成引导 / 回复和选材模型；启动正向终端 / Desktop 条件沿[待办](../../pending.md)。

### 2026-10-18 第十一批：SQLite 任务与提交严格模型

State 读写入口校验组合后的任务 / 独立副本和提交清单，版本 / 严格计数 / 布尔控制字段 / attempts / 文件身份 / 提交项状态与未知字段不再被宽松采用；JSON 列为非对象也先拒绝。准备结果复用领域模块的已有模型，搜索包装移到 M06 共用，运行层沿同一 TaskKind / PublicationScope。没有数据库格式或当前有效载荷变化，原事务、提交与恢复控制继续复用。

三项永久回归保护非法任务不覆盖预算、损坏任务 / attempt 不采用、损坏清单不触发恢复或改文件，均先在旧实现失败后转绿；实际纠错组同时保护 reanalysis_prepared_version / 后置等待的兼容性。完整测试与 PM 机械证据见[总 Plan](../../plan.md)第十一批。R5.1 仍未勾选；私有配置、episode 游标、外扩覆盖及 M07 调用 / 反馈控制记录为后续本地工作，外部验收条件不变。

### 2026-10-18 第十二批：私有配置与模块控制记录

私有配置读写复用 ConfigValues / 严格版本模型，错版本、布尔额度和未知字段在采用前拒绝；旧 search 缺省只补读取值、不改原文件。M03 游标、M06 覆盖及 M07 调用 / 反馈结构同时接入归属模块模型，错绑任务在共同读取入口拒绝。完整产品 224 项、浏览器 5 项及 PM / stdio 实际机械证据见[总 Plan](../../plan.md)第十二批。R5.1 保持未完成，下一步审计 M05 重分析依赖及启动 / 采集控制结构，再做 R4.2 清理；未重复已完成结构或推进外部验收项。

### 2026-10-18 第十三批：严格结构及复用清理收尾

补齐 M05 重分析依赖、启动实例 / health / PM 检查事实与采集游标的严格模型；Runtime 登记 / 增量来源、episode 历史来源参数 / 纠错结果复用既有模型，删除重复字段与枚举检查。错误控制记录在采用前拒绝并保留原字节，坏实例不发 health 请求；采集仍保持 200ms 不读响应 / 不启动后台。

固定 Hermes 六个同步文件 / Shell 工具直接复用实际发布的 JSON Schema，由 PM 已有 jsonschema 在原 registry handler 前校验，原 handler 签名 / kwargs 和执行链保持。实际 PM registry 六工具非法参数均未到达 handler，文件 / Shell 副作用为零；正常 AIAgent 链仍通过，PM 未安装产品框架或新依赖。环境检查补核对现有 jsonschema 可用。

26 份生产 Python 的一次性清点确认手写 HTTP 服务、旧模型代理路由、自定义 Formatter 和重复 Tavily 请求均无剩余调用。保留 Windows 根句柄相对打开 / 改名、精确 FILETIME 和挂起恢复的库未覆盖窄绑定，以及固定版本、来源归属、持久额度、发布恢复和不等待通知等产品契约。R5.1 与 R4.2 依据当前结构 / 调用清点及回归勾选；模块继续为 approved，R1.6、R3.4 和真实平台验收未完成。

完整产品 **229 tests / OK，96.782s**、浏览器 **5 tests / OK，24.953s**，实际 PM 七场景 43 次、Episode 链 22 次、Tavily 外扩链 14 次、纠错链 11 次、新材料修订链 12 次合成生成通过。真实 stdio、合成离线迁移、旧采集和 Push Guard 16 项通过；新增五项永久回归先复现旧错误再转绿，旧 Context fixture 补齐真实记录必填字段。全部日志、模型与副作用证据见[总 Plan 第十三批](../../plan.md#2026-10-18-第十三批严格结构及复用清理收尾)。普通终端独立冷启动、Desktop G2、真实模型语义和物理休眠条件保持，未执行远端写入。

### 2026-10-18 第十四批：实际 SDK 重建、断流与续额

原产品执行器 / PM AIAgent 四类机械场景通过：SSE 截断 2 次到达 / 计数；三次响应前断开后真实 primary_recovery，第四次成功，4 次均计数；连接拒绝保留 not_sent 并退额，启动监听后 1 次成功。只观察构造返回值的 profile 记录 18 个共享 / 请求专用 / 重建客户端，均保持门禁与 SDK max_retries=0。没有替换请求或重试。

同一任务实际生成 1 次后因 JSON 失败，关闭 / 重开 Store / Config / Runtime 后显式重试仅能再发 15 次；再重开 / 重试新增到达 0，持久总计 16，两次重试均 BudgetError。23 个到达请求与各账本一致；原传输 / Runtime 20 项及其他 120 项定向组通过。结合上一批正常工具 / 评分 / 503 / 16 与 17 次证据，本地机械场景已补齐；R1.6 仍待当前直连的一次获准真实模型流式工具往返，不复用旧代理的真实调用结论。详细命令 / 范围 / 日志见[总 Plan 第十四批](../../plan.md#2026-10-18-第十四批实际-sdk-边界与本地验收)。无生产代码、PM 环境或公开契约变化。

## 2026-10-18 第十六批：MCP 实例校验复用补漏

MCP local_request 直接采用启动模块已有 INSTANCE_RECORD / INSTANCE_HEALTH，删除重复 JSON 加载与宽松 protocol 比较。六种非法元信息 / 健康响应均在业务调用前拒绝，原文件字节保持；有效实例健康检查后可继续请求。新增边界契约先失败后通过，最终完整产品 230 tests / OK。没有新 schema、持久字段或协议；R5.1 已完成状态不变，启动正向独立性仍待普通终端。详见[总 Plan](../../plan.md)第十六批。

## 2026-10-20 第十九批：周期停机续接入口同步

共用 Runtime.retry 仅放行因 runtime_stopping 取消且已停止的周期外扩；重新核对当前路径权限与原输入，通过才恢复授权 / 清原因并排队。其他取消仍拒绝，原 task_id、配置 / Prompt / 固定输入、审计与已用次数保持。新增权限及取消类型回归、M06 实际调度 / SQLite 重启验收通过；完整产品 234 项通过，详见总 Plan 第十九批。M01 的实际模型、独立启动与 CI 仍按各自证据验收。

## 2026-10-20 第二十批：真实模型与本机验收

用户在独立验收 Web 保存配置 v2（chat_completions / deepseek-flash），当前 PM / Hermes / AF_PIPE 直连真实模型完成 read_source 工具往返：实际 2 次生成、stream=true、读取审计及最终 JSON 通过，证据 twentieth-real-model.json / .log。结合既有实际执行器合成边界，R1.6 完成；不使用旧代理证据替代当前直连。关闭启动 PowerShell 后，同一后台 PID / instance_id 继续 ready，真实 FastMCP stdio 两工具连接后退出仍存活，且不处于 Windows Job，最后实际 Stop 成功并保留配置。

## 2026-10-20 第二十一批：严格结果解析与 CI 证据

真实模型返回单个完整 JSON 围栏时，以标准库完整匹配去围栏后执行原 json.loads；裸 JSON、领域校验和错误拒绝保持。新永久用例先复现围栏失败，再验证合法围栏 / CRLF 及说明文字、多个 JSON、尾随载荷、其他语言和坏正文拒绝。当前全产品 235 项通过（103.496s），Hermes 6 项、认知 7 项及外扩 14 项通过，Ruff / 离线锁通过。17a23c8 对应 PR tested merge 868d000 的 Windows CI 已通过；当前新修复需新提交 CI，R3.4 暂不以旧 head 提前完成。普通终端独立后台证据仍有效，Desktop 冷启动另待 G2。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

### 2026-10-13：Task 1 开始执行

用户指令“现在开始按照plan执行”批准当前统一 Design / Prompt、总 Plan 和八模块 Plan 的本地实施。工作区从干净的 `codex/4-initial-development` / `0e81742fcfbfd36134cd175e18b0d5daee902e48` 开始；复用当前任务分支，由主 Agent 执行。GitHub 只读核对为 `Spokey5243/DistillAI`、默认分支 `main`、当前账号 `Spokey5243`、Issue #4 OPEN；没有本分支 PR。

Step 1：Windows 25H2、build `26200.9457`、x64；当前控制层解释器 Python `3.13.5`。Hermes 为干净的浅克隆，当前 SHA `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed`；Design 历史查证 SHA `97a9ae8ee55d31bebce49f1fb6b5ef775323976a` 不在本地 Git 对象中，差异比较返回 `fatal: bad object`，不能声称核对过完整 diff。本次不 fetch 或切换上游，当前 SHA 仅作为验证对象，未冻结为可发布组合。

核对入口为 Hermes 的 `website/docs/guides/python-library.md`、`website/docs/reference/package-management.md`、`activate.ps1`、`setup-hermes.ps1`、`run_agent.py`、`agent/agent_init.py`、`tools/registry.py` 和 `hermes_cli/plugins.py`。实际构造函数包含 `provider` / `api_mode`、`skip_context_files` / `skip_memory` / `skip_background_review`；资源释放使用 `close()`，工具使用 `registry.register(...)`。导入阶段会加载上游源码 `.env`，实例阶段会发现插件；后续 probe 使用独立 `HERMES_HOME`、`HERMES_SAFE_MODE=1`、显式工具白名单和关闭后台审查，不以 `quiet_mode` 代替这些边界。

PM 数据位于本机临时目录 `distillai-hermes-validation`，`HERMES_RUNTIME_DIR`、bootstrap Python / uv cache 均在该目录中；使用官方 `. .\activate.ps1` 准备，不写入个人配置或用 pip / uv 修改 PM 环境。初次 GitHub release 直连被重置；使用用户已配置的本机代理返回 200，本次只为准备进程设置代理。PM lock SHA-256 为 `49b79259220160f147255078a19af541a5f328d3871c8041cc1eb909d19eb549`，uv lock 为 `95a3082629ffecdabb1bad0880ccf5a237d47cd8fb67d86094f6d3d331f4eeac`；锁定 uv `0.12.3` / Python `3.14.7+20260901`，实际 Python `3.14.7`。

应用环境同步成功，receipt 为 `pm_20261013T101305Z-sync-35160-1af7be92e2c1433b8117098d311ac4aa.json`，`venv_rebuild.ok=true`。从 PM `facts.json` 读取实际解释器：`installs/df016e59190fdbc4/environments/eefbf627c51f49329d8fb71b8cf393fc/venv/Scripts/python.exe`（相对上述临时数据根）；直接导入 `run_agent.AIAgent` 并运行下述合成任务成功。不能据此声称完整激活成功：随后独立开发测试环境的 `uv lock` 因 Python 3.14 分支 `resvg-py==0.4.0` 缺少 publish time，与 `exclude-newer` 时间筛选冲突而失败，准备脚本退出 1，`activate` 报 `setup failed; shell environment unchanged`。本地 PM 文档确认应用环境不选 dev / test 两组，而开发激活还会准备测试解释器。未修改上游依赖、锁文件或时间筛选；Step 2 仍未完成，应用解释器也尚未冻结为产品启动组合。

Step 3 部分实测：用上述 PM 应用解释器执行 `.artifacts/initial-development/probe-hermes.py`，退出 0。本机合成 OpenAI-compatible endpoint 收到两次 `/v1/chat/completions`，均为流式；实际调用一次 `distill_probe_echo` 并得到预期终结 JSON。显式 `provider=custom` / `api_mode=chat_completions`、工具注册、`run_conversation()` 和 `close()` 已验证。独立配置关闭压缩、动态 `tool_search` 桥及自动资源，模型实际可见工具仅合成 echo。默认动态桥会改变工具呈现，产品适配不能只指定工具集而忽略该配置。完整 system / tools 请求保存在忽略目录的 `hermes-requests.json`；没有真实模型凭证，实际模型流式工具往返尚未执行，Step 3 保持未完成。

Step 4 部分实测：同一脚本加 `--retry-once` 让首个流式请求返回合成 503，退出 0。实际入口收到三次请求，stream 依次为 true / false / true，工具只执行一次，最终 JSON 正确；对应上游 `agent/chat_completion_helpers.py` 的 `_unmask_server_error_with_nonstreaming()` 恢复路径。失败尝试和非流式重试都必须由转发入口计数，不能依赖迭代数。记录保存在 `hermes-requests-retry.json` / `hermes-results-retry.json`；没有实现产品转发或预算持久化，第 16 / 17 次、重启、压缩 / 其他辅助活动与双名额并发仍待验证，Step 4 保持未完成。

Step 6 部分实测：临时文件的既有写句柄导致提交锁拒绝（32）；提交句柄持有期间外部覆盖 / 替换 / 删除 / 改名被拒绝；通过同一句柄写入并 `FlushFileBuffers` 后文件身份保持；新文件被用户抢占时 `CREATE_NEW` 返回 80 且用户内容保留。锁住 junction 指向的真实目录不能阻止删除 junction；带 `FILE_FLAG_OPEN_REPARSE_POINT` 打开 junction 自身并禁止共享删除时，其删除返回 32。产品仍须逐级保护 / 校验路径，无法确认时拒绝提交。probe 未验证多文件中断恢复、全部路径竞争或 OS 写隔离，Step 6 及 G1 保持未完成。

一次性脚本和合成输出保留 `.artifacts/initial-development/`。基线验证：`python tests/test_capture.py` 退出 0，`python .codex/hooks/test_pre_push_guard.py` 的 16 项测试 OK；`python .artifacts/initial-development/probe-win32.py` 退出 0，输出包含上述 junction 反例。未增加永久文档测试或改动上游源码。

Step 5 部分实测：`python .artifacts/initial-development/probe-job.py` 退出 0；父 / 子 / 孙三个进程均在关闭 `KILL_ON_JOB_CLOSE` Job 后进入 signalled 状态，随后心跳字节保持，证明这组进程树确实停止，不证明文件隔离。

MXC 验证包位于忽略目录，仅用于候选 probe；npm `@microsoft/mxc-sdk@1.0.0` tarball 的 SHA-512 与 registry 的 SRI 一致，内含 x64 `wxc-exec.exe` 的 Authenticode 验证通过，未执行安装脚本或 host-prep。直接原生 executor 不需要 Node SDK 的 Koffi / node-pty 依赖；SDK 若采用，需另核 Windows stdio 的 Node 最低版本，而非只看 package engines。

完整 MXC 请求的 probe 退出 0 但 JSON 包含 error，dry-run 退出 1：`network.ingress.hostLoopback='allow' is not supported by this version of Windows`。因此不能仅用 probe 退出码放行。仅用于文件边界定位的 `--file-only` 策略显式拒绝 host loopback：补足隔离环境的 `LOCALAPPDATA` 字段后，probe / dry-run / 真实执行均退出 0；选择 `base-container`、`needsDaclAugmentation=false`。保护文件可读、不可改写（errno 13），允许目录可写，嵌套子进程也保持该边界；原合成 sentinel 字节保留。该策略缺少产品所需 loopback，不作为运行基线。

Step 5 / G1 保持未完成。统一 Design T06 记录了 `WRITE_RESTRICTED` / Low integrity / Job 的替代候选和仅改任务目录 ACL 的范围，待用户确认后才验证新路线；不改主机 ACL、不启动普通无隔离进程来绕过。尚未验证 PowerShell / 孙进程写边界、外网、Hermes 在容器内运行及整体撤权窗口。

为区分策略校验与实际联网，另运行 `python .artifacts/initial-development/probe-mxc.py --network-test`：移除显式 hostLoopback 配置、保留 egress allow；probe / dry-run 成功，但隔离子进程访问受保护进程的合成本机 HTTP 服务超时，真实执行退出 1。普通进程以同样的 `ThreadingHTTPServer` / urllib loopback 方法作对照，读取成功、退出 0。该结果确认本次候选组合的模型转发路径未通，不能以省略该字段放行。

### 2026-10-14：模型、预算与替代隔离验证

用户批准验证 restricted token / Low integrity / Job 替代候选，并指定官方 `deepseek-flash` 作为本次真实模型。批准的是验证，未自动选定产品 runner。使用本机已有 pywin32 做一次性 Win32 探针；没有安装生产依赖、修改上游或调整真实工作目录 / 个人目录 / 系统设备 ACL。

Step 2 完成：官方 `python -m pm.cli install --trust-recorded` 未请求开发测试环境，退出 0；receipt 为 `pm_20261014T044905Z-sync-45736-1dc211f41042405cbd72510dacc0907c.json`，应用环境 `already in sync`。命令还在独立工具根准备官方固定的 agent-browser / cua-driver；它们不是 DistillAI 生产依赖或启用工具。实际应用解释器和 stamp 保持上述选择，导入检查再次退出 0、输出 `run_agent`，上游 Git 仍干净。依据本地官方 PM 文档，应用环境不选择 dev / test 两组；因此将 Step 2 从完整开发激活校准为应用准备 / 导入，属 Agent 闭环的技术事实澄清，不放宽 G1。2026-10-13 的开发测试解析失败保留，不声称修复了 activate。

Step 3 完成：`.artifacts/initial-development/probe-real-model.py` 的控制进程读取本次凭证，通过固定 `https://api.deepseek.com/chat/completions` 转发；Agent 子进程只取得 loopback endpoint 和内部任务令牌。协议为 Chat Completions，本次关闭 thinking、单次输出上限 1024；只发合成 echo 材料，执行白名单工具一次。两次流式生成均 HTTP 200，最终 JSON 符合预期，脚本退出 0；脱敏结果见 `hermes-real-results.json`。没有保存真实密钥、授权头或模型内部推理，也没有把此 probe 当成沙箱内模型验收。

Step 4 完成：`python .artifacts/initial-development/probe-budget.py` 退出 0。合成 provider 配合真实 AIAgent 循环：第 16 次返回有效终结 JSON；仍需第 17 次时，转发层在发出前拒绝，实际生成保持 16。Agent 与转发服务重新启动后，同任务仍为 16，新请求不发出。普通任务与完全无工具的筛选实例并行，两者首次请求通过同一屏障确认同时运行，独立计数分别为 2 / 1。共实际转发 35 次合成生成、拒绝 2 次；此前 503 的失败尝试 / 非流式恢复仍计数。压缩、记忆、后台审查、动态工具桥 / 扩展等未接管活动在此组合关闭；该结果验证接管能力，不表示产品调度、持久预算或转发模块已经实现。合成 forwarder 保存前锁内持久占用额度，证据见 `budget-results.json`。

Step 5 部分通过：`python .artifacts/initial-development/probe-restricted.py` 退出 0。仅在新建合成目录准备明确的当前用户 ACL，分别给本任务副本 / 临时目录和另一任务分配独立 SID；使用 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`、Low integrity、父目录 `FILE_DELETE_CHILD` deny 与 token default DACL。Python 父 / 子 / 孙均能读合成保护文件，只能写本任务目录；覆盖 / 删除 / 改名、另一任务目录 / 临时目录、junction 指向保护目录的写入被拒绝，新建保护文件硬链接被拒绝。PowerShell 真实读写同样保持边界，loopback 成功，外网 TLS 取得 401（未发送认证或生成请求）；关闭 Job 后三个活动进程均停止、心跳不再变化。根目录 DACL ACE / mandatory label 的有效策略恢复，无残留能力 SID / Low 标签，随后删除已核对的私有测试目录。SDDL 的自动继承 / 空 SACL 表达可被系统规范化，未声称描述符字节完全相同；结束前确认的是有效策略。

Step 5 仍失败：`python .artifacts/initial-development/probe-read-boundary.py` 退出 0是反例验证成功。只有 OWNER RIGHTS 的合成文件在普通 / 仅 Low token 下可读，在 WRITE_RESTRICTED token 下读失败；只对新建合成文件增加明确当前用户 read ACE 后恢复可读。普通令牌可读取的当前 PM 底层 Python 在替代 token 下同样不可读，venv launcher 和 Hermes 源码可读。`python .artifacts/initial-development/probe-restricted.py --hermes` 真实启动失败、退出 1，venv launcher 报无法找到已存在的底层 Python；失败输出保存在 `restricted-hermes-results.json`，授权恢复与私有目录清理仍成功。这条候选不能在仅调整任务目录 ACL 的批准范围内运行当前 Hermes，也不能声称符合不额外限制读取的契约；不修改被保护路径 ACL 来掩盖反例。

G1 保持未通过，Step 5–7 不勾选。下一候选是 MXC 加 stdio 模型请求转发；具体边界已同步统一 Design T06，待用户确认验证。没有启动产品维护任务、进入 Task 2 或执行 Commit / Push。

本轮同步检查：31 份 Markdown、384 个本地链接 / 锚点无错误，九份 Plan 为 approved，完成 / 未执行步骤为 4 / 136；跟踪改动的密钥 / 私钥模式扫描无发现，`git diff --check` 退出 0。所有一次性探针与 PM 安装进程均已结束；没有新增永久测试或生产依赖。


### 2026-10-14：OS 写隔离移出初版

用户明确要求本次不实现写隔离，后续 Issue 再做；与统一 Design `material_revision: 1` 对齐。Task 1 Step 5 改为普通进程停止验证，文件映射和永久测试组移除写隔离 runner / OS 越界写拒绝；Task 2 的任务副本、业务路径校验、基线冲突、提交句柄与恢复不受此功能延期影响。Task 3 保留普通独立 AIAgent、模型转发 / 16 次预算和业务授权，权限收紧仍注销任务并停树，不修改 OS ACL。MXC / token / 沙箱 stdio 后续独立 Issue 再决定，现有忽略目录探针仅为历史证据。

不将范围延期标成隔离测试通过：当前任务拥有普通用户文件权限，程序扫描 / 恢复只覆盖登记的副本与发布，不能保证阻止或回退自由命令的其他位置写入。没有创建远端 Issue、安装新依赖或开启新隔离验证。


修订 1 的 Step 5 验证完成：再次运行 `python .artifacts/initial-development/probe-job.py` 退出 0，普通父 / 子 / 孙三个进程均 signalled，关闭 Job 后心跳字节保持。普通 AIAgent 与 loopback 模型转发沿已通过的 Step 3 / 4；本次 Job 只作为停树证据，不称为写隔离通过。当前完成步骤 5 / 140，待执行 135；Step 6 / 7 保持未完成。

### 2026-10-15：G1 冻结及存储实施

用户再次要求按 Plan 执行并继续。Step 6 完成：临时探针验证原文件占用、共享模式阻止覆盖 / 替换 / 删除 / 改名、同句柄写入 / Flush 后身份不变、排他新建拒绝用户抢占、删除备份恢复拒绝覆盖新用户目标。产品回归进一步发现只读共享的目录句柄会阻止正常子项改名；改为目录禁止共享删除、文件禁止共享写 / 删除，并通过原生 `NtCreateFile` / `NtSetInformationFile` 相对固定父目录对象执行。禁止重解析、校验实际身份，不沿可能重指的路径字符串重新发布；临时合成测试实际把固定父目录改成 junction，证明新增文件未写入其外部目标。改名信息缓冲区补足 UTF-16 终止字符后，碰撞返回拒绝，永久用例保护此行为。

Step 7 完成：冻结 Hermes 源码 `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed`，官方 PM 应用 receipt `pm_20261014T044905Z-sync-45736-1dc211f41042405cbd72510dacc0907c.json`，PM / 上游 uv 锁摘要及 stamp 沿 10-14 记录。选择共用已准备应用环境，实测 Python 3.14.7；产品支持 Python 3.13+。`pyproject.toml` 固定 MCP 2.0.0，`uv.lock` SHA-256 `e757fb9156c5b78a96016e4b61212ca4196b580d1752829d9b435ec69e301386`；32 个 SDK 依赖版本逐项与 PM 环境一致。只在产品生成锁，没有用 pip / uv 修改 PM 环境。官方 `MCPServer` + `ClientSession` 的 stdio 初始化、列工具和一次结构化 echo 往返退出 0，协议 2025-11-25；不是手写协议或产品 M07 验收。

任务启动组合为上述 PM 解释器运行独立 Python 子进程；先等待输入，控制层分配 KILL_ON_JOB_CLOSE Job 后才释放输入。产品 `ProcessJob.stop()` 终止并查询整组 active process 为零，之后才能恢复或释放名额；父 / 子 / 孙心跳永久测试通过。正式 `start.ps1` / task-child 入口仍按 Task 3 / 4 创建，不把探针命令称为后台启动命令。

Task 2 已实现：数据根与 msvcrt 锁、同目录同步 JSON / 不可变 SHA-256 字节版本、独立字节副本和基线、源身份 / 元数据 / ADS / 链接检查、prepared 清单 / applying / applied / committed、排他新增、原句柄修改、原件同目录备份删除、逐项恢复和 recovery_conflict。新增目录由排他创建返回的句柄登记；不支持原目录结构删除及无法恢复的特殊元数据。未变化文件不重写，后续用户编辑、部分写入的不确定版本、备份冲突均保留；committed 恢复返回原清单供运行层补后置登记，绝不重新模型执行。

Task 2 Step 1 / 2 / 6 完成。Step 3–5 的基础存储逻辑已通过，但业务模块归属 / 字段校验、权限 / episode 修订绑定、处理位置、依赖和索引后置登记将由 Task 3 及对应业务模块接入，保留未勾选，避免将独立库通过当成完整业务发布闭环。当前 Task 1 全部完成，修订 1 的 G1 通过；累计 10 / 140 项完成。

验证：`PYTHONPATH=src` 下 `python -m unittest discover -s tests -p 'test_product_*.py' -v` 在本机 Python 3.13.5 及 PM Python 3.14.7 均为 24 tests / OK，无 skip；`uv lock --check --offline` 退出 0。存储组 18 项保护文件差异、用户冲突、部分发布 / 日志中断、删除身份恢复、历史内容及私有状态边界；Win32 组 6 项保护共享句柄、创建 / 改名碰撞、目录竞争、junction 重指和整树停止。源 / 数据 / 依赖状态与运行文档、Python / CI 规则同步；CI 只执行离线标准库组，不安装 Hermes / 个人凭证或调用模型。

### 2026-10-15：任务、产品适配和后台启动

Task 3 核心已实施：固定输入及 Prompt 内容版本、配置快照、登记去重、未开始的同 session 连续增量合并、普通 / 筛选双名额、查询在下一调度点优先、取消 / 权限收紧、持久请求预算、结果与提交后登记 / 恢复。增量合并保留原输入版本和去重别名，已经运行或跨缺口 / session 的输入不合并。恢复冲突范围暂停后续写任务；已 committed 的后置登记失败保留 validating，恢复重放登记而不重跑模型。M04 / M05 的 episode 字节版本在开始及提交前校验，提交窗口额外持读句柄，防止检查后被外部编辑器替换。

配置已覆盖批准字段与初始值，错误保留原值，空脱敏 key 不覆盖原凭证；配置版本在任务创建时固定，poll 下一等待读取现值，工作路径收紧注销授权并停树。路径先逐级拒绝 reparse，再用实际目录句柄的完整名称校验授权，避免点段 / 短路径别名绕过私有目录。不可变历史只保存脱敏配置与凭证引用；实际凭证留在私有 config 历史，模型子进程只接收任务 token。

`hermes.py` 为唯一直接 AIAgent 导入 / 构造 / run_conversation / close 入口。普通独立子进程用 `-I -B` 和明确 source / src 路径启动，先等待 stdin，控制层分配 Job 后才发送载荷；清除继承的 Hermes / terminal 配置和凭证变量，使用独立 HERMES_HOME、已准备 HERMES_RUNTIME_DIR 及 local backend / 副本 cwd。固定源码自定义 dotenv loader 不遵循 PYTHON_DOTENV_DISABLED，因此在适配进程内关闭该配置发现入口，不修改上游文件。维护工具实际为 read_file / write_file / patch / search_files / terminal / process_manage；query 只注册所需快照读取，screening 无工具。实际注册清单出现其他工具时在请求前拒绝。

产品模型入口固定 task / 协议 / 模型 / 路由，锁内持久占用额度后发送，不转发客户端授权头，不跟随重定向。已明确未建立连接 / DNS 失败释放对应占用，超时等未知是否发出保守计数；每次失败生成、非流式恢复和工具后续推理都独立计数。历史保存实际系统规则、工具定义和输入请求版本，剔除 provider 内部推理字段，结果正文另存版本；不保存授权头。

真实产品适配验证：`python .artifacts/initial-development/probe-product-hermes.py <固定源码> <PM 解释器>` 退出 0。真实 AIAgent + 产品 Runtime / 模型转发 / Job / Store 在临时目录运行六场景，实际 provider 生成 41 次：screening 1、query 2、维护 3（write_file 与 terminal 各一次，默认 cwd 等于副本，两个文件由程序发布）、503 后恢复 3、第 16 次有效结果成功、第 17 次需要生成时失败且 provider 保持 16。源码 SHA / 环境未变，没有再次请求真实收费模型；真实 DeepSeek 工具往返仍沿此前 G1 证据。脱敏结果和合成全文保存在忽略目录 product-hermes-results.json / product-hermes-requests.json。

Task 4 基础已实施：同数据根跨进程启动锁、完整实例 / PID / 协议 / 地址 / 授权 health 核对、八条基线 HTTP、独立模型路由、Host / Origin / body 限制和全局 Stop。stop 先拒绝新任务、等整树及恢复完成，再关闭 HTTP / 释放实例锁；未确认停完不释放写名额。源码和解释器在 Check 中核对固定 SHA、PM 归属、SDK 锁；不下载或安装。窗口隐藏、后台与启动入口生命周期分开。

实际 `scripts/start.ps1 -Action Check / Serve / Stop` 使用固定 source、上述 PM Python 和临时数据根执行均退出 0；跨独立命令 Check 读到同一实例，重复 Serve 复用；Stop 后再 Serve 的实例 ID 改变，最终 Stop 成功。首次遇到 Windows venv redirector 的实际服务 PID 与 Popen PID 不同，已用独立启动关联标识识别所属实例；并发入口需确认竞争子进程已退出，防止晚启动的第二实例。没有以端口或 PID 单独认作同一后台。

最新离线组：标准库 62 tests / OK，无 skip；Python 3.13.5 为 12.469s，PM Python 3.14.7 为 12.429s。当前 Step 3–5 的业务字段 / 归属和实际处理位置、依赖、索引仍在 M03–M07 验证；Task 3 Step 2 的最新修订依赖登记也随 M03 接续。Check / Serve / Stop 已实现，Mcp / Web 动作分别随 M07 / M08 补齐，Task 4 Step 3 不勾选。当前业务处理器尚未就绪时拒绝执行，不使用假处理器宣称产品可用。CI 仅修改离线命令，未触发 GitHub 运行，也未做远端写入。

### 2026-10-16：业务接入复核与基础收尾

已对照最新源代码和两解释器 160 项离线结果核对 Task 2 Step 3–5、Task 3 Step 2、Task 4 Step 3：业务副本 / 扫描、逐项清单 / 句柄提交 / 恢复、处理位置和后置登记、双名额与查询优先、全部启动动作已接入。旧 episode 版本取消、M04 索引失败后补建不重跑、MCP 查询独立取消、当前配置和来源保护均有永久契约及实际探针。真实后台 Web 启动 / 一次性引导 / 停止复跑通过；当前 SDK 冷启动限制仍由 M07 记录，不把现有 Mcp 命令的存在当作冷启动成功。

本模块 25 / 25；Plan 改为 implemented，仅表示当前修订范围的运行基础完成，不表示整体产品或 G2 / G4 完成。普通用户进程权限和写隔离延期保持。
