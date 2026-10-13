---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: draft
decision_mode: user-approved
---

# M02：采集、来源与材料交付 Implementation Plan

> 执行者使用 `executing-plans`，按本模块 checkbox 推进；默认主 Agent 实施。

## 来源与目标

依据[统一 Design M02](../../design.md#data-capture)及[总 Plan](../../plan.md)。在新产品插件采集正文增量和固定工具摘要，保存稳定的队列物理行来源，以通知和扫描交给后台。复用旧验证资产的经验，不更改其格式或宣称它已满足产品契约。

## 文件映射

Create：`src/distillai/capture.py`、`src/distillai/sources.py`、`plugins/distillai/hooks/dispatch.py`、`plugins/distillai/hooks/hooks.json`、`tests/test_product_capture.py`、`tests/test_product_sources.py`、`tests/fixtures/codex-rollout.jsonl`、`tests/fixtures/codex-tools.json`。

Modify：`src/distillai/runtime.py`、`server.py` 登记发现入口，`windows.py` 提供系统写互斥，`tools.py` 注册原始来源读取，产品 README。保留 `plugins/distill-capture/`、`scripts/demo_capture.py`、`tests/test_capture.py`。

## Task 1：正文、工具摘要与产品 Hook

- [ ] **Step 1：建立合成输入。** fixture 包含 user / assistant 中间与最终正文、独立 reasoning、文本 / 图片混合块、空正文、已知 / 未知标签、未完成 rollout 尾条及 UTC / 无效时间；工具 fixture 覆盖 Shell 数组、trivial 命令、patch 文件和产品自身 MCP。数据由本任务生成，不复制个人 rollout。
- [ ] **Step 2：写过滤用例。** 只提取 `response_item` 中 message 且 role=user / assistant 的正文，不筛 channel / phase；仅开头已知 tag 的 user 消息整条跳过，未知 / 中间标签保留。块只拼接文本类型；trim 后空跳过。断言 reasoning / base64 不出现，助手中间文本保留。
- [ ] **Step 3：实现解析和 cursor 增量。** Stop / PreCompact 全量解析 rollout，以筛选后的正文数与 `{count,at}` 取增量；cursor 读取失败 / 非法为零，超出当前数从头取。只计完整正文记录，不给工具计 cursor，不加源指纹 / byte offset / 源消息 ID。
- [ ] **Step 4：实现固定工具摘要。** 不读 tool_response，不调用模型。Shell 从 command 取值、按参考 TRIVIAL_SHELL 精确或“前缀+空格”排除后取前 120 字符；patch 最多五文件或 `applied a patch`，其他 `used <name>`；缺名称 / 空摘要不入队。按 M07 实际注册结果排除产品 MCP 前缀，不能按摘要声称执行成功。
- [ ] **Step 5：实现独立采集 dispatcher 分支。** 注册同步 command Stop / PreCompact / PostToolUse，禁用 async；Stop / PreCompact 需要 transcript，PostToolUse 不需要。所有采集结果 stdout `{}` / exit 0；诊断只存 UTC、事件、key、阶段、错误码，payload / 正文 / key 凭证不入日志。SessionStart / UserPromptSubmit / compact 分支由 M03 / M07 接续，不把它们当正文采集来源。
- [ ] **Step 6：运行过滤组。**

```powershell
python -m unittest discover -s tests -p 'test_product_capture.py' -v
python tests/test_capture.py
```

预期：新产品用例 `OK`，旧资产组仍退出 0。模拟 Hook 不算真实 Desktop 通过。

## Task 2：队列追加、尾部恢复与来源读取

- [ ] **Step 1：写系统互斥与失败窗口用例。** 两个进程竞争同 session，正文 cursor 与工具追加共用一个写互斥；拿不到立即返回。分别模拟队列落盘前失败、落盘后 cursor 保存失败、完整 JSON 无 LF、不完整尾字节、字段非法完整行、中段坏行。检查正文后续可补读，而本次工具可能丢失，不能声称恰好一次采集。
- [ ] **Step 2：实现队列 / cursor 保存。** key 用完整 session_id，仅将非 ASCII 字母 / 数字 / `_` / `-` 替换 `_`，不另加碰撞检测。UTF-8 无 BOM，一条 JSON 一物理 LF 行，正文换行转义。写互斥覆盖 cursor 读取、增量计算、检查尾部、追加 / flush / fsync 和 cursor 同目录替换；cursor 只能在队列完整同步后推进。
- [ ] **Step 3：实现限定尾修复。** 持写互斥只对未成为已登记来源的尾部处理：完整有效 JSON 补 LF，不完整尾截到最后 LF，字段非法完整条报错保留；无法确认边界保留并报错。不修复中段、不重编号、不写全文件自动修复器。
- [ ] **Step 4：实现来源解析。** `sources.py` 按 `{connector,session_key,line_start,line_end}` 校验 connector / key / 包含端点及行字段，从既有队列读真实物理行；禁止传任意绝对路径。后台仅登记完整有效的连续范围，尾条等待，中段坏行报告并停止。正文 / 工具共用行号，不按角色筛选重新编号。向 `tools.py` 注册原始队列的 `read_source`，让 M03 在 M04 实施前即可补读原文；外部 / 用户提交来源由其记录模块扩展同一读取入口。
- [ ] **Step 5：运行来源 / 追加组。**

```powershell
python -m unittest discover -s tests -p 'test_product_sources.py' -v
python -m unittest discover -s tests -p 'test_product_capture.py' -v
```

预期：`OK`；队列成功 cursor 失败允许重采到新位置，测试只断言保留来源 / 无提前推进，不断言自动去重。

## Task 3：轻量通知、扫描补登记与 Desktop 验证

- [ ] **Step 1：实现通知。** 采集后向已存在实例发送 `{connector:"codex",session_key}`，连接 / 发送合用 200ms 截止，不读响应、不重试、不启动后台或发送进程；无实例 / 失效跳过。不得发送正文。后台忽略响应写失败，不撤回已收到提示。
- [ ] **Step 2：接入可靠扫描。** worker 启动 / 恢复 / 每秒扫描补登记；通知只唤醒相同发现入口。相同来源位置重复提示复用任务；丢通知依然发现材料。未执行范围可合并，运行输入不改变；采集 cursor 与处理位置分别保存。
- [ ] **Step 3：验证通知失败。** 本机假服务不回应、立即断开或不在运行；检查 Hook 截止和正常回答，后台随后扫描取得完整行。只有 M03 / 下游结果提交后处理位置推进，不通过通知 202 推进。
- [ ] **Step 4：取得真实 Desktop 采集证据。** 独立测试数据根中依次触发中间文本 / 最终回复、工具使用、PreCompact；对照实际 rollout 和完整队列来源，核对 PostToolUse 字段适配、时间和自身 MCP 排除。记录 Desktop 版本、插件配置、触发证据及实际行号；正文缺失或中断尾部只记录事实和后续补采条件。
- [ ] **Step 5：同步插件启用说明。** 启用产品插件前停用旧验证插件对同会话的触发，旧文件 / 数据保留；无自动迁移。说明服务失效采集照常、日志脱敏、工具在竞争锁时可能丢失及原文后来重采不保证跨位置去重。

## 测试必要性、依赖与状态

永久测试保护过滤 / cursor 时序、来源物理行稳定、尾部恢复边界、通知不携正文、丢通知补登记和同位置幂等，现有旧 payload 测试没有这些覆盖。Desktop 字段 / 触发、固定发行组合和逐场景完整性做一次性记录，不固定个人文本 / 测试条数。

依赖 M01 文件互斥 / 本机实例 / 登记；生命周期进入 M03，产品 MCP 注册进入 M07。业务契约无偏差。本 Plan 为 draft，全部任务未执行。
