# Honcho 第 2 轮：Hook 采集、执行时序与本地文件

日期：2026-10-04。用户要求结合源码回答采集 Hook、同步 / 异步、伪代码、存储根目录及文件名。经用户授权下载 codex-honcho，在本地核对源码；没有安装插件、运行 Honcho 或触发其 Hook。

仓库路径、完整提交和入口见 [本地源码路由](README.md#本地源码路由)。以下实现事实以本轮固定提交为准；DistillAI 采集结论与候选集中于 [初版 Discussion D01：数据采集与材料交付](../../spec/v0.1.0/4-initial-development/discussion.md#data-capture)。

## Hook 与实际调用链

`src/connectors/codex.ts:40` 实际注册五个事件，映射四个处理函数。配置没有设置 `async: true`。

| Hook | 处理函数 | 职责 | 配置超时 |
| --- | --- | --- | --- |
| SessionStart | recall | 创建并关联 Honcho 会话与参与者；上下文缓存过期时查询用户表征，返回简短上下文及 MCP 提示 | 30 秒 |
| UserPromptSubmit | prompt | 可选逐轮回注，默认关闭；开启时读取本地缓存、过滤简短确认、避免重复注入 | 20 秒 |
| PostToolUse | observe | 固定规则生成工具活动摘要并追加本地队列；不调用模型或网络 | 10 秒 |
| Stop | writeback | 每轮结束读取 rollout、捕获新增消息，再在 Hook 进程内上传待发送队列 | 30 秒 |
| PreCompact | writeback | 压缩前执行同一套采集和上传逻辑，复用游标 | 30 秒 |

SessionStart / UserPromptSubmit 在该实现中不是会话正文采集入口。Stop 是轮次结束，不是整个会话关闭。上述超时是容许上限，不是实际执行耗时。

工具摘要见 `src/hooks/observe.ts:34`：部分只读 shell 命令以及 Honcho 自身 MCP 调用被跳过；其他 shell 命令取前 120 字符，补丁列出最多五个文件，其余工具记为 `used <工具名>`。`tool_response` 在输入类型中存在，但摘要函数没有使用它。工具摘要不是完整结果，也不能证明执行成功或用户理解。

会话解析见 `src/transcript/codex.ts:83`：只选择 `response_item` 中的 user / assistant message，提取 input_text / output_text / text，过滤代码列出的注入标签，跳过工具调用、推理和非文本内容。未按 assistant channel 限定只保留最终回复；已知标签过滤也不是通用用户作者识别。

## 同步与异步分属不同层

1. Codex默认等待 command Hook 完成；当前官方文档允许通过 `async: true` 在后台执行 Hook，但并发执行可能乱序，会话结束会取消未完成 Hook。
2. 本轮 codex-honcho 配置未开启该选项。`src/hooks/writeback.ts:36` 明确 `await flush()`；`src/hooks/flush.ts:136` / `143` 在同一进程内等待 API 写入完成，再推进发送位置。TypeScript 的 async / await 不改变 AI 工具等待关系。
3. Honcho 服务端 `src/routers/messages.py:117` 保存 Message，然后在 `:161` 安排 enqueue 后台任务；独立的 QueueManager 消费持久化任务并执行语义处理。API 收到消息与模型分析完成是不同状态。

源码中的“background worker”“detached”“Codex 无 SessionEnd”等注释不能覆盖实际调用和当前 AI 工具文档。当前官方文档已列出 SessionEnd / Interrupt；这个插件版本没有注册它们。不能由这组 Hook 保证强制关闭或中断时已经采集所有尾部材料。

AI 工具依据：[OpenAI Hooks 文档](https://learn.chatgpt.com/docs/hooks)，重点为 Run hooks in the background、Common input fields、Tool coverage 与 SessionEnd。文档同时说明 transcript 格式不是稳定 Hook 接口，实际 Desktop 行为仍需验证。

## “增量读取”的具体含义

`readRollout()` 使用 readFileSync 全量读取文件，解析并筛选出消息列表；`selectNewTurns()` 根据已捕获的消息数 slice 新列表。这里的 count 是过滤后消息数量，不是文件字节偏移，也不是一问一答的轮数。

capture 先追加新消息到队列，再写捕获游标。flush 使用单发送者锁，只有 API 请求成功后才更新 `.sent`。这是两个独立进度；没有把队列追加与捕获游标更新组成事务，也没有由此证明服务端写入恰好一次。失败后可重试，同一批重试的幂等和重复证据影响需要另行设计。

## 本地根目录、文件名与内容

默认根目录是 `~/.honcho`，由 `HONCHO_CONFIG_DIR` 可覆盖。文件 key 优先取完整 Codex session_id；缺少时退到派生的 Honcho session name。safe(key) 将字母、数字、下划线和连字符之外的字符替换为下划线。

```text
~/.honcho/
├── config.json
└── codex/
    ├── queue/
    │   ├── <safe-key>.jsonl
    │   ├── <safe-key>.sent
    │   └── <safe-key>.lock
    ├── cursors/
    │   └── <safe-key>.json
    └── context/
        └── <safe-key>.json
```

| 文件 | 内容 | 源码 |
| --- | --- | --- |
| queue/*.jsonl | 每行一个 `{role, text, at?}`；role 为 user / assistant / tool | src/queue.ts:14、27、35 |
| queue/*.sent | 已成功发送的队列条目数，纯数字文本 | src/queue.ts:31、63、70 |
| queue/*.lock | 上传锁文件，内容为持有者 PID | src/hooks/flush.ts:58、79 |
| cursors/*.json | `{count, at}`，count 为已捕获的筛选后消息数 | src/cursor.ts:14、28 |
| context/*.json | representation、peerCard、获取时间 at、lastInjected | src/cache.ts:9、20、34 |

队列条目本身没有保存 session_id、turn_id、tool_use_id 或原始行定位；会话通过文件 key 关联。默认 per-directory 策略可把同目录的不同 Codex 会话上传到同一 Honcho session，而本地 memoryKey 仍优先使用各自的 Codex session_id，见 src/config.ts:169、189。

Honcho 服务端收到的消息进入 PostgreSQL messages 表，见 src/models.py:213；上述 JSONL 是接入端本地队列，不是 Honcho 全部知识与用户表征的存储格式。Codex 自己的 rollout 是读取来源，通过 Hook 的 transcript_path 定位，不应硬编码其磁盘路径。

## 根据源码简化的伪代码

下面省略配置加载和异常返回细节，展示实际算法；async 函数仍由 Hook 进程等待。

```python
def capture(key, transcript_path):
    messages = read_and_filter_entire_rollout(transcript_path)
    count = read_capture_count(key)
    start = count if count <= len(messages) else 0
    fresh = messages[start:]
    if fresh:
        append_queue_jsonl(key, fresh)
        write_capture_count(key, len(messages))

async def writeback(payload):  # Stop / PreCompact
    if not enabled_and_saving() or not payload.transcript_path:
        return
    key = payload.session_id or derived_session_name(payload.cwd)
    capture(key, payload.transcript_path)
    await flush_pending_queue(key)  # 上传成功后推进 .sent

def observe(payload):  # PostToolUse
    if not enabled_and_saving():
        return
    text = summarize_tool_by_fixed_rules(payload.tool_name, payload.tool_input)
    if text:
        append_queue_jsonl(memory_key(payload), [
            {"role": "tool", "text": text, "at": now_utc()}
        ])

async def recall(payload):  # SessionStart
    await create_session_and_associate_peers(payload)
    context = read_fresh_cache(payload, ttl_minutes=10)
    if context is None:
        context = await fetch_peer_context(payload)
        write_cache(payload, context)
    return render_context_and_mcp_hint(context)

def prompt(payload):  # UserPromptSubmit
    if not inject_per_prompt_enabled() or is_trivial(payload.prompt):
        return
    context = read_cache(payload)
    return render_if_different_from_last_injected(context)
```

## DistillAI 借鉴记录与已撤下的早期候选

沿用 Hook 发现新增材料、先本地持久化、分别维护捕获与消费进度的机制。DistillAI 已选择本地常驻后端，候选为 Hook 同步完成短时落盘，后端异步消费、调用 LLM API 并更新派生记录；初版采集 Hook 不等待供应商 API。

本轮早期曾建议每个 session 使用 events.jsonl、capture.json 和 processed.json，并用字节偏移读取。这一候选现已撤下，不是当前产品方案。用户后续确认按 AI 工具组织 `~/.distillAI`，保留 `queue/<key>.jsonl / .sent / .lock` 与 `cursors/<key>.json`，采用消息计数游标作为参考基线；交付确认与后台处理状态分开，不以处理进度替换 `.sent`。默认根目录与 DISTILLAI_HOME 已确认，具体交付方式、采集互斥、字段扩展与后台处理状态组织仍待设计。当前结论及完整采集补充以 [Discussion D01：数据采集与材料交付](../../spec/v0.1.0/4-initial-development/discussion.md#data-capture) 为准。

所需调整包括保存源事件定位与标识、限制写锁范围、区分捕获顺序和源发生顺序，以及处理残缺行、游标重置和重试去重。具体材料筛选、工具结果保留范围和字段仍待确认，不把 Honcho 的摘要过滤直接当成 DistillAI 的证据规则。
