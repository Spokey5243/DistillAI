---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
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

- [x] **Step 1：建立合成输入。** fixture 包含 user / assistant 中间与最终正文、独立 reasoning、文本 / 图片混合块、空正文、已知 / 未知标签、未完成 rollout 尾条及 UTC / 无效时间；工具 fixture 覆盖 Shell 数组、trivial 命令、patch 文件和产品自身 MCP。数据由本任务生成，不复制个人 rollout。
- [x] **Step 2：写过滤用例。** 只提取 `response_item` 中 message 且 role=user / assistant 的正文，不筛 channel / phase；仅开头已知 tag 的 user 消息整条跳过，未知 / 中间标签保留。块只拼接文本类型；trim 后空跳过。断言 reasoning / base64 不出现，助手中间文本保留。
- [x] **Step 3：实现解析和 cursor 增量。** Stop / PreCompact 全量解析 rollout，以筛选后的正文数与 `{count,at}` 取增量；cursor 读取失败 / 非法为零，超出当前数从头取。只计完整正文记录，不给工具计 cursor，不加源指纹 / byte offset / 源消息 ID。
- [ ] **Step 4：实现固定工具摘要。** 不读 tool_response，不调用模型。Shell 从 command 取值、按参考 TRIVIAL_SHELL 精确或“前缀+空格”排除后取前 120 字符；patch 最多五文件或 `applied a patch`，其他 `used <name>`；缺名称 / 空摘要不入队。按 M07 实际注册结果排除产品 MCP 前缀，不能按摘要声称执行成功。
- [x] **Step 5：实现独立采集 dispatcher 分支。** 注册同步 command Stop / PreCompact / PostToolUse，禁用 async；Stop / PreCompact 需要 transcript，PostToolUse 不需要。所有采集结果 stdout `{}` / exit 0；诊断只存 UTC、事件、key、阶段、错误码，payload / 正文 / key 凭证不入日志。SessionStart / UserPromptSubmit / compact 分支由 M03 / M07 接续，不把它们当正文采集来源。
- [x] **Step 6：运行过滤组。**

```powershell
python -m unittest discover -s tests -p 'test_product_capture.py' -v
python tests/test_capture.py
```

预期：新产品用例 `OK`，旧资产组仍退出 0。模拟 Hook 不算真实 Desktop 通过。

## Task 2：队列追加、尾部恢复与来源读取

- [x] **Step 1：写系统互斥与失败窗口用例。** 两个进程竞争同 session，正文 cursor 与工具追加共用一个写互斥；拿不到立即返回。分别模拟队列落盘前失败、落盘后 cursor 保存失败、完整 JSON 无 LF、不完整尾字节、字段非法完整行、中段坏行。检查正文后续可补读，而本次工具可能丢失，不能声称恰好一次采集。
- [x] **Step 2：实现队列 / cursor 保存。** key 用完整 session_id，仅将非 ASCII 字母 / 数字 / `_` / `-` 替换 `_`，不另加碰撞检测。UTF-8 无 BOM，一条 JSON 一物理 LF 行，正文换行转义。写互斥覆盖 cursor 读取、增量计算、检查尾部、追加 / flush / fsync 和 cursor 同目录替换；cursor 只能在队列完整同步后推进。
- [x] **Step 3：实现限定尾修复。** 持写互斥只对未成为已登记来源的尾部处理：完整有效 JSON 补 LF，不完整尾截到最后 LF，字段非法完整条报错保留；无法确认边界保留并报错。不修复中段、不重编号、不写全文件自动修复器。
- [x] **Step 4：实现来源解析。** `sources.py` 按 `{connector,session_key,line_start,line_end}` 校验 connector / key / 包含端点及行字段，从既有队列读真实物理行；禁止传任意绝对路径。后台仅登记完整有效的连续范围，尾条等待，中段坏行报告并停止。正文 / 工具共用行号，不按角色筛选重新编号。向 `tools.py` 注册原始队列的 `read_source`，让 M03 在 M04 实施前即可补读原文；外部 / 用户提交来源由其记录模块扩展同一读取入口。
- [x] **Step 5：运行来源 / 追加组。**

```powershell
python -m unittest discover -s tests -p 'test_product_sources.py' -v
python -m unittest discover -s tests -p 'test_product_capture.py' -v
```

预期：`OK`；队列成功 cursor 失败允许重采到新位置，测试只断言保留来源 / 无提前推进，不断言自动去重。

## Task 3：轻量通知、扫描补登记与 Desktop 验证

- [x] **Step 1：实现通知。** 采集后向已存在实例发送 `{connector:"codex",session_key}`，连接 / 发送合用 200ms 截止，不读响应、不重试、不启动后台或发送进程；无实例 / 失效跳过。不得发送正文。后台忽略响应写失败，不撤回已收到提示。
- [x] **Step 2：接入可靠扫描。** worker 启动 / 恢复 / 每秒扫描补登记；通知只唤醒相同发现入口。相同来源位置重复提示复用任务；丢通知依然发现材料。未执行范围可合并，运行输入不改变；采集 cursor 与处理位置分别保存。
- [x] **Step 3：验证通知失败。** 本机假服务不回应、立即断开或不在运行；检查 Hook 截止和正常回答，后台随后扫描取得完整行。只有 M03 / 下游结果提交后处理位置推进，不通过通知 202 推进。
- [ ] **Step 4：取得真实 Desktop 采集证据。** 独立测试数据根中依次触发中间文本 / 最终回复、工具使用、PreCompact；对照实际 rollout 和完整队列来源，核对 PostToolUse 字段适配、时间和自身 MCP 排除。记录 Desktop 版本、插件配置、触发证据及实际行号；正文缺失或中断尾部只记录事实和后续补采条件。
- [x] **Step 5：同步插件启用说明。** 启用产品插件前停用旧验证插件对同会话的触发，旧文件 / 数据保留；无自动迁移。说明服务失效采集照常、日志脱敏、工具在竞争锁时可能丢失及原文后来重采不保证跨位置去重。

## 测试必要性、依赖与状态

永久测试保护过滤 / cursor 时序、来源物理行稳定、尾部恢复边界、通知不携正文、丢通知补登记和同位置幂等，现有旧 payload 测试没有这些覆盖。Desktop 字段 / 触发、固定发行组合和逐场景完整性做一次性记录，不固定个人文本 / 测试条数。

依赖 M01 文件互斥 / 本机实例 / 登记；生命周期进入 M03，产品 MCP 注册进入 M07。业务契约无偏差。2026-10-13 用户授权按当前 Plan 开始实施，本 Plan 已批准；完成状态按 checkbox 与执行记录核对。

## 执行记录

### 2026-10-15：产品队列、来源和扫描

新建 `capture.py` / `sources.py` 和独立 `plugins/distillai/`。正文按已批准规则保留 user / assistant 的中间与最终文本，跳过独立 reasoning、图片和开头七种 user 标签；源时间转 UTC，损坏 / 未完成 rollout 行不计 cursor。工具仅固定摘要，不读取 tool_response；参考 Shell / patch 规则已经实现，Codex 的 apply_patch.command 在适配入口转换为参考 input。`mcp__distillai__` 暂作排除前缀，尚待 M07 的实际注册名核对，因此 Task 1 Step 4 保留未勾选。

同 session 的队列可读 / 独写句柄覆盖正文与工具追加、cursor 读取 / 增量计算及保存。写锁竞争立即跳过；先同步队列再原子替换 cursor。仅对尚未登记的有效无 LF 尾条补 LF，或能确认在 EOF 截断的残缺 JSON / UTF-8 尾部截除；完整字段非法、不能确认的畸形尾部和中段坏行保留并报错。队列成功 cursor 失败允许重采到新行，不宣称恰好一次。UTF-8 stdin 按 bytes 解码，避免 Windows legacy 编码损坏中文路径与会话。

来源只接受 connector / session_key / 包含端点的物理行范围；正文 / 工具共用行号，半条尾部不登记，坏行之前的连续有效范围仍可读取。Hermes 适配在控制层按固定 source_refs 读取真实队列，把精确来源快照提供给只读 read_source；未授权范围不在子进程工具快照中。真实 AIAgent 已验证 read_source 工具往返，拿到 user 与 tool 两行原始材料。

通知仅向现有 loopback 实例发送 connector / key，connect / send 共用 200ms 截止，无响应等待 / 重试 / 后台启动。服务启动和轮询调用同一发现入口，丢通知也登记；未开始范围可合并，已开始输入不改，坏行之后不越过，登记历史在重启后复用。后台扫描主体已接入，但 M03 结果提交后的实际处理位置尚未实现，Task 3 Step 2 / 3 保留未勾选；通知 202 只唤醒，不推进任何业务处理位置。

验证采用标准库永久契约，保护过滤、物理来源、跨进程写锁、队列 / cursor 失败窗口、限定尾恢复、通知不等待 / 不传正文、扫描补登记与输入固定。另以真实固定版 AIAgent / 产品 Runtime / proxy / Job / Store 在临时目录执行七个合成场景，共 43 次 provider 请求；source 两次生成取得来源工具结果，其余六场景覆盖筛选、记录查询、文件 / Shell 发布、503 恢复、16 次成功与第 17 次拒绝。探针一度因新增 source 场景构造参数错误而超时，修复一次性探针后重跑退出 0，未改产品行为或收费模型。

真实 Desktop 未验证，Task 3 Step 4 / G2 保持未通过。已准备一次性 `distillai-g2-probe` 本地插件，只增加 Personal marketplace 的 AVAILABLE 条目，未安装 / 启用；使用独立临时数据根，生产 dispatcher 采集，探针另存事件 UTC / 顺序 / 完整队列行数，不保存原始 Hook payload 或工具响应。合成 dry-run 已单独用临时目录验证，不计 Desktop 证据。实际包与测试说明位于忽略目录的 g2-probe-locations.json / G2-desktop.md，不进入生产插件 / fixture。

Task 1 Step 1 / 2 / 3 / 5 / 6、Task 2 全部、Task 3 Step 1 / 5 完成，本模块 12 / 16 项完成。M03 / M07 的交接和实际 Desktop 证据仍按原 Plan 验收；当前没有远端写入或启用个人会话。

最新验证：完整标准库组 78 tests / OK，无 skip，Python 3.13.5 为 15.964s，PM Python 3.14.7 为 15.873s；旧 `python tests/test_capture.py` 为 PASS，`uv lock --check --offline` 退出 0。文档链接、diff 和变更文件凭证模式检查另行完成；没有真实 Desktop 或 GitHub CI 结果。

### 2026-10-15：处理位置接入

M03 普通材料提交已将 buffers/<key>.json 的 processed_line / material_updates 交控制层更新，并与语义文件共用发布清单。任务登记、采集 cursor 和实际处理位置各自保存；校验失败 / 未发布不推进正式状态，业务提交后的后置登记失败不重跑模型。来源扫描支持 M03 登记策略，新会话先取得首轮的固定 episode，再登记后续范围，未丢失的材料仍在原物理行。Task 3 Step 2 / 3 完成，本模块 14 / 16；实际 Desktop 和 M07 工具前缀仍待验收。
