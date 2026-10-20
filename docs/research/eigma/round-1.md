# Eigma：Agent 提取、个人 Wiki 与复习（2026-10-02）

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

本轮调研告一段落。核对范围为官方产品文档与本地 `E:\JourneyIntoAI\DL_and_LLM\projects\eigma-mcp`，本次读取的仓库 HEAD 为 `c6ed77784300fc11c65772de7cc4d136b55a4f62`。该仓库公开工具说明、参数结构、共享提取规则、Skill 与示例服务，不是完整 Eigma 产品；托管 MCP 服务与记忆衰退计算实现未包含其中。本轮没有连接个人 Eigma 账号或进行真实保存、测验，以下区分公开契约、产品文档说明和对 DistillAI 的候选参考。

## Codex 接入与职责划分

Codex 通过远程 MCP 地址 `https://my.eigma.app/api/mcp` 和 OAuth 接入 Eigma。当前 Agent 根据用户请求、服务 instructions 与工具说明决定是否调用工具；只连接 MCP 不代表每轮会话都会自动上传，也不等于存在独立后台 Agent 静默分析全部会话。

按公开保存流程，当前 Codex Agent 完成主要语义工作：筛选值得学习的概念，撰写标题、分类、摘要、Markdown 正文、关联链接与测验题；Eigma 提供已有页面匹配、读取、审核收件箱、知识管理、检索与复习状态服务。“当前 Agent 完成提取”不代表模型推理运行在用户本机。托管产品是否还有其他模型处理，本次公开材料不足以确认。

```text
用户请求整理会话 → 当前 Agent 按 Eigma 规则起草完整知识页
  → eigma_resolve_pages：批量检查已有页面与章节
  → 若更新已有页面，eigma_read_page：读取旧正文并合并
  → eigma_save_notes：提交知识页与会话来源摘要
  → Eigma 审核收件箱 → 用户接受 → 进入 Wiki

后续问题 → Agent 按需搜索、读取 Wiki → 工具结果进入上下文 → 回答
复习任务 → Eigma 读取与答题记录 → 计算记忆状态 → 展示待办与测验
```

更新已有页面时，保存会替换正文，因此 Agent 必须发送完整合并后的内容，不能只发送增量而丢失旧知识；针对已有页面的修改另有 `eigma_suggest_edits`，同样进入用户审核。不能把公开示例服务使用 `Map` 的行为当作生产存储实现。

参考：[接入与仓库范围](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/README.md)、[保存及更新流程](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/skill.ts)。

## 如何指导当前 Agent 提取知识

Eigma 的规则通过 MCP 初始化的 `instructions`、工具 `description`、参数字段说明，以及支持 Skill 的 AI 工具可加载的 `eigma-filing` 提供给 Agent。OpenAI 文档说明 Codex 会结合服务 instructions 和工具元数据使用工具；不应据此推定所有 AI 工具都以同一种提示词层级加载规则。

规则主要规定：保留长期有学习价值的概念、机制、原理与关系，过滤临时安排及查询型琐事；标题使用规范概念短名称；摘要写一行简短概括；正文依据当前对话组织导语与章节，不自行填充未讨论的知识；链接相关的新旧页面；更新前检查已有内容；题目考查原因、条件变化和应用。共享规则集中在 `src/rules.ts`，再组合进服务 instructions、工具说明与 Skill，减少多个渠道之间的规则漂移。

这些规则提供一致的提取标准，但不保证语义判断正确。字段说明中的自然语言要求也不等于程序强校验；公开输入结构有容错设计，不能把“调用成功”当作“页面质量合格”。用户审核是内容进入 Wiki 前的一次检查。

参考：[提取规则](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/rules.ts)、[字段契约](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/ingestSchema.ts)、[OpenAI MCP instructions 说明](https://developers.openai.com/plugins/build/mcp-server)。

## 提交内容与知识存储

保存参数包含 `nodes` 与 `conversation`。每个知识页可携带 `title`、`category_path`、`summary`、`body_md`、`tags`、`links`、`quizzes`；其中 `body_md` 是 Agent 整理的 Markdown 知识正文。`conversation` 的公开契约仅保留来源会话的标题、日期和一行摘要，并明确要求不要发送逐字记录。因此，这条路径保存的是知识结果与来源概括，不能用它恢复原始对话中的全部推理、纠正过程与工具证据。

与 LLM Wiki 构想相似，Eigma 的知识正文采用 Markdown；但 Markdown 内容格式与底层持久化方式要分别看。官方页面文档描述桌面形式可使用普通 Markdown 文件目录，浏览器形式使用设备上的浏览器存储，登录增加云端备份和跨设备同步。不能概括成“数据全部只存服务器”，也不能从 MCP 示例服务推断云端一页对应一个 `.md` 文件。官方页面文档和 FAQ 对原生应用的可用性表述不同，本轮不判断其发布状态。

参考：[保存输入与来源摘要](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/ingestSchema.ts)、[页面与 Markdown 存储说明](https://eigma.app/docs/pages/)、[本地与云端备份说明](https://eigma.app/faq/)。

## 待读、待测与衰退

Eigma 根据阅读记录、答题结果和时间衰减，将当前知识卷中的页面分为三个互斥的待办组。这些是学习与复习任务分类，不是用户理解程度的三个等级；已完成测验且尚未衰退的页面可以不在这三个组中。

| 状态 | 判断依据 | 对应任务 |
| --- | --- | --- |
| 待读（`to_read`） | 页面从未打开 | 先阅读知识页 |
| 待测（界面称 `to_recall`；MCP 返回称 `to_test`） | 页面已打开，但仍有测验题未回答 | 通过作答取得回忆证据 |
| 衰退（`fading`） | 页面测过，但上次答错，或经过时间衰减 | 重新复习与测验 |

官方说明中，记忆状态由设备上的规则计算，不需要 LLM 判定。当前回忆概率随时间下降，记忆持久度决定下降速度，并由正确作答提高；隔一段时间再次答对与连续重复作答的作用不同。重新阅读只能恢复部分状态。Agent 补充或改写页面后，页面状态也会略微回退，使其更早重新进入复习。

需要区分实际证据与预测：答错是已观察到的作答表现；时间衰减是对当前回忆能力的估计，标为 `fading` 不表示已通过新测验证实用户忘记。公开文档未披露完整函数、参数更新方法与触发阈值，公开 MCP 仓库也不含该实现，不能确认采用 FSRS、SM-2 或某种具体衰退曲线。准确结论是“本次未找到模型公开实现”，而非断言其在所有地方都未开源。

参考：[记忆状态与衰减说明](https://eigma.app/docs/memory/)、[MCP 复习列表](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/toolSpec.ts)。

## 复习题型与反馈

Agent 提交页面时生成测验题；当前 MCP 提取规则要求每页 1–3 道，产品页面可以继续添加题目。Eigma 的测验采用客观题，全部通过选择作答：`mcq` 是四选一单选题，`cloze` 是留空句子配四个候选项，`truefalse` 是判断题。这里的填空不是用户输入文本，也不是开放解释题。

规则要求每题只考一个知识点，脱离正文也能理解题意，考查原因、机制、条件变化或应用；避免仅复述标题与定义，干扰项应合理，选项长度不应泄露答案。答题后可显示解释。产品说明中，用户点击 `Start quiz`，题目按上次答错、从未回答、已衰减、最近答对的顺序优先呈现；题目共享页面的记忆持久度，页面要遍历全部题目才会被计为已内化。此产品指标不等同于对完整概念理解与迁移能力的证明。

示例题型仅用于理解规则：“同一次坐下来连续答对五遍，与隔几天后再次答对，对持久度的提升相同。”这是判断题，按文档机制答案为错；此例为本次生成的示例，不是 Eigma 实际调用结果。

参考：[测验生成规则](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/rules.ts)、[页面测验操作](https://eigma.app/docs/pages/)、[测验排序与状态更新](https://eigma.app/docs/memory/)。

## 调研结论与对 DistillAI 的参考

Eigma 可作为“Agent 按统一规则提取知识 → 用户审核知识页 → 显式作答取得证据 → 更新记忆状态 → 再复习”的流程参考。值得保留的是知识页与用户状态分别处理、提示规则集中维护、三个复习待办组，以及区分已观察到的答题表现与预测衰退。

DistillAI 还关注日常会话中用户为何这样判断，以及如何形成竞争假设、取得新证据并修正理解状态；本次资料未展示 Eigma 已完成这一流程。原始会话仍需单独保留。客观题便于评分和记录，开放解释或独立应用可提供更丰富的推理证据，两类证据可以按验证目的选用。

当前 DistillAI 仅有会话 Hook 数据，尚无知识页阅读与测验记录，不能直接计算 Eigma 式复习状态；未测不等于不懂，衰退不等于概念理解错误。上述机制保留为后续设计参考，尚未决定接入 Eigma、采用其状态模型或实现复习功能。本轮不继续追查未公开的衰退算法。
