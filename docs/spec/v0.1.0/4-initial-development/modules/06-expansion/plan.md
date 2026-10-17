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

Modify：`src/distillai/expansion.py`、`tools.py`、`hermes.py` 及搜索私有配置交付；测试复用 `tests/test_product_expansion.py`。不新增搜索网关、多供应商接口、网页清洗器或浏览器工程。

## M06-R1：删除重复 HTTP 请求实现

- [x] **R1.1 固定上游调用边界。** 按总 Plan 的 Hermes SHA 核对 `plugins/web/tavily/provider.py` 的 `TavilyWebSearchProvider.search/extract`、`_tavily_request` 和 `_normalize_tavily_*`。明确公开 provider 读取环境 / 配置，私有请求函数可传 `api_key`；不得把它们当稳定公共 SDK。
- [x] **R1.2 复用完整请求路径。** 在已有 PM 任务进程使用固定 Tavily 实现：优先 provider 方法且每任务配置隔离；若其隐式环境读取会突破固定配置，调用同文件接受显式 key 的窄请求 / 归一化函数，仍不复制 HTTP 代码。固定官方 endpoint，清掉继承的 `TAVILY_BASE_URL` 和个人配置入口；私有连接参数不进入模型载荷 / 日志。删除产品 `tavily_request` 中的 urllib、headers、payload HTTP 编解码和重复结果适配。
- [x] **R1.3 保留程序来源身份。** `web_search` / `fetch_page` 仍只登记给 M06，框架注册与 untrusted 包装复用上游能力。搜索结果只作为候选；实际提取正文 / URL / 读取时间经 M01 管道交父进程确认、保存不可变 external 来源、返回产品 SourceRef。取消 / 过时任务的晚结果不得发布。搜索密钥进入当前任务进程是总 Plan 待批准边界，不能仍声称父进程独占。
- [ ] **R1.4 验证新组合。** 私有配置 key 优先于固定启动环境；空 key 使用已选 keyless，显式清除 / 空脱敏语义沿现有配置。用实际 Search / Extract 查一项主要来源，记录实际 URL / 文本 / 截断 / 时间；限流 / 权限 / 读取失败保留明确错误，不退回其他供应商、不用摘要冒充全文。验证搜索本身不计模型生成，后续推理仍计。

## M06-R2：复用覆盖进度与逐主张核查

- [ ] **R2.1 复用定时触发并复跑公平性。** 3600 秒的周期唤醒由 M01 的 APScheduler IntervalTrigger 执行，配置更新重排下一次等待，重启从持久外扩状态重建 / 检查已到期项，不自建周期线程；回调仍用原 tick 判断是否能登记业务任务。每批最多 10 个已有知识点为可配置初值，新批次生效不清覆盖；稳定 ID 循环让历史节点仍轮到。无新依据 / 变化 / 用户请求不反复探索，失败不推进；retry 留原次数，重探用已有 client_request_id / 独立提交来源。
- [ ] **R2.2 复跑主张与下游。** expansions 保留 claims / proposed_connections / open_questions，各项引用本次确已读取来源；supported / conflicting 不可借整体摘要跨项背书。未核查保留缺口，第 16 次完成可发布，仍要第 17 次失败不发布 / 不交 M04。成功版本沿原入口交 M04、图与 M07，外部结果不登记用户掌握分析。
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

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

### 2026-10-15：Tavily 选择、G3 与外扩链路

用户选择 Tavily，随后说明暂时没有 key。官方现有免 key Search / Extract 已核对并实际调用；无需改模型协议或申请 key 即可继续。控制层固定官方 endpoint、复用固定 Hermes 提供者的请求头与归一化，不读取个人 `.env`。私有版本字段 search.api_key 优先，否则使用本次后台启动时的 TAVILY_API_KEY，均不传入任务载荷；空输入保留，显式 null 清除私有 key。无凭证为 keyless，有凭证为 keyed，工具历史保留实际 access_mode，不记 key。

真实公开核查问题为 Tavily Search / Extract 是否支持免 key：查询 `site:docs.tavily.com/documentation/keyless Search Extract without API key`，实际主要来源 `https://docs.tavily.com/documentation/keyless`。独立搜索返回 1 条、Extract 返回 6,692 字符，保存查询、实际正文、时间与错误于忽略的探针证据。实际 AIAgent 又通过控制层 web_search / fetch_page 读取并保存 external 来源，模型请求数为外扩 5、M04 3、指定字段用户编辑 3，共 11；工具调用本身不计模型请求。Hermes 内置同名 web_search 需要在独立任务 registry 显式 override；其 untrusted 结果包裹保留，未关闭框架防护。

G3 的搜索 / 阅读 / 工具与计数链通过，模型响应仍为 localhost 合成数据，不将它视为定性质量验收。自动调度只在模型 endpoint / model 已配置时启动等待；默认 3600 秒 / 十项。稳定 ID 循环游标和每对象依据版本持久化，频繁变化的早期对象不会挤掉历史节点；失败不推进，显式 retry 保留预算，旧输入取消后等待新依据续排，配置变化不清进度。用户要求重新探索通过带 client_request_id 的独立请求来源登记，不修改已有覆盖。重试失败任务不视为新周期，不重置次数。

结果逐项保存 claims / proposed_connections / open_questions；supported / conflicting 必须引用本任务实际读取并保存的来源。另一连接没有证据仍保留 unverified。搜索失败 / 限流 / 正文失败单独保留，不能把未取得依据当作正常成功空结果；已有真实依据的部分结果可带缺口提交。正常空探索不强迫重复检索。提交后交 M04，未提交或预算失败不交下游，不将外部结果当用户表现。

永久契约组 **11 项通过**，涵盖周期 / 配置、覆盖 / 重启 / 公平性、失败 / 过时输入、引用 / 部分核查、凭证版本 / 脱敏、取消后的晚返回和显式重探幂等。Task 1 全部、Task 2 全部、Task 3 Step 1–3 完成，当前 **12 / 13**；真实模型的 a / b / e 与先备定性对照仍为 Task 3 Step 4，见[执行待办](../../pending.md)。
