# 初版设计的调研依据与历史候选

[返回任务入口](../README.md)。本文件保留 R01–R06 的历史源码核对和候选。2026-10-10，当前产品契约以 [统一 Design](../design.md) 为准；Honcho 的 `.sent` / 上传锁与确认仍为参考事实，DistillAI 已由 M02 改为共享本地队列。旧伪代码、Prompt、NetworkX 与问题列表描述当时方案，不作为当前修改入口。Pi / TS 已重新开放，沙箱只限写；当前 DeepSeek / Pi / Hermes 及本地 LLM 比较见[后台运行第 4 轮](../../../../research/runtime/round-4.md)，第 2 / 3 轮保留历史技术依据。

<a id="research-records"></a>

## 五、调研依据与历史候选

| ID | 调研内容 | 对应设计或选择 |
| --- | --- | --- |
| [R01](#capture-reference) | Honcho 采集字段、Hook、伪代码、完整性与锁 | D01 / T02 |
| [R02](#episode-history) | episode 概念来源与历史修正 | D02 |
| [R03](#runtime-reference) | Pi 接入可行性与早期图查询草案 | T02 / T03 |
| [R04](#prompt-injection-research) | Prompt 注入平台机制与本地核对 | D05 / T04 |
| [R05](#extraction-research) | 跨项目提取机制与调研入口 | D03 |
| [R06](#openmaic-methods) | OpenMAIC 方法核对与适配依据 | D04 / D06 |

本节保存来源事实、技术可行性与方案修正。参考系统的配置与行为不自动成为 DistillAI 的执行契约。

<a id="capture-reference"></a>

<details>
<summary>R01：Honcho 采集字段、Hook、伪代码、完整性与锁</summary>

##### 文件内容、key 与字段参考

下面按 Honcho 源码补充与已确认文件名对应的内容。文件名和阶段语义已确认，条目扩展字段、配置内容和恢复契约仍待设计。

| 文件 | Honcho 实际内容 | 更新时机 |
| --- | --- | --- |
| `queue/<key>.jsonl` | 每行一个 `{role, text, at?}`；role 为 user / assistant / tool | capture 或 observe 追加选定材料 |
| `cursors/<key>.json` | `{count, at}`；count 为已捕获的筛选后用户 / 助手消息数，at 为游标更新时间 | 新消息入队后更新；工具摘要不计入该消息计数 |
| `queue/<key>.sent` | 纯数字文本；已成功交付的原队列条目数 | 每个完整队列条目批次获接收确认后更新 |
| `queue/<key>.lock` | 交付进程 PID，纯文本 | 建立交付互斥时创建，交付退出时释放 |

以下仅为合成格式示例，展示不同条目类型，不代表实际采集次序：

```jsonl
{"role":"user","text":"用户消息示例","at":"2026-10-04T08:00:00Z"}
{"role":"assistant","text":"助手消息示例","at":"2026-10-04T08:00:05Z"}
{"role":"tool","text":"ran: python example.py","at":"2026-10-04T08:00:10Z"}
```

与这三种条目对应的捕获计数可以是 `{"count":2,"at":"2026-10-04T08:00:15Z"}`：两个正文消息计入 count，工具摘要另在队列内。`.sent` 若为 `2`，表示当前队列前两个条目已获交付确认，不表示捕获两轮对话或已完成两次分析。队列含工具摘要时，消息捕获计数与队列交付计数本来就可能不同。

Honcho 的 `memoryKey()` 优先使用完整 Codex session_id，缺少时退到按配置派生的 Honcho session name；`safe()` 将字母、数字、下划线和连字符之外的字符替换为下划线。默认逻辑 session name 按工作目录生成，也可选择按分支或会话实例生成；它与本地文件 key 是两个用途，不应因为同项目可汇总就合并不同 Codex 会话的捕获游标。DistillAI 保留已确认的 session_id 优先方向，缺失标识、非法路径字符及转换碰撞的规则在 Design 中明确，不自动照搬 Honcho 的回退策略。源码：[memoryKey](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/config.ts:189)、[文件名转换](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/queue.ts:23)、[捕获游标](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/cursor.ts:28)。

Honcho 队列条目本身没有 session_id、turn_id、tool_use_id、event_id 或原始记录定位，session 通过 key 关联。DistillAI 是否扩展这些字段及怎样生成稳定源标识继续由 Q05 / Q15 决定；旧验证插件每次本地写入的 event_id 不能直接当成 AI 工具稳定事件 ID。`at` 描述源消息时间或工具活动记录时间，不能与落盘时间、接收时间、分析完成时间混为一谈。

Honcho 还在 `context/<key>.json` 保存 representation、peerCard、获取时间与 lastInjected，属于上下文缓存。这不是采集正文或发送进度；当前已确认采集目录不因此新增 context 子目录，其需要与格式归 Q14 讨论。统一数据根继续以 `DISTILLAI_HOME` 优先，未指定时使用用户目录下 `.distillAI`；它不指向插件安装缓存，也不构成旧测试数据迁移。源码：[上下文缓存](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/cache.ts:9)。

这里的 `codex` 区分材料的来源 AI 工具，不是区分 user / assistant 角色或后台 Agent 实例。Honcho 接入端用固定的 AI 工具名称组织子目录，数据根由用户目录或配置决定；DistillAI 沿用此分工。未来实际接入 ZCode、Claude 等 AI 工具时，可在同一根目录下增加 `zcode/`、`claude/`，当前只实现 Codex。不同 AI 工具的原始材料分开管理，同一用户的知识与用户模型仍由同一后台维护。

此前的 `data/sessions/<session_id>/events.jsonl / capture.json / processed.json` 候选已撤下：它无必要地更换了 Honcho 的文件组织，并把交付进度替换成处理进度。采用本地后端不构成这种替换的理由。

采集条目字段、来源标识、残缺行恢复和重复处理规则仍待 Q05 / Q15 明确；episode 及派生记录的目录、文件名与内容契约由 Q06 / Q15 确定，不由这份采集目录树预设。episode 的活跃记录、缓冲切分与收尾方向见 [D02](../design.md#episode-model)。

#### Honcho 源码核对与采集执行候选

2026-10-04，用户要求结合 Honcho 源码说明 Hook、同步 / 异步、伪代码、目录和文件名，并询问沿用用户目录下 `.distillAI` 统一管理的可行性。完整事实、提交与伪代码见 [Honcho 第 2 轮](../../../../research/honcho/round-2.md)。

核对事实：codex-honcho 注册五个事件，SessionStart / UserPromptSubmit 用于上下文，PostToolUse 本地追加工具摘要，Stop / PreCompact 共用 writeback。配置未开启 async；writeback 先捕获，再在 Hook 进程内 await 上传。rollout 每次全量解析，再用筛选后的消息条数取增量；捕获游标和发送进度分开。源码注释中的“后台”不能替代对调用链的核对。

##### Hook 事件与函数职责

下表为 codex-honcho `c17cbb2b4c7cf12172213345ae4c0d2a093d707b` 的实际配置。DistillAI 用途是当前讨论方向；Honcho 的超时、缓存策略和网络调用位置不自动成为本项目契约。

| Hook | Honcho 函数与触发条件 | 实际职责 | Honcho 超时 | DistillAI 用途 |
| --- | --- | --- | --- | --- |
| `SessionStart` | `recall()`；`startup / resume / clear / compact` | 创建并关联会话与参与者；读取 10 分钟内的上下文缓存，过期时重新查询；返回简短记忆与 MCP 提示 | 30 秒 | 可提供简短规则和 Skill / MCP 入口；不是首条问题采集入口 |
| `UserPromptSubmit` | `prompt()`；用户提交问题时 | 逐轮回注默认关闭；开启后只读本地缓存，跳过简短确认和已注入的相同内容 | 20 秒 | 当前方向为问题到达后由 LLM 条件筛选，有适用候选才注入；正文由 rollout 采集路线取得 |
| `PostToolUse` | `observe()`；匹配工具活动 | 固定规则生成摘要并追加队列；不调用模型或网络 | 10 秒 | 将选定工具活动加入同一采集队列 |
| `Stop` | `writeback()`；当前轮结束时 | 捕获 rollout 新增消息，随后在 Hook 进程内等待队列上传 | 30 秒 | 采集新增用户 / 助手文本；交付触发位置待定 |
| `PreCompact` | `writeback()`；`manual / auto` 压缩前 | 调用与 Stop 相同的捕获和上传流程，共用游标 | 30 秒 | 压缩前补采；不要求此时已有本轮最终回复 |

超时是配置上限，不是测得耗时。五个事件对应四个函数；真正追加会话正文或工具活动的是 PostToolUse、Stop 和 PreCompact。源码：[Hook 注册](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/connectors/codex.ts:40)、[SessionStart](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/recall.ts:21)、[UserPromptSubmit](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/prompt.ts:16)。

##### 会话正文与工具活动的选择

正文通过 AI 工具提供的 `transcript_path` 定位，不硬编码 Codex 会话文件目录。Honcho 每次全量解析 rollout，保留 `response_item` 中 `payload.type == message`、角色为 user / assistant 的消息；从字符串或 input_text / output_text / text 块收集文本，保留源记录时间。正文不包含这条路径跳过的推理、工具调用及非文本块，也没有按 assistant channel 限制为最终回复。

Honcho 对用户角色文本只过滤代码列出的前缀标签：environment_context、turn_aborted、user_instructions、apps_instructions、plugins_instructions、skills_instructions、collaboration_mode。它不是通用的作者识别器；其他自动注入内容不能仅因角色为 user 就认定为用户原话。过滤范围及用户材料识别仍属于 Q05。

工具活动使用固定代码规则，不使用 LLM 总结，也不使用完整 `tool_response`：

| 工具情况 | Honcho 的处理 |
| --- | --- |
| Honcho 自身 MCP 调用 | 跳过，避免记录查询自身记忆的循环噪声 |
| 部分只读 shell 命令 | 按命令前缀表跳过，包括 rg、cat、git status / log / diff 等 |
| 其他 shell 命令 | 记录 `ran: <命令前 120 字符>` |
| apply_patch | 从实现识别的补丁字段解析文件名，最多列出五个；解析不到时记为 `applied a patch` |
| 其他工具 | 记录 `used <工具名>` |

工具摘要没有说明完整输出、退出状态或用户实际使用了哪些结果；队列追加次序也不保证等于原始交互发生次序。PostToolUse 在工具期间先入队，Stop 才可能批量追加本轮正文，重建顺序需结合时间与来源。DistillAI 仍保留“默认活动摘要，必要结果或可追溯引用待确认”的边界，不把 Honcho 的只读命令过滤直接作为本项目的已定证据规则。源码：[正文筛选](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/transcript/codex.ts:39)、[工具摘要](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/observe.ts:34)。

##### 同步与异步的分层

Honcho 未配置 `async: true`，所以 AI 工具默认等待 Hook；observe 只等待本地追加，writeback 还会等待 flush 内的 API 写入。即使 SessionStart 的上下文缓存有效，recall 也先执行创建并关联会话的网络操作；UserPromptSubmit 开启回注后则只读缓存。函数声明 async、源码注释“background”或未显示 UI 提示，不改变这些等待关系。

Honcho 服务端先接收并保存 Message，再安排独立后台任务。DistillAI 的 LLM API 调用属于后台语义处理；接入端将材料交付给 DistillAI 后端，与后端调用模型供应商 API，是两类不同请求。沿用 `.sent` 不要求采集 Hook 等待模型分析；文件持久化也不决定交付必须采用 API、IPC 或共享文件。

DistillAI 执行候选：

- 继续用 Stop / PreCompact 采集新增用户与助手文本，PostToolUse 记录工具活动；SessionStart 提供简短规则与 Skill / MCP 入口，UserPromptSubmit 在问题到达后调用 LLM 筛选适用注入候选，允许返回空。
- 采集 command Hook 同步完成短时本地落盘后返回；常驻后端独立消费记录、调用模型 API 并保存结果。采集不等待 episode 分析；本轮注入采用独立的同步筛选与交付候选路线，等待关系见 D05。
- 采集与处理解耦：先落入本地队列，再由交付机制将待发送材料交给本地常驻后端，后端独立生成分析产物。后端停机时材料仍可积累；恢复后重试交付并触发处理。具体采用 API、IPC 或其他交付与唤醒方式仍待 Q04 决定。
- 2026-10-04 已确认沿用 Honcho 的队列与进度结构：采集游标、交付进度和后台处理状态各司其职。后端位于本机不改变这三个阶段的语义；不以 `processed.json` 替换 `.sent`。
- Honcho 的消息计数游标作为参考基线；不把字节偏移优化作为已定要求。来源定位、文件缩短或换源、追加与游标更新之间崩溃，以及消费幂等继续由 Q05 / Q15 明确，不能把两次文件写入称为事务。

同步短时落盘是本轮建议，不是已批准执行契约。当前官方文档支持 async Hook，但可能乱序或在会话结束时取消未完成任务；不把 async: true 当作可靠交付的替代。强制关闭、中断和未触发 Stop 的尾部材料恢复、采集过滤、工具结果保留和 Hook / MCP 去重继续由 Q05 / Q15 / Q16 收敛。

#### 采集与交付流程伪代码

以下伪代码先还原 Honcho，再按当前落盘结论表达 DistillAI 的阶段分工。伪代码只说明算法和进度推进顺序，不决定框架、语言、交付协议或触发者；省略配置读取、文本分片和协议封装。

Honcho 的 capture / observe / writeback 路径：

```python
def capture(key, transcript_path):
    messages = read_and_filter_entire_rollout(transcript_path)
    count = read_cursor_count(key)
    start = count if count <= len(messages) else 0
    fresh = messages[start:]
    if fresh:
        append_queue_jsonl(key, fresh)
        write_cursor(key, count=len(messages), at=now_utc())

def observe(payload):  # PostToolUse；仅本地追加
    if not enabled_and_saving():
        return
    summary = summarize_tool_by_fixed_rules(payload)
    if summary:
        append_queue_jsonl(memory_key(payload), [
            {"role": "tool", "text": summary, "at": now_utc()}
        ])

async def writeback(payload):  # Stop / PreCompact
    if not enabled_and_saving() or not payload.transcript_path:
        return
    key = memory_key(payload)
    capture(key, payload.transcript_path)
    await flush(key)  # Hook 进程等待上传；不是仅安排后台任务

async def flush(key):
    if not try_acquire_delivery_lock(key):
        return
    try:
        entries = read_queue_jsonl(key)
        sent = read_sent_count(key)
        for messages, next_entry_count in make_honcho_batches(entries, sent):
            await honcho_add_messages(messages)
            write_sent_count(key, next_entry_count)
    finally:
        release_delivery_lock(key)
```

`make_honcho_batches()` 按源队列条目边界推进进度：长正文会拆成多个上传消息，`.sent` 仍计原队列条目。参考实现每个上传请求最多 100 条消息，单个正文片段按 24,000 字符预算拆分；极长条目超过 100 个片段时会截去剩余片段。工具条目上传时绑定助手 peer，并带 `[tool]` 前缀及 type=tool 元数据；本地队列仍保留 role=tool。这些是 Honcho 的协议适配事实，不自动成为 DistillAI 的分片与角色映射契约。源码：[上传映射与分批](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/flush.ts:14)。

上下文入口的流程另列，避免与正文采集合并：

```python
async def recall(payload):  # SessionStart
    await create_session_and_associate_peers(payload)
    context = read_fresh_context_cache(payload, ttl_minutes=10)
    if context is None:
        context = await fetch_peer_context(payload)
        save_context_cache(payload, context)
    return render_context_and_mcp_hint(context)

def prompt(payload):  # UserPromptSubmit；默认关闭
    if not inject_per_prompt_enabled() or is_trivial(payload.prompt):
        return
    return render_cache_if_different_from_last_injected(payload)
```

DistillAI 沿用三个阶段的候选流程：

```python
def collect_materials(payload):
    key = resolve_capture_key(payload)
    if payload.event == "PostToolUse":
        append_selected_tool_activity(key, payload)
    elif payload.event in ("Stop", "PreCompact"):
        capture(key, payload.transcript_path)
    # SessionStart 提供规则入口；不在这里调用模型分析

async def deliver_pending_materials(key):
    if not try_acquire_delivery_lock(key):
        return
    try:
        entries = read_queue_jsonl(key)
        sent = read_sent_count(key)
        for batch, next_entry_count in make_delivery_batches(entries, sent):
            ack = await deliver_to_backend(batch)
            if not ack.accepted:
                return
            write_sent_count(key, next_entry_count)
    finally:
        release_delivery_lock(key)

async def process_received_materials(task):
    result = await backend_agent_analyze(task.materials)
    save_analysis_results(task, result)
    mark_backend_task_processed(task)
```

这里没有规定 collect 后必须由 Stop 立即调用 deliver，也没有规定接收确认的字段或后端任务存储文件。交付由谁触发、何时重试、后端怎样可靠保存接收材料并建立待处理任务，在 Q04 / Q15 中确定；必须能在确认接收后、分析完成前恢复处理，不能把仅唤醒成功等同于接收成功。后台处理状态继续由后端管理，不新增采集目录的 `processed.json`。

#### 采集与交付的异常边界

| 情况 | Honcho 参考行为或当前边界 | DistillAI 仍需明确 |
| --- | --- | --- |
| 禁用采集、缺少配置或 transcript_path | 相应处理函数返回；writeback 缺少 transcript_path 时也不调用 flush | 缺失材料入口的诊断与后续补采 |
| 文件无法读取、JSON 无法解析 | 读取器返回空集合或跳过坏记录；没有文件稳定性等待 | 区分暂未完整的尾部和中间损坏，避免静默丢失 |
| 捕获游标超出当前筛选消息数 | Honcho 从列表起点重新选取；游标不存在或读取失败时按零读取 | 换源、缩短与损坏游标的识别，重采后的幂等 |
| 后端离线或交付失败 | 已入队材料保留；只有已确认批次推进 `.sent` | 谁执行重试、何时唤醒及接收确认契约 |
| 交付锁已被其他进程持有 | 参考实现跳过此次 flush；尝试接管已失效持有者的锁 | 锁恢复与实际并发场景；不据此承诺恰好一次 |
| 已追加材料但未写捕获游标，或后端已接收但未写 `.sent` | 重启后可能重新采集或交付 | 源事件标识、接收幂等与重复证据不重复计入 |

Honcho 的 dispatch 捕获处理异常并返回空结果，便于继续日常任务；这不等于失败已恢复或数据完整。DistillAI 的错误记录、失败后继续交互与补采要求在后续契约中明确；诊断信息不携带原始个人正文。源码：[失败返回](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/dispatch.ts:17)。现有回复完整性、尾部补采和上传锁的核对见下文，继续保持源码快照与 Desktop 实测的区别。

#### 回复生成、rollout 写入与采集完整性

2026-10-04，补充核对 `Stop` / `PreCompact` 触发时是否已有完整回复，以及读取 rollout 时如何处理尚未写完整的数据。下述是参考实现的行为与证据边界，不代表 DistillAI 已实现这些机制。

**Hook 触发与整轮回复结束是两个需要分别判断的问题。** `Stop` 在当前轮即将结束时运行，正常完成路径上模型已返回本轮结果；`PreCompact` 在上下文压缩之前运行，自动压缩可能发生在一轮中途，压缩后模型仍会继续，因此不能认为每次 `PreCompact` 都已有本轮最终回复。参考：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)。codex-honcho 没有配置 `async: true`，`writeback()` 先同步捕获，再 `await flush()` 上传；默认 AI 工具会等待 Hook 返回。函数声明为 `async` 不意味着 Hook 在 AI 工具中后台执行，也不意味着只把上传排入后台队列。正常同会话流程通常先等待上一轮同步 Stop Hook 返回，再进入下一轮；“上一轮 Stop 仍在读取、下一轮已持续输出”不是该默认流程的必然情况。

**已核对的本地 Codex 源码快照在 Stop 前有 rollout 写入等待。** 在正常成功路径中，模型返回、消息交给 rollout recorder 后，构造 `StopRequest` 会调用 `hook_transcript_path()`；该函数先等待 `ensure_rollout_materialized()`，后者等待 recorder 的 `persist()`。recorder 按队列顺序处理写入，完成待写记录的写入和文件 `flush()` 后才确认，因此该快照不是仅靠 Honcho 解析 JSON 来解决 Stop 前的写入顺序。对应源码：[Stop 调用路径](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-main/codex-rs/core/src/session/turn.rs:513)、[获取 transcript 路径](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-main/codex-rs/core/src/session/mod.rs:3015)、[recorder persist](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-main/codex-rs/rollout/src/recorder.rs:630)。

这份 `codex-main` 本地副本没有可核对的 Git 提交信息，也未证明与当前安装的 Desktop 版本一致；上述顺序只能作为该源码快照的依据。`ensure_rollout_materialized()` 遇到错误会记录警告并继续，不能据此承诺写入失败时仍完整采集；文件 `flush()` 也不等于已确认断电持久性。该快照未提供可核对的 `PreCompact` 调用路径，因此其写入等待顺序及当前 Desktop 的实际表现仍待验证。

**Honcho 判断的是单条 JSON 记录能否解析，而不是整轮回复是否完成。** 核对版本为 codex-honcho `c17cbb2b4c7cf12172213345ae4c0d2a093d707b`。`readRollout()` 每次读取整个文件，按换行拆分并逐条 `JSON.parse()`；解析失败的记录跳过。随后只提取 `response_item` 中类型为 `message`、角色为 `user` / `assistant` 的文本，并进行相应过滤。流式增量、工具与推理记录不会作为这条路径中的用户 / 助手消息采集；筛选条件没有要求消息属于最终回复，也没有等待整轮结束。对应源码：[rollout 解析与消息筛选](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/transcript/codex.ts:64)。

因此，尚未写完整、无法解析的尾部 JSON 记录，本次不会采集；下一轮尚未结束，但已经写入完整的 assistant 中间消息，若读取时可见且满足筛选条件，仍可能被采集。“一条 JSON 完整”不等于“整轮 LLM 回复完整”，也不能推导出“未触发本轮 Stop 就完全不会读取本轮信息”。

**尾部补采依靠后续触发与消息计数游标。** Honcho 的游标是成功解析、筛选后得到的消息条数，不是字节偏移，也不是问答轮数。尾部半条 JSON 被跳过时不计入游标；如果之后写完整且再次触发采集，在此前记录保持不变的条件下，它会出现在新增消息中。该实现没有等待文件稳定、轮询半条记录或比较 `last_assistant_message`；发送重试只处理已进入本地队列的内容，不会自动补读 rollout。如果之后没有再触发采集，缺失尾部不会仅靠发送重试恢复；中间损坏记录等情况也不能直接套用尾部补采结论。对应源码：[采集与游标更新](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/writeback.ts:15)、[新增消息选择](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/cursor.ts:40)。DistillAI 的完整性要求、尾部恢复与游标契约继续由 Q05 / Q15 / Q16 收敛。

#### Codex Hook 输入与触发依据

已查文档中，`SessionStart` 的标准输入包含 `session_id`、`cwd`、`transcript_path`（可为空）、`hook_event_name`、`model`、`permission_mode` 和 `source`（`startup` / `resume` / `clear` / `compact`），没有 `prompt` 或 `turn_id`，不能作为首条问题的可靠入口。`UserPromptSubmit` 携带 `prompt` / `turn_id`，在问题交给模型处理前运行，支持 `additionalContext`。

官方文档未明确 Desktop 中 `SessionStart` 与用户点击发送的先后关系。读取 transcript 不保证获得正在提交的问题，且其格式不是稳定 Hook 接口。参考：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)。

#### Honcho 上传锁的范围与未决一致性契约

Honcho 的 `<key>.lock` 是按队列 key 建立、写入进程 PID 的协作锁文件。`flush()` 持锁执行“读取 JSONL → 读取 `.sent` → 上传未发送条目 → 成功后推进 `.sent`”，结束时释放；同一队列的 Hook 发送与手动 flush 等进程可能同时启动，这才是需要互斥的冲突。不同 session 通常采用不同 key，可分别持锁工作；两个不同 session 并行并不天然冲突。

锁保护的是这段交付临界区，而不是对某个数据文件施加操作系统级文件锁。Honcho 的 `capture()` 追加与采集游标更新发生在获取上传锁之前，因此这个锁不保护采集写入。此前提到的“写入锁”是泛称，“采集锁”指追加与采集游标更新的互斥范围；不能据此声称 Honcho 已有另一把采集锁。DistillAI 是否需要采集互斥及如何实现，按实际并发场景在 Q15 中确定。

互斥不能单独保证交付恰好一次；后端已接收但发送端未更新 `.sent` 时仍可能重发。接收确认、源事件标识、后台幂等、残缺行恢复及 Hook / MCP 证据去重仍需设计。现有 `event_id` 标识每次本地写入，不是 AI 工具源事件标识。参考本地 codex-honcho `c17cbb2b4c7cf12172213345ae4c0d2a093d707b`：[队列与发送进度](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/queue.ts:27)、[发送锁与交付流程](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/flush.ts:79)、[采集与游标更新](/E:/JourneyIntoAI/DL_and_LLM/projects/codex-honcho/src/hooks/writeback.ts:15)。待解决：Q04 / Q05 / Q12–Q16。

</details>

<a id="episode-history"></a>

<details>
<summary>R02：episode 概念来源与历史修正</summary>

#### 概念来源与含义差异

episode 的参考来源是 Graphiti：它将调用方提交的一份输入材料称为 episode，可为消息、文本或 JSON；调用方决定输入粒度，不要求先按话题切分聊天。Graphiti 从输入提取实体与时序关系，并保留来源关联。输入记录与派生图谱分存，是本项目借鉴的方向。

Graphiti 的 `EpisodicNode` 主要字段包括 `uuid`、`name`、`group_id`、`source`、`source_description`、`content`、`created_at`、`valid_at` 和 `entity_edges`。调用参数 `episode_body` 保存为 `content`，`reference_time` 保存为 `valid_at`；`created_at` 为摄入时间，`valid_at` 为原材料的发生或创建时间，不表示用户理解已经验证。`name` 由调用方指定，`group_id` 为图分区，不等同于 AI 工具 session。依据：[Graphiti 首轮记录](../../../../research/graphiti/round-1.md)、[本地节点定义](/E:/JourneyIntoAI/DL_and_LLM/projects/graphiti/graphiti_core/nodes.py:318)、[本地输入处理](/E:/JourneyIntoAI/DL_and_LLM/projects/graphiti/graphiti_core/graphiti.py:1155)。

首轮调研曾提出一条消息对应一个 Graphiti episode 的接入候选；那是向 Graphiti 提交材料的粒度建议，不构成当前独立派生记录层的必要性证明。后来 Discussion 使用“episode 观察”描述后台整理出的用户表现，含义已经与 Graphiti 的输入记录不同，不能仅凭沿用名称就照搬结构或生成流程。

#### 历史候选与修正记录

| 方案或说法 | 状态 | 理由 |
| --- | --- | --- |
| 仅以“相同主题”“同一次表现”描述聚合边界 | superseded | 此前没有可操作归属规则；现由 session 内活跃记录、缓冲与上下文评分方向细化 |
| 用 `(host, session_id, turn_id)` 确定 episode | superseded | 重复封装原始数据；本轮仍不采用每个 turn 固定生成一条 episode |
| 直接保存用户观察，取消独立 episode 层 | superseded | 用户本轮选择保存某次完整交流，不再作为当前待选架构 |
| 明确续接时跨 session 扩充同一 episode | superseded | 初版按 session 分开，通过关联表达续聊或背景 |
| 每次增加实质内容即更新 episode summary | superseded | 当前采用关闭后生成 summary 的处理时机，活跃阶段维护边界所需上下文的具体方式待定 |

同一来源重复交付与不同时间发生相似交流仍是不同问题：前者按来源去重，后者不能只因相似而合并或丢弃。本轮未要求定期删除旧引用；来源修正、边界纠错及其历史保留另定契约。

#### 下一层细化范围

- **评分与边界**：具体指标、维度、计算方式、档位及阈值，轮次口径、缓冲窗口与不确定性处理，正式 Prompt 及效果核对。
- **收尾与运行**：SessionEnd 的实际可用性、空闲检测、活动结束与计时、未满窗口收尾、延迟到达、关闭 / 分析状态及失败恢复。
- **调度与上下文**：批量触发条件、最大等待时间、上下文预算与按需读取、Agent 运行上下文生命周期、重复任务处理、并发及恢复；区分实际 token 用量、推理计算与调用成本的核对口径。
- **Agent 接入**：轻量框架与工具复用、SDK / RPC 等调用方式、材料接收接口、结果与保存工具契约，以及与既有后台语言及目录的适配。
- **记录与存储**：ID、字段、文件布局、完整历史正文或稳定引用、缓冲持久化、跨 session 关联、来源去重及修订后的重新分析。

关联事项：Q04 / Q05 / Q06 / Q15 / Q16。上述细化项是下一层任务，不阻止本层 episode 设计完成；Q07 / Q09 等上层工作保留在相应主题，episode 的本层确认不预设上层知识提取、掌握或衰退计算的具体规则。

</details>

<a id="runtime-reference"></a>

<details>
<summary>R03：Pi 接入可行性与早期图查询草案</summary>

Pi 接口的既有可行性参考：其 coding-agent SDK 可在 Node.js / TypeScript 进程中调用 `session.prompt()`；保留 Python 后台时，也可经 JSON 标准输入输出驱动常驻 RPC 子进程。具有现成文件与 Shell 工具的 coding-agent 接入层，与需要配置工具的 agent-core 层应分开核对。2026-10-08，用户已暂定 pi-agent 为基础框架，具体接入层及 SDK / RPC 方式仍待接口设计确定；上述接口尚未做 DistillAI 集成验证，本次不变更已有 Python 目录方向。依据：[Pi SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)、[Pi RPC](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md)、[Pi agent-core](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)。

#### NetworkX 图与检索记录

认知地图目标、关系资产与图索引的专题讨论集中于 [D03](../design.md#cognitive-map-model)；本节保留既有检索草案及上下文交付机制。

##### 既有图草案与待修订范围

已确认分层结构化记录及 JSON/JSONL 方向；具体文件组织仍待决定。session 是来源，知识与假设可关联多个 session 的证据。episode 保存某次完整交流，其边界、收尾及历史候选统一见 [D02](../design.md#episode-model)。不能把 Honcho、Letta 或 Graphiti 概括成“都不保存原始会话”：保存筛选后的消息与保存 AI 工具完整 rollout 是不同范围。

历史讨论曾选择 NetworkX 并绘制知识点 / 假设节点草案。后续 M04 采用知识点为节点、独立关系为边的名称有向多重图；假设从详情读取，不自动成为独立图节点。2026-10-10 用户改选 Node / TypeScript + Pi SDK 后，统一 Design 建议 Graphology。以下旧草案保留为研究记录。

图查询草案承担三件事：找到当前任务的知识点及邻居；找到相关假设并统计有效覆盖；假设更新后定位受影响知识点。暂不增加图数据库、图学习模型或基于中心性的掌握评分。

技术方向、代码目录与后台本地常驻已选，图仅保存名称的边界已确认；记录字段、名称到文件的定位、方向规范及基于详情的筛选和排序仍待模块设计。运行细节根据职责和交付契约确定，遵循“整体框架 → 模块设计 → 细节推断”的讨论顺序。待解决：Q06 / Q11 / Q12 / Q15。

#### 早期概念发现候选（已由 D04 全图扩展方向细化）

用户提出从会话概念出发，例如由反向传播寻找梯度下降、优化器等关联概念，从广度与深度形成理解假设。会话知识提取仍只整理会话实际内容；外部发现的概念和关系另标来源与状态，未提及和未验证的概念保持未知。

候选扩展围绕先备、机制、用途、替代和边界，从少量直接邻居开始，按任务筛选，必要时用教材或官方资料核对；有实际需要再扩展下一层。广度关注概念连接，深度关注机制、条件、形式化、反例与迁移。

2026-10-08，用户重申优先发现连接多个已有知识点的外部候选；a、b、c、d、e 的例子与 OpenMAIC Skill 参考统一见 [D04：外部搜索与知识扩充](../design.md#knowledge-expansion)。具体触发和搜索契约仍待确定。

当前图契约见 [M04](../design.md#cognitive-map-model)，认知规则见 [M05](../design.md#cognition-decisions)，Graphology 选项见 [技术收尾](../design.md#data-technology)。上述 NetworkX 代码不作为 Node 产品实现方案。

</details>

<a id="prompt-injection-research"></a>

### R04：Prompt 注入调研核对（2026-10-08）

用户指定 GPT-6 Luna（max）完成只读调研，主 Agent 核对并整理到本节。依据为当日官方文档、已登记的 codex-honcho 本地快照与当前采集插件；没有运行注入集成。方案继续保持 Discussion 草稿。

#### 已核对的机制与设计影响

| 核对项 | 已知机制 | 对当前方案的影响 |
| --- | --- | --- |
| 本轮交付 | UserPromptSubmit 在问题发给模型前触发；同步 command Hook 等待结束，additionalContext 进入 developer 上下文 | 采用“接入端调用后台筛选，校验后返回素材”的候选路线 |
| 异步交付 | async Hook 完成后在下一安全点交付；活跃轮需等当前模型请求和工具结束，空闲时等下轮 | 无法保证影响当前轮第一次回答；后台准备素材和本轮交付分别安排 |
| 运行限制 | Hook 有 timeout；大输出默认约 2500 token 后转为文件及预览 | 保持交付简短；用户暂不设筛选等待时间的决定继续有效，平台配置单独确定 |
| 可见性 | additionalContext 面向模型；systemMessage 面向 UI / 事件告警 | 交付素材使用 additionalContext；是否有执行提示、错误显示及用户感受需 Desktop 观察 |
| 启动与续接 | SessionStart 无当前 prompt；compact 可在轮内直接续接 | 恢复规则与关联，不凭启动事件新建 episode 或重新筛选素材 |
| MCP Hook | 使用已连接的 MCP；SessionStart 可能早于连接就绪 | 启动优先采用本地 command；工具连接后再按需查询 |

上述平台机制见 [官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。本轮的同步调用后台方案由这些契约推得，尚不能记为 Desktop 已验证。

MCP 工具的名称、描述和输入 schema 帮助模型选择能力；结果供模型继续回答。Skill 先展示名称与说明，选用时才加载完整方法。工具说明和 Skill 均不保证查询、素材采用或学习效果；SessionStart 只交付简短入口规则。依据：[MCP server](https://developers.openai.com/plugins/concepts/mcp-server)、[Skill 加载](https://learn.chatgpt.com/docs/build-skills)。目前无需另设 MCP prompt 模板来重复这些说明。

#### 本地证据与实现边界

| 材料 | 核对结果 | 可以支持的结论 |
| --- | --- | --- |
| 当前 `distill-capture` | UserPromptSubmit / Stop 各配置 5 秒；脚本采集后返回 `{}` | 仅为采集资产，没有本轮 LLM 筛选或注入 |
| codex-honcho | 五个 Hook 未配置 async；UserPromptSubmit 的逐轮回注默认关闭，开启后读缓存并跳过部分重复内容 | 可参考接入时机与缓存使用，不能直接证明当前 LLM 筛选方案 |
| OpenMAIC 教学方法 | 费曼与最近发展区方法要求观察用户解释及帮助条件；当前 D06 已作日常交互适配 | 保留可选类比与自然反馈，不把交付成功记成理解证据 |

本地入口：[采集配置](../../../../../plugins/distill-capture/hooks/hooks.json)、[采集脚本](../../../../../plugins/distill-capture/hooks/capture.py)、[Honcho 核对](../../../../research/honcho/round-2.md)、[OpenMAIC 本地源码路由](../../../../research/openmaic/README.md#本地源码路由)。

#### 下一层需要收敛的交接

建议筛选输入绑定当前 session / turn、episode、候选与子图版本及来源；LLM 返回候选引用或空结果，程序再核对引用、适用条件和版本后组装交付文字。选择期间子图刷新、话题切换和后台不可用如何处理，继续由 Q14 / Q15 决定，字段尚未定稿。

记录至少区分：LLM 选中、Hook 返回、模型可用、助手原文中可观察的采用，以及用户后续表现。一次 Hook 成功不能证明助手采用；认可、追问和无反应保留各自的竞争解释。MCP 回写与采集流按来源关联，不能仅用相同文本判断同一证据。

Q16 的一次性 Desktop 验证应取得当前轮交付、等待与错误表现、compact 续接、MCP 连接和自然回答采用的实际证据；本轮只保存待验证事项，沿用前述验证分类。

待解决：Q11–Q14；证据回写与采集去重关联 Q15，Desktop 使用效果关联 Q16。

<a id="extraction-research"></a>

### R05：跨项目提取机制与调研入口

#### 已核对的提取机制

以下概括来自此前公开提示词与源码快照，描述机制及产物，不声称运行这些系统生成了 DistillAI 结果。

| 参考项目 | 提取提示词的核心思想 | 主要产物 |
| --- | --- | --- |
| Honcho | Deriver 从目标参与者自己的消息提取明确、原子且自洽的事实，其他参与者仅作上下文；Dreamer 承担后续更高层的推断与整理 | 关于目标参与者的事实与结论，不直接等同于概念知识或用户掌握 |
| Mem0 | 已核对开源 additive 路径从新消息、近期上下文和旧记忆中提取有背景的独立记忆；区分用户事实与助手建议，避免重复 | 结构化记忆列表，主要是事实、偏好、计划、建议，也可包含参考材料内容；云端私有提示词未确认 |
| Graphiti | 先识别实体，再提取这些实体之间的事实关系并处理时间；本次核对的 message 提示词过滤抽象概念与泛词 | 实体、关系与时间信息，不天然对应教学意义上的概念条目 |
| Letta Code | 对照已有记忆，优先保存纠错、偏好、长期事实与可复用流程，过滤临时或重复信息 | 更新后的 Markdown 记忆；可复用多步骤流程可以另存为 Skill |
| Eigma | 筛选长期值得学习的概念、机制、原理和关系，基于会话形成知识页，不自行补足未讨论内容 | 知识页、相关链接和测验题；正文为 Markdown，知识页不代表用户掌握 |
| LLM Wiki | compiler 先从来源与旧索引识别独立主题，再按主题综合多份来源生成页面；llmwiki 的 guide 指导外部 Agent 阅读、整理和维护页面 | 概念候选及综合知识页，带引用、链接；两种实现的编排者不同 |
| OpenMAIC | 教学 Skill 定义学习目标、实际表现、帮助条件与新任务复核；属于教学编排和验证参考 | 课程内容和具体学习记录，不作为通用会话知识提取器 |

提示词依据：[Honcho Deriver](https://github.com/plastic-labs/honcho/blob/9d6fe8ca/src/deriver/prompts.py)、[Mem0 开源提取](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/mem0/configs/prompts.py)、[Graphiti 实体](https://github.com/getzep/graphiti/blob/main/graphiti_core/prompts/extract_nodes.py)与[关系](https://github.com/getzep/graphiti/blob/main/graphiti_core/prompts/extract_edges.py)、[Letta Code reflection](https://github.com/letta-ai/letta-code/blob/2b95889/src/agent/subagents/builtin/reflection-v2.md)、[Eigma 规则](https://github.com/eigma-app/eigma-mcp/blob/c6ed77784300fc11c65772de7cc4d136b55a4f62/src/rules.ts)、[Wiki compiler 提示词](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/src/compiler/prompts.ts)、[llmwiki guide](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/mcp/tools/guide.py)、[OpenMAIC 最近发展区](https://github.com/THU-MAIC/OpenMAIC/blob/c72a64b4b669608bd682ae561bea0e059710930a/skills/agent-runtime/zone-of-proximal-development/SKILL.md)。

#### 专题与源码入口

- 概念扩展、螺旋课程、UbD、最近发展区与教学等级：[OpenMAIC 第 2 轮专题](../../../../research/openmaic/round-2.md)。所查螺旋课程不会自动维护 DistillAI 所需的概念模型。
- Eigma 的待读、待测与衰退状态：[首轮记录](../../../../research/eigma/round-1.md)；页面阶段与掌握边界：[第 2 轮记录](../../../../research/eigma/round-2.md)。
- 原始材料与派生内容的存储分工：[Honcho](../../../../research/honcho/round-1.md)、[Letta](../../../../research/letta/round-1.md)、[Graphiti](../../../../research/graphiti/round-1.md)。
- Hook、采集队列与游标：[Honcho 第 2 轮](../../../../research/honcho/round-2.md)、[本地源码路由](../../../../research/honcho/README.md#本地源码路由)。调研记录中的早期自定义采集文件候选已撤下，当前采集结论集中于 [D01](../design.md#data-capture)。
- 主动收集区分性证据：[主动信息收集研究](https://aclanthology.org/2025.findings-emnlp.843/)；会话中的知识追踪：[对话知识追踪研究](https://arxiv.org/abs/2409.16490)。
- OpenMAIC 本地源码入口：[本地源码路由](../../../../research/openmaic/README.md#本地源码路由)。已记录本地仓库为 `E:\JourneyIntoAI\DL_and_LLM\projects\OpenMAIC`，核对提交为 `c72a64b4b669608bd682ae561bea0e059710930a`；后续按该路由核对本地源码。

<a id="openmaic-methods"></a>

### R06：OpenMAIC 方法核对与适配依据

2026-10-08 重新读取 [OpenMAIC 本地源码路由](../../../../research/openmaic/README.md#本地源码路由) 登记的 Skill，本地 HEAD 仍为 `c72a64b4b669608bd682ae561bea0e059710930a`。以下为适配建议，具体 DistillAI Skill 尚未定稿：

| OpenMAIC Skill | 已核对的方法 | DistillAI 适配建议 |
| --- | --- | --- |
| `deep-research` | 先读已有材料，拆分搜索问题，设置预算，维护主张到来源的记录，覆盖问题后停止 | 用户选择先沿用该流程，围绕 e 与 a、b 的具体连接搜索，保存关系依据、适用条件和冲突；具体预算另定 |
| `spiral-curriculum` | 每次重访明确保留、增加、重组与迁移；通过关系、抽象、形式化、表征、复杂度、反例及迁移等操作符增加理解结构 | 用于选择验证或深化维度，也用于评估候选知识的理解增量；操作符随任务、用户证据与竞争假设选择 |
| `feynman-learning` | 先解释、定位最小疑点、追问、重新解释、去术语、检查类比边界及迁移，保留实际学习记录 | 用于 Prompt 注入阶段，指导通用 Agent 通俗解释、保留类比边界，并依据用户自然表达按需帮助与观察；表现连同帮助条件回写，后台综合更新假设 |
| `understanding-by-design` | 先确定理解目标与表现性证据，再安排学习活动 | 在交互引入 e 前，明确希望用户形成什么理解，以及什么实际表现能支持该判断 |
| `zone-of-proximal-development` | 从独立表现出发，按困难提供帮助，再减少关键提示并用新任务复核 | 用户已明确定位在 Prompt 注入阶段：指导通用 Agent 的交互引导、帮助调整及表现验证，具体设计见 D05 / D06 |
