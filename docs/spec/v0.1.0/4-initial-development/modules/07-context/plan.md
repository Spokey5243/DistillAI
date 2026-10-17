---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M07：复用 FastMCP、上下文与 Desktop 交付 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、现状与文件

依据[统一 Design M07](../../design.md#context-retrieval)、[C04 / C05](../../design.md#closing-contracts)与[总 Plan](../../plan.md)。MCP 高层采用独立 FastMCP 包，复用 context、筛选快照与来源关联，补新执行 / 框架接入、真实冷启动和 Hook 交付。Modify：`src/distillai/mcp.py`、`context.py`、`startup.py`、产品 dispatcher / hooks / MCP 配置 / Skill 和 P06–P09 文本的实际字段；复用 `tests/test_product_context.py`、`test_product_mcp.py`、`test_product_feedback.py`。候选版本 / 底层 SDK 兼容关系见总 Plan，不混用旧 SDK 同名 FastMCP。

## M07-R1：FastMCP 和一个常驻后台

- [x] **R1.1 用 FastMCP 的高层工具。** `from fastmcp import FastMCP`，以 `@server.tool` 和现有 Pydantic 参数 / 返回类型登记 query_context / submit_feedback，严格输入校验、schema、结构化结果、标准工具错误和 stdio 会话由库承担，不另写 JSON-RPC / tool schema 管理器。只暴露这两个工具，不用 from_fastapi 自动公开整个管理 API；继续 stdio，不为换库增加 MCP HTTP 服务。底层 mcp.server.MCPServer 生产入口替换后删除，不双轨维护。
- [x] **R1.1a 复用依赖与异步生命周期。** 用 FastMCP 原有 lifespan / dependencies 管理 HTTPX AsyncClient，连接同一常驻后台，删除同步请求套 asyncio.to_thread；取消清理使用库的取消上下文和 AnyIO shield，只向同 invocation 发 cancel。MCP stdout 只协议，Loguru 诊断到文件 / stderr；产品项目解释器启动，不往 PM 装 FastMCP。框架取消工具不代表父进程里的业务任务已停，仍等 Runtime / Job 确认。
- [ ] **R1.2 闭合冷启动。** 与 M01 共用已有启动锁 / 实例身份检查，在真实 Desktop SessionStart / MCP 生命周期中测试后台不存在时的启动和等待。Windows breakaway 被限制时保留明确错误和先 Serve 的事实；不增加系统服务 / 计划任务 / 父进程伪装。真实冷启动和 stdio 退出后后台存活都取得证据才完成此项。
- [ ] **R1.3 查询和取消复用业务契约。** 明确 ID / 名称复用 M04，不调用模型；自然语言沿现有只读 AIAgent，先子图 / 两列表后全图。实际读取审计经 M01 通道调用原函数，结果只能引用已读固定版本；不开 Shell / 编辑 / 外部搜索。普通名额排队，不抢占运行维护；每次工具调用内部 UUID 绑定唯一取消，只停对应任务树，停完才回收名额。SDK 取消 / 平台超时 / 无匹配分别返回。
- [ ] **R1.4 用 FastMCP Client 测试。** 复用 `async with fastmcp.Client(server)` 的内存连接，list_tools / call_tool 验两工具 schema、严格参数、返回字段、错误、反馈幂等和取消绑定；不自写 session / stdio 收发 fixture。传输组另用 FastMCP 的 PythonStdioTransport 与实际子进程测连接 / 退出 / 取消，记录与 Codex Desktop 的实际工具全名和行为。底层官方 SDK 客户端只保留必要互操作检查，内存测试不能代替真实 stdio / G2。

## M07-R2：准备、筛选与 compact

- [x] **R2.1 复跑准备和候选规则。** 开放首次更新必准备，后每 3 次有效新增材料更新准备；M04 / M05 直接依赖变化立即合并待办、不加材料计数。候选稳定 ID / revision，只有名称连接进图，正文沿 refs；等待重分析 / 版本失效先排除，当前 M05 + 新 M07 完成后才恢复新选材。
- [x] **R2.2 复跑直连筛选。** P07 只取固定已有列表 / 当前问题 / 必要背景，无工具、独立执行名额；返回 0–3 个合法唯一 ID，提交前逐项核对候选 revision / 正文 / 条件 / refs。变化只排除该条，不临时检索或新造候选。未准备 / 无候选空返回不调用模型。
- [ ] **R2.3 完成真实 Hook 输出。** UserPromptSubmit 先登记 M03 开始再等待筛选，实际用 P09-B / additionalContext 输出；失败脱敏诊断后继续原问题，不把纯采集 `{}` 分支套到交付分支。记录写出失败、新轮迟到结果和无候选，不伪造平台确认。
- [ ] **R2.4 验证两次 compact。** SessionStart 根据真实 startup / resume / clear / compact 字段恢复原关联；compact 读取本轮已保存且确已写出的素材文字 / 版本，最多三条，不重筛、不计新生成、不因普通重复抑制跳过，不新建 episode。平台是否实际进入上下文、助手采用和用户表现分开记录。

## M07-R3：来源反馈与工具说明

- [x] **R3.1 复跑来源关联。** 相同 client_request_id 同内容复用、改内容拒绝；缺原文先待关联，Stop 后按角色 / 请求边界 / 唯一位置匹配；歧义不靠同字符串硬合并，不伪造 user_submission。取得真实 source_refs 后同源观察交 M05 复用，跨来源文本相同保持独立。
- [ ] **R3.2 实测插件配置与提示。** 固定真实命令解释器、PLUGIN_ROOT、MCP 注册全名和 Hook 返回结构；P08 / P09 使用实际工具名，M02 自身 MCP 排除同步。Skill 不每轮强制查询 / 出题，不引入 MCP prompt 资源，不指望 `${config.xxx}` 自动替换。
- [ ] **R3.3 验证自然交互。** 在实际 Desktop 查询 ID / 自然语言、取消一项并保留其他任务、MCP 早到后关联、素材可跳过、用户新表现回到 M05。记录 P06 排序 / 查询资料与 P07 条件判断的人工审阅，原任务仍可继续；工具成功不等于用户理解。

## 验证、测试必要性与依赖

```powershell
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_context.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_mcp.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_feedback.py' -v
```

预期各 `OK`；FastMCP 内存 Client、真实 stdio 传输和 Desktop G2 分别记录。永久测试复用来源身份、候选版本、compact 字节快照和取消所有权，不增加仅检查 private helper 的测试。测试仍可用 unittest.IsolatedAsyncioTestCase，不因换库重写所有测试 runner。真实工具名、平台事件、冷启动和 Prompt 语义是一轮实测证据。依赖 M01–M05；M06 外扩结果可后接，不阻塞首次查询。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第二批：原生框架、真实 stdio 与浏览器回归

原生 FastMCP 4.1.0 仅登记两个工具，严格参数与共享引用模型生成 schema；HTTPX AsyncClient 用原生 lifespan，取消经 AnyIO shield 请求原 invocation。内存 Client 四项通过；实际 PythonStdioTransport 独立进程验证列表、ID 查询、严格拒绝、反馈幂等和 stdio 退出后后台存活，零模型请求。该探针发现查询路由方法被同名属性遮蔽，补 HTTP 断言复现后修复。原上下文 / 筛选 / 反馈组及实际新 SDK 筛选 / 查询 / 来源探针通过，真实 Desktop、冷启动、stdio 取消和 Hook / compact 未勾完。证据见 .artifacts/fastmcp-stdio-results.json、direct-hermes-results.json。

完整证据、收尾测试结果与范围见[总 Plan](../../plan.md)第二批执行记录；本地通过不代替 GitHub CI，未迁移真实数据或执行远端写入。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

上下文、名称子图、MCP 摘要、注入候选、查询结果与筛选结果接入严格模型，候选 ID 工具 schema 由本模块定义生成。实际版本 / 候选修订 / 重分析依赖和程序准备前后相等判断继续保留。完整产品 192 项及真实 Tavily→知识→M07 3 次准备的实际 PM 链路通过，工具 / HTTP 请求清点继续；Desktop 工具全名、冷启动、compact 交付与语义仍未全验。见[总 Plan](../../plan.md)。

## 2026-10-17 第五批：HTTP 与 MCP 请求模型

HTTP 查询 / 反馈与 FastMCP 原生签名共用 SessionKey、RequestText、RecordRef / QueueRef。空白 query、非法会话、外部网页冒充用户表现来源及未知字段在协议层拒绝，不到后端；实际 stdio 的工具、精确查询、反馈幂等与后台独立存活通过，零模型调用。后台版本 / 事实归属规则保持，Desktop 交付验收仍待 G2。见[总 Plan](../../plan.md)第五批。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

## 2026-10-15：准备、只读查询、筛选与 SDK 桥接

已实现 context.py、mcp.py、P06 / P07 和 P09-C / D 工具描述。上下文保存 episode / 准备引用、只含名称和连接的子图、MCP 背景列表和注入候选；新候选 ID 程序分配，实质文字 / 条件 / 记录版本变化递增 revision，排序不重建身份。首次成功保存准备，随后每新增 3 次有效 episode 更新准备；仅缓冲不计开放 episode 更新，新 episode 重置。尚未执行的准备合并并保留触发别名，运行输入固定；直接依赖修改立即登记，材料计数不变。

明确 ID / 名称查询复用 M04；自然语言查询固定当前上下文、名称地图、记录 / 来源版本及已知引用。Hermes 初始 query 载荷不提供详情缓存正文，只有 query_records / read_source；工具返回前通过任务 token 登记实际读取版本，程序拒绝未读记录、虚构摘要及来源，并按实际版本组装正文。查询无业务发布范围。每次 MCP 调用独立内部 UUID，同调用重复登记复用；取消先保存该 UUID 的取消状态，登记回复尚未到达也不会留下可运行孤儿任务。

筛选只用 P07 和固定列表，独立名额且不开放工具；最多三条，未知 / 重复 / 超额 / 依赖已变条目过滤。程序保存本轮候选实际文字、引用及 Prompt 版本；两次 compact 恢复原快照，不新调用模型。Hook 实际输出阶段、P09-B 包装、筛选失败继续回答及真实 Desktop 交付仍未完成，不能把程序恢复当作平台注入证明。

反馈持久化 client_request_id / 请求内容，重复 ID 改内容拒绝。显式原始引用必须含本 session 的真实用户表达；缺引用时仅在已记录的 UserPromptSubmit 边界内核对唯一用户原文与唯一 episode 归属，歧义继续等待。record_request 已有程序边界入口，但生产 Hook 尚未接入，缺可信边界时不会仅凭相同字符串自动关联。已关联请求登记 M05，尚未完成实际 Desktop 的 Hook / MCP 同源维护验收。

官方 MCP 2.0.0 / 协议 2025-11-25 客户端已实测两个工具 schema、直接 / 语义查询、参数错误、索引未就绪、反馈幂等与运行中查询取消。AIAgent 准备、查询、无工具筛选与取消合计 9 次本机合成 provider 请求；compact 两次不增加生成。stdio 退出后，预先启动的后台保持同一实例。

发现当前 Windows SDK 客户端会清理 stdio 进程树，直接从 MCP 冷启动的后台也会被带走。因此当前 MCP 明确返回 backend_not_started，要求先通过 scripts/start.ps1 的 Serve 入口启动；Mcp 动作选择已配置 PM 解释器。Task 3 Step 1 的自动启动和 Task 4 接入继续待验，未引入服务 / 计划任务 / 父进程伪装来规避客户端约束。当前完成 8 / 22 步。

### 2026-10-16：重分析依赖、候选恢复与查询说明

直接 / 语义查询按实际读取版本返回正文，工具快照保留当时 reanalysis，响应补充当前依赖状态；旧查询重新读取也能看到当前等待。候选由程序填 reanalysis_versions。waiting 时不进入新筛选；M05 成功解除后，旧候选仍不能复活，须由 M07 完成新准备、更新依赖版本及 candidate revision。已选快照在等待期间仍可 compact 恢复。未沿图传播失效。

M05 的实际内容或等待解除可触发直接依赖的开放会话准备，材料计数不变。上下文组 8 项、纠错组 7 项通过，包含真实 prepare / selection / compact 生命周期、等待清除后继续排除旧候选以及无内容变更的刷新登记。Task 1 Step 4 / 5、Task 3 Step 2 完成，当前 11 / 22；P06 排序语义、真实 Hook / MCP 冷启动和 Desktop 继续待验。

### 2026-10-16：候选代次竞争和反馈接续

修复筛选期间候选本身变更而知识版本未变时仍可能交付旧候选的问题：提交筛选前逐项核对当前候选 ID / revision / 文字 / 条件 / refs / 重分析版本，只移除过时项，其他候选可正常留下。永久用例验证两候选一条更新、保留另一条，以及 compact 两次恢复原选择。

反馈在采集前等待、唯一可信用户原文关联、同 ID 幂等和同位置观察复用已完整串到 M05，字段及等待状态发布范围一致。当前官方 SDK / AIAgent 9 请求探针复跑通过，真实运行中查询取消及 stdio 退出保留预先启动后台成立；冷启动仍返回明确未启动。Task 2 Step 6、Task 3 Step 5 完成，累计 13 / 22。真实 Hook 输出阶段 / 时序 / 工具前缀和 Desktop 接入继续待 G2。

### 2026-10-16：输出阶段与原版本恢复核心

选材另存实际用户问题字节版本；write_selection 只在 writer 成功后登记 additional_context_written，不制造平台确认 / 助手采用 / 用户表现。写出失败只保留错误码，compact 不带未成功写出的素材；成功后固定实际发出条目、P07 / P09-B / 问题版本及输出内容版本，原记录变更仍可恢复同轮历史选择，新轮开始禁止旧轮迟到输出。现有上下文契约扩展覆盖失败、两次恢复、过时素材及新轮边界。P08 Skill 和 P09-A/B 按批准文本落盘，插件实际注册 / 工具全名 / Hook 包装字段仍待 G2，Task 4 Step 1 不据此勾选。当前 14/22。
