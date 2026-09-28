# Poweragent 开发交接

## 目标与边界

研究 IEEE 33-bus BESS 电压控制任务中 I/V/R Harness 的可靠性与成本，主实验只使用 PowerAgentBench + pandapower + hosted LLM API。PowerMCP/PowerSkills 作参考，不扩展 SOC、无功、多周期、MCP transport 或 Coding Agent 沙箱。公开入口和运行命令见 [README](README.md)，物理合同见 [BENCHMARK_SPEC](PowerAgentBench/docs/BENCHMARK_SPEC.md)。

## 当前验收，不要误报

- 本机虚拟环境 `PowerAgentBench/.venv`；PyPSA 1.2.4 / pandas 2.3.3，依赖检查已通过。Python 最低 3.11。
- 回归集 V0001–V0008 在仓库中；主研究候选集本地 `E:/work/voltage_corpus_v1` 有 24 Dev / 96 Test，未冻结，未发布。
- Dev scripted baseline：no-action 0/24，nearest/sensitivity 各 24/24。**不代表 LLM 也会 100%，也不证明任务足够难。**
- DeepSeek 官方 `deepseek-flash` + Responses 已跑过 D0005/I0-V0-R0 一个 episode：成功，5 turns，27421 tokens，约 35.7 秒，有一次 JSON parse error。是旧 observation 接口下的 smoke，不是完整 Pilot。
- 8 组矩阵、逐回合 tokens、独立 PF 计数、结果恢复和分析图表已有离线测试；完整 Dev Pilot、freeze/tag、Main、跨模型及正式论文结果均未完成。

## 当前最高优先级：corpus 方法学

生成脚本 `scripts/generate_voltage_corpus.py::candidate` 对每个候选只试 6 个四 BESS 同向等功率档位。失败就抛弃；因此现有 corpus **按简单均匀策略可解性筛选**，不能声称代表一般 BESS 可行任务。三档 severity 是越限幅度排序，不是控制难度。

分层还有一个已知偏差：每档按 severity 排序后，前部选作 Dev、后部作 Test，Dev 在每档内偏轻。不要用现有 Dev 100% 给 Test 作定论，也不要查看 Test 成绩后调场景。

下一步应在独立 Dev 候选池进行：

1. 保留原 corpus/hash，不覆盖、不修改动作边界或 success criterion，不按基线失败率挑 Test。
2. 预先定义更广的负荷/PV 空间变化与排除条件；保持四 BESS 控制空间固定。
3. 用合法离散动作的更广 witness 搜索替代均匀策略过滤；搜索失败应标记“未找到 witness”，不是已证明不可行。记录搜索方法、PF 预算和成功分布。
4. 比較固定均匀动作、单次简单策略与多次 simulator-guided baseline 的成功和成本；报告是否有控制余量紧、局部动作相互制约的任务。不能只追求基线低分。
5. 分层后使用固定 seed 在每档随机划分 Dev/Test，避免前低后高；所有方法学选择在新 Test 冻结前完成。用新目录和版本记录生成器/配置/solver，不覆写 v1 候选。

这是尚未实施/验收的研究工作；不要把本次文档更正当成已修好 corpus。

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
| `scripts/generate_voltage_corpus.py` | 候选 generator，存在上述筛选偏差 |
| `scripts/build_voltage_cases.py` | 旧 8 个 regression 场景，不是正式 corpus |
| `scripts/run_voltage_baselines.py` | 3 baseline，默认旧 8 case，Dev 要传 `--scenario-root` |
| `scripts/analyze_voltage_experiments.py` | 只读 CSV 的分析与图表，正式结果仍待验收 |

`.env` 中 URL/API_KEY/MODEL/API_MODE 与 `.env.example` 一致；默认 Responses。不要读取/回显凭据，不写入 trace、Git 或论文。dry-run 不调用模型。

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
