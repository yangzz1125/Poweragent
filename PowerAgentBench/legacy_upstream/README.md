# legacy_upstream：上游旧内容归档

这里集中存放来自上游 PowerAgentBench、但 Poweragent 电压控制研究**不使用**的内容。2026-09-30 整理时用 `git mv` 移入，保留历史；不再维护，也不保证还能运行。

| 路径 | 内容 |
|---|---|
| `benchmarks/steady/level_1/` | N-1 稳态审计与缓解 |
| `benchmarks/steady/level_2/` | N-2 Agent 搜索与缓解 |
| `benchmarks/steady/level_3/` | RestoreBench：AC 潮流收敛恢复（自带 `pyproject.toml` 与 uv 锁） |
| `benchmarks/dynamic/` | 动态模型质量评审（需 PSS/E 与 DMView 商业工具） |
| `cases/` | IEEE 39 与 WECC solar 案例数据 |

## 已不可用的部分

支撑 Level 1/2 的 Python 脚本和模块（`build_case.py`、`convert_case.py`、`evaluate_solution.py`、`run_steady_n2_*.py`、`steady_state_agentic.py`、`benchmark_utils.py`）已在 2026-09-30 的清理中从主目录删除，因此 Level 1/2 的 README 里的运行命令**不能直接使用**。需要时可从 Git 历史恢复：

```powershell
git log --diff-filter=D --name-only -- PowerAgentBench/scripts PowerAgentBench/poweragentbench
git checkout <删除前的提交> -- <路径>
```

Level 3 自成一体，可在其目录内独立使用（`uv sync` 等）。

## 使用约定

- 不要从主实验代码导入这里的内容，也不要让主实验依赖这里的文件。
- 已移出 `benchmarks/` 与 `cases/` 的原路径；若需要恢复原位置，用 `git mv` 移回。
- 若确定不再需要，整个目录可以直接删除，主实验不受影响（测试可验证）。
