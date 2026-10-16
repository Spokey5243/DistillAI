---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M06：主动外扩与来源核查 Implementation Plan

> 执行者使用 `executing-plans`，按本模块 checkbox 推进；默认主 Agent 实施。

## 来源与目标

依据[统一 Design M06](../../design.md#knowledge-expansion)、[搜索选择](../../design.md#technical-selection)及[总 Plan](../../plan.md)。周期覆盖全部已有知识，从具体问题探索新联系并逐主张核查，保留有据结果 / 未核查缺口，再交 M04；不将外部知识当用户理解。

## 文件映射

Create：`src/distillai/expansion.py`、`src/distillai/prompts/expansion.txt`、`tests/test_product_expansion.py`。

Modify：`tools.py` 接入最终选择的 web_search / fetch_page，`runtime.py` 周期 / 覆盖 / M04 依赖，`storage.py` 外部来源与外扩结果校验，`config.py` 接入实际搜索凭证配置与脱敏，README。不建立多供应商切换框架、浏览器工程或训练系统。

## Task 1：闭合搜索接入条件

- [x] **Step 1：到接入前收敛一个搜索方案。** 根据已选 Hermes、实际模型协议与用户要求，呈现具体内置工具或独立 API 的调用 / 凭证 / 费用与错误行为供选择；用户此前要求延后，写 Plan 不代替这个决定。新配置字段 / 外部依赖同步 Design 后再实现，未选择保持 G3 未通过。
- [x] **Step 2：验证工具和模型边界。** 用最终方案查一个公开具体主张、读主要来源，记录查询 / URL、实际读到的相关正文、时间、截断 / 读取失败、凭证位置；任何额外模型生成都经 M01 计数。搜索工具调用本身不计模型请求，不把供应商综合答案冒充全文。
- [x] **Step 3：实现窄适配。** 只对 M06 注册实际 web_search / fetch_page，返回真实内容与来源 / 错误；凭证控制层持有，历史 / Prompt / Web 不返回 key。授权网络动作不以本地回退成功声明远端撤销。
- [x] **Step 4：验证 G3。** 搜索、阅读、错误和预算计数都有实际证据才接入自动周期。没有配置时展示不可用原因，不消耗周期 / 覆盖进度、不用合成响应冒充生产搜索。

## Task 2：周期、覆盖和探索记录

- [x] **Step 1：写调度 / 覆盖用例。** 假时钟推进 3600 秒触发，批次最多十个已有知识点；修改周期用于下一等待、修改批次用于新任务，不清进度。稳定 ID 排序覆盖全图，近期对象可前置而历史仍轮到；同问题无新依据不反复探索，有节点变化 / 新用户证据 / 请求才可重新探索。
- [x] **Step 2：实现持久覆盖。** 控制层保存覆盖位置、已完成探索对象 / 问题及版本依据；运行输入固定，新记录留后批；成功提交才推进完成位置，失败保留待办与次数。同级后台队列沿 M01，不抢占查询 / 注入。
- [x] **Step 3：实现结果 / 来源载荷。** `expansions/<id>.json` 保存问题、输入 refs、探索理由、claims / proposed_connections / open_questions；每项关联外部来源与核查说明。`external-sources/<id>.json` 保存实际 URL / 标题 / 读取时间 / 必要相关正文及不可变版本，引用 source_kind=external；不伪造队列行号，不下载整站 / 媒体。
- [x] **Step 4：写并实现引用校验。** 主张引用必须在真实已保存来源，未读取 / 抓取失败明确标缺口；候选连接端点引用现有 / 拟维护对象，未核查另一连接不能跟随整体摘要变成成立。来源保存范围按许可与必要性，校验复用 M01 / M04。
- [x] **Step 5：运行外扩契约组。**

```powershell
python -m unittest discover -s tests -p 'test_product_expansion.py' -v
```

预期：周期 / 覆盖 / 结果校验 `OK`，不访问真实网络；真实工具证据另见 Task 1。

## Task 3：AIAgent 核查、发布与下游

- [x] **Step 1：发布 P05 和任务。** P01 + P05 + 固定知识 / 关系 / 用户证据 / 既有探索，按具体主张搜索 / 阅读。给定性连接价值、理解增量、当前需要和学习成本，图遍历只定位已有对象；不制造加权分或“高连接数=价值”。
- [x] **Step 2：接入正常结束 / 预算边界。** 有依据且足以结束时允许提交有据部分和缺口，第 16 次完成可成功；仍需第 17 次不发出、沿 M01 失败恢复，未发布文件不交 M04。正常空结果可成功，不为“无结果”不断重新搜索。
- [x] **Step 3：发布后交 M04。** M06 校验 / 提交真实结果版本后登记 M04 expansion_refs 维护；索引 / 子图沿后继触发。M05 只在另有真实用户表现时更新，外部结果自身不登记用户已掌握分析。
- [ ] **Step 4：人工核对一个完整外扩。** 使用两个已有概念 a / b 和候选 e：若只找到 e-a 的依据，e-b 保留未核查；比较单端 c / d 与双端 e 的定性理由和必要先备优先情况。记录实际原文 / 主张 / 版本 / Prompt / 后继变化，不按 LLM 文措辞断言质量。

## 测试必要性、依赖与状态

永久组保护覆盖不清零、不无依据重复、批次 / 周期生效、逐主张来源、失败不推进与不发布；现有测试无覆盖。M01 预算机制不重复实现，只测外扩下游不收到失败任务。搜索供应商、公开来源内容与定性价值效果做一次性验证，不锁搜索排序 / 固定网页 / 模型名。

依赖 M04 + M05，真实接入依赖 G1 + G3；未完成本模块则完整初版不能验收。2026-10-13 用户授权按当前 Plan 开始实施，本 Plan 已批准；完成状态按 checkbox 与执行记录核对。

### 2026-10-15：Tavily 选择、G3 与外扩链路

用户选择 Tavily，随后说明暂时没有 key。官方现有免 key Search / Extract 已核对并实际调用；无需改模型协议或申请 key 即可继续。控制层固定官方 endpoint、复用固定 Hermes 提供者的请求头与归一化，不读取个人 `.env`。私有版本字段 search.api_key 优先，否则使用本次后台启动时的 TAVILY_API_KEY，均不传入任务载荷；空输入保留，显式 null 清除私有 key。无凭证为 keyless，有凭证为 keyed，工具历史保留实际 access_mode，不记 key。

真实公开核查问题为 Tavily Search / Extract 是否支持免 key：查询 `site:docs.tavily.com/documentation/keyless Search Extract without API key`，实际主要来源 `https://docs.tavily.com/documentation/keyless`。独立搜索返回 1 条、Extract 返回 6,692 字符，保存查询、实际正文、时间与错误于忽略的探针证据。实际 AIAgent 又通过控制层 web_search / fetch_page 读取并保存 external 来源，模型请求数为外扩 5、M04 3、指定字段用户编辑 3，共 11；工具调用本身不计模型请求。Hermes 内置同名 web_search 需要在独立任务 registry 显式 override；其 untrusted 结果包裹保留，未关闭框架防护。

G3 的搜索 / 阅读 / 工具与计数链通过，模型响应仍为 localhost 合成数据，不将它视为定性质量验收。自动调度只在模型 endpoint / model 已配置时启动等待；默认 3600 秒 / 十项。稳定 ID 循环游标和每对象依据版本持久化，频繁变化的早期对象不会挤掉历史节点；失败不推进，显式 retry 保留预算，旧输入取消后等待新依据续排，配置变化不清进度。用户要求重新探索通过带 client_request_id 的独立请求来源登记，不修改已有覆盖。重试失败任务不视为新周期，不重置次数。

结果逐项保存 claims / proposed_connections / open_questions；supported / conflicting 必须引用本任务实际读取并保存的来源。另一连接没有证据仍保留 unverified。搜索失败 / 限流 / 正文失败单独保留，不能把未取得依据当作正常成功空结果；已有真实依据的部分结果可带缺口提交。正常空探索不强迫重复检索。提交后交 M04，未提交或预算失败不交下游，不将外部结果当用户表现。

永久契约组 **11 项通过**，涵盖周期 / 配置、覆盖 / 重启 / 公平性、失败 / 过时输入、引用 / 部分核查、凭证版本 / 脱敏、取消后的晚返回和显式重探幂等。Task 1 全部、Task 2 全部、Task 3 Step 1–3 完成，当前 **12 / 13**；真实模型的 a / b / e 与先备定性对照仍为 Task 3 Step 4，见[执行待办](../../pending.md)。
