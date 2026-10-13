# DistillAI 调研综述

| 元信息 | 当前状态 |
| --- | --- |
| 文档更新日期 | 2026-10-13 |
| 最新完成轮次 | 后台运行技术专题第 4 轮最新源码 / 同维度比较；既有第 2 轮专题（Eigma、OpenMAIC、Honcho）保留 |
| 第 1 轮完成日期 | 2026-10-02 |
| 当前阶段 | Issue #4 八模块 Design 已合并；2026-10-12 用户确认 Hermes AIAgent / Python 与独立任务进程，完成九项 grill 决定；2026-10-13 总 Plan / 八模块草案已创建。统一 Design / Prompt 与各 Plan 批准状态仍以 Spec 为准，搜索后端延后，尚未安装或验证集成 |

## 调研范围

当前产品决定见[统一 Design](../spec/v0.1.0/4-initial-development/design.md)与[总 Plan](../spec/v0.1.0/4-initial-development/plan.md)。下述各轮是当时的事实与候选，不将已被替代的框架比较结论当作当前待选项；本次归档没有新增调研轮次或运行证据。

2026-10-09 增加[后台运行技术专题](runtime/README.md)，核对 Pi、Microsoft MXC、Anthropic sandbox-runtime 与 Windows 文件 / 进程平台文档。该专题支撑 M01 技术方案，不改变下面七个产品调研对象的历史范围；本轮未下载仓库或安装依赖。

2026-10-10，该专题第 2 轮补充统一 Design 的 SDK 资源控制、Graphology、MCP v2、Hook、Node 文件句柄适配及外部搜索路线；只核对公开文档，没有新增集成实测。

同日第 3 轮按用户要求比较 DeepSeek Harness、Claude Agent SDK、Codex SDK、OpenAI Agents SDK、Pi、Deep Agents、Hermes；以只限写的沙箱口径比较现成能力与框架厚度。采用官方文档及本地 Codex / Hermes 快照，优先保留 DeepSeek / Pi 对照；随后补核 Hermes 官方 Python Library 与当前原生 Windows 支持，撤回旧快照导致的 WSL2 限制结论，保留 Python 嵌入候选。框架与语言未选。它是执行技术专题，不改变下述七个记忆 / 知识产品的历史范围。

同日第 4 轮按用户要求聚焦 DeepSeek Harness、Pi、Hermes SDK / Library，并纳入后期本地 LLM 服务。经授权下载三个最新默认分支，记录固定 HEAD / 发布版本，比较程序接入、联网工具、Windows 写隔离、资源控制、安装负担和预算 / 中断。完整结果交由用户选型；其他四个框架只退出本轮重点范围，不记为正式排除。

首轮已形成记录的对象为 Graphiti、Mem0、Letta、Honcho、Eigma、LLM Wiki，以及补充教学验证参考 OpenMAIC，共七个调研对象：六个记忆与知识方向，加一个教学参考。

按调研对象统计范围；Zep 文档、Letta Code、codex-honcho 和 LLM Wiki 的实现仓库属于对应项目的核对材料，具体仓库与验证范围见各项目 README。项目被列举、作为候选或存在本地目录，都不足以记为已完成专项调研。

已有本地副本的项目直接按其 README 路由核对源码。OpenMAIC 已在 `E:\JourneyIntoAI\DL_and_LLM\projects\OpenMAIC`，路径、核对提交与主要入口见 [OpenMAIC 本地源码路由](openmaic/README.md#本地源码路由)。

## 调研轮次

| 轮次 | 时间 | 状态 | 目标与结果 |
| --- | --- | --- | --- |
| 第 1 轮 | 2026-09-29 至 2026-10-02 | 已完成 | 核对采集、后台提取、持久化、检索回注及理解验证的机制，形成项目记录与 DistillAI 候选流程 |
| 第 2 轮专题 | 2026-10-04 | 已完成（Eigma、OpenMAIC、Honcho） | 核对概念扩展、表现证据、学习状态、教学等级及 Hook 采集时序与文件；[Eigma](eigma/round-2.md)、[OpenMAIC](openmaic/round-2.md)、[Honcho](honcho/round-2.md)，未运行账号、课堂或 Honcho 集成 |
| 后台运行技术第 1 轮 | 2026-10-09 | 文档核对完成，集成未验证 | [Pi RPC、MXC、Windows 版本及文件恢复](runtime/round-1.md)；用户认可非 Agent 接入方案及任务副本写回，Agent 接入在全模块 Design 写完后确认 |
| 后台运行技术第 2 轮 | 2026-10-10 | 文档核对完成，集成未验证 | [Node / Pi SDK、关联技术与搜索](runtime/round-2.md)；用户选择 Node / TypeScript + Pi SDK，其余提案见统一 Design |
| 后台运行技术第 3 轮 | 2026-10-10 | 文档 / 本地快照核对完成，集成未验证 | [七框架比较](runtime/round-3.md)；用户重新开放框架与语言，沙箱只限制写入，搜索服务延后确认 |
| 后台运行技术第 4 轮 | 2026-10-10 | 最新源码 / 同维度比较完成，集成未验证 | [DeepSeek / Pi / Hermes](runtime/round-4.md)；三个最新默认分支已下载，纳入本地 LLM、框架控制范围及补充成本，由用户决定最终选型 |

第 2 轮覆盖 Eigma 的掌握判断、OpenMAIC 的概念扩展、认知边界与 PBL 教学等级，以及 Honcho / codex-honcho 的 Hook、同步与异步边界、队列和游标文件。Honcho 的采集插件经用户授权下载后在本地核对；其他项目仍以首轮记录为准。

## 第 1 轮结论

### 项目覆盖与主要结论

| 调研对象 | 本轮核对到的主要机制 | 对 DistillAI 的参考 | 核对范围 | 复盘入口 |
| --- | --- | --- | --- | --- |
| [Graphiti / Zep](https://help.getzep.com/context-types) | Graphiti 接收 episode，提取实体与时序关系，再提供检索；接入方安排采集和回注 | 原始事件与派生图谱分存、关系的时间变化与来源关联 | 专项为 Graphiti 的文档和代码；Zep 服务仅作概览，不将两者能力混用 | [各轮结论](graphiti/README.md) |
| [Mem0](https://docs.mem0.ai/core-concepts/memory-operations/add) | Hook 采集与批量提交，后台模型提取，去重追加，再按需检索回注；核对的默认 `add()` 不自动覆盖旧记忆 | 采集、独立语义分析、保存和前台使用的完整链路 | 公开代码与 Codex 插件；云端私有模型和提示词未确认 | [各轮结论](mem0/README.md) |
| [Letta](https://docs.letta.com/agent-sdk/memory) | 常驻记忆与按需资料分工；后台 reflection 对照已有记忆做修订；MemFS 保存 Markdown，Git 管版本和合并 | 少量当前状态供前台使用，详细证据按需读取；后台整理可独立运行 | 文档与 Letta Code 源码；另实测 Letta Code v0.33.6 的一条记忆生命周期 | [各轮结论](letta/README.md) |
| [Honcho](https://github.com/plastic-labs/honcho/blob/main/docs/v3/documentation/core-concepts/reasoning.mdx) | 原始消息入库，Deriver 提取明确事实，Dreamer 做进一步演绎、归纳与整理，Dialectic 按问题查询用户表征 | 事实、推断及来源链分别保存，后台持续修正用户表征 | Honcho 与 codex-honcho 的文档和代码；文档能力概述以具体调用路径限定 | [各轮结论](honcho/README.md) |
| [Eigma](https://eigma.app/) | 当前 Agent 按统一规则起草知识页和客观题，用户审核后入 Wiki，再通过阅读、测验与时间衰减安排复习 | 知识内容与学习状态分别处理；实际答题表现与预测衰退分别记录 | 公开 MCP 契约和产品文档；未连接账号或实测，衰退模型实现未公开于所查资料 | [各轮结论](eigma/README.md) |
| [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | compiler 编排概念抽取与增量页面生成；llmwiki 通过 guide 和 MCP 指导外部 Agent 维护 Wiki | 跨来源综合同一概念、保留引用、按来源变化确定更新范围 | 原始构想及 atomicstrata/llm-wiki-compiler、lucasastorian/llmwiki 的固定源码快照；未运行验证 | [各轮结论](llm-wiki/README.md) |
| [OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) | 教学 Skill 指导课程生成，课堂角色组织解释与问答；最近发展区等策略要求依据真实作答检验理解 | 先定义证据，再选择小验证；记录提示程度，并用新任务检查独立应用 | 固定源码快照中的教学 Skill 和运行时代码；未启动课堂 | [各轮结论](openmaic/README.md) |

### 跨项目得到的共同认识

采集、语义分析、存储和前台使用是各自需要安排的环节。Hook 或应用代码可以自动交付事件，MCP 提供可调用工具，SDK 提供程序接口；接口形式本身不决定是否静默运行，也不保证每轮自动写入或检索。自动更新知识库同样需要明确的材料入口、整理任务和触发者。

“保存什么、怎样综合”主要由提示词与 LLM 判断；游标、批次、去重、引用校验、版本与重试由程序处理。两类规则共同完成流程。格式正确、工具调用成功、引用能定位、模型自评置信度高，都不能单独证明语义结论正确。

知识表征可以是图谱，也可以是持续维护的 Markdown 页面；预先编译 Wiki 后仍可以检索。选用图数据库、向量库、普通文件或 Git，应由后续的查询和维护需求决定。Git 在 Letta 等方案中用于派生记忆的版本管理，与用 Git diff 发现原始会话事件是不同职责。

本轮核对的公开流程没有展示 DistillAI 所需的完整闭环：保留关于用户理解方式的竞争假设，取得能区分它们的新用户证据，再支持、削弱或替换判断。Honcho 提供后台推断的参考，OpenMAIC 提供验证策略的参考；两者的机制仍需针对日常工作会话适配和验证。

## 复盘与后续记录

- 快速复盘：从本综述进入各项目 README，查看每轮简短结论，再按需读取 `round-N.md` 中的过程、来源和验证范围。
- 新一轮调研：在实际调研的项目目录增加 `round-N.md`，并在其 README 追加该轮结论；同步更新本综述的范围、轮次及状态。
- 项目设计：调研结论转入 DistillAI 的待决设计时，记录在 [初版开发 Discussion](../spec/v0.1.0/4-initial-development/discussion.md) 中，随后续架构设计与产品原型一起提交。
