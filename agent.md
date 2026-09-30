# Poweragent 开发交接

> **注意（文档整理后）：** 本文件写于 v2 Pilot 阶段（2026-09-28），之后项目已进入 v3/路线B。当前状态以 [README](README.md)、[V3 离线验收](PowerAgentBench/docs/V3_OFFLINE_ACCEPTANCE.md) 和 [路线 B 方案](PowerAgentBench/docs/ROUTE_B_PLAN.md) 为准；文档索引见 [docs/README.md](PowerAgentBench/docs/README.md)。v2 时代的文档已移入 `PowerAgentBench/docs/archive/`，下文路径已相应更新。

## 最新交接：Pilot 已完成，暂不跑 Main

v2 Dev 192/192终态，170成功；全低谷985 HTTP尝试，已知估算¥2.67079106、未知费用预留¥1，共¥3.67079106/¥10。五次ConnectionResetError保留在账本，用户已授权后续每笔未知预留¥0.20并有限重试，不再逐笔人工暂停。注意这不是确认收费，绝不绕过campaign总额。

完整脱敏公开记录 `research_records/voltage_control/cny_pilot_192/`（含analysis/、环境快照和SHA256）供其他云端Agent分析。全套离线61 tests通过。第9步完成、第10步未通过：见 `PowerAgentBench/docs/archive/v2/PILOT_PREFREEZE_REVIEW.md`。D0015/I1-V0-R1的8次空文本parse_error都对应4096 output_tokens，需审查输出上限/思考参数；不按Test调参。没有Main授权，不创建tag；下文部分段落保留旧阶段背景，以此最新交接和审查为准。

## 目标与边界

研究 IEEE 33-bus BESS 电压控制任务中 I/V/R Harness 的可靠性与成本，主实验只使用 PowerAgentBench + pandapower + hosted LLM API。PowerMCP/PowerSkills 作参考，不扩展 SOC、无功、多周期、MCP transport 或 Coding Agent 沙箱。公开入口和运行命令见 [README](README.md)，物理合同见 [BENCHMARK_SPEC](PowerAgentBench/docs/BENCHMARK_SPEC.md)。

## 当前验收，不要误报

- 本机虚拟环境 `PowerAgentBench/.venv`；PyPSA 1.2.4 / pandas 2.3.3，依赖检查已通过。Python 最低 3.11。
- 回归集 V0001–V0008 在仓库中；主研究候选集本地 `E:/work/voltage_corpus_v1` 有 24 Dev / 96 Test，未冻结，未发布。
- Dev scripted baseline：no-action 0/24，nearest/sensitivity 各 24/24。**不代表 LLM 也会 100%，也不证明任务足够难。**
- DeepSeek 官方 `deepseek-flash` + Responses 已跑过 D0005/I0-V0-R0 一个 episode：成功，5 turns，27421 tokens，约 35.7 秒，有一次 JSON parse error。是旧 observation 接口下的 smoke，不是完整 Pilot。
- 8 组矩阵、逐回合 tokens、独立 PF 计数、结果恢复和分析图表已有离线测试；完整 Dev Pilot、freeze/tag、Main、跨模型及正式论文结果均未完成。

## 当前最高优先级：corpus 方法学

旧 v1 按 6 个同向均匀动作筛选，存在选择偏差。generator 现已改为空间负荷/PV + bounded coordinate search，生成独立的 `E:/work/voltage_corpus_v2_candidate`（24/96，全部 witness 重放通过），详情见 `PowerAgentBench/docs/archive/v2/CORPUS_V2_CANDIDATE.md`。仍有 coordinate 搜索偏差；三档 severity 不是控制难度。新 Dev nearest 22/24，sensitivity 24/24；不要再为了压低 baseline 成绩调整采样。

现有 v1 数据有分层偏差：每档前部选作 Dev、后部作 Test，Dev 在每档内偏轻。生成代码现已改为每档固定 seed shuffle，并记录 split_policy/generator hash；v2 候选集已独立生成，旧 v1 未覆盖。不要用现有 Dev 100% 给 Test 作定论。独立 Dev 分层诊断已得到 20 欠压/17 过压/3 正常候选，单次策略成功 8/37、非均匀搜索 28/37；见 `PowerAgentBench/docs/archive/v2/DEV_DIFFICULTY_AUDIT.md`，不是正式实验。

下一步应在独立 Dev 候选池进行：

1. 保留原 corpus/hash，不覆盖、不修改动作边界或 success criterion，不按基线失败率挑 Test。
2. 预先定义更广的负荷/PV 空间变化与排除条件；保持四 BESS 控制空间固定。
3. 用合法离散动作的更广 witness 搜索替代均匀策略过滤；搜索失败应标记“未找到 witness”，不是已证明不可行。记录搜索方法、PF 预算和成功分布。
4. 比較固定均匀动作、单次简单策略与多次 simulator-guided baseline 的成功和成本；报告是否有控制余量紧、局部动作相互制约的任务。不能只追求基线低分。
5. 分层后使用固定 seed 在每档随机划分 Dev/Test，避免前低后高；所有方法学选择在新 Test 冻结前完成。用新目录和版本记录生成器/配置/solver，不覆写 v1 候选。

上述更广采样、非均匀 witness 和随机分层已在 v2 候选集实现并验收；搜索完备性和 LLM 难度仍未建立，禁止宣称已完成 freeze 或正式研究。

## Observation 约定（已精简）

`voltage_case.py::public_scenario_card` 仅返回 scenario_id、voltage limits、电压状态和符号约定；不带 network 或 BESS capabilities。`case_summary` 仍可取完整静态 network，`get_bess_capabilities` 提供动作边界。不删拓扑访问、不改电压数字、不根据 I/V/R 做不同精简。generic/domain 是语义预处理对比，不声称 information-equivalent。

DeepSeek Responses 无状态，LLM 仍收到历史文本 JSON；减少重复 observation 不等于服务端缓存历史。不要做激进截断而丢失 preview/recovery 反馈；测真实 tokens 前只报告 JSON 字节变化。

工具接口变更后用新 run 输出目录；旧 smoke 不混入新 Pilot。runner 尚不能自动检测所有未提交的源码变更，不能依赖 commit SHA 掩盖 dirty tree。

## 代码索引与操作

路径都相对 `PowerAgentBench/`：

| 文件 | 职责 |
|---|---|
| `poweragentbench/voltage_case.py` | 构建/加载、哈希、观察卡 |
| `poweragentbench/voltage_evaluator.py` | 合法性、符号转换、独立重载潮流 |
| `poweragentbench/voltage_tools.py` | preview/submit 和预算/调用账本 |
| `poweragentbench/voltage_agentic.py` | LLM loop、3 scripted baselines、score |
| `poweragentbench/openai_client.py` | Responses HTTP 与输出解析 |
| `poweragentbench/openai_chat_client.py` | 兼容 Chat 的备用适配器 |
| `scripts/run_voltage_agent_eval.py` | `.env`/客户端构造、旧单条件 runner |
| `scripts/run_voltage_experiment_matrix.py` | 8 条件、恢复、标准 CSV；通过 `python -m scripts.run_voltage_experiment_matrix` 执行 |
| `scripts/generate_voltage_corpus.py` | v2 空间候选 generator、bounded coordinate search；保留搜索偏差说明 |
| `scripts/build_voltage_cases.py` | 旧 8 个 regression 场景，不是正式 corpus |
| `scripts/run_voltage_baselines.py` | 3 baseline，默认旧 8 case，Dev 要传 `--scenario-root` |
| `scripts/analyze_voltage_experiments.py` | 只读 CSV 的分析与图表，正式结果仍待验收 |

`.env` 中 URL/API_KEY/MODEL/API_MODE 与 `.env.example` 一致；默认 Responses。不要读取/回显凭据，不写入 trace、Git 或论文。dry-run 不调用模型。

## 人民币低预算执行（当前优先级）

用户已批准：单局 ¥0.20、整个开发测试+Pilot campaign ¥10，仅 DeepSeek 低谷；Main/跨模型不在授权内。执行 `PowerAgentBench/docs/archive/plans/rmb-budget-and-trajectory-analysis.md`（已归档），复用固定 `results/voltage_control/cny_pilot_campaign`，smoke 阶段 ¥1 包含在总额中。新运行目录 `results/voltage_control/v2_cny_pilot`，不能续写旧 smoke，也不能创建新 campaign 绕过花费。

`voltage_costs.py` 与 request hook 已实现请求前/后门控，unknown/orphan 计费会暂停自动重试。高峰前留 timeout 窗口，高峰退出并打印下一低谷时间，不自动预约后台。事件/计费/checkpoint 不能删除来恢复运行；只在身份一致时恢复。新日志协议离线 59 tests 通过，但付费 smoke/Pilot 仍需验收；见 RMB_MEASUREMENT_SPEC.md / RMB_BEHAVIOR_ANALYSIS.md。

## 不可破坏的合同

- 正 benchmark p_mw = 放电注入，pandapower storage 反号仅在 evaluator 转换。
- 每次正式 verdict 从冻结 full JSON 重载，不信任 agent 自报或 preview 内存。
- 收敛且每个节点在 [0.95,1.05]；thermal loading 诊断而非 success criterion。
- 非法动作不能被计为实际 PF；最终独立评估要计入成本，未提交不是 valid submitted action。
- 不用早期成功替代最终失败；保留 API/JSON/tool 错误，不偷偷删除失败样本。
- 保持 8 个条件和统一预算；不能通过选取 case/重复试到成功优化论文结果。

## 验证与发布

在 `PowerAgentBench/` 运行：

```powershell
uv pip check --python .venv/Scripts/python.exe
.venv/Scripts/python.exe -m pytest -q tests
.venv/Scripts/python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root E:/work/voltage_corpus_v1/dev --dry-run
```

原 N-1/N-2/RestoreBench 不扩改，必要时复用其现有测试；运行 voltage 测试不等于全仓库软件验收。API 需要明确预算，不自动跑 2304 次 Test。

根目录才是发布到 `yangzz1125/Poweragent` 的仓库；子目录残留嵌套 `.git`，在子目录调用 git 可能得到旧上游 commit，正式元数据发布前必须核对。无需为普通 workspace 修改额外提交各子仓库。不要删除用户改动或嵌套 `.git`；仅暂存任务文件，排除 `.env`、`.venv`、results、隐藏 corpus。freeze gate 尚未完成，不要创建 `benchmark-v1.0`。

研究交付以 Markdown 记录为主，供人工写 LaTeX/PPT；不以生成 PPT 为要求。入口文档必须同步真实代码与实际验收结果，不写未经验证的完成声明。
