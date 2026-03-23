# FaultLens 错题分析 Agent 设计文档

- **日期**: 2026-03-24
- **项目**: FaultLens
- **形态**: CLI Agent（非平台）
- **目标用户**: 评测/质量团队为主，Prompt/算法工程师为辅

## 1. 背景与目标

FaultLens 要交付的是一个**针对代码评测日志的错误分析 Agent**，而不是 Web 平台。它面向一组评测产物：一个 inference-side JSONL 文件，一个 results-side JSONL 文件；两者记录一一对应。Agent 要先执行**不依赖 LLM 的规则化分析**，尽可能自动、稳定地识别低层错误；然后仅对失败样本执行 **LLM 归因与解释**；最后输出批量 Markdown 报告与单条深入解析结果。

FaultLens V1 要回答以下问题：

1. 哪些样本失败了？
2. 这些失败是否能被确定性规则直接解释，例如无代码、语法错误、编译错误、运行错误、测试失败、超时、接口不匹配？
3. 对于规则层不能完整解释或需要更高层次总结的失败，根因更接近哪一类？
4. 在整批数据中，各类错误如何分布、集中在哪些语言/难度/类别切片、哪些代表样本最值得复盘？
5. 某个具体 case 的代码、编译/测试行为、与参考解差异、以及 LLM 归因解释分别是什么？

## 2. V1 范围

### 2.1 包含内容

- 输入两个 JSONL 文件，**文件名不固定**，按 schema 自动识别角色
- 自动识别 inference-side 与 results-side 文件，并进行 1:1 配对校验
- 标准化为统一 Case 结构，保留原始记录、元数据、测试代码、评测指标
- 针对失败样本执行**规则化分析优先**的两阶段流程：
  1. 代码提取、语言识别、语法/解析检查、编译检查、测试执行、接口/签名检查、基础 diff
  2. LLM 归因、解释生成、低置信度补充分析
- 重点支持 Python / Java / C++ / Go，框架上允许常见多语言扩展
- 生成批量 Markdown 报告、结构化 JSONL/JSON 汇总、代表样本 exemplar、单条深挖报告
- 支持按 `case_id` 进行单条深挖，也支持批量运行时自动生成代表样本单条报告
- 模型凭证通过项目级 `.env` 加载，不写入代码和仓库

### 2.2 暂不包含

- Web UI / 后台服务 / 多用户系统
- 实时监听与在线评测
- 自动修复代码或回写评测系统
- 历史 run 对比仪表盘
- 复杂 RAG / 外部知识库
- 多 Agent 互相协作式决策链路

## 3. 输入数据约定

V1 输入是两个 JSONL 文件，角色通过字段语义自动识别，而不是通过文件名绑定。

### 3.1 inference-side 记录

当前已知最小字段集合：

- `id`: 题目标识，用于 join
- `content`: 题目内容
- `canonical_solution`: 参考代码
- `completion`: 模型输出，包含解释与代码

当前已知可选字段：

- `labels.programming_language`
- `labels.execution_language`
- `labels.category`
- `labels.difficulty`
- `labels.fewshot`
- `labels.locale`
- `test.code`

### 3.2 results-side 记录

当前已知最小字段集合：

- `task_id`: 与 inference `id` 一一对应
- `accepted`: 布尔值，`true` 表示通过，`false` 表示失败

当前已知可选字段：

- `passed_at_1`
- `pass_at_k`
- `all_k_correct`
- `n`
- `natural_language`
- `programming_language`
- `category`
- `difficulty`

### 3.3 角色识别规则

- 含 `id`、`content`、`canonical_solution`、`completion` 的文件判定为 inference-side
- 含 `task_id`、`accepted` 的文件判定为 results-side
- 若两个文件均符合同一侧 schema、或都不完整、或字段冲突导致无法可靠判定，应立即报错并终止
- 后续可以扩展成用户可配置 schema 映射，但 V1 默认使用上述规则

### 3.4 关联规则

- 默认 join 键：`inference.id == results.task_id`
- 比较前统一转为字符串
- 默认假设：两文件 1:1 对应
- 必须显式处理：
  - 缺失配对记录
  - 重复 join key
  - 类型不一致
  - 同一 join key 多条候选记录

## 4. 设计方案对比

### 方案 A：LLM 主导

- 规则层只做最基础筛选
- 大部分判断与解释交给 LLM
- **优点**：实现快
- **缺点**：成本高、慢、稳定性弱、不利于批量统计

### 方案 B：规则主导

- 解析、编译、测试、差异分析、归因都尽量靠代码实现
- **优点**：稳定、便宜
- **缺点**：高层归因僵硬，可读性和泛化差

### 方案 C：两阶段 Agent（推荐）

1. **Deterministic Analysis First**：先做失败门控、代码提取、语言识别、语法检查、编译检查、测试执行、签名/接口检查、基础 diff，产出结构化 findings 和 signals
2. **LLM Attribution Second**：只对失败样本、尤其是规则层未完全解释的样本做高层归因、解释和总结

**结论**：V1 采用方案 C，即 **规则优先，LLM 后置**。

## 5. 总体架构

FaultLens 是单进程 CLI Agent，内部流水线如下：

1. **Resolve Inputs**：读取两个 JSONL 输入并识别角色
2. **Validate & Join**：校验 schema 与 1:1 配对关系
3. **Normalize**：生成统一 `CaseRecord`
4. **Deterministic Analysis**：执行规则分析与运行验证
5. **LLM Attribution**：对失败 case 做高层归因与解释
6. **Aggregate**：聚合错误模式、切片、代表样本
7. **Render Reports**：输出 markdown、jsonl、json、单条 case 详情

### 5.1 架构原则

- **规则优先，LLM 后置**
- **批量分析和单条深挖复用同一底层分析链路**
- **输入文件名不固定，角色通过 schema 识别**
- **允许执行 compile / test，但必须受控隔离并有超时限制**
- **高层归因与低层 deterministic findings 必须分开保留 provenance**
- **所有批量统计基于结构化字段，而不是自由文本**

## 6. 核心模块设计

### 6.1 Input Resolver / Adapter

职责：

- 接收两个 JSONL 文件路径
- 逐行解析 JSONL，记录坏行和空行
- 基于字段识别 inference-side / results-side
- 输出角色识别结果与 schema 校验警告

输出：

- `input_role_detection`
- `schema_validation_warnings`
- 原始记录流

### 6.2 Joiner / Case Normalizer

职责：

- 按 `inference.id / results.task_id` 做 1:1 join
- 统一字段命名与类型
- 保留原始记录，生成可审计 `CaseRecord`

推荐 `CaseRecord` 字段：

**记录标识**
- `case_id`
- `join_status`
- `case_status`

**原始数据**
- `raw.inference_record`
- `raw.results_record`

**来源与关联元信息**
- `source.inference_id_raw`
- `source.results_task_id_raw`
- `source.inference_line_number`
- `source.results_line_number`
- `source.input_role_detection`

**标准化内容**
- `task.content_text`
- `reference.canonical_code_text`
- `reference.test_code_text`
- `completion.raw_text`
- `completion.code_blocks`
- `completion.primary_code_text`
- `completion.explanation_text`
- `language.programming_language`
- `language.execution_language`

**评测信息**
- `evaluation.accepted`
- `evaluation.pass_metrics`
- `evaluation.results_tags`

**元数据**
- `metadata.inference_labels`
- `metadata.results_tags`
- `metadata.slice_fields`

**诊断与警告**
- `normalization.warnings`
- `normalization.errors`
- `join_anomaly_flags`

设计要求：

- `canonical_solution` 是重要参考证据，但允许缺失
- `test.code` 是运行验证和接口分析的关键输入，必须单独保存
- `metadata.slice_fields` 由 inference labels 与 results tags 派生
- 若 inference labels 与 results tags 冲突，必须记录 warning

### 6.2.1 Join 确定性策略

- `1:1`：正常合并
- `0:1` / `1:0`：生成 `join_issue` 记录，写入结果，但不进入根因分布统计
- `N:1` / `1:N` / `N:N`：生成 `join_issue` 记录，不做猜测性合并
- join 成功率、失败率、重复键数量进入汇总报告

### 6.3 Failure Gate

职责：

- 以 `evaluation.accepted == false` 作为失败主门控
- 交叉检查 `accepted` 与 `pass_metrics`
- 识别数据问题与 join 问题

`case_status` 枚举：

- `passed`
- `attributable_failure`
- `data_issue`
- `join_issue`

说明：

- 只有 `accepted == false` 且基础数据可分析时才进入 `attributable_failure`
- 缺失 completion、严重解析失败等标记为 `data_issue`
- 缺失 `canonical_solution` 不必然阻塞分析；若有 `content + completion + test.code + accepted` 仍可进入规则分析与 LLM 归因
- 若 `accepted` 与 `pass_metrics` 冲突，应记录 warning，并允许后续归因为 `possible_evaluation_mismatch`

### 6.4 Deterministic Analyzer

这是 V1 的核心能力层，**优先于 LLM**。

职责：

- completion 代码提取
- 语言识别
- 语法/结构检查
- 编译检查
- 测试执行
- 接口/签名检查
- 与 `canonical_solution` 的表层差异分析
- 与 `test.code` 的 harness / entrypoint 适配分析

#### 6.4.1 重点支持语言

- Python
- Java
- C++
- Go

框架上保留扩展能力，但 V1 的 parser / compiler / runner / tests 优先覆盖上述四种语言。

#### 6.4.2 规则层输出

`deterministic_findings` 建议包括：

- `code_extraction_status`
- `detected_languages`
- `primary_language`
- `parse_status`
- `parse_error_excerpt`
- `compile_status`
- `compile_stderr_excerpt`
- `test_status`
- `test_summary`
- `runtime_error_excerpt`
- `failing_assert_excerpt`
- `exit_code`
- `timeout_triggered`
- `signature_check_status`
- `entrypoint_check_status`
- `canonical_diff_summary`
- `test_harness_alignment_summary`

#### 6.4.3 Deterministic Signals（V1 受控词表）

- `missing_code`
- `code_extraction_failed`
- `syntax_error`
- `compile_error`
- `runtime_error`
- `test_failure`
- `timeout`
- `signature_mismatch`
- `entrypoint_mismatch`
- `api_mismatch`
- `logic_mismatch`
- `metadata_conflict`
- `suspicious_eval_mismatch`

#### 6.4.4 执行与安全边界

- 所有 compile / test 在临时工作目录执行
- 设置超时、输出截断、目录清理
- 不允许访问项目外敏感文件
- 若某语言执行器不可用，降级为静态/解析分析，并记录 warning
- deterministic 结论必须保留原始 stderr/stdout 摘要，便于报告与审计

### 6.5 LLM Attribution Agent

职责：

- 只处理 `attributable_failure` 样本
- 消费 `CaseRecord + deterministic_findings`
- 给出高层根因、解释、证据整合、置信度与人工复核建议

LLM 输入应包括：

- 题目内容摘要
- completion 原文与主代码块
- `canonical_solution`（如存在）
- `test.code`
- deterministic findings 与 signals
- 元数据切片字段（语言、类别、难度等）

LLM 不负责重复判断“有没有语法错误/编译错误/测试失败”，而是负责：

- 在高层语义上解释失败原因
- 整合规则层证据
- 对歧义 case 给出保守判断
- 生成面向人的可读解释

#### 6.5.1 高层根因 taxonomy（V1）

- `task_misunderstanding`
- `contract_or_interface_violation`
- `solution_incorrect`
- `implementation_bug`
- `incomplete_or_truncated_solution`
- `environment_or_api_mismatch`
- `possible_evaluation_mismatch`
- `insufficient_evidence`

#### 6.5.2 输出字段

- `case_status`
- `accepted`
- `root_cause`
- `secondary_cause`
- `deterministic_signals`
- `llm_signals`
- `observable_evidence`
- `evidence_refs`
- `deterministic_findings`
- `llm_judgment`
- `final_decision_source`
- `confidence`
- `needs_human_review`
- `review_reason`
- `improvement_hints`

#### 6.5.3 Provenance 规则

- `deterministic_findings`：纯规则分析结果
- `llm_judgment`：LLM 对规则结果和代码语义的高层判断
- `final_decision_source`：`deterministic_only` / `deterministic_plus_llm` / `llm_fallback`
- 若 deterministic 已经形成明确结论，LLM 不得无痕覆盖，只能补充解释或提高/降低置信度

## 7. 归因与信号设计

### 7.1 低层 deterministic 信号 vs 高层根因

- `compile_error`、`runtime_error`、`test_failure` 等属于**低层信号**，来自规则层
- `solution_incorrect`、`implementation_bug` 等属于**高层根因**，来自 LLM 归因层或 deterministic+LLM 联合判断
- 报告中必须同时展示两层信息，避免把可验证事实与推断混为一谈

### 7.2 证据原则

- `canonical_solution` 差异只能作为参考证据，不是绝对真值
- `test.code` 与实际编译/测试结果是更强的运行证据
- 任何高层结论都要引用 deterministic findings 或原始文本片段
- 信息不足时优先输出 `insufficient_evidence`

## 8. 单条样本输出设计

单条结果统一输出 schema，但会根据 `case_status` 决定哪些字段为空。

### 8.1 单条分析至少包含

- case 基本信息
- completion 主代码块
- 语言识别结果
- parse / compile / test 结果
- deterministic signals
- root cause 与 explanation
- canonical diff 摘要
- test harness 对齐摘要
- evidence refs
- debug hints

### 8.2 单条深入解析模式

V1 支持两种方式：

1. CLI 指定 `case_id` 深挖
2. 批量分析后自动为代表性 exemplar 生成单条报告

## 9. 批量报告设计

主报告输出为 Markdown，建议命名为 `analysis_report.md`。

### 9.1 报告结构

1. **Run Summary**
   - 输入文件
   - schema 识别结果
   - join 成功率
   - 总样本数 / 通过数 / 失败数 / 数据问题数 / 关联问题数
   - 使用模型与配置摘要
2. **Deterministic Analysis Summary**
   - `missing_code` / `syntax_error` / `compile_error` / `runtime_error` / `test_failure` / `timeout` / `signature_mismatch` 等分布
3. **LLM Root Cause Distribution**
   - 高层根因分布
4. **Cross Analysis**
   - 低层信号 × 高层根因交叉分析
5. **Slice Analysis**
   - 按 `programming_language`、`execution_language`、`category`、`difficulty`、`fewshot`、`locale`、`natural_language` 切片
6. **Representative Exemplars**
   - 每个高频根因 / 模式生成代表样本摘要与链接
7. **Review Queue**
   - `join_issue`、`data_issue`、低置信度、`possible_evaluation_mismatch` 样本

### 9.2 结构化输出

除 Markdown 外，保留：

- `case_analysis.jsonl`
- `summary.json`
- `exemplars/`
- `cases/<case_id>.md`

## 10. 置信度与人工复核

- deterministic 强信号存在时，置信度优先由规则层决定基线
- LLM 只在高层解释和歧义消解上影响最终置信度
- 以下情况默认进入复核队列：
  - join_issue / data_issue
  - accepted 与 pass_metrics 冲突
  - compile/test 结果与高层归因明显冲突
  - `possible_evaluation_mismatch`
  - `insufficient_evidence`
  - LLM 置信度低

## 11. 错误处理与回退策略

- JSONL 坏行：记录 warning，继续处理其它样本
- 某语言工具链缺失：静态降级并告警
- compile/test 超时：产出 `timeout` 信号并继续后续流程
- LLM 不可用：仍输出 deterministic-only 报告
- `.env` 缺失或模型配置错误：批量 deterministic 流程仍可运行，LLM 部分降级并明确标记

## 12. 测试策略

V1 至少覆盖：

1. 输入角色识别测试
2. join 正常与异常测试
3. completion 代码提取测试
4. 语言识别测试
5. Python / Java / C++ / Go 的 parse/compile/test runner 测试
6. deterministic signals 生成测试
7. LLM 输出契约测试
8. 报告渲染测试
9. 单条深挖 CLI 测试

## 13. 项目结构建议

```text
FaultLens/
├─ .env.example
├─ .gitignore
├─ pyproject.toml
├─ README.md
├─ configs/
│  ├─ defaults.yaml
│  ├─ taxonomy.yaml
│  └─ models.yaml
├─ docs/
│  └─ superpowers/
│     ├─ specs/
│     └─ plans/
├─ src/
│  └─ faultlens/
│     ├─ cli.py
│     ├─ orchestrator.py
│     ├─ config.py
│     ├─ schemas/
│     ├─ ingest/
│     ├─ normalize/
│     ├─ deterministic/
│     │  ├─ analyzers/
│     │  ├─ runners/
│     │  └─ signals.py
│     ├─ llm/
│     ├─ attribution/
│     ├─ reporting/
│     └─ utils/
└─ tests/
```

## 14. 模型凭证与运行配置

- API key / base URL / 默认模型从项目级 `.env` 读取
- `.env` 必须加入 `.gitignore`
- 建议环境变量：
  - `FAULTLENS_API_KEY`
  - `FAULTLENS_BASE_URL`
  - `FAULTLENS_MODEL`
- `configs/models.yaml` 存放模型列表、默认模型、超时、fallback 策略
- 若 `.env` 缺失，则 deterministic-only 路径仍可运行；只有需要 LLM 时才报配置错误

## 15. CLI 交付形态

V1 目标命令示例：

```bash
faultlens analyze --input file_a.jsonl file_b.jsonl --output-dir ./outputs
faultlens analyze --input file_a.jsonl file_b.jsonl --output-dir ./outputs --case-id 123
```

行为：

- 不依赖固定文件名
- 自动识别输入角色
- 默认做批量分析
- 指定 `--case-id` 时额外生成单条深挖输出
- 批量运行后自动为代表 exemplar 生成单条 Markdown

## 16. 结论

FaultLens V1 应实现为一个**规则优先、LLM 后置**的 CLI 错题分析 Agent。其核心价值是：

- 用确定性程序稳定识别低层错误
- 用 LLM 为失败样本补充高层根因与可读解释
- 支持多语言代码评测场景，重点覆盖 Python / Java / C++ / Go
- 同时服务批量质量分析与单条 case 深入排查

在当前需求下，最佳路线是：

> **Deterministic Analysis First, LLM Attribution Second.**
