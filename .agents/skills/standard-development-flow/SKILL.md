---
name: standard-development-flow
description: Inspect the current GitHub development stage or resume the overall Issue-to-merge lifecycle in DistillAI. Use for overall status or continuation, not for a single code edit, Push, or PR review.
---

# Standard Development Flow

编排整体流程，依据仓库和远端事实恢复阶段；规则来源为根 `AGENTS.md` 和 `.agents/rules/sdlc.md`，不复制其完整正文。

## 入口

- `$standard-development-flow status`：只读检查当前阶段、证据、缺失信息和下一门禁，不修改文件 / 暂存 / Commit / 远端对象。
- `$standard-development-flow continue [Issue编号或URL]`：推进已授权整体流程至下一失败、冲突、未决选择或人工批准点。
- 查询整体开发阶段可隐式触发 status；要求继续整个 Issue / 分支流程可隐式触发 continue。
- 单项修复、Commit、Push、PR Review 不强制进入此编排。当前门禁得到用户回复后继续，不要求重复输入 Skill 名。
- 新 Direct 无 Issue 时需要明确短目标。续接目标不唯一时询问，不猜测任务。

## 事实恢复

依次核对：

1. 仓库根、分支、HEAD、status / diff、upstream、worktree。
2. 当前 GitHub 账号、origin、已验证的 owner/repo 和实际默认分支。
3. 唯一 Issue、用户确认的工作流、Spec 元信息与批准状态。
4. 任务提交、执行记录和最新验证证据。
5. 远端分支、PR、完整 head SHA、关联 Issue、CI / Review。
6. 合并状态、合并后提交、Issue 状态和本地同步情况。

聊天是线索，不是仓库状态；不另建工作流数据库。远端尚未配置或 HEAD 尚不存在时如实报告，不能声称远端已准备好。

关联 Issue 用真实 GitHub 编号。分支 / Spec 线索需与远端 Issue 内容核对，多个候选由用户选择。Direct 允许无 Issue，明确记录该事实。

## 续接

1. 完成当前流程的必要批准点；不把当前用户确认降级为更简单的流程。
2. 优先使用当前工作区；有其他任务、无关修改或并行需求时才考虑隔离。保留已有未提交内容。
3. 按批准 Spec 完成本地实施、相关验证和文档同步，在任务分支形成可审阅提交。
4. GitHub 阶段读取 `references/github.md`；审查读取 `github-pr-review`，测试设计读取 `test-necessity-review`。
5. 在用户已明确授权范围内执行远端操作；新动作缺少授权时展示具体目标与待审内容，不沿用其他动作的授权，也不反复索要已有授权。
6. 发生验证失败、冲突、范围扩大、证据不足或 SHA 改变时先解决当前问题，不继续推进后续阶段。

标准链路按所选类型为 Issue → Intent / Discussion → Design → Plan → 实现 → 验证 → Commit → Push → PR → Review → Merge → Issue 收尾与本地同步；Direct 和 Medium 的差异以 SDLC 规则为准。

## Push 与收尾

- Push 前 fetch 默认分支并检查祖先关系；落后时询问是否仍推送，用户同意后运行 `python .codex/hooks/pre_push_guard.py authorize`，再用同一工作区执行独立的标准 `git push`。
- PR 创建前按仓库和 head 分支查重；创建后将实际 PR URL 附加到当前 Codex chat。
- Review 绑定最新完整 SHA；用户确认待发布全文后 Post，发布不自动授权 Merge。
- Merge 默认人工执行。Agent Merge 需要明确授权和最新 CI / Review / 保护规则证据。
- GitHub 自动关闭关联 Issue 时先读回状态，不重复 close；未关闭时按授权处理。
- 核对真实 merged 状态和合并后提交后，本地默认分支仅 `--ff-only` 同步；不强制覆盖不同历史。
- squash / rebase 合并可能不保留原 head 祖先关系。分支删除前核对 GitHub merged 与合并后是否还有新增提交；`git branch -d` 拒绝时报告，不自动 `-D`。
