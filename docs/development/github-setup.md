# GitHub 与 Codex 配置指南

方案：**GitHub CLI + 本机登录 + GitHub Actions + 仓库规则 / Skill**。Codex Desktop 在本机调用 `git` / `gh` 完成 Issue、PR、代码审查和 CI 查询，不需要 GitHub MCP、GitHub App 或另一个后台服务。

启动迁移时的检查记录：本机已有 `gh 2.93.0`，活跃账号 `Spokey5243`，HTTPS Git，凭证保存在系统 keyring；scopes 为 `repo`、`read:org`、`gist`。当前仓库无提交、无 origin，迁移分支为 `codex/github-sdlc`。下列建仓、提交、Push 和设置步骤由用户选择执行；本文本身不授权 Agent 写远端。

当前状态（2026-10-04）：仓库已初始化，origin 为 `https://github.com/Spokey5243/DistillAI.git`，默认分支为 `main`；本机已具备 `workflow` scope。主干保护要求 PR、最新基线上的 `Windows tests` 和会话评论已解决，且对管理员生效。下述首次初始化命令保留为操作参考，已初始化仓库无需重复执行。

## 1. 登录与 workflow 权限

已有登录无需重新登录，只补充上传 / 更新 Actions workflow 所需授权：

```powershell
gh auth refresh --hostname github.com --scopes workflow
gh auth status --hostname github.com
```

根据终端提示在浏览器确认授权。如果未来换机器、账号或登录失效，再运行：

```powershell
gh auth login --hostname github.com --git-protocol https --web --scopes workflow
```

HTTPS Push 使用 `gh` 的 Git 凭证助手时运行 `gh auth setup-git --hostname github.com`。现有 Git Credential Manager 已能正确登录时也可沿用；实际账号需与仓库权限一致。

不用把 token 发到聊天、不运行 `gh auth token` 展示凭证，也不把凭证写入 `.env` / `.codex/config.toml`。选择浏览器登录时优先系统凭证存储；登录输出显示 plaintext 存储时先解决凭证存储问题。

依据：[gh auth login](https://cli.github.com/manual/gh_auth_login)、[gh auth refresh](https://cli.github.com/manual/gh_auth_refresh)、[OAuth scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps)。

## 2. 初始提交与创建仓库

以下采用 `Spokey5243/DistillAI`、私有仓库、默认分支 `main`。用户可选择公开仓库；公开前检查拟提交内容，个人原始会话保持在仓库外。无需单独创建 GitHub Projects 看板。

先在项目目录审核 **全部现有未跟踪内容**，尤其调研文档里的本地信息；本次没有自动暂存或 Commit 初始项目。

```powershell
Set-Location E:\JourneyIntoAI\DL_and_LLM\projects\DistillAI
git status --short
git config user.name
git config user.email
git add -- .gitignore AGENTS.md README.md .agents .codex .github docs plugins scripts tests
git diff --cached --stat
git diff --cached --check
git diff --cached
git commit -m "chore: initialize DistillAI with GitHub SDLC"
git branch -M main
gh repo create Spokey5243/DistillAI --private --source . --remote origin
git push -u origin main
git remote set-head origin -a
gh repo view Spokey5243/DistillAI --json nameWithOwner,defaultBranchRef,viewerPermission,url
```

这是无提交 / 空远端情况下的一次启动操作，用户手工初始化允许首次向默认分支 Push。后续开发使用 `codex/<Issue编号>-<slug>` 分支和 PR。不要把首次建仓例外用于后续直接推默认分支。

若仓库已由网页创建，**不要再运行 create**：创建时不勾选远端 README / license / gitignore，以免生成另一段历史；用 `git remote add origin https://github.com/Spokey5243/DistillAI.git` 连接空仓库，再执行首次 Push。若远端已有提交，先核对其内容 / 历史，不强推、不覆盖。

依据：[从本地创建 GitHub 仓库](https://cli.github.com/manual/gh_repo_create)。

## 3. GitHub 仓库设置

首次 Push 后，确认默认分支为 `main`；自动化实际读取 default branch，不依赖名称。

1. **Settings → General → Features**：启用 Issues。
2. **Settings → Actions → General**：启用 Actions，允许官方 `actions/checkout` / `actions/setup-python`；工作流只需要只读 Contents 权限。无需勾选“Allow GitHub Actions to create and approve pull requests”，当前远端写入来自本机 gh。
3. **Settings → General → Pull Requests**：选择允许的合并方式；本项目兼容 merge / squash / rebase。可以启用合并后自动删除分支，本地分支仍需按规则单独清理。
4. 先让 CI 在首次 Push 和一个真实 PR 上运行。检查名稳定为 **Windows tests**；配置检查不等于云端实际运行成功。
5. 账号 / 仓库套餐支持时，在默认分支保护规则或 Ruleset 中要求 PR 和 **Windows tests** 通过，禁止强推 / 删除默认分支。个人单账号项目不设置必须由另一人 Approve；GitHub 不允许作者批准自己的 PR。AI Comment 可保留为审查证据，最后由用户明确决定 Merge。

分支保护能力依 GitHub 套餐和仓库可见性而异，以当前仓库 UI 为准。没有平台强制保护时仍遵守 AGENTS 的 PR / 验证门禁，不能把未启用保护描述成已强制。

当前 CI 为 Windows + Python 3.13，执行采集与 Push 检查测试，零模型 / 项目依赖。普通分支 Push 会产生被 job 条件跳过的 workflow；它不算 PR 验证通过。

依据：[分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule)、[审查与作者限制](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request)。

## 4. Codex Skill 与 Push Hook

仓库 Skill 位于 `.agents/skills/`，AGENTS 显式路由；重新打开 / 新开此项目 chat 后检查 Skill 是否可用。即使当前会话目录缓存未刷新，Agent 仍按 AGENTS 的文件路径读取。

- `$standard-development-flow status`：只读查看当前阶段。
- `$standard-development-flow continue 123`：继续编号为 123 的真实 Issue 流程。
- `$github-pr-review <PR URL>`：分析完整当前 PR；只有明确“发布”后才写 COMMENT review。

项目 Push Hook 位于 `.codex/hooks.json`。Codex Desktop 的 Hooks 设置里审阅、信任并 Reload 本项目的 `PreToolUse`。使用项目根目录解析脚本路径；统一 exec shell 在当前官方文档中匹配 `Bash`，输入为 `tool_input.command`。

可在实际 Desktop 会话请求 Agent 执行不支持的 `git -P push` 以验证：应看到 Hook deny 并且 shell 不执行。不要用真实成功 Push 当作首次阻断测试。此步骤须在用户信任 Hook 后观察实际触发，脚本单元测试不证明 Desktop 已启用。

支持的普通形式为独立 `git push` 或 `git push -u origin HEAD`；默认分支落后时由用户决定是否继续，再运行 `python .codex/hooks/pre_push_guard.py authorize`。脚本通过远端 HEAD 找默认分支，未知 / 空仓库时拒绝。

这个 Hook 是标准 Push 的流程提醒，文本探测不覆盖别名、变量拼接或包装脚本；Hook 未信任、执行超时或回调失败也不能当作完整安全隔离。平台保护与授权规则继续生效。

依据：[Codex Hooks](https://learn.chatgpt.com/docs/hooks)、[项目配置与信任](https://learn.chatgpt.com/docs/config-file/config-advanced)。

## 5. 配置完成后的只读验收

```powershell
gh auth status --hostname github.com
gh repo view Spokey5243/DistillAI --json nameWithOwner,defaultBranchRef,viewerPermission,url
gh issue list --repo Spokey5243/DistillAI --limit 5
gh pr list --repo Spokey5243/DistillAI --limit 5
gh run list --repo Spokey5243/DistillAI --workflow ci.yml --limit 5
```

把实际仓库 URL 告诉 Codex 后，先核对 origin / 账号 / 权限 / workflow 的只读结果。下一真实任务再授权创建 Issue 和 PR，验证写入与回读，避免为证明权限制造测试 Issue / PR。

可用能力包括：Issue 创建 / 编辑、分支 Push、PR 创建 / 编辑、完整代码与 diff 审查、SHA 绑定 COMMENT review、CI 日志诊断，以及经明确授权的 Merge / Issue 关闭。能力由当前账号权限和平台规则决定；登录成功不代替真实写入验收。
