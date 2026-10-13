---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: draft
decision_mode: user-approved
---

# M05：用户证据、假设与理解 Implementation Plan

> 执行者使用 `executing-plans`，按本模块 checkbox 推进；默认主 Agent 实施。

## 来源与目标

依据[统一 Design M05](../../design.md#cognition-decisions)、[自然引导](../../design.md#natural-validation)及[总 Plan](../../plan.md)。从实际用户表现维护观察、竞争假设和定性理解判断，保留帮助和来源；证据修订期间旧判断可历史查询，暂不新注入。

## 文件映射

Create：`src/distillai/cognition.py`、`src/distillai/prompts/cognition.txt`、`tests/test_product_cognition.py`。

Modify：`storage.py` 注册 M05 字段 / 引用校验，`runtime.py` 维护直接依赖和等待解除，`server.py` 认知明确纠错入口。知识 / 关系正文沿 M04，反馈来源关联交 M07。

## Task 1：证据结构和字段权限

- [ ] **Step 1：写结构 / 来源测试。** 合成 observation 包含用户表达 / 产物、任务、时间、来源、帮助；hypothesis 引用支持 / 反对观察和待区分问题；cognition 保留评估时间 / 文字 / 观察与假设引用。未知来源、只有助手正文却声称用户表现的来源、缺观察引用、同源重复与跨模块修改必须被检测；有用户正文只证明来源具备分析材料，不机械证明用户理解。
- [ ] **Step 2：实现 M05 字段校验。** 沿知识 / 关系 example 的 observations / hypotheses / cognition / changes，不强制填满理解维度，不引入分数、固定等级、遗忘曲线。保留知识正文、关系端点 / 核查和知识来源；允许修改所属 cognition provenance / 变更原因。
- [ ] **Step 3：实现跨对象假设。** `hypotheses/<id>.json` 保存受影响 knowledge / relation refs，关系只保存 hypothesis_refs；同文件观察用记录 ID + observation ID 定位，不为布局把全部观察拆文件。字段与引用经 M01 / M04 共同校验。
- [ ] **Step 4：接入三类维护输入。** episode 分析始终读取原材料和 M04 结果，包括空；已关联普通会话反馈进入相同流程；Web 明确纠错使用独立 user_submission 版本和原因。未关联普通反馈不得伪造提交来源进入观察。

## Task 2：同源复用、修订等待与提交

- [ ] **Step 1：实现来源身份复用。** 同一真实来源的同一表现只一份观察，MCP 补充帮助 / 纠错合并到已有证据；一来源可以支持多个对象但不计成多次独立表现。相同文本不同位置不自动同源，不新增跨位置重采去重系统。
- [ ] **Step 2：发布 P04 并接入任务。** 用 P01 + P04、固定 episode / 反馈和相关记录；Agent 综合历史观察 / 支持反对证据，竞争解释可保持未决。最终输出实际 knowledge / relation / hypothesis refs 和 reason，版本由程序提交补齐，正常空结果允许成功。
- [ ] **Step 3：接入当前修订等待解除。** 查询 / Web 展示历史判断和“依据已修订，等待重新分析”；新注入排除此依赖。M05 在运行和提交前复核 episode 最新修订，只有对应当前修订分析成功并提交才解除直接标记，包括有依据的无变更结果；失败 / 过时仍等待。不沿图传播或由模型清控制状态。
- [ ] **Step 4：触发 M07 准备。** M05 相关记录或等待状态实际改变后，为直接依赖的开放 episode 登记准备；合并未运行重复待办、运行输入固定。不把正文变化自动当理解变化。
- [ ] **Step 5：运行认知契约组。**

```powershell
python -m unittest discover -s tests -p 'test_product_cognition.py' -v
```

预期：`OK`；同源复用、字段保护、等待解除和过时防发布均成立。

## Task 3：语义效果与自然反馈验收

- [ ] **Step 1：建立合成对照材料。** 使用下表各组的用户 / 助手原文、真实测试队列来源、固定 Prompt / 配置；每组说明允许支持的范围，不以 fixture 的标准答案注入生产 Prompt。

| 材料 | 人工审阅标准 |
| --- | --- |
| 只有助手讲解 + 用户“明白了” | 不写独立理解或应用证据 |
| 刚看过讲解后用自己的话讲清机制 | 支持当时解释理解，保存已获帮助，不要求额外考试 |
| 独立漏步骤，提示后修正 | 独立与受助分别记录；理解不足 / 疏漏等竞争解释可并存 |
| 有新表现直接反对旧假设 | 关联支持 / 反对来源并修订理由，不仅取最后一句覆盖 |
| 无区分力表现或经过时间 | 保持未决，不自动降低理解 |
| 仅 episode 分组修订、原证据含义没变 | 当前修订分析可保留判断并解除直接等待 |
| 单条用户联想 | 保留具体表现，不能推稳定习惯或沿图推掌握 |

- [ ] **Step 2：执行真实 AIAgent 对照任务。** 记录实际输入、输出版本、帮助、观察 / 假设变化和人工判断；结果不能只以格式正确 / completed=True 认定语义有效。语义测试不按固定词句断言，不保证模型没有误判断。
- [ ] **Step 3：与 M07 验证自然反馈闭环。** MCP 反馈先于 Stop 时等待来源，落盘后再维护，同一表现仅一份观察；取得一次有区分力的新用户表现使假设 / 检索改变的证据。通用 Agent 完成原任务、素材可跳过、不泄露目标答案；沉默 / 认可不直接转化为独立表现。

## 测试必要性、依赖与状态

永久组保护证据引用、角色 / 帮助结构、同源身份、字段权限和等待状态，不检验 LLM 文本是否逐字符合预设。现有测试没有产品认知覆盖；M01 提交恢复不重复。真实假设区分能力、Prompt 效果和日常中立交互是一次性人工验收。

依赖 M01 / M02 / M04、M03 修订与 M07 来源关联。当前无业务偏差。本 Plan 为 draft，全部任务未执行。
