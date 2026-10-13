# OpenMAIC 调研

| 元信息 | 地址或范围 |
| --- | --- |
| 本地仓库 | `E:\JourneyIntoAI\DL_and_LLM\projects\OpenMAIC` |
| GitHub | [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) |
| 本地核对版本 | `c72a64b4b669608bd682ae561bea0e059710930a` |
| 本地副本 | Git 浅克隆；当前提交的源码可读，历史范围有限 |
| 最近本地核对 | 2026-10-04；origin 与上述 GitHub 仓库一致，工作区干净 |
| 首轮核对范围 | 固定源码快照中的教学 Skill 和运行时代码；未启动课堂 |
| 首轮主要核对时间 | 2026-10-02 |

## 本地源码路由

下列路径均相对于本地仓库 `E:\JourneyIntoAI\DL_and_LLM\projects\OpenMAIC`。后续源码核对直接读取本地文件；GitHub 链接保留为来源标识。

| 要核对的内容 | 本地入口 |
| --- | --- |
| 项目介绍 | `README-zh.md` |
| 外部搜索、来源核对与搜索停止条件 | `skills/agent-runtime/deep-research/SKILL.md` |
| 系列课程与学习路径 | `skills/agent-runtime/curriculum-planner/SKILL.md` |
| 概念关联、深化与跨课记录 | `skills/agent-runtime/spiral-curriculum/SKILL.md` |
| 用户解释、因果缺口与迁移 | `skills/agent-runtime/feynman-learning/SKILL.md` |
| 理解目标与表现性证据 | `skills/agent-runtime/understanding-by-design/SKILL.md` |
| 独立尝试、帮助条件与后续验证 | `skills/agent-runtime/zone-of-proximal-development/SKILL.md` |
| Skill 的运行时加载 | `lib/server/agent-runtime/skills.ts` |
| 课堂角色与调度 Prompt | `lib/chat/pi/prompts.ts` |
| PBL 教学等级内核 | `packages/@openmaic/generation/src/pbl/operations/kernel/proficiency.ts` |
| PBL 动态信号 | `lib/pbl/v2/operations/runtime/dynamic-signals.ts` |
| PBL Instructor 调用点 | `lib/pbl/v2/agents/instructor.ts` |
| PBL 任务评价 Prompt | `lib/pbl/v2/prompts/evaluator-task.md` |

## 各轮调研简短结论

### 第 1 轮 · 已完成

- 教学 Skill 提供最近发展区、费曼学习法等验证策略，强调根据用户真实作答判断困难，并记录提供的帮助。
- 独立完成、提示后完成及撤去提示后在新任务中的表现需要分别记录；适配日常工作时可先使用一次与当前任务相关的小验证。
- 可借鉴教学 Prompt 和证据规则；本轮未启动课堂，所查代码也不足以证明它已自动维护独立的长期用户认知模型。

详细过程、源码与实测依据：[第 1 轮调研记录](round-1.md)。

### 第 2 轮 · 概念扩展与认知边界专题 · 已完成（2026-10-04）

- Deep Research 提供有边界的外部搜索与来源记录；螺旋课程提供概念关系、机制深化、反例及迁移维度。
- UbD 与最近发展区策略要求先定义表现证据，区分独立完成与受助完成。
- 螺旋课程明确平台不自动维护概念模型；上述 Skill 不足以证明完整的自动认知图与静默验证链路。
- 本轮核对与首轮相同的固定源码快照，未启动课堂。DistillAI 的概念扩展与轻量图仍是候选设计。
- 补充核对 PBL v2 的初级 / 中级 / 高级教学等级：多种信号通过平滑与切换门限调整项目难度；它与单个概念的理解证据不同，部分信号辅助函数未在当前 Instructor 路径找到调用。

详细过程与来源：[第 2 轮专题记录](round-2.md)。
