# Letta 调研

| 元信息 | 地址或范围 |
| --- | --- |
| 本地仓库 | `E:\JourneyIntoAI\DL_and_LLM\projects\letta`；`E:\JourneyIntoAI\DL_and_LLM\projects\letta-code` |
| GitHub | [letta-ai/letta](https://github.com/letta-ai/letta)；[letta-ai/letta-code](https://github.com/letta-ai/letta-code) |
| 首轮核对范围 | 文档、Letta Code 源码及 v0.33.6 本地生命周期实测；不等同于 Letta 服务端全量能力 |
| 首轮主要核对时间 | 2026-09-30 |

## 各轮调研简短结论

### 第 1 轮 · 已完成

- 原始交互、供整理的一轮材料、MemFS 中的 Markdown 记忆和下一次请求的编译上下文分别保存，后台 reflection 对照旧记忆做修订。
- Letta Code v0.33.6 实测跑通“前台写入偏好 → 普通对话触发后台最小修订 → 新会话使用更新后的常驻记忆”。
- 可借鉴事件调度、独立模型整理、少量常驻内容与按需读取；通用记忆更新规则仍不足以验证用户的竞争理解假设。

详细过程、源码与实测依据：[第 1 轮调研记录](round-1.md)。
