---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M06：复用 Hermes Tavily 与既有外扩业务 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、复用与文件

依据[统一 Design M06](../../design.md#knowledge-expansion)、[T07](../../design.md#technical-selection)与[总 Plan](../../plan.md)。Tavily 已选，不重开供应商选型；复用 Hermes 已有 Search / Extract 请求和结果处理，产品仅维护覆盖、逐主张来源和下游知识。

Modify：`src/distillai/runtime.py`、`web/app.js`、`src/distillai/expansion.py`、`tools.py`、`hermes.py` 及搜索私有配置交付；测试复用 `tests/test_product_expansion.py`。不新增搜索网关、多供应商接口、网页清洗器或浏览器工程。

## M06-R1：删除重复 HTTP 请求实现

- [x] **R1.1 固定上游调用边界。** 按总 Plan 的 Hermes SHA 核对 `plugins/web/tavily/provider.py` 的 `TavilyWebSearchProvider.search/extract`、`_tavily_request` 和 `_normalize_tavily_*`。明确公开 provider 读取环境 / 配置，私有请求函数可传 `api_key`；不得把它们当稳定公共 SDK。
- [x] **R1.2 复用完整请求路径。** 在已有 PM 任务进程使用固定 Tavily 实现：优先 provider 方法且每任务配置隔离；若其隐式环境读取会突破固定配置，调用同文件接受显式 key 的窄请求 / 归一化函数，仍不复制 HTTP 代码。固定官方 endpoint，清掉继承的 `TAVILY_BASE_URL` 和个人配置入口；私有连接参数不进入模型载荷 / 日志。删除产品 `tavily_request` 中的 urllib、headers、payload HTTP 编解码和重复结果适配。
- [x] **R1.3 保留程序来源身份。** `web_search` / `fetch_page` 仍只登记给 M06，框架注册与 untrusted 包装复用上游能力。搜索结果只作为候选；实际提取正文 / URL / 读取时间经 M01 管道交父进程确认、保存不可变 external 来源、返回产品 SourceRef。取消 / 过时任务的晚结果不得发布。搜索密钥进入当前任务进程是总 Plan 待批准边界，不能仍声称父进程独占。
- [x] **R1.4 验证新组合。** 私有配置 key 优先于固定启动环境；空 key 使用已选 keyless，显式清除 / 空脱敏语义沿现有配置。用实际 Search / Extract 查一项主要来源，记录实际 URL / 文本 / 截断 / 时间；限流 / 权限 / 读取失败保留明确错误，不退回其他供应商、不用摘要冒充全文。验证搜索本身不计模型生成，后续推理仍计。

## M06-R2：复用覆盖进度与逐主张核查

- [x] **R2.1 复用定时触发并复跑公平性。** 3600 秒的周期唤醒由 M01 的 APScheduler IntervalTrigger 执行，配置更新重排下一次等待，重启从持久外扩状态重建 / 检查已到期项，不自建周期线程；回调仍用原 tick 判断是否能登记业务任务。每批最多 10 个已有知识点为可配置初值，新批次生效不清覆盖；稳定 ID 循环让历史节点仍轮到。无新依据 / 变化 / 用户请求不反复探索，失败不推进；retry 留原次数，重探用已有 client_request_id / 独立提交来源。
- [x] **R2.2 复跑主张与下游。** expansions 保留 claims / proposed_connections / open_questions，各项引用本次确已读取来源；supported / conflicting 不可借整体摘要跨项背书。未核查保留缺口，第 16 次完成可发布，仍要第 17 次失败不发布 / 不交 M04。成功版本沿原入口交 M04、图与 M07，外部结果不登记用户掌握分析。
- [ ] **R2.3 真实模型审阅。** 使用 a / b / 候选 e：只有 e-a 原文支持时 e-b 明确保留未核查；比较双端连接、单端 c / d 和必要先备的定性理由。保存主要来源、实际模型判断 / 版本及 M04 → M07 结果，不以搜索排序 / 节点度数作价值规则。

## 验证、测试必要性与依赖

```powershell
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_expansion.py' -v
```

预期 `OK`，离线组不访问真实网络。复用原覆盖、版本、密钥脱敏、失败不发布用例；仅补上游结果错配 / 晚回复等尚未覆盖的长期失败路径。供应商 keyless、当前公开网页和模型定性质量为一次性实测，写 G3 新记录。依赖 M01 直连 / 通道 / 私有配置边界与 M04 / M05 既有数据；旧自写请求通过不能证明本次复用通过。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第二批：原生框架、真实 stdio 与浏览器回归

固定 Hermes 请求 / 归一化函数由 PM 任务进程显式传入固定 key，删除父进程重复 Tavily 请求；HTTPX 窄适配固定官方 endpoint、不重定向并限制实际响应尺寸。父进程只确认有效任务、版本化来源、逐主张引用和覆盖。实际 AIAgent + 真实 keyless Search / Extract → M04 → M07 → 用户编辑，14 次合成模型请求通过；不可变来源、缺口、材料计数和外部不算掌握均保留。证据 direct-expansion-results.json / direct-expansion-probe.log 位于忽略的 .artifacts。真实模型语义与完整私有 key 路径不冒充已验。

完整证据、收尾测试结果与范围见[总 Plan](../../plan.md)第二批执行记录；本地通过不代替 GitHub CI，未迁移真实数据或执行远端写入。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

搜索 / 网页参数 schema 从本模块严格模型生成；扩展记录、声明 / 连接 / 开放问题和结果结构由 TypeAdapter 验证，实际已读证据、输入版本、连接端点与部分保留仍为业务检查。真实 Tavily keyless + 实际 PM AIAgent 扩展 / M04 / M07 / 用户编辑 5 / 3 / 3 / 3 次成功，192 项完整产品通过；模型响应合成，语义未验。见[总 Plan](../../plan.md)。

## 2026-10-17 第五批：HTTP 与 MCP 请求模型

显式扩展请求由本模块严格 RequestArgs 校验，继续核对不同知识 ID、实际版本、配置批量限制和来源身份。实际 PM + 真实 Tavily keyless 的扩展 / M04 / M07 / 用户编辑 5 / 3 / 3 / 3 次在新来源结构校验下复跑通过。见[总 Plan](../../plan.md)第五批。

## 2026-10-18 第十二批：覆盖持久结构

覆盖状态读取采用严格模型，复用 Identifier / Version，时间值拒绝 bool / 非有限数，保留可空时间 / 任务和既有 cursor。坏记录不推进等待或改写覆盖文件，不登记额外任务；原周期 / 公平 / 成功才覆盖规则继续通过。实际 Tavily keyless → M04 → M07 / 用户编辑合成链 14 次生成通过，详见[总 Plan](../../plan.md)第十二批，不充当真实模型语义验收。

## 2026-10-18 第十六批：实际调度与在途停机待决

实际 AsyncIOScheduler / service_lifespan / SQLite 合成探针验证默认 3600 秒、配置改为 1 秒后下一次等待重排；初批 10 个、随后配置批次 1 个不清已有覆盖。失败后两个实际调度事件不重复创建或推进覆盖；显式 retry 保留原输入与已用 1 次许可后完成。空闲关闭并重开 Store / Config / Runtime，持久已到期项继续，从覆盖 12 到 13；旧任务输入 / 次数保持，无变化再经两个实际事件不重复探索。使用合成执行回调，真实模型请求 0，不作模型语义证据。

另单独复现：周期任务在途停止后为 cancelled / runtime_stopping，已用次数保留；重启 tick 仍指向该终态 pending，retry 又拒绝 cancelled，因此该周期待办无法继续。初版调度探针曾混入此在途场景而失败，后用公开 scheduler.pause 隔离空闲重启，并独立复现问题。恢复策略需要用户决定，具体问题、影响与可继续工作见[待办](../../pending.md)。不擅自清 pending、重建任务或放开取消重试，R2.1 保持未完成；R1.4 / R2.2 仍可独立续接。完整产品 230 tests / OK，详细证据见[总 Plan](../../plan.md)第十六批。

## 2026-10-18 第十七批：搜索交付与逐项发布验收

固定 PM / Hermes 的实际 TaskPipe 首帧验证五种合成凭证条件：私有 key 优先、空脱敏输入保留、显式清除后固定启动环境回退、两者为空时 keyless、任务登记后私有配置变化仍取原版本。实际子进程环境不含继承 Tavily key / base override，任务 inputs 不含密钥；在 SDK 初始化前截获并停止，模型请求 0。另验证 16,000 字符截断、URL / read_at 和不可变正文一致。

固定上游 _tavily_request / 归一化与产品 HTTPX 窄适配在实际 PM 环境通过 27 次 MockTransport 请求：keyed / keyless headers，401 / 403、402 / 429 / 432 / 433、500 / 302、超时、超尺寸、坏结构与 Extract 失败；错误不带原响应 / 私有 canary，不降级供应商，非固定 endpoint 在发送前拒绝。实际 keyless Search / Extract 再取官方正文 6,692 字符，保存 URL / 时间 / truncated=false；外扩 → M04 → M07 → 用户编辑的 5 / 3 / 3 / 3 次合成生成链通过，搜索 / 提取不另计生成，R1.4 完成。

六种逐项证据拒绝检查覆盖 supported / conflicting 的缺失引用、非本任务读取引用和试图以已有主张证据给另一连接背书；各自确已读来源的两状态可保存，unverified 连接 / 开放问题保留，不登记 M05。实际 PM AIAgent 在第 16 次完成时可发布并登记一项 M04；请求第 17 次时只到 provider 16 次，任务 BudgetError、无发布 / 覆盖 / M04，知识原字节保持。结合当前 12 项永久外扩契约与实际 M04 → 图 / M07 交接，R2.2 完成。模型响应仍合成，R2.3 不勾选；R2.1 的在途停机策略仍待用户，详见[总 Plan](../../plan.md)第十七批及[待办](../../pending.md)。

## 2026-10-20 第十九批：获准停机恢复完成

用户批准仅对 periodic_coverage / runtime_stopping 显式续接原任务，统一 Design 升至修订 4。Runtime.retry 重新核对当前授权与原输入后排队，保留 ID、配置 / Prompt / 执行输入版本、调用审计和已用次数；失败不改持久任务。Web 处理历史复用原重试按钮；用户取消、权限撤销、其他模块及 user_requested 取消仍拒绝。

新增长期回归先复现两个错误后通过：实际运行中停机 → 新 Store / Config / Runtime → tick 不自动恢复 → 手动续接原任务 → 提交才覆盖；另保护过时输入拒绝且原任务不变、当前路径权限重查及四类取消拒绝。14 项外扩、17 项 Runtime 测试通过。实际 APScheduler / SQLite 重启探针两次周期回调仍留原 pending，显式续接后由 1 次累计到 2 次、同一任务完成，后续不再重复；结合第十六批默认周期 / 配置 / 批次公平性证据，R2.1 完成。

真实 Chromium 验证仅受限任务显示重试、三类其他取消隐藏，点击实际 API 返回 202、ID / 输入 / 配置 / 次数保持。探针最初误将相同输入的任务登记视为不同案例，命中既有去重；修正为不同合成输入并等待当前任务 ID 后通过，未修改产品去重规则。完整产品 234 tests / OK（101.281 秒）、永久 Chromium 5 tests / OK（18.501 秒）；模型响应 / Desktop 语义未验，R2.3 保留。

## 2026-10-20 第二十一批：真实模型对象格式与上游限流

真实 AIAgent 首次对照 7 次生成，实际 Search / Extract 取得 SciPy rel_entr 主要来源，但 open_questions 字符串不符既有对象模型，被校验拒绝且没有发布。首次冻结输入时直接附现有 ExpansionRecord / ExpansionResult schema，并明确对象格式，不放宽校验、不另造 schema。14 项外扩回归与完整产品 235 项通过。

后续以 SciPy entropy 原文做 e-a / e-b 对照，前八次 keyless 工具调用均为 HTTP 429，第九次提取得到实际来源；300 秒探针到期清理时累计 16 次生成，任务保留 cancelled / runtime_stopping，没有发布或登记下游。原失败 7 次与新任务 16 次分别保留，不清预算，不把该用户请求任务套入周期恢复例外。后续先核对限流条件，安排明确的新验收；本轮不继续空转请求。详见[语义审阅](../../semantic-review.md)与 twentyfirst-expansion-rate-limit.json，R2.3 仍未完成。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

### 2026-10-15：Tavily 选择、G3 与外扩链路

用户选择 Tavily，随后说明暂时没有 key。官方现有免 key Search / Extract 已核对并实际调用；无需改模型协议或申请 key 即可继续。控制层固定官方 endpoint、复用固定 Hermes 提供者的请求头与归一化，不读取个人 `.env`。私有版本字段 search.api_key 优先，否则使用本次后台启动时的 TAVILY_API_KEY，均不传入任务载荷；空输入保留，显式 null 清除私有 key。无凭证为 keyless，有凭证为 keyed，工具历史保留实际 access_mode，不记 key。

真实公开核查问题为 Tavily Search / Extract 是否支持免 key：查询 `site:docs.tavily.com/documentation/keyless Search Extract without API key`，实际主要来源 `https://docs.tavily.com/documentation/keyless`。独立搜索返回 1 条、Extract 返回 6,692 字符，保存查询、实际正文、时间与错误于忽略的探针证据。实际 AIAgent 又通过控制层 web_search / fetch_page 读取并保存 external 来源，模型请求数为外扩 5、M04 3、指定字段用户编辑 3，共 11；工具调用本身不计模型请求。Hermes 内置同名 web_search 需要在独立任务 registry 显式 override；其 untrusted 结果包裹保留，未关闭框架防护。

G3 的搜索 / 阅读 / 工具与计数链通过，模型响应仍为 localhost 合成数据，不将它视为定性质量验收。自动调度只在模型 endpoint / model 已配置时启动等待；默认 3600 秒 / 十项。稳定 ID 循环游标和每对象依据版本持久化，频繁变化的早期对象不会挤掉历史节点；失败不推进，显式 retry 保留预算，旧输入取消后等待新依据续排，配置变化不清进度。用户要求重新探索通过带 client_request_id 的独立请求来源登记，不修改已有覆盖。重试失败任务不视为新周期，不重置次数。

结果逐项保存 claims / proposed_connections / open_questions；supported / conflicting 必须引用本任务实际读取并保存的来源。另一连接没有证据仍保留 unverified。搜索失败 / 限流 / 正文失败单独保留，不能把未取得依据当作正常成功空结果；已有真实依据的部分结果可带缺口提交。正常空探索不强迫重复检索。提交后交 M04，未提交或预算失败不交下游，不将外部结果当用户表现。

永久契约组 **11 项通过**，涵盖周期 / 配置、覆盖 / 重启 / 公平性、失败 / 过时输入、引用 / 部分核查、凭证版本 / 脱敏、取消后的晚返回和显式重探幂等。Task 1 全部、Task 2 全部、Task 3 Step 1–3 完成，当前 **12 / 13**；真实模型的 a / b / e 与先备定性对照仍为 Task 3 Step 4，见[执行待办](../../pending.md)。
