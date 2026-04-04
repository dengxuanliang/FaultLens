from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from faultlens.llm.adaptive_parser import parse_attribution_response
from faultlens.models import AttributionResult
from faultlens.reporting.aggregate import SummaryAccumulator
from faultlens.reporting.render import render_case_report
from faultlens.scale.run_store import RunStore


def result_from_row(row: Dict[str, Any]) -> AttributionResult:
    return AttributionResult(**row)


def summarize_results_from_store(run_store: RunStore):
    summary_accumulator = SummaryAccumulator()
    for row in run_store.iter_final_result_rows():
        summary_accumulator.add(result_from_row(row))
    return summary_accumulator.to_summary()


def build_run_context(
    *,
    run_store: RunStore,
    summary,
    llm_warnings: list[str],
    llm_response_stats: Dict[str, Any],
    execution_mode: str,
) -> Dict[str, Any]:
    metadata = run_store.load_run_metadata()
    stored_settings = metadata.get("settings_json") or {}
    input_files = run_store.load_input_files()
    input_warnings = [row["message"] for row in run_store.list_run_warnings()] + [
        row["message"] for row in run_store.list_ingest_events()
    ]
    job_status_counts = run_store.count_jobs_by_status()
    case_counts = {"passed": 0, "attributable_failure": 0, "data_issue": 0, "join_issue": 0}
    for row in run_store.iter_final_result_rows():
        status = str(row.get("case_status", "unknown"))
        case_counts[status] = case_counts.get(status, 0) + 1
    return {
        "input_files": [item["path"] for item in input_files],
        "role_detection": {item["path"]: item["detected_role"] for item in input_files},
        "join_stats": {
            "joined": summary.total_cases - case_counts.get("join_issue", 0),
            "join_issue": case_counts.get("join_issue", 0),
        },
        "case_counts": case_counts,
        "model_summary": metadata.get("settings_json", {}).get("model") or metadata.get("faultlens_version") or "deterministic-only",
        "input_warnings": input_warnings,
        "llm_warnings": llm_warnings,
        "llm_response_stats": llm_response_stats,
        "llm_max_workers": stored_settings.get("llm_max_workers"),
        "job_status_counts": job_status_counts,
        "pending_llm_backlog": sum(
            int(job_status_counts.get(status, 0))
            for status in ("llm_pending", "llm_running", "llm_failed_retryable")
        ),
        "execution_mode": execution_mode,
    }


def rebuild_llm_state_from_store(run_store: RunStore, *, stats_factory) -> tuple[list[str], Dict[str, Any]]:
    warnings: list[str] = []
    stats = stats_factory()
    for row in run_store.iter_llm_attempt_rows():
        warning = row.get("error_message")
        if warning:
            warnings.append(warning)
        response_text = _read_response_text(run_store, row.get("response_path"))
        _update_stats(
            stats,
            str(row.get("case_id")),
            status=row.get("parse_mode"),
            reason=row.get("parse_reason"),
            excerpt=_excerpt_text(response_text),
        )
    if stats["attempted"]:
        stats["nonconforming_percentage"] = round(
            stats["nonconforming"] / stats["attempted"] * 100, 2
        )
    return warnings, stats


def load_selected_llm_result(run_store: RunStore, case_id: str) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    attempts = run_store._load_llm_attempt_rows(case_id)
    if not attempts:
        return None, {
            "status": None,
            "invalid_reason": None,
            "raw_response_excerpt": None,
            "raw_response_path": None,
            "raw_response_sha256": None,
        }
    selected = next((row for row in attempts if row.get("is_selected")), attempts[-1])
    response_text = _read_response_text(run_store, selected.get("response_path"))
    parsed_payload = selected.get("selected_payload_json")
    if parsed_payload is None and response_text:
        parsed = parse_attribution_response(response_text)
        if parsed.payload:
            parsed_payload = parsed.payload
    return parsed_payload, {
        "status": selected.get("parse_mode"),
        "invalid_reason": selected.get("parse_reason"),
        "raw_response_excerpt": _excerpt_text(response_text),
        "raw_response_path": selected.get("response_path"),
        "raw_response_sha256": selected.get("response_sha256"),
    }


def export_case_report(*, output_dir: Path, case_id: str, dest: Path | None = None) -> Path:
    output_dir = Path(output_dir)
    run_store = RunStore(output_dir / "run.db").open()
    try:
        row = run_store.load_final_result_row(str(case_id))
        result = result_from_row(row)
    finally:
        run_store.close()

    destination = Path(dest) if dest is not None else output_dir / "cases" / f"{case_id}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_case_report(result), encoding="utf-8")
    return destination


def load_run_status(*, output_dir: Path, stats_factory) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    run_store = RunStore(output_dir / "run.db").open()
    try:
        summary = summarize_results_from_store(run_store)
        llm_warnings, llm_response_stats = rebuild_llm_state_from_store(run_store, stats_factory=stats_factory)
        return build_run_context(
            run_store=run_store,
            summary=summary,
            llm_warnings=llm_warnings,
            llm_response_stats=llm_response_stats,
            execution_mode="status",
        )
    finally:
        run_store.close()


def iter_results(case_analysis_path: Path) -> Iterator[AttributionResult]:
    with Path(case_analysis_path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            yield result_from_row(json.loads(raw))


def _excerpt_text(text: str | None, *, limit: int = 200) -> str | None:
    if not text:
        return None
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _read_response_text(run_store: RunStore, response_path: str | None) -> str | None:
    if not response_path:
        return None
    raw_path = run_store.path.parent / response_path
    if not raw_path.exists():
        return None
    return raw_path.read_text(encoding="utf-8")


def _update_stats(stats: Dict[str, Any], case_id: str, *, status: str | None, reason: str | None, excerpt: str | None) -> None:
    stats["attempted"] += 1
    if excerpt and len(stats["raw_response_excerpts"]) < 5:
        stats["raw_response_excerpts"].append({"case_id": case_id, "mode": status, "reason": reason, "excerpt": excerpt})
    if status == "strict_json":
        stats["strict_json"] += 1
    elif status == "adaptive_parse":
        stats["adaptive_parse"] += 1
        stats["nonconforming"] += 1
        _increment_reason(stats["nonconforming_reasons"], reason or "adaptive_parse")
    elif status == "salvaged":
        stats["salvaged"] += 1
        stats["nonconforming"] += 1
        _increment_reason(stats["nonconforming_reasons"], reason or "salvaged")
    elif status == "invalid":
        stats["skipped_invalid"] += 1
        stats["nonconforming"] += 1
        _increment_reason(stats["nonconforming_reasons"], reason or "invalid")
    elif status == "request_error":
        stats["request_errors"] += 1


def _increment_reason(counter: Dict[str, int], reason: str) -> None:
    counter[reason] = counter.get(reason, 0) + 1
