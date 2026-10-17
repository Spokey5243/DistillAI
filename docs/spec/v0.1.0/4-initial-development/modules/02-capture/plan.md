---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: approved
decision_mode: user-approved
---

# M02：复用采集与来源，完成 Desktop 接入 Implementation Plan

> 2026-10-17 用户批准重写稿并授权实施；按 `executing-plans` 由主 Agent 持续执行。
> 旧测试结果不代表新实现已通过；仅在取得当前验证证据后勾选步骤。

## 目标、现状与文件

依据[统一 Design M02](../../design.md#data-capture)与[总 Plan](../../plan.md)。现有过滤、cursor、队列、来源解析和扫描实现继续使用；只补实测发现的接入差异。Modify：`src/distillai/capture.py`、`sources.py`、`runtime.py`、`plugins/distillai/hooks/dispatch.py`、`hooks.json`；测试复用 `tests/test_product_capture.py` / `test_product_sources.py`，旧 `plugins/distill-capture/` / `tests/test_capture.py` 保留。

## M02-R1：保留队列与来源契约

- [x] **R1.1 核对已有覆盖。** 复跑过滤 / cursor、跨进程互斥、尾部恢复、来源物理行、通知与扫描原用例，不重写解析器。正文仅 response_item message user / assistant 文本，不筛中间 / 最终 channel；只过滤开头已知 user tag，reasoning / 非文本块不入正文。
- [x] **R1.2 核对保存和失败窗口。** 沿现有 Win32 / msvcrt 文件互斥，同 session 写锁覆盖完整队列追加 / fsync 再保存 cursor；竞争立即返回。只修可确认的未登记尾部，不改中段 / 物理行号；cursor 保存失败允许重复采到新位置，不宣称跨位置去重。M01-R6 离线迁移另须暂停所有指向该数据根的采集入口并等待在途 Hook 结束；停止后台或持 Store 锁不代表队列 / cursor 已停写，迁移完成核验前不恢复采集。来源仍为 connector / session_key / 包含端点行范围，不接受任意路径。
- [x] **R1.3 接入新后台入口。** 通知只传 connector / session_key，connect + send 共用 200ms，不读响应、不重试、不冷启动；失败继续对话。新 FastAPI 路由只唤醒现有发现入口，启动 / 周期扫描负责补登记；正式处理位置在业务提交后推进，不用 202 当保存成功。保留原最小 socket 发送，不为这条无需响应的通知硬套普通 HTTPX 请求。

## M02-R2：按真实 Desktop 字段完成适配

- [ ] **R2.1 获取合成会话证据。** 在独立测试数据根按已有 G2 探针说明观察 Stop / PreCompact / PostToolUse；记录实际 Desktop 版本、插件配置、事件顺序、完整来源行和字段。保持原材料私有，不将个人 rollout 复制为 fixture。
- [ ] **R2.2 补齐工具摘要映射。** 按真实 tool_input 映射 command 数组 / patch；复用已有 TRIVIAL_SHELL 规则，Shell 截前 120 字、patch 最多五文件，其他 used name。不读 tool_response、不调模型、不用摘要声明成功。由 M07 实际注册全名校准产品 MCP 排除前缀，不继续把猜测前缀当已验证。
- [ ] **R2.3 验证丢通知和错误继续。** 停后台后采集、服务不回应、写锁竞争、半条尾部、中断后补采各观察一次，确认正文后续可补、工具可能丢、stdout `{}` / exit 0 和脱敏诊断。检查只在事件契约允许的分支采正文，SessionStart / UserPromptSubmit 不另造正文来源。
- [ ] **R2.4 同步接入说明。** 写真实插件启用 / 停用 / 数据根 / 产品解释器路径；同会话启用前停用旧验证插件但保留旧数据，不做自动迁移。只有真实 Desktop 证据齐备才关闭本模块 G2 项。

## 验证与测试取舍

```powershell
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_capture.py' -v
uv run --locked python -m unittest discover -s tests -p 'test_product_sources.py' -v
uv run --locked python tests/test_capture.py
```

预期 `OK` / 退出 0。永久测试只补真实字段差异引发的长期过滤 / 来源回归，复用已有 fixture；固定发行字段、完整触发、工具全名前缀核对是一次性 Desktop 验证。依赖 M01 新入口和 M07 实际工具名，M03 负责生命周期。新稿无新增采集协议或存储层。

## 2026-10-17 批准与执行

用户明确批准本次重写总 Plan 与八模块 Plan，授权完成既有代码重构与计划内新功能。需要用户决策或外部条件的事项集中写入 [待办](../../pending.md)，不阻止独立可实施步骤；保留既有修改，不包含远端写入授权。

## 2026-10-17 第二批：原生框架、真实 stdio 与浏览器回归

复跑现有产品采集 / SourceRef / 启动发现组及独立 tests/test_capture.py：过滤、物理行 / cursor、并发 / 尾部恢复、忙锁与失败继续均通过。SourceRef / RecordRef / QueueEntry 改由共享 Pydantic 严格类型检查，来源存在 / 行序 / UTC 和授权仍由原领域判断负责。FastAPI 通知唤醒现有扫描；200ms 不等待响应、不冷启动的采集发送语义保留。真实 Desktop G2 仍未完成。

完整证据、收尾测试结果与范围见[总 Plan](../../plan.md)第二批执行记录；本地通过不代替 GitHub CI，未迁移真实数据或执行远端写入。

## 2026-10-17 恢复后第四批：共享结构与工具 schema

共用 SourceRef / RecordRef 的严格结构保留在 sources.py，增加 DraftRecordRef / SessionKey / 非空文本供下游直接复用，校验错误不输出来源原文。完整产品 192 项通过，未变更 Hook payload、原始队列或 Desktop 事件适配；G2 继续待验。详见[总 Plan](../../plan.md)。

## 2026-10-17 第五批：HTTP 与 MCP 请求模型

QueueLocator / QueueRef 共用严格会话定义，通知请求复用同一结构；产品外部来源 / 用户提交记录接入 discriminated union，URL / UTC / 实际注册身份与不可变历史版本仍独立核对。原始 Codex payload 继续沿实际格式解析，不把外部可扩展事件强制关字段。完整产品 193 项通过，真实 G2 仍未验。见[总 Plan](../../plan.md)第五批。

## 2026-10-17 第六批：Loguru 进程日志与停机排空

产品采集诊断改为每进程独占 logs/capture-<time>-<pid>.jsonl.gz，Loguru 在这一条诊断结束时 complete / remove、压缩并执行 retention；旧日志保留。两个真实 Python 进程的独立文件 / 实际 PID / 无正文断言通过，产品采集 11 项及完整产品 197 项通过。Hook stdout / 失败继续策略保持，Desktop 仍待 G2。见[总 Plan](../../plan.md)第六批。

<a id="historical-execution"></a>

## 重写前的执行记录（历史证据）

以下保留原记录、日期和旧 Task / Step 编号，便于回查。旧完成比例、批准状态、解释器组合及转发探针仅描述当时实现；不作为本稿的执行指令或本轮验证结果。旧计划全文可从 Git 中重写前的版本回查。

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
