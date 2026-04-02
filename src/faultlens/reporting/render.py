from __future__ import annotations

from io import StringIO

from faultlens.attribution.hierarchy import L1_LABELS, L2_LABELS, L3_LABELS
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
        "# 三层错因聚合\n" + _format_hierarchy_summary(summary),
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
    hierarchy = result.hierarchical_cause or {}
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
        "## 三层错因分析",
        _format_hierarchical_case_section(hierarchy),
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


def render_hierarchical_root_cause_report(summary: SummaryReport, results: list[AttributionResult]) -> str:
    buffer = StringIO()
    write_hierarchical_root_cause_report(buffer, summary, results)
    return buffer.getvalue()


def write_hierarchical_root_cause_report(handle, summary: SummaryReport, results) -> None:
    handle.write("# 三层错因总览\n")
    handle.write("# 方法说明\n")
    handle.write("- 说明：L1 表示表层错误，L2 表示过程阶段错误原因，L3 表示根能力项原因。\n")
    handle.write("- 仅对可归因失败样本统计三层错因分布。\n\n")
    handle.write("# L1 表层错误分布\n")
    handle.write(_format_hierarchy_table(summary.hierarchy_counts.get("l1", {}), level="l1"))
    handle.write("\n\n# L2 过程阶段错误原因分布\n")
    handle.write(_format_hierarchy_table(summary.hierarchy_counts.get("l2", {}), level="l2"))
    handle.write("\n\n# L3 根能力项原因分布\n")
    handle.write(_format_hierarchy_table(summary.hierarchy_counts.get("l3", {}), level="l3"))
    handle.write("\n\n# 主类到细类拆解\n")
    handle.write(_format_hierarchy_subtype_table(summary))
    handle.write("\n\n# 根因与三层错因交叉映射\n")
    handle.write(_format_hierarchy_root_cross_table(summary))
    handle.write("\n\n# 失败样本逐题明细\n")
    handle.write(_format_case_detail_table(results))
    handle.write("\n\n# 待人工复核样本\n")
    handle.write(_format_review_queue_table(summary, results))



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


def _format_hierarchical_case_section(hierarchy: dict) -> str:
    if not hierarchy:
        return "- 无"
    return "\n".join(
        [
            "### L1 表层错误",
            _format_hierarchical_level(hierarchy.get("l1", {})),
            "### L2 过程阶段错误原因",
            _format_hierarchical_level(hierarchy.get("l2", {})),
            "### L3 根能力项原因",
            _format_hierarchical_level(hierarchy.get("l3", {})),
        ]
    )


def _format_hierarchical_level(level: dict) -> str:
    if not level:
        return "- 无"
    return "\n".join(
        [
            f"- 主类：{level.get('label', '未知')}",
            f"- 细类：{level.get('subtype', 'unspecified')}",
            f"- 判定理由：{level.get('rationale', '无')}",
            f"- 支撑证据：{_format_evidence_inline(level.get('evidence') or [])}",
        ]
    )


def _format_hierarchy_mapping(mapping: dict, *, level: str | None = None) -> str:
    if not mapping:
        return "- 无"
    return "\n".join(
        f"- {_display_hierarchy_code(level, item) if level else item}: {count}"
        for item, count in mapping.items()
    )


def _format_hierarchy_summary(summary: SummaryReport) -> str:
    sections = [
        "## L1 表层错误",
        _format_hierarchy_mapping(summary.hierarchy_counts.get("l1", {}), level="l1"),
        "## L2 过程阶段错误原因",
        _format_hierarchy_mapping(summary.hierarchy_counts.get("l2", {}), level="l2"),
        "## L3 根能力项原因",
        _format_hierarchy_mapping(summary.hierarchy_counts.get("l3", {}), level="l3"),
    ]
    return "\n".join(sections)


def _format_hierarchy_subtypes(summary: SummaryReport) -> str:
    lines: list[str] = []
    for level in ("l1", "l2", "l3"):
        grouped = summary.hierarchy_subtype_counts.get(level, {})
        if not grouped:
            lines.append(f"## {level.upper()}")
            lines.append("- 无")
            continue
        lines.append(f"## {level.upper()}")
        for code, subtype_counts in grouped.items():
            lines.append(f"- {_display_hierarchy_code(level, code)}: {subtype_counts}")
    return "\n".join(lines)


def _format_hierarchy_root_cross(summary: SummaryReport) -> str:
    lines: list[str] = []
    for level in ("l1", "l2", "l3"):
        grouped = summary.hierarchy_root_cause_cross.get(level, {})
        if not grouped:
            lines.append(f"## {level.upper()}")
            lines.append("- 无")
            continue
        lines.append(f"## {level.upper()}")
        for code, root_counts in grouped.items():
            pretty = {f"{display_root_cause(root)} ({root})": count for root, count in root_counts.items()}
            lines.append(f"- {_display_hierarchy_code(level, code)}: {pretty}")
    return "\n".join(lines)


def _format_hierarchy_table(mapping: dict, *, level: str) -> str:
    if not mapping:
        return "| 主类 | 计数 |\n| --- | --- |\n| 无 | 0 |"
    lines = ["| 主类 | 计数 |", "| --- | --- |"]
    for code, count in mapping.items():
        lines.append(f"| {_display_hierarchy_code(level, code)} | {count} |")
    return "\n".join(lines)


def _format_hierarchy_subtype_table(summary: SummaryReport) -> str:
    lines = ["| 层级 | 主类 | 细类 | 计数 |", "| --- | --- | --- | --- |"]
    wrote_any = False
    for level in ("l1", "l2", "l3"):
        grouped = summary.hierarchy_subtype_counts.get(level, {})
        for code, subtype_counts in grouped.items():
            for subtype, count in subtype_counts.items():
                wrote_any = True
                lines.append(f"| {level.upper()} | {_display_hierarchy_code(level, code)} | {subtype} | {count} |")
    if not wrote_any:
        lines.append("| - | 无 | 无 | 0 |")
    return "\n".join(lines)


def _format_hierarchy_root_cross_table(summary: SummaryReport) -> str:
    lines = ["| 层级 | 主类 | root_cause | 计数 |", "| --- | --- | --- | --- |"]
    wrote_any = False
    for level in ("l1", "l2", "l3"):
        grouped = summary.hierarchy_root_cause_cross.get(level, {})
        for code, root_counts in grouped.items():
            for root_cause, count in root_counts.items():
                wrote_any = True
                lines.append(
                    f"| {level.upper()} | {_display_hierarchy_code(level, code)} | {display_root_cause(root_cause)} ({root_cause}) | {count} |"
                )
    if not wrote_any:
        lines.append("| - | 无 | 无 | 0 |")
    return "\n".join(lines)


def _format_case_detail_table(results: list[AttributionResult]) -> str:
    lines = [
        "| Case ID | Root Cause | L1 | L2 | L3 | 关键证据 | 解释来源 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    wrote_any = False
    for result in results:
        if result.case_status != "attributable_failure":
            continue
        wrote_any = True
        hierarchy = result.hierarchical_cause or {}
        l1 = hierarchy.get("l1", {})
        l2 = hierarchy.get("l2", {})
        l3 = hierarchy.get("l3", {})
        evidence = _format_evidence_inline(l3.get("evidence") or l2.get("evidence") or l1.get("evidence") or result.observable_evidence)
        lines.append(
            f"| {result.case_id} | {display_root_cause(result.root_cause)} ({result.root_cause}) | "
            f"{l1.get('label', '未知')} / {l1.get('subtype', 'unspecified')} | "
            f"{l2.get('label', '未知')} / {l2.get('subtype', 'unspecified')} | "
            f"{l3.get('label', '未知')} / {l3.get('subtype', 'unspecified')} | "
            f"{evidence} | {result.final_decision_source} |"
        )
    if not wrote_any:
        lines.append("| - | 无 | 无 | 无 | 无 | 无 | 无 |")
    return "\n".join(lines)


def _format_review_queue_table(summary: SummaryReport, results: list[AttributionResult]) -> str:
    reason_by_case = {result.case_id: (result.review_reason or "unspecified") for result in results if result.needs_human_review}
    lines = ["| Case ID | 复核原因 |", "| --- | --- |"]
    if not summary.review_queue:
        lines.append("| 无 | 无 |")
        return "\n".join(lines)
    for case_id in summary.review_queue:
        lines.append(f"| {case_id} | {reason_by_case.get(case_id, 'unspecified')} |")
    return "\n".join(lines)


def _display_hierarchy_code(level: str, code: str) -> str:
    mapping = {"l1": L1_LABELS, "l2": L2_LABELS, "l3": L3_LABELS}[level]
    return mapping.get(code, code)


def _format_evidence_inline(items: list) -> str:
    if not items:
        return "无"
    return "；".join(str(item) for item in items)
