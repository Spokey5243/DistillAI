# DistillAI

项目正在探索产品形式、架构与原型设计。

## GitHub 与标准开发流程

项目使用 Codex Desktop 开发，GitHub 管理 Issue / PR / CI，远端操作默认使用本机 GitHub CLI `gh`，不依赖 MCP。首次登录、workflow 权限、建仓、默认分支保护及 Desktop Hook 信任步骤见 [GitHub 配置指南](docs/development/github-setup.md)。

开发任务按 Direct、Medium、Intent、Exploratory 分类；非 Direct 保留 Issue 和对应文档批准点。完整行为规范见 [AGENTS.md](AGENTS.md)、[SDLC 规则](.agents/rules/sdlc.md)，目录说明和模板见 [Spec 工作流](docs/spec/README.md)。Spec 按 `docs/spec/<版本号>/<分支名>/` 管理。

- `$standard-development-flow status`：只读核对阶段、证据和下一门禁。
- `$standard-development-flow continue <Issue编号>`：推进已授权整体流程。
- `$github-pr-review <PR URL>`：默认只读 Analyze，发布当前 COMMENT review 需要明确授权。
- 本地 Push 检查与采集 Hook 是两个职责：`.codex/hooks.json` 检查 Push，`plugins/distill-capture` 保存原始会话；不会因为 GitHub 配置而增加采集事件。

GitHub Actions 的 `CI / Windows tests` 在 PR、默认分支 Push 和手动触发时执行同一套 Windows + Python 3.13 检查。普通分支 Push 的 job 跳过，不算 PR 通过。Actions 只有只读 Contents 权限，不需要 GitHub / 模型 secret，也不会自动创建 Issue / PR 或调用模型。

允许先发布开发规范、后发布插件：Push 检查始终执行；插件与采集测试均未提交时，CI 明确输出采集行为未验证。提交 `tests/test_capture.py` 后自动运行采集测试并传播失败；提交采集插件却遗漏测试时 CI 失败。CI 只验证已提交版本，不读取本机未跟踪文件。

完整本地检查：

```powershell
python tests/test_capture.py
python .codex/hooks/test_pre_push_guard.py
```

迁移与验证记录见 [迁移计划](docs/development/github-sdlc-plan.md)，Anthropic 文章的采用与暂缓项见 [AI-native SDLC 适配](docs/development/ai-native-sdlc.md)。
