---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M04：复用 NetworkX，保留知识与版本契约 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、复用与文件

依据[统一 Design M04](../../design.md#cognitive-map-model)及[总 Plan](../../plan.md)。JSON 详情和来源仍为权威，图为名称 / 连接索引；将手写邻接结构交给 NetworkX，继续复用现有知识校验、维护和查询业务方法。

Modify：`src/distillai/knowledge.py`、`tools.py` 的图快照读取适配；`pyproject.toml` / `uv.lock` 由 M01 统一登记 NetworkX 依赖。复用 `tests/test_product_graph.py` / `test_product_knowledge.py`。不增加图服务、图数据库、向量检索或 Graphify；本稿没有执行 `/graphify`。

## M04-R1：使用现成有向多关系图

- [x] **R1.1 保留公开查询测试。** 先跑已有图组，覆盖 trim / casefold 名称、别名多匹配、同端点多关系、in / out / both、对称关系、inactive、改名 ID 不变、未知记录和 index_not_ready。图类更换不修改结果 schema 或改成模糊查询。
- [x] **R1.2 替换邻接维护。** `KnowledgeIndex.rebuild` 使用 `networkx.MultiDiGraph`，知识 ID 为 node，关系 ID 为 edge key；只放名称、版本和端点等现有索引字段。名称 / 别名精确字典继续用于领域匹配；不再维护第二套 in / out sets 或复制 NetworkX 遍历代码。
- [x] **R1.3 保留方向语义。** 非对称关系只存 source→target；对称关系可在内存图用相同关系 ID 作双向索引，权威 JSON 仍一条。读取 in / out 边后按关系 ID 去重、邻居按知识 ID 去重并排序，自环也只返回一份关系；不同关系 ID 不能因端点相同合并。删除手写图结构后检查所有上下文消费者。
- [x] **R1.4 重建原子切换。** 从已提交详情集合构建临时图，完整成功再切换；失败明确索引未就绪，详情 / 历史版本仍能读取，原补建待办只补索引、不重跑模型 / 业务提交。不借机改变文件格式或业务记录 ID。
- [x] **R1.5 对照结果。** 用现有合成 fixture 比较替换前后公开查询结果，再扩展原组中遗漏的对称自环 / 多边重复路径（只有现有组遗漏才新增）。一次性记录清空索引后重建和代表规模耗时，不做固定节点数 / 代码行数永久断言。

## M04-R2：复用三类维护与实际语义审阅

- [x] **R2.1 复跑详情与字段权限。** 知识 / 关系 ID、来源、端点、同批引用、主名冲突、版本冲突沿原校验；M04 不覆盖 M05 的 observations / hypotheses / cognition。用户编辑只修改 changes 指定字段并留提交来源 / 原因，原材料只读。
- [ ] **R2.2 复跑真实执行链。** episode、外扩、用户编辑继续用原适配 / P03 / Hermes 文件工具；`query_records` 沿图和详情 Python 方法，`read_source` 沿来源解析，不把数据查询变成第二个 Agent。空结果成功仍交 M05 原 episode；提交后补图 / 直接依赖的 M07 准备沿现有登记。
- [ ] **R2.3 审阅语义与恢复。** 获准实际模型验证同义归一、同名异义、来源冲突、用户联想未核查、修订后丢部分支持、inactive / 空结果。另复跑图构建失败和同期编辑，确认可读已提交详情、补建不重算、不覆盖编辑。保留原文版本 / 理由，不能把格式校验通过当语义正确。

## 验证与依赖

```powershell
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_graph.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_knowledge.py' -v
```

预期各 `OK`；本轮未执行这些命令。永久组保护结果与数据关系，不断言 NetworkX 私有结构。依赖 M01 项目环境 / SDK 接入、M02 来源与 M03 固定 episode；M06 / M07 共享同一图入口。引入 NetworkX 的理由是删除已有手写多边 / 方向维护，不能为了依赖而新增图算法。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第一批重构证据

项目 uv 环境完成锁定安装，PM Python 3.14.7 / 固定 Hermes SHA 的 AIAgent 导入检查退出 0；产品环境与任务环境已拆开。FastAPI / Uvicorn 接管 HTTP，显式路由复用原业务；API / Web 以官方 TestClient 和 dependency_overrides 运行。旧 Handler、模型代理、HTTP 程序工具入口及任务 proxy token 已删除；请求历史脱敏转到执行适配。

SQLite 已接管任务、去重键 / 别名、依赖、attempt / 次数、提交清单和配置指针。原存储崩溃 / 冲突测试改走数据库；真实写锁超时测试验证未发送模型、停树可结束、业务不可读、重启恢复。离线迁移工具通过合成副本的完整备份、重复核验、预算保留、零新写入回退和新增 Hook 材料后拒绝回退；没有迁移真实数据。修复源读取中新建 Store 重入文件锁的死锁，现有纠错组复跑通过。NetworkX 替换手写邻接；Portalocker / pathvalidate / boltons 替换普通锁、路径词法和单文件保存，Loguru 记录白名单采集诊断。

TaskPipe 采用标准库认证 AF_PIPE / send_bytes / recv_bytes；阻塞 accept / 认证由归任务 Job 的通信进程持有，公开 Process 终止 / join 提供有界回收，不遗弃等待线程。连接前、认证未完成、错误密钥、断开和正常往返已在实际 Windows 通过；跨 PM 主调用与父进程程序工具通过。实际 AIAgent 新探针七场景通过：screening 1、query 2、source 2、文件 / Shell 维护 3、503 恢复 3、第 16 次有效完成 16、第 17 次拒发 16。发现 SDK 将任意发送钩子异常包成连接错误而重试；窄 HTTPX send 适配在额度拒绝时返回本地 400，不发送请求，重跑通过。模型请求编码 / TLS / SSE / 解析 / 模型循环仍由原 SDK 执行。

当前完整产品组 178 tests / OK（39.739s）；Ruff、uv lock --check --offline、git diff --check 退出 0。新增 SDK 组 4 项与 IPC 组 3 项，旧 HTTP 代理用例移至新 SDK 契约覆盖；没有为删除名称写断言。证据在 .artifacts/after-direct-all.log、direct-hermes-probe.log、direct-hermes-results.json 和 probe_state_migration.py。尚未完成全部 M01 / G1：模型参数探针、父进程死亡 / 大消息等完整 IPC 窗口、剩余通用能力、真实模型与 Desktop / 搜索新组合仍需后续证据。没有 Commit / Push 或远端写入。

## 2026-10-17 恢复后第三批：Windows、管道与到期恢复

补原图组遗漏的对称自环与双向多边组合，按稳定关系 ID 返回一次，方向 / 端点与邻居去重不变，图组 5 项通过。一次性 500 知识点 / 1000 关系与 HEAD 旧实现比较 90 组公开邻接查询及精确名 / 别名，新实例重建一致；旧 / NetworkX 温重建耗时 1.7220s / 1.6981s，仅记录规模，不据此声称显著性能提升。

详情 / 来源 / 同批端点 / 主名 / 版本冲突、M04 指定字段编辑和 M05 字段保留沿现有组复跑通过。完整产品 192 项通过，实际 AIAgent 文件 / Shell 维护随新 Windows 绑定再次通过；完整语义与 episode 真实执行链仍有未验范围。证据 .artifacts/third-graph-results.json，详见[总 Plan](../../plan.md)第三批。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

记录 / 关系元数据、维护结果和用户编辑参数复用本模块严格模型，共用 SourceRef / RecordRef 与 ID / 版本类型；新 ID 工具参数由同一模型生成 schema。内容 / provenance 等开放 map 保持原文档契约，M05 字段由其所属模块验证，跨对象来源和前后版本仍独立校验。完整产品 192 项及实际 PM 的知识链 / 扩展与用户编辑链通过；不代替真实模型语义。见[总 Plan](../../plan.md)。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

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
