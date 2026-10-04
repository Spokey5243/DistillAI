# GitHub CLI Adapter

仅在整体流程进入 GitHub 阶段时读取。使用现有 `gh` 和 keyring，不配置 MCP；当前机器配置见 `docs/development/github-setup.md`。

## 仓库与账号

```powershell
gh auth status --hostname github.com
gh repo view --json nameWithOwner,defaultBranchRef,viewerPermission,url
git remote get-url origin
git ls-remote --symref origin HEAD
```

核对两种仓库识别一致。后续 `$repo` 表示已验证的 `owner/name`，`$issue` / `$pr` 表示真实编号，`$head` 是当前完整 PR head；不要把示例编号当作待操作目标。

身份 / 远端检查只读；凭证不能输出。对有明确 GitHub 权限限制的操作，报告实际限制，不能把缺少授权或 403 当成对象不存在。

## Issue / PR 与写入

```powershell
gh issue view $issue --repo $repo --json number,title,body,state,url
gh pr list --repo $repo --state open --head $branch --json number,url,headRefName,headRefOid,baseRefName
gh pr view $pr --repo $repo --json number,title,body,url,state,headRefOid,headRefName,baseRefName,isDraft,closingIssuesReferences,statusCheckRollup,mergeStateStatus,reviewDecision
```

授权后，Issue / PR 文本先写入 UTF-8 文件并展示，调用 `gh issue create/edit` 或 `gh pr create/edit --body-file`；不通过 shell 拼接多行正文。创建 PR 时显式指定 base / head；创建后使用 Codex `attach_artifact` 附加 URL。

写入超时或返回不明确：先按 Issue、PR、source branch 或审查标记查询，再决定重试。不要让同一未知结果重复创建对象。

远端每种动作有自己的授权，用户明确列出的批量动作可分别作为对应授权；Spec 批准和登录成功不自动授权远端写。

## CI 与诊断

```powershell
gh pr checks $pr --repo $repo --json name,state,bucket,workflow,link,event
gh run list --repo $repo --workflow ci.yml --event pull_request --commit $head --json databaseId,headSha,event,status,conclusion,url,workflowName
gh run view $runId --repo $repo --json headSha,event,status,conclusion,jobs,url
gh run view $runId --repo $repo --log-failed
```

`gh pr checks` 只展示最新状态，不携带完整 head 字段；结合 PR metadata、run 信息、运行日志中的 head / base / tested SHA 确认对应关系，再读回 PR head，发生变化重新核对。

GitHub PR workflow 默认测试合并结果；head / base / 合并 SHA 不能混用。多个 PR workflow / rerun 候选需核对事件、PR 与最新尝试，不随便选择一条成功记录。跳过、取消、pending、无检查或查询失败不算通过；最终还需满足仓库实际 required checks / rules。

若 head 过滤没有结果，不直接判定没有 CI：从当前 PR checks 的链接定位 run，并读取 `gh api "repos/$repo/actions/runs/$runId"` 的 `pull_requests`、`head_sha` 与事件信息，结合日志确认测试对象；确实无法建立对应关系时报告未知。

有失败时输出步骤、根因、失败性质、最小复现和建议。先做只读诊断，本地修复依当前任务范围，rerun 需要授权。没有权限读取日志时保留未知状态，并请求该 run / SHA 的证据。

## 审查与合并

审查与发布用 `github-pr-review`；默认发布一个 `COMMENT` review，明确 `commit_id`，不自动 Approve / Request changes。作者使用同一账号时 AI Comment 仍是辅助审查，不能伪装独立用户批准。

用户合并后或已授权 Agent Merge 返回后，读取：

```powershell
gh api "repos/$repo/pulls/$pr" --jq '{merged: .merged, head: .head.sha, base: .base.ref, merge_commit_sha: .merge_commit_sha}'
```

要求 `merged == true`，核对最后已审查 head 与 API head；获取 base 后确认 **合并后的** `merge_commit_sha` 在 base 历史中。字段为空或历史不可核验时保持未完成。合并前同名字段可能是临时测试合并提交，不能作为已合并证据。

GitHub 支持 squash / rebase，因此不一律检查原 head 是否是 base 祖先。授权 Agent Merge 时使用 `gh pr merge --match-head-commit`，选择仓库允许且用户同意的 merge method；遇到合并队列时加入队列不等于已合并，继续按真实 merged 状态确认。

对比 `closingIssuesReferences` 与 Issue 实际状态，避免重复关闭。`Closes #编号` 会请求合并时自动关闭；需要独立关闭门禁时只写 `关联 #编号`。

## 官方依据

- [GitHub CLI](https://cli.github.com/manual/)、[身份登录](https://cli.github.com/manual/gh_auth_login)
- [PR checks](https://cli.github.com/manual/gh_pr_checks)、[run view](https://cli.github.com/manual/gh_run_view)
- [合并状态与 merge_commit_sha](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request)
- [SHA 绑定合并](https://cli.github.com/manual/gh_pr_merge)
