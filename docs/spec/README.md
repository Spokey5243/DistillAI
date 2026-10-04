# Spec 工作流

`docs/spec/` 按“目标版本 → 分支 → Spec 文档”保存需要长期保留的预期、决策和实施计划。强制行为以根 `AGENTS.md` 及其显式路由的 `.agents/rules/sdlc.md` 为准，本文件解释文档结构和生命周期。

## 版本入口

各版本目录中的 README 汇总该版本的分支任务；对应任务提交时同步入口。

## 工作流选择

| 工作流 | 适用条件 | Issue | 文档与批准点 |
| --- | --- | --- | --- |
| Direct | diff 和提交说明可完整解释修改 | 不要求 | 无 Spec，直接修改、验证、Commit、PR |
| Medium | Agent 可在给定问题、结果和边界内独立完成多步任务 | 必须 | 用户确认分类后，Agent 连续完成 Design、Plan 和实现 |
| Intent | 需要多轮沟通明确预期效果，但不共同选择架构 | 必须 | Intent、Design、Plan 分别由用户批准 |
| Exploratory | 需要共同选择产品、架构或技术路线 | 必须 | Discussion、Design、Plan 分别由用户批准 |

判断顺序为 Exploratory → Intent → Medium → Direct。Agent 可以建议升级，不能自行降级已确认的工作流。

## 目录与模板

```text
docs/spec/<版本号>/
├── README.md                 # 本版本的分支索引
└── <分支名>/
    ├── intent.md             # 仅 Intent 工作流
    ├── discussion.md         # 仅 Exploratory 工作流
    ├── design.md
    └── plan.md
```

版本目录使用 `v<主版本>.<次版本>.<修订版本>`，例如 `v0.1.0`。一个版本可以包含多个 Issue 和分支；每个分支的 Spec 始终独立存放在自己的目录中，批准记录也按分支管理。

分支目录使用实际 Git 分支名去掉 `codex/` 前缀后的名称：

| Git 分支示例 | Spec 目录示例 | Issue 元信息 |
| --- | --- | --- |
| `codex/123-capture-validation` | `docs/spec/v0.1.0/123-capture-validation/` | `issue: 123` |
| `codex/capture-validation` | `docs/spec/v0.1.0/capture-validation/` | `issue: null` |

无 Issue 时，分支名直接描述任务。是否需要 Issue 或 Spec 由现有工作流分类决定；有 Spec 时必须归入对应版本的分支目录。

按实际工作流选择文件，不要求四份齐全。模板位于 `docs/spec/templates/`；复制后删除不适用章节，不机械填充“无”。历史 Spec 不因模板升级批量重写，流程引入前的文档不补造 Issue 或批准记录。

## 元信息

```yaml
---
version: v0.1.0
issue: 123
branch: codex/123-example
workflow: medium | intent | exploratory
status: draft | approved | implemented | superseded
decision_mode: agent-closed | user-approved
---
```

- `version`：目标版本，与所在版本目录一致；
- `issue`：实际关联 Issue 编号，无关联 Issue 时为 `null`；
- `branch`：完整 Git 分支名，与所在分支目录对应；
- `status`：文档生命周期；
- `decision_mode`：`agent-closed` 表示 Medium 在已确认边界内由 Agent 闭环，`user-approved` 表示该文档是人工门禁；
- Design 额外包含 `material_revision: 0`，统计首次批准后的成组实质修订。

## 文档职责

- Issue：背景、问题、范围、非目标和验收入口；
- Intent：用户场景、业务规则、预期行为和验收标准，不预设技术架构；
- Discussion：事实、候选方案、权衡、否决理由和最终决定，不保存聊天逐字稿；
- Design：最终方案、模块/接口/数据边界、流程、异常、兼容、迁移、回退和验证策略；
- Plan：实施顺序、文件、命令、验证、依赖、状态和相对 Design 的偏差；
- Pull Request：实际变更、验证证据、Design 偏差和文档同步。

## 生命周期

1. 新建文档时使用 `draft`；
2. 对应门禁确认后改为 `approved`；
3. 实现和验证完成后改为 `implemented`；
4. 被新方案替代时改为 `superseded` 并指向替代文档。

Intent 与 Exploratory 的前一份文档未获批准时不得进入下一阶段。Medium 只在分类时人工确认，之后由 Agent 连续闭环；出现新需求选择、架构选择或范围扩大时暂停并升级。

已批准 Design 是实施基线。实现发生实质方案变化时先同步 Design；变化影响步骤、顺序、依赖、迁移、验证或回退时同步 Plan。详细判断见 `.agents/rules/sdlc.md`。

## Discussion 连续性

Discussion 使用单文件、稳定 D 编号和简短工作状态索引。只在用户确认、主题切换、阶段暂停或形成需要保留的候选方案时写入语义检查点；上下文恢复时定向读取当前主题，收敛前再完整核对一次。

## 测试

Discussion、Design 或 Plan 涉及测试时，先读取 `.agents/skills/test-necessity-review/SKILL.md`。永久测试必须保护持久行为；文件布局、固定模板文本和一次性迁移只做针对性验证并记录证据。
