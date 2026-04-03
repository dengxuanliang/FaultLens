# FaultLens 大规模评测日志摄取与可恢复分析设计

- **日期**: 2026-04-03
- **项目**: FaultLens
- **主题**: 面向 2000+ 题规模的评测日志摄取、断点恢复与可审计分析流水线
- **目标**: 在绝大多数失败样本都需要进入 LLM 的前提下，保证长任务不丢进度、可恢复、可审计，并保持现有 CLI 形态

## 1. 背景

当前 FaultLens 已具备以下能力：

- 两个 JSONL 输入文件的 schema 识别
- 基于流式读取和临时 SQLite 的 join
- deterministic-first 分析链路
- 可选 LLM 归因
- `case_analysis.jsonl`、Markdown 报告、checkpoint 的批量输出

现有实现对 demo 和中小规模数据是成立的，但在下面这个目标场景下会暴露结构性问题：

- 输入规模上升到 2000+ 题
- inference/results 两个文件都可能较大
- 绝大多数失败样本都需要进入 LLM
- 任务可能运行很久，期间会遇到 provider 抖动、429/5xx、人工中断或进程异常
- 运行结束后需要保留足够原始证据，支持人工复核和追责

此时瓶颈不再是单纯的 JSONL 文件读取，而是全链路如何做到：

1. 输入只扫描一次，避免 resume 时重复 join 和重复预处理
2. 每个 case 的阶段状态可恢复，而不是仅凭最终结果判断是否处理过
3. LLM 请求与响应具备完整审计轨迹
4. 汇总报告基于稳定中间状态重建，而不是依赖一次性流水线成功跑完

## 2. 非目标

本设计不包含以下内容：

- 引入新的服务端形态、Web 平台或分布式队列系统
- 将 FaultLens 改造成常驻 daemon
- 对 LLM 提供商 SDK 做深度绑定，仍优先保留标准库和简单 HTTP 适配
- 追求极致吞吐优先于可恢复和可审计

## 3. 方案对比

### 方案 A：保留当前单次流水线，继续在现有 checkpoint 上打补丁

做法：

- 保持“边 join、边 deterministic、边 LLM、边落盘”的流程
- 继续依赖 `processed_results` 判断 resume
- 在局部增加更多 warning 和 retry

优点：

- 改动最小
- 短期见效快

缺点：

- 输入阶段与分析阶段耦合，resume 时仍然需要再次扫描原始文件
- checkpoint 粒度过粗，无法表达 case 所处阶段
- 难以完整回答“这条 case 何时请求过 LLM、重试了几次、最终采用了哪次结果”

### 方案 B：本地 SQLite 状态机流水线

做法：

- 第一步先把输入文件稳定摄取到本地 SQLite
- 后续 deterministic、LLM、finalize 都围绕本地任务状态推进
- 报告与 JSON 输出从本地状态聚合生成

优点：

- 输入只扫一次
- 恢复精度高
- 审计链路完整
- 与现有 CLI 架构兼容，改造成本可控

缺点：

- 需要重构 orchestrator 与 checkpoint 逻辑
- 引入更多表结构和状态流转

### 方案 C：更重的数据库化分析平台

做法：

- 所有中间态、聚合和查询都完全数据库化
- 进一步引入更复杂的数据建模和任务管理

优点：

- 查询和分析能力最强

缺点：

- 对当前项目阶段过重
- 工程复杂度与维护成本偏高

## 4. 结论

采用 **方案 B：本地 SQLite 状态机流水线**。

这是当前项目最合理的中间形态：

- 比当前实现明显更接近产品级
- 不引入不必要的分布式复杂度
- 能直接解决“长任务不丢进度、必须可恢复和可审计”的核心诉求

## 5. 总体架构

新的批处理运行拆成四个阶段：

1. **Ingest Snapshot**
2. **Deterministic Stage**
3. **LLM Stage**
4. **Finalize Stage**

所有阶段围绕一个 run 目录下的持久化数据库推进，例如：

- `run.db`
- `input_manifest.json`
- `case_analysis.jsonl`
- `analysis_report.md`
- `summary.json`
- `run_metadata.json`
- `llm_raw_responses/`

### 5.1 阶段职责

#### Ingest Snapshot

职责：

- 识别两个输入文件角色
- 逐行解析 JSONL
- 记录空行、坏行、schema outlier、缺失 join key、重复 join key
- 按 join key 构建稳定的本地 case 索引
- 持久化原始 inference/results payload、输入来源和内容摘要

约束：

- 正式运行中，输入文件应只完整扫描一次
- resume 不依赖重新扫描原始文件恢复 case

#### Deterministic Stage

职责：

- 从本地 case 索引中拉取待处理样本
- 运行 failure gate
- 执行 deterministic analyzers
- 将 findings、signals、warnings 和 eligibility 写回数据库

约束：

- deterministic 结果必须可单独重建，不依赖 LLM 成功
- 若 deterministic 失败，也需要明确记录失败原因

#### LLM Stage

职责：

- 从数据库中选择 `eligible_for_llm = true` 的样本
- 构造 prompt/messages
- 发起 LLM 请求、处理限流和重试
- 完整保存 request、response、parse 结果、错误体和重试记录
- 将最终采纳的 LLM judgment 与 case 关联

约束：

- 每次 attempt 都必须有独立审计记录
- LLM 阶段失败不能导致前序 deterministic 结果丢失

#### Finalize Stage

职责：

- 从数据库聚合 summary
- 生成 `case_analysis.jsonl`
- 生成 Markdown/JSON 报告
- 输出 exemplar 和单 case 报告

约束：

- Finalize 可以重复执行
- Finalize 不依赖重新发起 LLM

## 6. 数据模型

数据库文件建议统一为 `run.db`。核心表如下。

### 6.1 `input_files`

用途：

- 保存本次 run 的输入清单和文件指纹

建议字段：

- `path`
- `declared_order`
- `detected_role`
- `size_bytes`
- `mtime_epoch`
- `sha256`
- `sample_record_count`
- `created_at`

### 6.2 `ingest_events`

用途：

- 记录输入阶段遇到的异常和 warning

建议字段：

- `id`
- `source_path`
- `line_number`
- `severity`
- `event_type`
- `message`
- `payload_excerpt`
- `created_at`

事件类型示例：

- `empty_line`
- `bad_json`
- `non_object_json`
- `schema_outlier`
- `missing_join_key`
- `duplicate_join_key`
- `missing_pair`

### 6.3 `joined_cases`

用途：

- 保存 join 后的稳定 case 索引

建议字段：

- `case_id`
- `join_status`
- `inference_line_number`
- `results_line_number`
- `input_role_detection`
- `inference_payload_json`
- `results_payload_json`
- `normalization_warnings_json`
- `normalization_errors_json`
- `join_anomaly_flags_json`
- `content_sha256`
- `created_at`
- `updated_at`

说明：

- `content_sha256` 用于识别 case 是否发生实质变化
- 原始 payload 直接存 JSON 文本，保证审计时可回放

### 6.4 `analysis_jobs`

用途：

- 维护每个 case 的处理状态机

建议字段：

- `case_id`
- `job_status`
- `eligible_for_llm`
- `deterministic_ready`
- `llm_required`
- `attempt_count`
- `next_retry_at`
- `worker_lease_token`
- `worker_lease_until`
- `last_error`
- `created_at`
- `updated_at`

推荐状态：

- `ingested`
- `gated`
- `deterministic_done`
- `llm_pending`
- `llm_running`
- `llm_done`
- `llm_failed_retryable`
- `llm_failed_terminal`
- `finalized`

### 6.5 `deterministic_results`

用途：

- 保存 failure gate 和 deterministic analyzers 的结果

建议字段：

- `case_id`
- `case_status`
- `failure_gate_warnings_json`
- `deterministic_signals_json`
- `deterministic_findings_json`
- `deterministic_root_cause_hint`
- `runner_warnings_json`
- `analysis_version`
- `created_at`
- `updated_at`

### 6.6 `llm_attempts`

用途：

- 保存每次 LLM 请求尝试的完整审计数据

建议字段：

- `id`
- `case_id`
- `attempt_index`
- `request_messages_json`
- `request_sha256`
- `provider_model`
- `provider_base_url`
- `http_status`
- `started_at`
- `finished_at`
- `latency_ms`
- `outcome`
- `error_type`
- `error_message`
- `response_text`
- `response_sha256`
- `parse_mode`
- `parse_reason`
- `is_selected`

说明：

- `request_messages_json` 保留 prompt 原文，便于人工核验
- `response_text` 保存 provider 的完整原始返回
- `is_selected` 标识最终采用的 attempt

### 6.7 `final_results`

用途：

- 保存最终归因结果，作为输出和聚合的唯一事实来源

建议字段：

- `case_id`
- `final_result_json`
- `final_decision_source`
- `root_cause`
- `secondary_cause`
- `confidence`
- `needs_human_review`
- `review_reason`
- `created_at`
- `updated_at`

## 7. 状态流转

### 7.1 标准成功路径

1. 输入文件完成摄取，case 写入 `joined_cases`
2. 对应 `analysis_jobs.job_status = ingested`
3. failure gate 完成后更新为 `gated`
4. deterministic 完成后更新为 `deterministic_done`
5. 若需要 LLM，则更新为 `llm_pending`
6. worker 领取任务后更新为 `llm_running`
7. LLM 成功并选定结果后更新为 `llm_done`
8. 生成最终归因并落入 `final_results` 后更新为 `finalized`

### 7.2 无需 LLM 的路径

1. `deterministic_done`
2. 直接生成 final result
3. 更新为 `finalized`

### 7.3 可重试失败路径

1. `llm_running`
2. 请求失败但属于可重试错误，例如 429、5xx、网络超时
3. 写入 `llm_attempts`
4. 更新为 `llm_failed_retryable`
5. 计算 `next_retry_at`
6. 到时后重新转回 `llm_pending`

### 7.4 终态失败路径

1. 达到最大重试次数或命中不可重试错误
2. 更新为 `llm_failed_terminal`
3. 仍基于 deterministic 结果生成 final result
4. 最终更新为 `finalized`

## 8. 可恢复策略

### 8.1 Resume 行为

当用户使用 `--resume` 时：

- 若 `run.db` 已存在，则优先从数据库恢复，而不是重扫原始输入文件
- 所有 `finalized` case 直接跳过
- 对 `llm_running` 中 lease 已过期的任务做回收
- 对 `llm_failed_retryable` 且已到 `next_retry_at` 的任务重新入队

### 8.2 Lease 机制

为了应对进程意外退出，LLM worker 领取任务时需要设置租约：

- `worker_lease_token`
- `worker_lease_until`

恢复时，若任务处于 `llm_running` 且 lease 已过期，则判定为 abandoned，可重新领取。

### 8.3 幂等要求

以下操作应尽量设计为幂等：

- Ingest Snapshot
- Finalize Stage
- case 级 final result 写入
- 报告重渲染

幂等的意义在于允许用户安全地重跑，而不是担心重复写坏状态。

## 9. 性能设计

### 9.1 输入读取

保留当前逐行 JSONL 读取方式，不改成整文件载入。原因如下：

- 两个文件、2000 题规模下，流式读取已经足够快
- 内存占用稳定
- 更适合坏行告警和行号记录

### 9.2 Join 策略

当前基于临时 SQLite 的 join 思路是对的，但需要升级为“持久化 run.db”：

- ingest 时把 inference/results 按 join key 写入数据库
- 只在本次 run 的开始阶段做一次完整 join
- 后续 resume 和汇总都不再重新 join 原始文件

### 9.3 LLM 吞吐控制

因为你的优先级不是极限提速，而是稳定性，推荐策略如下：

- 默认较低并发，例如 `1-4`
- 支持 provider 限流下的指数退避
- 用任务状态和 `next_retry_at` 控制节奏，而不是简单 sleep 整个进程
- 一次只领取少量待处理任务，避免进程崩溃后大量任务状态悬挂

### 9.4 输出策略

批量输出应采用“数据库聚合 + 流式导出”模式：

- `case_analysis.jsonl` 可从 `final_results` 逐条导出
- Markdown 报告从聚合结果渲染
- case 单文件报告仅对 exemplar 和指定 `case_id` 生成

## 10. 模块改造方案

### 10.1 保留的模块

- `src/faultlens/ingest/jsonl.py`
- `src/faultlens/ingest/resolver.py`
- `src/faultlens/deterministic/*`
- `src/faultlens/llm/prompting.py`
- `src/faultlens/llm/adaptive_parser.py`
- `src/faultlens/reporting/*`

这些模块的核心逻辑仍可复用。

### 10.2 重点重构模块

#### `src/faultlens/normalize/joiner.py`

从“返回 joined case iterator”升级为：

- `build_ingest_snapshot(...)`
- `iter_joined_cases_from_db(...)`

职责从一次性 join 转向持久化索引构建。

#### `src/faultlens/scale/checkpointing.py`

从轻量 checkpoint 升级为数据库访问层，统一处理：

- job 状态更新
- lease 管理
- metadata 持久化
- attempt 审计写入
- final result 查询

#### `src/faultlens/orchestrator.py`

从单函数串行推进，拆成阶段化入口：

- `ingest_inputs(...)`
- `run_deterministic_stage(...)`
- `run_llm_stage(...)`
- `finalize_outputs(...)`
- `resume_run(...)`

## 11. 错误处理

### 11.1 输入错误

- 文件缺失、坏 JSON、非对象 JSON、缺失 key、重复 key，均记录到 `ingest_events`
- 不要求所有输入错误都立即终止；可保留可分析部分继续执行

### 11.2 deterministic 错误

- runner 不可用、编译/执行异常、超时等，都作为结构化 findings/warnings 存档
- 不允许因为单个 case 的 deterministic 执行错误中断整批任务

### 11.3 LLM 错误

- provider 返回错误体时完整保存
- parse 失败和请求失败分开建模
- terminal failure 也必须产出 final result，而不是让 case 丢失

## 12. 测试策略

至少新增以下测试类型：

1. **大批量 ingest 测试**
   - 生成 2000+ 条 fixture
   - 校验输入只需一次完整摄取
   - 校验 `joined_cases` 和 `analysis_jobs` 条数正确

2. **resume 测试**
   - 在 deterministic 完成后中断
   - 在 LLM 处理中断
   - 验证 resume 后不会重复处理 `finalized` 样本

3. **lease 回收测试**
   - 人为构造过期 `llm_running`
   - 验证任务可重新领取

4. **LLM attempt 审计测试**
   - 校验 request/response/sha256/parse mode 被完整保存

5. **Finalize 幂等测试**
   - 重复执行 finalize
   - 输出不重复、不损坏

## 13. 迁移策略

建议分两步实施：

### 阶段 1：结构升级但保持 CLI 外部接口稳定

- 新增 `run.db`
- 完成 ingest snapshot
- 引入 `analysis_jobs` 和 `llm_attempts`
- 让现有 `analyze` 命令仍可正常使用

### 阶段 2：输出和 resume 全面切换到数据库驱动

- 让 `case_analysis.jsonl` 从 `final_results` 导出
- 让 resume 完全绕过原始文件重扫
- 完成 finalize 幂等

## 14. 验收标准

满足以下条件即可认为该方案达到目标：

1. 2000+ 题规模下，输入文件只在 ingest 阶段完整扫描一次
2. 任意时点中断后，可在本地状态上恢复，不重复处理已完成样本
3. 每个 LLM case 都能追溯到原始 request、raw response、重试记录和最终采纳结果
4. provider 故障不会导致整批结果丢失
5. Markdown/JSON 报告可从数据库稳定重建

## 15. 推荐实现顺序

最小可落地顺序如下：

1. 把现有 checkpoint sqlite 升级为 `run.db` 访问层
2. 先完成 ingest snapshot 和 `joined_cases`
3. 再引入 `analysis_jobs` 状态机
4. 再把 LLM attempt 审计迁移进去
5. 最后重构 finalize 和报告导出

这个顺序可以确保每一步都能单独验证，并避免一次性推翻现有实现。
