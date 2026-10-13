# 第 1 轮：Pi 接入、Windows 沙箱与文件恢复

日期：2026-10-09。目的：给出 M01 可审阅的具体方案。核对官方文档与本机版本，未核对固定源码提交、未安装或运行 Pi / MXC，结论不等于集成验证。

## Pi：跨语言接入与结束判定

[官方仓库](https://github.com/earendil-works/pi)目前承接原 `badlogic/pi-mono` 地址；当前文档使用 `@earendil-works/pi-coding-agent`。这些是本次公开文档状态，不能把旧包名、新主分支和某个已安装版本混用；实施前固定具体发行版并核对其接口。

[RPC 协议](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md)采用子进程 stdin / stdout JSONL；命令以 ID 关联响应，stdout 持续读取，stderr 单独处理。`prompt` 的成功响应仅表示已接受；当前文档以 `agent_settled` 表示自动工作结束，之后仍需 DistillAI 校验和提交。[SDK](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)适合 Node / TypeScript 直接控制 session、工具和资源加载。

[CLI 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md)列出文件、搜索、Bash 及 Windows PowerShell 工具，以及禁用扩展、MCP 等资源的参数。[配置文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md)支持独立 agent 目录；默认的个人 / 项目资源发现不能直接用作 DistillAI 的受控执行配置。

[模型文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)支持已兼容协议的自定义 endpoint；特殊供应商可能需 provider 扩展。官方仓库明确 Pi 没有内置文件、进程、网络与凭证权限系统。

设计推论：Python + RPC 可保留 Python 业务代码；通过沙箱运行整个 Pi 进程，可使其文件工具和命令共享隔离边界。为了让 Shell 无法取得真实模型密钥，建议由外部受保护的程序转发模型请求，并在这个实际请求入口计数；这不是 Pi 已提供的 DistillAI 功能。

## Windows：MXC 与备选

[MXC 说明](https://github.com/microsoft/mxc)提供 ProcessContainer、文件读写 / 拒绝策略及 Node SDK。[Node V1 API](https://github.com/microsoft/mxc/blob/main/docs/api-reference/node/v1/api.md)有策略 probe、实时标准管道启动及进程控制；[类型契约](https://github.com/microsoft/mxc/blob/main/docs/api-reference/node/v1/types.md)区分普通 `process` 与 `processcontainer`，并报告实际隔离层、警告、标准流和终止接口。普通进程模式不满足本项目要求。

[版本表](https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/os-version-support.md)列出 Windows 25H2 进程隔离最低版本 26200.9278。本机只读核对：Windows 11 家庭版 25H2，26200.9457。版本满足最低条件，但未检查实际 API、策略能力、Node / Python / Shell 兼容性或子进程终止，因此仍须请求级 probe 和真实运行验证。

[主机准备说明](https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/host-prep.md)说明某些 AppContainer + DACL 回退层需要管理员操作，并可能修改主机 ACL；不能承诺无管理员步骤，也不能在本轮自动执行。[网络说明](https://github.com/microsoft/mxc/blob/main/docs/backends/process-container/networking.md)区分外网、私网、主机 loopback 与入站能力，部分策略依赖实际 Windows API；“能联网”不能证明模型转发服务可达。需要 probe 本项目完整策略，拒绝无法保持边界的降级。

[AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)提供原生隔离，但自行封装需要管理权限、能力和兼容性；[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)可协调进程组生命周期，不能独立提供目录隔离。[Anthropic srt](https://github.com/anthropics/sandbox-runtime)公开说明使用 macOS sandbox-exec / Linux bubblewrap，未给出可直接用于 Windows 原生 Shell 的对应方案。

设计推论：优先评估 MXC ProcessContainer，复用它的 native runtime；自写 AppContainer 是备选，srt 不作为当前 Windows 首选。自由联网保留，文件 / 凭证及本机后台控制权限仍独立限制。

## 文件恢复：职责与平台依据

源目录的前后 diff 能发现变化，不能可靠区分同期用户编辑和任意命令的编辑。仅包装 Pi 的 `write` / `edit` 会漏掉 Shell / Python；Git 也不能自动覆盖非仓库、忽略文件及所有工作路径。

设计推论：任务复制文件并保存基线，在副本中运行全部写入，结束后收集副本差异；失败丢弃副本，成功按原文件是否仍为基线检查冲突再写回。这改变修改在原目录中可见的时机，必须由用户审阅；MXC 的文件权限表本身不提供透明路径映射或事务回退。

[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)定义共享模式及排他新建；比较旧内容和真正写入之间仍需保持文件句柄与目标身份约束。[os.replace](https://docs.python.org/3/library/os.html#os.replace)不是多文件事务。设计须记录每个提交步骤及前后版本；不能把多个原子替换称为整批原子提交，断电持久性和外部编辑冲突也要单独验证。

## 验证边界

本轮完成文档核对及 Windows 版本读取。尚未验证：固定 Pi 发行版的 RPC / 结束事件、供应商协议转发、完整网络策略、只读与拒绝路径、重解析点 / 硬链接、所有工具及子进程隔离、权限立即撤销、原始文件提交与崩溃恢复。具体运行检查在批准 Design / Plan 后执行；不能使用既有采集测试替代。
