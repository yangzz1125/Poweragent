# PowerAgentBench 电压控制研究：自主执行计划

## Context

以 `E:/ASUS/Documents/Poweragent_Research_Execution_Plan.md` 为研究范围，完成 IEEE 33-bus BESS 电压控制 benchmark、8 组 I/V/R 实验、成本与统计分析、论文材料。现有代码已有独立 evaluator、工具、8 组配置、两个 LLM 客户端；上一轮生成了 24 Dev / 96 Test corpus（`E:/work/voltage_corpus_v1`），但尚未冻结。P3 只验证了托管 LLM 的消息边界，Coding Agent 的文件系统隔离尚未验收。现有本地未提交改动和无关 PPT 文件不能覆盖或误提交。

## Approach

默认完成正式论文版（主实验 96×8×3），采用**托管 LLM API Agent**：模型仅收 JSON 消息，不授予 shell / 文件读取；Coding Agent 沙箱评测是另一个研究对象，不纳入本次主实验。OpenAI 兼容服务优先按标准 `/v1/chat/completions` 接入，保留现有 Responses API 客户端；`.env` 稍后由用户放入，绝不把它写进仓库、日志或论文。默认英文论文草稿、中文执行记录；额外模型由后来 CLI/环境配置指定。不要假定兼容服务支持 JSON schema、`temperature=0` 或用量字段，pilot 验证兼容性并记录缺失。

沿原计划 P3→P12 顺序交付，每阶段先跑可重复检查、记录验收证据，再进入下一阶段。Dev 可以调试；Test 冻结后不能根据结果改 prompt、tool、场景、成功标准。离线工作（P3–P5、基线、自测、分析脚本与空数据图表检查）现在就做；无服务地址/凭据时停在 P6 外部关卡，绝不编造模型结果。API 费用由用户给出预算上限或显式授权后才允许大规模调用，pilot 后预估 2304 次运行成本并检查限额，不擅自花钱。

**已发现风险**：现有 `score_voltage_output` 把每个 preview/submit 都算一次潮流，非法动作实际上在 validation 阶段退出；`LLMVoltageAgent` 只保存调用文本，没有每回合 usage；OpenAI 客户端只实现 Responses API，`sanitized_debug()` 是末次调用快照，不能用它推算整局 tokens；`run_voltage_agent_eval.py` 一次只跑一个条件且把每次结果写成整批 CSV，不能可靠断点续跑。`voltage_tools.py` 目前会给成功后再次 submit 返回反馈，但每局独立实例；需要测试其预算与失败语义。

## Files to modify

- `PowerAgentBench/docs/BENCHMARK_SPEC.md`：冻结协议、逐阶段验收日志；新增 `PowerAgentBench/docs/paper_voltage_control.md` 仅在真实数据完成后写论文初稿。
- `PowerAgentBench/poweragentbench/voltage_agentic.py`、`voltage_tools.py`、`voltage_evaluator.py`：计数与安全边界（按实际代码复核后缩小改动）。
- `PowerAgentBench/poweragentbench/openai_client.py`、新增最小的 `poweragentbench/openai_chat_client.py`（仅当兼容端点不支持 Responses；复用 stdlib HTTP/重试和现有客户端接口），`ollama_client.py`：仅当使用 Ollama 作跨模型验证时补其逐次 token 用量/延迟；主实验优先修 OpenAI 兼容路径，不能只取末次快照。
- `PowerAgentBench/scripts/run_voltage_experiment_matrix.py`：统一 8 组条件和断点续跑。
- `PowerAgentBench/scripts/analyze_voltage_experiments.py`：统计、汇总和图表；如需独立图表脚本，复用同一聚合表而不是重算统计。
- `PowerAgentBench/pyproject.toml`：仅在确需新分析包且无法复用已装的 `numpy`、`pandas`、`scipy`、`matplotlib` 时增设可选 analysis 依赖；不污染基础运行依赖。
- `PowerAgentBench/tests/test_voltage_*.py`：行为、账本、恢复、无泄漏回归测试。
- `PowerAgentBench/benchmarks/steady/voltage_control/README.md`：复现命令及数据权限。

## Reuse（已确认）

- `voltage_case.py` 的 manifest/hash/场景加载与 `scripts/generate_voltage_corpus.py` 的候选筛选和独立 witness 回放。
- `voltage_evaluator.py::evaluate_voltage_dispatch` 的独立重载、合法性检查和潮流判断。
- `voltage_tools.py::VoltageToolServer` 的 preview/submit 预算及工具反馈。
- `voltage_agentic.py::LLMVoltageAgent`、`score_voltage_output`；`config/experiments.json` 已有完整 8 个条件。
- `scripts/run_voltage_agent_eval.py` 的客户端构造、prompt 加载、CSV/JSONL 记录；避免重新发明调用协议。

## Steps（每一关完成后更新验收记录）

- [x] **P3 运行边界**：锁定本研究仅测 hosted LLM API Agent，不向模型暴露任意文件/代码执行。复核 `test_voltage_corpus.py` 的 8 条消息泄漏测试、异常 fail-closed；仅在 evaluator 进程持有 `E:/work/voltage_corpus_v1`，测试模型消息与日志不泄漏 full path / witness。主实验不接 Coding Agent：若未来增加，另立隔离部署与从沙箱内读取否证测试，不把本机目录名当隔离。
- [x] **P4 客户端与遥测**：优先支持 `.env` 中 `POWERAGENTBENCH_OPENAI_URL`、`POWERAGENTBENCH_OPENAI_API_KEY`，CLI `--model`/`--api-mode chat|responses`；优先 chat completions，Responses 保留。仅在无 Responses 支持时添加 chat 适配器，统一返回纯文本+可查询的每回合 usage；统计接口字段缺失记 `NULL` 并记录 `usage_unavailable`，绝不填估算值 0。时延用单调时钟测每 episode；重试次数单列，兼容端点拒绝 schema/temperature 时不静默换实验参数（pilot 决定并写入冻结规范）。
- [x] **P4 调用账本**：`VoltageToolServer` 计数 preview 请求（包括非法）、submit 请求、evaluator 调用、**确实执行** `run_locked_power_flow` 的次数；最终独立重评单计一次 evaluator/PF（合法时），不能把原始场景生成、基线或独立 witness 验证混进 episode 成本。保留 `n_llm_turns`、`input_tokens`、`output_tokens`、`total_tokens`、`latency_seconds`、`first_submit_success`、`recovered`、`valid_action`（明确为最终提交动作是否合法）、最终失败与无 submit 的定义。尽量在共享 evaluator 出口计数而非 `attempts+previews` 推断；非法/不收敛、preview 禁用/预算耗尽/超轮数各有测试。恢复率分母只计有首次正式 submit 且首次失败的 episode；未提交单列。
- [x] **P5 统一 runner**：新增 `scripts/run_voltage_experiment_matrix.py`，读 `config/experiments.json`，参数 `--provider openai --model ... --api-mode ... --split dev|test --repeats --output-dir --continue-on-error`，可加 `--scenario-root`、`--dry-run`（无 API 调用只列任务）、`--max-episodes`/`--max-total-tokens` 安全闸；如有用户提供的模型单价，才启用 `--max-cost-usd`，未知单价不假装可估算账单。运行前验证全 8 个条件、split manifest/config hash、模型连接和预算；只允许一个 run_id 的 CSV 内同一 `(model, split, condition, scenario_id, repetition_index)` 唯一；每 episode 完成才追加 JSONL 记录，恢复时以有效记录重建/原子替换 `episodes.csv`，并拒绝在同一 run_id 混用 prompt/config/dataset/model/temperature/预算哈希。失败记录 error JSONL 与 status，重试失败任务必须明确选项，不静默丢样本；最后核对计划任务集减去已完成/失败集合。保留 trace JSONL，不向 LLM 发内部指标。复用现有 `make_client`/`write_csv`/`append_jsonl`，旧单条件 runner 保持可运行。
- [x] **P5 结果字段**：`results/voltage_control/episodes.csv` 固定 schema，至少包含 run_id、provider/model、scenario_id/difficulty/voltage_condition、split/condition/I/V/R/repeat、success/valid_action/first_pass_success/recovered、初末越限数与幅度、action_l1_mw、上述交互/成本指标、prompt/config/dataset hash 与版本、commit SHA、temperature、tool budgets、错误状态；缺少 usage 用空值。CSV 是正式分析唯一输入；生产结果与 debug 日志默认 git-ignored。
- [x] **P5 基线与离线验收**：复用 `scripts/run_voltage_baselines.py` 跑 Dev 的 no-action/nearest/sensitivity baseline；mock 客户端全 8 条 × 小样本 × 2 repeats，注入 API 失败、中断、无 submit、非法动作，验证续跑不重复且账本等于原始 trace；旧轨道只跑其现有测试，不改动 N-1/N-2/RestoreBench。
- [ ] **P6 Pilot（需要 `.env` 和用户付费预算）**：先 1 Dev × 8 条连接/结构化返回冒烟，再 24 Dev × 8 条完整 pilot（每格至少一次）；确认模型实际 endpoint/usage/temperature/schema 能力、符号、preview/recovery、无越预算、错误率、CSV 完整性与费用。修复只允许在 Dev 上；pilot 不进论文主结果。根据实测每回合 tokens/成本估计 Test 2304 episode 的上界；未取得额度/模型授权则停在此关。
- [ ] **P7 Freeze**：最终锁定 corpus、prompt、tool/evaluator、预算、CSV 定义、模型/endpoint/温度/解析方式和分析方案；保存 v1 协议清单（含 corpus `dataset_sha256`、两个 split manifest hash、配置/Prompt SHA、依赖版本、commit SHA、run 参数），检查 `git status` 无意外未提交文件并仅提交本任务文件。签本地 `benchmark-v1.0` tag（已存在且内容不同则停止，绝不移动/覆盖）；Test 结果不得反过来改冻结代码。更换 provider 行为或修 bug 若影响主要结果，另起版本并重新预登记而不是无声补跑。
- [ ] **P8 Main**：主模型 Test 96 × 8 × 3 = 2304 episode；同模型、任务、温度、预算；按预定顺序/固定随机种子交错条件减少时段偏差，失败保留原始记录，按预定策略重试**传输错误**并保留重试审计，不选择性重跑答错 case。复核矩阵全覆盖、唯一键、错误总数、数据哈希不变、成本没有超闸门；若不完整只报告已完成范围，不宣称 full experiment。
- [ ] **P9 跨模型**：追加两种用户授权可用模型；在锁定的 baseline/full 和关键消融条件上跑共同 case/repeat 子集，预先记录模型名、case 子集和预算；不可用时标记待外部模型授权，不虚报跨模型结论。
- [ ] **P10 统计**：只读 CSV；每 condition 报例数、成功率与绝对差异、first-pass、恢复率（带分母）、valid-action、功率潮流/令牌/时延；按 scenario 分簇 bootstrap 95% CI（重复运行不当成独立场景），同一场景/重复配对比较 I/V/R 效应；拟合 2×2×2 logistic 主效应和 IV/IR/VR/IVR 交互，分离/样本不足时报告不可估计而不输出假 p 值。按 Easy/Medium/Hard 分层；缺失 token/错误 episode 另列，禁止静默过滤。用已装 `scipy`/`numpy`/`pandas`，只有模型诊断确需时增可选 `statsmodels`。
- [ ] **P11 图表**：从 P10 同一聚合数据产出 Figure 1–6、Table 1–4（架构、factorial、主成功率 CI、难度、成功率-潮流/令牌成本、恢复流）；使用 matplotlib，图脚注包含分母、CI 单位、数据版本；无真实结果的占位图不得标称实验结果。
- [ ] **P12 论文**：默认英文论文初稿及中文执行摘要：RQ、任务、三因素定义、独立 evaluator、可行 witness 和泄漏限制、冻结/重复协议、主效应与绝对值、成本、模型依赖及失败例；仅根据实际 CSV、图、表写结论，不加 SOC/多周期/OPF 等新功能。完成交付清单/复现命令并停止扩功能。

## Verification

1. 在 `PowerAgentBench/` 运行 `.venv/Scripts/python.exe -m pytest -q tests/test_voltage_agentic.py tests/test_voltage_evaluator.py tests/test_voltage_tools.py tests/test_voltage_corpus.py` 及新增 runner/分析测试；覆盖 mock usage、非法 dispatch 不计 PF、预览禁用、最终评估、失败续跑与八组互相独立。
2. 离线 `--dry-run` 核对 Dev 192 / Test 2304 任务及哈希；mock-run 小矩阵后强制中断再恢复，检查 CSV 无重复、缺失指标为 NULL、error 有日志，图表脚本对模拟 CSV 只生成测试产物，不混入正式结果。
3. 一次 Dev baseline + 一次 Dev pilot；凭独立 evaluator 重放抽样输出，核对 sign convention、witness 成功、八组工具权限和恢复预算、token 和 PF 账本的逐调用和；完整 pilot 后审查预算和冻结清单。
4. Main 前检查 tag、冻结文件 hash 和 corpus manifest；完成后校验 2304 条**成功执行的 episode 或明确列出的失败 episode**、全部条件/场景/重复覆盖和 CI/图表分母；保留依赖版本、run 参数、日志与代码 SHA。失败要如实纳入统计的预定处理规则，不能删除难 case。

## 执行进度（离线关卡）

P3–P5 已验收：hosted LLM 无 shell 工具、消息泄漏回归；兼容 Chat/Responses 客户端及逐回合 usage、evaluator/PF 账本；可恢复的 8 组 runner、统一 CSV、Dev 基线与 mock 测试。`24 passed`（含 8 条件×2 重复 mock）；Dev 基线 no-action 0/24、nearest 和 sensitivity 各 24/24（存在天花板效应风险）。P10/P11 的统计与图表脚本已用合成测试检查，但正式验收仍须等待 Test 真实结果；P6 是当前阻塞关卡：`.env` 尚未提供，不启动收费 API。P7–P12 未验收、未冻结、未打 tag。

## 执行控制 / 外部关卡

- 用户稍后提供 `.env`，计划不依赖其具体密钥。默认从环境读取 `POWERAGENTBENCH_OPENAI_URL` 与 `POWERAGENTBENCH_OPENAI_API_KEY`，模型 ID 从 CLI/env 显式指定；运行前只检查存在、端点能返回兼容响应，不能回显凭据。
- 未明确授权付费额度、主/额外模型时，AI 先完成代码、测试、Dev 离线检查与文档，然后停在需要外部资源的 P6/P8/P9，不自动推进收费实验；额度限额必须由用户指定金额/价格表或 token 上限，不能把尚未知的价格写死在代码里。若 API 无 token usage，报告 NULL 并在论文列限制，不猜测成本。
- Coding Agent 有 shell 时必须另建隔离项目/容器；本计划只针对现有 hosted LLM runner。写论文所需真实结果不足时交付可复现平台和进度报告，不能声称项目完整完成。
- 保留用户此前未提交的 PPT/代码变更；执行时先区分本计划改动与现有工作树，提交/tag 仅包含已审查的本项目文件；不自动 push。
