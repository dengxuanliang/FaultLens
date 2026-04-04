from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterator, Optional

from faultlens import __version__
from faultlens.deterministic.runners.base import sandbox_available
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
    run_warnings = run_store.list_run_warnings()
    ingest_events = run_store.list_ingest_events()
    input_warnings = [row["message"] for row in run_warnings] + [row["message"] for row in ingest_events]
    job_status_counts = run_store.count_jobs_by_status()
    case_counts = {"passed": 0, "attributable_failure": 0, "data_issue": 0, "join_issue": 0}
    for row in run_store.iter_final_result_rows():
        status = str(row.get("case_status", "unknown"))
        case_counts[status] = case_counts.get(status, 0) + 1
    capability_snapshot = _build_capability_snapshot(stored_settings)
    failure_taxonomy = _build_failure_taxonomy(
        case_counts=case_counts,
        job_status_counts=job_status_counts,
        run_warnings=run_warnings,
        ingest_events=ingest_events,
    )
    health_summary = _build_health_summary(
        summary=summary,
        case_counts=case_counts,
        job_status_counts=job_status_counts,
        input_warnings=input_warnings,
    )
    return {
        "input_files": [item["path"] for item in input_files],
        "role_detection": {item["path"]: item["detected_role"] for item in input_files},
        "faultlens_version": metadata.get("faultlens_version"),
        "git_commit": metadata.get("git_commit"),
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
        "capability_snapshot": capability_snapshot,
        "failure_taxonomy": failure_taxonomy,
        "health_summary": health_summary,
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


def inspect_output_dir(*, output_dir: Path) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    required_files = [
        "run.db",
        "analysis_report.md",
        "summary.json",
        "run_metadata.json",
        "case_analysis.jsonl",
        "hierarchical_root_cause_report.md",
    ]
    missing_artifacts = [name for name in required_files if not (output_dir / name).exists()]
    consistency_checks = _build_output_consistency_checks(output_dir)
    consistency_healthy = all(check.get("healthy", False) for check in consistency_checks.values())
    recommended_actions = _build_inspect_recommendations(
        missing_artifacts=missing_artifacts,
        consistency_checks=consistency_checks,
    )
    health = {
        "output_dir": str(output_dir),
        "healthy": not missing_artifacts and consistency_healthy,
        "missing_artifacts": missing_artifacts,
        "consistency_checks": consistency_checks,
        "recommended_actions": recommended_actions,
        "faultlens_version": __version__,
        "git_commit": _detect_git_commit(output_dir),
    }
    if (output_dir / "run.db").exists():
        run_store = RunStore(output_dir / "run.db").open()
        try:
            metadata = run_store.load_run_metadata()
            health["run_metadata_present"] = True
            health["run_id"] = metadata.get("run_id")
            health["analysis_version"] = metadata.get("analysis_version")
            health["prompt_version"] = metadata.get("prompt_version")
        finally:
            run_store.close()
    else:
        health["run_metadata_present"] = False
    return health


def diagnose_environment(*, output_dir: Path) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    return {
        "output_dir": str(output_dir),
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "sandbox": {
            "available": sandbox_available(),
            "implementation": shutil.which("sandbox-exec"),
        },
        "runners": _build_capability_snapshot({}).get("runners", {}),
        "llm_env": {
            "api_key_present": bool(os.environ.get("FAULTLENS_API_KEY")),
            "base_url_present": bool(os.environ.get("FAULTLENS_BASE_URL")),
            "model_present": bool(os.environ.get("FAULTLENS_MODEL")),
        },
        "artifacts": {
            "output_dir_exists": output_dir.exists(),
            "run_db_exists": (output_dir / "run.db").exists(),
        },
    }


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


def _build_output_consistency_checks(output_dir: Path) -> Dict[str, Any]:
    checks = {
        "case_analysis": {"healthy": False, "row_count": 0, "case_ids": []},
        "case_markdown": {"healthy": False, "missing_case_ids": [], "unexpected_case_ids": []},
        "summary": {"healthy": False},
        "run_metadata": {"healthy": False},
        "exemplars": {"healthy": False, "missing_files": [], "unexpected_files": []},
        "llm_raw_responses": {"healthy": False, "missing_paths": [], "unexpected_paths": []},
        "manifests": {"healthy": False, "missing": []},
    }

    case_analysis_path = output_dir / "case_analysis.jsonl"
    if not case_analysis_path.exists():
        return checks

    rows = []
    with case_analysis_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            rows.append(json.loads(raw))
    case_ids = sorted(str(row.get("case_id")) for row in rows)
    checks["case_analysis"] = {
        "healthy": True,
        "row_count": len(rows),
        "case_ids": case_ids,
    }

    case_dir = output_dir / "cases"
    rendered_case_ids = sorted(path.stem for path in case_dir.glob("*.md")) if case_dir.exists() else []
    missing_case_ids = sorted(case_id for case_id in case_ids if case_id not in rendered_case_ids)
    unexpected_case_ids = sorted(case_id for case_id in rendered_case_ids if case_id not in case_ids)
    checks["case_markdown"] = {
        "healthy": not missing_case_ids and not unexpected_case_ids,
        "expected_count": len(case_ids),
        "rendered_count": len(rendered_case_ids),
        "missing_case_ids": missing_case_ids,
        "unexpected_case_ids": unexpected_case_ids,
    }

    summary_path = output_dir / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        derived_total_cases = len(rows)
        reported_total_cases = int(summary.get("total_cases", -1))
        checks["summary"] = {
            "healthy": reported_total_cases == derived_total_cases,
            "reported_total_cases": reported_total_cases,
            "derived_total_cases": derived_total_cases,
        }
        expected_exemplars = sorted(
            f"{root_cause.replace('/', '-')}-{case_id}.md"
            for root_cause, case_ids in (summary.get("exemplars") or {}).items()
            for case_id in case_ids[:1]
        )
        rendered_exemplars = sorted(path.name for path in (output_dir / "exemplars").glob("*.md")) if (output_dir / "exemplars").exists() else []
        missing_exemplars = sorted(name for name in expected_exemplars if name not in rendered_exemplars)
        unexpected_exemplars = sorted(name for name in rendered_exemplars if name not in expected_exemplars)
        checks["exemplars"] = {
            "healthy": not missing_exemplars and not unexpected_exemplars,
            "expected_count": len(expected_exemplars),
            "rendered_count": len(rendered_exemplars),
            "missing_files": missing_exemplars,
            "unexpected_files": unexpected_exemplars,
        }

    expected_raw_paths = sorted(
        str(row.get("llm_raw_response_path"))
        for row in rows
        if row.get("llm_raw_response_path")
    )
    rendered_raw_paths = sorted(
        str(path.relative_to(output_dir))
        for path in (output_dir / "llm_raw_responses").glob("*")
        if path.is_file()
    ) if (output_dir / "llm_raw_responses").exists() else []
    missing_raw_paths = sorted(path for path in expected_raw_paths if path not in rendered_raw_paths)
    unexpected_raw_paths = sorted(path for path in rendered_raw_paths if path not in expected_raw_paths)
    checks["llm_raw_responses"] = {
        "healthy": not missing_raw_paths and not unexpected_raw_paths,
        "expected_count": len(expected_raw_paths),
        "rendered_count": len(rendered_raw_paths),
        "missing_paths": missing_raw_paths,
        "unexpected_paths": unexpected_raw_paths,
    }

    run_metadata_path = output_dir / "run_metadata.json"
    if run_metadata_path.exists():
        run_metadata = json.loads(run_metadata_path.read_text(encoding="utf-8"))
        derived_case_counts: Dict[str, int] = {}
        for row in rows:
            status = str(row.get("case_status", "unknown"))
            derived_case_counts[status] = derived_case_counts.get(status, 0) + 1
        reported_case_counts = dict(run_metadata.get("case_counts") or {})
        normalized_keys = sorted(set(reported_case_counts) | set(derived_case_counts))
        normalized_reported_case_counts = {
            key: int(reported_case_counts.get(key, 0))
            for key in normalized_keys
        }
        normalized_derived_case_counts = {
            key: int(derived_case_counts.get(key, 0))
            for key in normalized_keys
        }
        checks["run_metadata"] = {
            "healthy": normalized_reported_case_counts == normalized_derived_case_counts,
            "reported_case_counts": normalized_reported_case_counts,
            "derived_case_counts": normalized_derived_case_counts,
        }

    manifest_missing = [
        name
        for name in ("input_manifest.json", "analysis_manifest.json")
        if not (output_dir / name).exists()
    ]
    checks["manifests"] = {
        "healthy": not manifest_missing,
        "missing": manifest_missing,
    }
    return checks


def _build_inspect_recommendations(*, missing_artifacts: list[str], consistency_checks: Dict[str, Any]) -> list[str]:
    actions: list[str] = []
    report_artifacts = {
        "analysis_report.md",
        "summary.json",
        "run_metadata.json",
        "case_analysis.jsonl",
        "hierarchical_root_cause_report.md",
    }
    if any(name in report_artifacts for name in missing_artifacts):
        actions.append("run `faultlens rerender --output-dir ...` to regenerate report artifacts")
    if "run.db" in missing_artifacts:
        actions.append("missing `run.db` cannot be repaired by rerender; rerun `faultlens analyze` with the original inputs")

    manifests = consistency_checks.get("manifests") or {}
    if not manifests.get("healthy", True):
        actions.append("rerun `faultlens analyze` with the original inputs to rebuild missing manifests")

    case_markdown = consistency_checks.get("case_markdown") or {}
    if not case_markdown.get("healthy", True):
        actions.append("run `faultlens rerender --output-dir ...` to rebuild per-case markdown exports")

    summary = consistency_checks.get("summary") or {}
    run_metadata = consistency_checks.get("run_metadata") or {}
    exemplars = consistency_checks.get("exemplars") or {}
    if not summary.get("healthy", True) or not run_metadata.get("healthy", True) or not exemplars.get("healthy", True):
        actions.append("run `faultlens rerender --output-dir ...` to resynchronize summary, metadata, and exemplar exports")

    raw_responses = consistency_checks.get("llm_raw_responses") or {}
    if not raw_responses.get("healthy", True):
        actions.append("missing raw LLM responses cannot be reconstructed from exported markdown; rerun `faultlens analyze --resume` or a fresh `analyze` if audit retention matters")

    deduped: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if action in seen:
            continue
        seen.add(action)
        deduped.append(action)
    return deduped


def _build_capability_snapshot(settings: Dict[str, Any]) -> Dict[str, Any]:
    sandbox = sandbox_available()
    llm_configured = bool(settings.get("llm_enabled"))
    return {
        "sandbox": {"available": sandbox},
        "llm": {
            "configured": llm_configured,
            "mode": "enabled" if llm_configured else "deterministic_only",
            "model": settings.get("model"),
        },
        "runners": {
            "python": {
                "available": sandbox,
                "runtime_execution": sandbox,
                "toolchain": sys.executable,
            },
            "cpp": {
                "available": sandbox and bool(shutil.which("g++") or shutil.which("clang++")),
                "runtime_execution": sandbox,
                "toolchain": shutil.which("g++") or shutil.which("clang++"),
            },
            "java": {
                "available": sandbox and bool(shutil.which("javac")) and bool(shutil.which("java")),
                "runtime_execution": sandbox,
                "toolchain": {"javac": shutil.which("javac"), "java": shutil.which("java")},
            },
            "go": {
                "available": sandbox and bool(shutil.which("go")),
                "runtime_execution": sandbox,
                "toolchain": shutil.which("go"),
            },
        },
    }


def _build_failure_taxonomy(
    *,
    case_counts: Dict[str, int],
    job_status_counts: Dict[str, int],
    run_warnings: list[dict[str, Any]],
    ingest_events: list[dict[str, Any]],
) -> Dict[str, Any]:
    warning_counts: Dict[str, int] = {}
    for row in run_warnings:
        stage = str(row.get("stage") or "unknown")
        warning_counts[stage] = warning_counts.get(stage, 0) + 1
    return {
        "case_status_counts": case_counts,
        "llm": {
            "pending": int(job_status_counts.get("llm_pending", 0)),
            "running": int(job_status_counts.get("llm_running", 0)),
            "retryable": int(job_status_counts.get("llm_failed_retryable", 0)),
            "terminal": int(job_status_counts.get("llm_failed_terminal", 0)),
        },
        "warnings": {
            **warning_counts,
            "ingest": len(ingest_events),
        },
    }


def _build_health_summary(*, summary, case_counts: Dict[str, int], job_status_counts: Dict[str, int], input_warnings: list[str]) -> Dict[str, Any]:
    total_cases = int(getattr(summary, "total_cases", 0) or 0)
    finalized_count = int(job_status_counts.get("finalized", 0))
    finalized_ratio_value = (finalized_count / total_cases * 100) if total_cases else 100.0
    pending_backlog = sum(
        int(job_status_counts.get(status, 0))
        for status in ("llm_pending", "llm_running", "llm_failed_retryable")
    )
    terminal_failures = int(job_status_counts.get("llm_failed_terminal", 0))
    review_queue = list(getattr(summary, "review_queue", []) or [])

    blocking_issues: list[str] = []
    warnings: list[str] = []
    if pending_backlog > 0:
        blocking_issues.append(f"pending llm backlog: {pending_backlog}")
    if total_cases and finalized_count < total_cases:
        blocking_issues.append(f"finalized coverage incomplete: {finalized_count}/{total_cases}")
    if terminal_failures > 0:
        warnings.append(f"terminal llm failures: {terminal_failures}")
    if review_queue:
        warnings.append(f"{len(review_queue)} case requires human review" if len(review_queue) == 1 else f"{len(review_queue)} cases require human review")
    if input_warnings:
        warnings.append(f"input warnings present: {len(input_warnings)}")

    if blocking_issues:
        run_health = "blocked"
    elif warnings:
        run_health = "warning"
    else:
        run_health = "healthy"

    return {
        "run_health": run_health,
        "ready_for_delivery": not blocking_issues,
        "finalized_ratio": f"{finalized_ratio_value:.1f}%",
        "finalized_count": finalized_count,
        "total_cases": total_cases,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
    }


def build_provenance() -> Dict[str, Any]:
    return {
        "faultlens_version": __version__,
        "git_commit": _detect_git_commit(Path(__file__).resolve().parents[3]),
    }


def _detect_git_commit(base_path: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(base_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip()
    return value or None
