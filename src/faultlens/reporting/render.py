from __future__ import annotations

from faultlens.models import AttributionResult, SummaryReport
from faultlens.reporting.labels import display_case_status, display_root_cause, display_signal, display_signals



def render_analysis_report(summary: SummaryReport, results: list[AttributionResult], run_context: dict | None = None) -> str:
    run_context = run_context or {}
    sections = [
        "# 运行摘要\n"
        f"- 输入文件：{', '.join(run_context.get('input_files', [])) or 'unknown'}\n"
        f"- 角色识别：{run_context.get('role_detection', {})}\n"
        f"- Join 统计：{run_context.get('join_stats', {})}\n"
        f"- 案例统计：{_format_case_counts(run_context.get('case_counts', {}))}\n"
        f"- 模型配置：{run_context.get('model_summary', 'deterministic-only')}\n"
        f"- LLM 并发数：{run_context.get('llm_max_workers', 1)}\n"
        f"- 案例总数：{summary.total_cases}",
        "# 确定性分析摘要\n" + _format_signal_mapping(summary.deterministic_signal_counts),
        "# LLM 根因分布\n" + _format_root_cause_mapping(summary.root_cause_counts),
        "# 交叉分析\n" + _format_nested_mapping(summary.cross_analysis),
        "# 切片分析\n" + _format_slice_mapping(summary.slices),
        "# 代表性案例\n" + _format_root_cause_mapping(summary.exemplars),
        "# 待人工复核\n" + ("\n".join(f"- {item}" for item in summary.review_queue) if summary.review_queue else "- 无"),
        "# 输入警告\n" + ("\n".join(f"- {item}" for item in run_context.get("input_warnings", [])) if run_context.get("input_warnings") else "- 无"),
        "# LLM 响应质量\n" + _format_llm_response_stats(run_context.get("llm_response_stats")),
        "# LLM 警告\n" + ("\n".join(f"- {item}" for item in run_context.get("llm_warnings", [])) if run_context.get("llm_warnings") else "- 无"),
    ]
    return "\n\n".join(sections) + "\n"



def render_case_report(result: AttributionResult) -> str:
    findings = result.deterministic_findings
    lines = [
        f"# 案例 {result.case_id}",
        "## 基本信息",
        f"- 案例状态：{display_case_status(result.case_status)}",
        f"- Accepted：{result.accepted}",
        "## 语言",
        str(findings.get("primary_language", "unknown")),
        "## 生成代码",
        str(findings.get("completion_code", "")),
        "## 解析 / 编译 / 测试",
        f"- 解析：{findings.get('parse_status', 'unknown')}",
        f"- 编译：{findings.get('compile_status', 'unknown')}",
        f"- 测试：{findings.get('test_status', 'unknown')}",
        "## 确定性信号",
        display_signals(result.deterministic_signals),
        "## 根因",
        display_root_cause(result.root_cause),
        "## 解释",
        result.explanation,
        "## Canonical Diff",
        str(findings.get("canonical_diff_summary", "n/a")),
        "## Harness Alignment",
        str(findings.get("test_harness_alignment_summary", "n/a")),
        "## 证据引用",
        str(result.evidence_refs),
        "## LLM 解析信息",
        f"- LLM 解析模式：{result.llm_parse_mode or '无'}",
        f"- LLM 解析原因：{result.llm_parse_reason or '无'}",
        f"- 原始回复摘录：{result.llm_raw_response_excerpt or '无'}",
        "## 警告",
        ("\n".join(f"- {warning}" for warning in result.warnings) if result.warnings else "- 无"),
        "## 调试建议",
        "\n".join(f"- {hint}" for hint in result.improvement_hints) if result.improvement_hints else "- 无",
    ]
    return "\n".join(lines) + "\n"



def _format_case_counts(mapping: dict) -> dict:
    return {display_case_status(key): value for key, value in mapping.items()}



def _format_root_cause_mapping(mapping: dict) -> str:
    if not mapping:
        return "- 无"
    return "\n".join(f"- {display_root_cause(key)}: {value}" for key, value in mapping.items())



def _format_signal_mapping(mapping: dict) -> str:
    if not mapping:
        return "- 无"
    return "\n".join(f"- {display_signal(key)}: {value}" for key, value in mapping.items())



def _format_nested_mapping(mapping: dict) -> str:
    if not mapping:
        return "- 无"
    lines = []
    for key, value in mapping.items():
        pretty = {display_root_cause(inner): count for inner, count in value.items()}
        lines.append(f"- {display_signal(key)}: {pretty}")
    return "\n".join(lines)



def _format_slice_mapping(mapping: dict) -> str:
    if not mapping:
        return "- 无"
    lines = []
    for slice_key, values in mapping.items():
        pretty = {inner: {display_root_cause(root): count for root, count in counts.items()} for inner, counts in values.items()}
        lines.append(f"- {slice_key}: {pretty}")
    return "\n".join(lines)



def _format_llm_response_stats(stats: dict | None) -> str:
    if not stats:
        return "- 无"
    reasons = stats.get("nonconforming_reasons") or {}
    samples = stats.get("raw_response_excerpts") or []
    lines = [
        f"- LLM 归因尝试次数：{stats.get('attempted', 0)}",
        f"- 严格 JSON 成功数：{stats.get('strict_json', 0)}",
        f"- 自适应解析成功数：{stats.get('adaptive_parse', 0)}",
        f"- 保底挽救成功数：{stats.get('salvaged', 0)}",
        f"- 跳过的无效回复数：{stats.get('skipped_invalid', 0)}",
        f"- 非规范格式占比：{stats.get('nonconforming', 0)} ({stats.get('nonconforming_percentage', 0.0)}%)",
        f"- 非规范原因分布：{reasons if reasons else '无'}",
        f"- raw_response_excerpts: {samples if samples else '无'}",
        f"- 请求错误数：{stats.get('request_errors', 0)}",
    ]
    return "\n".join(lines)
