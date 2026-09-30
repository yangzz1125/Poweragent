# 项目本地数据布局与迁移记录

数据统一归属项目，私有数据不进Git。被测托管Agent只能收到现有工具的白名单输出；`.gitignore`本身不是沙箱。未来有shell/文件权限的Agent必须另行隔离。

```text
power_agent/
  .local-data/
    voltage_corpus_v1/
    voltage_corpus_v2_candidate/
    voltage_structure_v3/
    MIGRATION_FROM_WORK.json
  .local-archive/
    legacy_dev_diagnostics/
    v3_auxiliary/
    MOVE_MANIFEST.json
  PowerAgentBench/results/       # 原run/费用账本保留，已Git忽略
  research_records/             # 允许公开的脱敏历史快照
```

## 迁移与完整性

| 原目录 | 当前目录（相对项目根） | 文件数 |
|---|---|---:|
| `E:/work/voltage_corpus_v1` | `.local-data/voltage_corpus_v1` | 244 |
| `E:/work/voltage_corpus_v2_candidate` | `.local-data/voltage_corpus_v2_candidate` | 246 |
| `E:/work/voltage_structure_v3` | `.local-data/voltage_structure_v3` | 4796 |
| `E:/work/power_agent_research_archive` | `.local-archive` | 399 |

迁移了5685个文件、972045620字节；同盘重命名后逐文件核对SHA256和大小，全部一致，无实验数据删除。移动前确认没有Python实验进程运行。详细逐文件记录在`.local-data/MIGRATION_FROM_WORK.json`。

旧辅助记录先归档再迁移的路径链，由`.local-archive/MOVE_MANIFEST.json`和上述新迁移清单共同解释。旧协议、数据manifest、源快照、实验日志和公开记录不回写，历史文档中的旧路径通过此表定位。

v3数据集SHA仍为`8a84bc05bc5d98469158cbdf8e49bcc5e0c20c6bd029ff942331f8e840c900cd`。

## 代码兼容

生成入口只允许仓库外目录，或项目根`.local-data/`下的子目录，继续拒绝普通源码/公开目录。原生成算法、物理定义和模型观察未变。

路径检查修改会改变生成脚本源哈希，不能拿新脚本重写旧协议来伪造同一身份。已经完成的v3通过`run_voltage_route_b`直接进入原数据的基线与证据校验，不重新调用旧生成过程。若恢复尚未完成的历史生成，需要原始源码/环境；不要绕过身份检查。

## 当前命令

从`PowerAgentBench/`运行：

```bash
# 已完成v3的缓存校验；迁移后实测新增PF=0。
./.venv/Scripts/python.exe -m scripts.run_voltage_route_b --output-dir ../.local-data/voltage_structure_v3

# 仅核对Dev任务矩阵：256个planned tasks，不调用模型。
./.venv/Scripts/python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root ../.local-data/voltage_structure_v3/dev --output-dir results/voltage_control/v3_migrated_dry_run --dry-run

# 真正重新执行物理测试会增加PF，不是零成本缓存校验。
./.venv/Scripts/python.exe -m pytest -q tests --v3-root ../.local-data/voltage_structure_v3 --offline-pf-report ../.local-data/v3_recheck_tests.json
```

## 迁移后检查

- 路径策略、已完成数据跳过生成、结构/基线/隔离相关测试：14 passed，15次实际测试PF，网络连接尝试0。
- v3校验：PASS；三账本仍为253122、419、4225，共257766 PF，无新增数据流程PF。
- Dev dry-run：256任务，数据集SHA不变。
- 原8局收费smoke仍未执行。旧preflight协议保留；另存迁移后的dry-run命令，不执行旧绝对路径命令。
- 无收费API、无正式Test、无freeze/tag、无push。用户方案、`templates/`及其他work项目未动。
