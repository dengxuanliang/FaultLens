from __future__ import annotations

from typing import Iterable

from faultlens.models import AttributionResult, SummaryReport


def render_analysis_report(summary: SummaryReport, results: list[AttributionResult]) -> str:
    sections = [
        "# Run Summary\n"
        f"- Total cases: {summary.total_cases}\n"
        f"- Root causes tracked: {len(summary.root_cause_counts)}\n"
        f"- Review queue size: {len(summary.review_queue)}",
        "# Deterministic Analysis Summary\n" + _format_mapping(summary.deterministic_signal_counts),
        "# LLM Root Cause Distribution\n" + _format_mapping(summary.root_cause_counts),
        "# Cross Analysis\n" + _format_nested_mapping(summary.cross_analysis),
        "# Slice Analysis\n" + _format_slice_mapping(summary.slices),
        "# Representative Exemplars\n" + _format_mapping(summary.exemplars),
        "# Review Queue\n" + ("\n".join(f"- {item}" for item in summary.review_queue) if summary.review_queue else "- none"),
    ]
    return "\n\n".join(sections) + "\n"


def render_case_report(result: AttributionResult) -> str:
    findings = result.deterministic_findings
    lines = [
        f"# Case {result.case_id}",
        "## Language",
        str(findings.get("primary_language", "unknown")),
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
    sections = []
    for key, value in mapping.items():
        sections.append(f"- {key}: {value}")
    return "\n".join(sections)


def _format_slice_mapping(mapping: dict) -> str:
    if not mapping:
        return "- none"
    rows = []
    for slice_key, values in mapping.items():
        rows.append(f"- {slice_key}: {values}")
    return "\n".join(rows)
