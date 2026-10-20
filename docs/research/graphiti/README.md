# Graphiti 调研

| 元信息 | 地址或范围 |
| --- | --- |
| 本地仓库 | `E:\JourneyIntoAI\DL_and_LLM\projects\graphiti` |
| GitHub | [getzep/graphiti](https://github.com/getzep/graphiti) |
| 首轮核对范围 | Graphiti 开源仓库；Zep 服务仅作概览，不将两者能力混用 |
| 首轮主要核对时间 | 2026-09-30 |

## 各轮调研简短结论

### 第 1 轮 · 已完成

- 以 episode 保存输入及来源，再由 LLM 提取实体与时序关系；事件时间不能当作用户理解已获验证的时间。
- 写入、检索及回注由接入应用安排；注册 SDK 或 MCP 接口不会自动采集每轮会话。
- 可借鉴原始证据与派生关系分存、时间变化和来源关联；用户理解假设的验证仍需另行设计。

详细过程、源码与实测依据：[第 1 轮调研记录](round-1.md)。
