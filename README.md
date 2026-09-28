# Poweragent

研究 Agent Harness 如何影响电力系统控制任务中 LLM 的可靠性，以及提升可靠性需要多少工具、潮流计算和 token 成本。

主任务：IEEE 33-bus 配电网中，Agent 仅调节 4 台 BESS 有功功率，让所有节点电压回到 0.95–1.05 pu。使用完整 **2×2×2** 设计比较领域接口（I）、真实潮流预验证（V）、失败恢复（R），不以“LLM 打败传统控制器”为目标。

## 当前状态：开发中，尚未冻结

| 项目 | 已验证范围 |
|---|---|
| 回归场景 | 仓库内 V0001–V0008，供 sanity/regression 使用 |
| 候选 corpus | 本地 24 Dev + 96 Test，Test 每个欠压/过压×severity 三档格子 16 个；不是已冻结论文数据 |
| 基线 | 24 Dev：No-action 0/24，nearest 和 sensitivity greedy 各 24/24 |
| 模型 | DeepSeek 官方 `deepseek-flash`，Responses；只跑过 1 个真实 Dev 冒烟 episode |
| 工程 | 8 组矩阵、断点续跑、CSV/JSONL、逐回合 token、实际 PF 计数已有实现及离线测试 |
| 分析 | 聚类 bootstrap、factorial 和图表脚本只通过合成数据检查，不代表已获得科研结果 |
| 尚未完成 | 完整 Pilot、难度有效性审查、freeze/tag、2304 次主实验、跨模型验证、正式分析 |

**冻结阻塞：** generator 当前只接受能被等功率同向 BESS 调节解决的候选，存在筛选偏差；severity 大不等于控制困难。不要为压低基线成功率删除 case。先在 Dev 比较简单策略、控制余量与搜索成本，再设计新候选生成/可行性验证协议；现有 corpus 保留作开发参考，不覆盖其哈希。详见 [研究规范](PowerAgentBench/docs/BENCHMARK_SPEC.md)。

## 目录用途

```text
PowerAgentBench/                  主实验代码和本地 .venv
  poweragentbench/                Agent loop、工具、独立 evaluator、模型客户端
  benchmarks/steady/voltage_control/
    config/                      物理约束、solver、预算、8 条件
    prompts/                     系统提示
    scenarios/ieee33/            8 个回归场景（不是主实验 Test）
  scripts/                       生成、运行、分析入口
  tests/                         离线回归与 mock 测试
  results/                       本地日志/结果，git-ignored
  docs/                          研究规范与验收记录
PowerMCP/                        电力软件 MCP 连接器；当前主实验不依赖
PowerSkills/                     领域技能/工作流参考；当前主实验不导入
plans/                           项目执行计划（历史步骤不替代最新验收状态）
agent.md                         开发交接与操作注意事项
```

候选 corpus 当前位于 `E:/work/voltage_corpus_v1`，不随 GitHub 上传。仓库之外的目录**不是**操作系统隔离：当前只测无 shell/文件权限的托管 LLM，Coding Agent 评测尚未获隔离验收。

## 本机运行

已有 `PowerAgentBench/.venv` 时直接使用，不必重建或开启 Docker。新机器安装：

```powershell
cd PowerAgentBench
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -e . pytest
uv pip check --python .venv\Scripts\python.exe
.venv\Scripts\python.exe -m pytest -q tests
```

配置约束：Python >=3.11，PyPSA >=1.0,<1.3，pandas >=2,<3。当前本机验证过 Python 3.13.14、PyPSA 1.2.4、pandas 2.3.3；尚无正式实验锁定环境。

### API 配置

不存在 `.env` 时才复制，避免覆盖已有密钥：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

编辑 `.env`（不要提交或回显密钥）：

```dotenv
POWERAGENTBENCH_OPENAI_URL=https://api.deepseek.com
POWERAGENTBENCH_OPENAI_API_KEY=YOUR_DEEPSEEK_API_KEY
POWERAGENTBENCH_OPENAI_MODEL=deepseek-flash
POWERAGENTBENCH_OPENAI_API_MODE=responses
```

runner 自动补 `/responses`，也兼容完整端点 URL。Responses 目前承载文本 JSON 命令，不是原生 function-call 循环；DeepSeek Responses 无状态，每回合需传历史。

### 无 API 成本检查

以下命令从 `PowerAgentBench/` 执行：

```powershell
.venv\Scripts\python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root E:/work/voltage_corpus_v1/dev --dry-run
.venv\Scripts\python.exe scripts/run_voltage_baselines.py --scenario-root E:/work/voltage_corpus_v1/dev --output-dir results/voltage_control/dev_baselines
```

Dev dry-run 应列出 192 个任务；`--split test --repeats 3` 对应 2304 个任务，但不要因此运行正式 Test。

明确调用预算后才能运行付费 Dev 检查；新接口应使用新输出目录，不续写旧 smoke 数据：

```powershell
.venv\Scripts\python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root E:/work/voltage_corpus_v1/dev --output-dir results/voltage_control/dev_compact_smoke --max-episodes 8 --max-total-tokens 100000
```

这里 100000 是示例软上限，不是用户已授权额度；检查发生在 episode 边界，可能超出一局。继续相同输出目录会跳过完成项，错误需显式 `--retry-errors`。缺失 usage 无法可靠预算；日志/断点等边界还需完整 Pilot 验收。

## 工具与物理约定

- `case_summary`：网络静态信息（含 topology/load）、工具列表和预算。
- `inspect_voltage_state`：仅电压观察与约束，不重复发送 network/BESS 表；I0 提供原始电压，I1 提供任务语义预处理，不声称信息等价。
- `get_bess_capabilities`：BESS 边界、步长和符号。
- `preview_bess_dispatch`：仅 V1 可用；运行真实潮流。
- `submit`：正式提交；R1 失败后在预算内重规划。

BESS bus：8/17/24/32；每台 ±1.5 MW、0.25 MW 步长。正功率放电注入，负功率充电吸收；evaluator 内转换 pandapower storage 符号。默认预算 12 turns、4 previews、3 submits。

独立 evaluator 每次重载冻结 JSON，检查 ID/有限值/边界/步长，再跑锁定 bfsw 潮流。成功仅要求收敛且全部电压合格；线路热负载只记录诊断。非法动作不计实际 PF。最后一次失败提交不能用此前成功动作替代。

删除重复字段减少了 observation 大小，但完整历史仍会重传，不能把字节减少比例等同真实 token 降幅；真实成本需新 Dev pilot 测量。

## 结果与分析

矩阵 runner：`run.json`、`episodes.jsonl`、`episodes.csv`、`traces.jsonl`；出现错误/重试时另有 `errors.jsonl`/`retries.jsonl`。旧单条件脚本 `run_voltage_agent_eval.py` 仍使用 prefix 命名，不要混用两套结果。

```powershell
.venv\Scripts\python.exe -m scripts.analyze_voltage_experiments --episodes results/voltage_control/dev_compact_smoke/episodes.csv --output-dir results/voltage_control/dev_analysis --allow-incomplete
```

`--allow-incomplete` 只用于开发诊断。统计脚本已有 CI、factorial 分离检测和图表输出，但正式分析仍需验证完整任务集合、错误分母、依赖版本与 freeze 清单。当前没有论文级统计结论。

## 研究记录与图片

AI 在本项目中使用 Markdown（`.md`）记录研究问题、方法、实验配置、结果和结论，供后续人工编写 LaTeX 论文和 PPT 时参考；有用的配图可按需另行保存，不保留无用的旧图片，也不以生成 PPT 文件作为交付要求。

## 文档与来源

- [开发交接](agent.md) / [研究规范与验收](PowerAgentBench/docs/BENCHMARK_SPEC.md)
- [执行计划](plans/voltage-benchmark-completion.md)
- 上游：[PowerAgentBench](https://github.com/Power-Agent/PowerAgentBench)、[PowerMCP](https://github.com/Power-Agent/PowerMCP)、[PowerSkills](https://github.com/Power-Agent/PowerSkills)
- 仓库：<https://github.com/yangzz1125/Poweragent>

各子项目和数据适用各自许可证；发表和再分发时核查 LICENSE/NOTICE 与案例引用要求，保留 attribution。
