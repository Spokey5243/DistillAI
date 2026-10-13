---
version: v0.1.0
issue: 4
branch: codex/4-initial-development
workflow: exploratory
status: draft
decision_mode: user-approved
---

# M01：运行、执行边界与保存 Implementation Plan

> 执行者使用 `executing-plans` 按 checkbox 推进，默认主 Agent 实施；本 Plan 批准前只做文档工作。

## 来源与目标

依据[统一 Design M01](../../design.md#runtime-contracts)、[技术选择](../../design.md#technical-selection)、[总 Plan](../../plan.md)。完成一个常驻 Python 控制层，直接在独立任务子进程调用 Hermes `AIAgent`，可控制调用预算、真实写权限、冲突安全发布和崩溃恢复。它是后续七模块的唯一共用运行基础。

## 文件映射

以下均以仓库根目录为基准。

| Create / Modify | 职责 |
| --- | --- |
| `src/distillai/__init__.py`、`__main__.py` | 包、启动和 task-child 入口 |
| `src/distillai/runtime.py` | 单例、任务登记 / 固定输入 / 调度 / 停止 / 计数 / 依赖 |
| `src/distillai/storage.py` | 不可变版本、任务副本、变更扫描、发布 / 恢复 |
| `src/distillai/windows.py` | 文件身份 / 共享模式、写隔离 runner 窄适配和进程树停止 |
| `src/distillai/config.py` | 版本配置、校验、脱敏、即时 / 延后生效 |
| `src/distillai/server.py` | 本机 HTTP、请求授权、路由 / 限额 / 错误 |
| `src/distillai/hermes.py`、`tools.py` | AIAgent 直接调用与工具清单；任务模型转发 |
| `src/distillai/prompts/common.txt` | P01 正式批准后的全文 |
| `scripts/start.ps1`、`pyproject.toml`、产品依赖锁文件 | 来源定位、已准备环境启动及固定产品依赖 |
| `tests/test_product_storage.py`、`test_product_runtime.py`、`test_product_config.py`、`test_product_http.py`、`test_product_windows.py` | 永久契约组；Windows 组需实际能力可用 |
| `.gitignore`、`README.md`、`.agents/rules/python.md`、`github-actions.md`、`.github/workflows/ci.yml` | 真实运行 / 检查说明和离线 CI |

一次性 probe 放 `.artifacts/initial-development/`，不形成产品诊断框架；已有采集插件、开发 Hook 和 Hermes 上游代码不改。

## Task 1：冻结可工作的执行组合

先通过 G0；本任务运行结果是 G1 的证据，不自动授权安装额外框架、改主机 ACL 或选择新长期技术路线。

- [ ] **Step 1：记录本机和本地源码。** 记录 Windows build、Python / 架构、Hermes 当前 SHA 和与 Design 查证 SHA 的差异。核对当前源码的 Library、PM、provider、工具注册和资源加载入口，不从旧 Pi / TS 提案复制参数。

```powershell
git -C E:\JourneyIntoAI\DL_and_LLM\projects\hermes-agent rev-parse HEAD
python --version
Get-ComputerInfo -Property WindowsVersion,OsBuildNumber,OsArchitecture
```

预期：得到明确版本事实；源码路径只用于本机验证，不写死在产品中。

- [ ] **Step 2：在独立数据根准备 Hermes 环境。** 依据该固定源码的 PM PowerShell 开发流程，设置专用 `HERMES_HOME` / `HERMES_RUNTIME_DIR`，dot-source `activate.ps1`；记录 PM receipt、实际解释器、导入路径与锁文件摘要，不用 pip / uv 直接修改 PM 环境。先确认准备动作及下载范围在已批准的执行范围内。

```powershell
$env:HERMES_HOME = Join-Path $env:TEMP 'distillai-hermes-validation'
$env:HERMES_RUNTIME_DIR = Join-Path $env:HERMES_HOME 'tools'
Push-Location E:\JourneyIntoAI\DL_and_LLM\projects\hermes-agent
. .\activate.ps1
python -c "import sys; from run_agent import AIAgent; print(sys.executable); print(AIAgent.__module__)"
Pop-Location
```

预期：激活成功后退出 0，输出实际解释器和 `run_agent`；此导入检查不证明已执行模型任务。失败时记录 PM / 依赖事实，不改用 Hermes CLI。

- [ ] **Step 3：验证最小 AIAgent 任务。** 在忽略目录写一个 probe，直接导入 AIAgent、设置 `quiet_mode=True`、显式模型 / 固定本机转发 endpoint / 工具集，调用 `run_conversation()`。由本机合成服务依次返回工具调用和终结 JSON；记录实际构造参数、工具注册方法、关闭方法、缓存 / 压缩 / retry 路径及实际 system / tools 全文。禁用个人配置发现、自动扩展 / MCP、并行子 Agent、无额度后台活动和无需的功能。最后用用户实际配置的模型核对一次流式工具往返，凭证只在控制层。
- [ ] **Step 4：验证请求计数接管。** 本机合成服务记录每次实际到达的生成请求；覆盖正常结束、工具后继续、失败重试、压缩 / 辅助请求、第 16 次完成、第 17 次拒绝、同任务重启。将各调用导向受保护转发入口；无法接管的自动模型活动关闭。对未知是否已发出记录保守计数；不把 AIAgent `max_iterations` 当外部请求额度。完成一次“并发普通任务 + 独立筛选”验证；单槽模型服务实际排队只记技术约束，不承诺服务端抢占。
- [ ] **Step 5：验证 OS 写策略与停止。** 对候选 MXC / 框架提供的实际 Windows 写隔离记录 probe、隔离层、告警和完整策略。分别尝试 Python 文件写、框架文件工具、PowerShell、子 / 孙进程写保护目录与允许目录；读取允许；模型转发 loopback 和外网可用。撤销授权后停止整个树并确认无继续写入。Job / abort 只能证明生命周期，不能单独证明文件隔离。无法保持只限写口径或需要新增长期 runtime / 管理员 ACL 时，先将具体方案和效果同步 Design 供确认，不直接降级为普通进程。
- [ ] **Step 6：验证 Win32 提交窗口。** 在临时目录用 `CreateFileW` 共享模式、文件 / 目录身份和落盘操作实际检查：用户占用、比较后替换、删除 / 改名、路径被 junction 重指、新文件抢占、部分发布后再次用户编辑。记录通过句柄执行的操作及不能保证的窗口；无法可靠阻止目标替换就拒绝发布。
- [ ] **Step 7：冻结环境和依赖。** 首选不修改 PM 源环境即可共用兼容依赖的最小组合；产品 MCP 依赖若与 PM 冲突则分离控制层环境，子进程仍用 PM 解释器。记录固定源码 SHA、PM receipt、产品 SDK 版本 / 锁、runner 安装与启动方式，再把下面启动命令改成验证后的实际命令。G1 未通过不执行具有任意写 / Shell 能力的产品维护任务。

能力矩阵的每项记录实际命令、退出码、观察文件哈希 / 进程状态及通过 / 失败；只读文档和假 runner 不构成放行结果。trajectory 训练方向保留；不在本任务实现训练导出或 RLVR。

## Task 2：版本、副本和冲突安全提交

- [ ] **Step 1：建立最小持久布局。** 用 `DISTILLAI_HOME` 定位 config、tasks、versions、commits、workspaces 和程序事件；默认 `.distillAI`。内容版本用不可变字节 SHA-256；JSON 保存使用同目录临时文件、flush / fsync、锁内替换；追加事件用 JSONL。将 `.distillAI/`、既有 `.distallAI/`、凭证、PM 数据、虚拟环境和临时证据纳入提交排除。
- [ ] **Step 2：先写提交回归用例。** 临时目录构造新增、修改、删除、改名、未改变文件和同期用户修改；准备清单后模拟逐项中断及用户再编辑。断言失败保留用户版本、业务 / 处理位置不提前成功、历史前后版本可读取。新测试补齐现有采集测试没有覆盖的多文件发布 / 恢复风险。
- [ ] **Step 3：实现副本和变更扫描。** 创建独立字节副本，记录基线存在性、哈希、元数据和原授权路径；来源一致读失败明确报错。任务停止后扫描真实差异而非信任模型文件列表；禁止新增链接、特殊设备、NTFS 附加流和不能恢复的元数据修改。校验文件身份、相对路径、结构、来源及业务模块归属。
- [ ] **Step 4：实现 prepared → committed。** 保存前后不可变版本和逐项状态；取权限 / 提交锁核对授权、当前 episode 输入修订和原文件基线。使用 Task 1 验证的句柄适配持有目标保护，新文件排他新建；未改变文件不写回。整批完成才标 committed；完整持久化后推进处理位置 / 依赖，再触发索引补建。
- [ ] **Step 5：实现崩溃恢复。** 读取同一提交清单补完业务已 committed 的后置登记，禁止重跑模型；提交未完成时只撤销仍等于本次发布版本的项目，用户再编辑或恢复失败进入 `recovery_conflict` 并暂停冲突范围。运行失败仅丢弃未发布副本，保留任务和版本证据。不能声称外部编辑器可原子看到整批文件。
- [ ] **Step 6：运行存储组和 Win32 组。**

```powershell
python -m unittest discover -s tests -p 'test_product_storage.py' -v
python -m unittest discover -s tests -p 'test_product_windows.py' -v
```

预期：离线提交用例 `OK`；Windows 组在具备真实策略的环境验证写 / 句柄边界。能力缺失明确 skip 原因并保持 G1 不通过，不能把 skip 当安全验收。

## Task 3：任务调度、预算、配置与 Hermes 适配

- [ ] **Step 1：写任务状态 / 预算用例。** 相同 kind / 固定范围 / 版本 / 触发登记复用任务；仅未运行增量可合并；第 16 次生成返回有效结果成功，第 17 次不发出；重启不清计数；取消 queued 任务不启动进程；取消 running 任务等进程树停完才释放名额；M04 / M05 旧 episode 输入不能发布。
- [ ] **Step 2：实现任务状态和双名额调度。** 一个普通执行名额、一个当前轮筛选名额；查询在下一调度点优先于普通待办，不抢占正在运行者，同级登记顺序。持久 queued / running / validating / recovering / 终态；绑定固定输入、配置 / Prompt / 权限版本。只以实际提交 / 结果保存判成功，空结果可成功。
- [ ] **Step 3：实现受保护模型转发。** 每个请求检查任务授权、许可协议 / 模型 / 路由，发出前锁内持久占用额度；从配置取得真实 key，载荷只持有内部引用 / 任务 token。禁止任意 URL 代理、泄露授权头和模型内部推理。源连接失去授权时拒绝新请求；最后允许请求正常返回 / 校验，仍需新增请求才预算失败。控制层与子进程协议按 task_id 关联并验证大小 / 字段。
- [ ] **Step 4：接入独立 AIAgent 子进程。** `hermes.py` 唯一直接导入、创建 / 调用和关闭 AIAgent；业务模块只提供任务载荷和工具清单。运行资源只读，HERMES_HOME 使用产品隔离数据与任务临时状态，不执行个人 / 工作目录配置。维护带副本 / Shell，query 只读工具，筛选完全无工具；全部注册名由能力验证结果固定。
- [ ] **Step 5：实现配置校验和生效。** 沿 Design 的全部字段与初始值：调用 16、poll 1 秒、buffer 3、refresh 3、外扩 3600 秒 / 10 条。模型协议参数按支持范围验，非法保持旧版本并返回字段错误。新任务固定配置；poll / 周期下一判定生效且不清进度；工作路径扩大用于新任务，收紧立即注销授权、停止树后恢复。读配置遮蔽 key，Web 新输入可写 key，空的脱敏显示不能覆盖原 key。
- [ ] **Step 6：发布 P01 和执行历史。** 从批准文本创建 common.txt，将实际共用 Prompt、业务 Prompt、工具定义、输入 / 输出引用、计数 / 错误 / 恢复、当时配置脱敏版本入不可变历史；没有工作不调用模型，不使用无限 Agent 对话承载业务连续性。
- [ ] **Step 7：运行任务和配置组。**

```powershell
python -m unittest discover -s tests -p 'test_product_runtime.py' -v
python -m unittest discover -s tests -p 'test_product_config.py' -v
```

预期：上述契约 `OK`，无效配置和恢复不重置预算；再复核 Task 1 真实工具 / 模型请求，mock 结果不能替代 G1。

## Task 4：单例、本机接口和启动脚本

- [ ] **Step 1：实现单例与启动锁。** 按数据根保存实例 ID / PID / 协议 / 地址 / 授权，启动前验证完整身份和 health，不能只认端口或 PID。后台选可用 loopback 端口，Hook / MCP 退出不关闭；Stop 先停止新任务、停树 / 恢复后退出。
- [ ] **Step 2：实现 HTTP 契约。** 用标准库线程 HTTP 保持 worker / 模型 I/O 不阻塞 health / 配置；绑定 `127.0.0.1`，验证本机授权、Host / Origin、体积和路由，固定返回 schema / 错误。实现 Design 八个基线路由，cancel 的 `202` 只表示正在处理；查询任务不存在 404、配置版本冲突 409。任意材料不拼成 Shell。
- [ ] **Step 3：实现启动接口。** 创建总 Plan 中定义的 `start.ps1` 动作和 `__main__` 模式：显式定位 Hermes 源码与已准备解释器、加入产品 src；检查不自动安装或激活下载。环境准备单独按 Task 1 文档执行，后台启动使用隐藏窗口 / 无窗口子进程，不启动 Hermes CLI 或重复 worker。
- [ ] **Step 4：写并运行 HTTP 契约测试。** 覆盖伪造 PID / 同端口其他进程、多入口竞争启动、服务恢复、未知路由、无授权 / 外部 Origin / 非法 Host、超大 body、health 不被慢任务阻塞、显式退出后下次重新启动。

```powershell
python -m unittest discover -s tests -p 'test_product_http.py' -v
```

预期：`OK`；真实后台启动后用脚本 `Check / Serve / Stop` 验证一实例和退出恢复。

- [ ] **Step 5：同步运行文档和离线 CI。** 记录经验证的准备 / 启动 / 检查 / 退出命令、源与数据边界、受支持组合；CI 增加标准库产品测试，不安装个人 Hermes / 模型密钥，不改现有触发器 / token 权限。需要 SDK 协议组时只按产品锁安装最小控制层依赖，Hermes 实机组保留本地证据。同步 Python / CI 规则从“无产品环境”到真实状态。

## 测试必要性与一次性验证

| 永久组 | 保护的未来回归 | 一次性验证 |
| --- | --- | --- |
| 存储 / Win32 | 覆盖用户编辑、错误恢复、位置提前推进、链接绕过与未停止树继续写 | 当前 Windows / runner 完整策略、实际占用和提交窗口 |
| 任务 / 配置 | 同任务次数清零、末次请求被误中断、超额生成、配置失效、撤销不即时、查询抢占 | Hermes 内部 retry / 压缩真实路径、选定模型及单槽服务并发 |
| HTTP | 假实例被复用、外部授权绕过、慢任务堵控制入口 | 固定 SDK / 环境安装与真实启动组合 |

现有 test_capture 和 Push Guard 未覆盖上述产品契约；产品测试使用临时数据与本机合成 provider。依赖数量、文件名、Prompt 全文相等和安装位置不做永久断言。

## 依赖、偏差与状态

前置 G0；Task 1 输出 G1。未固定的 runner / MCP / 环境不是隐藏实现假设，重大新方案先同步 Design。当前无业务偏差；执行后将证据和批准范围写在本节。本 Plan 为 draft，全部任务未执行。
