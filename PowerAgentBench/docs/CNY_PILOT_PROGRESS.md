# 人民币低谷 Pilot 进度（部分运行，非论文结果）

## 身份与预算

- run：`83efca53-9f99-4d06-aeed-97b560e50aa1`
- campaign：`75672523-ca3b-418d-a0b4-e52466e0e8f8`
- 数据：v2 Dev，SHA `8642cae21141b22af062eb47d6c4fc8b9aeec9a981246678e1be3e05148545c3`
- DeepSeek Flash / Responses；串行，12 turns/4 previews/3 submits；单局 ¥0.20、campaign ¥10，smoke 阶段 ¥1 包含在总额内。
- 日志目录：`results/voltage_control/v2_cny_pilot`；账本 `results/voltage_control/cny_pilot_campaign`。不要删除或换目录清空费用。

## 第 8 步 smoke 验收完成

北京时间 2026-09-28 19 点低谷开始。同一 D0005 的 8 条件全部完成，6 成功、2 正常任务失败。42 个 HTTP 请求，全为 offpeak；费用 ¥0.05598432，逐请求 Decimal 加总等于 episode CSV 合计和 campaign 合计，无 unknown/orphan；16 个元数据/日志/checkpoint 文件密钥扫描通过。

这 8 个 episode 已直接计入后续 Pilot，没有重复收费。单场景不作 CI 或机制因果结论。

## GitHub 分析快照与统一异常预留

用户要求将脱敏 Dev 记录上传 GitHub 并继续监督实验。66条进度快照位于 `research_records/voltage_control/cny_pilot_066/`，包含 CSV、逐事件/请求账本、价格、预留和元数据迁移审计；不包含密钥、checkpoint、隐藏Test/full或参考witness。

此后统一采用经用户批准的 ¥0.20/未知请求预留策略，计入原 ¥10 campaign 总额，保留 unknown 标签；HTTP ConnectionResetError 纳入现有有限重试（最多3次 retry），每次重试仍检查时间窗和人民币总额。当前2笔未知均已预留，占用¥0.40；已知¥0.81203662，总占用¥1.21203662。不是供应商收费确认。若新请求耗尽额度仍会停机，不自动追加预算。

两次错误发生在1.114秒和0.264秒后，均未返回HTTP状态/usage；现有日志无法判定来自本地网络、代理、TLS链路或服务商。不能断言模型/任务复杂度造成这些连接重置。针对性离线35 tests通过后启用自动预留与重试，既不把费用当零，也不再为每笔同类小额未知费用人工停整轮。

## 前阶段续跑：66/192，第二笔未知费用暂停

用户批准对 request `15aed31f-adb3-46f1-a5b7-8b8fc837a2ea` 预留 ¥0.20，仅占用 campaign 总预算，不伪造实际费用或单局模型消耗。预留追加到 `reservations.jsonl`，原 error/unknown 事件保留。为支持这一明确授权的会计处理，仅修改 `voltage_costs.py`；`run.before_reservation.json` 和 `metadata_migrations.jsonl` 保留旧源码身份及迁移原因，已有62条结果不改写、不重跑。

续跑新增4个终态：现 **66完成、61成功、5任务失败，1暂停、125未开始**。已知费用 **¥0.81203662**，已授权预留 **¥0.20**，总预算占用 **¥1.01203662**；共336请求，2笔未知，其中1笔未获预留授权。

第二次 `ConnectionResetError`：request `9db77e22-e6f7-4736-9062-0db9d463f8d0`，UTC 2026-09-28 12:54:55.961617（北京时间20:54:55），D0002/I0-V0-R0/turn 5，0.264秒后连接重置，无HTTP状态/usage。前4轮的对话和费用保留。一次预留授权不自动适用于后续错误，因此再次暂停；没有绕过¥10上限，也没有删除未知账单记录。

离线验证：预留保留 unknown 标记、纳入 campaign 总额、不虚构单局实际费用、不自动覆盖下一笔异常；相关29个测试通过。当前需要确认第二笔或统一后续有限预留策略，不能以“完成Pilot”为理由擅自处理未知计费。下文62条结果为此前阶段记录。

## 第 9 步 Pilot 前阶段部分结果（62条）

随后切换 campaign-stage=pilot，在同一 run、相同源码和账本续跑。现在：

- 192 个计划任务；62 个完成，1 个暂停，129 个未开始（共 130 个未决）。
- 已完成任务 57 成功、5 失败；失败均为 R0 首次提交失败后正常终止。
- 311 个 HTTP 请求（310 个返回响应、1 个连接重置），均在低谷发起。
- **已知费用 ¥0.76258752，另有 1 个未知计费请求**。费用不是发票；不能把未知计费计为零。
- 已完成任务 token 总量 1078082；费用 median ¥0.00861826、max ¥0.15076688。
- 观测最大 turns=12、preview=3、submit=2；没有单局金额/campaign 金额限制导致的终态。
- 完成的 R1 首次提交失败共6局，6局恢复成功；只有部分 Dev 和很小分母，不得解释为稳定100%恢复能力。
- 已保存 trace 共发现8次 parse_error；仍须完整 Pilot 后按条件/任务归类分析。

| 条件 | 完成 | 成功 |
|---|---:|---:|
| I0-V0-R0 | 8 | 6 |
| I0-V0-R1 | 8 | 8 |
| I0-V1-R0 | 8 | 8 |
| I0-V1-R1 | 8 | 8 |
| I1-V0-R0 | 7 | 4 |
| I1-V0-R1 | 8 | 8 |
| I1-V1-R0 | 7 | 7 |
| I1-V1-R1 | 8 | 8 |

条件覆盖不齐，不能从这张表推出 I1 比 I0 更差等结论。分析脚本保留 planned 分母；不把缺失任务悄悄排除。临时 CSV/图在 `results/voltage_control/v2_cny_partial_analysis`。

## 暂停原因与恢复前动作

在 D0009 / I1-V0-R0 / turn 1 发生 `ConnectionResetError`：

- request_id：`15aed31f-adb3-46f1-a5b7-8b8fc837a2ea`
- UTC：2026-09-28 11:20:04.425536 → 11:20:05.539602
- 北京时间：2026-09-28 19:20:04 → 19:20:05
- 未收到 HTTP 状态或 usage；error 事件完整落盘，不是 orphan。

程序按合同 `usage_unknown` 暂停，未自动重试。已知 episode 费用与请求账本仍相等。需要核对该时间附近的供应商用量/账单；未确认金额或明确批准保守计提处理前，不继续收费调用、不删错误记录。恢复仍受 ¥10 总额和低谷规则约束。第9步尚未完成，第10步 freeze 前验收不得标记完成；本轮没有执行 Test，也未创建 benchmark-v1.0。
