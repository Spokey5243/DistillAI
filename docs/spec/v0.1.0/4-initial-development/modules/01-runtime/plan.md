---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: implemented
decision_mode: user-approved
---

# M01：运行、执行边界与保存 Implementation Plan

> 执行者使用 `executing-plans` 按 checkbox 推进，默认主 Agent 实施；2026-10-13 用户授权按当前 Plan 开始实施。

## 来源与目标

依据[统一 Design M01](../../design.md#runtime-contracts)、[技术选择](../../design.md#technical-selection)、[总 Plan](../../plan.md)。完成一个常驻 Python 控制层，直接在独立任务子进程调用 Hermes `AIAgent`，可控制调用预算、业务路径授权、任务停止、冲突安全发布和崩溃恢复；OS 写隔离依据 Design 修订 1 延后。它是后续七模块的唯一共用运行基础。

## 文件映射

以下均以仓库根目录为基准。

| Create / Modify | 职责 |
| --- | --- |
| `src/distillai/__init__.py`、`__main__.py` | 包、启动和 task-child 入口 |
| `src/distillai/runtime.py` | 单例、任务登记 / 固定输入 / 调度 / 停止 / 计数 / 依赖 |
| `src/distillai/storage.py` | 不可变版本、任务副本、变更扫描、发布 / 恢复 |
| `src/distillai/windows.py` | 文件身份 / 共享模式和普通任务进程树停止；不实现写隔离 runner |
| `src/distillai/config.py` | 版本配置、校验、脱敏、即时 / 延后生效 |
| `src/distillai/server.py` | 本机 HTTP、请求授权、路由 / 限额 / 错误 |
| `src/distillai/hermes.py`、`tools.py` | AIAgent 直接调用与工具清单；任务模型转发 |
| `src/distillai/prompts/common.txt` | P01 正式批准后的全文 |
| `scripts/start.ps1`、`pyproject.toml`、产品依赖锁文件 | 来源定位、已准备环境启动及固定产品依赖 |
| `tests/test_product_storage.py`、`test_product_runtime.py`、`test_product_config.py`、`test_product_http.py`、`test_product_windows.py` | 永久契约组；Windows 组需实际能力可用 |
| `.gitignore`、`README.md`、`.agents/rules/python.md`、`github-actions.md`、`.github/workflows/ci.yml` | 真实运行 / 检查说明和离线 CI |

一次性 probe 放 `.artifacts/initial-development/`，不形成产品诊断框架；已有采集插件、开发 Hook 和 Hermes 上游代码不改。

2026-10-15 后续执行边界修复：Hermes 可修改 stdout 编码，task-child 协议改为显式 UTF-8 字节，使用非 GBK 可编码字符的回归测试。Windows PM 虚拟环境解释器为转发器，任务改用 check_environment 核对的底层解释器，设置虚拟环境 launcher 配置保留原依赖；CREATE_SUSPENDED 后加入 Job，再恢复执行并发送输入。分配失败显式终止尚未加入 Job 的挂起进程。启动 / 三代进程停树与错误清理在两解释器验证；没有增加写隔离。后台启动请求 Windows breakaway，拒绝时明确要求在可独立启动的入口执行。MCP 当前先复用 Serve 实例，SDK 关闭传输后的后台存活与冷启动限制见 M07 记录。

## Task 1：冻结可工作的执行组合

先通过 G0；本任务运行结果是 G1 的证据，不自动授权安装额外框架、改主机 ACL 或选择新长期技术路线。

- [x] **Step 1：记录本机和本地源码。** 记录 Windows build、Python / 架构、Hermes 当前 SHA 和与 Design 查证 SHA 的差异。核对当前源码的 Library、PM、provider、工具注册和资源加载入口，不从旧 Pi / TS 提案复制参数。

```powershell
git -C E:\JourneyIntoAI\DL_and_LLM\projects\hermes-agent rev-parse HEAD
python --version
Get-ComputerInfo -Property WindowsVersion,OsBuildNumber,OsArchitecture
```

预期：得到明确版本事实；源码路径只用于本机验证，不写死在产品中。

- [x] **Step 2：在独立数据根准备 Hermes 应用环境。** 设置专用 `HERMES_HOME` / `HERMES_RUNTIME_DIR`，依据固定源码的官方 PM 流程准备应用环境；记录 receipt、实际解释器、导入路径与锁文件摘要，不用 pip / uv 直接修改 PM 环境。开发激活另含 dev / test 环境，其失败单独记录，不作为直接 Library 接入的必要条件。首次准备及下载在已批准范围内；下面命令核对本次已由 PM 准备的实际选择，不是首次 bootstrap 配方。

```powershell
$env:HERMES_HOME = Join-Path $env:TEMP 'distillai-hermes-validation'
$env:HERMES_RUNTIME_DIR = Join-Path $env:HERMES_HOME 'tools'
$facts = Get-Content (Join-Path $env:HERMES_HOME 'installs/df016e59190fdbc4/facts.json') -Raw | ConvertFrom-Json
$HermesPython = Join-Path $facts.packages.venv.environment 'Scripts/python.exe'
Push-Location E:\JourneyIntoAI\DL_and_LLM\projects\hermes-agent
& $HermesPython -m pm.cli install --trust-recorded
& $HermesPython -c "import sys; from run_agent import AIAgent; print(sys.executable); print(AIAgent.__module__)"
Pop-Location
```

预期：PM 应用准备与导入分别退出 0，输出实际解释器和 `run_agent`；导入检查不证明已执行模型任务。失败记录 PM / 依赖事实，不改用 Hermes CLI。安装 key / 路径仅是本机验证事实，产品启动不写死该 generation。

- [x] **Step 3：验证最小 AIAgent 任务。** 在忽略目录写一个 probe，直接导入 AIAgent、设置 `quiet_mode=True`、显式模型 / 固定本机转发 endpoint / 工具集，调用 `run_conversation()`。由本机合成服务依次返回工具调用和终结 JSON；记录实际构造参数、工具注册方法、关闭方法、缓存 / 压缩 / retry 路径及实际 system / tools 全文。禁用个人配置发现、自动扩展 / MCP、并行子 Agent、无额度后台活动和无需的功能。最后用用户实际配置的模型核对一次流式工具往返，凭证只在控制层。
- [x] **Step 4：验证请求计数接管。** 本机合成服务记录每次实际到达的生成请求；覆盖正常结束、工具后继续、失败重试、压缩 / 辅助请求、第 16 次完成、第 17 次拒绝、同任务重启。将各调用导向受保护转发入口；无法接管的自动模型活动关闭。对未知是否已发出记录保守计数；不把 AIAgent `max_iterations` 当外部请求额度。完成一次“并发普通任务 + 独立筛选”验证；单槽模型服务实际排队只记技术约束，不承诺服务端抢占。
- [x] **Step 5：验证普通任务进程停止。** 使用普通任务子进程与 Job Object / 进程树生命周期控制，验证父 / 子 / 孙都能运行；取消或授权收紧后停止整棵树，确认心跳 / 文件写入停止后才恢复和释放名额。普通进程访问本机模型转发与外网沿 Step 3 / 4 的实际组合核对。Job 只证明生命周期，不作为写隔离；本次不验证 MXC、restricted token、主机 ACL 或沙箱 stdio 转发。
- [x] **Step 6：验证 Win32 提交窗口。** 在临时目录用 `CreateFileW` 共享模式、文件 / 目录身份和落盘操作实际检查：用户占用、比较后替换、删除 / 改名、路径被 junction 重指、新文件抢占、部分发布后再次用户编辑。记录通过句柄执行的操作及不能保证的窗口；无法可靠阻止目标替换就拒绝发布。
- [x] **Step 7：冻结环境和依赖。** 首选不修改 PM 源环境即可共用兼容依赖的最小组合；产品 MCP 依赖若与 PM 冲突则分离控制层环境，子进程仍用 PM 解释器。记录固定源码 SHA、PM receipt、产品 SDK 版本 / 锁、普通任务子进程与停树启动方式，再把下面启动命令改成验证后的实际命令。G1 未通过不执行具有任意写 / Shell 能力的产品维护任务。

能力矩阵的每项记录实际命令、退出码、观察文件哈希 / 进程状态及通过 / 失败；只读文档和假 runner 不构成放行结果。trajectory 训练方向保留；不在本任务实现训练导出或 RLVR。

## Task 2：版本、副本和冲突安全提交

- [x] **Step 1：建立最小持久布局。** 用 `DISTILLAI_HOME` 定位 config、tasks、versions、commits、workspaces 和程序事件；默认 `.distillAI`。内容版本用不可变字节 SHA-256；JSON 保存使用同目录临时文件、flush / fsync、锁内替换；追加事件用 JSONL。将 `.distillAI/`、既有 `.distallAI/`、凭证、PM 数据、虚拟环境和临时证据纳入提交排除。
- [x] **Step 2：先写提交回归用例。** 临时目录构造新增、修改、删除、改名、未改变文件和同期用户修改；准备清单后模拟逐项中断及用户再编辑。断言失败保留用户版本、业务 / 处理位置不提前成功、历史前后版本可读取。新测试补齐现有采集测试没有覆盖的多文件发布 / 恢复风险。
- [x] **Step 3：实现副本和变更扫描。** 创建独立字节副本，记录基线存在性、哈希、元数据和原授权路径；来源一致读失败明确报错。任务停止后扫描真实差异而非信任模型文件列表；程序拒绝发布新增链接、特殊设备、NTFS 附加流和不能恢复的元数据修改。校验文件身份、相对路径、结构、来源及业务模块归属。
- [x] **Step 4：实现 prepared → committed。** 保存前后不可变版本和逐项状态；取权限 / 提交锁核对授权、当前 episode 输入修订和原文件基线。使用 Task 1 验证的句柄适配持有目标保护，新文件排他新建；未改变文件不写回。整批完成才标 committed；完整持久化后推进处理位置 / 依赖，再触发索引补建。
- [x] **Step 5：实现崩溃恢复。** 读取同一提交清单补完业务已 committed 的后置登记，禁止重跑模型；提交未完成时只撤销仍等于本次发布版本的项目，用户再编辑或恢复失败进入 `recovery_conflict` 并暂停冲突范围。运行失败仅丢弃未发布副本，保留任务和版本证据。不能声称外部编辑器可原子看到整批文件。
- [x] **Step 6：运行存储组和 Win32 组。**

```powershell
python -m unittest discover -s tests -p 'test_product_storage.py' -v
python -m unittest discover -s tests -p 'test_product_windows.py' -v
```

预期：离线提交用例 `OK`；Windows 组在实际环境验证提交句柄 / 占用 / 路径竞争和停树。能力缺失明确 skip 原因并保持对应 G1 项未通过，不能把 skip 当验收；不要求 OS 越界写拒绝。

## Task 3：任务调度、预算、配置与 Hermes 适配

- [x] **Step 1：写任务状态 / 预算用例。** 相同 kind / 固定范围 / 版本 / 触发登记复用任务；仅未运行增量可合并；第 16 次生成返回有效结果成功，第 17 次不发出；重启不清计数；取消 queued 任务不启动进程；取消 running 任务等进程树停完才释放名额；M04 / M05 旧 episode 输入不能发布。
- [x] **Step 2：实现任务状态和双名额调度。** 一个普通执行名额、一个当前轮筛选名额；查询在下一调度点优先于普通待办，不抢占正在运行者，同级登记顺序。持久 queued / running / validating / recovering / 终态；绑定固定输入、配置 / Prompt / 权限版本。只以实际提交 / 结果保存判成功，空结果可成功。
- [x] **Step 3：实现受保护模型转发。** 每个请求检查任务授权、许可协议 / 模型 / 路由，发出前锁内持久占用额度；从配置取得真实 key，载荷只持有内部引用 / 任务 token。禁止任意 URL 代理、泄露授权头和模型内部推理。源连接失去授权时拒绝新请求；最后允许请求正常返回 / 校验，仍需新增请求才预算失败。控制层与子进程协议按 task_id 关联并验证大小 / 字段。
- [x] **Step 4：接入独立 AIAgent 子进程。** `hermes.py` 唯一直接导入、创建 / 调用和关闭 AIAgent；业务模块只提供任务载荷和工具清单。使用普通独立任务子进程；程序不修改运行资源，HERMES_HOME 使用产品独立数据与任务临时状态，不执行个人 / 工作目录配置。维护带副本 / Shell，query 只读工具，筛选完全无工具；全部注册名由能力验证结果固定。
- [x] **Step 5：实现配置校验和生效。** 沿 Design 的全部字段与初始值：调用 16、poll 1 秒、buffer 3、refresh 3、外扩 3600 秒 / 10 条。模型协议参数按支持范围验，非法保持旧版本并返回字段错误。新任务固定配置；poll / 周期下一判定生效且不清进度；工作路径扩大用于新任务，收紧立即注销授权、停止树后恢复。读配置遮蔽 key，Web 新输入可写 key，空的脱敏显示不能覆盖原 key。
- [x] **Step 6：发布 P01 和执行历史。** 从批准文本创建 common.txt，将实际共用 Prompt、业务 Prompt、工具定义、输入 / 输出引用、计数 / 错误 / 恢复、当时配置脱敏版本入不可变历史；没有工作不调用模型，不使用无限 Agent 对话承载业务连续性。
- [x] **Step 7：运行任务和配置组。**

```powershell
python -m unittest discover -s tests -p 'test_product_runtime.py' -v
python -m unittest discover -s tests -p 'test_product_config.py' -v
```

预期：上述契约 `OK`，无效配置和恢复不重置预算；再复核 Task 1 真实工具 / 模型请求，mock 结果不能替代 G1。

## Task 4：单例、本机接口和启动脚本

- [x] **Step 1：实现单例与启动锁。** 按数据根保存实例 ID / PID / 协议 / 地址 / 授权，启动前验证完整身份和 health，不能只认端口或 PID。后台选可用 loopback 端口，Hook / MCP 退出不关闭；Stop 先停止新任务、停树 / 恢复后退出。
- [x] **Step 2：实现 HTTP 契约。** 用标准库线程 HTTP 保持 worker / 模型 I/O 不阻塞 health / 配置；绑定 `127.0.0.1`，验证本机授权、Host / Origin、体积和路由，固定返回 schema / 错误。实现 Design 八个基线路由，cancel 的 `202` 只表示正在处理；查询任务不存在 404、配置版本冲突 409。任意材料不拼成 Shell。
- [x] **Step 3：实现启动接口。** 创建总 Plan 中定义的 `start.ps1` 动作和 `__main__` 模式：显式定位 Hermes 源码与已准备解释器、加入产品 src；检查不自动安装或激活下载。环境准备单独按 Task 1 文档执行，后台启动使用隐藏窗口 / 无窗口子进程，不启动 Hermes CLI 或重复 worker。
- [x] **Step 4：写并运行 HTTP 契约测试。** 覆盖伪造 PID / 同端口其他进程、多入口竞争启动、服务恢复、未知路由、无授权 / 外部 Origin / 非法 Host、超大 body、health 不被慢任务阻塞、显式退出后下次重新启动。

```powershell
python -m unittest discover -s tests -p 'test_product_http.py' -v
```

预期：`OK`；真实后台启动后用脚本 `Check / Serve / Stop` 验证一实例和退出恢复。

- [x] **Step 5：同步运行文档和离线 CI。** 记录经验证的准备 / 启动 / 检查 / 退出命令、源与数据边界、受支持组合；CI 增加标准库产品测试，不安装个人 Hermes / 模型密钥，不改现有触发器 / token 权限。需要 SDK 协议组时只按产品锁安装最小控制层依赖，Hermes 实机组保留本地证据。同步 Python / CI 规则从“无产品环境”到真实状态。

## 测试必要性与一次性验证

| 永久组 | 保护的未来回归 | 一次性验证 |
| --- | --- | --- |
| 存储 / Win32 | 覆盖用户编辑、错误恢复、位置提前推进、链接绕过与未停止树继续写 | 当前 Windows 的普通进程树停止、实际占用和提交窗口 |
| 任务 / 配置 | 同任务次数清零、末次请求被误中断、超额生成、配置失效、撤销不即时、查询抢占 | Hermes 内部 retry / 压缩真实路径、选定模型及单槽服务并发 |
| HTTP | 假实例被复用、外部授权绕过、慢任务堵控制入口 | 固定 SDK / 环境安装与真实启动组合 |

现有 test_capture 和 Push Guard 未覆盖上述产品契约；产品测试使用临时数据与本机合成 provider。依赖数量、文件名、Prompt 全文相等和安装位置不做永久断言。

## 依赖、偏差与状态

前置 G0；Task 1 输出 G1。未固定的 MCP / 环境不是隐藏实现假设，重大新方案先同步 Design。当前对齐用户确认的 Design 修订 1，OS 写隔离延后；执行证据与批准范围写在本节。2026-10-13 用户授权按当前 Plan 开始实施，本 Plan 已批准；完成状态按 checkbox 与执行记录核对。

当前范围（2026-10-14，用户确认）：OS 写隔离移至后续独立 Issue；保留副本、授权 / 计数、停树、冲突检查与程序写回。历史写隔离失败不再阻塞当前 G1，Step 6 提交窗口和 Step 7 环境 / 依赖冻结仍需证据。后续 Issue 尚未创建，MXC + stdio 候选不再等待批准。

### 2026-10-13：Task 1 开始执行

用户指令“现在开始按照plan执行”批准当前统一 Design / Prompt、总 Plan 和八模块 Plan 的本地实施。工作区从干净的 `codex/4-initial-development` / `0e81742fcfbfd36134cd175e18b0d5daee902e48` 开始；复用当前任务分支，由主 Agent 执行。GitHub 只读核对为 `Spokey5243/DistillAI`、默认分支 `main`、当前账号 `Spokey5243`、Issue #4 OPEN；没有本分支 PR。

Step 1：Windows 25H2、build `26200.9457`、x64；当前控制层解释器 Python `3.13.5`。Hermes 为干净的浅克隆，当前 SHA `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed`；Design 历史查证 SHA `97a9ae8ee55d31bebce49f1fb6b5ef775323976a` 不在本地 Git 对象中，差异比较返回 `fatal: bad object`，不能声称核对过完整 diff。本次不 fetch 或切换上游，当前 SHA 仅作为验证对象，未冻结为可发布组合。

核对入口为 Hermes 的 `website/docs/guides/python-library.md`、`website/docs/reference/package-management.md`、`activate.ps1`、`setup-hermes.ps1`、`run_agent.py`、`agent/agent_init.py`、`tools/registry.py` 和 `hermes_cli/plugins.py`。实际构造函数包含 `provider` / `api_mode`、`skip_context_files` / `skip_memory` / `skip_background_review`；资源释放使用 `close()`，工具使用 `registry.register(...)`。导入阶段会加载上游源码 `.env`，实例阶段会发现插件；后续 probe 使用独立 `HERMES_HOME`、`HERMES_SAFE_MODE=1`、显式工具白名单和关闭后台审查，不以 `quiet_mode` 代替这些边界。

PM 数据位于本机临时目录 `distillai-hermes-validation`，`HERMES_RUNTIME_DIR`、bootstrap Python / uv cache 均在该目录中；使用官方 `. .\activate.ps1` 准备，不写入个人配置或用 pip / uv 修改 PM 环境。初次 GitHub release 直连被重置；使用用户已配置的本机代理返回 200，本次只为准备进程设置代理。PM lock SHA-256 为 `49b79259220160f147255078a19af541a5f328d3871c8041cc1eb909d19eb549`，uv lock 为 `95a3082629ffecdabb1bad0880ccf5a237d47cd8fb67d86094f6d3d331f4eeac`；锁定 uv `0.12.3` / Python `3.14.7+20260901`，实际 Python `3.14.7`。

应用环境同步成功，receipt 为 `pm_20261013T101305Z-sync-35160-1af7be92e2c1433b8117098d311ac4aa.json`，`venv_rebuild.ok=true`。从 PM `facts.json` 读取实际解释器：`installs/df016e59190fdbc4/environments/eefbf627c51f49329d8fb71b8cf393fc/venv/Scripts/python.exe`（相对上述临时数据根）；直接导入 `run_agent.AIAgent` 并运行下述合成任务成功。不能据此声称完整激活成功：随后独立开发测试环境的 `uv lock` 因 Python 3.14 分支 `resvg-py==0.4.0` 缺少 publish time，与 `exclude-newer` 时间筛选冲突而失败，准备脚本退出 1，`activate` 报 `setup failed; shell environment unchanged`。本地 PM 文档确认应用环境不选 dev / test 两组，而开发激活还会准备测试解释器。未修改上游依赖、锁文件或时间筛选；Step 2 仍未完成，应用解释器也尚未冻结为产品启动组合。

Step 3 部分实测：用上述 PM 应用解释器执行 `.artifacts/initial-development/probe-hermes.py`，退出 0。本机合成 OpenAI-compatible endpoint 收到两次 `/v1/chat/completions`，均为流式；实际调用一次 `distill_probe_echo` 并得到预期终结 JSON。显式 `provider=custom` / `api_mode=chat_completions`、工具注册、`run_conversation()` 和 `close()` 已验证。独立配置关闭压缩、动态 `tool_search` 桥及自动资源，模型实际可见工具仅合成 echo。默认动态桥会改变工具呈现，产品适配不能只指定工具集而忽略该配置。完整 system / tools 请求保存在忽略目录的 `hermes-requests.json`；没有真实模型凭证，实际模型流式工具往返尚未执行，Step 3 保持未完成。

Step 4 部分实测：同一脚本加 `--retry-once` 让首个流式请求返回合成 503，退出 0。实际入口收到三次请求，stream 依次为 true / false / true，工具只执行一次，最终 JSON 正确；对应上游 `agent/chat_completion_helpers.py` 的 `_unmask_server_error_with_nonstreaming()` 恢复路径。失败尝试和非流式重试都必须由转发入口计数，不能依赖迭代数。记录保存在 `hermes-requests-retry.json` / `hermes-results-retry.json`；没有实现产品转发或预算持久化，第 16 / 17 次、重启、压缩 / 其他辅助活动与双名额并发仍待验证，Step 4 保持未完成。

Step 6 部分实测：临时文件的既有写句柄导致提交锁拒绝（32）；提交句柄持有期间外部覆盖 / 替换 / 删除 / 改名被拒绝；通过同一句柄写入并 `FlushFileBuffers` 后文件身份保持；新文件被用户抢占时 `CREATE_NEW` 返回 80 且用户内容保留。锁住 junction 指向的真实目录不能阻止删除 junction；带 `FILE_FLAG_OPEN_REPARSE_POINT` 打开 junction 自身并禁止共享删除时，其删除返回 32。产品仍须逐级保护 / 校验路径，无法确认时拒绝提交。probe 未验证多文件中断恢复、全部路径竞争或 OS 写隔离，Step 6 及 G1 保持未完成。

一次性脚本和合成输出保留 `.artifacts/initial-development/`。基线验证：`python tests/test_capture.py` 退出 0，`python .codex/hooks/test_pre_push_guard.py` 的 16 项测试 OK；`python .artifacts/initial-development/probe-win32.py` 退出 0，输出包含上述 junction 反例。未增加永久文档测试或改动上游源码。

Step 5 部分实测：`python .artifacts/initial-development/probe-job.py` 退出 0；父 / 子 / 孙三个进程均在关闭 `KILL_ON_JOB_CLOSE` Job 后进入 signalled 状态，随后心跳字节保持，证明这组进程树确实停止，不证明文件隔离。

MXC 验证包位于忽略目录，仅用于候选 probe；npm `@microsoft/mxc-sdk@1.0.0` tarball 的 SHA-512 与 registry 的 SRI 一致，内含 x64 `wxc-exec.exe` 的 Authenticode 验证通过，未执行安装脚本或 host-prep。直接原生 executor 不需要 Node SDK 的 Koffi / node-pty 依赖；SDK 若采用，需另核 Windows stdio 的 Node 最低版本，而非只看 package engines。

完整 MXC 请求的 probe 退出 0 但 JSON 包含 error，dry-run 退出 1：`network.ingress.hostLoopback='allow' is not supported by this version of Windows`。因此不能仅用 probe 退出码放行。仅用于文件边界定位的 `--file-only` 策略显式拒绝 host loopback：补足隔离环境的 `LOCALAPPDATA` 字段后，probe / dry-run / 真实执行均退出 0；选择 `base-container`、`needsDaclAugmentation=false`。保护文件可读、不可改写（errno 13），允许目录可写，嵌套子进程也保持该边界；原合成 sentinel 字节保留。该策略缺少产品所需 loopback，不作为运行基线。

Step 5 / G1 保持未完成。统一 Design T06 记录了 `WRITE_RESTRICTED` / Low integrity / Job 的替代候选和仅改任务目录 ACL 的范围，待用户确认后才验证新路线；不改主机 ACL、不启动普通无隔离进程来绕过。尚未验证 PowerShell / 孙进程写边界、外网、Hermes 在容器内运行及整体撤权窗口。

为区分策略校验与实际联网，另运行 `python .artifacts/initial-development/probe-mxc.py --network-test`：移除显式 hostLoopback 配置、保留 egress allow；probe / dry-run 成功，但隔离子进程访问受保护进程的合成本机 HTTP 服务超时，真实执行退出 1。普通进程以同样的 `ThreadingHTTPServer` / urllib loopback 方法作对照，读取成功、退出 0。该结果确认本次候选组合的模型转发路径未通，不能以省略该字段放行。

### 2026-10-14：模型、预算与替代隔离验证

用户批准验证 restricted token / Low integrity / Job 替代候选，并指定官方 `deepseek-flash` 作为本次真实模型。批准的是验证，未自动选定产品 runner。使用本机已有 pywin32 做一次性 Win32 探针；没有安装生产依赖、修改上游或调整真实工作目录 / 个人目录 / 系统设备 ACL。

Step 2 完成：官方 `python -m pm.cli install --trust-recorded` 未请求开发测试环境，退出 0；receipt 为 `pm_20261014T044905Z-sync-45736-1dc211f41042405cbd72510dacc0907c.json`，应用环境 `already in sync`。命令还在独立工具根准备官方固定的 agent-browser / cua-driver；它们不是 DistillAI 生产依赖或启用工具。实际应用解释器和 stamp 保持上述选择，导入检查再次退出 0、输出 `run_agent`，上游 Git 仍干净。依据本地官方 PM 文档，应用环境不选择 dev / test 两组；因此将 Step 2 从完整开发激活校准为应用准备 / 导入，属 Agent 闭环的技术事实澄清，不放宽 G1。2026-10-13 的开发测试解析失败保留，不声称修复了 activate。

Step 3 完成：`.artifacts/initial-development/probe-real-model.py` 的控制进程读取本次凭证，通过固定 `https://api.deepseek.com/chat/completions` 转发；Agent 子进程只取得 loopback endpoint 和内部任务令牌。协议为 Chat Completions，本次关闭 thinking、单次输出上限 1024；只发合成 echo 材料，执行白名单工具一次。两次流式生成均 HTTP 200，最终 JSON 符合预期，脚本退出 0；脱敏结果见 `hermes-real-results.json`。没有保存真实密钥、授权头或模型内部推理，也没有把此 probe 当成沙箱内模型验收。

Step 4 完成：`python .artifacts/initial-development/probe-budget.py` 退出 0。合成 provider 配合真实 AIAgent 循环：第 16 次返回有效终结 JSON；仍需第 17 次时，转发层在发出前拒绝，实际生成保持 16。Agent 与转发服务重新启动后，同任务仍为 16，新请求不发出。普通任务与完全无工具的筛选实例并行，两者首次请求通过同一屏障确认同时运行，独立计数分别为 2 / 1。共实际转发 35 次合成生成、拒绝 2 次；此前 503 的失败尝试 / 非流式恢复仍计数。压缩、记忆、后台审查、动态工具桥 / 扩展等未接管活动在此组合关闭；该结果验证接管能力，不表示产品调度、持久预算或转发模块已经实现。合成 forwarder 保存前锁内持久占用额度，证据见 `budget-results.json`。

Step 5 部分通过：`python .artifacts/initial-development/probe-restricted.py` 退出 0。仅在新建合成目录准备明确的当前用户 ACL，分别给本任务副本 / 临时目录和另一任务分配独立 SID；使用 `DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED`、Low integrity、父目录 `FILE_DELETE_CHILD` deny 与 token default DACL。Python 父 / 子 / 孙均能读合成保护文件，只能写本任务目录；覆盖 / 删除 / 改名、另一任务目录 / 临时目录、junction 指向保护目录的写入被拒绝，新建保护文件硬链接被拒绝。PowerShell 真实读写同样保持边界，loopback 成功，外网 TLS 取得 401（未发送认证或生成请求）；关闭 Job 后三个活动进程均停止、心跳不再变化。根目录 DACL ACE / mandatory label 的有效策略恢复，无残留能力 SID / Low 标签，随后删除已核对的私有测试目录。SDDL 的自动继承 / 空 SACL 表达可被系统规范化，未声称描述符字节完全相同；结束前确认的是有效策略。

Step 5 仍失败：`python .artifacts/initial-development/probe-read-boundary.py` 退出 0是反例验证成功。只有 OWNER RIGHTS 的合成文件在普通 / 仅 Low token 下可读，在 WRITE_RESTRICTED token 下读失败；只对新建合成文件增加明确当前用户 read ACE 后恢复可读。普通令牌可读取的当前 PM 底层 Python 在替代 token 下同样不可读，venv launcher 和 Hermes 源码可读。`python .artifacts/initial-development/probe-restricted.py --hermes` 真实启动失败、退出 1，venv launcher 报无法找到已存在的底层 Python；失败输出保存在 `restricted-hermes-results.json`，授权恢复与私有目录清理仍成功。这条候选不能在仅调整任务目录 ACL 的批准范围内运行当前 Hermes，也不能声称符合不额外限制读取的契约；不修改被保护路径 ACL 来掩盖反例。

G1 保持未通过，Step 5–7 不勾选。下一候选是 MXC 加 stdio 模型请求转发；具体边界已同步统一 Design T06，待用户确认验证。没有启动产品维护任务、进入 Task 2 或执行 Commit / Push。

本轮同步检查：31 份 Markdown、384 个本地链接 / 锚点无错误，九份 Plan 为 approved，完成 / 未执行步骤为 4 / 136；跟踪改动的密钥 / 私钥模式扫描无发现，`git diff --check` 退出 0。所有一次性探针与 PM 安装进程均已结束；没有新增永久测试或生产依赖。


### 2026-10-14：OS 写隔离移出初版

用户明确要求本次不实现写隔离，后续 Issue 再做；与统一 Design `material_revision: 1` 对齐。Task 1 Step 5 改为普通进程停止验证，文件映射和永久测试组移除写隔离 runner / OS 越界写拒绝；Task 2 的任务副本、业务路径校验、基线冲突、提交句柄与恢复不受此功能延期影响。Task 3 保留普通独立 AIAgent、模型转发 / 16 次预算和业务授权，权限收紧仍注销任务并停树，不修改 OS ACL。MXC / token / 沙箱 stdio 后续独立 Issue 再决定，现有忽略目录探针仅为历史证据。

不将范围延期标成隔离测试通过：当前任务拥有普通用户文件权限，程序扫描 / 恢复只覆盖登记的副本与发布，不能保证阻止或回退自由命令的其他位置写入。没有创建远端 Issue、安装新依赖或开启新隔离验证。


修订 1 的 Step 5 验证完成：再次运行 `python .artifacts/initial-development/probe-job.py` 退出 0，普通父 / 子 / 孙三个进程均 signalled，关闭 Job 后心跳字节保持。普通 AIAgent 与 loopback 模型转发沿已通过的 Step 3 / 4；本次 Job 只作为停树证据，不称为写隔离通过。当前完成步骤 5 / 140，待执行 135；Step 6 / 7 保持未完成。

### 2026-10-15：G1 冻结及存储实施

用户再次要求按 Plan 执行并继续。Step 6 完成：临时探针验证原文件占用、共享模式阻止覆盖 / 替换 / 删除 / 改名、同句柄写入 / Flush 后身份不变、排他新建拒绝用户抢占、删除备份恢复拒绝覆盖新用户目标。产品回归进一步发现只读共享的目录句柄会阻止正常子项改名；改为目录禁止共享删除、文件禁止共享写 / 删除，并通过原生 `NtCreateFile` / `NtSetInformationFile` 相对固定父目录对象执行。禁止重解析、校验实际身份，不沿可能重指的路径字符串重新发布；临时合成测试实际把固定父目录改成 junction，证明新增文件未写入其外部目标。改名信息缓冲区补足 UTF-16 终止字符后，碰撞返回拒绝，永久用例保护此行为。

Step 7 完成：冻结 Hermes 源码 `a7b2ba02e3b9bb95d0cac87a6312cc82a3bc3eed`，官方 PM 应用 receipt `pm_20261014T044905Z-sync-45736-1dc211f41042405cbd72510dacc0907c.json`，PM / 上游 uv 锁摘要及 stamp 沿 10-14 记录。选择共用已准备应用环境，实测 Python 3.14.7；产品支持 Python 3.13+。`pyproject.toml` 固定 MCP 2.0.0，`uv.lock` SHA-256 `e757fb9156c5b78a96016e4b61212ca4196b580d1752829d9b435ec69e301386`；32 个 SDK 依赖版本逐项与 PM 环境一致。只在产品生成锁，没有用 pip / uv 修改 PM 环境。官方 `MCPServer` + `ClientSession` 的 stdio 初始化、列工具和一次结构化 echo 往返退出 0，协议 2025-11-25；不是手写协议或产品 M07 验收。

任务启动组合为上述 PM 解释器运行独立 Python 子进程；先等待输入，控制层分配 KILL_ON_JOB_CLOSE Job 后才释放输入。产品 `ProcessJob.stop()` 终止并查询整组 active process 为零，之后才能恢复或释放名额；父 / 子 / 孙心跳永久测试通过。正式 `start.ps1` / task-child 入口仍按 Task 3 / 4 创建，不把探针命令称为后台启动命令。

Task 2 已实现：数据根与 msvcrt 锁、同目录同步 JSON / 不可变 SHA-256 字节版本、独立字节副本和基线、源身份 / 元数据 / ADS / 链接检查、prepared 清单 / applying / applied / committed、排他新增、原句柄修改、原件同目录备份删除、逐项恢复和 recovery_conflict。新增目录由排他创建返回的句柄登记；不支持原目录结构删除及无法恢复的特殊元数据。未变化文件不重写，后续用户编辑、部分写入的不确定版本、备份冲突均保留；committed 恢复返回原清单供运行层补后置登记，绝不重新模型执行。

Task 2 Step 1 / 2 / 6 完成。Step 3–5 的基础存储逻辑已通过，但业务模块归属 / 字段校验、权限 / episode 修订绑定、处理位置、依赖和索引后置登记将由 Task 3 及对应业务模块接入，保留未勾选，避免将独立库通过当成完整业务发布闭环。当前 Task 1 全部完成，修订 1 的 G1 通过；累计 10 / 140 项完成。

验证：`PYTHONPATH=src` 下 `python -m unittest discover -s tests -p 'test_product_*.py' -v` 在本机 Python 3.13.5 及 PM Python 3.14.7 均为 24 tests / OK，无 skip；`uv lock --check --offline` 退出 0。存储组 18 项保护文件差异、用户冲突、部分发布 / 日志中断、删除身份恢复、历史内容及私有状态边界；Win32 组 6 项保护共享句柄、创建 / 改名碰撞、目录竞争、junction 重指和整树停止。源 / 数据 / 依赖状态与运行文档、Python / CI 规则同步；CI 只执行离线标准库组，不安装 Hermes / 个人凭证或调用模型。

### 2026-10-15：任务、产品适配和后台启动

Task 3 核心已实施：固定输入及 Prompt 内容版本、配置快照、登记去重、未开始的同 session 连续增量合并、普通 / 筛选双名额、查询在下一调度点优先、取消 / 权限收紧、持久请求预算、结果与提交后登记 / 恢复。增量合并保留原输入版本和去重别名，已经运行或跨缺口 / session 的输入不合并。恢复冲突范围暂停后续写任务；已 committed 的后置登记失败保留 validating，恢复重放登记而不重跑模型。M04 / M05 的 episode 字节版本在开始及提交前校验，提交窗口额外持读句柄，防止检查后被外部编辑器替换。

配置已覆盖批准字段与初始值，错误保留原值，空脱敏 key 不覆盖原凭证；配置版本在任务创建时固定，poll 下一等待读取现值，工作路径收紧注销授权并停树。路径先逐级拒绝 reparse，再用实际目录句柄的完整名称校验授权，避免点段 / 短路径别名绕过私有目录。不可变历史只保存脱敏配置与凭证引用；实际凭证留在私有 config 历史，模型子进程只接收任务 token。

`hermes.py` 为唯一直接 AIAgent 导入 / 构造 / run_conversation / close 入口。普通独立子进程用 `-I -B` 和明确 source / src 路径启动，先等待 stdin，控制层分配 Job 后才发送载荷；清除继承的 Hermes / terminal 配置和凭证变量，使用独立 HERMES_HOME、已准备 HERMES_RUNTIME_DIR 及 local backend / 副本 cwd。固定源码自定义 dotenv loader 不遵循 PYTHON_DOTENV_DISABLED，因此在适配进程内关闭该配置发现入口，不修改上游文件。维护工具实际为 read_file / write_file / patch / search_files / terminal / process_manage；query 只注册所需快照读取，screening 无工具。实际注册清单出现其他工具时在请求前拒绝。

产品模型入口固定 task / 协议 / 模型 / 路由，锁内持久占用额度后发送，不转发客户端授权头，不跟随重定向。已明确未建立连接 / DNS 失败释放对应占用，超时等未知是否发出保守计数；每次失败生成、非流式恢复和工具后续推理都独立计数。历史保存实际系统规则、工具定义和输入请求版本，剔除 provider 内部推理字段，结果正文另存版本；不保存授权头。

真实产品适配验证：`python .artifacts/initial-development/probe-product-hermes.py <固定源码> <PM 解释器>` 退出 0。真实 AIAgent + 产品 Runtime / 模型转发 / Job / Store 在临时目录运行六场景，实际 provider 生成 41 次：screening 1、query 2、维护 3（write_file 与 terminal 各一次，默认 cwd 等于副本，两个文件由程序发布）、503 后恢复 3、第 16 次有效结果成功、第 17 次需要生成时失败且 provider 保持 16。源码 SHA / 环境未变，没有再次请求真实收费模型；真实 DeepSeek 工具往返仍沿此前 G1 证据。脱敏结果和合成全文保存在忽略目录 product-hermes-results.json / product-hermes-requests.json。

Task 4 基础已实施：同数据根跨进程启动锁、完整实例 / PID / 协议 / 地址 / 授权 health 核对、八条基线 HTTP、独立模型路由、Host / Origin / body 限制和全局 Stop。stop 先拒绝新任务、等整树及恢复完成，再关闭 HTTP / 释放实例锁；未确认停完不释放写名额。源码和解释器在 Check 中核对固定 SHA、PM 归属、SDK 锁；不下载或安装。窗口隐藏、后台与启动入口生命周期分开。

实际 `scripts/start.ps1 -Action Check / Serve / Stop` 使用固定 source、上述 PM Python 和临时数据根执行均退出 0；跨独立命令 Check 读到同一实例，重复 Serve 复用；Stop 后再 Serve 的实例 ID 改变，最终 Stop 成功。首次遇到 Windows venv redirector 的实际服务 PID 与 Popen PID 不同，已用独立启动关联标识识别所属实例；并发入口需确认竞争子进程已退出，防止晚启动的第二实例。没有以端口或 PID 单独认作同一后台。

最新离线组：标准库 62 tests / OK，无 skip；Python 3.13.5 为 12.469s，PM Python 3.14.7 为 12.429s。当前 Step 3–5 的业务字段 / 归属和实际处理位置、依赖、索引仍在 M03–M07 验证；Task 3 Step 2 的最新修订依赖登记也随 M03 接续。Check / Serve / Stop 已实现，Mcp / Web 动作分别随 M07 / M08 补齐，Task 4 Step 3 不勾选。当前业务处理器尚未就绪时拒绝执行，不使用假处理器宣称产品可用。CI 仅修改离线命令，未触发 GitHub 运行，也未做远端写入。

### 2026-10-16：业务接入复核与基础收尾

已对照最新源代码和两解释器 160 项离线结果核对 Task 2 Step 3–5、Task 3 Step 2、Task 4 Step 3：业务副本 / 扫描、逐项清单 / 句柄提交 / 恢复、处理位置和后置登记、双名额与查询优先、全部启动动作已接入。旧 episode 版本取消、M04 索引失败后补建不重跑、MCP 查询独立取消、当前配置和来源保护均有永久契约及实际探针。真实后台 Web 启动 / 一次性引导 / 停止复跑通过；当前 SDK 冷启动限制仍由 M07 记录，不把现有 Mcp 命令的存在当作冷启动成功。

本模块 25 / 25；Plan 改为 implemented，仅表示当前修订范围的运行基础完成，不表示整体产品或 G2 / G4 完成。普通用户进程权限和写隔离延期保持。
