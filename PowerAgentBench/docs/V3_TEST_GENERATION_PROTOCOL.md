# v3 Test 生成协议（预先声明）

> 编制：2026-10-02，**在运行任何 Test 候选扫描之前**提交。本文是数据构造规则，不是模型实验；整个过程不调用任何模型 API。
> 上位计划：[ROUTE_B_PLAN.md](ROUTE_B_PLAN.md) 第 6.1、10.4 节。Dev 的生成协议见 [V3_GENERATION_PROTOCOL.md](V3_GENERATION_PROTOCOL.md)（哈希固定，不改）。
> 本文在 Test 冻结时将和其他协议文档一起纳入哈希；在此之前改动须在提交说明中写明原因。

## 1. 目标

构造 96 个 sealed Test 场景：S1、S2、S3、S4 各 24 个，独立于 Dev 的 32 个场景。后续 Main 计划为 96 × 8 条件 × 3 次重复 = 2304 局（见 ROUTE_B_PLAN 10.4）。

## 2. 为什么要先做可行性扫描

Dev 阶段扫描了 1024 个候选，通过认证的 S1/S2/S3/S4 分别是 379/54/47/11 个。S4 的出产率约 1%，且 Dev 已用掉 8 个。所以 24 个独立 S4 能不能凑够是未知的，不能先承诺。

## 3. 固定的规则

- **独立 seed：2041**（Dev 为 2031）。候选由 `(seed, index)` 确定，使用与 Dev 相同的四个 recipe（A/B/C/D）、同样的包络、同样的初始接受条件和同样的结构认证模板与 witness 搜索。**不改认证标准。**
- **与 Dev 的隔离：** 候选如果与 Dev 已选的 32 个场景满足以下任一条，就被排除：相同 `operating_family_id`、相同物理指纹、近重复（与 Dev 相同的 `near_duplicate` 判据）。
- **选择规则：** 与 Dev 相同。在每个结构类别内，按 seed 固定的哈希优先级，按方向和空间 family 轮转；每个 `operating_family_id` 只选一个；近重复的拒绝。**不使用任何模型得分。**
- **规模：** 每类目标 24 个。S4 必须来自至少 2 个不同空间 family，否则标记结构覆盖不足。
- **扫描范围：** 候选索引 0–3071，分 6 轮，每轮 512 个；每轮单轮 PF 上限 250000，全量网格扫描名额同 Dev（每轮 2 个）。每轮结束后检查：四类可选数量都 ≥ 24 且 S4 覆盖 ≥ 2 个空间 family，就停止扫描。
- **不足时的处理（预先固定）：** 扫满 6 轮后仍有类别不足 24，则**如实报告缺口**。**不放宽**认证标准、family 去重、近重复阈值、recipe 包络，**不重复使用同一母样本**，**不用重复场景凑数**。是否改为每类更少的配额，或继续扩大扫描范围，须由用户作为新的、记录在案的决定。
- **场景 ID：** 通过 seed 固定的哈希顺序给出不透明 ID `T0001…T0096`；结构类别、witness、模板计数只放在评价器私有目录。公开文件和提示里不出现。

## 4. 输出位置与保密

- 输出在 `.local-data/voltage_structure_v3_test/`（Git 忽略，需要 U 盘拷贝），与 Dev 的 `.local-data/voltage_structure_v3/` 分开。其中的 `evaluator_private/` 永远不得发布。
- 构造过程会运行评价器来认证 witness，这是数据构造，不是运行模型 Test；不产生任何模型得分。

## 5. 不做的事

- 不调用模型，不产生费用。
- 不批准 freeze，不打 tag，不授权 Main（`main_authorized` 保持 false）。
- 不覆盖或修改 Dev、v2 Test 和任何已有结果。

## 6. 命令（供复现）

```text
python -m scripts.generate_voltage_structural_test --mode scout     --output-dir ../.local-data/voltage_structure_v3_test
python -m scripts.generate_voltage_structural_test --mode build-test --output-dir ../.local-data/voltage_structure_v3_test
```

`scout` 只扫描、认证、选择并报告可选数量；`build-test` 只在四类都足额时才构建 `test/manifest.json`，否则拒绝并报告缺口。
