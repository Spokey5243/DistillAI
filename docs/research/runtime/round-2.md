# 后台运行技术第 2 轮：统一 Design 收尾

> 历史轮次。用户随后重新开放 Agent 框架与语言选择，并明确沙箱只限制写入；当前七框架比较见[第 3 轮](round-3.md)。以下保留本轮发生时的选择与技术依据。

2026-10-10，关联 Issue #4。核对官方在线文档，没有下载源码、安装依赖或运行 Pi / MXC / 搜索集成。用户已在设计讨论中选择全部 Node / TypeScript + Pi SDK，模型 API key 自行配置；本记录补充技术依据，不批准其余候选。

## Pi SDK 与进程边界

[Pi SDK 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md)提供会话创建与显式资源加载接口。默认资源发现不能当成产品隔离；项目应显式控制资源、工具、配置和会话。SDK 的会话取消也不能替代 OS 子进程停止。这些是接入推导，尚未验证资源发现是否全部受控。

[MXC Node API](https://github.com/microsoft/mxc/blob/main/docs/api-reference/node/v1/api.md)提供 probe 与 spawn。建议受保护后台管理配置、额度与提交，在 ProcessContainer 中运行使用 Pi SDK 的独立 Node 执行器；不能因 SDK 可进程内调用就把任意命令工具放入有全部后台权限的进程。实际策略、loopback、文件工具和进程树均待验证。

## Node 文件句柄缺口

[Node fs.open](https://nodejs.org/api/fs.html#fsopenpath-flags-mode-callback)公开参数没有 Windows dwShareMode 选项；这是对公开接口的核对，不表示所有 Node 原生模块都无法实现。

[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)按访问与共享模式取得句柄，冲突可返回共享错误，模式持续到句柄关闭。[Koffi](https://koffi.dev/load)允许 Node 加载 DLL 并声明 Win32 调用约定；[官方支持表](https://koffi.dev/)列出 Windows 和预构建二进制。由此提出 Koffi 窄适配，避免另写完整原生模块；该推导不保证提交原子性或目录身份安全。新增依赖、句柄写回与故障恢复须在 Design 确认和 M01 Plan 验证，未安装。

## 图、MCP 与 Hook

- [Graphology 实例类型](https://graphology.github.io/instantiation.html)包含 MultiDirectedGraph，符合 M04 同端点多关系；仅作 Node 图处理建议，不扩充业务图属性。
- [官方 MCP TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk)本次读取的 main 为 v2 稳定线，服务包为 `@modelcontextprotocol/server`，stdio transport 位于 server/stdio。不要把旧 v1 包名与 v2 API 混用；Plan 再固定实际发行组合。
- [Codex Hooks](https://learn.chatgpt.com/docs/hooks)说明 UserPromptSubmit 上下文入口以及 SessionStart 的 compact 来源。当前产品需分别核对普通提交与当前轮 compact 恢复，提示输出不自动证明平台接收或助手采用。生命周期信号及中断时序尚无本产品 Desktop 证据。

## Agent 搜索方式

[Codex 配置](https://learn.chatgpt.com/docs/config-file/config-basic)公开了 cached、indexed、live、disabled 搜索模式；未据此推断内部具体搜索引擎。[OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)是供应商托管工具；能否使用取决于实际模型和协议，不能用兼容 endpoint 名称代替验证。

[Pi CLI 工具清单](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md)的默认工具不自动包含通用网页搜索。另一条路线是给 Pi 注册独立搜索和读取工具：[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[Exa Search](https://exa.ai/docs/reference/search)为候选 API。浏览器可处理动态交互，但初版普通资料核查无需默认依赖它。

设计建议独立 API 加网页读取，让后台模型由用户自由配置；供应商尚未选择。搜索摘要与综合答案不自动替代原文，逐主张保存实际来源和核查缺口。

## 转入设计与待验证

本轮依据转入 [统一 Design](../../spec/v0.1.0/4-initial-development/design.md#technical-selection)。Node / TypeScript + Pi SDK 是用户决定；Graphology、MCP / Hook 接入、Koffi、搜索路线及起始参数是收尾提案。Prompt 九组全文已经编写，语义效果尚未实测。没有产品实施或 Plan，不把文档核对记作集成通过。
