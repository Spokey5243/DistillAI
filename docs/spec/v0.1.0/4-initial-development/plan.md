---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# DistillAI 初版 Implementation Plan：复用现成能力，移除模型转发

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 来源、范围与当前基线

来源是[统一 Design](design.md)与本次用户要求：重写 Plan，优先复用依赖，去掉无必要的 HTTP 转发层。本稿替换旧 R01 和原 140 步的执行安排，继续归属 Issue #4 / 当前分支，不另起一套需求。

目标：保留采集、episode、知识关系、用户模型、主动外扩、上下文 / MCP 和 Web 的完整产品范围，把框架已提供的能力交回框架，并补齐尚未完成的 Desktop 与语义验收。

2026-10-16 只读核对：已有 `src/distillai/`、产品插件、启动脚本和 20 份产品测试文件；`server.py` 仍是 `BaseHTTPRequestHandler` / `ThreadingHTTPServer`，`hermes.py` 把模型与程序工具请求送回 loopback。当前 `pyproject.toml` 已声明 FastAPI / Uvicorn / HTTPX / MCP，但声明依赖不代表源码已迁移。工作区原有 `pyproject.toml`、`uv.lock`、`tests/test_product_http.py`、`tests/test_product_web.py` 修改，本轮保留其字节内容。

当前源码基准为 `011cf0444c4d81a7738ed2cfe68153be0f74f263`；Hermes 本地 HEAD 核对为 `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed`。旧测试 / 实机结论只作历史参考，实施时重新取得针对新代码的证据。

## 执行结构与复用决策

```text
Codex Hook / FastMCP stdio / 浏览器
                  ↓ 本机业务 API
          FastAPI + Uvicorn（一个进程 / 一个 worker）
                  ↓ 现有 Runtime / Store
          普通独立任务子进程：Hermes AIAgent
                  ↓ Hermes 已有模型 SDK
                用户配置的模型 endpoint

任务子进程 ←→ 父进程：标准库 multiprocessing.connection（Windows AF_PIPE）
用途仅为预算确认、程序业务工具、结果；不转发模型 HTTP 响应。
```

| 能力 | 直接复用 | DistillAI 保留 / 删除什么 |
| --- | --- | --- |
| 模型 / 工具循环、流式解析、失败重试 | Hermes `AIAgent.run_conversation()` 及其模型 SDK | 删除本机 `/internal/tasks/{id}/v1` 模型代理、`models` 镜像、SSE 转抄；不自写 provider / tool loop |
| 调用额度 | SDK 发送前接入现有 `Runtime.reserve_generation` | 只保留持久次数和拒发判断；不把 `max_iterations` 当请求数，不再用代理实现计数 |
| HTTP 服务、路由、响应、静态文件 | FastAPI / Starlette + Uvicorn | 删除手写 Handler、HTTP 编解码和路由分发；保留本机业务授权、CSRF 与版本冲突语义 |
| 请求 / 配置 / 工具 / 记录结构 | Pydantic 严格模型与 TypeAdapter；现有外部 JSON Schema 用已锁定 jsonschema | 共用字段定义、校验和工具 schema 生成；来源、字段归属和版本关系仍由领域校验处理，不重复维护结构校验 |
| 本机 API 客户端 | HTTPX | 统一启动 / MCP 的超时、错误和连接管理；采集通知的 200ms 不等响应契约保留现有最小发送实现 |
| MCP 高层工具、协议、schema、测试连接 | 独立 FastMCP 包及其兼容 MCP SDK | FastMCP 注册两个工具、生成 schema / 结果，以 Client 测试；保留实际业务映射，不手写协议 / 测试连接 |
| 搜索与正文提取 | 固定 Hermes 的 Tavily 请求和结果归一化实现 | 删除 `expansion.tavily_request` 重复 HTTP 请求构造；保留实际来源落盘、逐主张引用和覆盖进度 |
| 有向多关系图 | NetworkX `MultiDiGraph`（拟新增直接依赖） | 删除手写入 / 出邻接维护；保留名称 / 别名精确映射、关系 ID / 版本及查询排序 |
| 文件 / Shell 工具 | Hermes 现有工具与 registry | 只登记来源读取、程序评分、业务 ID 等产品工具，不复制基础工具实现 |
| 运行控制状态 / 数据库事务 | SQLite，标准库 `sqlite3` | 任务、调用额度、任务幂等键、提交清单和配置版本指针入库；唯一约束与事务替换扫描任务 JSON 和多次保存控制状态，内容文件发布仍有独立恢复协议 |
| 内容文件 / 原子替换 / 进程 | `json`、`hashlib`、`subprocess`；boltons / pywin32 | 原始材料、领域内容和不可变快照继续为文件；保留多文件发布、冲突恢复与停树规则，只保留系统库未覆盖的原生窄适配 |
| Web 页面 | 现有 HTML / CSS / JS 和 DOM / 表单能力 | 复用已建页面，不重做界面，不新增前端构建链或业务服务 |
| 浏览器行为回归 | Playwright Python，`browser` 开发依赖组 | 在真实 Chromium 中验证现有 JS、冲突留输入与迟到响应；不重复 API 单测，不依赖个人会话或模型 |
| Python 静态检查 | Ruff，`dev` 开发依赖组 | 检查未定义名称、未使用导入等明确错误；不把全仓格式化混入框架迁移 |

复用的判断以具体职责为准。JSONL 来源身份、episode 边界规则、同源观察、版本提交、候选失效和覆盖进度属于产品本身；它们不因换框架被重新发明或删除。

### 用户确认的复用约束

2026-10-16 用户明确指定日志用 Loguru，并要求继续复用 FastAPI 的测试能力、评估 FastMCP，以及“只要有的就不要写”。每项通用能力先查所用框架、现有依赖和成熟库；有满足契约的现成实现就直接调用，不再以“标准库优先”“少加依赖”或“自己写几行更轻”为由重复实现。新增代码限于产品规则、参数 / 来源 / 权限映射，以及经核对确无现成覆盖的窄适配；保留自写部分须记录具体缺口与依据。已有库提供的重试、schema、测试客户端、日志、锁、定时器、配置加载、路径词法校验、协议和消息分帧不再另造框架。

具体安排：日志采用 Loguru；HTTP / Web 用 `fastapi.testclient.TestClient` 与 `app.dependency_overrides` 测试；MCP 高层采用独立包 `from fastmcp import FastMCP, Client`，stdio 对接 Codex，内存 Client 做工具测试。工具签名 / schema / 结果封装与测试连接交给 FastMCP，业务层只实现两个工具的实际行为。FastAPI TestClient 来自 Starlette 并基于 HTTPX，它与 MockTransport 分别负责应用入站测试和外部 HTTP 模拟。

本轮官方文档与 PyPI 元数据核对：Loguru 0.7.3、FastMCP 4.1.0 为候选安装版本；FastMCP 4.1.0 的 client / server 依赖声明兼容 `mcp>=2,<3`，同时约束 Pydantic / Starlette 等依赖。该声明不是已完成兼容验证；实施时由 uv 解析整个产品环境并锁定，不照搬旧环境检查，不把独立 FastMCP 与旧 SDK 中的同名类混用。产品实现仍未启动。

依据：[Loguru API](https://loguru.readthedocs.io/en/latest/api/logger.html)、[FastAPI TestClient](https://fastapi.tiangolo.com/tutorial/testing/)、[依赖覆盖](https://fastapi.tiangolo.com/advanced/testing-dependencies/)、[lifespan 测试](https://fastapi.tiangolo.com/advanced/testing-events/)、[FastMCP 工具](https://gofastmcp.com/servers/tools)、[FastMCP 测试](https://gofastmcp.com/development/tests)、[FastMCP stdio](https://gofastmcp.com/deployment/running-server)、[FastMCP 包元数据](https://pypi.org/pypi/fastmcp/json)。

### 补充审计：上一稿漏掉的通用能力

2026-10-16 再次核对现有代码及 `uv.lock`：MCP 已传递引入 Pydantic、AnyIO、jsonschema 和 Windows pywin32 311。锁中存在只证明依赖已解析，不证明各解释器已安装；实际直接使用时声明直接依赖并检查对应环境。本表补入具体替换范围，不以“属于产品基础设施”为理由整块保留手写实现。

| 能力 / 当前重复实现 | 复用对象与本稿处理 | 保留的契约 / 验证 |
| --- | --- | --- |
| `config._validate`、各模块记录 / 引用字段检查、`tools.py` 的手写工具 schema | Pydantic `BaseModel` / `TypeAdapter`，严格模式、未知字段拒绝；同一模型生成工具 schema。上游已经给出的 JSON Schema 需要程序验证时用 jsonschema，不翻译成第二份 schema | 不强制把字符串 / bool 转数字；optional / null / 默认值沿契约；字段错误路径不丢。来源存在、权限、前后版本 / 观察身份等跨记录判断继续保留 |
| `windows.py` 的 kernel32 函数签名、Job / 文件信息 ctypes 结构 | pywin32 `win32job` / `win32file` / `win32api` / `win32process` 已覆盖部分直接调用；删除对应声明 / 手动 CloseHandle 管理，复用 PyHANDLE 生命周期 | 保留目录句柄绑定、拒绝 junction / ADS / hard link、挂起后入 Job、确认 active=0 等策略。NtCreateFile / 根句柄相对 rename 等未覆盖接口单列保留，不声称 pywin32 全覆盖 |
| `Store.locked` 与 `startup._lease` 的文件锁包装 | 拟用 portalocker 复用跨进程锁、重入 / acquire / release / 异常处理；保留进程内 threading.RLock，启动锁用非阻塞获取，Store 沿原嵌套语义 | Windows 两进程竞争、同线程嵌套、跨线程排他、进程崩溃释放。采集 / 发布的目标句柄保护不改用 sidecar lock，文件身份保护仍沿 Win32 |
| 上一稿准备新增的 stdout JSON 行双向协议 | 改用标准库 `multiprocessing.connection` 的 Windows AF_PIPE / Connection 消息分帧、认证与 EOF；`send_bytes` / `recv_bytes(maxlength)` 传 JSON，不用自动 pickle 的 send / recv | 保留 Popen / PM 解释器 / suspended→Job→resume；stdin 只传一次私有引导连接信息。父进程绑定单任务连接、鉴权、尺寸、操作名和顺序；无 TCP / HTTP 服务，不自己做字节缓冲 / 消息帧解析 |
| `mcp.Bridge` 同步请求 + asyncio.to_thread + shield 拼接 | HTTPX `AsyncClient` 原生异步请求；SDK 已用的 AnyIO TaskGroup / CancelScope 管理客户端与取消清理 | HTTP await 被取消后，shield 内向同一 invocation 发 cancel；业务任务取消仍由 Runtime / Job 确认。去掉每次请求额外线程，不重写持久调度 / 调用所有权 |
| `server._page` 的 Base64 + HMAC 游标编解码 | 拟用 ItsDangerous `URLSafeSerializer`，salt 区分游标用途；继续校验 collection / filters / after | 游标不允许跨筛选 / 集合使用或篡改；保持分页结果 schema，客户端游标是 opaque。重构启停清旧会话 / 游标；不偷偷给持久业务记录换格式 |
| 手写 Cookie header / 解析和基础 Host 检查 | Starlette Request.cookies、Response.set_cookie / delete_cookie、TrustedHostMiddleware；复用 FastAPI 授权依赖 | 一次性引导、服务端 opaque session、Origin / CSRF 仍保留；不以 CORS 代替 CSRF，不切成 JWT 或签名客户端 session，不引入第二套用户认证 |
| `capture.diagnostic` 的日志文件打开 / JSON 写入；各处 stderr 诊断 | Loguru `logger.bind` / `logger.add` 的结构化输出、rotation / retention / compression；不再手写 Formatter、轮转、清理器或通用日志包装框架 | 配置 diagnose=False / backtrace=False，白名单字段，不记任意异常正文 / payload / key。独立 Hook / Popen 任务进程使用各自 sink，enqueue=True 不等于能把不同解释器的独立 logger 自动合并；持久 Store.event 仍保留原落盘语义 |
| HTTP 单测里的手写 Provider HTTPServer | `fastapi.testclient.TestClient` 用 with 启动 / 结束 lifespan，`app.dependency_overrides` 注入测试依赖并在结束清空；HTTPX MockTransport 只模拟出站上游 | API 认证 / 版本 / 错误 / Cookie 测试直接请求真实 app，不走自写 HTTP 测试客户端；实际 socket / 流式断开 / 跨进程模型计数和 Job 探针仍单独验证 |
| 启动配置的环境变量 / 已保存路径取值拼接 | pydantic-settings BaseSettings 与内置 JSON 配置源，显式配置 CLI → 获准环境 → launch.json → 默认值优先级，关闭 dotenv / 隐式 secret 目录源 | 版本化业务 Config 继续固定任务版本；不把 Web 保存变成热读进程环境，不读取个人 Hermes .env，敏感字段不经调试源日志输出 |
| scan / expansion 的周期唤醒、episode 终止计时的调度机械部分 | APScheduler 3.x AsyncIOScheduler、IntervalTrigger / DateTrigger、reschedule / remove_job；由单后台 lifespan 启停，内存 job store 由既有持久记录重建 | 回调只唤醒 / 登记既有领域任务，来源 / 依赖 / 固定输入 / 额度仍由 Runtime 校验；episode 一次性任务设 misfire_grace_time=None，休眠迟到后仍按原截止 / 代次检查；周期任务合并唤醒，不补造业务任务。不把 Job 当业务已完成，不引入独立调度 DB / Redis |
| `storage._relative` 的 Windows 保留名 / 非法字符正则 | pathvalidate 的 Windows filename 校验，覆盖各路径段并显式拒绝 `.` / `..`；只 validate，不 sanitize 后猜用户目标 | 相对路径 / 目录授权、ADS、junction / hard link 和句柄身份仍由现有权限与 Win32 检查；库的长度 / 规范化默认值必须按现有合法路径用例核对，不能引入新截断或悄悄改路径 |
| `storage.atomic_json` 的临时文件、fsync、替换和异常清理 | boltons.fileutils.atomic_save；严格 JSON 编码仍用标准库，临时文件名由现有任务身份派生为唯一值 | 在 Windows 核对同目录保存、覆盖 / 占用 / 写失败旧文件不损坏；只替单文件通用保存，不替多文件冲突发布 / 恢复 |

执行映射：字段 / IPC / pywin32 / 锁 / Loguru / settings / 定时触发 / 路径在 M01-R1 / R5，FastMCP 与 MCP 异步在 M07-R1，TestClient / 游标 / Cookie 在 M08-R1，结构模型按 M02–M07 各自归属接入。只为实际导入声明直接依赖；本轮仍不安装或修改代码。

### 已评估但不直接引入的方案

SQLite 已由用户同意加入本稿，不再列为暂不采用的候选；控制状态与内容文件的具体划分见下节。SQLAlchemy / Alembic、Redis / Celery 本轮不引入；以标准库 sqlite3 的事务和约束完成当前单机控制状态保存，不建立通用 ORM / 队列框架。

APScheduler 直接复用定时触发，不冒充持久业务队列。Celery / Redis 没有在当前本机单用户方案中被采用；这不授权另写它们提供的通用队列框架。Hermes 已有重试，不再叠 Tenacity 重试模型；单文件保存改复用 boltons.atomic_save，不因当前实现只有几行就保留重复通用代码。`argparse`、`datetime`、`pathlib`、`hashlib`、浏览器原生表单 / fetch 继续直接使用。

新增依据：[pydantic-settings](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/)、[APScheduler 3.x](https://apscheduler.readthedocs.io/en/3.x/userguide.html)、[pathvalidate](https://pathvalidate.readthedocs.io/en/latest/pages/reference/function.html)、[boltons AtomicSaver](https://boltons.readthedocs.io/en/latest/fileutils.html#boltons.fileutils.AtomicSaver)。APScheduler 3.11.3 / pathvalidate 3.3.1 为当前包元数据查证版本，不混用 APScheduler 4.x 文档 API；实际版本由实施时兼容解析锁定。

核对依据：[Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)、[jsonschema](https://python-jsonschema.readthedocs.io/en/stable/validate/)、[pywin32 Job](https://mhammond.github.io/pywin32/win32job.html)、[pywin32 files](https://mhammond.github.io/pywin32/win32file.html)、[Portalocker](https://portalocker.readthedocs.io/en/latest/api/portalocker.html)、[Python Connection](https://docs.python.org/3.13/library/multiprocessing.html#listeners-and-clients)、[AnyIO cancellation](https://anyio.readthedocs.io/en/stable/cancellation.html)、[ItsDangerous URLSafeSerializer](https://itsdangerous.palletsprojects.com/en/stable/url_safe/)、[Starlette middleware](https://starlette.dev/middleware/)、[Loguru](https://loguru.readthedocs.io/en/latest/api/logger.html)、[HTTPX MockTransport](https://www.python-httpx.org/advanced/transports/#mock-transports)、[SQLite](https://docs.python.org/3.13/library/sqlite3.html)。文档核对不等于替换已实测。

### SQLite、Playwright 与 Ruff 的本轮增补

2026-10-16，用户同意将 SQLite、Playwright、Ruff 加入计划。三项选型已确认；下述具体存储划分与迁移步骤作为新稿供审阅，不把同意加入依赖扩大成整份 Plan 或数据迁移的执行批准。

SQLite 通过 Python 标准库 `sqlite3` 使用，不新增 PyPI 同名包、数据库服务或 ORM。拟在数据根建立 `state.sqlite3`，只承担运行控制状态：任务及依赖、任务去重键 / 合并别名、生成 attempt 与额度、发布清单 / 恢复阶段、当前配置版本指针。原始队列与采集 cursor、episode / 知识 / 关系 / 认知 / 上下文内容、外部来源、配置历史正文和不可变字节版本仍为文件；这些内容不是同一状态的数据库与 JSON 双写。任务的输入 / Prompt / 结果哈希引用随任务入库，领域内容的现有版本引用保持不变。具体步骤见 M01-R6。

数据库接管的状态以数据库为唯一当前权威；旧 `tasks/*.json`、`commits/*.json`、`config.json` 仅保留为迁移前证据，不继续读写或在数据库损坏时静默回退。配置历史正文仍在私有 `config/<version>.json`，更新全程持 Store 锁，选择未占用版本号，以不覆盖方式保存后再事务切换当前指针；失败遗留版本不复用覆盖，版本号允许跳号。旧 `config.json` 的兼容说明同步到 README。文件字节版本先保存，数据库再引用；异常留下未引用文件可以保留，不能引用尚未落盘的内容。SQLite 事务不包办用户文件的多步替换：提交意图先入库，句柄保护 / 冲突恢复照旧，文件核对完成后再提交完成状态和处理位置。未 committed 时，即使全部文件已写完也按原清单安全撤销；已 committed 只补后继状态，不重跑模型。运行中数据库故障也须阻止半成品被读取或继续发布，无法安全恢复时保留证据并暂停受影响范围，详见 M01-R6.4。离线迁移须同时停后台、任务树和全部采集入口，等待在途 Hook 结束；整根备份及零新写入回退检查包含队列 / cursor，不能只以 Store 锁或数据库状态证明停写。数据库只由产品控制层访问，Hermes、Hook 与浏览器不直接打开它。

Playwright 用于长期浏览器行为回归，Ruff 用于开发静态检查；两者分别放入 `browser` / `dev` dependency group，由 uv 锁定，产品运行和 Hermes PM 环境不安装它们。浏览器只准备 Chromium。现有 unittest 继续使用，新增浏览器组单独运行，不为 Playwright 引入 pytest。M08-R3 明确只覆盖现有 API 测试无法执行的 JavaScript 交互，布局 / 配色仍作一次性人工检查。

运行模型沿本轮讨论明确：Uvicorn 后台使用 asyncio 事件循环，AnyIO 管理协程生命周期、超时和取消；HTTPX 使用异步客户端。Hermes 仍在独立进程同步调用 `run_conversation()`。SQLite 事务、文件 / 管道阻塞操作在工作线程中执行，同一事务的连接创建、使用与关闭留在同一线程，不在协程中直接执行阻塞 SQL，也不把取消等待视为数据库已回滚或子进程已停止。业务优先级、预算及恢复规则调用现成执行 / 存储机制，不重新实现事件循环或数据库事务框架。

依据：[sqlite3 事务与线程约束](https://docs.python.org/3.13/library/sqlite3.html)、[Playwright Python Library](https://playwright.dev/python/docs/library)、[Ruff 配置](https://docs.astral.sh/ruff/configuration/)、[AnyIO](https://anyio.readthedocs.io/en/stable/)。本轮核对接口文档，未安装或执行新组合。

## 移除转发后如何保留预算

本地固定源码已核对：`agent/client_lifecycle.py` 的 `_create_request_openai_client` 和共享客户端重建均走 `AIAgent._create_openai_client`；`agent/agent_runtime_helpers.py:create_openai_client` 接受 `http_client` 并默认关闭 SDK 内层重试。这是本版的适配位置，属于固定源码的内部接口，不宣称是公开稳定 API。`agent/transports/base.py` 只处理消息转换，不承担网络发送；`pre_api_request` Hook 异常会被吞掉，不能拿它作硬预算门禁。

M01-R1 在这个唯一客户端构造点接入 HTTPX 的发送前钩子 / 极薄 transport 装饰，仅向父进程申请额度与保存脱敏请求快照，再由原 SDK 直接请求真实 endpoint。HTTP 编码、TLS、连接池、SSE、响应解析、工具循环和重试继续由依赖执行。装饰不监听端口，不解析响应，不新建 provider 接口。实例初始化、请求专用客户端、重试后客户端重建都必须被同一适配覆盖。

额度持久化确认后才能发送；父进程断开、拒绝或任务失效则拒发。默认第 16 次正常完成允许校验和发布，第 17 次必须在发送前拒绝；工具往返和重试仍各按实际生成请求计数，重启不清次数。只有底层能证明还没发送的连接失败可按原 attempt_id 退额；读超时、写失败、已发送后断流及未知结果不退。自动压缩 / 其他辅助生成若不能经过同一入口则继续关闭，不建第二条隐式模型通路。必须通过实际 AIAgent 探针才能采用此适配。

程序工具沿现有工具注册调用 Python 函数；需要父进程权威状态的操作经标准库 Connection 字节消息交接。只支持已有业务操作与预算确认，单任务串行请求 / 对应回复，限制尺寸和操作名；父进程把鉴权连接绑定它创建的 task_id，不相信子进程另报任务身份。stdout 不承载业务协议，Hermes 日志隔离。关闭连接或取消时退出等待、停 Job 后再释放名额；R1.3a 在 R1.2 业务接入前验证连接、认证、收发各阶段的有限截止 / 取消和线程回收，外层 AnyIO 取消不等于同步管道等待已终止。不另建通用 RPC 框架、消息总线或 HTTP 工具服务器。

## 需要同步的 Design 差异

本稿不把下列提案写成已批准 Design：

| 当前 Design / 实现 | 本稿提案及影响 |
| --- | --- |
| 修订 2 仍使用 HTTPX 做模型转发 | 删除模型转发，SDK 直连；公开 Hook / MCP / Web 业务接口不因此更换 |
| 真正模型 / 搜索密钥只在控制层 | SDK 直连必须让当前任务子进程取得私有连接配置。通过父子私有通道交给 SDK 内存，不进入模型载荷、任务输入 JSON、stdout 日志、URL 或历史；不伪称仍只在父进程。任务终止关闭并清理临时状态 |
| 手写名称图为旧实施安排 | 用 NetworkX 承担有向多边结构，领域内容仍为 JSON / JSONL，图仍可重建，不引入图数据库；SQLite 只负责下述控制状态 |
| 修订 2 仍要求全部文件持久化、不引入数据库 | 用户已同意加入 SQLite；本稿提出运行控制状态入库、领域内容保持文件。此项覆盖旧“不引入数据库”约束的拟修订范围，具体数据归属、迁移和回退随新稿审阅 |

用户本次要求授权计划重写，不视为自动批准以上具体替换实现。实施前按 Exploratory 人工批准点确认本稿，并同步统一 Design 的连接 / 凭证边界；不得沿旧“持续实施”记录越过这次“先重写 Plan”的范围。OS 写隔离仍按既有决定留在后续 Issue。

## 实施顺序与文件归属

| 顺序 / 模块 | 本轮任务 | 文件与交付 |
| --- | --- | --- |
| 1 / [M01](modules/01-runtime/plan.md) | R3.1 项目依赖准备；R2 FastAPI；R6 SQLite；R1 SDK / Connection；R3 启停；R5 通用能力复用；R4 回归 | 原 M01 文件，以及 `state.py`、离线迁移脚本、SQLite 契约测试、Ruff 配置 / CI |
| 2 / [M04](modules/04-knowledge/plan.md) | R1 复用图依赖；R2 内容链和语义 | `knowledge.py`；不重写来源 / 保存系统 |
| 3 / [M06](modules/06-expansion/plan.md) | R1 复用 Hermes Tavily；R2 覆盖与核查 | `expansion.py`、`tools.py`、`hermes.py` |
| 4 / [M02](modules/02-capture/plan.md) | R1 核对采集契约；R2 真实 Hook 字段 | `capture.py`、`sources.py`、产品 dispatcher / hooks |
| 5 / [M03](modules/03-episode/plan.md) | R1 生命周期适配；R2 修订和收尾 | `lifecycle.py`、`episode.py`、dispatcher |
| 6 / [M05](modules/05-cognition/plan.md) | R1 复用证据链；R2 语义对照 | `cognition.py`；不另写认知评分器 |
| 7 / [M07](modules/07-context/plan.md) | R1 FastMCP / Client 测试 / 启动；R2 注入 / compact；R3 反馈 | `mcp.py`、`context.py`、插件 / Prompt |
| 8 / [M08](modules/08-web/plan.md) | R1 接入框架路由；R2 浏览器验收；R3 Playwright 回归 | `web/` 只改受影响交互；增加 `tests/browser/` 并复用归属业务方法 |
| 9 / 本文 A1 | 全链验收与文档 | 根 README、Spec 入口、CI / Python 规则及证据索引 |

M01 先准备环境并拆清任务进程导入边界；FastAPI 迁移可先使用已有执行适配独立验收，再完成 SQLite 控制状态和“真实 AIAgent → SDK 直连 → 持久预算确认 → 一次业务工具 → 结果保存”。两条验收线分别记录，不让 HTTP 框架迁移等待 SDK 内部接口探针。R5 分块替换，数据库已接管的状态不再做文件锁 / atomic_save 的重复迁移。每块通过后删除被替代生产路径；图和搜索继续复用已有契约。

## 验证方式与门禁

产品控制 / MCP / Web 使用项目 uv 环境；Hermes 任务继续使用官方 PM 已准备解释器。检查两边各自实际依赖，不要求 PM 安装 FastAPI / Uvicorn / NetworkX，也不再要求整个产品锁与 PM 环境完全相同。只在实施任务中修改依赖，锁文件由 uv 生成。

实施后的环境准备与检查统一为下列命令；本轮文档重写不执行产品验收：

```powershell
uv sync --locked --group dev --group browser
uv run --locked --group browser python -m playwright install chromium
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'src'
uv run --locked --group dev ruff check src/distillai plugins/distillai scripts tests .codex/hooks
uv run --locked python -m unittest discover -s tests -p 'test_product_*.py' -v
uv run --locked --group browser python -m unittest discover -s tests/browser -p 'test_*.py' -v
uv run --locked python tests/test_capture.py
uv run --locked python .codex/hooks/test_pre_push_guard.py
uv lock --check --offline
git diff --check
```

依赖同步与 Chromium 安装是联网准备，不能称为离线验证；准备完成后的 Ruff / 合成测试不调用外部模型或搜索。预期：检查与测试退出 0、unittest 为 `OK`、锁一致、无 diff 空白错误。浏览器缺失明确失败，不能静默 skip。按模块先跑对应组，最终跑全量；不新增覆盖率目标，不对模型措辞作永久断言。

| 门禁 | 放行依据 | 不能替代它的证据 |
| --- | --- | --- |
| G0 新方案批准 | 本稿与连接 / 凭证、SQLite 权威划分 / 迁移边界明确获批，统一 Design 同步 | 同意增加三项选型、旧 Plan approved、旧继续实施授权 |
| G1 新执行与框架 | SQLite 事务 / 重启 / 文件恢复成立；直连每次请求受额度约束；ASGI 启停、健康与业务授权成立；项目 / PM 导入边界各自检查 | 声明了依赖、旧代理探针、只测 import |
| G2 真实 Desktop | 采集 / 中断 / 终止时序、冷启动、additionalContext、两次 compact、MCP 查询取消有实际证据 | 模拟 Hook、stdout 成功、预启动后连接成功 |
| G3 搜索复用 | 固定 Hermes Tavily Search / Extract 实际接通，来源可回查、错误和密钥处理成立 | 旧重复 HTTP 实现曾通过、localhost 模型输出 |
| G4 产品闭环 | 八模块链、模型语义、来源 / 用户证据和浏览器交互审阅完成 | 测试条数、所有任务格式正确、completed=True |

### A1：完整验收与文档同步

**Files:** `README.md`、`.agents/rules/python.md`、`.agents/rules/github-actions.md`、`.github/workflows/ci.yml`、本目录入口和模块记录；临时证据写 `.artifacts/initial-development/`。

- [ ] **A1.1 离线与依赖检查。** 先准备锁定依赖与 Chromium，再跑上面检查；CI 在原 Windows job 按锁安装 dev / browser 组、准备 Chromium、运行 Ruff / 既有组 / 浏览器组，不下载 Hermes / 个人数据或用个人密钥。同步 Python / Actions 规则的旧零依赖表述，Ruff 只启用本稿明确的错误规则。核对实际 PR tested SHA 后才能声称 GitHub CI 通过；此项不包含远端写授权。
- [ ] **A1.2 Desktop 闭环。** 合成会话贯通采集 → episode 关闭 / 修订 → M04（含空结果）→ M05 → M07 → 查询 / 新用户表现再分析。检查实际来源和每次固定版本，不用编写好的 localhost 模型响应代替语义评价。
- [x] **A1.3 恢复与外扩。** 丢通知、进程终止、旧输入、并发编辑、查询取消、发布中断各复用现有用例；再做一条真实搜索 / 读取 → M04 → M07 链。失败不发布、不推进、不丢用户修改，外部内容不当用户掌握。
- [ ] **A1.4 日常体验。** 四入口浏览 / 编辑、409 和错误留输入、旧异步响应不盖新内容、键盘 / 窄屏、两次 compact 原选材恢复。检查原任务仍可继续、无候选为空、自然反馈无诱导。
- [ ] **A1.5 更新实际状态。** README 写实际解释器 / 启动 / 锁 / 环境边界；规则文件删除已过时的零依赖假设；模块记录写新命令、结果、版本和证据。按功能完整、来源可靠、认知更新有效、日常体验四项逐项审阅后才标 implemented。未过项目明确保留，不能用比例代替验收。

## 永久测试与一次性证据

先复用已有测试。同一契约因替换框架而换启动 fixture，不另复制测试矩阵。新增覆盖旧组遗漏的长期失败路径：直连重试 / 重建的预算门禁、管道断开拒发、多关系 / 对称查询、搜索来源，以及 SQLite 并发登记 / 最后额度 / 提交崩溃一致性。Playwright 只补 API 测试无法观察的浏览器留输入、旧响应竞争与安全文本渲染；不按 HTTP 状态码复制 API 矩阵。测试验证公开结果和数据边界，不断言私有类名、路由函数位置、依赖字符串或代码行数。

源码检查“代理和 Handler 已删除”、依赖锁 / 环境核对、Desktop 字段、模型语义、真实公开网页和布局截图属于一次性检查，写执行记录。保留必要的无授权 / 跨源拒绝和非法来源测试，因为这是持续安全 / 数据契约。

## 本轮重写记录与回退

本轮只重写总 / 八模块 Plan，并同步计划入口。旧执行日志保留在各文件下方，旧完整 checklist 由 Git 保存。本稿新编号使用 M01-R1 等，不继续累计旧 140 步；历史完成比例不换算成新进度。所有新步骤未勾选。

首稿文档验证（补充审计前）：`python .artifacts/verify_plan_rewrite.py` 退出 0，核对九份 draft、75 个未执行步骤、九份历史记录原文保留及四个原有修改文件 SHA-256 未变；`python .artifacts/initial-development/check-docs.py` 退出 0，32 份文档 / 404 个本地链接和锚点无错误；`git diff --check` 退出 0。检查脚本与结果留本地忽略目录，不新增永久文档测试；未运行产品、真实模型、Desktop 或 CI 验收。

同日补充复用审计：核对现有字段校验、Win32 绑定、锁、MCP 异步请求、分页游标、Cookie、诊断与测试服务，新增上表复用范围；总 / M01 / M07 / M08 Plan 同步，Connection 取代首稿的自写 stdout 消息分帧。相同文档检查重新退出 0：九份 draft、81 个待执行步骤、历史记录 / 原有四文件保持，32 份文档 / 404 个本地链接无错误，diff 空白检查通过。库接口已查文档，替换的运行效果未验；没有新增产品代码、依赖安装或 Commit。

同日用户补充 Loguru / FastAPI 测试 / FastMCP 要求后：替换日志选型，明确官方 TestClient / dependency_overrides 与 FastMCP 内存 Client / stdio 传输，新增 settings / 定时器 / 路径 / 单文件保存复用任务，总 / M01 / M03 / M06 / M07 / M08 及 Design 阅读状态同步。文档核对结果为九份 draft、87 个待执行步骤，九份历史记录与原有四文件不变；32 份文档 / 404 个本地链接无错误，diff 空白检查通过。以上均是计划 / 文档验证，未安装新包或执行产品改造。

同日依赖审查后，用户同意加入 SQLite、Playwright、Ruff；本稿与 M01-R6 / M08-R3 补齐职责、事务、离线迁移、验证及依赖组。SQLite 数据划分为草案，选型确认不代表迁移已批准或执行；此前 87 步与验证数字保留其当时含义。

2026-10-17 用户接受第二轮审查的四项修正：迁移覆盖采集停写；发布恢复沿未提交撤销 / 已提交补后续的原规则，并处理存活进程数据库故障；管道接入先验证有界取消；episode 定时器允许休眠迟到执行。总 / M01 / M02 / M03 Plan 与待办同步。本次接受对应上述修正，文档继续保持 draft / 未执行，不扩展为真实数据迁移或代码实施授权。

实施按小块替换并保留 Git 记录；先用合成数据根验证 SQLite 迁移，真实数据切换按获批新稿和 M01-R6 离线步骤执行。原始队列 / 内容格式保留；迁移后的控制状态不能回退读旧 JSON。出现兼容问题停止受影响任务、保留数据 / 版本 / 错误；已产生新写入时不能用迁移前备份覆盖恢复。已有未提交改动不覆盖、不清理；本轮没有安装、代码重构、产品实测、Commit 或远端写入。

依据：[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)、[HTTPX hooks](https://www.python-httpx.org/advanced/event-hooks/)、[HTTPX transports](https://www.python-httpx.org/advanced/transports/)、[NetworkX MultiDiGraph](https://networkx.org/documentation/stable/reference/classes/multidigraph.html)。Hermes 依据按[本地源码路由](../../../research/runtime/README.md#本地源码路由)读取上述固定 SHA，不用网页源码替换本地版本。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第一批重构证据

项目 uv 环境完成锁定安装，PM Python 3.14.7 / 固定 Hermes SHA 的 AIAgent 导入检查退出 0；产品环境与任务环境已拆开。FastAPI / Uvicorn 接管 HTTP，显式路由复用原业务；API / Web 以官方 TestClient 和 dependency_overrides 运行。旧 Handler、模型代理、HTTP 程序工具入口及任务 proxy token 已删除；请求历史脱敏转到执行适配。

SQLite 已接管任务、去重键 / 别名、依赖、attempt / 次数、提交清单和配置指针。原存储崩溃 / 冲突测试改走数据库；真实写锁超时测试验证未发送模型、停树可结束、业务不可读、重启恢复。离线迁移工具通过合成副本的完整备份、重复核验、预算保留、零新写入回退和新增 Hook 材料后拒绝回退；没有迁移真实数据。修复源读取中新建 Store 重入文件锁的死锁，现有纠错组复跑通过。NetworkX 替换手写邻接；Portalocker / pathvalidate / boltons 替换普通锁、路径词法和单文件保存，Loguru 记录白名单采集诊断。

TaskPipe 采用标准库认证 AF_PIPE / send_bytes / recv_bytes；阻塞 accept / 认证由归任务 Job 的通信进程持有，公开 Process 终止 / join 提供有界回收，不遗弃等待线程。连接前、认证未完成、错误密钥、断开和正常往返已在实际 Windows 通过；跨 PM 主调用与父进程程序工具通过。实际 AIAgent 新探针七场景通过：screening 1、query 2、source 2、文件 / Shell 维护 3、503 恢复 3、第 16 次有效完成 16、第 17 次拒发 16。发现 SDK 将任意发送钩子异常包成连接错误而重试；窄 HTTPX send 适配在额度拒绝时返回本地 400，不发送请求，重跑通过。模型请求编码 / TLS / SSE / 解析 / 模型循环仍由原 SDK 执行。

当前完整产品组 178 tests / OK（39.739s）；Ruff、uv lock --check --offline、git diff --check 退出 0。新增 SDK 组 4 项与 IPC 组 3 项，旧 HTTP 代理用例移至新 SDK 契约覆盖；没有为删除名称写断言。证据在 .artifacts/after-direct-all.log、direct-hermes-probe.log、direct-hermes-results.json 和 probe_state_migration.py。尚未完成全部 M01 / G1：模型参数探针、父进程死亡 / 大消息等完整 IPC 窗口、剩余通用能力、真实模型与 Desktop / 搜索新组合仍需后续证据。没有 Commit / Push 或远端写入。

## 2026-10-17 第二批：原生框架、真实 stdio 与浏览器回归

产品环境原生 FastMCP 4.1.0 接管两个工具，参数引用共用 sources.py 的 Pydantic 严格类型；HTTPX AsyncClient 由 FastMCP lifespan 管理，取消用 AnyIO shield 请求同一 invocation。内存 Client 四项通过；一次性 PythonStdioTransport 探针验证真实独立 Python 进程的工具列表、ID 精确查询、严格输入拒绝、反馈幂等和 stdio 退出后独立后台存活，全程零模型请求。探针发现查询方法被同名 query 属性遮蔽、HTTP 返回 422，补原 HTTP 组的公开查询断言复现后修复。真实 Desktop 工具全名、冷启动和 stdio 取消停树仍未完成。

FastAPI lifespan 内由 APScheduler 管理周期扫描 / 外扩和持久 episode 截止的 DateTrigger，后者允许 misfire；Uvicorn 实际监听后才写 instance。启动组新增忙扫描回归：扫描间隔设 3600 秒，在当前扫描已过 dispatch 后登记任务并唤醒，旧实现丢失唤醒、新任务不执行；现在借 APScheduler 完成事件补一次合并唤醒，任务及时成功。任务 Runtime.wait 与调度各自消费唤醒，避免共享 Event 被等待方清除。配置源 CLI / 获准环境 / launch.json 的优先级已通过。休眠迟到与真实 Windows 休眠探针仍待接续，不能据此勾完 R5.7。

直接 AIAgent 七场景再次通过，实际 provider 共收到 43 个请求：无工具筛选 1、只读查询 2、来源工具 2、文件 / Shell 维护 3、503 恢复 3、第 16 次完成 16、第 17 次拒发 16。此轮实际请求还核对 max_tokens、temperature、top_p、DeepSeek thinking、model；登记后修改配置，已登记筛选仍使用原固定参数，其后任务使用新参数。共享 SourceRef 的 PM 跨环境导入与实际调用同时通过。真实模型语义仍未验。

M06 删除重复 Tavily HTTP 构造，固定 Hermes 私有请求 / 归一化入口接受显式任务 key；仅任务进程持有相应私有配置，HTTPX 官方 endpoint / 无重定向 / 实际响应上限沿窄 client 适配。新的实际 AIAgent + 真实 Tavily keyless Search / Extract → M04 → M07 → 用户指定编辑探针通过，14 次合成模型请求；逐主张缺口、不可变版本、材料次数不增加、外部证据不算用户掌握均有结果。真实付费 key 路径与模型语义不冒充已验。

tests/browser 复用真实 run_service / FastAPI / Uvicorn / SQLite 与合成维护回调，不导入 Hermes、不读取个人材料；每页通过一次性引导换 Cookie。Chromium 实际执行五项 JS 回归通过：两个独立会话真实成功 / 409 且正文和原因保留；保存失败后保留输入并可重试；迟到旧详情不覆盖当前记录；提交期间的新正文 / 原因在成功回调和重新读取后保留；脚本 / HTML 按文字显示且无副作用。路由拦截控制响应先后，不用固定 sleep。失败只保存合成截图到 .artifacts/browser，不开启 trace / HAR。Windows CI 已接入锁定 browser 组、Chromium、Ruff 和独立浏览器命令；本地通过不代表 GitHub CI 已运行。

验证证据：.artifacts/after-browser-all.log（第二批前段 182 tests / OK）、browser-regressions.log（5 tests / OK）、scheduler-wake-red.log / scheduler-wake-green.log（修复前失败 / 启动组 6 tests OK）、direct-hermes-results.json、fastmcp-stdio-results.json、direct-expansion-results.json；最终完整组和静态 / 文档检查以本节下方收尾记录为准。原独立 capture 行为组与 push guard 16 tests 均通过。所有输入均为合成数据；没有迁移真实数据、Commit、Push 或远端写入。

### 第二批收尾核验

当前源码最终完整产品组 **183 tests / OK，44.214s**；独立 Chromium 组 **5 tests / OK，18.264s**。Ruff、uv lock --check --offline、32 份文档 / 419 条本地链接检查与 git diff --check 均退出 0；独立采集行为检查与 push guard 16 tests 通过。证据为 `.artifacts/batch2-final-product.log`、`batch2-final-browser.log`、`capture-regression.log` 和 `push-guard-regression.log`。启动测试停止 scheduler 时可见 APScheduler 的 CancelledError 诊断，业务停机 / 测试结果均为成功；日志整合和完整休眠窗口仍在未勾步骤中。

本轮未创建 Commit 或执行远端写入；Goal 尚未完成。当前 Goal 查询状态为 usageLimited，未自行恢复或标记完成；有效续接范围和外部验收仍见 pending.md。

## 2026-10-17 恢复后第三批：Windows、管道与到期恢复

Goal 已恢复 active，继续用户批准的原完整总 Plan / M01–M08；恢复状态本身不表示完成。前一目标状态 usageLimited 记录保留为历史，当前仍有字段模型 / 工具 schema、诊断整合和接入工作，不能整体归为外部阻塞。

Windows 文件创建、读写 / seek / truncate / flush、最终路径、句柄流枚举 / 删除与 Job 绑定复用 pywin32；原始 NtCreateFile 根句柄相对打开、NtSetInformationFile 根句柄相对 rename、NtResumeProcess 和 100ns FILETIME 读取 / 恢复仍是窄适配。实际探针确认 pywin32 日期把 132537600000000007 变成 132537600000000000；带 RootDirectory 的库 rename 返回 WinError 87，原生相对 rename 成功。未用绝对路径重新解析来规避。pywintypes.error 不继承 OSError，窄适配转换回已有异常契约；PyHANDLE 管理覆盖到的句柄生命周期。9 项 Windows、23 项存储、11 项产品采集组通过，包含追加 / 截断 / 空文件、精确时间、重指向目录中的创建 / rename 不到外部、冲突不覆盖和停父子孙。

IPC 组从 3 项补到 6 项，实际 Windows 进程验证：accept 前未连接、连接后不认证、错误 key、认证后不回复、双向 8MiB 阻塞写、父进程突然死亡。Connection.poll 只协调已连接消息；实际连接 / 认证截止、Job.stop、通信进程 terminate / join 保证退出，未用自写帧。双向阻塞前分别确认接收端已看到待收数据，停止后写线程和两个进程均有界退出；父进程死亡后 Job 内通信进程与已认证 peer 均终止。测试曾在停止后尝试设置被杀进程等待的 multiprocessing.Event，诊断堆栈证明是测试清理的 Condition 锁卡住；改为不操作已终止进程的共享等待器后通过，生产协议未靠放宽超时通过。证据 ipc-complete-phases.log / ipc-diagnostic.log。

Store 新增嵌套 / 跨线程互斥和进程死亡后文件锁释放回归；SQLite 状态组 9 项通过。原始事务竞争 / 额度 / busy 数据库拒发与停树仍通过。调度组 7 项通过：在进程未重启而事件循环暂停跨过原持久截止后，只登记一次 closing；暂停期间出现新 request，旧截止不再登记。周期扫描设为 3600 秒，避免用周期补扫冒充 DateTrigger 的迟到处理；不修改实际系统时钟，也没有让电脑休眠。真实 Windows 休眠 / 唤醒与 Desktop 接入仍单列验收。

图查询新增对称自环与双向多边去重回归，5 项通过。一次性合成 500 知识点 / 1000 关系，与当前 HEAD 旧实现的 90 组公开邻接查询逐项相同，名称 / 别名结果和新实例重建相同；温缓存重建旧 1.7220s / NetworkX 1.6981s，只记录代表规模，不声称性能显著提升或固化节点数测试。M05 三类来源 / 字段归属 / 等待后继原组在新 SQLite / SDK / 框架组合复跑通过，真实模型语义仍未验。

当前完整产品组 **192 tests / OK，56.532s**；Ruff 与 uv lock --check --offline 通过。固定 PM 解释器的实际 AIAgent 七场景再次通过，43 个合成 provider 到达请求，包含文件 / Shell 工具、503、16 次完成 / 17 次拒发和固定参数；PM 不新增产品依赖。证据 third-full-product.log、third-direct-hermes.log、third-state-locks.log、third-scheduler-late.log、third-graph-results.json、third-win32-gaps.json 均在忽略的 .artifacts。浏览器与文档收尾检查另记；CI / Desktop / 真实模型未冒充通过，没有迁移真实数据或远端写入。

### 第三批收尾核验与本地提交范围

新 Windows 绑定下再次执行独立 Chromium，**5 tests / OK，19.156s**；完整产品为 **192 tests / OK，56.532s**。Ruff、uv lock --check --offline、32 份文档 / 423 条本地链接与 git diff --check 通过。实际 PM 的直接 AIAgent 七场景、固定参数和 43 个合成上游请求再次通过；未读取个人材料、未修改用户实际数据根。探针 / 日志均留在被忽略的 .artifacts；未遗留本轮测试进程，原用户 Hermes gateway 保持原状。

本批本地提交范围是已批准的框架 / SDK / SQLite 基础迁移、相关边界回归和 Spec 同步；剩余步骤继续保留 approved 与未勾状态，不以基础提交冒充完整实现。Goal 维持 active，下一阶段继续领域 / 工具参数模型、Loguru 与剩余文件故障闭环；远端写入仍需对应授权。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

在本地基础提交 a6de5b49319779e56ddd958771974c834c73b926 上续接。sources.py 共用 RecordRef / DraftRecordRef / SourceRef、ID / 版本 / session 与非空文本约束；领域结构留在 episode / knowledge / cognition / expansion / context。严格 TypeAdapter 接管记录 / 结果、观察与假设、查询 / 筛选及程序工具的字段结构；九组工具参数由相同定义生成 JSON Schema，删除对应手写 required / 类型 / 枚举检查。工具回调仍经认证 Connection 调用父进程，公式、来源实际存在 / 原文引用、同轮归属、权限、依赖版本与字段归属仍由原业务校验负责；验证后继续保存原 JSON，不用模型默认值或强制转换重写历史。

内容 / provenance / 帮助说明等原本开放的文档 map 保留开放；M04 只保留 M05 所有的认知载荷，由 M05 校验结构，不抢夺字段归属。模型错误隐藏输入正文。公开只读工具补参数边界断言：数字冒充文本、bool / float 冒充行号、额外路径字段均拒绝，冻结引用读取和查询结果保持。九份工具参数与七类代表记录 schema 用已锁定 jsonschema 的 Draft202012Validator.check_schema 做一次性核对通过，不维护第二份结构 schema；上游工具自身的校验仍交 Hermes。

最终完整产品 **192 tests / OK，55.112s**，真实 Chromium **5 tests / OK，18.567s**。实际固定 PM AIAgent：Episode 首建 / 窗口评分 / M04 / M05 为 3 / 7 / 7 / 5 次；新材料修订 / 空 M04 / 空 M05 为 10 / 1 / 1 次，验证旧来源按需 RPC、实际新引句、同清单等待与当前版本完成解除；明确归属纠错 / 空 M04 / 空 M05 / Web 独立认知纠错另为 5 / 1 / 1 / 4 次，当前版本解除且内容保持。真实 Tavily keyless + 合成模型的扩展 / M04 / M07 / 用户编辑为 5 / 3 / 3 / 3 次，证明来源版本与字段保护；SDK 七场景含最后额度成功 / 额外额度拒发仍为 43 个到达请求。模型均为 localhost 合成响应，不证明语义质量。证据 fourth-product-final.log、fourth-browser.log、fourth-episode-direct-final.log、fourth-material-revision.log、fourth-corrections-direct.log、fourth-expansion-direct.log、fourth-direct-hermes.log 在忽略的 .artifacts。

Ruff、uv lock --check --offline、32 份文档 / 431 条本地链接与 git diff --check 通过；临时探针进程均已退出。

R5.1 继续保留未勾：HTTP 请求结构和剩余记录字段的完整清点尚未全完；R2.2、Loguru R5.4 与 SQLite / 文件完整故障闭环继续实施。产品组仍打印 APScheduler 停机 CancelledError 诊断，退出与业务断言通过；后续生命周期 / 日志整理须区分正常取消和实际失败，不能静默吞异常。G2、物理 Windows 休眠、真实模型语义和 CI 仍未验，没有真实数据迁移或远端写入。Goal 保持 active，按原完整批准目标持续推进。

## 2026-10-17 第五批：HTTP 与 MCP 请求模型

在 4a6b847f0b453b80db5b65b577276e3fa32cb728 上继续 M01-R2.2 / R5.1。FastAPI 明确路由绑定所属模块 Pydantic 请求模型，保留 Depends(get_api) 的 Host / Origin / 授权 / CSRF 与实际流字节上限；先认证并有界读取，再校验请求，不让自动 body 解析绕过该边界。请求模型在路由建立时创建 TypeAdapter，不另存字段白名单；领域函数共用同一模型，继续做实际来源 / 版本 / 归属判断。任务、通知、查询 / 取消、配置、纠错 / 重分析 / 扩展、反馈、Web bootstrap / 停机 / 重试请求均接入，删除替代的手写字段检查，原错误码作窄映射。

配置更新外层只约束 expected_version / values 两字段；其中 values 是部分修改，继续由 Config.update 合并后校验并返回原字段路径。expected_version 的非 int / bool / 过期版本仍为 409，而 values 非对象仍为 invalid_config / fields.values，不能被新外层模型统一变为默认 422。回归验证 bool / 字符串 / float 版本、非法任务与依赖、未知字段、通知路径、取消 / 重试 / 停机载荷；拒绝后任务、配置版本和 accepting 均不变，错误不含提交正文，无授权先 401。永久断言保护这些公开错误 / 无副作用边界，不断言模型类名或代码布局。

查询与反馈在所属模块定义共享会话、65536 字符非空文本及记录引用；FastMCP 原生签名复用这些类型，实际用户反馈来源只允许同会话 QueueRef，外部网页不能作为用户表现。严格参数在 MCP 传输前拒绝，不触发后端调用。SourceRef 共用 QueueLocator，外部来源 / 用户提交记录使用带 source_kind 的严格 discriminated union，保留 URL / UTC / 注册身份 / 不可变字节版本检查。开放 payload 文档 map 保留，历史版本读取仍以实际登记身份校验，不因当前正文已更新而否认旧字节版本。

完整产品 **193 tests / OK，55.536s**，Chromium **5 tests / OK，17.793s**；移除重复 bootstrap 空 body 判断后 Web 10 / HTTP 7 项再次通过。实际 PythonStdioTransport 工具列表、精确查询、反馈幂等、严格输入和退出后后台存活通过，零模型请求。固定 PM 的实际 AIAgent + Tavily keyless 扩展→M04→M07→用户编辑仍为 5 / 3 / 3 / 3 次；明确归属纠错→空 M04→空 M05→Web 独立认知纠错 5 / 1 / 1 / 4 次通过。都是合成 localhost 模型，未验语义。证据 fifth-product-final.log、fifth-browser.log、fifth-stdio.log、fifth-expansion.log、fifth-corrections.log 在忽略的 .artifacts。

M01-R2.2 当前范围完成。R5.1 保留未勾，继续清点 IPC 程序操作、生命周期 / 交付与持久控制记录的剩余结构校验；原始 Codex / Tavily 上游 payload 不改造成闭合产品记录，继续按上游格式取用。Loguru sink 的各进程归属和 APScheduler 停机取消诊断、SQLite / 文件完整故障窗口仍由 Agent 继续，不需要新的用户技术路线决策。G2、机器休眠、实际模型语义及 CI 未验；无真实数据迁移或远端写入，Goal 仍 active。

## 2026-10-17 第六批：Loguru 进程日志与停机排空

在本地 9a43c257cb4e681393a4cff167f4e6a453775a27 上实施 M01-R5.4。diagnostics.py 只管理 Loguru sink 注册与退出 complete / remove；业务直接 logger.bind，保留 task / session / stage / error_code 等白名单，静态事件消息，不记录任意异常正文、原文、配置 key 或异常栈。未知 extra 字段和 exception record 不进入文件，serialize 使用 Loguru 原生结构，文本时间按 !UTC 输出；diagnose / backtrace 关闭。Store.event 和 SQLite 的持久恢复职责未替换。

后台 / MCP 各有带时间及真实 PID 的独占 JSONL，mode=x 避免共享，时间格式中的 PID 不阻断 Loguru 的跨进程文件匹配；5 MB 轮转、gzip、7 天 retention 交库处理。短生命周期 Hook 一次只写一条诊断，rotation=None，使 Loguru 在退出时压缩 / 执行 retention；否则从不达到 5 MB 的独立 Hook 无法触发清理。旧 capture-errors.log 保留为历史，不移动真实数据。诊断配置 / 写入失败继续原业务；MCP stdout 只协议。PM 沿原 Hermes 日志，不安装或导入 Loguru；父进程只验证并记录 ChildDiagnostic 的有界 code / 固定 stage，不复制异常原文。

停机问题先复现：独立 expansion 回调仍在执行时 service_lifespan 已返回，且 APScheduler 打印 CancelledError。检查锁定 AsyncIOExecutor 源码确认 shutdown(wait=True) 仍取消 Future。现按公开 SUBMITTED / EXECUTED / ERROR / MISSED 事件追踪本模块 coalesce / max_instances=1 的工作，在 shield 内 pause 后等待排空，再 shutdown 和关闭 Runtime；没有使用调度器私有 Future、定时轮询或吞掉取消。回调普通异常按白名单记录 ERROR，周期入口保留后续重试；扫描中的数据库故障仍走原隔离 / 停树路径，关闭失败记 stop_pending。新增回归证明排空等待，回调报错可观测且异常正文不落日志；原迟到截止 / 忙扫描唤醒组继续通过。

完整产品 **197 tests / OK，56.734s**，Chromium **5 tests / OK，18.278s**；最后 PID 命名细化后诊断 3 项与启动 / 调度 8 项再次通过，16.811s。两真实 capture Python 进程各写独立、已排空压缩日志，测试核对 Python 自身 PID（Windows venv launcher PID 不等于解释器 PID），无正文 / key。实际 PythonStdioTransport 正常及 logger.add 模拟失败两场景均通过精确查询、严格输入、反馈幂等与 stdio 退出后后台存活，零模型调用。PM 实际 import distillai.hermes 的产品框架加载集合为空；实际 AIAgent 七场景 / 43 个合成到达请求通过，16 次可完成、17 次拒发仍正确，子进程失败的 code / stage 只在父进程记录。

一次性 Loguru 实测保存 1000 条合成消息，实际跨 5 MB 轮转 gzip，库清除超过 retention 的合成文件，未知 extra 与异常对象被拒、UTC 文本有效。原真实数据与日志不参与探针；证据 sixth-product.log、sixth-browser.log、sixth-startup-final.log、sixth-direct-hermes.log、sixth-pm-import.log、sixth-stdio.log、sixth-stdio-no-log.log、sixth-loguru-lifecycle.log 均在忽略的 .artifacts。Ruff、uv lock --check --offline、32 份文档 / 443 条本地链接和 git diff --check 通过；本轮探针进程均已退出。

M01-R5.4 完成。R5.1 剩余 IPC / 生命周期 / 交付 / 持久控制结构和 R6 文件 / SQLite 完整故障闭环继续推进；Desktop G2、真实模型语义、物理 Windows 休眠和 CI 未验，无远端写入，Goal 保持 active。

## 2026-10-18 第七批：SQLite 故障隔离与文件恢复闭环

本批在本地 0feeb29cb1ee75d4c0b8185b7a38d6aa3ca151c5 上补齐 M01-R6.4 / R6.6，未迁移真实用户数据。复现并修复：连接建立失败未置失败标志；缺库重启错误地创建空权威库；已 committed 输出缺失仍继续补登记；健康 / 停止等待失败发布锁；重复依赖触发 SQL 唯一约束。每项先以回归复现，再修共享入口，不新增恢复框架或依赖。

State.transaction 把建立连接放入同一异常边界，sqlite3.Error 隔离当前根。数字版本私有配置、versions 或 workspaces 表明已有持久状态，缺库时明确拒绝启动；只有队列 / launch 的首次启动仍可正常初始化。真实配置指针写失败保留旧当前版本及孤立新文件，重启后跳过已占用版本，不覆盖失败历史。Runtime 登记按原顺序去重依赖，保留幂等任务身份。

Store 对已 committed 清单只核对输出 / 新增目录存在及路径安全，缺失时保留 committed 与前后版本，Runtime 标记 recovery_conflict 并暂停重叠范围写入；不撤销其他已提交文件，不覆盖用户再编辑。人工修复后重启只补后继登记，原模型调用次数、结果版本不变。未 committed 的部分 / 全部文件已写仍沿原清单校验与撤销。既有 prepare 已在一个 SQL 事务保存清单与 task.commit_id；输入 / 结果版本先落盘。健康 / 停止不等待数据发布锁，仍先认证与校验，真正停树 / 排空沿原服务生命周期。

永久测试新增 8 项，保护连接故障 / 缺库不重置权威状态、首次采集兼容、重复依赖、孤立配置版本、存活进程真实 SQL 写失败、已提交缺失内容及恢复、健康 / 停止可用性。真实 SQLite BEGIN IMMEDIATE 竞争分别在已写 1 / 2 个文件后制造写超时，并非 mock SQL 异常；验证业务 API 拒绝半成品读取、停树可结束、数据库仍不可写时不谎报恢复，解锁重启安全撤销、预算 1 次及前后版本保留、无模型重跑 / 后继登记，重复恢复幂等。原 Windows 文件中断 / 用户冲突及 Runtime / Config / Startup / Web / Corrections 组继续通过。

最终完整产品 **205 tests / OK，95.213s**（seventh-product-complete.log），Chromium **5 tests / OK，18.661s**（seventh-browser-final.log）。一次性 actual AIAgent / PM 进程 + 真实监听 run_service 探针在第一次预算许可前用实际 SQLite 写锁超时：上游生成请求 **0**，API 隔离，stop_background 在数据库仍锁定时完成，真实 Job / PM 子进程与服务线程退出；重启次数 0、任务 failed，无语义验收。证据 seventh-live-pm-results.json、seventh-live-service-results.json 及对应日志在忽略目录 .artifacts。合成离线迁移复跑通过停写门禁、整根备份、幂等核验、保留预算、零新写入回退及恢复采集后拒绝旧备份回退（seventh-migration-final.log）。

收尾 Ruff、uv lock --check --offline、32 份文档 / 445 条本地链接及 git diff --check 通过；探针 / 浏览器 / 测试进程均已退出。

R6.4 / R6.6 已勾选，R6 全部完成；统一 Design、M01 / M08 Plan、README 与待办同步。下一步仍有 R5.1 的 IPC / 生命周期 / 交付 / 持久控制结构清点及启动接入，未把本批当整体完成。Goal 最新查询为 usageLimited，未自行改状态或新建替代 Goal；本轮 heartbeat 已授权的本地实施已完成。Desktop G2、获准真实模型语义、物理休眠及 GitHub CI 未验，无远端写入。

## 2026-10-18 第八批：程序操作与生命周期严格模型

本批在 57a891dbc8dfc584fd55d1ee180e0287c2c48238 上续接 M01-R5.1。Hermes 适配的管道消息、生成 attempt / 请求、搜索操作包装与完成报告改用 Pydantic strict / extra=forbid / TypeAdapter，删除替代掉的字段集合 / 类型遍历；完成报告复用 ChildDiagnostic，不再重复校验。搜索实际参数继续复用 M06 模型；读取审计模型留在 M07，复用 RecordRef / SourceRef，来源存在、任务状态、实际读到的固定快照仍由原业务函数检查。模型 SDK 请求、消息分帧、认证及停树方式不变，PM 不安装产品框架。

先复现空 attempt_id 被 Runtime 自动生成并扣额，再在管道的 GenerationRequest 前置拒绝，坏输入不保存请求版本或额度。Runtime 直接调用原有可选 attempt_id 契约不变。生命周期新增严格持久模型，读取时拒绝 bool / 非整数计数、错属 session、未知事件 / 字段，复核已有 aware UTC 规则；坏记录不被后续事件覆盖、不形成关闭信号。新增两项永久回归保护这些持久 / 额度不变量；原只读查询回归改走实际 audit_reads 程序入口，错误审计无状态变更，合法审计后保留固定版本结果。

完整产品 **207 tests / OK，100.089s**（eighth-product.log）；随后增强的查询 / 审计组 **9 tests / OK，2.315s**；Chromium **5 tests / OK，20.546s**（eighth-browser.log）。实际 PM AIAgent 七场景 / **43** 个合成 provider 到达请求完成无工具筛选、查询 / 来源、文件 / Shell、503 恢复、16 次完成与 17 次拒发。旧一次性查询 fixture 使用了非正式 ID / version，本轮改为合法合成引用并补工具返回正文断言后复跑通过，不能仅凭任务 succeeded 认定读取成功（eighth-direct-hermes-final.log）。实际 Episode / 评分 / M04 / M05 链 **22** 次请求及真实 Tavily keyless → M04 → M07 / 用户编辑链 **14** 次生成通过（eighth-episode.log、eighth-expansion.log）。这些 provider 生成内容均为合成响应，不作为实际模型语义验收。

PM 实际 import distillai.hermes 后 Loguru / FastAPI / Uvicorn / FastMCP / NetworkX / settings / scheduler 加载集合仍为空（eighth-pm-import.log）。Ruff、锁一致性、32 份文档 / 448 条本地链接及 diff 空白检查通过，测试 / 探针进程均已退出。证据仅保留忽略目录 .artifacts，未使用个人数据，未执行远端写入。

统一 Design、M01 / M03 / M07 执行记录及待办已同步，material_revision 仍为 3。R5.1 保持未勾选：任务引导 / 回复、交付及其余持久控制记录继续清点；启动接入 / 清理审计仍有可独立实施项。Goal 用量状态未变，不重建或标 complete；外部 Desktop / 模型语义 / 物理休眠条件沿待办，不阻止后续本地工作。

## 2026-10-18 第九批：原生入口与后台独立性

本批在 ed76de8b07ed57f2b95ed6d6cf3a466efdcb4b84 上续接 M01-R3.4 / M07-R1.2。用 FastMCP 的通用 StdioTransport 直接执行 powershell.exe / scripts/start.ps1 -Action Mcp，真实 PM 检查与产品入口均实际运行，数据根含空格且只使用合成内容。发现此前“冷启动 ready”不等于独立常驻：venv launcher 的嵌套 Job 让 CREATE_BREAKAWAY_FROM_JOB 成功，但后台仍属于 SDK 的外层 Job；stdio 退出后进程 exit 0、health 失效而 instance.json 残留。一次性直接核对 SDK 所持 Job 的实际成员关系，仅作诊断，不在产品依赖其私有属性。原始证据 ninth-start-membership.log。

新增真实 launcher + 外层 ProcessJob 永久回归，旧实现返回 started 导致失败。修复后后台先以 CREATE_SUSPENDED 创建，用公开 IsProcessInJob 检查不属于任何 Job 才恢复；仍受 Job 管理则终止 / 等待，产品入口不会执行，不创建控制库或宣称 ready。恢复动作复用 windows.py 原有 NtResumeProcess 窄适配，ProcessJob.resume 继续原锁与普通任务语义，没有新建执行器或绕开父进程管理。保守拒绝意味着当前测试执行器自身 Job 也可能阻止自启，正向常驻不能在该上下文中假定通过。

原启动并发 / 实例 / 轮询 fixture 验证业务服务而非独立常驻：现在明确由测试负责回收服务，并仅在这些 fixture 替换“脱离全部 Job”的环境前提，仍执行真实 Popen、挂起 / 恢复、Uvicorn、锁、API 与停止。直接受限 Job 和新增嵌套 launcher 两个拒绝用例在未替换的独立子进程运行，不能将 fixture 通过当作实际脱离证明。原 Windows 9 项通过；启动 / 调度 **9 tests / OK，17.665s**，最终完整产品 **208 tests / OK，97.867s**（ninth-startup-tests.log、ninth-product.log）。既有采集行为脚本通过，Push Guard **16 tests / OK，31.312s**。

最终原生探针（ninth-start-entries-final.log / ninth-start-entries-results.json）确认：Check 不创建数据库；受限 Serve 返回 exit 1、无运行实例；MCP 冷启动明确 backend_not_started。随后由测试在 MCP Job 外启动真实前台 serve fixture，Serve / Check 返回同一 instance_id / pid，公开结果无 token；原生 MCP 精确查询无匹配、反馈幂等通过，stdio 退出后 fixture 仍活着且不属于 SDK Job。Stop 等待服务退出，再次 Stop 返回 false。第二个真实前台实例供 Web 复用；webbrowser.open 经本次进程的 BROWSER 捕获 helper 交接，实际 Chromium 完成一次性引导、303 清 URL 和页面读取。这不是系统默认浏览器或 Web 正向冷启动证明。

实际产品解释器为项目 .venv，底层进程镜像 D:\miniconda3\python.exe；Hermes 检查使用 PM Python 3.14.7。全程零模型请求，无个人数据，全部自建服务 / stdio / 浏览器退出。原 Windows CI 的锁安装、Ruff、采集 / Guard / 产品 / 浏览器命令与权限配置已核对，未写远端或声称当前 SHA 的 GitHub CI 通过。

收尾 Ruff、uv lock --check --offline、32 份文档 / 453 条本地链接及 git diff --check 通过，自建探针 / 服务进程均已退出。统一 Design、M01 / M07、README 和待办同步；保留 R3.4 / R1.2 未勾选，正向独立常驻与 Desktop 需在普通 Windows 终端 / 真实平台验证。当前无需新增技术选型，仍不引入系统服务、计划任务或父进程伪装。R5.1 的引导 / 回复 / 交付 / 控制记录仍是可独立实施工作；Goal 状态未变，不标整体完成。

## 2026-10-18 第十批：任务引导、回复与选材持久结构

本批在 44d9444b7a58312efe1caa680574de4871ce731a 上续接 M01-R5.1。任务子进程 stdin 的 pipe 地址 / 32 字节 authkey、固定 TaskInput 和程序 result / error 回复使用严格 TypeAdapter；ModelConnection 直接从 Config 共用，原 _LLM 仅更名为可复用定义，配置字段 / 错误路径 / 持久格式不变。消息大小统一引用 TaskPipe.MAX_MESSAGE。连接前验证引导，建立私有 home / 导入 AIAgent 前验证任务；非法任务关闭连接，以固定错误文本报告。程序回复恰为 result 或带白名单 code 的 error，完成确认沿既有 result=null，不重复建立协议 / 通信层。

选材记录、当前轮指针和输出尝试接入 M07 严格模型，共用 Candidate / RecordRef / Version，历史 / 状态 / 后置登记通过同一记录读取入口。保存的 round_key 必须匹配文件名，恢复前必须匹配 session。先复现旧实现接受 bool 恢复次数 / 未知字段 / 错轮次、跨 session 指针读出其他选材并增加计数，再修复；错误字节保留。原“最多三条”、版本失效排除、写出失败不标已交付和两次 compact 复用已写文本 / Prompt 的契约保持。

新增四项永久测试保护坏引导不得连接、歧义 / 多余回复不得采用、非法选材不推进及跨 session 恢复拒绝；原 UTF-8 / stdout 用例增加布尔额度输入的拒绝 / 连接关闭检查，先在旧实现失败后修复。定向工具 6 项 / Config 8 项 / Context 11 项通过。完整产品 **212 tests / OK，100.402s**（tenth-product.log），Chromium **5 tests / OK，17.925s**（tenth-browser.log）。

实际 PM AIAgent 七场景 **43** 个合成 provider 到达请求通过，包含正常 result、BudgetError error、查询 / 来源 / 文件 / Shell、503 恢复、16 次可完成 / 17 次拒发；实际 Episode / M04 / M05 链 **22** 次与真实 Tavily keyless → M04 → M07 / 用户编辑链 **14** 次生成通过。证据 tenth-direct-hermes.log、tenth-episode.log、tenth-expansion.log。PM 实际 import distillai.hermes 的 Loguru / FastAPI / Uvicorn / FastMCP / NetworkX / settings / scheduler 加载集合为空（tenth-pm-import.log），未在 PM 安装产品依赖。生成内容仍是合成 localhost 响应，不作为真实模型语义验收。

全范围 Ruff、离线锁检查、32 份文档 / 456 个本地链接及 git diff 检查通过；本批测试与 PM 探针进程均已退出。统一 Design、M01 / M07 和待办同步，material_revision 仍为 3；没有有效数据迁移或公开 API 变化。R5.1 仍未勾选，后续清点任务 / 提交及其余事件控制记录；已完成的任务引导 / 回复、选材持久模型不重复改写。普通终端独立冷启动、Desktop G2、物理休眠及真实模型语义条件不变，未执行远端写入，Goal 不标整体完成。

## 2026-10-18 第十一批：SQLite 任务与提交严格模型

本批在 33a984d0eaeb009e71f53c7a689b931fc82c7e45 上续接 M01-R5.1。State 用严格 TypeAdapter 校验完整任务 / 独立副本记录和提交清单，包含 attempts、模型次数 / 布尔控制字段、配置快照、依赖 / 版本、文件身份 / 元数据和提交项状态；JSON 列先校验为对象，再组合权威列 / 关联表，缺失幂等键也拒绝。原 SQLite 表 / 事务、prepared 绑定及发布恢复协议不变。TaskKind / PublicationScope 由运行层共用，准备结果直接引用各领域已有模型；搜索包装归 M06，IPC 和持久审计共用实际 web_search / fetch_page 字段。

先复现非法任务写入会覆盖原记录 / 次数、损坏任务 / attempt 会被采用、含未知字段的提交项被恢复为 rolled_back；补三项永久回归后转绿，损坏字节与源文件保持原状。JSON 非对象的列表 / null 在合并前拒绝，避免先抛类型错误；提交路径继续复用原词法检查。既有纠错组验证原 reanalysis_prepared_version / 后置等待字段，不删字段或放宽未知字段。一次性检查另确认缺失幂等键拒绝、非法清单写入不覆盖权威记录 / 文件，未新增永久迁移测试。

最终完整产品 **215 tests / OK，97.822s**（eleventh-product-final.log），实际 Chromium **5 tests / OK，18.859s**（eleventh-browser.log），定向纠错 **10 tests / OK，4.569s**。实际 PM AIAgent 预算 / 文件 / Shell / 查询 / 来源 / 503 恢复为 **43** 个合成 provider 请求，Episode → M04 → M05 为 **22** 次、真实 Tavily keyless → M04 → M07 → 用户编辑为 **14** 次。另实际归属纠错 → M04 → M05 / 独立认知纠错 **11** 次、新材料旧边界修订 / M04 / M05 **12** 次通过，验证同提交等待、历史来源读取和最新版本解除。证据 eleventh-direct-hermes.log、eleventh-episode.log、eleventh-expansion.log、eleventh-corrections.log、eleventh-material.log；生成 provider 仍是合成 localhost，不作为真实语义质量验收。

实际 PM 导入产品框架集合为空（eleventh-pm-import.log）；合成离线迁移、重复核对、预算保留、整根回退及新采集拒绝回退通过（eleventh-migration.log）。全范围 Ruff、离线锁、32 份文档 / 457 个本地链接及 git diff 检查通过。统一 Design、M01 与待办同步，material_revision 仍为 3，无真实数据迁移或远端写入。R5.1 仍未勾选，下一步为私有配置、episode 游标、外扩覆盖及 M07 调用 / 反馈控制记录清点；外部验收和 Goal 未完成条件保持。

## 2026-10-18 第十二批：配置、游标、覆盖及请求归属

本批在 2fd50f496d1b4c779fcacfcbb0f17c7970d39475 上续接 M01-R5.1。私有配置复用 ConfigValues 的严格结构并核对文件版本，保留旧文件缺少 search 时的只读缺省；episode 游标读取接入原 SessionState 并核对 session，关键词保持原值。外扩覆盖复用 Identifier / Version 与严格有限数值；坏游标 / 时间 / 依据不再被读取采用或由 tick 改写。

M07 查询记录区分直接结果 / 后台任务 / 提前取消，反馈区分 awaiting_source / registered；请求边界及嵌入的 QueryArgs / FeedbackArgs 沿归属模块复用。共同读取入口核对 task 种类、调用 / 反馈 ID 和请求内容，反馈文件名同时匹配请求 ID hash。先复现错绑查询会取消另一调用、错绑反馈会报告另一请求任务、布尔边界与未知字段仍被采用 / 推进，再补八项永久回归转绿；另加一项保护旧搜索配置缺省及原字节。既有提前取消、失败保留、来源唯一关联和幂等契约继续通过，没有更改公开载荷 / 持久格式或真实数据。

最终完整产品 **224 tests / OK，96.860s**（twelfth-product-final.log），实际 Chromium **5 tests / OK，19.380s**（twelfth-browser.log）；定向配置 / Episode / 外扩 / 查询 / 反馈 / FastMCP 组 **55 tests / OK，9.164s**。复核补齐任务内反馈结构的同模型校验，缺失反馈不再抛未处理类型异常；定向反馈 / MCP **10 tests / OK，0.809s**（twelfth-feedback-final.log），对应坏输入回归先失败再通过。实际 PM AIAgent 的预算 / 工具组 **43** 个合成 provider 请求、Episode → M04 → M05 **22** 次、实际 Tavily keyless → M04 → M07 → 用户编辑 **14** 次生成通过（twelfth-direct-hermes.log、twelfth-episode.log、twelfth-expansion.log），生成 provider 仍是 localhost 合成响应，不作模型语义质量证明。PM 导入产品框架集合为空（twelfth-pm-import.log）。

真实 FastMCP PythonStdioTransport 两工具、精确查询 / 严格参数 / 反馈幂等、stdio 退出后的预启动测试后台存活通过，零生成（twelfth-stdio.log）；服务由测试管理，不证明独立冷启动或 Desktop。合成离线迁移 / 重复核对 / 预算保留 / 回退 / 新采集拒绝覆盖通过（twelfth-migration.log），一次性校验非法配置不建版本、错 hash 反馈保留原字节（twelfth-extra-records.log）。全范围 Ruff、离线锁、32 份文档 / 461 个本地链接及 diff 检查通过，测试与 PM / stdio 探针均已退出。统一 Design、M01 / M03 / M06 / M07 和待办同步，material_revision 仍为 3；R5.1 继续审计 M05 重分析依赖及启动 / 采集控制结构，再做 R4.2 清理。无远端写入，Goal 不标整体完成。

## 2026-10-18 第十三批：严格结构及复用清理收尾

本批在 d0481a1d0e1b467d0112d6c3cbf961fba3398d4c 上续接 M01-R5.1 / R4.2。M05 重分析依赖、启动实例 / health / PM 检查事实与采集游标接入严格模型；非法状态、版本、布尔协议 / 字符串 ready 和未知字段在采用前拒绝，坏记录保留原字节。Runtime 登记 / 增量来源、episode 历史来源参数和纠错结果复用既有 TypeAdapter，删除重复字段 / required / 枚举遍历，保留来源归属、跨版本、引用范围及权限判断。启动地址补拒绝只有 password 的 authority，实例清理失败只记白名单诊断并保留记录。

固定 Hermes 六个同步文件 / Shell 工具在原 registry handler 前直接复用其发布的 JSON Schema，由 PM 已有 jsonschema 校验；handler 签名 / kwargs、实际文件 / Shell 处理及调用预算不变。实际 PM registry 探针六工具非法参数均未到达 handler，副作用为零（thirteenth-upstream-schema.log），正常 AIAgent 工具链继续通过。环境检查补核对 PM 现有 jsonschema；未安装 PM 包、修改上游或建立第二套工具执行器。采集通知复核保持 200ms 总截止、不读响应、不启动后台；游标坏值仍从原文重采且保留旧文件（thirteenth-cursor-audit.log）。

新增五项永久回归，先复现坏重分析状态 / 实例元信息和 health 被采用、密码地址被接受及非法工具参数到达 handler，再转绿。完整组暴露旧 Context fixture 缺失真实记录必填字段，补齐 fixture 后复跑，没有放宽生产校验。定向认知 / 纠错 / 采集 / 启动 **40 tests / OK，24.708s**（thirteenth-focused.log），Runtime / 纠错 / 工具 **32 tests / OK，6.482s**（thirteenth-schema-green.log），Context **13 tests / OK，2.845s**（thirteenth-context.log）。最终完整产品 **229 tests / OK，96.782s**（thirteenth-product-final.log），实际 Chromium **5 tests / OK，24.953s**（thirteenth-browser.log）；首轮旧 fixture 失败保留原日志，不当成通过证据。

实际 PM AIAgent 七场景 **43** 个合成 provider 到达请求，Episode → M04 → M05 **22** 次、真实 Tavily keyless → M04 → M07 → 用户编辑 **14** 次、归属纠错 / 独立认知纠错 **11** 次、新材料旧边界修订 **12** 次生成通过；证据 thirteenth-direct-hermes.log、thirteenth-episode.log、thirteenth-expansion.log、thirteenth-corrections.log、thirteenth-material.log。生成 provider 仍是 localhost 合成响应，不作为真实模型语义验收。PM 环境 / SHA / AIAgent 检查通过，实际导入产品框架集合为空，已有 jsonschema 4.26.0（thirteenth-environment.log、thirteenth-pm-import.log）。

真实 FastMCP Python StdioTransport 的两工具、精确查询 / 严格参数 / 反馈幂等及 stdio 退出后的预启动测试后台存活通过（thirteenth-stdio.log），不作为独立冷启动或 Desktop 证据。合成离线迁移、重复核对、预算保留、整根回退及新采集拒绝覆盖通过（thirteenth-migration.log）；旧采集合成 UTF-8 / 并发 / 隔离 / fail-open / 通知通过，Push Guard **16 tests / OK，31.346s**（thirteenth-push-guard.log）。全部本批测试 / PM / stdio 探针进程已退出。

全范围 Ruff、离线锁检查、32 份文档 / 465 个本地链接及 git diff 检查通过。

26 份生产 Python 的复用清点确认 BaseHTTPRequestHandler / ThreadingHTTPServer、旧模型路由、自定义 Formatter 和重复 Tavily 请求实现均无剩余调用（thirteenth-reuse-audit.json）。保留库未覆盖的 Windows 根句柄相对操作 / 精确 FILETIME / 恢复挂起窄绑定，以及持久额度、固定版本 / 来源归属、原子发布恢复和有界不等待采集通知等产品契约。M01-R5.1 与 R4.2 据此勾选；Design、README、M01 / M02 / M03 / M05 及待办同步，material_revision 仍为 3，无有效持久格式变化或真实数据迁移。下一轮审计 R1.6 的客户端重建 / 断流 / 连接拒绝 / 重启续额等实际 SDK 边界证据，并推进其余依赖满足的本地接入；R3.4、G2、物理休眠和真实模型语义仍未完成，无远端写入，Goal 不标整体完成。

## 2026-10-18 第十四批：实际 SDK 边界与本地验收

在 e5565bd9add531a16cadacfccb1ca73099e89d0b 的干净任务分支续接 M01-R1.6。固定 Hermes 源码仍为干净 a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed，使用原产品 HermesExecutor / TaskPipe / Job / SQLite 和已准备 PM Python 3.14.7，不更改生产代码、上游或 PM 包。一次性探针只用 sys.setprofile / threading.setprofile 观察产品客户端构造返回值；不替换 SDK 请求、重试、客户端构造方法或模型处理。

四类实际 AIAgent 场景共 **23** 个 localhost 合成 provider 到达请求，逐项与持久账本一致：SSE 响应建立后截断，随后恢复，共 **2** 次均计数；前三次请求在响应头前断开，触发真实 primary_recovery 重建，第四次成功，共 **4** 次均计数；端口已绑定但尚未 listen，首次连接被拒绝，对应 attempt 保留 not_sent 且 model_calls=0，随后启动监听，**1** 次成功 / 计数。观察到 **18** 个共享 / 请求专用 / 重建 SDK 客户端，全部仍有产品发送门禁且 max_retries=0。证据 fourteenth-sdk-boundaries.log / .json。

重启续额使用同一任务：第一次实际生成后返回非法 JSON，任务失败但保留已用 **1** 次；关闭并重新打开 Store / Config / Runtime，显式重试启动新的实际 PM AIAgent，仅能再发 **15** 次，第 17 次尝试在发送前拒绝，总到达 / 持久额度为 **16**。再次关闭 / 重开并重试，仍为 **16**，新增到达 **0**，两次重试均按 BudgetError 失败，没有清预算或重写原任务输入。结合上一批正常工具、评分、只读查询、无工具筛选、503 和第 16 次完成证据，R1.6 的本地机械场景已补齐；当前直连实现的一次获准真实模型流式工具往返仍缺可用私有配置，R1.6 保持未勾选，不继承旧代理的真实调用结果。

复用原组完成本地验收：SDK 传输 **5 tests / OK，0.349s**（fourteenth-transport.log）、Runtime **15 tests / OK，1.700s**（fourteenth-runtime.log）、采集 **11 tests / OK，2.027s**、来源 **7 tests / OK，0.446s**（fourteenth-capture.log、fourteenth-sources.log）；存储 / SQLite / episode / 纠错 / context / MCP / feedback / Web / HTTP **102 tests / OK，65.893s**（fourteenth-acceptance-final.log）。覆盖丢通知补登记、进程死亡释放锁、旧输入、并发编辑、查询取消、发布中断 / 数据库失败恢复、失败不推进和两次 compact 原选材复用。首次用 stdin 分组执行时 Windows spawn 无法重载 <stdin>，已改为有 main 保护的临时文件入口后完整复跑；未改产品或放宽测试。

真实 Tavily keyless → 外扩 → M04 → M07 → 指定字段编辑再次通过，共 **14** 次合成模型请求，外扩 / M04 / M07 / 编辑分别 **5 / 3 / 3 / 3** 次；新版本进入 M07，材料计数保持，外部内容未当用户掌握，旧版本可回读（fourteenth-expansion.log）。据当前恢复组和这条实际搜索 / 读取链勾选 A1.3；模型判断质量仍未验收。

实际 Chromium 永久回归 **5 tests / OK，18.125s**（fourteenth-browser-final.log），另一次性检查四入口 / 空列表 / 名称筛选 / 未知记录 404 重试、原来源弹窗与 Escape、跳至主内容 / Tab / Shift-Tab、迟到历史响应不覆盖当前配置页，以及 1280 / 390px 布局无横向溢出，通过后人工查看 desktop.png / narrow.png（fourteenth-web-final.log、fourteenth-web/）。临时脚本最初误把 tabindex=-1 的主区域当作 Shift-Tab 停点，修正为实际上一导航项；路由等待沿 Playwright 事件驱动完成。旧详情 / 保存异步、409 / 失败留输入、脚本文本渲染由原五项回归保护。M08-R2.3 据此勾选；R2.1 的关联版本 / 子图 / 两列表 / 选材与 R2.2 两类纠错的完整浏览器验收仍待推进，A1.4 不提前完成。

本轮只补验收证据与 Spec 状态，不新增永久测试、依赖或生产路径。全范围 Ruff、离线锁、32 份文档 / 467 个本地链接及 git diff 检查通过。Design、M01、M08 和待办同步，material_revision 仍为 3；真实模型 / Desktop G2、普通终端独立冷启动、物理休眠与远端授权条件保持。全部本批探针、测试、Chromium 和 fixture 已结束；无真实数据迁移或远端写入，Goal 不标整体完成。

## 2026-10-18 第十五批：完整 Web 验收与修订链收尾

在 f2b2c9b42efc1e17e269a03883a508a0bee928a4 的干净任务分支续接 M08-R2.1 / R2.2、M05-R2.1，并核对 M03 / M04 修订交接。工作区、固定 PM / Hermes、当前 Goal 和批准记录已核对；未改生产代码、依赖、上游或真实数据。

独立合成 ASGI / Chromium 完整交互 **2 tests / OK，21.443s**（fifteenth-rich-web-final.log）。复用 CorrectionTests / BrowserTests 和真实 context 准备 / 筛选 / 发布入口，验证 23 条分页 / 准确名称筛选、原用户来源、编辑后旧知识版本只读、四项关联记录（外扩、两份不可变上下文、已选素材）。两份 MCP 背景 / 注入候选分别展开，纯文本偶含 ID 不当关联，历史外扩可打开；输出阶段明确不等于平台收到。

两窗口正文 / 认知纠错均取得实际 409 并保留输入 / 原因；归属 422 不丢行范围，修正后观察 running → succeeded。当前依据的等待说明附 episode 版本，M05 故意失败保持等待，经新 M04 → M05 解除，旧失败任务 input_version / model_calls / status 保持。独立认知纠错先失败留输入，再新请求成功，用独立 user_submission、知识正文保持，独立应用仍未知。维护回调合成，真实模型调用 0；人工查看 fifteenth-web/ 的 waiting.png、corrected-judgment.png、historical-expansion.png。

临时探针修正多处文本定位及同 URL 刷新；最小探针另确认当前 Playwright wait_for_function 对 async 函数采用 Promise 真值，即使最终 false 也提前返回。改为真实 API 状态有界轮询、明确超时失败后完整复跑通过；没有把等待脚本错误当生产问题或放宽断言。结合第十四批五项永久回归、四入口 / 空列表 / 404 / 迟到响应 / 键盘 / 窄屏，M08-R2.1 / R2.2 完成，模块状态改为 implemented；A1.4 的实际日常交付 / 自然反馈及整体产品不提前完成。

当前 PM AIAgent 明确归属 / 空 M04 / 空 M05 / Web 独立纠错共 **11** 次合成生成（5 / 1 / 1 / 4），新材料旧边界修订 / M04 / M05 共 **12** 次（10 / 1 / 1）；历史来源 RPC、新引句、固定来源、同提交等待和最新修订解除均通过（fifteenth-corrections-direct.log、fifteenth-material-direct.log）。episode / 纠错 / context / Web **43 tests / OK，12.467s**（fifteenth-targets.log），知识 **9 tests / OK，1.877s**（fifteenth-knowledge.log），继续保护并集守恒、同轮完整、跨 session / 旧输入、固定次数、直接依赖刷新与图失败不重算。M03-R2.3 据此勾选。M04-R2.2 结合新增空结果交接、浏览器编辑及第十四批 Tavily → M04 → M07 / 用户编辑 14 次证据勾选；两阶段 src Git 树同为 3348828b89b92d12fafcc69a92eab7187a2adeb3。生成 provider 为 localhost 合成响应，不作模型语义证明。

七组原语义材料只读复核通过：13 行队列引用可读取、字节与不可变版本一致，四类 Prompt hash 与当前文件一致，原 manifest / 队列未改，模型调用 0（fifteenth-semantic-audit.log / .json）。准备配置章节与当前产品一致；本次实际模型私有配置未提供，M05-R2.1 的配置核对与 R2.2 继续待办，材料不重复重建。

全范围 Ruff、离线锁、32 份文档 / 473 个本地链接及 git diff 检查通过。本轮仅保存验收证据 / 文档及状态，没有新增永久测试或改生产逻辑。同步 Design、M03 / M04 / M05 / M08、版本 / Spec 入口、README 与待办，material_revision 仍为 3。下一轮审计 M06-R2.1 周期 / 重启公平性和 M07-R1.3 查询 / 独立取消的剩余本地机械证据；Desktop G2、普通终端独立冷启动、物理休眠、真实模型和远端授权仍单列。全部本批 fixture / 浏览器 / PM / 测试进程已退出，无真实数据迁移或远端写入，Goal 不标整体完成。

## 2026-10-18 第十六批：查询取消验收、实例校验与外扩停机待决

在 59aead4bbdd13389c0994060cc9cc84f9f2a0883 的干净任务分支续接 M07-R1.3 / M06-R2.1，核对规则、批准记录、工作区和 Goal；固定 Hermes / PM 环境保持。MCP local_request 的手写实例身份判断漏用已有严格模型，bool protocol、字符串 ready 与未知字段可能通过。直接复用启动模块 INSTANCE_RECORD / INSTANCE_HEALTH，非法元信息不发健康请求、非法健康响应不发业务请求；原文件字节不改，有效实例继续复用。只改该共用入口，不新增 schema / 依赖或重写启动流程。

新增永久 MCP 边界契约先复现 **5 tests / failures=6**，修复后 **5 tests / OK，0.598s**（sixteenth-mcp-red.log / sixteenth-mcp-green.log）；六种非法输入与正常复用均有 HTTP 请求 / 文件字节断言。最终完整产品 **230 tests / OK，97.416s**（sixteenth-product-final.log）。

实际 FastMCP PythonStdioTransport → HTTP 后台 → PM AIAgent 的准备 / 查询探针通过（sixteenth-context-stdio-final.log / sixteenth-context-stdio.json）。准备 4 次、查询 3 / 1 / 3 次，共 **11 次 localhost 合成生成**；ID / 名称直接查询 0 次，无匹配与索引失败明确区分，严格参数拒绝。普通维护占名额时两个同内容查询以独立 UUID 排队，取消一个不影响维护或另一份；运行中取消后真实 ProcessJob handle 关闭，再释放名额并完成剩余查询。SDK timeout 返回 MCPError，其排队任务取消且生成 0 次。

所有查询 manifest 仅 query_records / read_source，scope / commit 均空；实际 AF_PIPE 记录 / 来源读取审计与返回已读版本通过，查询预算合计 7 与实际到达匹配，知识 / episode 字节保持，活动任务 / Job 清空。stdio 退出后测试预启动服务存活；这不证明独立冷启动或 Desktop G2。取消时合成 provider 观察到预期连接重置，探针断言及退出码通过。M07-R1.3 据此勾选，R1.4 的 Desktop 条件仍未满足。

实际 APScheduler / service_lifespan / SQLite 外扩探针通过默认周期 3600 秒 → 配置 1 秒的下一次等待重排、初批 10 → 后批 1 且不清覆盖；失败经两个调度事件不重跑，显式 retry 留原输入 / 已用 1 次许可。空闲重启恢复持久已到期项，覆盖 12 → 13，旧任务输入 / 次数保持，无变化再经两个调度事件不重复（sixteenth-expansion-scheduler-final.log，报告为 sixteenth-expansion-scheduler.json）。执行回调合成，真实模型请求 0。

初次调度探针在关闭时混入新到期任务而失败；用公开 scheduler.pause 分离空闲重启后，独立探针确认在途停机的真实缺口：任务 cancelled / runtime_stopping，保留已用 1 次；重启 tick 仍返回该 pending，retry 拒绝 cancelled，无新任务或覆盖推进（sixteenth-expansion-active-stop-final.log，报告为 sixteenth-expansion-active-stop.json）。最早独立探针另曾因错误使用两个 Store 对象嵌套锁而失败，改单 Store 后才取得上述产品证据。恢复策略写入 pending，未擅自清理、重建或放开取消重试，M06-R2.1 保持未完成。

本批同步 Design、M01 / M06 / M07 Plan 和待办；material_revision 仍为 3。全范围 Ruff、离线锁、32 份文档 / 477 个本地链接与 git diff 检查通过；本批探针和任务子进程均已退出。README 启动 / 用户流程、配置及前端均未变化，无需改 README 或重跑浏览器验收。后续可独立推进 M06-R1.4 搜索凭证优先级 / 错误与 R2.2 主张 / 预算发布边界；已完成的查询和空闲调度证据不重复实施。普通终端独立后台、Desktop、物理休眠、实际模型语义与远端授权仍单列，Goal 不标整体完成。

## 2026-10-18 第十七批：M06 搜索与发布边界验收

在 588a9e21ef8d9896be6484a7fd5386aff3a52b13 的干净任务分支核对规则、批准 Plan、Goal、固定 Hermes SHA / PM 环境、GitHub 账号 / 默认分支与 Issue #4 OPEN；无其他聊天修改。当前 M06-R1.4 / R2.2 实现已具备，按 test-necessity-review 复用永久测试与临时实际探针，未改生产代码、依赖、Prompt、永久测试或真实数据。

现有外扩 **12 tests / OK，2.239s**（seventeenth-expansion-tests.log）。实际 TaskPipe / 任务子进程首帧验证五种合成凭证选择：私有配置优先于固定启动环境、空脱敏输入不抹 key、显式 null 清除后回退、两者为空 keyless、登记后更新私有配置仍用任务旧版本。继承的 TAVILY_API_KEY / TAVILY_BASE_URL 不进入子进程环境，连接 key 不进入业务 inputs；捕获首帧后停止实际 Job，SDK / 模型未初始化。另以原工具确认 16,000 字符截断、URL / 时间与不可变字节版本（seventeenth-key-delivery.log / .json）；真实供应商 / 模型请求均 0。

实际 PM 解释器中，固定上游 Tavily 请求 / 归一化与产品 _tavily_client / _search_tool 经过 **27 次 HTTPX MockTransport 请求**：keyed / keyless 的 Authorization / access-mode、401 / 403 权限、402 / 429 / 432 / 433 限流、500 / 302、读取超时、超过 2 MiB、坏结果、Extract 失败。错误保留对应 code / HTTP status，不返回供应商响应正文或合成私有 canary；自定义 endpoint 在发送前拒绝，provider.httpx 离开后恢复（seventeenth-search-adapter.log / .json）。该组无供应商 / 模型网络，不冒充真实账号额度验收。

实际 keyless Search / Extract 读取 https://docs.tavily.com/documentation/keyless，取得 **6,692 字符、truncated=false、read_at=2026-10-18T02:19:30.651334Z**，完整正文 / URL / 读取时间及搜索候选 / 提取结果保存在忽略的 seventeenth-primary-source.json。实际 AIAgent 外扩 / M04 / M07 / 用户编辑 **5 / 3 / 3 / 3，共 14 次 localhost 合成生成**；搜索和提取不增加模型计数，未核查连接保持、外部来源不算用户掌握、新知识版本进入 M07、材料更新次数不变、历史版本保持（seventeenth-m06-chain-final.log）。首次包装脚本漏 __main__ 保护导致 Windows spawn 重入、EOF 且模型调用 0；补保护后复跑通过，未将临时探针错误归为产品缺陷。

逐项证据临时检查 **6 种拒绝 / 通过**：supported / conflicting 各拒绝空来源、非本任务读取引用和另一连接无独立引用；实际已读来源的两种状态可保存，unverified 连接及开放问题保留。成功后只登记一项 M04、不登记 M05，覆盖正确；模型 / 供应商请求 0（seventeenth-claims.log / .json）。此处验证引用归属与结构，不用合成主张替代语义审阅。

实际固定 PM AIAgent 另验 **16 次完成 / 请求 17 次**，两任务实际各只到合成 provider **16 次**，均完成真实 keyless Search / Extract。前者发布固定版本、保留未核查连接并登记一项 M04；后者 BudgetError、commit_id / result_version 为空、无权威外扩 / 覆盖 / M04，知识原字节保持，活动任务 / Job 排空（seventeenth-m06-budget.log / .json）。首次临时脚本漏注册 importlib 模块导致 inspect.getsource 失败，未启动任务；修正后取得上述证据。

M06-R1.4 / R2.2 据新证据勾选；R2.1 保留在途停机恢复策略待决，R2.3 保留实际模型定性审阅。全范围 Ruff、离线依赖锁、32 份文档 / 479 个本地链接和 git diff 检查通过，本批探针 / 任务子进程已退出。同步统一 Design、M06 Plan、Spec 入口与 pending；设计 / 公开流程不变，material_revision 仍为 3，无需改用户启动 README 或重跑浏览器 / 完整产品组。后续逐项核对其余批准 Plan 的独立本地部分；Desktop、普通终端独立后台、物理休眠、实际私有模型配置 / 语义与当前 SHA 的 PR / CI 仍待相应条件，Goal 不标整体完成。

## 2026-10-18 第十八批：M02 失败恢复的实际进程补验

Goal 本次重新查询为 active，保留原目标与完整批准范围，未将恢复等同完成。在 76ee18b06d0f24cb851cece0ffd2f8644ddb0cbc 干净分支重新审核全部剩余步骤，发现 M02-R2.3 可独立补验正式 Hook 入口的组合失败窗口；此前只按 Desktop 条件归类过宽。按 test-necessity-review 复用既有测试与忽略目录的一次性探针，不改变生产代码、依赖、数据格式或测试工程。

实际产品解释器启动 plugins/distillai/hooks/dispatch.py，五类窗口通过（eighteenth-capture-failures.log / .json）：无后台实例时正文 / cursor 保存，新 Store / Runtime 两次发现扫描只补一项 episode，固定来源行 1–2；通知接收端保持不回应，Hook 仍退出，实际请求只含 connector / session_key。两次 Hook 总耗时 0.302 / 0.299 秒，包含进程初始化，不声称这是 socket 200ms 截止的精确计时。正常结束的每次 Hook 调用均 stdout={} / exit 0，不冷启动后台。

真实 FileHandle 写竞争下 Stop / PostToolUse 不改队列和 cursor；解锁后正文补采，丢失工具摘要不伪造补回。队列残缺 UTF-8 尾部在 PreCompact 采集时安全截除再补正文，原前两行字节 / 物理来源不改。实际探针子进程在队列已写、cursor 保存前被确定暂停，再终止并补采：保留原来源，在新位置允许重复，最终 cursor count=2；未把该窗口误写成恰好一次或跨位置去重。被终止进程由本探针创建，仅停止该 PID。

SessionStart / UserPromptSubmit 的合成调用不生成正文队列；缺失 transcript 产生压缩诊断，包含 FileNotFoundError、不含合成正文 canary 或原路径。既有产品采集 **11 tests / OK，2.295s**、来源 **7 tests / OK，0.669s**、旧采集验证 **PASS**（eighteenth-capture-tests.log、eighteenth-source-tests.log、eighteenth-legacy-capture.log）。没有模型调用、真实个人材料或 Desktop 插件启用操作。

同步 M02 Plan、Design 和 pending：R2.3 的本地失败恢复窗口已补齐，真实 Desktop 触发 / 字段 / 顺序仍待 G2，checkbox 保持未完成。全范围 Ruff、离线锁、32 份文档 / 480 个本地链接与 git diff 检查通过，本批探针进程已退出。其余开放步骤仍需已列出的 M06 恢复选择、普通终端独立启动、Desktop、物理休眠、实际模型配置 / 语义和当前 SHA 的远端验收条件；不重复此前已完成的局部验收。设计 / 用户流程不变，material_revision 仍为 3，无需更新用户启动 README 或重跑完整产品 / 浏览器组。Goal 保持原目标，不标整体完成。

## 2026-10-20 第十九批：批准恢复策略、M06 收尾与外部验收授权

用户批准 pending 中 M06 推荐方案，以及 Desktop 合成实测、普通 PowerShell 独立后台验收；物理休眠只允许北京时间每天 02:00–08:00。另明确授权本任务分支 Push 和创建 PR，不包含发布 Review、Merge、Tag / Release。现有半小时 heartbeat 已更新这些条件，未新建重复自动任务；Goal 查询仍为 paused，不谎称已恢复 Goal 调度或整体完成。

统一 Design 修订 4：仅周期外扩因 runtime_stopping 取消后可显式 retry 原任务，当前权限 / 固定输入重查成功才恢复授权、清原因并排队。其余取消终态不变；原输入 / 执行输入 / 配置 / Prompt / 预算与生成审计保留。处理历史同步原重试入口。永久回归先复现旧 retry 拒绝的两个失败，再验证重启和原预算完成、过时输入不改任务、撤权与其他取消拒绝。M06-R2.1 完成，M06-R2.3 仍待实际私有模型。

新证据保留于忽略目录 .artifacts：nineteenth-expansion-red.log / nineteenth-expansion-green.log、nineteenth-runtime.log；完整产品 nineteenth-product-final.log 为 234 tests / OK / 101.281 秒，永久浏览器 nineteenth-browser-final.log 为 5 tests / OK / 18.501 秒。实际 APScheduler / SQLite 重启结果 nineteenth-periodic-scheduler.json 验证两次回调不自动恢复、同任务显式继续且许可 1 → 2、提交才记覆盖、其后不重复。实际 Chromium/API nineteenth-periodic-web.json 验证受限按钮、三类其他取消隐藏和 202 留输入 / 次数；截图 nineteenth-periodic-resume.png 仅含合成材料。UI 探针初次未区分去重任务、并曾只等待相同标题，修正合成用例与任务 ID 等待后通过；不是产品缺陷。真实模型请求均为 0。

普通 PowerShell 配置 / 启动命令已准备在 .artifacts/open-acceptance-web.ps1，实际 Check 通过固定 Hermes SHA 与 PM 环境，instance=null。验收数据根 C:\Users\11954\.distillAI-acceptance，用户可在 Web 的配置 / 模型服务填写 endpoint、deepseek-flash 与密钥，保存后由 Agent 使用当前直连 SDK 验收；不索取聊天密钥，不手工改私有版本 JSON。独立后台仍需从 Codex Job 树之外实际启动，Desktop 信任 / compact / 中断仍需真实 UI，批准不等于这些验收已发生。当前检查时为北京时间 09:43，窗口外未触发休眠。后续依 pending 继续，远端 CI 结果另据实际 SHA 登记。

## 2026-10-20 第二十批：真实模型往返、独立后台与 CI 修正

用户在独立 Web 保存 OpenAI 兼容 chat_completions / deepseek-flash 配置 v2。当前 PM / Hermes / AF_PIPE 直连真实模型，read_source 流式工具往返实际 2 次生成、请求 stream=true、来源读取审计和最终 JSON 通过，M01-R1.6 完成。临时探针最初漏建 knowledge 目录，在模型请求前失败；补齐临时目录后通过，没有修改产品。七组原合成材料 / 不可变版本 / Prompt hash 再次核对，最新模型配置已冻结，M05-R2.1 完成。真实 M04 → M05 顺序执行中，部分 M05 实际输出存在结构校验和预算失败，R2.2 不提前通过；原失败任务、调用次数和生成记录保留。

用户确认已关闭启动用 PowerShell。原后台 instance_id=4ae6621ae8d447d486468185e3380e41 / pid=43304 仍 ready，原生 IsProcessInJob=false；真实 FastMCP stdio 连接，列出 query_context / submit_feedback，连接退出后同一实例仍 ready。临时探针初次预期了缩写 query，按实际注册名修正后通过，不改产品工具名。最后实际 Stop / 无存活实例通过，配置保留；证据 twentieth-independent-backend.json / .log。不能据此声称 Codex Desktop 工具全名前缀或 Hook 已验。

已 Push 2ba9740ab0a06b0bd742e8368a72731532bc3bef 并创建草稿 [PR #6](https://github.com/Spokey5243/DistillAI/pull/6)，已附加到本聊天；没有发布 Review 或 Merge。首轮 [CI run 39355377660](https://github.com/Spokey5243/DistillAI/actions/runs/39355377660) 对此 head 的合并结果执行：采集 / 锁与 Chromium 准备 / Ruff / Push Guard 通过，产品 234 项有 1 failure / 1 error，浏览器跳过，不能声称 CI 通过。runner TEMP 的 RUNNER~1 被安全路径处理展开为 runneradmin，测试误比较原始字符串；改为标准库解析后的路径等价，仍严格校验唯一目录。认知任务实际在启动 8.025 秒后成功，测试默认 5 秒超时；仅将该行为测试等待设为 30 秒，保留成功 / 来源去重 / 内容不变断言，不改生产等待或权限。10 项配置和 7 项认知测试通过；新提交触发新 CI，不 rerun 旧 SHA 掩盖失败，A1.1 仍待实际成功检查。

只读 powercfg 确认 S3 可用、S4 未启用，交流电唤醒定时器启用、直流禁用；没有修改电源设置或在北京时间 02:00–08:00 外触发睡眠。真实 Desktop 信任 / compact / 中断仍需界面操作，已有授权无需重复询问。

## 2026-10-20 第二十一批：恢复执行、严格结果适配与真实语义验收

用户明确恢复工作，半小时 heartbeat 已恢复 ACTIVE，沿用原授权与休眠窗口。Goal 工具仍返回 paused，接口不支持 Agent 将其改成 active；不新建替代 Goal，不以其旧状态阻止本次用户已明确授权的实施。保留四个暂停前修复文件与既有全部验收记录。

已核对 [PR #6 的 CI run 39356494487](https://github.com/Spokey5243/DistillAI/actions/runs/39356494487)：head `17a23c8d986870f1bfd4a5bf73f3b470438e6ee5`，base `fa13b0bc346ace5e54d94806caedd7bf40220bf0`，实际 tested merge `868d00015df767b43c273b4857f2966db4a1631a`，Windows tests SUCCESS。日志确认产品 **234 / OK / 201.452s**、浏览器 **5 / OK / 20.238s**、Push Guard **16 / OK / 67.503s**，采集 / 锁 / Ruff 同时通过。该证据只属于上述提交，当前真实模型修复尚未纳入远端检查，A1.1 待最终 head 验证后完成。

真实模型首轮共 82 次，失败原样保留。修复严格单 JSON 围栏解析，M05 冻结现有 Pydantic schema 并明确实际输入与字段归属；统一 Design 已同步，未增加模型重试、依赖或放宽结构。永久回归保护单围栏接收与说明文字 / 尾随 / 坏 JSON 拒绝，先红后绿；产品完整 **235 / OK / 99.810s**（twentyfirst-product-final.log），Hermes **6 / OK**、认知 **7 / OK**，改动文件 Ruff 通过。七组真实模型及 M06 主要来源对照正在独立数据根续接，实际语义结论另补；Desktop 与物理休眠不因本地通过而勾选。

本批最终产品完整 **235 / OK / 103.496s**（twentyfirst-product-with-expansion.log），M05 **7 / OK / 0.977s**、Hermes **6 / OK / 0.382s**、M06 **14 / OK / 2.689s**，全 src / tests Ruff 与离线锁通过。生产修改限严格单围栏入口、首次冻结的现有 M05 / M06 schema、原字段归属提示；不改协议、预算或自动重试。七组补测先用 88 次完成：M04 全部成功，M05 五组成功、两组拒绝；新反证据 / 正确依赖顺序的分组任务再分别以 9 / 5 次成功。旧失败 / 输入 / Prompt / 次数保留；一次提前冻结的补测副本另耗尽 16 次，失败原样保留。原七组来源 hash 未变；[实际语义审阅](semantic-review.md)给出定性结论，M05-R2.2 留待用户集中审阅，R2.3 仍待 Desktop。

M06 实际主要来源对照暴露 open_questions 字符串错误，7 次生成被严格拒绝；补现有 schema 后另一明确请求前八次搜索 / 提取为 HTTP 429，第九次取得主要来源，但 300 秒期限清理时已用 16 次且未结束，保留 cancelled / runtime_stopping，不发布、不交 M04 / M07。R2.3 未完成，后续先核对上游条件，不清预算或反复空转。详见 twentyfirst-real-expansion.json、twentyfirst-expansion-rate-limit.json。G2 无新事件证据；当前北京时间晚间不在物理休眠窗口，未触发休眠。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

## 执行记录与 Plan 状态

2026-10-13：创建总计划及八份模块草案，完成按 Design 八模块 / C01–C06 / P01–P09 和九项 grill 决定的覆盖核对。一次性文档检查覆盖 31 份 Markdown、367 个本地链接 / 锚点，错误为零；九份 Plan 元信息 / draft 状态、27 个任务、140 个未执行步骤及占位词检查通过。检查在忽略目录已有检查脚本上临时扩展，不新增永久文档测试。当前没有实施命令或产品验证结果；所有实施 checkbox 保持未勾选，批准记录由后续实际确认填写。

同日用户授权按主题提交实施前的当前改动。提交准备检查覆盖 52 份 Markdown、395 个本地链接 / 锚点，错误为零；全部 54 个待提交文件的凭证 / 个人会话引用扫描无发现，两个合成 JSON 可解析，九份 Plan 仍为 draft。个人原始会话仅保留本地忽略目录原件，C01 提交版改为合成场景。此授权仅覆盖本地归档，不执行产品实现或远端写入。

同日用户指令“现在开始按照plan执行”批准当前统一 Design / Prompt、总 Plan 与 M01–M08 Plan，G0 通过；在当前 `codex/4-initial-development` 开始 M01 Task 1。已记录本机 / 上游事实，PM 应用环境完成同步并通过 AIAgent 合成流式工具往返和一次 503 非流式恢复探针；开发测试环境解析失败，完整 activate 未成功。Job 父 / 子 / 孙停止及部分 Win32 提交窗口已实测；junction 反例已回写 Design。MXC 文件写边界部分通过，但所需 loopback 策略被本机 Windows 拒绝，省略该字段后实际连接仍超时；G1 未通过。替代 restricted token / Low integrity / Job 路线记录为待用户确认候选，真实模型验证也等待本机配置。详细命令、退出码和未完成范围见 [M01 执行记录](modules/01-runtime/plan.md#2026-10-13task-1-开始执行)。本次只完成 Task 1 Step 1，其余保持未勾选；未创建产品运行代码或进入后续模块。

本次同步检查覆盖 31 份 Markdown、377 个本地链接 / 锚点，错误为零；九份 Plan 均为 approved，步骤核对为 1 项完成 / 139 项待执行；`git diff --check` 退出 0。一次性 probe 保持忽略，不提交 PM 数据或合成请求日志；未新增永久文档测试，没有 Commit / Push / PR。

2026-10-14：用户批准验证 restricted token / Low integrity / Job 候选，指定 `deepseek-flash`。M01 Task 1 Step 2–4 完成：官方 PM 应用准备及导入退出 0（开发 activate 的独立测试解析失败保留）；真实模型两次流式请求 / 一次 echo 工具 / 最终 JSON 通过；16 / 17 次、Agent 与转发重启计数、普通任务与无工具筛选并发通过合成验证。替代隔离的明确用户 ACL 合成目录写 / 停树 / 网络 / 权限恢复通过，但当前 PM 底层 Python 在受限 token 下不可读，真实启动 Hermes 失败；不改被保护目录 ACL 或放宽读取契约。G1 仍未通过，Step 5–7 保持未勾选，累计 4 项完成 / 136 项待执行。下一 MXC + stdio 转发候选已写 T06，待批准验证；产品 Task 2 和后续模块尚未启动。详细退出码、反例与脱敏证据见 [M01 2026-10-14 执行记录](modules/01-runtime/plan.md#2026-10-14模型预算与替代隔离验证)。

同日用户将 OS 写隔离能力移出初版，后续独立 Issue 再实现。当前 Plan 对齐 Design 修订 1，G1 移除写隔离验收，M01 Task 1 Step 5 改为普通任务进程停止；保留模型转发 / 预算、任务副本、业务路径授权、冲突检查、提交句柄与恢复。此前隔离失败保留历史证据，不再要求批准或继续验证 MXC + stdio；后续 Issue 尚未创建。本次不承诺拒绝自由 Shell / Python 的目录外写入或恢复这些未登记改动，提交窗口与依赖组合仍需验证。

修订同步核对通过：31 份 Markdown、385 个本地链接 / 锚点无错误，Design 修订 1 / 九份已批准 Plan 一致；普通父 / 子 / 孙 Job 停止复测退出 0，M01 Task 1 Step 5 完成，累计 5 项完成 / 135 项待执行。`git diff --check` 退出 0；无新增生产依赖、永久测试或远端写入。

2026-10-15：继续执行 M01，Task 1 Step 6 / 7 完成，G1 通过当前范围；新增 `storage.py`、`windows.py`、产品元信息 / MCP 锁和永久契约组，同步 README / Python / CI 规则，离线 CI 增加产品测试而不安装 Hermes 或调用模型。Task 2 Step 1 / 2 / 6 已完成；文件扫描 / prepared → committed / 恢复主体通过，Step 3–5 保留未勾选，待运行层绑定业务范围、字段校验、处理位置和后置依赖登记。累计 10 项完成 / 130 项待执行，下一任务为 M01 Task 3；没有远端写入。

同日继续实施运行层：固定输入 / 未开始增量合并、双名额 / 查询优先、授权与 episode 提交窗口保护、持久预算、配置、P01 / 历史、直接 AIAgent 子进程、模型转发、本机 HTTP 和单例已落地。62 项标准库契约在 Python 3.13.5 / PM 3.14.7 均通过；实际产品适配完成六场景 / 41 次合成 provider 请求，含文件 / Shell 发布、503 三次计数、16 次成功 / 17 次拒绝。真实 Check / Serve / Stop 在 PM 解释器通过，venv redirector 的 PID 差异用启动关联标识解决。Task 3 Step 1 / 3–7、Task 4 Step 1 / 2 / 4 / 5 完成，累计 20 / 140 项完成；剩余业务字段、实际处理位置和最新修订依赖仍按 M03–M07 接入，Mcp / Web 动作随 M07 / M08 补齐。M01 不标 implemented，继续 M02；没有创建远端 Issue、Commit / Push / PR。

同日推进 M02：新产品采集、物理来源、同步写互斥 / 尾恢复、200ms 轻量通知、服务扫描补登记和真实来源工具往返已实现。M02 完成 12 / 16 步，累计 32 / 140 步完成；其余为 M07 实际工具名前缀、M03 提交后处理位置交接、通知到业务处理闭环及真实 Desktop。真实 AIAgent 七场景 / 43 次合成 provider 请求退出 0。G2 一次性测试插件已添加到本机 Personal marketplace 的 AVAILABLE 条目，未安装 / 启用，独立临时数据根；真实事件和 30 分钟终止时刻尚未取得。详细记录见 [M02 执行记录](modules/02-capture/plan.md#2026-10-15产品队列来源和扫描)。没有 Commit / Push / PR。

同日继续 M03 / M04：普通 episode 的单活跃 / 完整来源 / 轮次、程序评分 RPC、缓冲共同复核和发布处理位置已接通；M04 的队列来源 / 字段权限、程序 ID、名称多关系图、历史详情 / 一跳 API 和 episode 分析接入。M04 空结果也登记 M05。已提交后置登记 / 索引失败不再阻止后台恢复，轮询只补登记不重跑模型。M02 当前 14 / 16、M03 2 / 15、M04 8 / 14，累计 44 / 140 步完成；保留 G2、终止 / 不足窗口 / 纠错、外扩 / 用户提交来源、编辑入口、M05 / M07 依赖及真实语义验收。真实 AIAgent 合成链路 M03 首次 3 次生成、切换 7 次、M04 7 次，共 17 次请求退出 0；这不是实际模型语义质量证明。完整标准库 98 tests / OK，无 skip，Python 3.13.5 为 20.334s，PM 3.14.7 为 20.290s。没有 Commit / Push / PR，继续 M05。

同日继续 M05 / M07：证据 / 假设 / 定性理解的引用和字段权限、episode 分析、实际用户位置复用，以及上下文准备 / 两列表 / 有效材料周期、直接依赖刷新、只读语义查询、独立调用取消、无工具筛选和 compact 快照已实现。MCP 反馈保存请求身份与来源关联阶段，来源不唯一或缺可信请求边界则等待。M05 完成 4 / 12、M07 完成 8 / 22，全 Plan 当前 56 / 140 步完成、84 步待办；不把结构测试或合成 provider 当作真实语义验收。

完整标准库 120 tests / OK，无 skip，Python 3.13.5 与 PM 3.14.7 均退出 0。官方 MCP 2.0.0 / 协议 2025-11-25 客户端实际调用两个工具；AIAgent 准备 4 次、查询 3 次、筛选 1 次、被取消查询 1 次，共 9 次合成请求，查询不注册文件 / Shell / 外部搜索工具，compact 两次不增加生成。SDK schema 错误、未知 ID、索引未就绪、反馈幂等和运行中取消均有探针证据。

Windows SDK 关闭 stdio 会清理其进程树，MCP 内直接冷启动的后台不能保证存活，因此当前明确要求 Serve 先启动；退出 stdio 复用的独立后台保持同一实例。自动冷启动保留 Task 3 Step 1 / G2 待验，不引入 Windows 服务或计划任务绕过约束。另修复子进程协议受框架 stdout 编码影响，显式写 UTF-8；启动任务直接使用 PM 底层解释器并保留虚拟环境配置，先挂起 / 加入 Job / 恢复，分配失败杀掉挂起进程。原子重命名后的 Windows stat / fstat 差异可能触发上游 write_file 保守拒绝，实际维护探针使用原有 patch 工具，不关闭校验。

后续继续 M03 收尾 / 纠错及修订等待、M05 等待解除、M07 Hook / 入口接入和 M08；G2 真实 Desktop 尚未取得，M06 按 Task 1 Step 1 等待搜索选型，不据此停止其他独立实施。没有 Commit / Push / PR，没有启用个人会话或重新实施 OS 写隔离。

### 2026-10-15：M04 三类维护、Tavily 外扩与 Web

用户选择 Tavily，缺 key 后已核对并实测官方免费免 key Search / Extract，无需切换模型协议。G3 实际搜索返回主要来源、读取 6,692 字符，真实非法搜索请求返回 HTTP 400；限流、正文失败、晚返回和预算边界由控制层契约组保护。实际 AIAgent → 真实 Tavily → 外扩提交 → M04 维护 → 指定字段用户编辑共 11 次生成（5 + 3 + 3），完整证据退出 0。模型响应为 localhost 合成数据，真实模型定性语义质量不据此验收。

M04 已补齐 external / user_submission 来源、三类输入、指定字段与原因历史、过时输入拒绝和提交后的索引补建；失败补建不重跑模型或业务版本。M06 已实现版本依据 / 稳定循环游标、成功才推进、无新依据不重复、旧输入取消后续排、显式重试 / 重探、P05 / 逐主张引用 / 缺口 / M04 后继；模型未配置不启动周期。M08 四入口、本机会话 / CSRF、配置 / 知识编辑、游标 / 只读来源 / 历史任务版本和 Web 动作已实现；episode / cognition 纠错及等待说明尚未接入。

真实浏览器使用合成数据验证分页 / 空 / 筛选 / 未知记录、脚本标签只显示文本、实际提交与两窗口 409、迟到详情 / 配置响应不覆盖新输入、来源 / 历史版本和旧配置、键盘与 390 像素窄屏。Web 启动探针另实际启动 / 复用后台并交换一次性 token，浏览器启动回调在该探针中捕获，页面交互由内置浏览器独立验证；两种证据不混淆。未安装或启用个人采集插件。

最新验证为 **146 项产品测试 / OK / 无 skip**：Python 3.13.5 为 31.381s，PM 3.14.7 为 31.338s；旧采集验证 PASS，开发 Hook 16 项 OK，`uv lock --check --offline` 与 JS 语法检查通过。新增永久测试保护配置凭证版本、外部 / 用户来源、指定编辑 / 索引恢复、外扩覆盖 / 公平 / 引用 / 失败和 Web 安全 / 版本 / 重试；视觉与浏览器时序只保留一次性证据。

当前 checkbox：M01 20 / 25、M02 14 / 16、M03 2 / 15、M04 13 / 14、M05 4 / 12、M06 12 / 13、M07 8 / 22、M08 10 / 16，总计 **83 / 140 完成，57 待办**。模块仍不标 implemented。用户要求的未及时回复事项记入[执行待办](pending.md)，不阻止独立工作；G2、修订等待 / 解除、真实语义质量和剩余 UI / Hook 交接仍按各模块接续，未创建远端对象。

2026-10-16：继续完成明确 episode 归属纠错、原子直接依赖等待、M04 / M05 旧版防发布和当前 M05 解除；Web 独立认知纠错保留 user_submission；M07 候选须在等待解除后重新准备才恢复，compact 既定选择保留；Web 跟踪实际任务，409 / 失败和迟到响应保留输入。

模块进度为 M01 20 / 25、M02 14 / 16、M03 5 / 15、M04 13 / 14、M05 8 / 12、M06 12 / 13、M07 11 / 22、M08 15 / 16，累计 **98 / 140**。新增永久组保护来源守恒 / 同轮完整 / 程序等待字段 / 固定旧输入 / 独立提交 / 候选重新准备 / 关联历史，复用已有事务和预算测试，不为 DOM / 布局建立工程。

两个解释器全量测试各 **155 项 OK**，Python 3.13.5 为 34.324 秒，PM 3.14.7 为 34.219 秒。真实 AIAgent + 本机合成 provider 的归属纠错 → M04 → M05 为 5 / 1 / 1 次请求，独立认知纠错为 4 次，共 11 次，退出 0；同清单等待、失败保留、当前解除和独立来源通过。模型响应是合成数据，不证明语义质量。最新证据为忽略目录 correction-tests-313.txt、correction-tests-314.txt、corrections-hermes-results.json 和 web-correction-waiting.jpg。浏览器实际验证合法修订、等待 / 来源、409 保留和迟到任务回调。

G2、真实语义验收、生命周期 / 不足窗口、新材料触发旧边界修订、MCP 自动冷启动 / Hook 交付和跨模块关联视图继续待办。未 Commit / Push / PR；没有新增依赖或隔离能力。

2026-10-16 后续连续执行：新材料直接修订及按需旧原文读取 / 新引句检查、同事务等待、MCP 同源反馈、候选自身代次竞争、最新依据重分析和关联历史视图完成。M01 / M08 的模块 Plan 全部复核并标 implemented；整体保持执行中。

当前模块计数：M01 25 / 25、M02 14 / 16、M03 6 / 15、M04 13 / 14、M05 10 / 12、M06 12 / 13、M07 13 / 22、M08 16 / 16；模块合计 109 / 133。总体验收 Step 3（实际外扩到 M07）、Step 4（异常契约）和 Step 6（实际 Web）完成，累计 **112 / 140**。

两个解释器各 **160 项 OK**：Python 3.13.5 34.944 秒，PM 3.14.7 33.786 秒。旧采集、16 项 Push Guard、离线锁通过。实际 AIAgent 新材料修订链 12 请求；真实 Tavily / AIAgent 的 M06 → M04 → M07 → 编辑链 14 请求，M07 采用新知识版本且计数仍为 2，外部资料没有进入用户掌握；SDK / AIAgent 上下文链 9 请求、真实后台 Web 启动 / 一用引导 / 停止通过。

总 Step 4 的证据分别来自最新 startup / sources 的丢通知及停止重启、runtime 的撤权停树 / 后置恢复 / 旧输入 / 计数、storage 的中断恢复和同期编辑、episode 的失败不推进处理位置、corrections 的等待不提前解除、MCP / SDK 的排队与运行取消。复用已有永久组和实际 SDK 探针，不重复建立相同测试；这不替代 Desktop 的完整业务会话。Step 6 使用已保存的四入口 / 两窗口 / 原来源 / 两类纠错 / 关联历史 / 异步 / 键盘 / 窄屏浏览器证据。

7 组模型语义材料已经准备但调用 0；真实模型及 Desktop G2 / 生命周期仍待外部条件。总 Step 1 的真实 PR / CI SHA、Step 2 / 5 的 Desktop 会话和 Step 7 的整体收尾保持未完成；未擅自 Push / 创建 PR。

运行适配器的当前工具 / 读取审计探针已更新后复跑：七场景共 43 次实际 AIAgent 合成 provider 请求，工具结果无 TOOL_ERROR；筛选 1、记录查询 2、原始来源 2、文件 / Shell 发布 3、503 恢复 3、最后允许请求 16、超额尝试 16（第 17 次由产品拒绝，任务按预期 BudgetError）。旧探针的过时工具清单 / 未登记读取快照问题只修正于忽略目录，不放宽生产校验。

以上当前已验证实现准备保存为本地任务提交；源码 / 合成 fixture / 锁 / 文档 / CI 一并核对。143 个非忽略版本文件的凭证模式扫描无发现，32 份文档 / 403 个本地链接检查无错误，JS 语法及 git diff 检查通过。原始数据、私有配置、日志和探针继续排除；远端未写入，整体仍有 28 项真实集成 / 语义及 PR / CI 收尾步骤未完成。

2026-10-16 再续接：补 M03 规范事件 / 持久计时 / 固定收尾 / 不足窗口、M07 实际写出阶段及原版本恢复。两个解释器各 168 项产品契约通过；真实 AIAgent 两条收尾 → M04 → M05 合计 19 请求通过（localhost 合成模型，未证明语义）。新增 5 个 checkbox，累计 117/140。Desktop 适配与语义仍待实测，未 Push。
