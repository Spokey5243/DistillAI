# Anthropic AI-native SDLC 对 DistillAI 的适配

核对日期：2026-10-04。

来源：[The AI-native SDLC playbook](https://claude.com/blog/the-ai-native-sdlc-playbook)；本地参考为 cac-model-manage 的 `docs/product-inputs/anthropic-ai-native-sdlc-playbook.md` 与 `IKHTXN-ai-native-sdlc` 决策记录。旧借鉴清单记录的是当时状态，不能把其中未勾选项当作当前实现缺失。

DistillAI 保留已经确认的标准开发流程。文章中的 Claude 配置映射为 Codex AGENTS、Skill 和 Hook，GitHub 由本机 gh 操作，不引入 Claude CLI / Anthropic API key。

| 可复用机制 | DistillAI 配置 / 做法 | 状态 |
| --- | --- | --- |
| 每阶段产生版本化交接物 | GitHub Issue → 按类型选择 Intent / Discussion → Design → Plan → Commit / PR / Review | 本地规则与模板已迁移；远端待连接 |
| 组织知识供 Agent 读取 | AGENTS 唯一入口、按任务读取条件规则和调研文档 | 本地已配置 |
| 重复过程编码为 Skill | standard-development-flow、github-pr-review、test-necessity-review | 本地已配置 |
| 写代码前明确计划、交付前反馈 | 非 Direct 按批准点推进，测试 / CI 给出实际结果 | 本地规则与 CI 已配置；云端待运行 |
| PR 交接与 UI 证据 | PR 模板包含 Spec、偏差、测试、风险和文档；有 UI 变化再提供截图 | 模板已配置 |
| 独立上下文审查高风险变化 | reviewer 只接收身份、SHA 和风险，独立核对证据，COMMENT 不替代用户合并决定 | 协议已配置；真实 PR 待验证 |
| Hook 做可解释的流程检查 | PreToolUse Push 检查目标、默认分支新鲜度和一次性放行 | 脚本 / 配置已迁移；Desktop 信任与触发待验证 |
| CI 失败 AI 诊断 | gh 查询 run / logs，输出根因、失败性质、最小复现和建议 | 手动触发的操作规范已配置 |
| 隔离并行任务 | 有独立任务和真实冲突风险时使用 worktree；无提交仓库先初始化 | 按需采用，未建调度系统 |
| 可追溯修订和收尾 | material_revision 计数，记录 Agent 闭环 / 用户确认，合并后检查 implemented / superseded | 规则与模板已迁移 |

## 当前不新增的配置

- 文章里的 Claude `.claude/`、`CLAUDE.md`、Claude 非交互任务和其他 Agent 入口：用户只使用 Codex。
- 模型自动调用的 CI triage / agent-evals：当前没有模型运行接口与经用户核对的行为样本；普通软件测试不能冒充模型语义评估。
- 自动部署、线上监控、值班消息和定期安全 Agent：尚无对应运行设施与持续需求。
- 自动跨越需求 / 设计 / 合并门禁的整套循环：当前按用户确认的标准流程执行。
- 独立指标系统：Design 修订次数已在文档；Issue / PR 时间可从 GitHub 按需查询，出现实际评估需求再统计。

## 后续适合增加的行为评估

DistillAI 引入知识提取 / 用户理解推断后，可使用已审核的合成或获准材料，检验来源追踪、原话与助手总结区分、条件保留、竞争假设和反证更新。先取得可核对的预期结果，再保存少量稳定案例；不要以模型自评或关键词命中当作语义正确。

规则 / Skill 修改的评估同样使用真实决策场景：是否正确识别只读 status、是否阻止旧 SHA 发布、是否将 Direct 无 Issue 误当缺陷、是否误把登录当远端写授权。首次迁移仅记录一次性推演，不把固定 Markdown 文本断言提交为永久测试。
