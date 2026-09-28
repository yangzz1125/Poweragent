# Dev Pilot 后 freeze 前审查：工程校验已补齐，正式冻结待批准

最新工程验收见 [EXPLICIT_REASONING_AND_FREEZE.md](EXPLICIT_REASONING_AND_FREEZE.md)：显式high/16384经独立Dev调用验证，完整冻结身份校验和场景配对交互CI已实现，92个离线测试通过。下文问题记录保留发生背景；供应商alias、筛选偏差及干净环境复现等限制仍需正式发布时确认。不创建tag、不启动Main。

## 已通过

- v2 Dev 全 24×8=192 个任务有唯一终态，与 run.json planned_tasks 一致；24个不同场景、全部条件、每格1次重复。
- 同一模型/API协议、prompt、物理约束及12/4/3工具预算；顺序由固定seed生成。测试集未运行。
- 985 HTTP请求都在低谷；已知费用Decimal与episode合计相等，五笔费用未知有明确的用户批准预留（合计¥1），总预算占用¥3.67079106，不隐瞒异常。
- 根commit/源码SHA与两次会计/网络重试策略迁移均有记录。完成项未重跑；旧记录不回填新source hash。
- 脱敏记录已可由GitHub外部agent读取，未发布隐藏Test/full/witness或密钥；导出内容提供SHA256，文本固定LF、PNG保留二进制以保证Windows/Linux一致。
- 保存 `environment.txt` 作为本地环境快照，但它不等于已经在干净环境中复现通过的正式lockfile。

## 输出预算更新（Pilot 后，未重跑）

按用户要求，电压实验 runner 的新运行默认 `--max-output-tokens 16384`，显式传给 Responses/Chat 客户端并记录到 run.json / episodes.csv；单条件 runner 同步。修改此值拒绝续写同一 run。共享客户端用于其他轨道的原默认值不改。原192条Pilot仍对应4096，不回填或覆盖。之后在D0015/I1-V0-R1完成一次独立Dev复测：5轮、2次提交后成功，花费¥0.01200310；5次provider状态均为completed，无截断，单轮最大输出987（小于原4096），所以不能把成功归因于扩容。账本已增加provider完成状态/截断原因，见 [诊断记录](OUTPUT_LIMIT_16384_DIAGNOSTIC.md)。人民币单局/campaign与工具预算不变。

## Main 前的阻塞

1. **输出上限导致的潜在截断需要在Dev澄清。** 唯一R1失败D0015/I1-V0-R1在第3、5–11轮的output_tokens恰好都是4096，visible_text为空，随后被标记parse_error；当前客户端max_output_tokens默认4096。这与输出上限耗尽一致，不能简单归因为“模型不会JSON”。日志未持久化provider status/incomplete_details和显式thinking参数，尚不能确认内部原因；先补这类元数据，并在单独Dev诊断协议中验证，不能改完后无声并入这192条。
2. **模型/推理参数未完整冻结。** 目前记录alias deepseek-flash，但供应商可滚动更新；应记录返回版本（若提供）、采样参数是否生效、thinking/reasoning设置、max_output_tokens、结构化输出模式和重试协议。Responses不代表原生function-call loop。
3. **freeze gate已补齐工程检查。** runner现在核对完整源码/环境/模型/价格/分析规则/任务清单，并要求显式批准、Main授权、匹配tag和干净源码。旧3-hash检查已淘汰；candidate不会授权Test。尚未建benchmark-v1.0 tag。
4. **数据难度与筛选偏差。** verification开启的96个Dev episode全部成功；witness搜索又与sensitivity baseline同类，因此不能宣称广泛困难分布。不得按Test表现或为压低baseline而改场景。需要在预登记研究问题下解释这一覆盖范围。
5. **统计可估计性。** 多个condition全成功，logistic完全/近完全分离；table4正确报告不可估计。配对绝对成功差异和场景聚类CI可用于Dev诊断，但不是主论文Test结果；已新增场景配对IV/IR/VR差中差及IVR三重差的bootstrap CI，logit不可估计仍如实报告，不能捏造p值。
6. **开发中会计/重试政策迁移。** 旧阶段手动暂停，后阶段自动预留及有限ConnectionError重试，latency/transport比较可能混杂。所有历史保留为开发数据；正式Main应从头使用一份冻结政策的新run。

## 交付范围

第9步Pilot完成；第10步冻结前工程审查已补齐检查与测试，正式freeze文件批准/tag和Main预算仍是独立授权步骤。云端分析agent可使用 `research_records/voltage_control/cny_pilot_192/` 独立检视，不必再次调用模型。没有执行2304次Test、跨模型、额外付费预算扫描或作论文最终结论。后续仍受原¥10 campaign额度约束，Main须单独授权。
