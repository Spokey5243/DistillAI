# 会话采集最小原型

目标：通过 Codex 插件捕获 UserPromptSubmit 和 Stop，追加保存到用户目录 `.distallAI/data/sessions/<session_id>.jsonl`。

采用 Python 标准库；保存原始 payload，附加事件 ID、UTC 采集时间、平台、格式版本和消息角色。Hook 同步短写入；同会话通过文件锁避免并发记录混写。失败记错误日志并放行正常对话。暂不解析历史 transcript、不分析认知、不注入上下文。

实施及验收：

- [x] 先写可运行的独立测试：中文、多行、追加、会话隔离、并发、非法输入。
- [x] 实现采集脚本及两类 Hook，运行测试和插件结构校验。
- [x] 安装到个人插件目录，检查发现与信任状态。
- [x] 在实际 Codex 会话中验证自动落盘；若需用户审阅 Hook，明确交接步骤，模拟测试不替代此项。

（2026-09-29 复验：测试套件通过；仓库源码与 `%USERPROFILE%\plugins\distill-capture` 安装副本一致；`~/.distallAI/data/sessions` 已有多个真实会话文件，用户/助手消息按 `turn_id` 成对落盘，无错误日志。）

采集时间仅代表接收时间；event_id 标识记录，不保证源事件去重。Stop 仅提供最近助手消息；本原型不承诺完整中间消息、图片、工具轨迹或历史导入。

## 2026-10-04：归档发布与复验

发布分支：`codex/capture-validation`；无关联 Issue。原计划和原型形成于 Git 初始化前，本次归档包含 `plugins/distill-capture/`、`scripts/demo_capture.py`、`tests/test_capture.py` 与本目录文档。

- `python tests/test_capture.py`：通过，覆盖 UTF-8、原始 payload、追加、会话隔离、并发、非法输入、失败放行和平台覆盖。
- `python .codex/hooks/test_pre_push_guard.py`：16 项测试通过。
- `python scripts/demo_capture.py`：在临时 `DISTILLAI_HOME` 中通过真实 Hook 命令写入两条合成事件，验证成功。
- 插件 JSON、本地链接、发布范围与源码保留检查通过；目录归档只做一次性检查，不新增永久路径测试。

上述复验使用合成材料，没有重新执行 Desktop 真实会话触发；真实落盘证据保留在原验收记录中。产品、架构与原型设计属于后续独立任务，这些采集验证资产可按后续设计需要移除。

独立审查发现锁等待可超过 5 秒 Hook 超时。本地长时间占锁用例在原实现中以 `TimeoutExpired` 复现；改为每次锁等待最多 2 秒，给错误记录及退出留出时间。此用例保护“占锁失败在宿主超时前返回有效 JSON 并记录诊断”的持久行为，原有短时并发用例未覆盖；不承诺磁盘 I/O 故障时完整保存事件。修复后采集测试通过。
