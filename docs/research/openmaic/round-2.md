# OpenMAIC：概念扩展、深化与认知边界（2026-10-04）

轮次：第 2 轮专题核对（已完成）。本轮覆盖概念扩展相关教学 Skill，以及补充核对的 PBL v2 理解验证与教学等级代码；未运行课堂。Eigma 的独立核对见其第 2 轮记录。

## 问题与核对范围

用户提出：会话出现反向传播后，搜索梯度下降、优化器等相关概念，形成潜在知识关联；从广度与深度生成理解假设，在日常任务中通过上下文交付取得验证证据；考虑用轻量图表达概念与假设的关联并选择验证对象。

本轮核对本地仓库 HEAD `c72a64b4b669608bd682ae561bea0e059710930a` 及同一 GitHub 快照的 `deep-research`、`curriculum-planner`、`spiral-curriculum`、`feynman-learning`、`understanding-by-design` 和 `zone-of-proximal-development`。未启动课堂、生成页面或验证运行效果。下述结论区分提示词要求与 DistillAI 的候选设计。

2026-10-04：用户要求保存本地路由，后续不再在线查源码。本地副本已核对，后续入口见 [本地源码路由](README.md#本地源码路由)；本文件中的 GitHub 链接仅保留为来源标识。

## 核对到的设计

| 设计 | 已核对的要求 | 可借鉴部分 |
| --- | --- | --- |
| Deep Research | 先读当前材料，将研究问题拆为少量可搜索方面，在预算内搜索并读取主要来源，维护主张到来源的记录；稳定教材内容不要求机械搜索 | 概念扩展需要问题边界、来源和停止条件 |
| Curriculum Planner | 根据学习目标、学习者背景和材料规划课程序列，前课为后课的假定基础提供铺垫，跨课读取已实际生成的内容 | 根据任务目标控制扩展范围，不能只依据原计划推断用户状态 |
| Spiral Curriculum | 用少量核心理解组成概念脊柱，跨课增加复杂度、抽象度、关系密度、表征变化、迁移距离及边界反例 | 广度可体现概念关系，深度可体现机制、形式化、反例与迁移 |
| Feynman Learning | 学习者先解释，定位少量关键断点，通过追问、改写、类比边界与迁移复核 | 从用户解释中区分术语熟悉与机制理解 |
| Understanding by Design | 先确定持久理解及表现性证据，再设计活动 | 每个理解假设先明确什么表现能区分候选解释 |
| Zone of Proximal Development | 根据独立尝试判断困难，记录实际帮助，撤去关键提示后用新任务复核 | 自然验证时保留条件，避免提示后的完成被记为独立掌握 |

其中 Spiral Curriculum 明确要求教师侧记录概念遭遇史、已知关系、误解线索、掌握证据和下一次目标，同时说明平台不会替该 Skill 自动维护概念模型。规划语言也应与学生可见内容分开。这是概念发展与记录的设计指导，不能据此声称已实现“自动发现知识邻域 → 长期认知图 → 静默假设验证”的完整系统。

## 补充：掌握判断与 PBL 教学等级

用户继续要求核对单个知识的掌握程度。以下仍基于同一源码快照，补充读取 PBL v2 的等级内核、运行时信号、Instructor 调用点和任务评价提示词。

教学 Skill 的核心依据是用户实际表现：先观察独立尝试和理由，再定位困难；提供帮助后记录帮助条件，撤去关键提示后在新任务中复核。费曼策略关注解释中的因果断点与迁移。螺旋课程的初次接触、深化、整合/迁移标记用于规划课程，不能直接当作观测到的掌握等级。

代码另有 `beginner` / `intermediate` / `advanced` 三个 PBL 教学等级。它们保存在项目的 `proficiencyAssessment` 中，用来调整教学支持与难度，不是每个知识点各自的长期理解状态。

| 环节 | 已核对机制 | 边界 |
| --- | --- | --- |
| 初始化 | 用课程线索、背景与已有测验正确率形成起点 | 无证据时默认 intermediate 是教学策略，不是已验证掌握 |
| 动态更新 | 多种信号转换为方向及权重，通过指数加权移动平均更新分数 | 属于规则与平滑机制，不是已校准的掌握概率 |
| 等级切换 | 置信度、信号数量、冷却回合及不同升降阈值限制切换 | 可借鉴防止单次表现造成频繁跳级的思路 |
| 用户请求 | 显式自报或要求调整难度可以改变教学等级 | 自报与实际能力证据需分别处理 |

必须区分辅助函数与接通的运行路径：当前 Instructor 的 `record_observation` 使用 error、struggle、question，并调用 `trackObservation`。内核还支持 closing-check 质量、任务速度、提交评分等信号；本轮在 `lib/pbl/v2` 中未找到 `trackSubmissionScore` 或 `trackClosingCheck` 的调用点，不能据此声称这些信号都在当前路径自动更新等级。独立的任务评价 Prompt 对提交产物给出 0–100 分及改进建议；产物评价不自动等于概念掌握。

OpenMAIC 将 question 映射为较弱的负向求助信号。这种启发式服务于教学支持；DistillAI 不应据此把用户提问直接记为不理解。其 `confidence` 也是规则累计值，不是经过校准的统计概率。

补充来源：

- [等级内核](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/packages/%40openmaic/generation/src/pbl/operations/kernel/proficiency.ts)
- [动态信号](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/lib/pbl/v2/operations/runtime/dynamic-signals.ts)
- [Instructor 调用点](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/lib/pbl/v2/agents/instructor.ts)
- [任务评价提示词](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/lib/pbl/v2/prompts/evaluator-task.md)

## 对 DistillAI 的候选建议

会话提取仍只整理已有会话来源，外部概念发现作为独立职责：由会话中的概念生成先备、机制、用途及替代等候选关联，按当前任务筛选，再以教材或官方资料核对必要关系。初版可先扩展直接邻居，新的边界需求出现后再深化；不把未在会话出现的概念记成用户不懂。

领域知识关系与用户理解证据保持不同语义。图可以描述概念和假设的关联；用户是否理解仍需实际表现支持。验证选择同时考虑当前任务相关性、能否区分候选解释、对关键依赖的影响及打断成本，概念关联数量只作辅助。一个假设关联五个概念，不意味着一次验证能同时确认五个概念的掌握。

这些建议已进入 [初版开发 Discussion](../../spec/v0.1.0/4-initial-development/discussion.md)，尚未批准实现。

## 主要来源

- [Deep Research](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/deep-research/SKILL.md)
- [Curriculum Planner](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/curriculum-planner/SKILL.md)
- [Spiral Curriculum](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/spiral-curriculum/SKILL.md)
- [Feynman Learning](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/feynman-learning/SKILL.md)
- [Understanding by Design](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/understanding-by-design/SKILL.md)
- [Zone of Proximal Development](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/zone-of-proximal-development/SKILL.md)
