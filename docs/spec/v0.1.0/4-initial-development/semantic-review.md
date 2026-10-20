# 真实模型语义审阅：2026-10-20

本页供 M05-R2.2 的人工审阅使用，是 Agent 对实际保存记录的检查结果；不是用户已批准的验收结论。使用用户保存的 OpenAI 兼容协议配置 v2、deepseek-flash 与固定 Hermes AIAgent；没有使用预写模型回答。七组都是既有合成材料，不含个人会话。原准备 manifest、队列字节及失败任务保持不变。

## M05 七组对照

首轮基线共 82 次模型调用。补 schema / 单 JSON 围栏适配后的七组共 88 次：M04 全部成功，M05 五组成功、两组严格拒绝。随后按新 Prompt 发起明确的新认知验收请求，保留原失败的 10 / 12 次及其固定输入；不把重试当预算归零。

| 材料 | M04 / M05 次数 | 实际结果与 Agent 审阅 |
| --- | --- | --- |
| acknowledgement | 3 / 4 | 助手解释后用户说“明白了”；没有新增用户表现观察、理解假设或认知判断，没有据认可认定掌握。 |
| assisted-explanation | 5 / 6 | 保存用户对条件与分母关系的机制表述，明确助手刚给出步骤。判断支持受助条件下的解释，独立应用 / 迁移未知；没有要求先通过额外考试才保存这次表现。 |
| prompted-repair | 6 / 8 | 同一观察保留提示前用总人数作分母、引导后改为 B 群体人数；“偶发疏漏”和“机制未稳固”仍并存，没有把修正倒推成提示前已理解。 |
| counterevidence | 8 / 10（拒绝）；新 M05 9 | 原输出误把知识内假设 ID 放入外部 hypothesis_refs，被拒绝。新请求成功：对旧假设加入反观察，承认无即时提示的方法表述已出现，保留“没看示例”为自述、没有实际数值结果与迁移证据的范围；未宣布全面掌握。 |
| non-discriminating | 3 / 3 | 比较前后已提交记录，observations / hypotheses / cognition 均保持相同；时间经过没有触发分数、理解下降或编造新表现。 |
| grouping-only | 3 / 12（拒绝）；新 M05 5 | 原输出补取另一会话的表现却漏 episode_id，被严格归属校验拒绝。按正确依赖顺序补测后成功：observations / hypotheses / cognition 均与上一已提交状态相同，仅分组变化没有制造新表现或改变理解判断。 |
| single-analogy | 8 / 9 | 保存一条用户主动提出的数据库筛选 / 聚合类比，说明只对应操作先后、未展开或检验。知识关系作为待核查类比保留，未推出稳定思维习惯、独立应用、迁移或沿图掌握。 |

## 证据与限制

原七组准备清单为 `.artifacts/initial-development/semantic-acceptance-data/manifest.json`；补测逐组输入 / 输出 / Prompt 版本、来源 hash、任务 ID、次数及当时记录快照见 `.artifacts/twentyfirst-real-semantics.json`，两组进一步补测见 `.artifacts/twentyfirst-real-cognition-recheck.json`。这些本机证据保持忽略，不提交私有配置、原始运行日志或认证字段。

补测脚本曾缺 Windows spawn 的主入口保护，提前派生后一任务并冻结输入。修正入口后，该零调用失败沿原 ID 重试，正确保留了早先冻结输入，最终耗尽 16 次；没有把它改成成功或重置。最后明确登记依赖新反证据成功提交的补测请求，用 5 次完成；前一反证据成功任务没有再次生成。这些验收脚本及顺序问题，与前述产品结构拒绝分别保留。

上述材料固定 closed episode 后直接验证 M04 → M05；没有验证真实 Desktop 的切段、Hook 顺序、自然反馈和 compact。M05-R2.3、总体验收 A1.2 / A1.4 仍需相应实测。人工审阅需确认这些关于帮助条件、未决解释、反证据和单次类比的定性表述是否符合预期；不能以任务 succeeded 或 JSON 有效代替。

## M06 当前对照

首次对照读取了 SciPy rel_entr 主要来源，实际生成 7 次；输出将 open_questions 写成字符串，校验拒绝，未发布。程序已补现有 ExpansionRecord / ExpansionResult schema 与对象格式说明。

后续改用 SciPy entropy 主要来源，以获得 e-a 的实际关系原文并继续区分 e-b。keyless 搜索 / 提取前八次均返回 HTTP 429；第九次提取取得来源，但 300 秒探针期限内任务尚未结束，清理取消时已用 16 次，未发布、未交 M04 / M07。证据为 `.artifacts/twentyfirst-expansion-rate-limit.json`，不能据此勾选 M06-R2.3。保留该任务与次数，后续在上游条件允许时安排新的明确验收，不继续消耗已满预算任务。
