# 显式 reasoning 与冻结身份校验验收

## 模型参数依据

官方文档：
- https://api-docs.deepseek.com/guides/responses_api/
- https://api-docs.deepseek.com/guides/thinking_mode

当前 Responses 支持 reasoning.effort=none/low/high/max；none关闭思考，默认high。思考模式下temperature不生效。因此本项目不能再把“请求temperature=0”描述为有效的确定性保证。

电压runner现将DeepSeek官方Responses默认effort显式设为high，可用 `--reasoning-effort` 指定；Chat/Ollama不支持这一路参数时拒绝显式设置，避免静默忽略。请求构造和运行元数据共用 `model_request_settings()`，记录实际URL哈希、effort、temperature_policy、max_output_tokens、结构化输出模式、timeout、重试次数和退避。

## 独立Dev验证

run `756e2751-e1a5-448a-a495-f6e4134b5e51`，D0015/I1-V0-R1，显式high + 16384。5轮、2次submit后成功；5个响应全部completed，output_tokens为127、82、260、301、1408，无截断。费用估算¥0.01251810。仍只能说明参数和执行链可用，不建立输出上限改善成功率的因果结论，不合并入原192条Pilot。

整个campaign已知¥2.69531226，未知费用预留¥1.00，总占用¥3.69531226/¥10；未新增未知请求，全部低谷。模型返回alias仍为deepseek-flash，**不能获得不可变的供应商模型修订号**，这是可复现性的外部限制。

## 冻结前工程校验

- `voltage_freeze.py`定义逐字段合同，涵盖数据及split manifest、prompt/config/conditions、根commit/源码SHA、完整Python环境身份、实际模型设置、8条件×场景×重复任务清单、物理/输出预算、价格SHA、会计政策、分析协议SHA。
- 环境快照记录Python/平台/全部已安装distribution版本，不包含本地editable路径或凭据。它是复现资料，不是干净环境复现已通过的声明。
- 实际Test启动要求freeze.status=approved、main_authorized=true、完整合同digest和所有字段匹配、benchmark-v1.0 tag指向当前commit，以及相关源码/config/prompt/协议文件干净且已提交。旧的仅3个hash的manifest不能绕过。
- `--write-freeze-candidate`只能与 `--dry-run` 一起使用，并要求完整96×8×3 Test任务集；只校验artifact hash，不调用LLM/PF。输出status=candidate、main_authorized=false，不创建tag、不授权收费。
- 对每个合同字段的变更有拒绝测试；candidate不能自动变成approved；截断日志、条件选择和客户端参数有回归。
- 全部离线测试：**92 passed**。Test dry-run列出2304任务、explicit high、16384输出上限、thinking温度无效策略和环境SHA；没有Test执行。

## 分析规则补齐

新增 `factorial_rate_contrasts.csv`：场景配对的I/V/R绝对成功率差异、IV/IR/VR差中差、IVR三重差，按scenario bootstrap 95% CI。只使用八条件齐全的场景，并报告未配对剔除数；单场景不给伪确定性CI。原logit在完全/近完全分离时仍报告不可估计，不用大系数或假p值掩盖。

这些是观测样本的描述统计/配对比较，不能把Dev调参结果当Test结论；也不能将条件不同的首次失败人群对比视为恢复机制因果效果。v2的可行性搜索筛选偏差、severity不等于控制难度等限制保留。

## 发布与正式Main边界

本轮完成的是**模型参数显式化和冻结前工程审查**。正式benchmark-v1.0尚未签发、Main未授权；候选协议须人工审核、另行确认预算后才能批准。正式冻结前应在干净环境核对依赖快照，并认可供应商alias可漂移等研究限制。不得改写旧Pilot的4096/provider_default记录，或继续旧run混入新设置。
