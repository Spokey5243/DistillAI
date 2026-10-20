# Python 与采集规则

修改 `src/`、`plugins/` 下 Python、`scripts/` 或 Python 测试时生效。

- 当前运行时为 Windows + Python 3，采集脚本依赖标准库 `msvcrt`；不要把 Linux 测试通过等同于 Windows 集成通过。
- 产品代码位于 `src/distillai/`，继续使用 unittest；控制 / Web / MCP 用项目 uv 环境，依赖和开发组由 `pyproject.toml` / `uv.lock` 锁定。Hermes 任务解释器由上游 PM 准备，不用 pip / uv 修改 PM 环境，不要求其匹配全部产品依赖。
- 按已批准修订 3 复用 FastAPI / Uvicorn、HTTPX、FastMCP、Pydantic、Loguru 等成熟能力；Ruff 仅启用 pyproject 明确的错误规则，Playwright 浏览器组单独运行。不迁移 pytest，不引入覆盖率门槛。
- 后续明确引入依赖时，按批准的技术方案建立 pyproject 和锁文件，并同步本规则、README 与 CI。
- Hook 快速保存原始 payload；不在采集写锁内调用模型或执行 GitHub 网络操作。
- 采集失败继续正常对话，保留无正文的错误诊断；权限 / Push 检查在可判定错误时返回明确 deny，不混用两种失败策略。
- 个人原始记录留在用户目录；测试使用临时目录和合成事件。
- Bug 先用已有测试或最小回归用例复现，再修复；测试取舍读取 `test-necessity-review`。

相关验证在仓库根目录执行：

```powershell
uv sync --locked --group dev --group browser
python tests/test_capture.py
python .codex/hooks/test_pre_push_guard.py
$env:PYTHONPATH = 'src'
uv run --locked python -m unittest discover -s tests -p 'test_product_*.py' -v
uv lock --check --offline
```

按变化运行相关组；同时影响采集和开发 Hook 时两组都运行。实际 Desktop 触发必须单独验证。
