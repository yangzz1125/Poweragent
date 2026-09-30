# v3 Dev Pilot 预登记

> 编制：2026-09-30。本文在任何 v3 模型输出产生之前完成。自提交起作为“哈希固定”文档，其 SHA256 进入 structure-v3 运行的 `analysis_protocol_sha256`；之后如需修改，属于有意的协议变更，须开新运行目录并说明原因。
> 上位计划：[ROUTE_B_PLAN.md](ROUTE_B_PLAN.md) 第 10–12 节。执行计划：`plans/V3_PILOT_PREP_AND_SMOKE.md`。

## 1. 范围

- 数据：v3 Dev，32 个场景（S1–S4 各 8 个）× 8 个条件（I×V×R）× 1 次重复 = **256 局**。
- Smoke（第 9 节）是独立的 8 局连通性检查，不计入 Pilot 结论，也不用于推断 I/V/R 效果。
- Pilot 和 Smoke 都是**开发诊断**，不是论文 Test 结论。不读取、不运行 v2 sealed Test，不生成 v3 Test。
- 不修改 v3 语料、物理约束、成功判据、预算（12 turns / 4 previews / 3 submits）和 8 个条件的定义。

## 2. 模型与设置

- 模型：DeepSeek `deepseek-flash`，Responses 接口。
- `--max-output-tokens 16384`，`--reasoning-effort high`，temperature 取 runner 默认（0.0，按 runner 的 `temperature_policy` 记录）。
- 预算：最多 12 个 LLM turn、4 次 preview、3 次 submit。
- 旧 Dev Pilot（v2 语料，`max_output_tokens` 4096）与本 Pilot 的语料、输出上限和推理强度都不同，**不可混合比较**。

## 3. 主要对比

指标 `success`（最终成功），按结构类别 S1–S4 分层，外加 MACRO（四层等权平均）：

| 名称 | 定义 |
|---|---|
| `dV` | 对 I、R 等权平均的 SR(V1) − SR(V0) |
| `dR_V0` | 对 I 等权平均的 SR(V0,R1) − SR(V0,R0) |
| `VR` | 对 I 等权平均的 [SR(V1,R1) − SR(V1,R0)] − [SR(V0,R1) − SR(V0,R0)] |

重点看 **S3/S4 与 S1/S2 的差异**：RQ1（V/R 的效果是否随控制结构变化）、RQ2（V 与 R 是互补还是重叠，即 `VR` 的符号和大小）。

## 4. 次要对比

- `first_submit_success`、`first_proposal_success` 的同类对比（`dV`、`dR_V0`、`VR`）。
- 过度校正率（`first_proposal_overcorrection`、`any_overcorrection`）、`submitted_same_as_verified_candidate`、重复候选数、未改善转移数。
- 每局费用、实际潮流次数、token 数。
- `dI_exploratory`（对 V、R 等权平均的 SR(I1) − SR(I0)）：**只作探索，不是主要结论**。
- 同预算参照：v3 离线基线 `bounded_local` 在 Dev 上的分层成功数为 S1 8/8、S2 3/8、S3 3/8、S4 0/8。它是脚本基线，不是模型性能的上限或下限。

## 5. 指标定义（与 `scripts/analyze_voltage_mechanisms.py` 一致）

- **proposal**：一次 `preview_bess_dispatch` 或 `submit` 的 `tool_finished` 事件，按 turn 排序（同 turn 内保持事件原始顺序）。
- **首次候选 vs 首次提交**：`first_proposal_*` 取第一个 proposal；`first_submit_success` 取第一次 submit 的物理结果，没有 submit 记为 0（与 `first_pass_success` 口径一致）。`first_proposal_success` 在 `mechanism_episodes.csv` 中无 proposal 时为空，在对比中按 0 处理。
- **过度校正**：初始纯欠压、动作后 `remaining_overvoltage_buses` 非空；或初始纯过压、动作后 `remaining_undervoltage_buses` 非空。它与“原侧仍越限”“不收敛”“非法动作”分开统计。
- **`submitted_same_as_verified_candidate`**：第一次 submit 的调度是否等于此前某次成功 preview 的调度（`dispatch_key`：忽略 0 功率项，排序后比较）。此前没有成功 preview 时为空值，不记 0。
- **`nonimproving_candidate_transitions`**：相邻两次 proposal 中，前一次未成功且越限幅度没有下降（后 ≥ 前）的次数。
- **`repeated_candidate_count`**：与本局此前某次 proposal 调度完全相同的 proposal 个数。
- 结构类别（`structure_class`）、witness 和模板计数只出现在分析端 manifest，不进入 prompt 或工具输出。运行时 `difficulty` 一律为 `unstratified`。

## 6. 推断单位与不确定性

- 推断单位是**场景**。先把每个场景内同一条件的重复取平均，再按场景配对计算对比。
- 层内按场景做 bootstrap（1000 次，seed 2026）；MACRO 用分层 bootstrap（各层内分别重采样后等权平均）。
- 只报告绝对百分点差和区间，**不报 p 值**。
- 所有配对差值相同时标记 `no_variation`，此时区间退化，须如实注明。
- logistic 回归出现分离时，写“不可估计”，不做修正。
- 报告 `n_paired_scenarios` 和 `excluded_unpaired_scenarios`；缺失局不被填补。

## 7. 天花板的判定与处理（预先固定）

- **判定**：Pilot 完成后，将 S3 与 S4 合并，若满足以下任一条，则判定出现天花板：
  1. 在全部 V1 条件**以及** I0-V0-R1、I1-V0-R1 上，成功率都 ≥ 95%；
  2. S3∪S4 的 `VR` 和 `dV` 的区间都包含 0，且两者点估计的绝对值均 < 0.05。
- **处理**：按 2026-09-30 用户决定，启用第 10 节的**小预算实验**，作为独立实验版本。**不修改语料，不换题。**
- 全部成功也照实报告，不因结果“太好”而删除场景。

## 8. 协议阻断与保留原则

- 由输出截断、解析失败或传输错误造成的无效局超过 5% 时，先处理协议问题，暂不解释控制性能。这是工程警戒线，不是统计标准。
- **不因结果不好看而删除场景或局**。缺失、暂停和重试全部保留，并在报告中列出。
- 高峰时段由 runner 自动暂停，用同一输出目录续跑；只有运行身份一致才能续跑。

## 9. Smoke 场景选择（选完即固定）

- **规则**：在每个结构类别内，选 `sha256("v3-smoke-2026:" + scenario_id)` 十六进制值最小的场景。
- **条件**：`I0-V0-R0` 与 `I1-V1-R1`，共 4 个场景 × 2 个条件 = 8 局。
- **选择时只读了 v3 Dev manifest，没有看任何模型结果。**

各类别中哈希最小的前两个候选（便于复核）：

| 类别 | 选中 | 哈希（前 16 位） | 电压条件 | 次小 |
|---|---|---|---|---|
| S1 | **D0014** | `408aa64a67d6909a` | UNDERVOLTAGE | D0003 |
| S2 | **D0020** | `1155b2c994fc4f54` | OVERVOLTAGE | D0011 |
| S3 | **D0026** | `0000a24715485f9f` | UNDERVOLTAGE | D0028 |
| S4 | **D0024** | `59e4136438cae1eb` | OVERVOLTAGE | D0027 |

选中的 4 个场景：`D0014`（S1）、`D0020`（S2）、`D0026`（S3）、`D0024`（S4）。

## 10. 后备：小预算实验（仅设计，本文不启用）

只有第 7 节的天花板判定成立后才会启用。

- **独立实验版本**：preview 预算 b ∈ {1, 2}，其他预算（12 turns、3 submits）不变。**不通过截断已有轨迹来模拟**，必须用新的真实运行（ROUTE_B_PLAN 11.5）。
- **条件**：4 个 V1 条件（I × R），这些条件都依赖 preview 预算。32 个 Dev 场景各跑 1 次：每个 b 值 128 局，两个 b 值共 256 局。
- **同预算基线**：用相同的 b 重新运行 `bounded_local` 和 `uniform_bisection`，离线执行，不花钱。
- **实现可行性核对（只读，未改代码）**：
  - `VoltageToolServer` 的构造函数已有 `max_previews` 参数（`poweragentbench/voltage_tools.py`），默认回退到 `config["agent"]["max_preview_calls"]`；但 `LLMVoltageAgent.run` 和矩阵 runner 目前不传它，所以需要新增一个显式的运行参数，并一路传到 `VoltageToolServer`。
  - **不能**靠另写一份配置文件覆盖 `max_preview_calls`：评估器会校验场景 manifest 中的 `benchmark_config_sha256` 与所用配置文件哈希一致（`voltage_evaluator.py`），不一致会拒绝评估。因此要用显式参数，而不是修改或复制默认 benchmark config。
  - 运行身份里 `max_preview_calls` 目前读自默认配置，需要改为记录实际生效的预算，使不同 b 值形成不同的运行身份；`max_preview_calls` 已在冻结字段里（`voltage_freeze.py`）。
  - 工具输出里会向模型显示 `max_preview_calls` 和 `preview_calls_remaining`，小预算下模型看到的是新预算，无需改 prompt。
  - `max_previews or default` 会把 0 当作默认值，所以 b=0 不能用这种方式表示；本实验只用 b=1、2，不受影响。
