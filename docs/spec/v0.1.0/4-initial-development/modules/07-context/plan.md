---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: draft
decision_mode: user-approved
---

# M07：上下文、筛选、MCP 与反馈 Implementation Plan

> 执行者使用 `executing-plans`，按本模块 checkbox 推进；默认主 Agent 实施。

## 来源与目标

依据[统一 Design M07](../../design.md#context-retrieval)、[C04 / C05](../../design.md#closing-contracts)、[P06–P09](../../design.md#prompt-finalization)及[总 Plan](../../plan.md)。准备两份用途不同的列表，以最多三条已有素材交付当前轮；按需只读 MCP 检索和真实来源反馈，compact 恢复原选择。

## 文件映射

Create：`src/distillai/context.py`、`src/distillai/mcp.py`、`src/distillai/prompts/context.txt`、`selection.txt`、`injection.txt`；`plugins/distillai/skills/distillai/SKILL.md`；`tests/test_product_context.py`、`test_product_mcp.py`、`test_product_feedback.py`。

Modify：`runtime.py` 登记准备 / 查询 / 筛选和取消，`tools.py` 只读快照工具，`server.py` 业务桥接，`plugins/distillai/hooks/dispatch.py` / `hooks.json` 启动与上下文。MCP SDK 版本沿 M01 G1 固定，不手写协议。

## Task 1：子图、两列表与刷新

- [ ] **Step 1：写刷新 / 依赖矩阵。** 新开放 episode 首次成功保存准备；第三次新增材料成功更新刷新；重复交付 / 重写不计更新。M04 / M05 直接依赖变化立即登记，不等周期、不增加材料次数；尚未运行准备合并，运行准备固定输入且新变化另排。
- [ ] **Step 2：实现上下文载荷。** `contexts/<session_key>.json` 保存 episode_ref、准备 refs、名称 / 连接子图与两列表；候选含稳定 id / revision、record_refs、text、conditions、rationale，MCP 项引用摘要 / 来源。实质变更增加 revision，不因换排序重建身份或清交付历史；不复制权威详情到图。
- [ ] **Step 3：发布 P06 prepare 模式。** P01 + P06 + mode=prepare；查实际完整图 / 详情，分别按问题背景价值与素材连接价值定性排序，不凑列表或生成用户已知状态。使用维护工具 / 副本，结果 `context_ref,reason` 由程序校验 / 提交补版本。
- [ ] **Step 4：实现依赖失效。** 原记录 / 来源变更标待刷新；等待重新分析的判断及依赖候选不能新选材，只有当前修订 M05 成功且 M07 准备成功才恢复使用。历史选择快照保留，未知 / 候选身份不转成事实。
- [ ] **Step 5：运行上下文组。**

```powershell
python -m unittest discover -s tests -p 'test_product_context.py' -v
```

预期：刷新 / 版本 / 状态用例 `OK`；P06 排序语义另人工审阅。

## Task 2：当前轮筛选、交付与 compact

- [ ] **Step 1：写筛选输出边界。** 未准备或无候选不调用临时全图检索；结构化选择 ID 必须来自固定列表、唯一、0–3 个。伪造 ID、超量、重复、筛选期间来源变更拒绝对应条目，仍有效条目可以留下；没有适用候选正常空。
- [ ] **Step 2：发布 P07 并使用独立名额。** 只给当前问题 / 必要背景 / 固定候选 / 普通交付历史，不拼 P01 维护步骤、不注册任何工具。模型调用经 M01 计数，筛选最高优先且不等普通任务模型 I/O，不新增产品等待时限。
- [ ] **Step 3：保存当前轮选择快照。** 程序生成 round_key，持久选中文字、RecordRefs / 来源版本、Prompt 版本、原因和实际输出阶段；新 Prompt 新 round_key。普通连续重复按历史提示模型，实质变化 / 明确需要可再用；输出文本不算平台确认、助手采用或用户表现。
- [ ] **Step 4：实现 Hook / compact 返回。** UserPromptSubmit 在 M03 request_started 后同步筛选，用 P09-B 包装 additionalContext；SessionStart startup / resume / clear 恢复关联和 P09-A，compact 在当前轮续接前读取原选择原文 / 版本，最多三条，无选择只入口。compact 不重筛、不按重复历史过滤、不新建 episode。
- [ ] **Step 5：实现失败继续回答。** 启动 / 筛选 / 交付失败不带本次未交付素材，保留脱敏诊断继续原任务；没有候选空返回。与纯采集 stdout `{}` 分支区分，不把 Hook 技术超时解释为无匹配或业务收尾。
- [ ] **Step 6：复跑上下文组。** 新增“二次 compact 同一选择且筛选调用数不增”“旧选择历史版本仍可恢复”“筛选期间两候选一条失效仅交有效条”“候选变更不删交付历史”的契约测试；只断言版本 / 身份 / 内容快照，不固化 Prompt 全文措辞。

## Task 3：MCP 查询和反馈关联

- [ ] **Step 1：使用官方 Python SDK 建 stdio 桥接。** 注册服务 `distillai` 和 query_context / submit_feedback，读取 / 启动同一后台，stdio 退出不关闭常驻实例；stdout 只协议消息，诊断 stderr。用 SDK 客户端验证初始化、工具 schema 和调用错误，不手写 JSON-RPC。
- [ ] **Step 2：实现直接查询。** query_context 对明确 ID / 名称查询复用 M04，无模型任务；自然语言选择进入下一步骤。返回固定版本内容、来源、理解 / 假设身份及等待重分析说明。成功空、未知记录、索引未就绪、服务不可用分别映射，不用“无匹配”遮盖错误。
- [ ] **Step 3：发布 P06 query 模式。** 输入固定 query / 已知 refs，只注册 query_records / read_source 和必要记录搜索；不开放编辑、Shell、外部搜索，策略不允许业务文件变更。先子图 / 上下文，资料不足再全图；返回 status / items / source_refs / reason，程序校验实际读取 refs / 版本并组装对应版本正文。模型新编摘要不能替代未读记录，任务 / 历史保存由控制层负责。
- [ ] **Step 4：接入排队、同步返回和取消。** 查询复用普通名额、次于筛选且优先普通待办，不抢占运行维护；工具等待结果。桥接为每次独立工具调用生成内部触发标识，仅同一次调用的重复登记复用任务；不同调用即使查询相同也各有关联任务，使取消所有权唯一，不增加源消息 ID 或公开必填字段。客户端取消 / 平台超时只取消该调用关联的 queued 查询或停止对应 running 进程树，确认停完才复用名额，连接结束仍存原因；不关闭后台、不取消其他任务、不成功空返回。
- [ ] **Step 5：实现反馈幂等和待关联。** submit_feedback 保存 client_request_id / session / 真实表现与帮助 / 目标 refs / 可取得 source_refs，同 ID 重试复用。先于 Stop 时仅待关联；落盘后按角色、范围和上下文核查，唯一可信位置才进入 M05，多位置保持待关联。同来源不同请求由 M05 复用观察；文本相同不等于同源，普通反馈不伪造 user_submission。
- [ ] **Step 6：写并运行 MCP / 反馈组。** 检查 query 模式禁止写业务、实际版本对应、不读记录不返回、SDK 不同错误、运行维护不被查询抢占、排队查询优先下一普通任务、cancel 只停对应查询、两个相同文本的独立调用取消一个不影响另一个、重复反馈与歧义待关联。

```powershell
python -m unittest discover -s tests -p 'test_product_mcp.py' -v
python -m unittest discover -s tests -p 'test_product_feedback.py' -v
```

预期：`OK`；慢任务 / SDK 客户端取消使用本机合成数据，不需要外部模型。真实平台取消另 Task 4 验证。

## Task 4：插件说明与真实 Desktop 联调

- [ ] **Step 1：发布 P08 / P09。** Skill 使用批准全文与实际工具名，SessionStart 输出服务状态 / session_key / Skill 入口 / 实际注册全名；MCP 工具描述分别 P09-C / D。Prompt 与数据分开，配置由程序读取，不依赖 `${config.xxx}` 自动替换，不新建 MCP prompt 资源。
- [ ] **Step 2：固定 Desktop 接入配置。** 按当前 Desktop 实测确定插件启用、command 解释器 / PLUGIN_ROOT、MCP stdio 启动及所有事件字段，补产品安装 / 信任 / 停用说明。测试后台未运行时 SessionStart 可启动且不等待 MCP 已连接，多个入口不多实例。
- [ ] **Step 3：验证真实注入 / compact。** 合成会话取得可观察的最多三素材、条件不适用跳过、无候选空、后台错误继续、当前轮 compact 两次恢复原文字 / 版本；核对实际进入上下文的证据。只写 Hook stdout 不能替代平台交付证据，不要求通用 Agent 每轮采用。
- [ ] **Step 4：验证真实查询 / 取消。** Desktop 中查询已知 ID / 名称和自然语言；后者先上下文不足再全图。后台维护运行中发 query，观察等待 / 优先次序；客户端取消或平台超时确认仅该 query 停止。记录实际 SDK / Desktop 限制，没有收到取消信号就保留未验证状态。
- [ ] **Step 5：验证自然反馈链。** 同一真实测试来源经 Hook / MCP 各一次，回查唯一观察、帮助和假设变化；MCP 先到 / 歧义来源各测一次。记录交付、可观察采用、用户接触 / 独立应用的不同身份，中立问题不诱导目标答案。

## 测试必要性、依赖与状态

永久组保护刷新触发、版本 / ID / 数量、compact 快照、只读任务、队列 / 取消和来源幂等；现有测试未覆盖。Desktop additionalContext / MCP 连接、实际 tool 名、平台超时、Skill 使用和 Prompt 价值是一次性验收。M01 预算和文件提交不重复测试，只核对 query / prepare / selection 接入模式。

依赖 M01–M05；M06 结果可后接，不构成首次查询前置。Task 3 Step 4 的内部调用标识实现已确认的“只取消关联查询”，不改变公开输入或采集身份。本 Plan 为 draft，全部任务未执行。
