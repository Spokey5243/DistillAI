# Python 与采集规则

修改 `plugins/` 下 Python、`scripts/` 或 Python 测试时生效。

- 当前运行时为 Windows + Python 3，采集脚本依赖标准库 `msvcrt`；不要把 Linux 测试通过等同于 Windows 集成通过。
- 当前没有 pyproject、uv 环境或第三方生产依赖；不照搬其他项目的 backend 目录、pytest / Ruff 或 uv 命令。
- 后续明确引入依赖时，按批准的技术方案建立 pyproject 和锁文件，并同步本规则、README 与 CI。
- Hook 快速保存原始 payload；不在采集写锁内调用模型或执行 GitHub 网络操作。
- 采集失败继续正常对话，保留无正文的错误诊断；权限 / Push 检查在可判定错误时返回明确 deny，不混用两种失败策略。
- 个人原始记录留在用户目录；测试使用临时目录和合成事件。
- Bug 先用已有测试或最小回归用例复现，再修复；测试取舍读取 `test-necessity-review`。

相关验证在仓库根目录执行：

```powershell
python tests/test_capture.py
python .codex/hooks/test_pre_push_guard.py
```

按变化运行相关组；同时影响采集和开发 Hook 时两组都运行。实际 Desktop 触发必须单独验证。
