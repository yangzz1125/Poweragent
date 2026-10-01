# v3 Pilot 前准备与 Smoke 执行计划

> 编制：2026-09-30（基线提交 `5371948`）。执行者：Claude Code（Sonnet 5.5）。
> 上位计划：[`PowerAgentBench/docs/ROUTE_B_PLAN.md`](../PowerAgentBench/docs/ROUTE_B_PLAN.md) 第 10–12 节。本文只覆盖“B4 之后、B5 Pilot 之前”的一段，不替代上位计划。
> **本计划中所有付费模型调用都必须在对应的 STOP 点得到用户明确同意后才能执行。**

---

## 0. 背景（执行前必读，不要重新推导）

- 研究问题：I（领域接口）、V（提交前潮流预验证）、R（失败后重规划）三个开关（8 组）对 LLM 电压控制可靠性和成本的影响。v3 按控制结构 S1–S4 分层，看 V/R 的效果是否随结构变化（RQ1）、V 与 R 是互补还是重叠（RQ2）。
- 已有真实数据：v2 Dev Pilot（DeepSeek `deepseek-flash`，192/192，170 成功）。V +22.9pp、R +20.8pp、I −2.1pp；6/8 组 100%，出现天花板，因此转向 v3。公开记录：`research_records/voltage_control/cny_pilot_192/`。
- v3 离线验收 B0–B4 已 PASS：32 Dev（S1–S4 各 8），同预算基线局部搜索 S1 8/8、S2 3/8、S3 3/8、S4 0/8。
- **用户 2026-09-30 的决定**：
  1. 按 v3 走，不换题。
  2. 若 v3 Pilot 出现天花板，后备方案是**小预算实验**（preview 预算 b=1/2，作为独立实验版本）。
  3. Main 预算上限为“几十元人民币”，具体数额届时再确认。
  4. 先做小规模测试和实验。
- 预算现状：共享 campaign `PowerAgentBench/results/voltage_control/cny_pilot_campaign`，授权总额 ¥10，已占用 ¥3.69531226（已知 ¥2.69531226 + 未知预留 ¥1），**剩余约 ¥6.30**。单局上限 ¥0.20。

## 1. 硬性约束（违反任何一条都要停下来报告）

1. **不改题**：不修改 v3 语料、物理约束、成功判据、预算（12 turns / 4 previews / 3 submits）、8 个条件的定义。
2. **不动 5 个哈希固定文档**：`PowerAgentBench/docs/` 下的 `BENCHMARK_SPEC.md`、`RMB_MEASUREMENT_SPEC.md`、`RMB_BEHAVIOR_ANALYSIS.md`、`STRUCTURAL_BENCHMARK_V3_SPEC.md`、`V3_GENERATION_PROTOCOL.md`，既不移动也不编辑。
3. **不泄漏结构标签**：`structure_class`、witness、模板计数只能出现在分析端，不能进入 prompt 或工具输出。
4. **没有用户在 STOP 点的明确同意，不发任何付费模型请求**。dry-run 可以跑。
5. 不创建新 campaign 来绕过额度；不删除或改写账本、事件、checkpoint；不续写旧 run 目录。
6. 不读取、不回显 `.env` 和密钥。
7. **git 只从仓库根目录 `E:\work\power_agent` 执行**。`PowerAgentBench/` 里有一个有意保留的嵌套 `.git`，在该目录里执行 git 会作用到错误的仓库。可以提交到本地；**push 前先问用户**。
8. 不对 v2 sealed Test 做任何读取或运行；不生成 v3 Test。

## 2. 已查明的事实（可以直接用）

**事件日志 `events.jsonl`**（每个 run 目录下都有），关键事件：
- `tool_finished`：字段 `tool`、`args`、`observation`、`outcome`、`turn`、`episode_key`（JSON 字符串 `["I1-V1-R0","D0005",0]`）、`episode_attempt`。
  - `tool == "preview_bess_dispatch"`：物理结果在 `observation.preview`。
  - `tool == "submit"`：物理结果在 `observation.verification`。**V0 条件下提交后的物理结果同样有完整记录**，无需再跑潮流。
  - 物理结果字段：`success`、`valid_action`、`converged`、`min_vm_pu`、`max_vm_pu`、`remaining_undervoltage_buses`、`remaining_overvoltage_buses`、`voltage_violation_magnitude`、`voltage_improvement`、`new_thermal_violation`。
  - `outcome` 取值：`ok` / `voltage_unresolved` / `pf_nonconverged` / `invalid_dispatch` / `unknown_tool` / `tool_error`。
- `parse_error`、`output_truncated`：解析失败和输出截断。
- 其他工具：`case_summary`、`get_bess_capabilities`、`inspect_voltage_state`。

**`episodes.csv`** 关键列：`condition`、`domain_interface`、`verification`、`recovery`、`scenario_id`、`repetition_index`、`episode_attempt`、`status`、`success`、`first_pass_success`、`first_submit_failed`、`recovered`、`voltage_condition`（`UNDERVOLTAGE`/`OVERVOLTAGE`）、`difficulty`、`termination_reason`、`n_actual_power_flows`、`total_tokens`、`accounted_cost_cny`。
- **v3 运行时 `difficulty` 一律是 `unstratified`**；结构类别要从评估端 manifest 关联。

**v3 manifest**：`.local-data/voltage_structure_v3/dev/manifest.json`，其中 `scenarios[]` 每项含 `scenario_id`、`structure_class`、`condition`、`all_full_feasible`、`severity`、`recipe_id`、`operating_family_id`。

**矩阵 runner** `PowerAgentBench/scripts/run_voltage_experiment_matrix.py`，用 `python -m scripts.run_voltage_experiment_matrix` 从 `PowerAgentBench/` 运行：
- 子集：`--scenario-id`（可重复）和 `--condition`（可重复），**仅限 Dev**，run_scope 会记为 `dev_diagnostic_subset`。
- 其他参数：`--max-output-tokens`（默认 16384）、`--reasoning-effort {none,low,high,max}`、`--campaign-dir`（默认就是共享 campaign）、`--campaign-stage {smoke,pilot}`、`--max-episode-cost-cny`（默认 0.20）、`--max-campaign-cost-cny`（默认 10）、`--dry-run`。
- 分析协议哈希：约第 163 行 `protocol_paths` 是 3 个文档；约第 183 行在 `corpus_version == "structure-v3"` 时追加 v3 的两个文档。它们的 SHA256 进入运行身份 `analysis_protocol_sha256`。
- 低谷时段由代码按价格配置自动判断，高峰会暂停退出。**不要在代码里手写时段。**

**现有分析脚本**：`scripts/analyze_voltage_experiments.py`（总体因子对比，按 `difficulty` 分组，不认识结构类别）和 `scripts/analyze_voltage_trajectories.py`（恢复、错误连续、preview 行为）。

**测试基线**：从 `PowerAgentBench/` 执行 `.venv\Scripts\python.exe -m pytest -q tests`，结果为 112 passed / 1 skipped，约 6 分钟。

## 3. 阶段 A：机制指标与分层分析（离线，不花钱）

### A1. 完成 `scripts/analyze_voltage_mechanisms.py`

仓库里已有一份**未经测试的草稿**（2026-09-30 编写，未运行过）。可以在它的基础上修改，也可以重写。草稿**已知问题**：
- `analyze()` 里生成 `summary` 的循环有一段无效的去重判断（`(stratum, condition) in summary`）。只有一个层级时，ALL 层会重复输出。要改成：先按 `(stratum, condition)` 汇总，只在层数 > 1 时再追加 ALL 层。
- 事件按 `turn` 排序时，同一 turn 内的顺序依赖原始顺序，要确认是稳定排序（Python 的 `sorted` 是稳定的，但要在测试里覆盖）。
- `episode.get("difficulty") or "ALL"` 遇到 NaN 时行为要确认。
- 从 `scripts.analyze_voltage_trajectories` 导入函数的做法，需确认在 pytest 下可行。现有测试已经这样导入，应该没问题。

**要求的输出**（写到 `--output-dir`）：
1. `mechanism_episodes.csv`：每局一行，至少包含：
   - 标识：`condition`、`scenario_id`、`repetition_index`、`stratum`（v3 为 S1–S4，否则取 `difficulty`）、`voltage_condition`
   - 结果：`success`、`termination_reason`、`n_actual_power_flows`、`total_tokens`、`accounted_cost_cny`
   - 计划第 11.2 节：`first_proposal_source`、`first_proposal_valid`、`first_proposal_success`、`no_proposal`、`first_submit_success`
   - 计划第 11.3 节：`first_candidate_violation_magnitude`、`best_preview_violation_magnitude`、`first_proposal_overcorrection`、`any_overcorrection`、`submitted_same_as_verified_candidate`、`repeated_candidate_count`、`nonimproving_candidate_transitions`、`parse_errors`、`output_truncated`
2. `mechanism_summary.csv`：按 `(stratum, condition)` 汇总。二值指标给比率和场景聚类 bootstrap CI（复用 `fraction_ci`），连续指标给均值。
3. `structure_contrasts.csv`：对 `success`、`first_submit_success`、`first_proposal_success` 三个指标，分别在每个层和 `MACRO`（各层等权平均）上计算：

   | 名称 | 定义（计划 12.2） |
   |---|---|
   | `dV` | 对 I、R 等权平均的 SR(V1) − SR(V0) |
   | `dR_V0` | 对 I 等权平均的 SR(V0,R1) − SR(V0,R0) |
   | `VR` | 对 I 等权平均的 [SR(V1,R1) − SR(V1,R0)] − [SR(V0,R1) − SR(V0,R0)] |
   | `dI_exploratory` | 对 V、R 等权平均的 SR(I1) − SR(I0)；**只作探索，不是主要结论** |

   - 先把每个场景内同一条件的 repeats 取平均，再按场景配对计算。
   - CI 用层内场景重采样的 bootstrap（seed 2026），MACRO 用分层 bootstrap。
   - 输出 `n_paired_scenarios`、`excluded_unpaired_scenarios` 和 `no_variation`；`no_variation` 在全部差值相同时为真，此时要注明 CI 退化。
4. `mechanism_report.json`：run_id、planned/complete、strata、是否为探索性分析。

**指标定义**（写进代码注释和预登记文档，二者要一致）：
- **proposal**：一次 `preview_bess_dispatch` 或 `submit` 的 `tool_finished`，按 turn 排序。
- **过度校正（overcorrection）**：初始纯欠压、动作后出现过压节点，或初始纯过压、动作后出现欠压节点。依据是物理结果里 `remaining_overvoltage_buses` / `remaining_undervoltage_buses` 非空。它和"原侧仍越限""不收敛""非法动作"是分开的。
- **`submitted_same_as_verified_candidate`**:第一次提交的调度是否等于之前某次**成功 preview** 的调度。如果之前没有成功的 preview,记为空值,不记 0。调度的比较用现有的 `dispatch_key`(忽略 0 功率项,排序后比较)。
- **`nonimproving_candidate_transitions`**:相邻两次 proposal 中,前一次未成功且越限幅度没有下降(后 ≥ 前)的次数。
- **`repeated_candidate_count`**:和本局之前某次 proposal 调度完全相同的 proposal 个数。

### A2. 测试 `tests/test_voltage_mechanisms.py`

仿照 `tests/test_voltage_trajectories.py` 构造合成的 run 目录，至少覆盖：
1. 欠压场景中 preview 出现过压 → `first_proposal_overcorrection == 1`。
2. 先 preview 成功,再提交同一调度 → `submitted_same_as_verified_candidate == 1`。没有成功的 preview → 空值。
3. 没有任何 proposal → `no_proposal == 1`,并且首次候选的相关字段为空。
4. 重复调度和"没有改善"的计数正确。
5. 用 8 个条件 × 2 个场景 × 2 个层构造已知成功率,核对 `dV`、`dR_V0`、`VR`、`dI_exploratory` 的数值与手算一致,包括 MACRO。
6. 不完整的 run:不加 `--allow-incomplete` 时报错;加上后 report 标记为探索性。
7. manifest 里缺少某个场景时报错。

### A3. 用 v2 真实数据做正确性对照

```powershell
cd E:\work\power_agent\PowerAgentBench
.venv\Scripts\python.exe -m scripts.analyze_voltage_mechanisms --run-dir ..\research_records\voltage_control\cny_pilot_192 --output-dir results\voltage_control\mechanism_check_v2
```

输出目录在被 Git 忽略的 `results/` 下。按 `success` 汇总全部场景时,期望值如下(由 v2 的 table3 手算得到):

| 对比 | 期望值 |
|---|---|
| `dV` | ≈ +0.229(与现有 table4 的 verification 一致) |
| `dR_V0` | ≈ +0.417 |
| `VR` | ≈ −0.417 |
| `dI_exploratory` | ≈ −0.021 |

v2 按 `difficulty`(easy/medium/hard)分层,MACRO 是三层的等权平均。要核对的是**所有场景合并计算**的值。如果 MACRO 与上表有差异,先确认是不是分层权重造成的,再判断是否是 bug。数值对不上就停下来排查,**不要为了对上而改公式**。

同时检查 `mechanism_summary.csv` 里的首次提交成功率:V1 各组应为 1.0,与 table3 的 `first_pass_success` 一致。

### A4. 全量测试

`.venv\Scripts\python.exe -m pytest -q tests`。结果应为原有 112 项加上新增项全部通过,1 项跳过。

**A 阶段验收**:新测试全部通过;全量测试不退化;v2 对照数值吻合。完成后可以在本地提交,提交信息说明"offline mechanism metrics"。

## 4. 阶段 B:预登记文档(离线,不花钱)

### B1. 写 `PowerAgentBench/docs/V3_PILOT_PREREGISTRATION.md`

**必须在任何 v3 模型输出产生之前完成并提交。**内容包括:
1. **范围**:v3 Dev,32 个场景 × 8 个条件 × 1 次重复 = 256 局。Smoke 另外单独说明。它们是开发诊断,不是论文 Test 结论。
2. **模型与设置**:DeepSeek `deepseek-flash`,Responses 接口,`--max-output-tokens 16384`,`--reasoning-effort high`,temperature 按 runner 默认,预算 12/4/3。和旧的 4096 Pilot 不可混合比较。
3. **主要对比**:`success` 指标上,按结构分层的 `dV`、`dR_V0`、`VR`,以及 MACRO。**重点看 S3/S4 与 S1/S2 的差异**(RQ1、RQ2)。
4. **次要对比**:`first_submit_success`、`first_proposal_success`、过度校正率、每局费用、实际潮流次数、token 数;`dI_exploratory`。同预算参照基线使用 v3 的 `bounded_local`,分层结果为 8/3/3/0。
5. **推断单位**:以场景为单位,按场景配对;在层内按场景做 bootstrap(1000 次,seed 2026);MACRO 用分层 bootstrap。只报告绝对百分点差和区间,不报 p 值。logistic 分离时明确写"不可估计"。
6. **天花板的判定与处理(预先固定)**:
   - 判定:Pilot 完成后,S3 与 S4 合并,在全部 V1 条件**以及** I0-V0-R1、I1-V0-R1 上成功率都 ≥ 95%;或 S3∪S4 的 `VR` 和 `dV` 的 CI 都包含 0 且点估计的绝对值 < 0.05。
   - 处理:按用户决定执行**小预算实验**(见第 6 节),**不修改语料,也不换题**。
   - 全成功照实报告。
7. **协议阻断**:截断、解析失败或传输错误造成的无效局超过 5% 时,先处理协议问题,暂不解释控制性能。这是工程警戒线,不是统计标准。
8. **不因结果不好看删除场景或局**;缺失、暂停和重试全部保留。

### B2. 把预登记文档纳入运行身份

在 `run_voltage_experiment_matrix.py` 约第 183 行,把 `"V3_PILOT_PREREGISTRATION.md"` 追加到 structure-v3 的 `protocol_paths` 列表。这样预登记内容的哈希会写进每个 v3 run 的 `analysis_protocol_sha256`,之后改动预登记就会被身份校验拒绝续跑。
- 同时在 `PowerAgentBench/docs/README.md` 的"哈希固定"表中加上这个文件,说明它自此也不能随意编辑。
- 为此加一条测试:structure-v3 manifest 下,预登记文件的内容变化会改变 `analysis_protocol_sha256`。或者核对现有测试中是否已有等价覆盖。
- 跑全量测试。

### B3. Smoke 场景的选择规则(写进预登记,选完就固定)

- 规则:每个结构类别内,选 `sha256("v3-smoke-2026:" + scenario_id)` 十六进制值最小的那个场景。
- 条件:`I0-V0-R0` 和 `I1-V1-R1`,共 4 个场景 × 2 个条件 = 8 局(对应计划 10.1)。
- 把选中的 4 个场景 ID 和计算过程写进预登记文档。**选择时只读 manifest,不看任何模型结果。**

**B 阶段验收**:预登记文档和 B2 的代码改动已提交到本地;全量测试通过。

## 5. 阶段 C:Smoke(8 局,付费)

### C1. Dry-run(不花钱)

```powershell
cd E:\work\power_agent\PowerAgentBench
.venv\Scripts\python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root ..\.local-data\voltage_structure_v3\dev --output-dir results\voltage_control\v3_smoke_8 --scenario-id <S1选中> --scenario-id <S2选中> --scenario-id <S3选中> --scenario-id <S4选中> --condition I0-V0-R0 --condition I1-V1-R1 --reasoning-effort high --max-output-tokens 16384 --campaign-stage smoke --dry-run
```

核对三点:tasks 为 8;条件和场景正确;model_settings 里 reasoning_effort=high、max_output_tokens=16384。
- 如果 runner 在 dry-run 时对 campaign 或定价有额外要求,照报错信息处理,**不要绕过门控**。
- 从 `requests.jsonl` 或 campaign 状态读出剩余额度并报告。

### C2. ⛔ STOP:向用户申请授权

向用户报告以下内容,**等用户明确回复同意**后再执行:
- 8 局的清单、使用的模型和设置
- 最坏费用:8 × ¥0.20 = ¥1.60(单局上限)
- 预计费用:参考 v2 平均每局约 ¥0.014,可能在 ¥0.1–0.5 之间
- 剩余额度约 ¥6.30,以及运行只在低谷时段进行

### C3. 执行 smoke

同意后,去掉 `--dry-run` 运行同一条命令。
- 高峰时段会自动暂停退出,等低谷时用同一个输出目录续跑。只有运行身份一致才能续跑,**不要换目录重开**。
- 遇到未知计费或孤立请求,按现有门控暂停并报告,不要自行清理。

### C4. Smoke 分析与报告

```powershell
.venv\Scripts\python.exe -m scripts.analyze_voltage_trajectories --run-dir results\voltage_control\v3_smoke_8 --campaign-dir results\voltage_control\cny_pilot_campaign --output-dir results\voltage_control\v3_smoke_8\analysis
.venv\Scripts\python.exe -m scripts.analyze_voltage_mechanisms --run-dir results\voltage_control\v3_smoke_8 --output-dir results\voltage_control\v3_smoke_8\mechanisms --manifest ..\.local-data\voltage_structure_v3\dev\manifest.json
```

smoke 只是子集,预计 mechanisms 脚本需要 `--allow-incomplete` 或会自动判定为完整。无论哪种情况都要**标注为连通性检查**。

报告内容:
1. 8 局是否全部完成;各局的结束原因
2. 解析错误、截断、传输错误的数量
3. 实际费用:每局平均、最大值、合计,以及账本里的未知请求
4. 每局 token 数和耗时
5. 所有新增指标是否都能从 v3 的事件里正确算出
6. **不从 8 局推断 I/V/R 效果**

### C5. 用 smoke 的实际费用估算 Pilot(不执行)

- 估算公式:Pilot 预计费用 = smoke 每局平均费用 × 256 × 1.5(安全系数)。另外单独给出按"每局最大值 × 256"算出的最坏值。
- 和剩余额度(约 ¥6.30 减去 smoke 花费)比较。**如果超出,需要用户把 campaign 总额从 ¥10 提高**。这是用户的决定,执行者不能自己改 `--max-campaign-cost-cny`。
- 同时估算 Main(2304 局)的费用,和用户给的"几十元"上限对照。如果超出,列出缩减方案,例如只跑 1 次重复,或减少条件。
- 把结果写进报告,然后 **⛔ STOP**,由用户决定是否进入 Pilot。

## 6. 后备:小预算实验(本轮只写设计,不执行)

只有在 Pilot 达到第 4 节 B1 的天花板判定标准后才会启用。本轮只需把设计写进预登记文档:
- **单独的实验版本**:preview 预算 b ∈ {1, 2},其他预算不变。**不能通过截断已有轨迹来模拟**(计划 11.5)。
- **条件**:4 个 V1 条件(I × R),这 4 个条件都依赖 preview 预算。在 32 个 Dev 上各跑 1 次:每个 b 值 128 局,两个 b 值共 256 局。
- **实现要求**:通过单独的配置文件或显式参数设置 preview 预算,不修改默认的 benchmark config。这样 `benchmark_config_sha256` 会变,自然形成新的运行身份。先确认 `config["agent"]["max_preview_calls"]` 能否通过这种方式覆盖。**本轮只做可行性核对,写成说明,不改代码。**
- **对应的同预算基线**:要用相同的 b 重新跑 `bounded_local` 和 `uniform_bisection`。这部分离线执行,不花钱。

## 7. 交付与汇报格式

每个 STOP 点和结束时,用中文汇报:

```text
状态:A 完成 / B 完成 / 等待 smoke 授权 / smoke 完成 / 阻塞
模型 API 调用:否 / 是(次数、费用、账本位置)
测试:实际命令和结果(不引用旧数字)
提交:本地 commit 哈希;是否已 push(默认否,push 前询问)
```

然后列出:改动的文件、v2 对照的数值、预登记文档路径、smoke 的场景 ID、费用和下一步需要用户决定的事项。

## 8. 不在本计划范围内

256 局 Pilot 的执行、v3 Test 生成、freeze/tag、Main、跨模型、小预算实验的执行、任何对 v3 语料或 5 个哈希固定文档的修改。
