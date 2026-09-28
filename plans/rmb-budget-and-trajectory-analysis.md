# 人民币预算与 Agent 失败轨迹分析计划（确认版）

## Context

本计划接续 `plans/voltage-benchmark-completion.md`，只补齐正式实验前缺失的人民币计费、逐事件日志、恢复分析和验收关卡，不重写现有 Harness，也不改变 v2 corpus。

已核对代码：
- `openai_client.py::_post` 负责 HTTP 重试，但只有最后一次 `last_debug`；每次请求和失败请求没有独立持久化账本。新调用失败时还可能保留上次成功响应。
- `voltage_agentic.py::LLMVoltageAgent.run` 累加成功返回的 usage，异常导致 episode 退出时可能丢失前面已消耗的费用和工具轨迹。
- matrix runner 目前仅在 episode 边界检查 tokens/美元累计；重跑失败记录会替换 active episode，旧费用不能随之消失。
- 当前已实现根仓库 commit、源码 SHA、固定 seed 条件随机化和 planned_tasks 完整性检查，复用这些改动，不重复实现。
- 分析脚本已实现主结果、scenario-cluster bootstrap、配对主效应、logistic 交互系数；缺少失败链、终止原因、失败费用和交互不确定性分析。
- v2 Dev 仅同一场景的 8 条件 smoke：6 个最终成功，记录 164961 tokens。不是完整 Pilot，不能据此得出机制效果。

研究依据：SWE-agent（arXiv:2405.15793v3）§4 每任务 $4；§5.2 / B.3.3 的 57.2% 是一次编辑错误后的编辑恢复概率，不是整个任务成功率。本项目应分别分析命令修复、物理恢复、最终成功。

## Approach

人民币（CNY 元）作为用户配置和报告的预算单位；tokens 保留作计费依据与成本指标，不再作为主实验停止预算。模型/API 价格不同，不照搬 SWE-agent 的 $4。保持 I/V/R、独立 evaluator、BESS 与电压限制不变。

以现有 JSONL/CSV 为基础，新增最小的按请求/工具事件持久化记录，不引入数据库、分布式服务或复杂监控平台。预算单位分为每 episode 与整个 Pilot campaign（包括连接测试、smoke、失败重试、修复后再跑）；换 output-dir 不重置 campaign 总额。

用户已确定：每次 API 请求结束后检查人民币金额；仅在 DeepSeek 低谷期调用。不是请求前精确预留，也不再以总 token 数作为停机闸门。串行运行，超限最多存在当前请求尾部费用（供应商未知计费不在此保证内）；未知 usage/中断账本必须暂停核对，不能当零后继续重试。

用户已确认的预算：单 episode ¥0.20；本次开发连接测试、smoke 和 Pilot **累计 ¥10**，不要求一定花完。Main、跨模型和额外预算扫描均暂不授权，不设置 ¥2500 之类高额默认值。到 ¥10 就停止，即使 Pilot 尚未跑完；不得自动加钱。已有历史调用单列，不假装归入新的 campaign 账本。

依据当前官方中文定价，Flash 低谷每百万输入缓存命中 ¥0.02、未命中 ¥1、输出 ¥4。现有 8 个 smoke 的输入 149431、输出 15530，按全部输入未命中且低谷计算约 ¥0.212，即平均 ¥0.0264/episode；192 次线性外推约 ¥5.08。这里只是一个场景的粗估，不能保证完整 Pilot 低于 ¥10，更不是历史实扣账单。

价格来源：https://api-docs.deepseek.com/zh-cn/quick_start/pricing 。实施时存带获取时间与内容哈希的人民币价格快照，不使用固定美元汇率估算。

## Files to modify

- `PowerAgentBench/poweragentbench/openai_client.py`：请求开始/成功/失败事件、usage 归一化、重试与缓存字段。
- `PowerAgentBench/poweragentbench/voltage_agentic.py`：每回合事件、错误分类、终止原因、失败后保留已完成日志。
- `PowerAgentBench/poweragentbench/voltage_tools.py` / `voltage_evaluator.py`：复用 PF 账本，补可机器判读的错误原因，确保统计不改变物理 verdict。
- `PowerAgentBench/scripts/run_voltage_experiment_matrix.py`：人民币总预算/单局预算、续跑审计、价格哈希与 schema 版本、异常 episode 处理。
- `PowerAgentBench/scripts/analyze_voltage_experiments.py`：恢复条件概率、失败分布、轨迹/成本分析及图表；若明显过长才拆独立轨迹分析脚本。
- 拟新增 `PowerAgentBench/poweragentbench/voltage_costs.py`：小型纯函数计费模块（Decimal、价格版本、缓存/时段、未知费用处理）。
- 拟新增 `PowerAgentBench/benchmarks/steady/voltage_control/config/pricing.json`：经官方人民币价格核对后的价格快照；不可填猜测价格。
- `PowerAgentBench/tests/test_voltage_client.py`、`test_voltage_matrix.py`、`test_voltage_telemetry.py`、`test_voltage_analysis.py` 及必要的计费测试。
- `PowerAgentBench/docs/BENCHMARK_SPEC.md`、`README.md`、`agent.md`：统一预算和字段、论文分析口径、复现说明。

## Reuse

- 客户端现有 `_post_once`、`_extract_text` 与重试规则；不新增第二套 API 调用栈。
- runner 的 `append_jsonl`、`atomic_csv`、`source_identity`、`ordered_tasks` 和 planned_tasks。
- `evaluate_voltage_dispatch` 的独立重载与真实 PF 计数、`VoltageToolServer` 的 preview/submit 状态。
- 分析脚本现有 `cluster_ci` 和配对 scenario/repeat 主效应统计。

## Steps（按顺序执行，每步记录验收证据）

- [x] 1. 冻结计量定义：确认单局 ¥0.20 / 本次 campaign ¥10，人民币原生价、cache hit/miss、分母及未知费用处理。价格快照按 request start/end 时间关联，跨价格边界保守按较高价记上界并标记待核对；禁止声称等同官方实扣。
- [x] 2. 请求级计费：每个 HTTP 尝试独立 ID，记录开始和结束，提前落盘；费用采用 Decimal，零与未知不同；不保存 API key 或模型隐藏推理。
- [x] 3. 人民币预算控制：每次实际 HTTP 请求结束后，先持久化 usage/cost 再检查 episode 和 campaign 金额；检查放在客户端重试层，不能重试数次以后才算钱。下次请求（包括自动 retry）之前再次检查累计值和低谷时段。终止原因 `episode_cost_limit`、`campaign_cost_limit`、`offpeak_pause`、`usage_unknown` 分开；预算停止不强行执行此前未提交动作，不覆盖最后一次提交。单局上限耗尽为资源受限 episode；全局上限/时段关闭导致的中断不能直接算物理失败。
- [x] 4. 事件日志：API、解析、工具、preview、submit、独立终评逐事件记录；保留失败前完整可观测轨迹，按 episode attempt 和 request ID 去重。
- [x] 5. 失败/恢复统计：首次提交失败后最终成功/失败，连续命令错误后的修复和最终成功，preview 改善，重复动作与停滞，终止原因和分组成本；报告分母、样本量和 CI。
- [x] 6. 研究设计复核：R0 首次失败即终止不能作为恢复能力比较；条件恢复率是描述性指标，不能忽略首次失败人群的选择差异；主要因果比较仍以所有共同场景的 I/V/R 绝对成功差异为主。
- [x] 7. 离线回归：模拟缓存 hit/miss、价格边界、HTTP 重试、超时/中断、未知 usage、预算截断、续跑与分析分母；不使用付费 API。模拟北京时间周一 08:59/09:00/12:00/14:00/18:00、周末和未知节假日，确认重试也不能绕过时段闸门。
- [x] 8. 新日志 schema 的小规模 Dev smoke：仅低谷，串行 1 Dev × 8 条件，内部阶段额度 ¥1（包含在 campaign ¥10 中），先验证账本等于逐请求费用之和、8 条件执行一致、关键日志无泄漏；不复用旧输出目录。若代码/参数未改且该任务属于 Pilot 任务集，复用该行，不重复收费；如发生修改则新 run，旧费用仍归 campaign。
- [ ] 9. 在 campaign 剩余额度及低谷时间内跑 24×8 Dev Pilot；沿用 12 turns/4 previews/3 submits，不同时扩大动作预算。报告费用分布、预算/turn/preview/submit 触发率、错误分类、恢复链覆盖。低谷窗口关闭时记录安全 checkpoint 并退出；恢复保持同一任务进度、计费账本，不能从头免费重置。明确每个任务 completed/paused/error/cost-limited 状态；不足 192 条时报告部分结果而不是删失败样本。
- [ ] 10. freeze 前验收：协议、源码/环境、价格、模型参数、计划任务集及分析规则完整；随后按单独授权启动 Main，不自动花完整主实验预算。

## 数据与实现合同

### 运行/计费配置

新增 CLI `--campaign-dir`、`--max-episode-cost-cny`、`--max-campaign-cost-cny`、`--pricing-file`；本 campaign 固定为 0.20/10，支持调低，不允许续跑静默调高。价格、额度、低谷规则写入 campaign 元数据；`.env` 只放 endpoint/model/凭据。现有 token/USD 参数作为旧实验兼容入口保留，但不能与人民币 campaign 模式同时指定以产生歧义。默认本轮 provider 为 DeepSeek Responses；未知 provider/model 无价格不能推测。

采用 stdlib `Decimal`（由字符串构造）；持久化金额为十进制字符串，不逐请求四舍五入到分，仅展示时舍入。统一公式：`(cached_input × hit_price + uncached_input × miss_price + output × output_price) / 1_000_000`。`input_tokens` 已含 cached input，不重复相加；output 中包含的 reasoning 用量不再次计费。若总输入/输出已知而 cache 明细缺失，按全部 miss 记明确的保守上界；若总 usage 缺失，费用为 NULL、状态 unknown，暂停 campaign 自动收费执行。成功费用不是账户发票，可与用户账单核对但不请求账户支付信息。

### 最小持久化文件

| 文件 | 内容/作用 |
|---|---|
| campaign `campaign.json` | campaign_id、额度、模型/价格快照、时段政策、单写入者锁；所有输出 run 指向它 |
| campaign `requests.jsonl` | 每次 HTTP 尝试的 started/finished/error/settled 事件；是累计费用权威来源，不能被重试删除 |
| run `events.jsonl` | 逐回合 parse/tool/preview/submit/evaluate/stop 事件及可观测命令/反馈 |
| run `checkpoint.json` | 原子替换：messages、下一 turn、tool state、最后处理的事件/响应 ID、累计计数；不含客户端密钥对象 |
| run `episodes.csv` / `episodes.jsonl` | 固定版本 schema 的汇总、各任务 active attempt 和终止原因；保留已有接口，新增人民币/完整性字段 |
| run `run.json` | 复用 planned_tasks、源码 SHA、配置/模型参数，新增 schema、pricing/campaign 身份、依赖版本和模型返回的版本信息 |

API 事件字段：`campaign_id/run_id/episode_key/episode_attempt_id/request_id/turn/retry_index`、UTC 起止时间、耗时、HTTP 状态/错误码、服务商 response ID、实际返回 model、输入/缓存/输出用量、price_version、offpeak 判定、`cost_cny/cost_upper_bound_cny/cost_status`。错误日志采用白名单字段及脱敏错误，不保存认证头、完整错误响应、API key 或模型隐藏推理。工具事件含 dispatch（合法时规范化）、结果分类、电压越限 count/magnitude、实际 PF 与 evaluator 调用、是否 terminal；这些内部字段不要额外发给模型。

先落 started 再发 HTTP，收到响应先落 finished/usage 和可恢复的可见文本，再处理动作。若进程在 started 后中断、没有 finished，标记 orphan/unknown，停止付费续跑待核对；不能假设该请求未收费。非法 JSON 同样计费。损坏的 JSONL 尾行保留副本并 fail-closed，不静默截去未审计费用。

已有 `last_debug` 每次调用前清空，callback 是可选参数，不破坏其他轨道原有 callable 用法。计费/低谷退出使用专用控制信号，不能被 HTTP transient retry 或 Agent 的 parse-error handler 吞掉。

### 请求结束与安全暂停语义

- 金额检查位于**每次 HTTP 请求完成后**。刚收到且已经付费的响应允许处理为至多一个现有工具动作（无需新 API 费用），随后保存 checkpoint；不是“预算耗尽后额外向模型请求 submit”。如该响应本身提交成功，按正常独立评估结束；否则依据已触发的限制结束/暂停。
- 单局达到 ¥0.20：禁止新模型调用；独立评估最后正式提交（若有），记录 `episode_cost_limit`；无提交为失败且 `no_submission=true`，不自动用 preview 动作冒充提交。
- campaign 达到 ¥10、低谷窗口关闭：保存当前 episode，标记 paused；不当作终态物理失败。恢复从 checkpoint 继续，不重新发已付费调用、不重置 turns/tools/cost。遇到源码/价格/模型协议不一致则拒绝恢复，先由用户决定；旧 run 保留。
- 使用单进程串行执行，campaign 锁防止两个 runner 同时消费 ¥10。进程故障留下的锁显式验证后释放，不自动抢占其他进程。
- HTTP 失败若无可核实 usage，就记录未知潜在费用并暂停；只能对有确定计费依据且仍在预算/时段内的失败做有限 retry。`--retry-errors` 不等于无成本重跑，所有旧费用都保留。

## 分析口径与交付表

### 错误类型与终止原因分开

可观察错误分类：`parse_error`、`unknown_tool`、`invalid_dispatch`、`pf_nonconverged`、`voltage_unresolved`、`api_error`、`evaluator_error`。终止原因：`success`、`first_failure_no_recovery`、`submit_limit`、`turn_limit`、`episode_cost_limit`、`no_submission`（附标志）、`campaign_pause`、`offpeak_pause`、`usage_unknown`、`infrastructure_error`。不能把“无功功率不够”“模型误解”之类推测当作自动标签；符号错误等只在有清晰规则或人工复核时标注。

### 必须产出的分析

1. **主结果表**：8 条件的 planned/completed/paused/error 数，success、valid action、first-pass、恢复率；主效应以所有共同预定场景比较，重复按 scenario 聚类。完整 Pilot 后也只是 Dev 诊断，不是论文 Test。
2. **首次失败表**：`P(final failure | first submit failed, R=1)` 与成功补集，分 I/V、初次失败类型、severity；分子/分母/CI 同报。R0 单列“设计上不能恢复”，不混入 R1 恢复能力估计。首次失败人群是条件选择，不用恢复率差异声称因果效应。
3. **连续错误曲线**：以每局首次连续错误段作主分析，k=1/2/3… 为至少 k 个连续同类错误后的下一次相关合法操作概率，以及最终任务成功概率；parse/invalid-dispatch 和物理失败分开。主样本每局每类一段，所有段仅作辅助聚类分析；结束/暂停前仍无观察机会者单列 censored，不能算成功或静默删去。
4. **Preview 表**：首次失败 preview 后下一个合法 preview 的越限幅度改善量/成功率，成功 preview 的动作是否原样正式提交、提交是否成功；相同规范化 dispatch 重复率、连续非改善次数、PF 与费用。只有收敛且可比较的电压量才计算幅度差；不收敛单列。
5. **费用/轮数分布**：成功、失败、资源受限、基础设施错误的人民币 median/mean/P90、turns、PF、unknown-cost 计数；逐回合累计费用曲线和触发限制比例。API retries 与 episode attempts 不混为一类。
6. **终止/失败类型表与图**：各原因数量、比例、分母；恢复流程图区分 first-pass、failed→recovered、failed→final failure、no-submit 和 censored。
7. **动作序列**：case_summary→inspect→preview→submit 等转移计数与条件概率，只做 1 阶转移，不为模仿论文加入没有样本支撑的 4 阶统计。
8. **预算收益描述曲线**：用本次轨迹记录的“成功时累计费用”绘制截至某金额已成功的比例；明确不是重新以较低上限运行的因果结果，不额外花钱跑多预算 sweep。若实际暂停、样本不足或规则不支持，则只给成本分布。

逐事件 JSONL 先导出 `requests.csv`/`events.csv`（统一 schema），统计层只读标准化 CSV；不在分析时再调模型或 evaluator。API 费用和物理指标分开存储。最终导出 `recovery_summary.csv`、`error_streaks.csv`、`termination_summary.csv`、`preview_summary.csv`、`cost_summary.csv` 和对应图；没有分母输出 NA，不能做 0/0=0。

暂停与基础设施错误不伪装物理失败：主表同时给已完成比例与计划覆盖率；在完整统计前拒绝“官方结果”模式。对未完成任务给成功率上下界（已知成功/N 与 [已知成功+未决]/N），作为透明度指标而非置信区间。scenario-cluster bootstrap 的 95% CI 用在有定义的比例/配对差异上；一个场景的 smoke 不画有误导性的 CI。

## Verification

- 单元检查：精确人民币加总（含缓存），费用未知不能当零；重试不会覆盖已发生费用；后续 API 失败不污染 last_debug。
- 故障注入：首轮成功、第二轮网络失败、中途异常退出/强制中断，重新运行后的费用不减少、不重复计数。
- 轨迹例子：JSON 修复但最终电压失败、非法动作修复、首次物理失败后 recovered、连续两次失败后预算终止、R0 强制结束、无 submit。
- 合成统计：整批场景缺失拒绝正式分析；分母为零输出 NA；同场景重复不当独立样本；错误/censored 单列，按预登记规则提供完成样本指标和敏感性分析。
- 最终以独立 evaluator 作为唯一成功判据；预算日志不修改物理评判。

## 低谷时间执行规则（用户已确认仅低谷）

按官方当前中文页：北京时间周一至周五（不含中国法定节假日）09:00–12:00、14:00–18:00 为高峰；其余时段及周末、法定节假日为空闲。使用明确 UTC+8 时区，不依赖电脑本地时区。

- 默认保守遵循工作日时段，不为节假日引入新依赖；无法确认节假日就仍按工作日处理，宁可漏跑优惠时段，不放行已知高峰。
- 每次请求和重试前检查。临近高峰边界至少预留单次 timeout 的安全窗口；网络/服务商结算时点不能由本机保证，跨界的在途调用标明并按高峰上界记录，不自动开下一次请求。
- 不自动启动 Docker、系统定时任务或后台常驻服务；窗口外打印下一可运行时间、安全退出。自动预约如需要另行明确，不能承诺未经安排的定时唤醒。
- 在途 timeout 可能仍被供应商计费；保存 unknown-cost 状态并暂停自动收费续跑，待核对，不在低预算下无限重试。

## 已确认授权与停止点

- 用户确认：单局 ¥0.20、本次开发 API 测试及 Pilot 累计 ¥10、每次请求结束检查、仅低谷执行。一次在途请求可能超额少量，不能承诺服务商实扣绝不超限。
- 计划批准后执行：离线实现/回归 → 低谷 smoke → 账本验收 → 同一 campaign 剩余额度内的 Dev Pilot。时间窗或预算不足时安全退出并报告完成数、支出/未知支出、下次可运行时间，不自动新建 campaign 绕限额。
- Main、跨模型、付费 budget sweep、扩大总预算、修改 v2 场景均不在本次授权内。Pilot 若暴露方法学问题，先记录，不为了完成数量静默更改 protocol。
- 完成条件分层：工程验收可以独立完成；只有 192 个任务均有预定终态、成本账本可对账，才能称 Pilot 完成。低谷/预算/未知计费阻塞时交付部分报告，不标记整个项目完成。
