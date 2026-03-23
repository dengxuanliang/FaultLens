# 评测日志错误归因 Agent 设计文档

- **日期**: 2026-03-23
- **项目**: FaultLens
- **形态**: CLI Agent（非平台）
- **目标用户**: 评测/质量团队为主，Prompt/算法工程师为辅

## 1. 背景与目标

本项目要实现的是一个**针对 LLM/Agent 评测日志进行错误项分析的归因 Agent**，而不是一个评测平台或可视化系统。第一阶段聚焦于**离线批处理**：给定评测日志文件，Agent 自动完成样本合并、失败样本识别、证据抽取、错误归因、批量汇总，并输出结构化结果与报告。

该 Agent 的核心目标不是“判断是否通过”，而是回答以下问题：

1. 失败样本主要属于哪一类错误？
2. 做出该判断的直接证据是什么？
3. 这些错误在一批评测任务中如何分布？
4. 哪些错误模式最值得质量团队优先关注？

## 2. 一期范围（V1）

### 2.1 包含内容

- 读取两个 JSONL 文件：`inference-output` 与 `results`
- 使用 `inference-output.id == results.task_id` 做一一对齐
- 统一为内部标准样本对象
- 基于 `accepted` 识别通过/失败样本
- 对失败样本生成单条归因结果
- 对整批样本生成统计汇总与 Markdown 报告
- 输出 JSONL 明细和 Markdown 汇总

### 2.2 暂不包含

- Web 平台 / 后台服务 / 多用户系统
- 实时分析与在线监控
- 自动修复代码或自动回写评测系统
- 复杂知识库 / RAG / 历史案例检索
- 多 Agent 协同决策闭环

## 3. 输入数据约定

V1 明确支持两个 JSONL 文件。

### 3.1 inference-output

每条记录至少包含以下语义字段：

- `id`: 题目标识，用于 join
- `content`: 题目内容
- `canonical_solution`: 标准代码解答，供参考
- `completion`: 大模型回复，包含必要解释和生成的代码

已知可选字段：

- `labels.programming_language`
- `labels.execution_language`
- `labels.category`
- `labels.difficulty`
- `labels.fewshot`
- `labels.locale`
- `test.code`

> 说明：当前已确认真实字段名是 `canonical_solution`，不是 `canonical solution`。

### 3.2 results

每条记录至少包含以下语义字段：

- `task_id`: 与 `inference-output.id` 一一对应
- `accepted`: 布尔值，`true` 为通过，`false` 为失败

已知可选字段：

- `passed_at_1`
- `pass_at_k`
- `all_k_correct`
- `n`
- `natural_language`
- `programming_language`
- `category`
- `difficulty`

### 3.3 关联规则

- 主关联键：`inference-output.id == results.task_id`
- 默认假设：两文件一一对应
- 但实现上必须显式处理以下异常：
  - 某侧缺失记录
  - 关联键重复
  - 关联键类型不一致（字符串/整数）
  - 同一 join key 多条候选记录

## 4. 设计备选方案

### 方案 A：规则优先

使用字段解析、字符串模式匹配和少量启发式规则完成归因。

- **优点**: 实现快、成本低、结果稳定
- **缺点**: 面对复杂失败模式时归因过于僵硬，难以覆盖开放场景

### 方案 B：LLM 归因优先

将单条失败样本完整上下文直接交给模型，让模型生成原因与解释。

- **优点**: 上手快，适合开放式归因
- **缺点**: 一致性、可复现性、批量统计稳定性较弱

### 方案 C：混合式归因流水线（推荐）

先以代码完成数据接入、标准化、失败检测与证据抽取，再由 LLM 执行最终归因，最后做结构化汇总。

- **优点**: 可解释性、扩展性、批量稳定性更好
- **缺点**: 比纯规则或纯 LLM 多一层工程设计

**结论**: V1 采用方案 C。即：**代码负责流程与结构化处理，LLM 负责归因判断与解释生成。**

## 5. 总体架构

Agent 采用单进程 CLI 形态，内部按流水线工作：

1. **Load**：读取两个 JSONL 文件
2. **Join**：按 `inference-output.id / results.task_id` 合并记录
3. **Normalize**：标准化为统一 Case 结构
4. **Detect**：识别失败样本
5. **Extract**：提取归因证据
6. **Attribute**：调用 LLM 生成归因结果
7. **Aggregate**：聚合整批错误模式
8. **Report**：输出 JSONL 与 Markdown 报告

### 5.1 架构原则

- Agent 优先，不做平台耦合设计
- 单条分析与批量分析复用同一套核心模块
- 输入/输出尽量结构化，减少隐式状态
- 明确区分“日志中可观察事实”与“模型推断出的原因”
- 所有批量统计都基于结构化归因结果，而不是基于自由文本

## 6. 核心模块设计

### 6.1 Input Adapter

职责：

- 读取 `inference-output.jsonl` 与 `results.jsonl`
- 校验基础字段存在性
- 提供字段名映射与容错
- 对 JSONL 格式错误、空行、编码异常做基础处理

输出：原始记录流

### 6.2 Joiner / Case Normalizer

职责：

- 使用 `inference-output.id / results.task_id` 合并两侧记录
- 标准化字段命名
- 统一类型（例如将 `id` / `task_id` 统一为字符串）
- 保留原始输入，生成可审计的内部 `CaseRecord`

推荐的 `CaseRecord` 字段：

**记录标识**
- `case_id`
- `join_status`

**原始数据保留**
- `raw.inference_output`
- `raw.results`

**来源与关联元信息**
- `source.inference_id_raw`
- `source.results_task_id_raw`
- `source.inference_line_number`
- `source.results_line_number`

**标准化后的任务载荷**
- `task.content_text`
- `reference.code_text`
- `reference.test_code_text`
- `completion.raw_text`
- `evaluation.accepted`
- `evaluation.pass_metrics`
- `metadata.inference_labels`
- `metadata.results_tags`
- `metadata.slice_fields`

**completion 分解结果**
- `completion.explanation_text`
- `completion.code_blocks`
- `completion.primary_code_text`
- `completion.primary_code_language`
- `completion.parse_status`

**诊断与派生字段**
- `normalization.warnings`
- `normalization.errors`
- `normalization.version`
- `case_status`
- `is_failure`
- `completion_has_code`
- `reference_has_code`
- `content_length`
- `completion_length`
- `join_anomaly_flags`

设计要求：

- 采用**保留原始输入的标准化包络结构**，而不是只保留扁平字段
- 下游模块默认消费标准化字段，但在报告与调试中可回溯原始记录
- 任何 join/解析问题都必须通过显式 warning/error 暴露，而不能静默吞掉
- `canonical_solution` 是重要参考证据，但在结构上应视为**可选 reference evidence**，不能假设它永远存在且绝对正确
- `test.code` 作为评测 harness / 测试上下文证据单独保留，不能混入普通 metadata
- `metadata.inference_labels` 原样保留 `labels` 对象
- `metadata.results_tags` 原样保留 results 中的语言、类别、难度等顶层标签
- `evaluation.pass_metrics` 保留 `passed_at_1`、`pass_at_k`、`all_k_correct`、`n`
- `metadata.slice_fields` 是由 `labels` 和 `results` 元数据派生出的统一切片视图；未配置时不做对应切片统计
- 若 `labels.*` 与 `results` 顶层标签字段冲突，必须生成 normalization warning，而不是静默覆盖

### 6.2.1 Join 规则与确定性策略

- `0:1` 或 `1:0`：生成一条 `case_status = join_issue` 的记录，写入 `case_analysis.jsonl`，但**不进入根因分布统计**
- `1:1`：正常合并
- `N:1`、`1:N`、`N:N`：生成 `case_status = join_issue`，记录重复键与候选数，**不做猜测性合并**
- 键类型不一致时先将 `inference-output.id` 与 `results.task_id` 统一为字符串再比较；统一后仍冲突则按重复键处理
- Join 成功率、join_issue 数量、重复键数量必须进入汇总报告

### 6.3 Failure Detector

职责：

- 以 `accepted == false` 作为失败主判据
- 标记失败样本并生成轻量 hint
- 识别数据异常类失败（如 completion 缺失、代码块缺失）
- 交叉检查 `accepted` 与 `passed_at_1` / `pass_at_k` / `all_k_correct` 是否一致

输出：
- `is_failure`
- `failure_gate_reason`
- `data_quality_flags`
- `case_status`

`case_status` 的推荐枚举：

- `passed`
- `attributable_failure`
- `data_issue`
- `join_issue`

说明：

- 只有 `accepted == false` 且基础数据可归因的样本，才标记为 `attributable_failure`
- 缺失 completion、严重解析失败等情况标记为 `data_issue`
- 缺失 `canonical_solution` 不必然是 `data_issue`；若仍有 `content + completion + test.code + accepted`，允许进入保守归因
- `join_issue` 和 `data_issue` 会出现在运行报告中，但不计入 root-cause 分布分母
- 若 `accepted` 与辅助通过率字段明显冲突，应生成 warning，并优先考虑 `possible_evaluation_mismatch`

### 6.4 Evidence Extractor

职责：

- 从 `task.content_text`、`reference.code_text`、`reference.test_code_text`、`completion.raw_text` 中抽取归因证据
- 尽量减少送入 LLM 的无关文本，压缩上下文
- 为报告保留“可直接引用的证据片段”

V1 建议抽取的证据原语：

- 题目摘要
- 参考解摘要
- 测试代码 / harness 摘要
- 模型回答摘要
- completion 分段结果（解释段 / 代码段）
- 模型是否产出代码
- 提取出的全部代码块
- 主代码候选 `primary_code_text`
- 代码语言识别结果
- 代码可解析性 / 语法探测结果
- 关键结构符号抽取（函数名、类名、签名、imports）
- test.code 中的目标接口/入口点/断言摘要
- completion 中解释与代码是否冲突
- 参考解与模型代码的高层差异提示（仅做表层结构差异，不做重语义判对）
- completion 与 test.code 的接口适配性提示
- 可回指原文的 evidence anchors（片段或偏移）
- 归因子信号（如 `missing_code`、`multiple_code_blocks`、`syntax_error`、`signature_mismatch`）
- metadata 不一致信号（如 inference labels 与 results tags 冲突）
- 明显的数据质量问题（空回答、无代码块、截断、异常格式）

### 6.5 Attribution Agent

职责：

- 读取 `CaseRecord` 与 `EvidenceBundle`
- 输出结构化归因结果，而不是仅输出自然语言评论
- 明确分离：
  - **observable_evidence**：日志中直接可见的事实
  - **inferred_root_cause**：基于事实做出的原因判断

建议输出字段：

- `case_status`
- `accepted`
- `root_cause`
- `secondary_cause`
- `attribution_signals`
- `case_signals`
- `confidence`
- `observable_evidence`
- `evidence_refs`
- `explanation`
- `needs_human_review`
- `review_reason`

输出约束：

- `observable_evidence` 只允许记录日志中直接可见的事实
- `evidence_refs` 必须指向原始字段、代码块编号、片段或偏移锚点
- `explanation` 必须明确“基于这些事实，推断出的原因是什么”
- 当评估侧异常更可能时，应优先输出 `possible_evaluation_mismatch`

统一输出约束：

- 所有行都输出统一 schema
- 当 `case_status = attributable_failure` 时：
  - `accepted = false`
  - `root_cause` 必填
  - `confidence` 必填
  - `observable_evidence` 至少 1 条
  - `evidence_refs` 至少 1 条
- 当 `case_status = passed | data_issue | join_issue` 时：
  - `accepted = true | false | null`，其中 `join_issue` 且无法可靠拿到评测标签时为 `null`
  - `root_cause = null`
  - `secondary_cause = null`
  - `attribution_signals = []`
  - `case_signals` 记录非归因类状态信号
  - `confidence = null`
  - `observable_evidence` 仅记录状态说明或数据问题事实
  - `evidence_refs` 可为空
  - `explanation` 仅描述为何该样本未进入归因

### 6.6 Batch Aggregator

职责：

- 汇总失败样本数与错误类别分布
- 统计按任务、标签或语言维度的切片分布（若元数据存在）
- 发现高频重复失败模式

输出：
- 错误类型计数
- Top recurring patterns
- 关键切片对比
- 评测元数据一致性告警
- 需要人工优先复核的样本列表

### 6.7 Report Generator

职责：

- 生成 `case_analysis.jsonl`
- 生成 `summary_report.md`
- 保持报告面向质量团队可读，同时为工程师保留单例证据

## 7. 错误归因分类体系（V1）

V1 使用可解释、可统计的实用型 taxonomy，避免过早细化。

### 7.1 一级分类

V1 要求：

- **必须输出且仅输出 1 个 primary attribution**
- **最多输出 1 个 secondary attribution**
- 优先保守归因；证据不足时使用 `insufficient_evidence`

推荐一级分类：

1. `task_misunderstanding`
   - 解错题、忽略核心要求、未满足题面目标
2. `contract_or_interface_violation`
   - 函数签名、类名、输入输出协议、返回格式不符合要求
3. `incomplete_or_truncated_solution`
   - 只给部分代码、回答中断、明显 unfinished
4. `non_executable_code`
   - 语法错误或结构上不可执行
5. `solution_incorrect`
   - 解决方案看起来不正确，但仅凭现有证据无法再细分为算法错误、实现 bug 或边界条件缺失
6. `environment_or_api_mismatch`
   - 使用错误运行时假设、不可用库或虚构 API
7. `possible_evaluation_mismatch`
   - 怀疑标签、评测 harness 或参考解存在问题
8. `insufficient_evidence`
    - 信息不足，无法稳定归因

### 7.2 设计说明

- 此 taxonomy 适合当前已知字段：`content`、`canonical_solution`、`test.code`、`completion`、`accepted` 及相关 labels/评测元数据
- `labels`、`test.code` 和 results 侧元数据应优先用于加强 contract / harness / metadata mismatch 判断
- 不提前引入工具调用、执行栈、judge comment 等更复杂类别
- `canonical_solution` 的差异只能作为佐证，不能单独当成归因证明
- 不可把隐藏测试行为当成“观察到的证据”
- `solution_incorrect` 是当前证据条件下的保守汇总类，后续接入更多执行信号后再拆细
- 若后续接入编译错误、测试输出、执行 trace，再扩展更细粒度分类

### 7.3 Attribution Signals（V1 受控词表）

`attribution_signals` 是辅助聚合与审计的结构化子信号；V1 只允许输出以下受控值：

- `missing_code`
- `multiple_code_blocks`
- `syntax_error`
- `signature_mismatch`
- `output_protocol_mismatch`
- `unfinished_output`
- `explanation_code_conflict`
- `logic_mismatch`
- `api_mismatch`
- `suspicious_eval_mismatch`
- `metadata_conflict`

规则：

- 仅允许输出该词表中的值
- 词表版本随 `taxonomy.yaml` 版本管理
- 批量 recurring patterns 统一按 `root_cause + sorted(attribution_signals)` 聚合

### 7.4 Case Signals（非归因状态信号）

`case_signals` 用于承载 `data_issue` / `join_issue` 等非归因类状态，不进入 root-cause 聚合。V1 受控值：

- `missing_reference`
- `missing_completion`
- `bad_jsonl_line`
- `duplicate_join_key`
- `join_conflict`
- `unmatched_inference_record`
- `unmatched_result_record`

## 8. 单条样本输出设计

单条归因结果建议采用如下结构：

```json
{
  "case_id": "task-001",
  "case_status": "attributable_failure",
  "accepted": false,
  "root_cause": "solution_incorrect",
  "secondary_cause": "contract_or_interface_violation",
  "attribution_signals": ["logic_mismatch", "explanation_code_conflict"],
  "case_signals": [],
  "confidence": 0.79,
  "observable_evidence": [
    "completion 包含代码块，但核心逻辑与 canonical solution 的关键步骤不一致",
    "completion 文本解释称使用双指针，但代码未体现相应更新逻辑"
  ],
  "evidence_refs": [
    {"source": "completion.code_blocks[0]", "anchor": "block-0"},
    {"source": "completion.explanation_text", "anchor": "span-12-46"}
  ],
  "explanation": "样本失败的主因更接近 solution_incorrect。模型给出了完整代码，但关键逻辑没有实现题目所需策略。",
  "needs_human_review": false,
  "review_reason": null
}
```

## 9. 批量报告设计

面向评测/质量团队，V1 报告建议至少包含以下部分：

1. **总体概览**
   - 总样本数、通过数、可归因失败数、数据问题数、关联问题数
2. **错误类型分布**
   - 仅基于 `case_status = attributable_failure` 统计各一级分类的数量和占比
3. **归因覆盖与复核队列**
   - 低置信度样本数、需人工复核样本数、`insufficient_evidence` 占比
4. **重点失败模式**
   - 基于结构化字段聚合：`root_cause + attribution_signals`
5. **数据质量告警**
   - 缺失 completion、无代码块、关联失败等异常
6. **热点切片**
   - 按 `programming_language`、`execution_language`、`category`、`difficulty`、`fewshot`、`locale`、`natural_language` 等 `metadata.slice_fields` 切分
7. **附录：典型样本**
   - 每类展示 1~3 个代表性 case

## 10. 置信度与人工复核规则

V1 不将置信度视为统计学概率，而视为**归因稳定度评分**。

建议策略：

- `confidence >= 0.8`：证据较充分，可直接纳入汇总
- `0.5 <= confidence < 0.8`：可纳入汇总，但建议抽样复核
- `confidence < 0.5`：标记 `needs_human_review = true`

以下情形直接触发人工复核：

- completion 为空或无法提取代码
- canonical_solution 缺失
- `accepted=false` 但 completion 看起来与参考解高度一致
- 样本同时满足多个强竞争归因，无法稳定排序
- 关联或解析过程中出现严重告警
- 命中 `possible_evaluation_mismatch`
- explanation 与代码表现强冲突

## 11. 错误处理与健壮性要求

### 11.1 输入层
- JSONL 单行解析失败时记录错误并继续处理其他样本
- 缺失关键字段时将样本标记为数据异常，而不是直接中止整批执行

### 11.2 关联层
- 对无法关联的样本输出 warning 列表
- 汇总报告中必须展示 join 成功率与异常统计

### 11.3 归因层
- LLM 返回非结构化结果时需要二次解析/回退
- 无法稳定归因时回退到 `insufficient_evidence`

### 11.4 输出层
- 即使存在部分坏样本，也应尽量产出整体报告
- 保留错误清单，便于后续修复数据管线

## 12. 测试策略

V1 至少覆盖以下测试层次：

1. **适配层测试**
   - 正常读取 JSONL
   - 空行/坏行/缺字段处理
2. **关联层测试**
   - 成功 join
   - 缺失/重复/类型不一致
3. **标准化测试**
   - 不同字段命名映射到统一结构
4. **证据提取测试**
   - 从 completion 中提取代码块
   - 检测空回答与截断
5. **归因输出契约测试**
   - LLM 输出必须满足结构化 schema
6. **聚合与报告测试**
   - 分类统计正确
   - Markdown 报告关键段落完整

## 13. 建议目录结构

```text
FaultLens/
├─ pyproject.toml
├─ README.md
├─ configs/
│  ├─ taxonomy.yaml
│  ├─ prompt.yaml
│  └─ defaults.yaml
├─ src/
│  └─ faultlens/
│     ├─ cli.py
│     ├─ orchestrator.py
│     ├─ schemas/
│     │  ├─ case_record.py
│     │  ├─ attribution_result.py
│     │  └─ report_models.py
│     ├─ adapters/
│     │  ├─ jsonl_reader.py
│     │  ├─ inference_output_reader.py
│     │  ├─ results_reader.py
│     │  └─ joiner.py
│     ├─ pipeline/
│     │  ├─ normalizer.py
│     │  ├─ failure_detector.py
│     │  ├─ evidence_extractor.py
│     │  ├─ batch_aggregator.py
│     │  └─ report_generator.py
│     ├─ agents/
│     │  ├─ attribution_agent.py
│     │  └─ prompts.py
│     ├─ llm/
│     │  ├─ client.py
│     │  └─ response_parser.py
│     └─ utils/
│        ├─ logging.py
│        └─ io.py
└─ tests/
```

## 14. V1 交付物

V1 完成后，用户应能够执行一条命令完成整批分析，例如：

```bash
faultlens analyze \
  --inference-output ./data/inference-output.jsonl \
  --results ./data/results.jsonl \
  --out ./outputs
```

并得到：

- `outputs/case_analysis.jsonl`
- `outputs/summary_report.md`
- `outputs/run_warnings.json`

## 15. 后续演进方向

在 V1 跑通后，再考虑以下增强：

- 接入更多评测字段（编译结果、测试输出、judge comments）
- 引入二级错误分类
- 增加历史对比与回归分析
- 加入人工修正结果回流
- 支持更复杂的 Agent 评测日志结构

## 16. 结论

FaultLens V1 应被实现为一个**离线 CLI 错误归因 Agent**。其核心价值是：

- 对评测失败样本给出可解释的错误归因
- 对整批失败做稳定、可统计的模式汇总
- 在不过度平台化的前提下，为质量团队提供高价值分析输出

在当前输入条件下，最合理的技术路线是：

> **以代码构建稳定的数据管线，以 LLM 完成最终归因判断。**
