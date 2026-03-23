from __future__ import annotations

from faultlens.models import AttributionResult, SummaryReport


def render_analysis_report(summary: SummaryReport, results: list[AttributionResult], run_context: dict | None = None) -> str:
    run_context = run_context or {}
    sections = [
        "# Run Summary\n"
        f"- Inputs: {', '.join(run_context.get('input_files', [])) or 'unknown'}\n"
        f"- Role detection: {run_context.get('role_detection', {})}\n"
        f"- Join stats: {run_context.get('join_stats', {})}\n"
        f"- Case counts: {run_context.get('case_counts', {})}\n"
        f"- Model config: {run_context.get('model_summary', 'deterministic-only')}\n"
        f"- Total cases: {summary.total_cases}",
        "# Deterministic Analysis Summary\n" + _format_mapping(summary.deterministic_signal_counts),
        "# LLM Root Cause Distribution\n" + _format_mapping(summary.root_cause_counts),
        "# Cross Analysis\n" + _format_nested_mapping(summary.cross_analysis),
        "# Slice Analysis\n" + _format_slice_mapping(summary.slices),
        "# Representative Exemplars\n" + _format_mapping(summary.exemplars),
        "# Review Queue\n" + ("\n".join(f"- {item}" for item in summary.review_queue) if summary.review_queue else "- none"),
        "# Input Warnings\n" + ("\n".join(f"- {item}" for item in run_context.get("input_warnings", [])) if run_context.get("input_warnings") else "- none"),
        "# LLM Warnings\n" + ("\n".join(f"- {item}" for item in run_context.get("llm_warnings", [])) if run_context.get("llm_warnings") else "- none"),
    ]
    return "\n\n".join(sections) + "\n"


def render_case_report(result: AttributionResult) -> str:
    findings = result.deterministic_findings
    lines = [
        f"# Case {result.case_id}",
        "## Basics",
        f"- Case status: {result.case_status}",
        f"- Accepted: {result.accepted}",
        "## Language",
        str(findings.get("primary_language", "unknown")),
        "## Completion Code",
        str(findings.get("completion_code", "")),
        "## Parse / Compile / Test",
        f"- Parse: {findings.get('parse_status', 'unknown')}",
        f"- Compile: {findings.get('compile_status', 'unknown')}",
        f"- Test: {findings.get('test_status', 'unknown')}",
        "## Deterministic Signals",
        ", ".join(result.deterministic_signals) if result.deterministic_signals else "none",
        "## Root Cause",
        str(result.root_cause),
        "## Explanation",
        result.explanation,
        "## Canonical Diff",
        str(findings.get("canonical_diff_summary", "n/a")),
        "## Harness Alignment",
        str(findings.get("test_harness_alignment_summary", "n/a")),
        "## Evidence Refs",
        str(result.evidence_refs),
        "## Warnings",
        ("\n".join(f"- {warning}" for warning in result.warnings) if result.warnings else "- none"),
        "## Debug Hints",
        "\n".join(f"- {hint}" for hint in result.improvement_hints) if result.improvement_hints else "- none",
    ]
    return "\n".join(lines) + "\n"


def _format_mapping(mapping: dict) -> str:
    if not mapping:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in mapping.items())


def _format_nested_mapping(mapping: dict) -> str:
    if not mapping:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in mapping.items())


def _format_slice_mapping(mapping: dict) -> str:
    if not mapping:
        return "- none"
    return "\n".join(f"- {slice_key}: {values}" for slice_key, values in mapping.items())
