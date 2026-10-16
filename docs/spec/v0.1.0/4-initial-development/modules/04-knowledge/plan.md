---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M04：知识、关系与名称图 Implementation Plan

> 执行者使用 `executing-plans`，按本模块 checkbox 推进；默认主 Agent 实施。

## 来源与目标

依据[统一 Design M04](../../design.md#knowledge-contracts)及[总 Plan](../../plan.md)。维护独立知识 / 关系 JSON、可定位的实际来源和稳定 ID；通过确定性名称图提供精确 / 详情 / 一跳查询，不把用户判断放图属性。

## 文件映射

Create：`src/distillai/knowledge.py`、`src/distillai/prompts/knowledge.txt`、`tests/test_product_knowledge.py`、`tests/test_product_graph.py`。

Modify：`storage.py` 登记字段校验，`tools.py` 注册 `query_records` 并复用 M02 的 `read_source`，`runtime.py` 登记索引补建和后继任务，`server.py` 业务查询 / 编辑路由。沿用两个 example 的组织，但重新生成可真实解析的合成 fixture。

## Task 1：详情、身份、来源与字段归属

- [x] **Step 1：写最小有效 / 无效记录用例。** 知识至少 id / name、content.summary / source_refs；关系至少身份 / 端点 / kind / relation_type / direction_semantics、content.statement / source_refs。构造 ID / 文件不一致、引用缺失、主名冲突、别名多匹配和跨模块字段写入；expected_version 冲突由 M01 拒绝。
- [x] **Step 2：实现对变更后集合的校验。** 检查端点和显式关系属于该知识点，新增同批对象可以相互引用；来源通过 M02 / 外部版本 / 用户提交来源读取。不固定示例中的假设状态或关系类型枚举，relation_type 非空；record_status 省略 active、inactive 留历史。
- [x] **Step 3：实现 M04 字段权限。** M04 可维护内容、名称 / 别名、端点 / 关系核查、内容 provenance / changes；保留 M05 观察 / 假设 / cognition 及其 provenance。直接用户编辑只改 changes 指定字段，原因写历史；认知纠错交 M05。
- [x] **Step 4：建立维护输入 / 输出适配。** episode 使用固定 refs 与关闭 / 修订原因，外扩用 expansions refs，用户编辑用 record_kind / record_id / expected_version / changes / reason。结果 `knowledge_refs, relation_refs, reason` 只列真实差异，版本在提交后补齐，空列表正常成功。
- [x] **Step 5：运行详情组。**

```powershell
python -m unittest discover -s tests -p 'test_product_knowledge.py' -v
```

预期：`OK`；跨模块写入或失效来源拒绝，保留用户当前版本。

## Task 2：标准库名称图与公开查询

- [x] **Step 1：写查询矩阵。** 按以下返回契约断言，测试数据在临时目录生成而非复用 example 的虚构队列。

| 场景 | 预期 |
| --- | --- |
| 名称 / 别名 trim、忽略大小写 | 全部 `{id,name,version}` 匹配，别名歧义返回多个；无匹配空 |
| 详情已知 / 未知 ID | `{record,version}` / 明确未找到 |
| 相同端点两条独立关系 | 两条关系均保留，邻居去重 |
| 先备 / 因果 / 类比 | 方向按 Design，类比参照 → 尝试理解 |
| 对称一条关系 | in / out 两端均可发现，保留存储端点 |
| inactive、改名、无邻居 | inactive 不进有效图，改名 ID 不变，无邻居空 |
| 重建失败 | 一跳明确索引未就绪，详情仍可读 |

- [x] **Step 2：实现确定性索引。** 用标准库字典保存主名 / 别名映射、节点名、关系名及两端；关系 ID 为连接身份，入 / 出邻接支持有向多关系。正文、来源、理解不进入属性；不引入图数据库 / Graphify / TS Graphology。
- [x] **Step 3：实现查询返回。** 精确匹配不做模糊 / 向量召回；一跳 direction 默认 both，邻居去重、关系附 refs / 两端、按 ID 排序，默认不截断。读取已提交快照，绑定返回内容的版本，不能用当前详情替换历史引用。
- [x] **Step 4：实现全量重建 / 补建。** 启动和知识 / 关系提交后从已提交集合构建新索引，完成才切换，期间不暴露半成品；失败保留提交和补建待办。模型任务不因索引失败重跑，旧图不冒充最新；实际规模慢再优化。
- [x] **Step 5：运行图组。**

```powershell
python -m unittest discover -s tests -p 'test_product_graph.py' -v
```

预期：`OK`；清除派生索引后重建仍得到相同稳定查询结果。

## Task 3：AIAgent 内容维护与后继

- [x] **Step 1：发布 P03。** P01 + P03 + 固定输入 / 最小已有记录，注册快照 query_records / read_source，Agent 按需读取原文并直接编辑副本；会话提取不注册外部搜索，不从常识补未讨论知识。
- [ ] **Step 2：接入三类维护和语义审阅。** 合成场景覆盖同义归一、同名异义、来源冲突、用户联想未核查、修订后失去部分支持、inactive 与空结果。核对实际出处 / 条件 / 角色；事实 / 同义由 Agent 判断，程序不以关键词机械判成立。
- [x] **Step 3：发布后触发依赖。** episode 分析成功后交 M05 原 episode / 版本 / 来源及维护结果，包括空；M04 相关详情变更为直接依赖它的开放 episode 登记 M07 准备，不等材料周期，也不加材料更新计数。用户编辑和外扩结果复用相同提交 / 图补建入口。
- [x] **Step 4：验证编辑和重建恢复。** 故意制造索引失败后读取已提交详情，再补建；核对仅补索引，不新增模型调用和重复业务版本。同期用户编辑返回冲突而非被模型覆盖。

## 测试必要性、依赖与状态

永久组保护来源 / 身份 / 端点、字段归属、有向多关系、精确查询与索引就绪错误；M01 已测发布恢复，不重复私有存储步骤。语义归一、事实核查、规模性能与模板字段布局做一次性验证，不锁定节点 / 示例数量。

依赖 M01 + M02 + M03；M05 / M07 交接在本模块验证。标准库图是最小实施建议，满足既有契约才采用，不新增业务规则。2026-10-13 用户授权按当前 Plan 开始实施，本 Plan 已批准；完成状态按 checkbox 与执行记录核对。

## 执行记录

### 2026-10-15：详情约束、名称图与 episode 维护

已实现 knowledge.py / P03，校验 ID / 文件、有效主名唯一、别名多匹配、内容及队列来源、同批新增端点和显式关系归属；M04 保留 observations / hypotheses / cognition / hypothesis_refs、对应 provenance 及既有 changes。任意非空 relation_type 合法，未核查用户联想可保留，inactive 关系保留历史而不进有效图。新 ID 经运行中的知识任务调用 new_record_id，由控制层生成并记入任务；不接受模型自行编造的新 ID。

名称图以标准库字典和入 / 出邻接保存节点 / 关系名称、ID、字节版本及两端；没有正文、来源、观察或理解属性。同端点多关系保留，邻居去重，按 ID 排序。对称采用 symmetric=true 并保留 source / target，in / out 均可发现。主名 / 别名 trim、忽略大小写精确匹配，详情支持历史版本，未知 ID 明确未找到；索引失败一跳 / 名称查询返回 index_not_ready，详情仍可读取。

启动和提交后全量构建新图，完成才切换，不开放半成结果。修复了 M01 后置登记失败会阻止后台恢复的缺口：已 committed 任务保留 validating / post_registration_pending，后台可继续提供 API，轮询只补后置登记，不重跑模型 / 业务发布。永久回归已验证索引失败后的详情读取、启动恢复保留待办、补建成功和原模型执行次数不变。

episode 维护使用固定关闭记录及原材料，实际读工具按快照授权，无外部搜索；输出仅列真实差异，程序补版本，空结果也登记 M05。新增只读 API：/v1/knowledge/lookup、/v1/knowledge/<id>/neighbors、/v1/records/<knowledge|relation>/<id>，统一使用 M01 控制授权。三类维护中的外扩 / 用户编辑、外部 / 用户提交来源读取和 M07 直接依赖刷新尚未接入，相关步骤保留未勾选。

真实 AIAgent 的 M03 → M04 合成链路已完成：M04 7 次生成，三个程序 ID、两个知识点和一条未核查联想关系按实际源行发布，图查询成立，登记一个 M05 待办。该验证证明库 / 工具 / 版本衔接；同义、事实核查等语义对照尚未执行收费模型 / 人工审阅。

本模块完成 Task 1 Step 1 / 5、Task 2 全部、Task 3 Step 1，共 8 / 14；不标 implemented。规模上暂冻结所有已有详情供快照读取，实际任务接近 8 MiB 子进程输入上限时再收窄按需载荷，不增加索引服务或依赖。

### 2026-10-15：三类输入、用户编辑与索引恢复

已补齐 external / user_submission 版本来源读取、M04 三类维护输入及指定字段编辑。用户提交用独立不可变来源，expected_version 过时在登记、开始 / 生成和提交前拒绝；正文编辑只改指定字段，程序追加原因与来源历史，观察 / 假设 / 理解及其他字段保留。`POST /v1/knowledge-edits` 返回任务登记阶段，不能冒充保存；空变化不制造业务版本。外扩结果只能引用已发布 expansions refs，正常交同一提交 / 索引 / M07 依赖路径，外部结果或用户内容编辑自身不登记掌握分析。

实际 AIAgent + 真实免 key Tavily 的外扩 5 请求 → M04 3 请求 → 用户编辑 3 请求探针退出 0，历史版本可读，e-b 的未核查状态保留，用户理解未被改写；模型响应为合成 localhost。永久知识组 9 项通过，新增索引失败后已 committed 详情仍可读取、只补建不重跑执行 / 不重复业务版本的回归。

Task 1 Step 2–4 与 Task 3 Step 3–4 完成，当前 **13 / 14**。Task 3 Step 2 的完整语义对照仍未验收，见[执行待办](../../pending.md)。
