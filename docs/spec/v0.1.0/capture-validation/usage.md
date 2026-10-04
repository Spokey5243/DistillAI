# Distill AI：Codex 会话采集原型

Windows + Python 3，零第三方依赖。只采集 `UserPromptSubmit` 和 `Stop`，保存原始 Hook payload；不分析认知、不注入提示词、不主动联网。

当前插件、`scripts/` 和 `tests/` 属于 [Hook 采集可行性验证](README.md)。验证结果为后续设计提供依据，这些资产后续可按产品设计需要移除。产品形式、架构与产品原型属于后续独立任务，最终实现方式仍待确定。

## 保存位置

```text
%USERPROFILE%\.distallAI\
├── data\sessions\<session_id>.jsonl
└── logs\capture-errors.log
```

每行包含 `schema_version`、`event_id`、`captured_at`（UTC）、`platform`、`session_id`、`turn_id`、`hook_event_name`、`role`、`payload`。消息及 cwd/model/transcript_path 等原始元数据保留在 payload 中。失败记日志，正常对话继续；目录不可写时 stderr 也会输出错误提示。`platform` 标注事件来源（`codex` 或 `zcode`），同一存储目录混存多个宿主的会话，靠它区分。

## ZCode 注册（2026-09-29）

同一个 `capture.py` 通过 `--platform zcode` 参数区分来源，注册在用户级配置 `~/.zcode/cli/config.json` 的 `hooks.events` 下（`UserPromptSubmit` 与 `Stop`，`type: "process"`，无 shell 调用，5 秒超时），指向本仓库源码，改代码即时生效。注册用的是配置 Hook 而非插件安装：插件 Hook 需要本地 marketplace 安装记录，其文件格式无从核对，而配置 Hook 是官方文档化格式；代价是不出现在 Settings → Plugin Management 界面。不要同时再以插件形式安装，否则每轮会写两条重复记录。

配置 Hook 需 `hooks.enabled: true`（已设置）；暂停采集改为 `false` 或删除该文件即可，不删个人数据。zcode 的 payload 不含 `turn_id`，后续按轮配对时对 zcode 记录需退化为相邻配对；Stop 的消息字段缺失时记录仍落盘（role=assistant，正文为空）。

生效范围是新开的 zcode 会话。验证：新会话发送含 `DISTILL-ZCODE-TEST-002` 的消息，然后：

```powershell
Select-String -SimpleMatch 'DISTILL-ZCODE-TEST-002' "$env:USERPROFILE\.distallAI\data\sessions\*.jsonl"
```

命中记录的 `platform` 应为 `zcode`。

## 立即看写入效果

在项目目录运行：

```powershell
python scripts/demo_capture.py
```

它通过真实 Hook 命令写入两条**模拟事件**，并输出文件路径。模拟文件名以 `demo-` 开头，payload 标有 `test_fixture: true`，不会冒充实际会话。

自动测试使用临时目录，不污染个人数据：

```powershell
python tests/test_capture.py
```

## 历史个人安装与验证记录（2026-09-29）

- 开发源码：本仓库 `plugins/distill-capture`。
- 个人 marketplace 源目录：`%USERPROFILE%\plugins\distill-capture`。
- 已安装插件：`distill-capture@personal`；Codex 使用安装缓存中的副本。
- Python 必须在运行 Codex 的环境 PATH 中可用。

安装和 Hook 信任是两步。用当前 Codex 的 `/hooks` 审阅并信任本插件的 `UserPromptSubmit`、`Stop` 后，再新开会话发送：

> DISTILL-TEST-001，请只回复“收到”。

使用 Codex Desktop 的 Hooks 设置审阅并信任插件；本项目按桌面端验证集成。

验证真实数据：

```powershell
Get-ChildItem "$env:USERPROFILE\.distallAI\data\sessions" -Filter *.jsonl |
    Where-Object Name -NotLike 'demo-*' |
    Select-String -SimpleMatch 'DISTILL-TEST-001'
```

找到文件后，使用 `Get-Content -LiteralPath <文件路径> -Encoding utf8 -Tail 10 -Wait` 实时查看。需要同时看到用户消息和助手回复，并且 session_id/turn_id 相符。没有文件时先检查 `/hooks` 的加载、启用、信任状态，再查错误日志。

暂停采集可在 `/hooks` 禁用这两个 Hook；卸载使用 `codex plugin remove distill-capture@personal`。这些操作不删除个人数据。

## 范围

- 面向本机 Windows 用户，采集启用后的会话；不会导入安装前的历史。
- Stop 只有最近助手消息，不保证保存中间 commentary、附件、工具结果或完整历史。
- 文件锁防止并发记录混写；采集时间/文件顺序不代表源事件严格时序。
- 单次文件锁最多等待 2 秒；长时间占锁时记录错误并放行对话，该事件可能未保存。
- event_id 标识每次写入，不实现源事件去重；本原型不处理崩溃后残缺行恢复。
- `DISTILLAI_HOME` 可覆盖存储根目录，用于测试。默认仍是 `.distallAI`。

官方接口依据：[Hooks](https://learn.chatgpt.com/docs/hooks)。
