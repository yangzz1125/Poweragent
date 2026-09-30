# PowerAgentBench

本目录是 Poweragent 研究项目的主实验代码：**IEEE 33-bus 配电网 BESS 电压控制**，比较 Agent Harness 的三个因素（领域接口 I、真实潮流预验证 V、失败恢复 R，完整 2×2×2 设计）对 LLM 可靠性和成本的影响。

项目目标、当前进度、运行命令和 API 配置见仓库根目录 [README](../README.md)；文档索引（现行与归档）见 [docs/README.md](docs/README.md)。本文件只说明本目录的结构。

> 本目录源自上游 [PowerAgentBench](https://github.com/Power-Agent/PowerAgentBench)。上游的 N-1/N-2/RestoreBench/动态研究等部分已集中移入 [`legacy_upstream/`](legacy_upstream/README.md)，当前实验不使用，也不再维护。

## 目录结构

```text
PowerAgentBench/
├── poweragentbench/                 共享库
│   ├── voltage_case.py              场景构建/加载、哈希、观察卡
│   ├── voltage_structure.py         v3 控制结构分层（S1–S4）
│   ├── voltage_storage.py           本地数据路径与存储
│   ├── voltage_evaluator.py         独立重载的潮流评估器
│   ├── voltage_tools.py             Agent 工具：preview / submit、预算与账本
│   ├── voltage_agentic.py           Agent loop、脚本化基线、评分
│   ├── voltage_costs.py             人民币计费与门控
│   ├── voltage_freeze.py            冻结身份校验
│   ├── openai_client.py             Responses API 客户端
│   ├── openai_chat_client.py        Chat 兼容备用客户端
│   ├── ollama_client.py             Ollama 客户端
│   └── llm_agent_adapter.py         JSON 命令解析与提示模板加载
├── benchmarks/steady/voltage_control/
│   ├── config/                      物理约束、solver、预算、8 个实验条件
│   ├── prompts/                     系统提示
│   └── scenarios/ieee33/            8 个回归场景（V0001–V0008，非主实验 Test）
├── scripts/                         生成、运行、分析入口（见下）
├── tests/                           离线回归与 mock 测试
├── docs/                            研究规范与验收记录
├── legacy_upstream/                 上游旧内容归档，不再使用
└── results/                         本地日志与结果（Git 忽略）
```

## 脚本

| 类别 | 脚本 |
|---|---|
| 场景/语料生成 | `build_voltage_cases.py`（8 个回归场景）、`generate_voltage_corpus.py`（v2）、`generate_voltage_structural_corpus.py`（v3） |
| 校验与基线 | `validate_voltage_structural_corpus.py`、`run_voltage_baselines.py`、`run_voltage_structural_baselines.py` |
| 运行实验 | `run_voltage_agent_eval.py`（单条件）、`run_voltage_experiment_matrix.py`（8 条件矩阵，支持断点续跑）、`run_voltage_route_b.py`（路线 B） |
| 分析与研究 | `analyze_voltage_experiments.py`、`analyze_voltage_trajectories.py`、`audit_voltage_difficulty.py`、`study_voltage_landscape.py`、`study_voltage_shortcuts.py`、`export_voltage_run.py` |

## 安装与测试

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -e . pytest
.venv\Scripts\python.exe -m pytest -q tests
```

依赖：Python ≥ 3.11，PyPSA ≥ 1.0,<1.3，pandapower，pandas ≥ 2,<3。测试全程离线，不调用模型 API。完整套件耗时约 6 分钟。

## 注意

- 物理合同与研究边界：[docs/BENCHMARK_SPEC.md](docs/BENCHMARK_SPEC.md)；场景合同：[benchmarks/steady/voltage_control/README.md](benchmarks/steady/voltage_control/README.md)。
- 实验只使用 BESS 有功功率；SOC、时间耦合、无功和变流器暂态不在范围内。
- `docs/` 中 5 个文件被运行身份哈希固定，不要移动或编辑，见 [docs/README.md](docs/README.md)。
- 不要提交 `.env`、密钥、隐藏 Test 集或 witness。
