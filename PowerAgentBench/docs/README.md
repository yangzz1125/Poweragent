# 文档索引

最后整理：2026-09-30。当前进度和下一步以根目录 [README](../../README.md) 为准。

## 现行文档（`docs/` 根目录）

| 文件 | 内容 | 备注 |
|---|---|---|
| [ROUTE_B_PLAN.md](ROUTE_B_PLAN.md) | 路线 B：控制结构分层 Benchmark v3 执行方案 | **当前唯一的项目计划** |
| [V3_OFFLINE_ACCEPTANCE.md](V3_OFFLINE_ACCEPTANCE.md) | v3 离线验收（B0–B4 PASS） | 最新进度 |
| [STRUCTURAL_BENCHMARK_V3_SPEC.md](STRUCTURAL_BENCHMARK_V3_SPEC.md) | v3 离线认证规范 | 哈希固定 |
| [V3_GENERATION_PROTOCOL.md](V3_GENERATION_PROTOCOL.md) | v3 离线生成协议 | 哈希固定 |
| [V3_PILOT_PREREGISTRATION.md](V3_PILOT_PREREGISTRATION.md) | v3 Dev Pilot 预登记（范围、对比、天花板规则、smoke 场景） | 哈希固定（仅 structure-v3 运行） |
| [LOCAL_DATA_LAYOUT.md](LOCAL_DATA_LAYOUT.md) | `.local-data/` 布局与复现路径 | |
| [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md) | IEEE 33-bus BESS 研究合同 | 哈希固定 |
| [RMB_MEASUREMENT_SPEC.md](RMB_MEASUREMENT_SPEC.md) | 人民币计量合同 | 哈希固定 |
| [RMB_BEHAVIOR_ANALYSIS.md](RMB_BEHAVIOR_ANALYSIS.md) | 恢复分母与行为分析口径 | 哈希固定 |
| [CLOUD_REVIEW_HANDOFF_ZH.md](CLOUD_REVIEW_HANDOFF_ZH.md) | 云端审阅入口（v2 阶段的研究问题） | |

### 为什么这些文件不能移动或编辑

“哈希固定”的 5 个文件被 `scripts/run_voltage_experiment_matrix.py` 按 `docs/<文件名>` 读取，其 SHA256 写入运行身份中的 `analysis_protocol_sha256`。移动或改动它们会使已有运行无法续跑，也会破坏冻结身份校验。**需要修改时，应作为有意的协议变更处理，并开新的运行目录。**

`V3_PILOT_PREREGISTRATION.md` 自预登记提交起同样入列，但只在 structure-v3 运行中读取（追加到 v3 的两个文档之后），其哈希同样写入 `analysis_protocol_sha256`；改动它会使 v3 运行无法续跑。

### 已知的失效相对链接（不修复，以免改变哈希）

`BENCHMARK_SPEC.md` 与 `RMB_MEASUREMENT_SPEC.md` 里写的是旧的同目录相对链接；对应文件现位于 `archive/v2/`：

`CNY_PILOT_PROGRESS`、`PILOT_PREFREEZE_REVIEW`、`EXPLICIT_REASONING_AND_FREEZE`、`V2_RESPONSES_SMOKE`、`CORPUS_V2_CANDIDATE`、`DEV_DIFFICULTY_AUDIT` → 均在 [archive/v2/](archive/v2/)。

## 归档（`archive/`，仅作历史证据，不代表当前状态）

### `archive/v2/`：v2 Dev Pilot 阶段

| 文件 | 内容 |
|---|---|
| CORPUS_V2_CANDIDATE | v2 候选集验收 |
| V2_RESPONSES_SMOKE | v2 Responses 8 条件 smoke |
| DEV_DIFFICULTY_AUDIT | Dev 难度审计（seed 2027） |
| DEV_PHYSICAL_DIFFICULTY_STUDY | Dev 动作空间诊断 |
| DEV_STRUCTURAL_COVERAGE | Dev 结构覆盖审查（促成路线 B） |
| DEV_PILOT_RESULT_ANALYSIS_ZH | Dev Pilot 结果分析 |
| CNY_PILOT_PROGRESS | 人民币低谷 Pilot 192/192 进度 |
| OUTPUT_LIMIT_16384_DIAGNOSTIC | 输出上限 16384 诊断 |
| EXPLICIT_REASONING_AND_FREEZE | 显式 reasoning 与冻结身份校验 |
| PILOT_PREFREEZE_REVIEW | Pilot 后、freeze 前审查 |

### `archive/plans/`：已被路线 B 取代的旧计划

- `voltage-benchmark-completion.md`：v2 时代自主执行计划
- `rmb-budget-and-trajectory-analysis.md`：人民币预算与失败轨迹分析计划

新的计划放在仓库根目录的 `plans/`。
