# GitHub Actions 与 CI 诊断

修改 `.github/workflows/` 或诊断 CI 时生效。

- 当前 CI 为 `ci.yml`：PR 验证、默认分支 Push 验证、手动验证；只有 `windows-tests` 一个 job，显示名 `Windows tests`。
- PR 与 Push 执行同一套命令。采集使用 Windows `msvcrt`，runner 为 `windows-latest`，Python 明确固定为 3.13；未批准跨平台采集前不替换为 Ubuntu。
- Actions 引用固定完整提交 SHA，并注明版本；升级时核对官方 action、runner 要求和实际 CI。
- 当前测试零第三方依赖：`python tests/test_capture.py`、`python .codex/hooks/test_pre_push_guard.py`。不安装 Codex CLI 或模型 SDK。
- CI token 仅有 `contents: read`，checkout 不保留凭证；不在外部 PR 执行 `pull_request_target` + 不可信 head，不向测试交付个人会话或模型密钥。
- CI 保留 PR head、base、测试合并 SHA；默认 PR checkout 测试合并结果，不把 `GITHUB_SHA` 当作 PR head。
- 查询远端检查使用 `gh pr checks`、`gh run list` / `gh run view` 和必要的只读 API。核对仓库、PR、workflow、事件、run ID、head SHA 和结果；同 SHA 的普通分支 Push 不替代 PR 检查。
- 没有检查、检查未完成、运行取消或日志不可读，都不等于通过。检查失败先查看日志，不通过盲目 rerun 掩盖。
- 诊断报告包含失败步骤、最小日志证据、根因、稳定失败 / 偶发 / 不确定、最小复现和建议动作；修改代码 / workflow 遵循对应任务范围和批准点。
- 扩展 CI 的触发器、权限、依赖或长期 job 前同步 README / Plan；不要为了模板完整添加未存在的前端、发布或模型评估 job。

官方依据：[GitHub workflow 事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)、[gh pr checks](https://cli.github.com/manual/gh_pr_checks)、[gh run view](https://cli.github.com/manual/gh_run_view)。
