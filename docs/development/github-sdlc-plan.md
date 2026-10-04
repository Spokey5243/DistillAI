# GitHub SDLC 迁移计划与执行记录

**Goal:** 保留 cac-model-manage 的标准开发流程，迁移到 DistillAI，使用 GitHub CLI 维护 GitHub。

**Architecture:** AGENTS 是规则入口；SDLC 规则、Spec 模板、流程与审查 Skill 各司其职。GitHub CLI 使用本机凭证，CI 运行已有 Windows/Python 测试，Push 检查使用 Python 标准库。

**Tech Stack:** Codex Desktop、Python 3、Git、GitHub CLI、GitHub Actions；不增加项目依赖。

## 授权与范围

- 2026-10-04：用户批准上一轮迁移清单，排除其他 Agent 入口；授权调研并选择实用的 GitHub 接入方式。
- 来源：cac-model-manage，本地 HEAD `e847ca3e7528ed83aac94c1bdd0cfecf5a8c0924`。
- 本次为已批准的仓库启动迁移，当前无提交、无 origin，无法先关联远端 Issue。此记录只用于本次启动，不作为后续非 Direct 任务绕过 Issue 的通用例外。
- 当前分支：`codex/github-sdlc`。保留现有调研文档、MVP 文档和采集代码。
- 不创建远端仓库、不创建远端 Issue/PR、不 Push、不提交初始项目；这些由用户配置后再开展。

## 文件映射

- 修改：`AGENTS.md`、`README.md`。
- 新增：`.agents/rules/{sdlc,python,frontend,github-actions}.md`。
- 迁移：Spec 工作流说明、四份模板、三个 Skill（standard-development-flow、github-pr-review、test-necessity-review）。启动时使用的 Spec 目录现已统一为 `docs/spec/`，版本文档按版本号归档。
- 新增：`.github/pull_request_template.md`、`.github/workflows/ci.yml`。
- 迁移改写：`.codex/hooks.json`、Push 检查脚本与现有行为测试。
- 新增：本计划、`docs/development/github-setup.md`、`docs/development/ai-native-sdlc.md`。
- 不迁移：其他 Agent 入口/适配、业务代码、旧 Spec、Gitee MCP 配置、Docker/MinIO 部署设施。

## 实施

- [x] 检查原项目规范、Anthropic 文章、当前仓库和 GitHub CLI 的登录状态；核对官方 GitHub/Codex 文档。
- [x] 迁移规则、模板和 Skill；GitHub API 替换 Gitee 工具，保留完整 SHA、只读审查、批准点和幂等处理。
- [x] 复制既有 Push 行为测试，增加动态默认分支、失败关闭和失效授权用例，先运行 RED，再改写检查脚本。
- [x] 配置 Windows CI：`python tests/test_capture.py` 与 `python .codex/hooks/test_pre_push_guard.py`，沿用标准库测试。
- [x] 编写 GitHub 设置步骤和 Anthropic 借鉴说明；同步 README，保留已有调研路由。
- [x] 运行下述验证，检查文档引用、配置、敏感文件及源码保留情况，记录实际结果。

## 验证

```powershell
python tests/test_capture.py
python .codex/hooks/test_pre_push_guard.py
python -X utf8 C:\Users\11954\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents/skills/standard-development-flow
python -X utf8 C:\Users\11954\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents/skills/github-pr-review
python -X utf8 C:\Users\11954\.codex\skills\.system\skill-creator\scripts\quick_validate.py .agents/skills/test-necessity-review
git diff --check
git status --short
```

Expected: 采集用例通过，Push 行为测试 OK，三个 Skill 校验通过；JSON/YAML 和本地链接检查通过。配置、文档结构和迁移保留检查只做一次性验证，不新增永久文本测试。Push 测试仅访问临时本地 bare 仓库。

## 执行记录

- 已确认 GitHub CLI 2.93.0 登录 `Spokey5243`，凭证保存在 keyring，当前 scopes 为 `repo`、`read:org`、`gist`；尚缺用于更新 workflow 文件的 `workflow` scope，用户按设置指南刷新授权。
- RED：新增用例针对原脚本得到 8 failures / 5 errors，暴露固定 master、默认分支和无效输入等缺口；改写后 16 项 Push 行为测试全部通过。
- 采集测试通过：UTF-8、payload、追加写入、会话隔离、并发、无效输入、fail-open、平台覆盖。
- 三个 Skill 的 quick_validate 均返回 `Skill is valid!`；Python 语法、JSON/YAML、本地 Markdown 引用、Actions 固定 SHA / 只读权限、平台遗留和凭证扫描通过。
- 对迁移前保存的 22 个采集、产品、调研和 MVP 文件做 SHA-256 比较，一致；README 的原有正文保留，追加开发入口。
- 临时 Git index 中检查全部新增规则 / 模板 / 配置 / 文档，`git diff --cached --check` 通过；使用仓库既有 `core.autocrlf=true`，真实暂存区保持空。一次性检查脚本与基线保存在忽略的 `.artifacts/github-sdlc/`，不纳入项目测试。
- 本地推演：status 保持只读；Direct 无 Issue 不误报；PR head 变化须重新审查；不确定发布结果先按 marker 回读；squash / rebase 以真实 merged 状态及合并后提交核验，不要求原 head 祖先关系。以上是流程检查，不冒充模型行为评估。
- 本地迁移与 Hook 单元测试可在远端未配置时完成。GitHub CI 和 Desktop Hook 的真实触发验证须在用户配置/信任后执行；静态配置检查不替代这两项。
