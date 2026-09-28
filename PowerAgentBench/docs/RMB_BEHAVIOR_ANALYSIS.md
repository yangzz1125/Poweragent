# 人民币 Pilot：行为分析与研究设计复核

## 不变项

保持 v2 候选集、2×2×2 I/V/R、DeepSeek Flash Responses、12 turns/4 previews/3 submits 和独立 evaluator。单局 ¥0.20、全部开发/重试/Pilot 共用 ¥10；smoke ¥1 包含在总額中。当前无 Main 或跨模型付费授权。

真实 API 只在核实的低谷发起。每次请求与重试前检查时段和已发生费用，结束后记录人民币估算/上界再决定是否允许下一次请求。官方未提供精确缓存明细时报告保守上界，不把它作为实扣账单；中断/缺失 usage 不算零。缓存和低谷价格是成本混杂因素，因此除了人民币还记录原始 input/cache/output tokens 和各自覆盖率。

## 主要比较与分母

1. 主要机制结果：相同预定场景/重复的 I/V/R **最终成功率绝对差异**及 scenario-cluster CI。条件随机顺序已固定 seed。不得只选失败任务比较后声称因果提升。
2. 首次提交失败后的最终失败/恢复率：限真正提交过且首次失败的 R1 episode；分 I/V 与初次失败类型。R0 按设计首次失败即终止，单列，不解释为恢复能力差。
3. 工具错误恢复（JSON/非法动作）与物理错误恢复（潮流未收敛/剩余越限）分开。合法动作恢复不代表任务成功。
4. 连续错误统计以每 episode、每类首次连续错误段为主；下一个相关操作未观察到的行单列 unknown/censored，报告后续操作成功和整个 episode 最终成功两个结局。相同场景多个重复不是独立样本。
5. 费用和次数截断会影响可观察恢复机会。单局预算/turn/submit 耗尽有明确资源受限终态；campaign/低谷暂停、API 基础设施异常不伪装物理失败。全计划任务量、终态量、暂停/错误量必须并列。
6. 完整任务集来自 run.json planned_tasks，不从已观察场景数反推。部分运行给已知成功/N 到 (已知成功+未决)/N 的覆盖边界，不叫置信区间。
7. 单场景 smoke 不报告退化的 CI；零分母为 NA。低样本 logit separation 标注不可估计。交互效应聚类不确定性和完整 freeze 核查仍是 Main 前的单独阻塞，不能因为 Pilot 能画图就算通过。

## 已实现的可观察分析

`scripts/analyze_voltage_trajectories.py` 先将请求/工具事件导出标准 CSV，再读取 episode CSV：

- `first_failure_episodes.csv`、`recovery_summary.csv`：首次提交失败后的最终失败概率，附 R0 设计终止标志。
- `error_streaks.csv`、`streak_summary.csv`：首次连续命令/物理错误段，k 次错误后下一操作及最终成功；附 observed/unobserved 分母。
- `preview_summary.csv`、`preview_rates.csv`：后续 preview 成功、越限改善、重复动作、停滞、成功 preview 后是否原样提交。
- `action_transitions.csv`：一阶工具转移计数/概率，不强行做数据不足的高阶统计。
- `termination_summary.csv`、`failure_types.csv`：终止原因与错误事件类型，二者不能相互替代。
- `cost_summary.csv`：人民币已计估算/上界的平均、中位、P90、unknown 请求数、turn/PF；不是发票。
- `observed_budget_curve.csv`：实际轨迹在各金额内的已知成功份额，不是重新以该预算运行的因果实验。
- `trajectory_summary.json`：已计划/已记录/已成功/未决计数、覆盖边界和 campaign 费用。

不记录或解释模型隐藏思维；自动失败标签仅为可观测结果。若要解释“符号理解错误”“规划失误”，需基于动作/反馈人工复核，另报标注规则和不确定性。

## 已知局限与禁止结论

- v2 的 witness 来源是 bounded coordinate search，与 sensitivity baseline 同类；后者 100% 不能证明全分布覆盖。搜索失败不是已证明不可行。
- severity 是物理越限幅度，不直接等于控制难度；不为降 baseline 成绩继续改 Test。
- responses/chat 协议不是本次独立变量，不能从当前数据宣称 Responses 因果优于 Chat。
- 不从旧接口/旧 corpus smoke 与新接口跑分相减，得出精简 observation 的真实 token 降幅。
- ¥10 不保证192个 episode 都能跑完，遇到上限不自动加钱、不删除失败样本、不修改 budget 去补出好结果。
- 暂停记录、账本和模型版本一致性必须验收后才启动付费 Pilot。即使全部 Dev 完成，也不能把 Dev 数值直接当主论文结果。
