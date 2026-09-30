# Dev 输出上限16384诊断（独立于原192条Pilot）

## 设置与结果

- 场景 D0015，条件 I1-V0-R1；`run_scope=dev_diagnostic_subset`，1个预先指定任务，无失败后挑选/补跑。
- 新 run_id：`8f75f248-ef96-4677-89d7-d2161a5a7994`，目录 `results/voltage_control/v2_cny_16384_diagnostic`。
- 模型 deepseek-flash / Responses；max_output_tokens=16384，temperature请求值0，reasoning_effort未显式设置（provider_default）。12 turns、4 previews、3 submits及每局¥0.20上限不变。
- 与原Pilot共用campaign，全部请求在低谷；这次没有网络重试或新增未知费用。
- **成功，5轮、2次submit、3次实际PF，first-pass失败后恢复成功。**
- 总tokens 15493；费用估算 **¥0.01200310**。
- campaign现已知费用¥2.68279416，未知预留¥1.00，累计占用¥3.68279416/¥10；并非官方发票。

工具顺序：case_summary → inspect_voltage_state → get_bess_capabilities → submit（失败）→ submit（成功）。

## Provider状态验证

| 回合 | output_tokens | 可见字符 | response_status | incomplete_reason |
|---|---:|---:|---|---|
| 1 | 66 | 33 | completed | null |
| 2 | 26 | 42 | completed | null |
| 3 | 82 | 42 | completed | null |
| 4 | 895 | 165 | completed | null |
| 5 | 987 | 167 | completed | null |

新请求账本记录 max_output_tokens_requested、temperature_requested、reasoning_effort_requested、response_status、incomplete_reason、finish_reason。provider显式声明输出上限截断时，内部事件记 `output_truncated`，不再误标为普通parse_error；模型可见JSON修复提示保持不变。仅token数等于上限而缺少provider状态时**不推断**截断。

## 解释边界

原D0015/I1-V0-R1曾在第3、5–11轮达到4096 output_tokens而无可见文本，但当时未记录provider截断原因。这次最大单轮输出只有987，低于旧上限；因此**不能把这次成功归因于提高输出上限，也不能宣称旧问题已确定解决**。不同运行的模型输出有随机性，temperature=0并不保证确定性；两次轨迹也不同。

若需建立因果证据，应预先确定相同输入上下文的4096/16384配对诊断并记录provider状态，而不是反复跑到成功。此类额外诊断尚未执行。旧192条Pilot保留原始结果，这一条不补入原Pilot分母。Test未运行，完整freeze前验收仍未通过。

## 工程检查

新增Dev-only场景/条件选择，subset写入planned_tasks和run_scope；拒绝未知ID及Test subset。输出上限写入run/CSV，变更会拒绝原run续写。相关客户端、runner、campaign和行为分析24个离线测试通过；未声称已重跑完整Pilot。
