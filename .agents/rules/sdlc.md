# SDLC 规则

本文件仅在根 `AGENTS.md` 显式路由且任务不是明显 Direct，或需要创建、确认、同步 Spec 时生效。

## 工作流分类

按以下顺序选择唯一工作流：

```text
需要共同选择产品、架构或技术路线？ → Exploratory
否则，需要多轮沟通才能明确预期效果？ → Intent
否则，需要多步实施并保留解决记录？   → Medium
否则                                  → Direct
```

### Direct

适用于 diff 和一两句提交说明足以无歧义还原修改事实、原因和约束的变更。Direct 不要求 Issue、Discussion、Design 或 Plan，执行“修改 → 验证 → Commit → Pull Request”。只要包含无法从 diff 还原的产品、兼容、安全或架构取舍，就不得使用 Direct。

### Medium

适用于用户只需说明问题、预期结果和边界，Agent 即可在无需后续产品或技术选择的情况下独立完成的多步任务。必须先有 Issue；Agent 说明分类依据，用户确认后，Agent 以 `decision_mode: agent-closed` 连续生成 Design、Plan、实现、验证和文档同步。出现需求歧义、产品行为选择、架构选择或范围扩大时立即暂停并升级。

### Intent

适用于需要多轮沟通才能明确“做成什么样”，但沟通不涉及架构共同选择的功能。流程为 Issue → Intent 批准 → Design 批准 → Plan 批准 → 实现。每份文档是独立人工门禁；Design 阶段发现重要技术路线需要共同探索时升级为 Exploratory。

### Exploratory

适用于产品行为、架构或技术路线尚未确定，存在多个权衡方案，或需要调研、实验、原型后决策的任务。流程为 Issue → Discussion 批准 → Design 批准 → Plan 批准 → 实现。Discussion 保存事实、候选方案、权衡、否决理由和最终决定。

Medium、Intent、Exploratory 必须先有 Issue，并由用户确认 Agent 报告的工作流分类。Agent 可以建议升级，不能自行降级已经确认的工作流。

## Spec 位置与元信息

Spec 存放在 `docs/spec/<版本号>/<分支名>/`，结构和模板见 `docs/spec/README.md` 与 `docs/spec/templates/`。版本目录汇总分支入口，每个分支独立保存自己的 Spec 文档。目录中的分支名去掉 `codex/` 前缀：有关联 Issue 时使用 `<Issue编号>-<slug>`，无关联 Issue 时使用 `<slug>`；不补造 Issue 编号。统一元信息为：

```yaml
version: v0.1.0
issue: 123
branch: codex/123-example
workflow: medium | intent | exploratory
status: draft | approved | implemented | superseded
decision_mode: agent-closed | user-approved
```

`version` 与所在版本目录一致；`branch` 使用完整分支名，并与分支目录对应；`issue` 使用实际编号，无关联 Issue 时为 `null`。是否需要 Issue / Spec 仍按上述工作流分类执行。Design 额外使用 `material_revision: 0`。Direct 不创建 Spec。流程引入前的历史文档保留原记录，不补造 Issue 或批准状态。

## Discussion 连续性

- 每份 Discussion 使用单一文件、简短工作状态、稳定 `D01` 等主题 ID 和 `exploring`、`confirmed`、`superseded` 状态。
- 用户确认、主题切换、阶段暂停或形成需要保留的候选方案时写入语义检查点；一次 Patch 同步更新主题与状态索引。
- 上下文恢复时先读 frontmatter、工作状态和当前主题，需要时按 ID 定向读取；只在阶段收敛前完整读取一次。
- 不为每个主题创建临时文件，不逐轮落盘，不保存聊天逐字稿。

## Design 与 Plan 同步

- 已批准 Design 是实施基线。实现发现遗漏或偏差时，不能只修改代码。
- 在已确认目标、范围和约束内的明显遗漏、异常流程或技术事实，可由 Agent 更新 Design 并标记 `Agent 闭环`。
- 改变用户可见行为、验收标准、范围、非目标、公开 API、数据兼容、安全边界、破坏性迁移、重要模块边界，或存在多个长期选项时，必须先请求用户确认。
- Design 首次批准时 `material_revision` 为 `0`；实施后每组成组形成新基线的实质变化加一，并记录内容、原因、决策方式和 Plan 影响。措辞、错别字、状态和不改变含义的证据补充不计数。
- Design 变化影响实施步骤、顺序、依赖、迁移、验证或回退时同步 Plan；仅澄清原因或约束且实施方式不变时记录“Plan 不受影响”。

## Review 一致性

- Review 同时核对最新 Design、Plan 和实现，但差异本身不是 finding。
- 只有违反明确约束或存在具体失败路径时报告代码 finding；纯文档漂移作为 Spec 同步阻塞项或 `Uncertain`。
- 检查修订记录的决策方式；Agent 把超出授权边界的变化标记为 `Agent 闭环` 时，必须请求用户确认，不能机械回退代码。

## 测试与文档

- Discussion、Design 或 Plan 涉及测试时，必须读取 `.agents/skills/test-necessity-review/SKILL.md`，区分永久测试和一次性验证。
- Plan 记录可执行步骤、验证命令和状态；Pull Request 记录实际变更、验证证据、Design 实质偏差和文档同步。
- 不适用的模板章节可以删除，不机械填写无意义内容。
