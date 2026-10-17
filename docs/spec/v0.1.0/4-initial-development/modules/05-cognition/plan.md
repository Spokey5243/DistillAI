---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M05：复用证据维护，完成语义与自然反馈验收 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、现状与文件

依据[统一 Design M05](../../design.md#cognition-decisions)、[自然引导](../../design.md#natural-validation)与[总 Plan](../../plan.md)。现有证据、竞争假设、理解文字判断、同源身份与等待机制继续使用；本模块不新建学习算法或评分框架。

Modify：`src/distillai/cognition.py`、`prompts/cognition.txt`，仅处理新执行接入或验收暴露的具体问题；业务 ID / 工具登记沿 `tools.py`。复用 `tests/test_product_cognition.py`、`test_product_feedback.py`、`test_product_corrections.py`，Store / Runtime / 来源均沿归属模块。

## M05-R1：保留来源身份与修订边界

- [x] **R1.1 复跑证据组。** 同原始用户位置复用观察，MCP 补帮助不增加独立表现；同文本不同位置不合并。只有助手文本不能作用户表现，一来源支持多个对象不算多次表现，保留任务 / 帮助 / 时间 / 来源。
- [x] **R1.2 复跑三类输入与权限。** 原 episode + M04（包括空结果）、已关联 MCP 反馈、Web 独立纠错继续同一维护入口。普通反馈未关联不能伪造 user_submission；M05 只写自己归属字段，跨对象假设按现有 refs 定位，知识正文 / 关系端点保留。
- [x] **R1.3 复跑等待与后继。** 旧 episode 修订任务不能发布；只有当前固定修订成功（含有依据无变更）解除直接等待。失败保留旧判断 / 等待，解除后登记 M07 新准备；旧候选不能在 M07 更新前复活，已选快照仍可 compact 恢复。不沿图传播、不由模型清程序状态。

## M05-R2：实际模型对照和自然反馈

- [ ] **R2.1 复用七组既有语义材料。** 核对其真实合成队列引用、Prompt 版本和最新模型配置；材料覆盖助手解释 + 明白了、受助解释、独立失误后提示修正、新证据反对旧假设、无区分力 / 时间经过、仅 episode 归属修订、单次联想。原材料若已过时修正引用，不再造第二套评测工程。
- [ ] **R2.2 运行直连 AIAgent 并人工审阅。** 每组保存实际输入 / 输出版本、用户表现、已获帮助、支持 / 反对观察、仍未决解释及审阅理由。检查没有凭认可 / 提问 / AI 产物写成独立掌握，没有时间衰减、强制总分或沿图扩散；不把 completed / JSON 正确当语义通过。费用 / 密钥沿用户私有配置和当前授权范围。
- [ ] **R2.3 联同 M07 实测反馈。** MCP 早到等 Stop 来源，歧义保持待关联，可信原文到达后同源唯一维护；再用有区分力的新用户表现观察假设 / 检索的实际变化。原任务可继续、素材可跳过，中立反馈不泄露目标答案。Desktop 真实行为与程序契约结果分别记录。

## 验证、测试取舍与依赖

```powershell
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_cognition.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_feedback.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_corrections.py' -v
```

预期各 `OK`。已有来源 / 同源 / 权限 / 等待组优先复用；新增永久用例必须指明旧组漏掉的实际回归，语义措辞和模型排序不作固定断言。依赖 M01 新执行、M02 / M03 来源和版本、M04 结果、M07 来源关联。外部知识只交 M04，仍不直接证明用户理解。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 恢复后第三批：Windows、管道与到期恢复

在新的 SQLite / 直接 SDK / FastAPI 组合复跑认知、反馈与纠错原组：同一用户来源复用观察，同文不同位置不合并，助手解释不算用户表现；episode + M04、已关联反馈、Web 独立纠错沿原维护入口；正文 / 端点归属保护、修订等待和 M07 依赖恢复均通过。完整产品 192 项通过，R1 三项仅勾程序契约复跑，R2 真实模型语义与自然 Desktop 反馈仍未验。证据与当前范围见[总 Plan](../../plan.md)第三批。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

观察、观察来源、内联 / 共享假设、跨对象观察定位、定性判断、纠错请求和发布结果接入本模块严格模型；定性理解递归类型拒绝数值评分。保留来源身份复用、实际用户证据、字段所有权、依赖版本和同清单等待规则。完整产品 192 项与实际 PM Episode→M04→M05、新材料修订→空 M04→空 M05 通过；G2 与真实语义仍待验。见[总 Plan](../../plan.md)。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

## 2026-10-15：证据、假设与 episode 分析接入

已实现 cognition.py / P04，以及 observations、内联 / 跨对象 hypotheses、cognition 的结构、引用和字段归属校验。用户来源按原始物理位置判定；助手单独正文拒绝，助手帮助背景不增加一次表现，相同文本不同位置不合并。观察 ID 由控制层按用户原始位置分配并复用；竞争解释、支持 / 反对观察和待区分问题保留，理解为文字判断，不引入分数或固定等级。知识正文、关系端点 / 核查及内容 provenance 的修改被拒绝。

M04 episode 分析包括正常空结果均登记 M05；执行固定原文和详情快照，实际变更引用由程序补版本。已关联 MCP 反馈可登记同一认知维护入口，来源未关联则保持等待，不伪造 user_submission。M05 实际修改直接依赖时接续 M07 准备。修订等待标记及解除、Web 明确纠错、完整自然反馈与语义对照验收仍未完成，因此本模块仅勾选 4 / 12 步。

真实 AIAgent 配本机合成 provider 的 M03 → M04 → M05 链路取得观察 / 假设记录，用户仅提出请求时保留理解未知；机械验证不等同于模型语义质量验收。具体请求计数与最新验证见总 Plan；原文和探针留在忽略目录，不提交个人数据或凭证。

### 2026-10-16：三类输入、等待解除与 Web 独立纠错

Web 入口 POST /v1/cognition-corrections 接收单个知识 / 关系目标的 expected_version、performance、help、reason。程序保留独立 user_submission，观察 source 不伪造 episode_id；复用原始用户身份及新观察分配，原有表现和内容版本保留。任务仅维护选定对象的认知字段，拒绝正文改动和跨对象自动纠错。与 episode 分析、已关联 MCP 反馈共用 M05 流程；普通 MCP 来源仍须真实关联。

程序等待状态与修订 / 当前 M05 分析各自同事务保存，Agent 不可编辑。只有固定 episode_ref 仍为当前版本且成功提交，才将直接等待标记转为 ready；有依据的无变更结果也可解除。失败 / 旧输入保持 waiting，解除状态触发 M07 直接依赖刷新且不增加材料计数。Web 和 MCP 附当前等待说明，旧判断正文和查询历史版本不改。

认知、纠错和上下文契约已运行，实际 AIAgent 纠错链 11 次合成 provider 请求通过，其中独立认知提交 4 次。Task 1 Step 4、Task 2 Step 3–5 完成，当前 8 / 12；完整同源反馈和真实模型语义对照仍未验收。

### 2026-10-16：反馈同源复用与新依据分析入口

补充实际 MCP 反馈 → M05 的契约回归：修复登记范围漏带 cognition/reanalysis.json 导致程序清等待无法提交的问题。相同原始用户位置的两次不同请求复用一个 observation ID，补充帮助条件，未增加第二份表现；助手及未关联普通反馈仍不能伪造独立提交来源。

显式最新依据重分析使用独立请求来源、client_request_id 幂等及最新 episode refs，登记新的 M04 → M05，原失败任务、固定输入和调用数保留。浏览器已验证原失败分析后新链成功并将等待改为 ready。7 组语义对照材料已准备于忽略目录 semantic-acceptance-data，真实队列范围、字节版本、当前 Prompt 和准备配置可回查；模型调用 0，未声称语义通过，未来实际执行固定自己的模型配置。

Task 2 Step 1、Task 3 Step 1 完成，累计 10 / 12；剩余两步为真实模型对照与真实自然反馈闭环。
