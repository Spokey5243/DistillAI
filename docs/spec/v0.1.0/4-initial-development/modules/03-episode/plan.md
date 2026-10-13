---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: draft
decision_mode: user-approved
---

# M03：episode、计时与修订 Implementation Plan

> 执行者使用 `executing-plans`，按本模块 checkbox 推进；默认主 Agent 实施。

## 来源与目标

依据[统一 Design M03](../../design.md#episode-model)、[交接 C01 / C02](../../design.md#closing-contracts)及[总 Plan](../../plan.md)。保留完整来源，持久维护一条活跃 episode / session 和待归属缓冲，以真实生命周期收尾；纠错后把最新固定修订交 M04 / M05，并保护等待重分析的旧判断。

## 文件映射

Create：`src/distillai/episode.py`、`src/distillai/prompts/episode.txt`、`tests/test_product_episode.py`、`tests/test_product_lifecycle.py`。

Modify：`tools.py` 注册 `evaluate_episode_boundary`，`runtime.py` 登记依赖 / 计时 / 修订保护，`plugins/distillai/hooks/dispatch.py`、`hooks.json` 接入生命周期。复用 M01 保存，来源只经 M02 读取；原队列只读。

## Task 1：验证并接入生命周期

- [ ] **Step 1：观察真实 Hook 时序。** 在独立 Desktop 测试会话记录 UserPromptSubmit、Stop、PreCompact / compact SessionStart、中断和关闭 / SessionEnd 实际事件及可用字段；附接入端 UTC、顺序和采集后完整行数。检查 Stop 被其他 Hook 继续时是否等同终止。这个验证构成 G2 的计时部分，不能从“文档有事件”推断已收到。
- [ ] **Step 2：固定事件适配。** 受保护记录包含 session、kind、观察 UTC、本地递增序号、当时完整队列行数；kind 沿 request_started / response_stopped / interrupted / session_ended。UserPromptSubmit 等筛选前登记开始，Stop 完成正文采集后登记终止，SessionEnd 补采后排收尾。PreCompact 不登记终止；中断的实际计时处理先依据 Step 1 同步 Design，不猜成功结束。
- [ ] **Step 3：写假时钟用例。** 终止后 29 分钟未收尾，新开始暂停旧计时，后续终止重新给完整 30 分钟；重启复用持久终止 UTC，不以文件 / 分析时间重计。缺事件 / 顺序不可靠不收尾；收尾任务只在所属已知材料处理后运行。
- [ ] **Step 4：实现计时和延迟材料处理。** 程序保存有效终止依据、截止时间和已知来源边界；实际新续聊另建，旧段迟到材料交原 episode 修订。无法区分先缓冲、保留诊断，不按后台到达时间切新记录。计时只登记任务，不在 Hook 等 LLM。
- [ ] **Step 5：运行生命周期组。**

```powershell
python -m unittest discover -s tests -p 'test_product_lifecycle.py' -v
```

预期：`OK`；真实平台未提供足够事件时保持 G2 未通过，测试不模拟一个并不存在的平台保证。

## Task 2：评分往返、归属与缓冲

- [ ] **Step 1：写公式和归属用例。** 覆盖下表、非法 C / 依据、无活跃记录、一个用户消息及多个助手片段同轮、工具不单计轮、三轮新交流、独立插曲、低分新轮不清缓冲以及不足窗口收尾。

| 输入 | 程序结果 / 断言 |
| --- | --- |
| 关键词无交集、C=4 | S=0.8，保留旧目标 |
| 关键词完全重合、C=0 | S=3.2，能进入独立交流判断 |
| Jaccard=0.5、C=2 | S=2，边界值保留缓冲 |
| 任一侧无有效关键词、C=1 | S=3，不制造关键词概率 |
| C=5 / 非整数 / 来源不在固定任务范围 | 拒绝评分，不发布语义状态 |
| 已有缓冲 + 新轮 S<2 | 共同复核，不单独清空旧缓冲 |

- [ ] **Step 2：实现最小记录。** episode 包含 C01 字段；source_refs 多段保留实际顺序，closed 添加 close_reason / summary。每 session 状态持久 active_episode_id / buffer；正文归属与缓冲不重叠，已处理材料不遗漏。历史只引用队列，不复制原文或 summary 替代。
- [ ] **Step 3：注册程序评分工具。** 校验固定旧 episode_ref、关键词 / 来源、候选原文 / C / 理由及最多五个规范关键词，计算 K / S 并保存实际输入 / 结果。Agent 在同一 AIAgent 循环收到结果继续编辑副本；最终提交仅采用程序保存的评分。不新建评分调度任务；工具不计次数，继续推理计同任务预算。
- [ ] **Step 4：接入 P02 维护任务。** P01 + P02 + 固定新材料 / 近期原文 / 状态 / 生命周期；开始后输入固定，新材料另排。无活跃记录直接建；S≥2 先缓冲，窗口内各轮 S≥3 且同一新目标才回落首轮切换；收尾不足窗口保守判断并保留理由。校验实际变更和 result 五字段，再交 M01 发布。
- [ ] **Step 5：运行归属组并审阅语义案例。**

```powershell
python -m unittest discover -s tests -p 'test_product_episode.py' -v
```

预期：程序约束 `OK`；用合成追问、纠错、同主题新请求、独立插曲审阅实际 AIAgent 原文依据。语义案例记录输入版本 / Prompt / 判断理由，不以固定措辞或模型自评分建立永久断言。

## Task 3：关闭 / 修订交接与过时分析

- [ ] **Step 1：实现提交后业务依赖。** 新开放首次准备 M07，新增来源成功更新计周期；关闭 / 修订提交登记 M04，M04 成功包括空结果后登记 M05。依赖持久且幂等，失败保留待办，不将整链成功。关闭不表示理解 / 问题解决。
- [ ] **Step 2：实现纠错入口。** 用户编辑提交 expected_version、指定归属变化、原因与独立用户提交来源；新材料确有旧边界错误才修订直接受影响记录，不批量全历史重切或跨 session 自动合并。提交先校验身份 / 来源 / 不重叠，再登记最新修订分析。
- [ ] **Step 3：实现等待标记和旧输入防发布。** 同一修订提交中由控制层标记直接依赖受影响来源的判断；M03 不写 cognition。M04 / M05 运行前和提交锁内核对 episode 输入版本，过时则取消未发布副本、留输入 / 已用次数 / 历史并复用最新修订任务。已提交旧历史不删除；不替换运行输入或自动合并结果。
- [ ] **Step 4：补交接回归用例。** M04 空结果仍分析新用户表现；旧 M04 / M05 分析分别在启动前 / 提交前遇新修订不能发布；仅新修订对应 M05 成功才解除等待标记，失败继续等待；开放准备依赖变化不增加材料计数。复用 M01 事务测试，不重测存储实现。
- [ ] **Step 5：验证真实收尾与修订链。** 手动 SessionEnd / 模拟时钟的业务收尾与真实 Desktop 30 分钟终止计时分别记录；旧段补采 / 新续聊各检查一次。确认来源 → episode → M04 → M05 / M07 全链版本可回查。

## 测试必要性、依赖与状态

永久组保护轮次 / 缓冲、单活跃记录、评分工具范围、真实输入固定、生命周期暂停 / 重计、关闭 / 修订依赖和旧版防发布；现有采集测试无覆盖。Desktop 信号 / 终止误差、Prompt 归属质量和当前发行组合是一次性验证；不固定模型判断正确率或事件数。

依赖 M01 + M02，生命周期未知处保留 G2 验证条件；中断语义不得静默改 Design。当前无业务偏差。本 Plan 为 draft，全部任务未执行。
