---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M08：复用现有页面与框架路由 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、复用与文件

依据[统一 Design M08](../../design.md#local-web-console)、[C06](../../design.md#closing-contracts)与[总 Plan](../../plan.md)。沿现有配置、episode、知识 / 关系、处理历史四入口；本轮迁移 API 承载方式并复验交互，不重做 UI。

Modify：`src/distillai/server.py` 的 Web 路由和授权依赖，`startup.py` / 启动脚本的 Web 入口；`src/distillai/web/index.html`、`app.js`、`styles.css` 仅在新 API 接入需要时修改。复用 `tests/test_product_web.py`。配置 / 内容 / 归属 / 认知写入仍各交 M01 / M04 / M03 / M05，不另建 Web 保存逻辑。

Playwright 增补：Create `tests/browser/test_web.py`、`tests/browser/serve_fixture.py`；browser 依赖组 / 锁和 CI 安装由 M01-R3 统一维护。真实浏览器测试补充 API 测试无法执行的 JS 行为，不替换原 HTTP 契约组。

## M08-R1：框架响应与已有业务 API

- [x] **R1.1 复用现有会话与框架 HTTP 能力。** 用 Starlette Request.cookies / Response.set_cookie / delete_cookie 替换手拼 Cookie 解析 / header，TrustedHostMiddleware 承担匹配的 Host 基础检查，继续显式限定实际 loopback 端口。保留一次性引导、服务端 opaque session、HttpOnly / SameSite、303 清 URL；Origin / CSRF 和静态资源授权沿 M01 依赖，不用 CORS / SessionMiddleware 替代。后台 bearer、模型 / 搜索 key 不进 HTML / URL / 浏览器持久缓存或历史。使用 FileResponse / StaticFiles 时，挂载路径不得绕过授权或开放任意文件。
- [x] **R1.2 保持读取契约。** 原列表 cursor / limit 20（最大 100）、稳定排序 / 绑定筛选、详情历史版本、只读来源、关联历史继续调用原 Python 方法。原文用 textContent / value；历史 context / expansion / selection 读取实际不可变版本，文本偶然含 ID 不作关联。索引未就绪 / 不存在 / 无匹配 / 服务错误分开显示。
- [x] **R1.3 保持写入契约。** 配置 PUT 返回保存 / 生效版本，密钥已配置 / 空输入 / 显式清除区分；知识 edits 带 expected_version / changes / reason，episode / cognition corrections 复用任务入口。202 表示登记，成功任务才显示提交；409 / 验证失败保留输入，原失败任务和次数不因“按最新依据分析”被覆盖。
- [x] **R1.4 用 FastAPI TestClient 复跑 API 组。** 直接 `from fastapi.testclient import TestClient`，以 `with TestClient(app)` 创建真实 app 的测试入口；临时 Store / Runtime 用 app.dependency_overrides 注入并在结束清空，不自建监听端口 / 请求客户端 / 服务线程。其余授权、CSRF、版本、分页、路径越界、历史和失败不改数据断言继续使用；出站上游才用 HTTPX MockTransport。保留独立真实 socket / 浏览器验收；M08-R3 不复制这套 API 断言，不为了类名变化改业务期望。SQLite 接入后 Web 仍经原业务 API 读取任务 / 配置，不能绕过授权直接打开数据库或回读旧任务 JSON。
- [x] **R1.5 复用游标签名。** `_page` 使用 ItsDangerous URLSafeSerializer 替换手写 Base64 / HMAC 组合，独立 salt 绑定游标用途，加载后继续校验 collection / filters / after。保留现有篡改、跨筛选 / 集合和正常分页用例；客户端只存 opaque cursor，重构启停清理旧运行时游标 / 会话，不改持久记录。签名只防篡改，不把明文载荷当加密，不放入凭证。

## M08-R2：真实浏览器复验

- [ ] **R2.1 四入口与来源。** 用合成数据打开四入口、空列表、筛选 / 分页、未知项重试、原来源和历史版本、关联外扩 / 子图 / 两列表 / 已选素材。确认等待状态附当前依据版本，不把旧内容当最新，未知不写成不懂。
- [ ] **R2.2 编辑 / 任务 / 冲突。** 两窗口改同记录产生成功 / 409；episode 归属和认知纠错观察真实任务阶段；失败 / 冲突保留正文 / 原因，当前依据重分析沿原链解除等待。普通 UI 数据检查可用合成维护回调，真实模型语义与执行另记，不能混称。
- [ ] **R2.3 异步和可访问性。** 延迟旧详情 / 保存 / 任务响应再切页面 / 继续编辑，确认代次保护仍保留新内容。检查脚本标签只作为文本、Tab / Shift-Tab / label / 焦点 / 错误状态、窄屏无溢出；只修可复现问题，不为换后台引入视觉工程。
- [x] **R2.4 同步实际使用说明。** 写产品项目解释器的 Web 启动、会话失效 / 重开、任务登记 / 完成区别、冲突处理和实际证据位置。旧 M08 implemented 只表示旧服务版本已验，新框架接入不得自动继承。

## M08-R3：Playwright 浏览器行为回归

- [x] **R3.1 建立独立合成浏览器 fixture。** `tests/browser/serve_fixture.py` 复用产品 app 工厂 / Uvicorn，在 loopback 绑定端口 0 并返回实际地址，使用临时数据根、SQLite Store 和合成维护回调；不能导入 / 启动 Hermes、连接真实模型或读取个人数据。`test_web.py` 用 unittest + Playwright Python 同步 API 管理 Chromium、fixture 子进程和独立 browser context；每例经真实一次性引导换 Cookie，不跳过产品授权。等待公开就绪信号，失败 / 超时用 finally 停进程和浏览器，不留后台。浏览器安装缺失明确报错，不能以 skip 当通过；只装 Chromium，不引入 pytest / Node 前端工程。
- [x] **R3.2 保护表单与冲突。** 两个独立页面读取相同版本，先保存一份，再保存另一份触发真实 409；断言后者输入 / 原因仍在、提示冲突且已提交内容未被覆盖。另通过 Playwright network routing 制造保存失败，检查输入保留、重试可用；状态码完整矩阵仍由 TestClient 负责，不在浏览器重复。现有 HTTP 组无法验证浏览器控件是否丢字，故这组保留为永久测试。
- [x] **R3.3 保护迟到响应与安全渲染。** 用 Playwright 的请求拦截 / fulfill 控制详情或保存响应先后顺序，不使用固定 sleep；延迟旧详情后切换记录，旧响应到达也不能覆盖当前记录；保存期间继续编辑，旧保存结果不能清掉新输入。合成正文包含脚本 / HTML 片段时，断言按文字显示且无脚本副作用。按角色 / label 等可访问定位器操作，不固定 DOM helper、CSS 类或当前菜单数量；这些 JS 层行为不由 API 单测覆盖。
- [x] **R3.4 接入检查和证据。** 原 Windows CI job 安装锁定 browser 组与 Chromium，运行独立浏览器命令；合成 fixture 不需 Hermes 或 secret。失败只保存合成页面 screenshot 到 .artifacts，默认关闭含网络头 / Cookie 的 trace 与 HAR，不输出引导令牌。键盘、窄屏及布局沿 R2 人工审阅，运行记录分别标 API / 浏览器自动化 / 实际 Desktop，不把 Playwright 通过当 Codex 集成通过。

## 验证与测试取舍

```powershell
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_web.py' -v
uv run --locked --group browser python -m playwright install chromium
uv run --locked --group browser python -m unittest discover -s tests/browser -p 'test_*.py' -v
```

Chromium 安装是联网准备，安装后测试仅用合成 loopback 服务，预期两组各 `OK`；再记录实际浏览器检查与关键合成截图。API 永久组保护会话 / CSRF、版本、公开结果和数据完整性；Playwright 永久组补 JS 表单留输入、迟到响应和文本安全。布局、当前入口数量、DOM helper 名与发行截图仍是一次性验证，不写视觉像素基线。依赖 M01 新服务 / SQLite 与 M03–M07 的现有业务入口；不新增前端框架、第二个业务后台或模型代理。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第二批：原生框架、真实 stdio 与浏览器回归

新增 tests/browser 的真实 run_service / FastAPI / Uvicorn / SQLite 合成 fixture；每页通过一次性引导换 Cookie，不导入 Hermes或读取个人材料。Chromium 五项永久 JS 回归通过：独立会话成功 / 409 留正文与原因、保存失败后可重试、迟到旧详情不覆盖当前记录、提交中输入在成功回调 / 重新读取后保留、HTML / script 按文字显示。拦截控制响应次序，不用固定 sleep；失败截图只含合成页面，不开启 trace / HAR。API / Web 现有 TestClient 组通过，Windows CI 已接入锁 / Chromium / Ruff 和独立浏览器命令，README 已同步。键盘 / 窄屏 / 全入口与 Desktop 仍需各自验收。

完整证据、收尾测试结果与范围见[总 Plan](../../plan.md)第二批执行记录；本地通过不代替 GitHub CI，未迁移真实数据或执行远端写入。

## 2026-10-17 第五批：HTTP 与 MCP 请求模型

关联 HTTP 写路由接入领域 Pydantic 模型，保留 Host / Origin / CSRF、先认证再有界读 body 与原 409 / 422 错误结构；配置字段路径由原 Config.update 返回。新增无副作用 / 正文不回显回归，完整产品 193 项、浏览器 5 项与最后 Web 10 / HTTP 7 项通过。无 UI 或公开有效载荷改动。见[总 Plan](../../plan.md)第五批。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

### 2026-10-15：四入口、本机会话与实际浏览器验证

使用 minimalist-ui，按已批准四入口形成原生 HTML / CSS / JS：左侧导航、筛选 / 列表和详情 / 编辑；暖灰底、细边界、无外部字体或资源。窄屏上下排列，保留 label、焦点和状态。所有原文通过 textContent / value 显示，固定三个静态路由、同源 CSP / 禁止内联执行 / frame、无任意路径读取。业务写入复用控制层，未建立第二套保存逻辑或前端工程。

一次性 120 秒引导 token 只能交换一次，303 清除 URL，Cookie HttpOnly / SameSite；浏览器写入校验 Origin / Host / CSRF。后台 bearer 不进入 URL / HTML。实际启动探针完成独立后台启动、Web 回调、一用交换、受保护 HTML 和停止；浏览器启动函数在该探针中捕获，真实页面操作另通过 Codex 内置浏览器进行。

已提供知识 / 关系 / episode / 假设 / 外扩列表与固定版本详情、只读来源、绑定筛选的游标、任务历史和选定任务的不可变输入 / 输出 / Prompt / 生成请求。配置保存显示新版本和运行任务的旧配置版本，密钥只显示状态，支持私有 key 的显式清除；检测环境凭证只返回布尔值。知识编辑提交指定 changes / 版本 / 原因，202 只显示登记，成功任务才显示已提交；失败和 409 保留输入。任务历史可显式重试已停止失败任务，保留原次数和配置版本。

合成真实浏览器证据：20 → 23 条分页；四入口、空列表 / 准确名称 Enter 筛选 / 未知记录重试；知识名称、正文与原来源中的脚本标签均无 script 元素；两窗口分别真实提交和 409、冲突正文 / 原因保留；旧详情延迟 3 秒后未覆盖新记录 / 输入，配置 PUT 延迟 3 秒期间输入 11 → 10，返回仍保留 10 并显示待保存；历史显示当时配置 v1 而当前为 v3；完整 SHA 读取旧记录且无编辑表单；Tab / Shift-Tab 顺序正常，390 像素窄屏无横向溢出。忽略证据为 web-overview.jpg、web-conflict.jpg、web-narrow.jpg 及一次性探针。浏览器维护执行器为合成回调；实际 AIAgent 维护另由 M06 的 11 请求探针验证。

永久 Web 组 8 项保护真实授权 / CSRF / 版本 / 分页 / 历史 / 路径及重试预算，不为布局或 DOM 名称引入测试框架。Task 1 Step 1 / 2 / 5、Task 2 Step 1–3、Task 3 Step 1 / 4–6 完成，当前 **10 / 16**。episode / 认知纠错与等待说明、跨模块关联视图、延迟任务回调的完整交互仍待接续，未勾选剩余步骤；见[执行待办](../../pending.md)。

### 2026-10-16：归属 / 认知纠错、等待与迟到任务反馈

复用 M03 / M05 的两个纠错入口。交流详情载入另一个同会话片段并显示版本，使用可读来源行范围与原因提交完整新归属；知识 / 关系详情可填写表现、帮助条件及原因，独立认知来源不伪造 episode。旧版本仍只读。等待标记附版本与原因，原来源可只读回查；202 和最终成功分开显示，错误 / 409 保留输入，路由代次和输入代次保护迟到回调。关联历史按 record_id 也能找到尚未产出结果的编辑任务。

真实浏览器合成数据验证：来源重叠拒绝且原因保留；合法归属修订实际提交并更新行范围；切换页面不被旧任务回调覆盖；M05 失败后旧判断明确等待；认知纠错实际提交，提交期间的新输入保留，再次用旧版本提交得到 409；来源对话框显示原始 user 文本。浏览器使用合成维护回调，真实 AIAgent 两类纠错另经 11 请求探针。截图 web-correction-waiting.jpg 保留在忽略目录。修复来源枚举将含 connector 的整条 episode 误作 SourceRef、显示 undefined 行号的问题，按实际行范围识别来源。

Web API 组 9 项通过。Task 1 Step 3 / 4、Task 2 Step 4、Task 3 Step 2 / 3 完成，当前 15 / 16；Task 2 Step 5 的跨模块外扩 / 子图 / 筛选关联视图尚待补齐，不能把当前历史详情当作该步骤全部完成。

### 2026-10-16：关联历史视图收尾

新增只读关联回查：从 episode / 知识 / 关系详情查看实际 M04 结果、外扩、子图 / MCP 背景 / 候选及选材版本。历史 committed context_ref / expansion_refs 从不可变版本读取；当前记录变化不冒充当时内容，文本中偶然出现 ID 不算关联。选材保存固定 episode_ref，旧记录无明确 episode 关联时不猜测。游标绑定目标与筛选，已登录会话和 ID 校验沿原接口。

真实浏览器已打开关联外扩历史版本、展开当时子图和选材，选材准备与实际 Hook 输出明确区分。显式最新依据分析从等待状态登记新任务，原失败任务保留，M04 / M05 成功后显示“当前依据已完成重新分析”。截图 web-reanalysis-ready.jpg，浏览器维护回调为合成数据；模型链另有实际 AIAgent / 真实 Tavily 探针。

Task 2 Step 5 完成，16 / 16；本模块 Plan 改为 implemented，整体 Desktop 和模型语义验收仍未完成。
