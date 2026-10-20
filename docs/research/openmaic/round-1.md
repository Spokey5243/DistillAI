# OpenMAIC：教学策略与理解验证（2026-10-02）

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

## 调研范围与项目定位

官方仓库为 [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC)，已克隆到 `E:\JourneyIntoAI\DL_and_LLM\projects\OpenMAIC`。本次源码快照为 `c72a64b4b669608bd682ae561bea0e059710930a`，调研基于 README、教学 Skill 和运行时代码，未安装依赖或启动课堂。以下区分源码描述的机制与 DistillAI 的待实现设想。

OpenMAIC 将学习需求转为可运行的互动课堂：用户输入主题、学习要求或上传材料，系统生成大纲、教学页面和讲解动作；课堂运行时由教师、助教和 AI 学生等角色参与互动。教学页面包括课件、测验、交互演示和项目式学习任务，也支持语音讲解、白板及页面元素高亮。

```text
学习需求或材料 → 选择教学策略 → 课程大纲
              → 教学页面、练习与讲解动作
              → 多 Agent 课堂互动 → 用户作答与反馈
```

课堂调度 Agent 通过 `call_agent` 决定谁发言，通过 `cue_user` 将机会交回用户，或用 `close_session` 结束互动。教师承担主要解释与教学推进，助教补充或改换解释方式，AI 学生提出常见误解、追问或例子；角色 Prompt 限制学生抢先承担主要讲解及学生之间的自我对话。需要页面内容时，调度器先读取实际场景，再交给发言角色使用。这是角色与上下文的编排，不表示每个角色都有独立训练的模型。

参考固定快照：[项目介绍](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/README-zh.md)、[课堂调度与角色 Prompt](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/lib/chat/pi/prompts.ts)。

## 与学科、概念学习相关的 Prompt

这些教学策略以 `skills/agent-runtime/<name>/SKILL.md` 保存，并实际接入生成流程。运行时发现和读取 Skill 后，将其正文及可选结构约束放入大纲生成器的 `teacherContext`；生成后可检查结构约束并将问题返回给 Agent 修订。结构检查不能证明所有教学要求已经执行，也不能证明学习效果。

| 教学 Skill | 规定的学习过程 | 对 DistillAI 的潜在用途 |
| --- | --- | --- |
| [课程规划](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/curriculum-planner/SKILL.md) | 根据学习目标、基础与时间拆分系列课程，逐步生成 | 用户明确要学习某一学科时，组织后续学习路径 |
| [费曼学习法](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/feynman-learning/SKILL.md) | 先由学习者解释，再找因果缺口、追问、重新解释，并在新情境中检验 | 从用户自己的解释中提取概念混淆与待验证的理解缺口 |
| [螺旋课程](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/spiral-curriculum/SKILL.md) | 反复接触少量核心概念，逐步增加复杂度、概念联系与迁移要求 | 串联同一概念在不同时间、情境下的理解证据 |
| [最近发展区](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/zone-of-proximal-development/SKILL.md) | 独立尝试 → 判断卡点 → 提供适量帮助 → 撤去帮助 → 新任务复核 | 区分不同困难解释，记录独立完成与提示后完成的差异 |
| [学会学习](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/learning-to-learn/SKILL.md) | 在具体学习中加入提取练习、自我解释、预测与理解检查 | 形成关于学习策略的待验证线索，并安排后续检查 |
| [逆向教学设计](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/understanding-by-design/SKILL.md) | 先明确最终理解目标及评价证据，再安排活动 | 先定义什么表现能支持理解判断，再选择验证问题 |

参考：[Skill 加载与大纲适配](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/lib/server/agent-runtime/skills.ts)。

## 理解证据与长期模型的边界

最近发展区 Skill 与本项目的假设验证目标最接近。它要求观察真实作答，区分缺少知识、步骤执行困难、题意不清和证据不足；当不同解释会改变帮助方式时，只补一个有区分力的问题。判断需要连接原话与解释，不能把未说出的心理状态写成事实，也不能从一次成功直接推断稳定掌握或长期保持。

它还要求记录实际提供的帮助、是否看过答案，以及撤去提示后在新任务中的表现。AI 同伴的答案属于教学材料，不计作用户表现；带关键步骤提示的完成也不能记为独立完成。这些规则可供 DistillAI 的证据提取和状态更新借鉴。

螺旋课程 Skill 提出了概念跨课记录，但明确说明平台不会替该 Skill 自动维护概念模型，需要在当前对话中保存教师侧记录，并在后续课程前回读已保存课堂。因此，教学 Prompt 提供了概念记录和验证方法，不能据此认定 OpenMAIC 已实现完整、独立的长期用户认知模型。

## 融入 DistillAI 的候选方式

可以将这些 Prompt 改写为同一个后端 Agent 按任务选择的分析与验证策略，符合一个 Agent 对应一个用户的定位。候选流程为：

```text
采集会话 → 提取概念与用户证据 → 形成竞争假设
        → 选择验证策略 → 前台在相关任务中取得用户回应
        → 保存验证条件与结果 → 更新理解状态
```

OpenMAIC 主要围绕明确的学习活动组织教学，而 DistillAI 的用户可能正在编程、讨论方案或处理工作。适配重点是将整课设计转为围绕当前任务的一次小验证；已有工作产物足够时先分析产物，需要更多证据时再自然追问。

示例：用户问“能不能用 Git 驱动文件更新事件”，可以保留“已理解事件驱动，只是在比较实现方式”与“尚未区分发现变化和可靠消费事件”两个假设。后续讨论文件更新后如何确认哪些记录已经处理时，用户自己的解释可能帮助区分二者，也可能出现第三种解释。此例只是候选验证设计，不是对用户的既定判断；应先明确不同假设预期出现的证据，不能把 Agent 自己给出的解答算作验证成功。

建议先借鉴最近发展区 Skill，验证“观察 → 假设 → 小验证 → 更新”的闭环，再按需要引入费曼学习法等策略。Prompt 指导推理与交互，原始证据、竞争假设、验证问题、帮助条件及状态变化仍需单独保存。知识表征提供概念及关系；理解状态根据用户表现更新；遗忘与复习模型仍需要跨时间的回忆记录。这些接入方式均为讨论方案，尚未在 DistillAI 中实现。
