from __future__ import annotations

from io import StringIO
import json

from faultlens.attribution.hierarchy import L1_LABELS, L2_LABELS, L3_LABELS
from faultlens.models import AttributionResult, SummaryReport
from faultlens.reporting.labels import display_case_status, display_root_cause, display_signal, display_signals



def render_analysis_report(summary: SummaryReport, results: list[AttributionResult], run_context: dict | None = None) -> str:
    run_context = run_context or {}
    failed_cases = summary.failed_cases
    attributable_failures = summary.attributable_failure_cases
    sections = [
        "# 运行摘要\n"
        f"- 输入文件：{', '.join(run_context.get('input_files', [])) or 'unknown'}\n"
        f"- 角色识别：{run_context.get('role_detection', {})}\n"
        f"- Join 统计：{run_context.get('join_stats', {})}\n"
        f"- 案例统计：{_format_case_counts(run_context.get('case_counts', {}))}\n"
        f"- 模型配置：{run_context.get('model_summary', 'deterministic-only')}\n"
        f"- LLM 并发数：{run_context.get('llm_max_workers', 1)}\n"
        f"- 案例总数：{summary.total_cases}\n"
        f"- 失败样本数：{failed_cases}\n"
        f"- 可归因失败数：{attributable_failures}",
        "# 健康摘要\n" + _format_health_summary(run_context.get("health_summary")),
        "# 任务状态\n" + _format_job_status_section(run_context),
        "# 能力快照\n" + _format_capability_snapshot(run_context.get("capability_snapshot")),
        "# 失败分类\n" + _format_failure_taxonomy(run_context.get("failure_taxonomy")),
        "# 确定性分析摘要\n" + _format_signal_mapping(summary.deterministic_signal_counts, total=failed_cases),
        "# LLM 根因分布\n" + _format_root_cause_mapping(summary.root_cause_counts, total=attributable_failures),
        "# 三层错因聚合\n" + _format_hierarchy_summary(summary, total=attributable_failures),
        "# 交叉分析\n" + _format_nested_mapping(summary.cross_analysis, total=attributable_failures),
        "# 切片分析\n" + _format_slice_mapping(summary.slices, total=attributable_failures),
        "# 代表性案例\n" + _format_root_cause_mapping({key: len(value) for key, value in summary.exemplars.items()}, total=attributable_failures),
        "# 待人工复核\n" + _format_review_queue_summary(summary.review_queue, total=failed_cases),
        "# 输入警告\n" + ("\n".join(f"- {item}" for item in run_context.get("input_warnings", [])) if run_context.get("input_warnings") else "- 无"),
        "# LLM 响应质量\n" + _format_llm_response_stats(run_context.get("llm_response_stats")),
        "# LLM 警告\n" + ("\n".join(f"- {item}" for item in run_context.get("llm_warnings", [])) if run_context.get("llm_warnings") else "- 无"),
    ]
    return "\n\n".join(sections) + "\n"



def render_case_report(result: AttributionResult) -> str:
    findings = result.deterministic_findings
    hierarchy = result.hierarchical_cause or {}
    language = str(findings.get("primary_language", "unknown"))
    completion_code = str(findings.get("completion_code", "") or "")
    lines = [
        f"# 案例 {result.case_id}",
        "## 基本信息",
        f"- 案例状态：{display_case_status(result.case_status)}",
        f"- Accepted：{result.accepted}",
        f"- 最终归因来源：{result.final_decision_source}",
        f"- 置信度：{result.confidence if result.confidence is not None else '无'}",
        f"- 是否需要人工复核：{'是' if result.needs_human_review else '否'}",
        f"- 复核原因：{result.review_reason or '无'}",
        "## 代码与语言",
        f"- 语言：{language}",
        _format_code_block(completion_code, language),
        "## 解析 / 编译 / 测试",
        f"- 解析：{findings.get('parse_status', 'unknown')}",
        f"- 编译：{findings.get('compile_status', 'unknown')}",
        f"- 测试：{findings.get('test_status', 'unknown')}",
        "## 确定性信号",
        display_signals(result.deterministic_signals),
        "## 归因结论",
        f"- 主根因：{display_root_cause(result.root_cause)}",
        f"- 次根因：{display_root_cause(result.secondary_cause)}",
        f"- LLM 信号：{', '.join(result.llm_signals) if result.llm_signals else '无'}",
        "## 解释",
        result.explanation or "无",
        "## 可观察证据",
        _format_bullet_list(result.observable_evidence),
        "## 解析摘录",
        _format_excerpt_section(findings),
        "## 确定性分析摘要",
        f"- Canonical Diff：{findings.get('canonical_diff_summary', 'n/a')}",
        f"- Harness Alignment：{findings.get('test_harness_alignment_summary', 'n/a')}",
        "## 证据引用",
        _format_json_block(result.evidence_refs),
        "## 三层错因分析",
        _format_hierarchical_case_section(hierarchy),
        "## LLM 解析信息",
        f"- LLM 解析模式：{result.llm_parse_mode or '无'}",
        f"- LLM 解析原因：{result.llm_parse_reason or '无'}",
        f"- 原始回复文件：{result.llm_raw_response_path or '无'}",
        f"- 原始回复 SHA256：{result.llm_raw_response_sha256 or '无'}",
        _format_optional_code_block(result.llm_raw_response_excerpt, "json"),
        "## 警告",
        _format_bullet_list(result.warnings),
        "## 调试建议",
        _format_bullet_list(result.improvement_hints),
    ]
    return "\n".join(lines) + "\n"


def _format_code_block(code: str, language: str) -> str:
    if not code:
        return "_无代码_"
    return f"```{language or ''}\n{code}\n```"


def _format_optional_code_block(content: str | None, language: str = "") -> str:
    if not content:
        return "- 原始回复摘录：无"
    return f"- 原始回复摘录：\n```{language}\n{content}\n```"


def _format_bullet_list(items: list[str]) -> str:
    if not items:
        return "- 无"
    return "\n".join(f"- {item}" for item in items)


def _format_json_block(payload) -> str:
    if not payload:
        return "_无_"
    return f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"


def _format_excerpt_section(findings: dict) -> str:
    excerpts = []
    for label, key in (
        ("失败断言", "failing_assert_excerpt"),
        ("运行时报错", "runtime_error_excerpt"),
        ("语法解析错误", "parse_error_excerpt"),
    ):
        value = findings.get(key)
        if value:
            excerpts.append(f"### {label}\n```\n{value}\n```")
    return "\n\n".join(excerpts) if excerpts else "- 无"


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



def _format_root_cause_mapping(mapping: dict, *, total: int) -> str:
    if not mapping:
        return "- 无"
    return _format_distribution_block(
        [(display_root_cause(key), value) for key, value in mapping.items()],
        total=total,
        percent_label="占可归因失败比例",
    )



def _format_signal_mapping(mapping: dict, *, total: int) -> str:
    if not mapping:
        return "- 无"
    return _format_distribution_block(
        [(display_signal(key), value) for key, value in mapping.items()],
        total=total,
        percent_label="占失败样本比例",
    )



def _format_nested_mapping(mapping: dict, *, total: int) -> str:
    if not mapping:
        return "- 无"
    lines = []
    for key, value in mapping.items():
        lines.append(f"## {display_signal(key)}")
        lines.append(
            _format_distribution_block(
                [(display_root_cause(inner), count) for inner, count in value.items()],
                total=total,
                percent_label="占可归因失败比例",
            )
        )
    return "\n".join(lines)



def _format_slice_mapping(mapping: dict, *, total: int) -> str:
    if not mapping:
        return "- 无"
    lines = []
    for slice_key, values in mapping.items():
        lines.append(f"## {slice_key}")
        for inner, counts in values.items():
            lines.append(f"### {inner}")
            lines.append(
                _format_distribution_block(
                    [(display_root_cause(root), count) for root, count in counts.items()],
                    total=total,
                    percent_label="占可归因失败比例",
                )
            )
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


def _format_job_status_section(run_context: dict) -> str:
    counts = run_context.get("job_status_counts") or {}
    lines = [
        f"- job_status_counts: {counts if counts else '无'}",
        f"- 待处理 LLM backlog：{run_context.get('pending_llm_backlog', 0)}",
    ]
    return "\n".join(lines)


def _format_health_summary(summary: dict | None) -> str:
    if not summary:
        return "- 无"
    lines = [
        f"- 运行健康度：{summary.get('run_health', 'unknown')}",
        f"- 可交付：{'是' if summary.get('ready_for_delivery') else '否'}",
        f"- finalized 覆盖率：{summary.get('finalized_ratio', '0.0%')}",
    ]
    blocking_issues = summary.get("blocking_issues") or []
    warnings = summary.get("warnings") or []
    lines.append(f"- 阻塞项：{blocking_issues if blocking_issues else '无'}")
    lines.append(f"- 告警项：{warnings if warnings else '无'}")
    return "\n".join(lines)


def _format_capability_snapshot(snapshot: dict | None) -> str:
    if not snapshot:
        return "- 无"
    runners = snapshot.get("runners") or {}
    runner_lines = [
        f"- {language}: available={details.get('available', False)}, runtime_execution={details.get('runtime_execution', False)}, toolchain={details.get('toolchain') or '无'}"
        for language, details in runners.items()
    ]
    return "\n".join(
        [
            f"- sandbox: {snapshot.get('sandbox', {}).get('available', False)}",
            f"- llm: {snapshot.get('llm', {})}",
            *runner_lines,
        ]
    )


def _format_failure_taxonomy(taxonomy: dict | None) -> str:
    if not taxonomy:
        return "- 无"
    return "\n".join(
        [
            f"- case_status_counts: {taxonomy.get('case_status_counts') or {}}",
            f"- llm: {taxonomy.get('llm') or {}}",
            f"- warnings: {taxonomy.get('warnings') or {}}",
        ]
    )


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


def _format_hierarchy_mapping(mapping: dict, *, level: str | None = None, total: int) -> str:
    if not mapping:
        return "- 无"
    return _format_distribution_block(
        [
            (_display_hierarchy_code(level, item) if level else item, count)
            for item, count in mapping.items()
        ],
        total=total,
        percent_label="占可归因失败比例",
    )


def _format_hierarchy_summary(summary: SummaryReport, *, total: int) -> str:
    sections = [
        "## L1 表层错误",
        _format_hierarchy_mapping(summary.hierarchy_counts.get("l1", {}), level="l1", total=total),
        "## L2 过程阶段错误原因",
        _format_hierarchy_mapping(summary.hierarchy_counts.get("l2", {}), level="l2", total=total),
        "## L3 根能力项原因",
        _format_hierarchy_mapping(summary.hierarchy_counts.get("l3", {}), level="l3", total=total),
    ]
    return "\n".join(sections)


def _format_count_share_table(rows: list[tuple[str, int]], *, total: int, percent_label: str) -> str:
    if not rows:
        return "- 无"
    lines = [f"| 类别 | 数量 | {percent_label} | 图示 |", "| --- | --- | --- | --- |"]
    for label, count in _sort_rows(rows):
        lines.append(f"| {label} | {count} | {_format_percent(count, total)} | {_make_bar(count, total)} |")
    return "\n".join(lines)


def _format_percent(count: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{(count / total) * 100:.1f}%"


def _format_review_queue_summary(case_ids: list[str], *, total: int) -> str:
    if not case_ids:
        return (
            "结论：当前没有样本进入人工复核。\n\n"
            "| 待复核数量 | 占失败样本比例 | 图示 | Case IDs |\n| --- | --- | --- | --- |\n| 0 | 0.0% |  | 无 |"
        )
    joined = ", ".join(str(case_id) for case_id in case_ids)
    count = len(case_ids)
    percent = _format_percent(count, total)
    return (
        f"结论：当前共有 {count} 个样本进入人工复核，占失败样本 {percent}。\n\n"
        "| 待复核数量 | 占失败样本比例 | 图示 | Case IDs |\n"
        "| --- | --- | --- | --- |\n"
        f"| {count} | {percent} | {_make_bar(count, total)} | {joined} |"
    )


def _format_distribution_block(rows: list[tuple[str, int]], *, total: int, percent_label: str) -> str:
    if not rows:
        return "- 无"
    sorted_rows = _sort_rows(rows)
    return "\n".join([
        _build_distribution_conclusion(sorted_rows, total, percent_label=percent_label),
        "",
        _format_count_share_table(sorted_rows, total=total, percent_label=percent_label),
    ])


def _build_distribution_conclusion(rows: list[tuple[str, int]], total: int, *, percent_label: str) -> str:
    if not rows:
        return "结论：当前没有可展示的统计项。"
    top_count = rows[0][1]
    leaders = [label for label, count in rows if count == top_count]
    top_percent = _format_percent(top_count, total)
    percent_subject = percent_label.removeprefix("占").removesuffix("比例")
    if len(rows) == 1:
        return f"结论：当前统计全部集中在「{rows[0][0]}」，占{percent_subject} {top_percent}。"
    if len(leaders) == len(rows):
        return f"结论：当前各类别分布均匀，最高占比为 {top_percent}。"
    if len(leaders) == 1:
        return f"结论：当前最突出的类别是「{leaders[0]}」，占{percent_subject} {top_percent}。"
    leader_text = "、".join(f"「{label}」" for label in leaders)
    return f"结论：当前最高频类别为 {leader_text}，并列占{percent_subject} {top_percent}。"


def _make_bar(count: int, total: int, *, width: int = 20) -> str:
    if total <= 0 or count <= 0:
        return ""
    steps = max(1, width // 2)
    filled = max(1, round((count / total) * steps))
    return ("●" * filled) + ("○" * max(0, steps - filled))


def _sort_rows(rows: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(rows, key=lambda item: (-item[1], item[0]))


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
