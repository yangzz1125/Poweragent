# Poweragent 项目交接文档

最后更新：2026-09-21

## 1. 项目目标

本工作区基于现有 Power-Agent 开源项目进行最小侵入式扩展，研究：

> 面向配电网电压越限校正的 LLM Agent Benchmark，以及 domain-specific interface、verification 和 recovery 对 Agent performance 的影响。

当前第一阶段范围：

- IEEE 33-bus 配电网；
- 构造低电压和高电压越限快照；
- 使用若干 BESS 的有功功率进行校正；
- 使用 pandapower 重新执行独立潮流验证；
- 支持可控的 verification preview 和失败后 recovery/re-planning；
- 不考虑时序、SOC、充放电效率、无功控制和电力电子暂态。

## 2. 工作区结构

```text
power_agent/
├── PowerAgentBench/   主 benchmark、场景、Agent、evaluator 和实验脚本
├── PowerMCP/          电力软件与 MCP 工具实现参考
├── PowerSkills/       领域 workflow 与 Agent interface 设计参考
├── README.md          工作区简介
└── agent.md           本交接文档
```

职责边界：

- PowerAgentBench 是唯一的主实验框架。
- pandapower 是当前电力计算后端。
- PowerMCP 的 pandapower server 用于工具语义参考，当前 benchmark 不依赖其进程内全局状态。
- PowerSkills 仅用于工作流和接口设计参考，没有被运行时导入。
- 原有 N-1、N-2 和 RestoreBench 代码未被改写。

## 3. 当前实现状态

已完成一个可运行的 IEEE 33-bus BESS 电压校正 benchmark 最小版本。

### 3.1 新增核心模块

位于 `PowerAgentBench/poweragentbench/`：

- `voltage_case.py`
  - 构建和加载 IEEE 33-bus 场景；
  - 校验 manifest 与 scenario artifact SHA-256；
  - 生成 generic/domain-specific 两种 public interface；
  - 写入 pandapower 原生 JSON。
- `voltage_evaluator.py`
  - 规范化并验证 BESS dispatch；
  - 统一 benchmark 与 pandapower 的功率符号；
  - 从冻结 JSON 独立重放动作；
  - 使用锁定的 pandapower 参数重跑潮流；
  - 判定是否真正消除全部电压越限。
- `voltage_tools.py`
  - 提供 Agent-facing tool server；
  - 控制 verification 和 recovery 实验开关；
  - 保存 preview、submit 和失败反馈状态。
- `voltage_agentic.py`
  - 提供 LLM Agent loop；
  - 复用已有 JSON command parser 和 provider client；
  - 实现 No-action、Nearest-BESS 和 Voltage-sensitivity scripted baselines；
  - 计算 per-case 和 aggregate metrics。

### 3.2 新增入口脚本

位于 `PowerAgentBench/scripts/`：

- `build_voltage_cases.py`
  - 构建冻结场景；
  - 生成 manifest；
  - 搜索 private witness；
  - 独立重放并拒绝不可解场景。
- `run_voltage_baselines.py`
  - 运行三个 scripted baselines；
  - 输出 per-case CSV、summary CSV 和 attempt JSONL。
- `run_voltage_agent_eval.py`
  - 支持 OpenAI Responses API 和 Ollama；
  - 支持 interface、verification、recovery 开关；
  - 支持 repetitions；
  - 输出 CSV、tool logs、attempt logs、sanitized API debug 和 error JSONL。

### 3.3 配置与数据

位于 `PowerAgentBench/benchmarks/steady/voltage_control/`：

```text
config/benchmark.json       物理约束、BESS、solver 和 Agent budget
config/experiments.json     I/V/R 三因素 2×2×2 全因子设计
prompts/                    LLM system prompt
scenarios/ieee33/full/      evaluator 使用的冻结 pandapower JSON
scenarios/ieee33/public/    Agent 可见场景数据
scenarios/ieee33/private/   witness dispatch，正式 sealed eval 不可暴露
scenarios/ieee33/manifest.json
```

当前 corpus 共 8 个场景：

- V0001–V0004：欠电压；
- V0005–V0008：过电压；
- BESS 位于 bus 8、17、24、32；
- 每台 BESS 范围为 `[-1.5, 1.5] MW`，步长 `0.25 MW`。

## 4. 关键物理与接口约定

### 4.1 BESS 符号

Benchmark 对 Agent 暴露的统一约定：

- `p_mw > 0`：BESS 放电，向电网注入有功；
- `p_mw < 0`：BESS 充电，从电网吸收有功。

pandapower `storage.p_mw` 的符号与此相反。反号只能在 `apply_bess_dispatch()` 中处理，prompt、日志、CSV 和 Agent 输出不得使用 pandapower 原始符号。

### 4.2 电压与 solver

- 合格电压范围：`0.95–1.05 pu`；
- solver：backward/forward sweep (`bfsw`)；
- initialization：`flat`；
- `max_iteration=100`；
- `tolerance_mva=1e-8`。

成功条件：

1. 独立重放后的潮流收敛；
2. 所有 bus 电压均落入 `[0.95, 1.05] pu`。

线路 loading 会记录为诊断指标，但不进入成功判定，因为标准 `case33bw()` 没有 study-grade thermal ratings。

### 4.3 独立验证边界

最终 evaluator 不信任以下内容：

- Agent 自报的 `success`；
- preview tool 的回执；
- Agent 或 tool server 中已修改的内存网络；
- scripted baseline 自己计算的终态。

每次正式评分都会：

```text
scenario_id + submitted dispatch
    → 校验 manifest/config hash
    → 从 full/Vxxxx.json 重新加载网络
    → 校验 BESS id、上下限、步长和有限数值
    → 应用符号转换
    → 重新运行锁定参数的 pandapower 潮流
    → 从 res_bus 独立计算最终 verdict
```

## 5. Agent 工具协议

LLM 继续复用 PowerAgentBench Level 2 的文本 JSON command 协议：

```json
{"tool": "<tool_name>", "args": {}}
```

当前工具：

- `case_summary`
- `inspect_voltage_state`
- `get_bess_capabilities`
- `preview_bess_dispatch`，仅 verification condition 开启
- `submit`

提交格式：

```json
{
  "tool": "submit",
  "args": {
    "dispatch": [
      {"bess_id": "BESS_1", "p_mw": 0.25},
      {"bess_id": "BESS_2", "p_mw": -0.50}
    ]
  }
}
```

Recovery 开启时，失败的 submit 会返回：

- 是否收敛；
- 最小/最大电压；
- 剩余欠电压/过电压 bus；
- violation magnitude 和 improvement；
- 动作是否合法；
- 剩余提交次数。

默认最多 3 次提交、4 次 preview、12 个 LLM turns。

## 6. 实验设计

`config/experiments.json` 定义三因素 2×2×2 全因子实验：

| 因素 | 关闭 | 开启 |
|---|---|---|
| Interface | 原始 bus voltage 表 | 越限分类、极值和领域符号提示 |
| Verification | 不提供 preview | 可在提交前独立预演候选 dispatch |
| Recovery | 首次 submit 后终止 | 失败反馈后允许 bounded replanning |

condition id 使用：

```text
I0-V0-R0 ... I1-V1-R1
```

无论 verification 因素是否开启，最终 independent evaluator 始终开启。

## 7. 环境与运行

从工作区根目录进入主项目：

```powershell
cd E:\work\power_agent\PowerAgentBench
```

建议 Python 3.11。安装：

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -e . pytest
```

注意：`pyproject.toml` 已限制 `pandas>=2,<3`。pandapower 3.1.x 与 pandas 3 的结果表写回存在兼容问题，不要移除此限制，除非已在更新版 pandapower 上完成回归测试。

### 7.1 重建并验证场景

```powershell
.venv\Scripts\python.exe scripts\build_voltage_cases.py
```

构建器会验证每个场景确实存在初始越限，并确保 private witness 可以独立重放成功。重复构建已验证会产生相同的 full scenario hashes。

### 7.2 运行 scripted baselines

```powershell
.venv\Scripts\python.exe scripts\run_voltage_baselines.py
```

输出目录：

```text
PowerAgentBench/results/voltage_control/
```

`results/` 已被 Git 忽略。

### 7.3 运行 OpenAI Agent

密钥放入环境变量或本地 `.env`，不得提交：

```powershell
$env:POWERAGENTBENCH_OPENAI_API_KEY="..."

.venv\Scripts\python.exe scripts\run_voltage_agent_eval.py `
  --provider openai `
  --model <model-id> `
  --domain-interface `
  --verification `
  --recovery `
  --repeats 3
```

关闭因素时使用：

```text
--no-domain-interface
--no-verification
--no-recovery
```

### 7.4 运行 Ollama Agent

```powershell
$env:POWERAGENTBENCH_OLLAMA_URL="http://localhost:11434/api/generate"

.venv\Scripts\python.exe scripts\run_voltage_agent_eval.py `
  --provider ollama `
  --model <local-model> `
  --domain-interface `
  --verification `
  --recovery
```

## 8. 输出与可重复性

LLM runner 按 model/provider/condition 生成：

```text
<prefix>_per_case.csv
<prefix>_summary.csv
<prefix>_tool_logs.jsonl
<prefix>_attempts.jsonl
<prefix>_api_debug.jsonl
<prefix>_errors.jsonl
```

结果携带：

- scenario artifact hash；
- dataset version；
- benchmark config hash；
- prompt hash；
- pandapower version；
- solver 参数；
- model/provider；
- I/V/R condition；
- repetition index。

OpenAI debug 使用已有 `sanitized_debug()`；Ollama 仅记录是否收到响应，不落盘原始 model output，避免泄露 reasoning 或部署信息。

主要指标：

- `success`
- `initial/final_violation_count`
- `initial/final_min_vm_pu`
- `initial/final_max_vm_pu`
- `initial/final_violation_magnitude`
- `voltage_improvement`
- `action_l1_mw`
- `action_cost`
- `n_attempts`
- `n_recovery_steps`
- `preview_calls`
- `n_power_flows`
- `invalid_tool_calls`
- `submitted_explicitly`
- `auto_finalized`

## 9. 当前验证结果

离线测试：

```text
11 passed
ruff: All checks passed
git diff --check: passed
```

测试覆盖：

- frozen artifact 加载；
- 欠压/过压场景同时存在；
- no-action 必须失败；
- 8 个 private witness 全部独立重放成功；
- BESS 越界动作拒绝；
- 正负功率符号；
- verification 条件开关；
- recovery feedback 和二次提交；
- malformed LLM output reprompt；
- 最后一次非法提交不会被先前动作替代。

Scripted baseline 首轮结果：

| Agent | Success rate | Mean action L1 |
|---|---:|---:|
| No-action | 0% | 0 MW |
| Nearest-BESS-greedy | 100% | 1.9375 MW |
| Voltage-sensitivity-greedy | 100% | 1.15625 MW |

旧 N-2 baseline 已执行 1-case smoke test，原执行链仍可正常运行。

## 10. 重要设计决策

1. 没有修改 `steady_state_agentic.py`，避免破坏原 N-2 benchmark。
2. 没有让 benchmark 直接调用 PowerMCP 的全局 `_current_net`。
   - 原因：并发 case 隔离不足；
   - 当前 pandapower MCP 也没有 BESS active-power setter。
3. 复用了 Level 2 的 provider clients、JSON command parser、runner 输出风格和 baseline contract。
4. 参考了 RestoreBench 的 frozen artifacts、hash manifest、独立重放和 recovery feedback，但没有把根项目强耦合到其独立 Python 3.11/uv 包。
5. private witness 与 public scenario 分目录保存。开放仓库可用于复现；正式 sealed evaluation 必须从 Agent 环境中移除 `private/`。

## 11. 已知限制

- corpus 仅 8 个确定性场景，规模不足以直接支持论文级统计结论；
- 目前没有提交真实 LLM 的完整 2×2×2 实验结果；
- `run_voltage_agent_eval.py` 每次运行一个 condition，尚无一键 campaign/sweep 调度器；
- 当前 tool protocol 是复用 Level 2 的文本 JSON command，不是实际 MCP transport；
- 未实现 SOC、时序耦合、效率、Q 控制或 inverter capability curve；
- 标准 `case33bw()` 缺少可信线路热限值，因此 thermal loading 只作诊断；
- Nearest-BESS baseline 当前用 bus 编号距离作轻量排序，不是严格 electrical distance；
- 根项目尚无 lockfile；实验发布前应冻结 Python、pandapower、NumPy 和 pandas 版本；
- OpenAI/Ollama live runner 尚未在本次交付中使用真实凭据做端到端测试。

## 12. 建议的下一步

按优先级排序：

1. 增加 campaign runner，一键运行 8 个 I/V/R conditions、多个模型和多个 repetitions。
2. 扩充 scenario corpus，并按生成 recipe 分组，避免 train/eval leakage。
3. 建立 sealed evaluation 打包流程，将 `private/witnesses.json` 与 Agent 环境隔离。
4. 用真实模型执行 pilot，检查 tool schema、turn budget、timeout 和日志完整性。
5. 增加 factorial effect、interaction effect、bootstrap CI 和 paired-case 统计分析。
6. 将 Nearest-BESS 改为基于 feeder graph/electrical sensitivity 的 baseline。
7. benchmark 稳定后，再考虑为 PowerMCP 上游增加 BESS 查询与有功设定工具。
8. 第二阶段再加入 SOC、效率和多时段任务，不要提前污染第一阶段结论。

## 13. Git 与发布说明

GitHub：<https://github.com/yangzz1125/Poweragent>

工作区根目录是聚合仓库，同时三个子目录保留各自原有 `.git` 元数据：

- 根仓库用于发布整个 workspace；
- `PowerAgentBench` 子仓库保留 benchmark 开发历史；
- `PowerMCP`、`PowerSkills` 子仓库保留各自上游历史。

在子目录中修改文件后，若需要同步整个 workspace，除了子项目自身的 commit，还要在工作区根目录执行一次 commit/push。不要删除嵌套 `.git`，也不要把 `.venv`、`.env` 或 `results/` 提交到仓库。

