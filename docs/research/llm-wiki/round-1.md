# LLM Wiki：知识编译器与 Agent 工作台（2026-10-02）

轮次：第 1 轮（已完成）。项目元信息与各轮简短结论见 [README](README.md)。

## 调研范围与整体分工

本节核对 [atomicstrata/llm-wiki-compiler](https://github.com/atomicstrata/llm-wiki-compiler) 与 [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) 的文档和关键源码，未安装依赖、启动服务或进行运行验证。固定源码快照分别为 `0db26f28084bb95eaa1ea5c8c89319fd471647da` 与 `aac3e6493306b7fff3b09cb181ca93918e93d0e6`，以下机制以这两个快照为准。

两个项目都将原始材料综合成持续更新的 Markdown Wiki。主要差别是：`llm-wiki-compiler` 由程序编排抽取、合并与生成步骤；`lucasastorian/llmwiki` 提供材料工作区与 MCP 工具，通过工作手册指导外部 Agent 自行安排整理步骤。前者的 npm 包名是 `llm-wiki-compiler`，命令名也是 `llmwiki`，不能据此与后者混为同一个项目。

| 比较项 | llm-wiki-compiler | lucasastorian/llmwiki |
| --- | --- | --- |
| 主要角色 | 调用模型完成指定步骤的知识编译器 | 外部 Agent 操作的 Wiki 工作台 |
| 原始材料 | 摄入后保存到 `sources/` | 保存在指定工作区；支持上传、网页剪藏、高亮与批注 |
| 生成内容 | `wiki/` 下的 Markdown 页面 | `wiki/` 下由 Agent 编写的 Markdown 页面 |
| 派生状态 | `.llmwiki/` 保存编译状态、检索索引及候选页等 | 本地 `.llmwiki/` 保存可重建的 SQLite 索引和提取缓存 |
| 流程由谁决定 | 内置编译流程、提示词与页面规则 | 外部 Agent 根据 `guide` 和当前任务决定 |
| 自动更新入口 | `watch` 监听来源变化并触发编译 | 文件监听器建立索引；外部定时任务启动 Agent 整理 |
| 审核与维护 | 可选候选页审核、引用检查与模型评估 | Agent 直接编辑；结构检查与语义审查分别进行 |

## llm-wiki-compiler：材料摄入与概念抽取

`sources/` 的写入既可由用户执行摄入命令或准备 Markdown 材料，也可由 Agent 调用 MCP 的 `ingest_source`，还可由后台程序调用摄入接口。接入方负责选择哪些材料进入知识库；编译器处理已摄入材料，不会因安装或连接 MCP 就自动采集所有聊天。

```text
用户 / Agent / 后台采集程序
    → 摄入材料并保存到 sources/
    → 检测来源变化
    → LLM 抽取概念
    → 按概念标识合并各来源的贡献
    → LLM 生成或更新概念页
    → 保存页面、处理链接、更新编译状态与检索索引
```

抽取阶段的调用链是 `extractForSource()` → `extractConcepts()` → `buildExtractionPrompt()` → 模型调用 → `parseConcepts()`。每份来源的完整文本与已有 `wiki/index.md` 一起进入抽取提示词；现有索引帮助模型识别已有主题并保持命名一致。符合条件的未变化来源可以复用已保存的抽取结果。

概念选择主要由提示词与 LLM 判断完成。默认要求每份来源选出约 3–8 个有意义、值得独立查阅的主题，关注重要思想、技术、模式或实体，参考已有索引避免重复。因此这里的“概念”既可以是抽象思想，也可以是具体产品或实体；数量是提示词要求，解析器不强制返回 3–8 个。

模型通过名为 `extract_concepts` 的结构化输出接口返回 `concepts` 数组。每项必需字段为概念名称 `concept`、一句话摘要 `summary`、是否为新概念 `is_new`；可选字段包括 `tags`、`confidence`、`provenance_state` 与 `contradicted_by`。`confidence` 是模型对来源支持程度的自评；`provenance_state` 区分直接提取、综合、推断或歧义。程序进行 JSON 解析和基础字段类型检查，这些字段不表示用户理解程度。

抽取完毕后，合并函数按概念名称转换得到的 `slug` 分组，汇集贡献来源，再生成对应页面。这个合并函数没有另做语义相似度判断；同义但名称不同的概念，需要模型在抽取时尽量统一命名。因此，概念归一效果仍依赖模型与现有索引的提示。

参考固定快照：[摄入与 MCP 工具](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/docs/guides/mcp-agent-integration.mdx)、[抽取阶段](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/src/compiler/extraction-phase.ts)、[提示词与结构化结果解析](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/src/compiler/prompts.ts)、[跨来源合并](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/src/compiler/extraction-merge.ts)。

## llm-wiki-compiler：增量更新、审核与检索

编译器记录来源哈希及其贡献的概念，来源变化时找到受影响页面。共享概念页面会结合其他贡献来源重新生成；未变化来源可以复用抽取元数据，但仍提供页面生成所需的来源文本。来源和生成设置均未变化时，跳过抽取与页面生成；向量索引的修复或更新另行判断。

默认编译直接写入 Wiki；`--review` 将生成页暂存为候选，批准后才发布。选择性审核策略也可以拦截低置信度、冲突或来源问题。自定义 `--instructions` 提供额外提示词指导，但在本次快照中，`watch`、`refresh --stale` 和 MCP 编译工具不接收这个选项；持续后台更新时需要确认自定义规则是否确实传入。

正文引用可以定位到来源文件及行范围。`lint` 检查来源存在、格式和行号是否合法；完整 `eval` 可抽样让评审模型判断来源是否支持论断。引用可解析和语义上有支持是两个不同检查，模型评审也不等于人工确认的事实。

查询时仍使用检索：按问题选择相关页面或文本片段，沿 Wiki 链接扩展邻居，并组装有预算限制的上下文包供 Agent 使用。预先综合成 Wiki 与查询时检索可以同时存在。

参考固定快照：[编译、增量与审核](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/docs/cli/compile.mdx)、[来源引用与评估](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/docs/concepts/citations.mdx)、[上下文组装](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/src/context/build.ts)。

## lucasastorian/llmwiki：guide 指导外部 Agent

`guide` 是一个 MCP 工具。源码中的 `GUIDE_TEXT` 保存工作手册，调用工具时再追加当前可用知识库的名称与标识。Agent 收到这段文本后，依据其中规则使用搜索、读取、创建、编辑和检查工具。可以将其理解为通过工具动态提供的项目操作指南。

手册说明原始材料与生成 Wiki 的职责，规定总览、概念页、实体页的组织方式，以及元数据、脚注引用和交叉链接的写法。新来源流程是阅读材料，创建或更新相关页面，再维护总览；回答问题时先检索与阅读，有价值的综合结果可以继续写成页面。`guide` 提供推理与操作指导，实际动作由 Agent 调用 MCP 工具执行，格式等程序约束由写入校验和 `lint` 检查。

```text
文件上传 / 网页剪藏 / 用户高亮和批注
    → 解析材料、建立索引
    → 用户请求或外部调度器启动 Agent
    → Agent 调用 guide，读取手册与知识库列表
    → 搜索和阅读材料
    → 创建、编辑并维护 Wiki 页面
    → 检查引用、关联与可能过时的页面
```

页面写入后，系统解析脚注和链接形成引用关系，返回反向引用与受影响页面线索。`lint` 检查结构、引用目标、链接及过时状态；冲突、遗漏或综合质量由 Agent 另做语义审查。本地文件系统是来源和 Wiki 的持久存储，SQLite 索引与提取缓存是派生数据。

搜索可区分原文与用户高亮、批注的命中，便于分别保存“材料的主张”和“用户对此表达的意见”。高亮表示用户关注过材料，不能直接判定已理解；批注也需要保留原话及具体语境。

参考固定快照：[guide 正文与工具注册](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/mcp/tools/guide.py)、[搜索与批注区分](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/mcp/tools/search.py)、[页面写入](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/mcp/tools/write.py)、[结构检查](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/mcp/tools/lint.py)。

## 自动触发与人工介入的位置

两个项目都不要求用户在每轮 Prompt 中重复要求建库，但需要预先设定材料范围、整理任务和触发方式。注册 MCP 只提供可调用能力；是否调用、何时调用由 Agent 任务或外部编排决定。

| 运行方式 | 触发者与执行流程 | 人工介入位置 |
| --- | --- | --- |
| compiler 的 CLI / MCP 编译 | 用户、Agent 或程序调用摄入与编译入口 | 初次指定材料和任务；后续也可程序调用 |
| compiler 的 `watch` | 保持监听进程运行，`sources/` 新增或修改触发编译，编译器调用模型 | 初次配置来源和模型；有审核策略时处理候选页 |
| llmwiki 的交互使用 | 用户给外部 Agent 任务，Agent 阅读 `guide` 并维护页面 | 初次给出建库目标，或按需要请求更新 |
| llmwiki 的定时维护 | 外部定时任务自动提交预设 Prompt，Agent 检查新材料并更新 Wiki | 初次配置 MCP、任务 Prompt 和调度；日常可自动执行 |

`lucasastorian/llmwiki` 的 README 建议首次告诉 Agent 阅读 `guide` 并摄入材料，随后配置 Claude Routine 或桌面定时任务进行维护。Prompt 仍然存在，但保存在任务配置中，运行时自动提交。其文件监听器负责解析和索引变化，本身不执行知识综合；`guide` 也不启动后台任务。云端任务能否读取本地工作区取决于连接方式，不能仅凭设置定时任务就认定本地数据可被访问。

自动整理知识与自动采集会话是两个环节。若希望处理 Codex 日常对话，仍需把 Hook 等采集结果接入来源入口，并提供后台执行与失败重试机制。两个项目上述流程不等于安装后自动取得 AI 工具的全部会话。

参考固定快照：[compiler Agent Skill](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/skills/llmwiki/SKILL.md)、[compiler watch](https://github.com/atomicstrata/llm-wiki-compiler/blob/0db26f28084bb95eaa1ea5c8c89319fd471647da/docs/cli/compile.mdx#L208-L214)、[llmwiki 首次使用、调度与本地模式](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/README.md)、[llmwiki 文件监听器](https://github.com/lucasastorian/llmwiki/blob/aac3e6493306b7fff3b09cb181ca93918e93d0e6/api/domain/watcher.py)。

## 对 DistillAI 的借鉴与边界

可参考的机制包括：保留原始材料与生成知识的对应关系，同一概念跨会话综合，根据来源贡献或引用关系确定更新范围，以及将人工整理要求写成可复用的 Agent 工作规则。知识库可以由独立后台持续维护，无需用户每轮重复声明任务。

本次核对的核心流程未看到 DistillAI 所需的完整竞争假设验证闭环：形成多个关于用户思考方式的解释，选择有区分力的后续交互，取得用户自己的回应，再支持、削弱或替换判断。Wiki 页面、来源可靠性分数和用户批注都只能提供证据或候选线索，不能自动成为用户掌握程度。

候选链路可以是 `Hook 采集 → 保存原始事件 → 后台读取新增材料 → 综合知识并更新待验证判断 → 按需供前台使用`。本节记录的是机制参考；两个项目尚未接入 DistillAI，知识编译、自动回注和用户假设验证也未因此实现。
