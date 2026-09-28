# 人民币计量合同（Dev campaign）

## 已批准范围

单 episode ¥0.20；本次开发 API 测试、smoke、Pilot、重试及代码调整后新 run 共用 campaign 总额 ¥10。smoke 阶段 ¥1 包含在 ¥10 内。历史 smoke 单列，不推测过去缓存/时段费用。Main、跨模型、付费预算扫描未授权。

本轮使用 DeepSeek 官方 `deepseek-flash` / Responses，人民币价格以 `benchmarks/steady/voltage_control/config/pricing.json` 的来源、抓取时间和源页 SHA 为依据。它是价格快照，不保证未来仍生效，开始 campaign 前复核。单价单位为元/百万 tokens，低谷 cached input 0.02、uncached input 1、output 4；高峰分别 0.04、2、8。

## 费用

`(cached_input × hit_price + (input - cached_input) × miss_price + output × output_price) / 1000000`。

金额使用 Decimal（字符串构造），逐请求不舍入到分。输入总量已含 cached input，输出总量已含其 reasoning 子计数，不能重复相加。合法的 0 与未知不同；负值、非整数计数、缓存大于输入、相互冲突的 usage 字段均视为未知/异常。缓存明细缺失但输入/输出总量可用时，计算全 miss 的保守上界；整体 usage 缺失不填 0，暂停自动付费执行。所有估算和上界都不是供应商账单。

每次实际 HTTP 尝试均有 started 和 finished/error 事件（独立 request_id，包括重试）。收到响应先写费用，再检查金额，禁止到整局结束才检查。累计金额按请求唯一 ID 加总，不按 active episode 覆盖记录计算；失败重跑不能消除历史费用。中断造成 started 无 terminal event 为 orphan，潜在费用未知，暂停付费续跑待核对。

## 时段与暂停

明确使用 UTC+8：工作日 [09:00,12:00)、[14:00,18:00) 为高峰；周末为空闲，节假日未验证时保守当普通工作日。仅低谷开始请求，重试同样检查；接近高峰至少留出单次 timeout 安全窗口。跨界或覆盖任何高峰时间的响应按较高价作上界，记录需核对；不能保证服务商到账时点。

请求结束检查单局、阶段、campaign 金额，达到就禁止下一次 API 请求。已付费返回文本可处理至多一个原有工具动作；若该动作已成功提交，照常独立评分；不能为提交再免费调用模型。单局上限耗尽按已正式提交的最后动作判定，并记录资源截断；没有提交不能自动把 preview 当 submit。时段/campaign 停止为 paused，保留 checkpoint，不伪装任务失败。

## 分母与结果类型

- 单局正常结束、提交/轮数/单局金额耗尽：终态有明确 success/no_submission 与 termination_reason。
- 时段/总额暂停：未完成，不混入物理成功/失败分母；计划总量与完成量同时报告。
- API/evaluator 基础设施错误：独立类别，不能推测成模型物理决策失败；费用保留。
- 首次提交失败恢复率只对实际首次 submit 失败的 R1 episode 计算；无 submit、R0 强制终止、未知终态分别列出。
- 对所有计划任务给已知成功/N 与 (已知成功+未决)/N 的透明度边界；这不是置信区间。模型条件之间以共同预定场景作配对，不能只比较各自首次失败子集后声称因果效应。

验收：价格单位/来源/缓存拆分/零与未知/高峰边界有离线测试；不调用真实 API 验证价格。支付账单需用户另行核对，不读取账户支付信息。

## 实现与离线验收

- `voltage_costs.py`：Decimal 计费、Responses/Chat usage 归一化、UTC+8 时间窗、请求 JSONL、orphan 检测、campaign 锁和持久费用。
- `openai_client.py`：可选 request hook，started 先于网络，finished/error 包含唯一 request_id 和脱敏白名单元数据；last_debug 每次调用清空。CNY hook 在未知费用错误后停止自动 retry。
- `voltage_agentic.py`：按回合 checkpoint，已经收到账本中的付费响应可恢复处理、不重复付费；暂停与单局金额耗尽分开，工具反馈/失败前轨迹保留。
- runner：默认官方 Flash Responses CNY 模式；`.env` 密钥不写入 campaign；所有新 run 共用同一 campaign，阶段 smoke/pilot 不重置总额。更改价格或额度拒绝续跑。
- `analyze_voltage_trajectories.py`：事件/请求先导出 CSV，再做恢复和成本分析；保留未知/未决分母。
- 全部 `PowerAgentBench/tests` 离线回归：**59 passed**。覆盖 Decimal/缓存/非法 usage、HTTP retry/timeout、锁、计费上限、跨 run 累计、时段边界、paid-response 中断恢复、首轮已提交后第二轮失败、统计分母和现有电压回归。
- 新 CNY smoke 已在低谷完成8条件/42请求，¥0.05598432 对账通过；复用这8条继续 Pilot，目前62/192完成，1暂停、129未开始，已知费用¥0.76258752。一次 ConnectionResetError 未返回 usage，按合同暂停等待计费核对；不是预算不足。详见 [进度记录](CNY_PILOT_PROGRESS.md)。历史旧日志 smoke 不混入新结果。
- 真实 runner 高峰闸门检查（北京时间 2026-09-28 15:47 后）：run `83efca53-9f99-4d06-aeed-97b560e50aa1`，campaign `75672523-ca3b-418d-a0b4-e52466e0e8f8`；192 任务，0 completed、1 paused；**0 HTTP requests、¥0、0 unknown/orphan**，stop_reason=offpeak_pause。下一安全窗口 18:00（UTC+8）。目录 `results/voltage_control/v2_cny_pilot` / `cny_pilot_campaign` 已保存，恢复不重置账本；未设置定时唤醒。第 8 步付费 smoke 仍未验收。
