# 三层错因总览
# 方法说明
- 说明：L1 表示表层错误，L2 表示过程阶段错误原因，L3 表示根能力项原因。
- 仅对可归因失败样本统计三层错因分布。

# L1 表层错误分布
| 主类 | 计数 |
| --- | --- |
| 输出缺失/截断 | 1 |
| 语法/解析错误 | 1 |
| 接口/类型/符号错误 | 1 |
| 环境/评测错配 | 1 |

# L2 过程阶段错误原因分布
| 主类 | 计数 |
| --- | --- |
| 代码实现与局部逻辑 | 2 |
| 仓库上下文/接口对齐 | 1 |
| 验证、调试与自修复 | 1 |

# L3 根能力项原因分布
| 主类 | 计数 |
| --- | --- |
| 任务分解与求解规划 | 1 |
| 状态、控制流与不变量维护 | 1 |
| 输入输出契约建模 | 1 |
| 测试验证、反思与调试能力 | 1 |

# 主类到细类拆解
| 层级 | 主类 | 细类 | 计数 |
| --- | --- | --- | --- |
| L1 | 输出缺失/截断 | missing_code | 1 |
| L1 | 语法/解析错误 | syntax_error | 1 |
| L1 | 接口/类型/符号错误 | signature_mismatch | 1 |
| L1 | 环境/评测错配 | suspicious_eval_mismatch | 1 |
| L2 | 代码实现与局部逻辑 | incomplete_solution_delivery | 1 |
| L2 | 代码实现与局部逻辑 | code_synthesis_breakage | 1 |
| L2 | 仓库上下文/接口对齐 | api_contract_mismatch | 1 |
| L2 | 验证、调试与自修复 | evaluation_validation_gap | 1 |
| L3 | 任务分解与求解规划 | incomplete_solution_plan | 1 |
| L3 | 状态、控制流与不变量维护 | syntactic_consistency_gap | 1 |
| L3 | 输入输出契约建模 | signature_mismatch | 1 |
| L3 | 测试验证、反思与调试能力 | validation_feedback_gap | 1 |

# 根因与三层错因交叉映射
| 层级 | 主类 | root_cause | 计数 |
| --- | --- | --- | --- |
| L1 | 输出缺失/截断 | 解答不完整或被截断 (incomplete_or_truncated_solution) | 1 |
| L1 | 语法/解析错误 | 实现缺陷 (implementation_bug) | 1 |
| L1 | 接口/类型/符号错误 | 解答逻辑错误 (solution_incorrect) | 1 |
| L1 | 环境/评测错配 | 可能是评测不一致 (possible_evaluation_mismatch) | 1 |
| L2 | 代码实现与局部逻辑 | 解答不完整或被截断 (incomplete_or_truncated_solution) | 1 |
| L2 | 代码实现与局部逻辑 | 实现缺陷 (implementation_bug) | 1 |
| L2 | 仓库上下文/接口对齐 | 解答逻辑错误 (solution_incorrect) | 1 |
| L2 | 验证、调试与自修复 | 可能是评测不一致 (possible_evaluation_mismatch) | 1 |
| L3 | 任务分解与求解规划 | 解答不完整或被截断 (incomplete_or_truncated_solution) | 1 |
| L3 | 状态、控制流与不变量维护 | 实现缺陷 (implementation_bug) | 1 |
| L3 | 输入输出契约建模 | 解答逻辑错误 (solution_incorrect) | 1 |
| L3 | 测试验证、反思与调试能力 | 可能是评测不一致 (possible_evaluation_mismatch) | 1 |

# 失败样本逐题明细
| Case ID | Root Cause | L1 | L2 | L3 | 关键证据 | 解释来源 |
| --- | --- | --- | --- | --- | --- | --- |
| 101 | 解答不完整或被截断 (incomplete_or_truncated_solution) | 输出缺失/截断 / missing_code | 代码实现与局部逻辑 / incomplete_solution_delivery | 任务分解与求解规划 / incomplete_solution_plan | signature_mismatch；entrypoint_mismatch；api_mismatch；missing_code；completion code missing | deterministic_plus_llm |
| 102 | 实现缺陷 (implementation_bug) | 语法/解析错误 / syntax_error | 代码实现与局部逻辑 / code_synthesis_breakage | 状态、控制流与不变量维护 / syntactic_consistency_gap | compile_error；syntax_error；expected ':' (line 1) | deterministic_only |
| 103 | 解答逻辑错误 (solution_incorrect) | 接口/类型/符号错误 / signature_mismatch | 仓库上下文/接口对齐 / api_contract_mismatch | 输入输出契约建模 / signature_mismatch | test_failure；logic_mismatch；api_mismatch；signature_mismatch；entrypoint_mismatch；mismatch | deterministic_only |
| 104 | 可能是评测不一致 (possible_evaluation_mismatch) | 环境/评测错配 / suspicious_eval_mismatch | 验证、调试与自修复 / evaluation_validation_gap | 测试验证、反思与调试能力 / validation_feedback_gap | suspicious_eval_mismatch；parse=parsed, signature=ok, entrypoint=ok, api=ok | deterministic_plus_llm |

# 待人工复核样本
| Case ID | 复核原因 |
| --- | --- |
| 104 | unspecified |