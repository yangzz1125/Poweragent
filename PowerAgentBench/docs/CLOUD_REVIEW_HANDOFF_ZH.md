# 云端审阅入口：项目进度与待决研究问题

本次交接基于实验代码/结果提交 `b8196e9`。之后的交接提交只整理文档与状态，不新增实验。请先读本页，再核对CSV、日志和源码；不要仅复述已有分析结论。

## 项目研究什么

研究Agent Harness中的三个因素如何影响LLM完成工程任务的可靠性与成本：领域接口I、执行前物理验证V、失败恢复R。采用完整2×2×2设计，不以LLM打败传统控制算法为目标。

任务为IEEE 33-bus静态电压控制：4台BESS，位置8/17/24/32，每台±1.5 MW，0.25 MW步长；目标是潮流收敛且所有节点电压在0.95–1.05 pu。线路热负载只作诊断，不是当前成功约束。每局12 turns、最多4 previews、3 submits；V0不能preview，R0首次提交失败即终止。

被测Agent使用托管API，没有shell或文件系统权限。当前不是Coding Agent benchmark，也没有多时段SOC控制、长期调度或设备故障恢复任务。

## 当前进度：工程已实现，研究设计待决定

- generator、独立evaluator、工具接口、8条件矩阵、断点续跑、人民币计费、行为与统计分析已有实现。
- v2候选corpus为24 Dev、96 Test；120个构造witness独立回放合格。原v1保留。
- 24×8=192局Dev Pilot完成，170局成功。
- 另有两次独立Dev诊断，以及两轮不调用LLM的物理/结构审查。
- 有未批准的freeze candidate，无正式freeze/tag，无Main授权，未跑2304局Test。
- 原计划的工程验收勾选完成，不表示研究设计已获认可，更不表示Main已完成或可以自动启动。
- 当前没有在生成v3，没有更换Test，没有新的付费实验在等待执行。

争议是：现有任务足不足以区分I/V/R的效果，还是只适合支撑较窄的“短程物理反馈减少错误”结论。请独立判断，不默认必须加难或必须保留原任务。

## 已有证据

### 1. Dev Pilot：192局，不是Test

每格24个场景，1次模型运行：

| 条件 | 成功数 |
|---|---:|
| I0-V0-R0 | 14/24 |
| I0-V0-R1 | 24/24 |
| I0-V1-R0 | 24/24 |
| I0-V1-R1 | 24/24 |
| I1-V0-R0 | 13/24 |
| I1-V0-R1 | 23/24 |
| I1-V1-R0 | 24/24 |
| I1-V1-R1 | 24/24 |

已有按场景配对bootstrap分析：V主效应+22.92个百分点，R+20.83，I−2.08；VR差中之差−41.67个百分点，表现为收益重叠/递减，不能解释为“恢复有害”。有全成功单元格和logistic separation；全成功格bootstrap区间[1,1]也不代表真实成功概率必为100%。

轨迹：96局V1中38局首次preview失败，但最终都成功；R1首次提交失败22局，21局恢复成功。V0-R0的21次失败中20次属于过度校正。R0按规则不允许失败后恢复，不能把它的终止率与R1的条件恢复率混为同一个比较。

上述因子是按当前实现的整套机制处理，不是纯粹的表示或信息等价实验。I0/I1观察不声称信息等价；V和R也改变可用反馈与尝试机会。请审查这些因素对因果解释的限制。

### 2. 可行空间诊断：24个Dev抽样与3个子空间穷举

对每个case，从28561个合法动作中抽256个；另从正确方向的2401个动作中抽256个，均为固定seed、无放回均匀抽样。

- 可行比例的case中位数：完整网格3.71%，正确方向网格21.88%。不能把这些中位数当成总体随机动作成功率。
- 对D0009/D0010/D0012的正确方向网格额外穷举，可行数9/2401、1/2401、51/2401。
- 三者都可用四台全部+1.5 MW解决，原Pilot两种V0-R0条件在这三局均成功（共6/6）。

这反驳了“物理可行域越小，LLM决策必然越难”的简单推断。D0010的唯一解结论只适用于穷举的非负子空间，不是完整合法空间。后续选这三个case做穷举属于Dev探索，不能冒充预登记总体研究。

### 3. 简单策略/模板覆盖：全部24 Dev

预写协议后，先执行无模板lookahead的均匀二分策略，再枚举固定模板族：

- 均匀二分最多4次查询，实测最多3次，解决19/24。成功局平均1.84次查询；全24局平均2次。
- 全部同向满功率一次可解决8/24。
- 19个有均匀解；余下5个中4个有单BESS解，仅D0022同时超出均匀和单BESS模板族。
- 全24个都有每台仅取{-1.5,0,+1.5} MW的组合解。

互斥标签按优先级为：全满功率8、均匀中间档11、单台非均匀4、零/满功率多台组合1、超出已测模板族0。这里的标签不是经过验证的综合难度等级。

**模板存在性是枚举81个组合得到的结果，不是4查询控制器100%成功。** 当前缺少“必须使用细粒度中间功率组合”的样本，但仍可能需要识别设备位置、符号与冲突约束。均匀策略也不是传统控制方法的上限。

两轮本地物理审查分别19838和3168次实际PF，无模型API费用。独立脚本的策略查询、最终重评与LLM的preview/submit/最终评分口径不同，不可直接比平均PF总数而不对齐。

## 配置与费用：不能混合历史结果

- 原192局Pilot使用4096输出上限、供应商默认reasoning设置。
- 新请求改为16384，显式`reasoning.effort=high`，模型为DeepSeek官方`deepseek-flash`，Responses协议。
- D0015的两次独立重跑成功，但输出均未超过原4096上限，不是“提高上限治好了失败”的因果证据。
- 原Pilot冻结保留；不能把旧结果冒充high/16384下的完整实验。
- 最近已核对的共享campaign累计995个HTTP请求，已知费用估算¥2.69531226，五笔未知计费各预留¥0.20，共预留¥1，占用¥3.69531226/¥10。预留不是已确认收费，估算也不是供应商账单。
- 新API调用仍受每局¥0.20、共享开发/Pilot ¥10、只低谷调用限制；本次云端审阅不授权新调用。

## 数据与代码阅读路线

以下路径均相对仓库根目录。

| 用途 | 路径 |
|---|---|
| 实验规范 | `PowerAgentBench/docs/BENCHMARK_SPEC.md` |
| v2构造方法与限制 | `PowerAgentBench/docs/CORPUS_V2_CANDIDATE.md` |
| Pilot解释 | `PowerAgentBench/docs/DEV_PILOT_RESULT_ANALYSIS_ZH.md` |
| Pilot公开CSV、事件与轨迹 | `research_records/voltage_control/cny_pilot_192/` |
| 绝对因子效应表 | `research_records/voltage_control/explicit_high_freeze_review/pilot_factorial_rate_contrasts.csv` |
| 参数诊断/冻结工程 | `PowerAgentBench/docs/EXPLICIT_REASONING_AND_FREEZE.md` |
| 动作空间诊断 | `research_records/voltage_control/dev_action_landscape_2030/` |
| 固定策略/模板覆盖 | `research_records/voltage_control/dev_structural_coverage/` |
| 费用定义 | `PowerAgentBench/docs/RMB_MEASUREMENT_SPEC.md` |
| 恢复分母与行为口径 | `PowerAgentBench/docs/RMB_BEHAVIOR_ANALYSIS.md` |
| 生成器 | `PowerAgentBench/scripts/generate_voltage_corpus.py` |
| 独立物理评分 | `PowerAgentBench/poweragentbench/voltage_evaluator.py` |
| 工具与Agent loop | `PowerAgentBench/poweragentbench/voltage_tools.py`、`voltage_agentic.py` |
| 矩阵与模型参数 | `PowerAgentBench/scripts/run_voltage_experiment_matrix.py`、`run_voltage_agent_eval.py` |
| 统计与轨迹分析 | `PowerAgentBench/scripts/analyze_voltage_experiments.py`、`analyze_voltage_trajectories.py` |
| 新诊断可复核实现 | `PowerAgentBench/scripts/study_voltage_landscape.py`、`study_voltage_shortcuts.py` |

GitHub仅有允许公开的Dev结果、代码和回归样例，不含候选corpus的完整网络、隐藏Test、私有witness、密钥和checkpoint。因此云端能重算公开统计、审查方法和代码，但不能只凭本仓库独立重跑全部v2物理场景。请将无法核验的物理结果标为“已有本地报告”，不要声称自行重跑验证过。

## 请云端模型详细回答

1. 从研究目标出发，当前实验到底能支持什么主张，哪些主张不成立？区分实现缺陷、统计局限和任务覆盖不足。
2. 反馈全成功是任务过易、模型能力够强、工具信息足够，还是预算/失败终止机制差异所致？现有证据能区分到哪一步？
3. I0/I1的信息差异、V/R的尝试机会、生成器witness搜索方法，与观察到的主效应/交互效应之间有哪些混淆或范围限制？
4. 简单模板覆盖能否否定本研究价值？比较控制算法不是目标时，应怎样使用这些baseline，避免立错问题？
5. 保留现有任务并收窄论文主张，是否值得继续？如果修改任务，最小必要改动是什么？不要默认引入多时段、更多设备或更大工具预算。
6. 如需新的结构分层，怎样预先定义物理指标、候选采样与接受规则，避免只保留模型/某baseline失败的case？若刻意构造粗模板无解的层级，如何报告其合成分布偏差？
7. 正式2304局是否合适？在Test保持未看的前提下，还缺哪些最少的Dev验证、重复次数或统计设计检查？不要把2304局当2304个独立场景。
8. 给出一个明确建议：继续原设计、最小修改后继续，或暂停此研究方向。列出理由、证据位置、主要反对意见和能推翻建议的证据。

建议输出：短结论；按优先级排列的问题清单（引用文件/列名/代码位置）；现有主张可保留与应撤回之处；最多三个后续步骤及停止条件。把已观测事实、推测和待验证假设分开。

本次只做审阅，不执行新实验、不改Test、不批准Main、不默认修改现有代码。现有记录中的建议也应被审查，而不是作为必须遵循的研究结论。
