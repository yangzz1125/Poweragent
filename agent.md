# Poweragent 开发交接

最后更新：2026-10-01。**换电脑接手先读第 10 节**。先读 [README](README.md)（进度与运行）和 [docs/README.md](PowerAgentBench/docs/README.md)（文档索引）；本文件只写**接手时容易踩坑的事**。

## 1. 当前状态（不要误报）

- **阶段**：路线 B（控制结构分层 benchmark v3）**离线验收 B0–B4 PASS**。详见 [V3_OFFLINE_ACCEPTANCE](PowerAgentBench/docs/V3_OFFLINE_ACCEPTANCE.md)，计划见 [ROUTE_B_PLAN](PowerAgentBench/docs/ROUTE_B_PLAN.md)。
- **数据**：v3 Dev 32 例（S1–S4 各 8），在 `.local-data/voltage_structure_v3/`（Git 忽略）。**没有 v3 Test**，没有 freeze，没有 `benchmark-v1.0` tag。
- **基线（同预算：最多 4 preview + 1 submit）**：No-action 0/32、全满功率 1/32、均匀二分 8/32、有界局部搜索 14/32。这些不是 LLM 成绩，也不是筛选目标。
- **模型结果**：v3 Dev Pilot **进行中、未完成**（见第 10 节）。尚无可解释的结论。v2 Dev Pilot（DeepSeek `deepseek-flash`，192/192，170 成功）是旧语料上的结果，不能当作 v3 或论文结论。
- **测试**：`tests/` 离线，112 passed / 1 skipped（约 6 分钟，阻止网络）。
- **已完成的精简**（2026-09-30）：v2 文档与旧计划归档到 `PowerAgentBench/docs/archive/`；上游 N-1/N-2/RestoreBench/动态内容移入 `PowerAgentBench/legacy_upstream/`，对应的 N-2 脚本和模块已删除（可从 Git 历史恢复）。

## 2. 授权与预算（没有新的授权就不要花钱）

- **已批准（旧）**：v2 阶段的人民币 campaign 总额 ¥10、单局 ¥0.20，仅 DeepSeek、仅低谷时段。已占用 ¥3.69531226（已知估算 ¥2.69531226 + 五笔未知费预留 ¥1）。
- **v3 阶段已批准（用户 2026-09-30/10-01）**：8 局 smoke（已完成）；256 局 Dev Pilot，campaign 总额上限 ¥22、单局 ¥0.20、仅 DeepSeek、仅低谷时段。第 10 节有当前账本状态。
- **未批准**：v3 Test 生成、freeze/tag、Main、跨模型。离线 PASS **不会**自动授权这些；按方案应先申请 8 局 smoke，再决定 256 局 Pilot，**不要直接启动 2304 局 Main**。
- campaign 总额不能靠新建 campaign 绕过；账本/事件/checkpoint 不能删除来恢复运行，只在运行身份一致时续跑。未知或孤立计费会暂停自动重试。
- `.env` 中的 URL/API_KEY/MODEL/API_MODE 不要读取、回显或写入日志/Git/论文。dry-run 不调用模型。
- 预算门控实现：`voltage_costs.py` 与 request hook（请求前/后）。规范见 `RMB_MEASUREMENT_SPEC.md`、`RMB_BEHAVIOR_ANALYSIS.md`。

## 3. 不可破坏的合同

- 正 benchmark `p_mw` = 放电注入；pandapower storage 的反号只在 evaluator 内转换。
- 每次正式 verdict 从冻结 full JSON 重载，不信任 agent 自报或 preview 内存。
- 成功 = 收敛且每个节点在 [0.95, 1.05]；thermal loading 只做诊断。
- 非法动作不计为实际 PF；最终独立评估计入成本；未提交不是 valid submitted action。
- 不用早期成功替代最终失败；保留 API/JSON/tool 错误，不删除失败样本。
- 保持 8 个条件和统一预算；**不能通过挑场景、换题、重复试到成功来优化结果**。即使完整组全成功也要如实解释。
- evaluator 已升级为 `voltage-replay-v2-finite-buses`（增加非有限/缺失/停役节点检查）；旧实验成绩未重写。

## 4. 哈希固定的文档（不要移动或编辑）

`docs/` 根目录的 5 个文件被 `scripts/run_voltage_experiment_matrix.py` 按路径读取，SHA256 写入运行身份 `analysis_protocol_sha256`：
`BENCHMARK_SPEC.md`、`RMB_MEASUREMENT_SPEC.md`、`RMB_BEHAVIOR_ANALYSIS.md`、`STRUCTURAL_BENCHMARK_V3_SPEC.md`、`V3_GENERATION_PROTOCOL.md`。
改动它们 = 有意的协议变更，必须开新的运行目录。它们内部有几条指向 `archive/v2/` 的失效相对链接，刻意不修，映射见 docs/README.md。

## 5. 代码索引

路径相对 `PowerAgentBench/`：

| 文件 | 职责 |
|---|---|
| `poweragentbench/voltage_case.py` | 构建/加载、哈希、观察卡 |
| `poweragentbench/voltage_structure.py` | v3 控制结构分层（S1–S4）、模板与认证 |
| `poweragentbench/voltage_storage.py` | 本地数据路径与存储 |
| `poweragentbench/voltage_evaluator.py` | 合法性、符号转换、独立重载潮流 |
| `poweragentbench/voltage_tools.py` | preview/submit、预算与调用账本 |
| `poweragentbench/voltage_agentic.py` | LLM loop、脚本化基线、评分 |
| `poweragentbench/voltage_costs.py` / `voltage_freeze.py` | 人民币门控 / 冻结身份校验 |
| `poweragentbench/openai_client.py` | Responses HTTP 与输出解析（默认）；`openai_chat_client.py` 为 Chat 备用 |
| `poweragentbench/llm_agent_adapter.py` | 仅 `parse_json_command`、`load_prompt_template` |
| `scripts/generate_voltage_structural_corpus.py` | v3 生成；`validate_voltage_structural_corpus.py` 独立校验 |
| `scripts/run_voltage_route_b.py` | v3 一键构造/续跑 + 基线 + 验收 |
| `scripts/run_voltage_structural_baselines.py` | v3 受限查询基线 |
| `scripts/run_voltage_experiment_matrix.py` | 8 条件矩阵、恢复、CSV、身份校验；用 `python -m scripts.run_voltage_experiment_matrix` |
| `scripts/generate_voltage_corpus.py` | v2 候选集 generator（保留，含搜索偏差说明） |
| `scripts/analyze_voltage_experiments.py` | 只读 CSV 的分析与图表 |

## 6. Observation 约定

`voltage_case.py::public_scenario_card` 仅返回 scenario_id、电压限值、电压状态和符号约定；不带 network 或 BESS capabilities。`case_summary` 可取完整静态 network，`get_bess_capabilities` 提供动作边界。不删拓扑访问、不改电压数字、不按 I/V/R 做不同精简；generic/domain 是语义预处理对比，不声称信息等价。

DeepSeek Responses 无状态，LLM 仍收到历史文本 JSON。不做激进截断而丢失 preview/recovery 反馈。工具接口变更后用新运行目录，旧 smoke 不混入新结果。

## 7. 常用命令

从 `PowerAgentBench/` 执行（路径都相对它）：

```powershell
# 全量离线回归（约 6 分钟）
.venv\Scripts\python.exe -m pytest -q tests

# v3 一键构造或续跑，含基线与独立校验；已有目录续跑新增 PF=0。完整重建请用新子目录，不要覆盖旧的
.venv\Scripts\python.exe -m scripts.run_voltage_route_b --output-dir ..\.local-data\voltage_structure_v3

# 只核对 v3 Dev 任务矩阵，不调用模型（应得到 256 个 planned tasks）
.venv\Scripts\python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root ..\.local-data\voltage_structure_v3\dev --output-dir results\voltage_control\v3_offline_dry_run --dry-run
```

数据布局与路径映射：[LOCAL_DATA_LAYOUT](PowerAgentBench/docs/LOCAL_DATA_LAYOUT.md)。

## 8. 发布与仓库

- **根目录**才是发布到 `yangzz1125/Poweragent` 的仓库。`PowerAgentBench/` 内有一个**有意保留**的嵌套 `.git`（上游残留）：在该子目录里执行 git 命令会作用在嵌套仓库上，得到旧上游提交，**提交/移动/删除请一律从根目录执行**。不要删除它。
- 只暂存任务文件，排除 `.env`、`.venv`、`results/`、`.local-data/`、`.local-archive/`（均已被忽略）。隐藏 Test、witness 和密钥不发布。
- `templates/`（CSEE 论文 LaTeX 模板）保持未跟踪，授权许可确认前不入库。
- 不要创建 `benchmark-v1.0`：freeze gate 尚未完成。
- Git 忽略不是操作系统隔离：当前只测无 shell/文件权限的托管 LLM；将来测 Coding Agent 必须另做文件访问隔离。

## 9. 已知局限（写论文时必须如实说明）

单拓扑、静态、4 维合成任务；结构分类不等于 LLM 难度；严格数值质量门和有界 witness 搜索带来选择偏差（仅 4 例做了全离散网格扫描）；每类仅 8 个 Dev；方向/recipe 在各类间并不完全匹配（如 S4 未选入 recipe B）；四类均衡是受控合成分布，不是现实频率；尚无 v3 模型结果。

研究交付以 Markdown 记录为主，供人工写 LaTeX/PPT；入口文档必须同步真实代码与实际验收结果，不写未经验证的完成声明。

## 10. v3 Dev Pilot 进度与换机交接（2026-10-01）

**目标**：完成 `results/voltage_control/v3_pilot_dev`（256 局 = 32 场景 × 8 条件），然后做分析并汇报。预登记见 `docs/V3_PILOT_PREREGISTRATION.md`。

**进度（只读核对于 2026-10-01）**：`episodes.csv` 147/256 局，全部 `complete`。smoke（`v3_smoke_8`，8 局）已完成并报告。费用账本：`requests.jsonl` 共 1919 条 started、1898 条 finished、19 条 error，其余为孤儿请求。
- 孤儿请求 2 个：`c55d01f0-5249-4d2d-bc1b-752afce840de`（**已**由用户批准预留 ¥0.20）和 `a25414ca-cdc6-4275-9449-f090567f864e`（**新**，尚未预留，须用户批准才能续跑）。
- `campaign.lock` 残留，内容 `pid=7580`，该进程已不存在（陈旧锁）。锁**绝不会**被程序自动删除，须用户同意后手动删。
- 此前总账（早前核对）：已记账约 ¥5.50，预留未知约 ¥2.80；最新数以重新核对为准。

**为什么停了**：旧电脑内存太小，Claude Code 的后台内存保护把实验进程强杀了两次，与代码、模型无关。强杀会留下陈旧锁和孤儿请求。

**换机需要手动拷的（均被 Git 忽略，GitHub 上没有）**：
1. `.local-data/voltage_structure_v3/`（评估端数据，不得公开）。位置必须与 `PowerAgentBench/` 同级。
2. `PowerAgentBench/.env`（API key，用私下渠道传，别走公开渠道）。
3. `PowerAgentBench/results/`（含 `v3_pilot_dev` 与 `cny_pilot_campaign`）。**账本必须原样带过去**；新建账本等于把 ¥22 上限重置，是被禁止的。拷贝前确认旧电脑没有实验在跑。

**新电脑环境**：
```powershell
git clone https://github.com/yangzz1125/Poweragent.git power_agent
cd power_agent\PowerAgentBench
uv venv --python 3.13 .venv
uv pip install --python .venv\Scripts\python.exe -e . pytest
.venv\Scripts\python.exe -m pytest -q tests
```

**续跑前必须做的（按顺序）**：
1. 只读核对：`episodes.csv` 局数、`requests.jsonl` 里的孤儿请求（started 无 end）、`campaign.lock`、`reservations.jsonl`。读 `requests.jsonl` 时要 `encoding='utf-8'`（Windows 默认 gbk 会报错）。
2. 向用户汇报，**得到明确批准后**才：(a) 确认锁里的 pid 不在运行，再删陈旧锁；(b) 在 `reservations.jsonl` 为每个未预留的孤儿请求追加预留记录（`reserve_cny: "0.20"`、`approved_by: "user"`、写明原因，格式参照已有记录）。不得自行批准。
3. 用与之前**完全一致**的参数续跑（运行身份才对得上；同一输出目录）：
```powershell
.venv\Scripts\python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root ../.local-data/voltage_structure_v3/dev --output-dir results/voltage_control/v3_pilot_dev --reasoning-effort high --max-output-tokens 16384 --campaign-stage pilot --max-campaign-cost-cny 22
```
- `voltage_costs.py` 里写死的批准上限已改为 ¥0.20/¥22（提交 `e44ab25`）；`campaign.json` 和 `reservation_policy.json` 里的上限也是 22（在 `results/`，随拷贝带走）。runner 的 CLI 默认 `--max-campaign-cost-cny` 仍是 10，所以必须显式传 22。
- 低谷时段由 runner 按价格配置自动暂停，不需要也不要去查系统时区；也不要查代理配置（用户隐私偏好）。

**跑完后的分析**（预登记的口径；未跑完只能加 `--allow-incomplete` 并标注“探索”）：
```powershell
.venv\Scripts\python.exe -m scripts.analyze_voltage_trajectories --run-dir resultsoltage_control3_pilot_dev --campaign-dir resultsoltage_control\cny_pilot_campaign --output-dir resultsoltage_control3_pilot_devnalysis
.venv\Scripts\python.exe -m scripts.analyze_voltage_mechanisms --run-dir resultsoltage_control3_pilot_dev --output-dir resultsoltage_control3_pilot_dev\mechanisms --manifest ..\.local-dataoltage_structure_v3\dev\manifest.json
```
然后：按预登记第 7 节判 S3∪S4 的天花板，按第 8 节查协议阻断（截断/解析/传输错误无效局 >5% 先处理协议）。汇报格式：“状态 / 模型 API 调用 / 测试 / 提交”，中文。

**待查**：约 9–10 个连接层错误（`ConnectionResetError`/`URLError`，集中在 2026-09-30 13:02–13:41）尚未定位根因；D0026 有输出截断风险（16384 tokens 对 V1R1 偏紧）；未决：是否换 OpenCode Go（需新增 Chat Completions 客户端、新运行目录、新 smoke，用户尚未决定）、Main 阶段规模。

**Git 提醒**：根目录才是发布仓库（见第 8 节）。推送前先问用户。
