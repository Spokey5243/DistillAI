# LLM Wiki 调研

| 对象 | 本地路径 | 远端地址 |
| --- | --- | --- |
| Karpathy LLM Wiki 构想 | `E:\JourneyIntoAI\DL_and_LLM\projects\karpathy-llm-wiki-gist` | [GitHub Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) |
| llm-wiki-compiler | 本地未提供 | [atomicstrata/llm-wiki-compiler](https://github.com/atomicstrata/llm-wiki-compiler) |
| llmwiki | 本地未提供 | [lucasastorian/llmwiki](https://github.com/lucasastorian/llmwiki) |

首轮核对范围：原始构想和两个实现的固定源码快照；两个实现未运行验证。首轮主要核对时间：2026-10-02。

## 各轮调研简短结论

### 第 1 轮 · 已完成

- 原始 gist 提出持续维护 Markdown Wiki 的思路；两个实现分别通过内置编译流程和 guide 指导外部 Agent 综合知识。
- 可借鉴跨来源合并概念、保留引用、按来源变化更新页面；自动整理仍需要明确的材料入口和触发者。
- 知识综合不能自动成为用户理解判断；两个实现按固定源码快照核对，未运行验证，竞争假设验证仍是 DistillAI 的待设计能力。

详细过程、源码与实测依据：[第 1 轮调研记录](round-1.md)。
