from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from typing import Any, Dict, Iterable, Iterator, Optional

from faultlens.attribution.engine import build_final_case_result
from faultlens.config import Settings
from faultlens.deterministic.pipeline import analyze_case_deterministically, analyze_cases_deterministically
from faultlens.deterministic.runners.registry import build_runner_registry
from faultlens.ingest.jsonl import JsonlScanObserver, iter_jsonl_records
from faultlens.ingest.resolver import detect_input_roles
from faultlens.llm.client import LLMClient
from faultlens.llm.adaptive_parser import parse_attribution_response
from faultlens.llm.prompting import PROMPT_VERSION, build_attribution_messages
from faultlens.models import AttributionResult, CaseRecord, DeterministicFindings, EvaluationInfo, TaskInfo
from faultlens.normalize.failure_gate import apply_failure_gate
from faultlens.normalize.joiner import build_ingest_snapshot, build_ingest_snapshot_with_manifest, iter_joined_cases_from_store
from faultlens.reporting.aggregate import SummaryAccumulator
from faultlens.reporting.render import (
    render_analysis_report,
    render_case_report,
    write_hierarchical_root_cause_report,
)
from faultlens.scale.run_store import RunStore


ANALYSIS_VERSION = "deterministic-v2"
LLM_LEASE_SECONDS = 300



def run_analysis(
    *,
    input_paths: Iterable[Path],
    settings: Settings,
    output_dir: Path,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    input_paths = [Path(path) for path in input_paths]
    resolved = detect_input_roles(input_paths)
    input_metadata = _build_input_metadata(input_paths, resolved.detected_roles)

    _prepare_output_dir(output_dir, resume=settings.resume)
    run_store = RunStore(output_dir / "run.db").open()
    resume_run = settings.resume and run_store.has_run_metadata()
    if resume_run:
        input_snapshots = _build_input_snapshots(input_paths, resolved.detected_roles)
        run_store.assert_resume_safe(
            current_inputs=input_snapshots,
            analysis_version=ANALYSIS_VERSION,
            prompt_version=PROMPT_VERSION,
        )
        run_store.requeue_expired_leases(now=_utcnow_iso())
        run_store.expire_retryable_jobs(
            now=_utcnow_iso(),
            max_attempts=_max_llm_attempts(settings),
        )
        run_store.requeue_retryable_jobs(now=_utcnow_iso())
    else:
        run_store.initialize_run_metadata(
            analysis_version=ANALYSIS_VERSION,
            prompt_version=PROMPT_VERSION,
            settings={
                "model": settings.model,
                "llm_max_workers": settings.llm_max_workers,
                "llm_max_retries": settings.llm_max_retries,
                "llm_retry_backoff_seconds": settings.llm_retry_backoff_seconds,
                "llm_retry_on_5xx": settings.llm_retry_on_5xx,
                "resume": settings.resume,
            },
        )
        (output_dir / "analysis_manifest.json").write_text(
            json.dumps(
                {
                    "analysis_version": ANALYSIS_VERSION,
                    "prompt_version": PROMPT_VERSION,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if run_store.count_joined_cases() == 0:
        if resume_run:
            build_ingest_snapshot(run_store, resolved.inference_path, resolved.results_path)
        else:
            input_snapshots = build_ingest_snapshot_with_manifest(
                run_store,
                resolved.inference_path,
                resolved.results_path,
                input_metadata=input_metadata,
            )
            run_store.replace_input_files(input_snapshots)
            (output_dir / "input_manifest.json").write_text(json.dumps(input_snapshots, ensure_ascii=False, indent=2), encoding="utf-8")

    case_analysis_path = output_dir / "case_analysis.jsonl"
    cases_dir = output_dir / "cases"
    exemplars_dir = output_dir / "exemplars"
    llm_raw_responses_dir = output_dir / "llm_raw_responses"
    cases_dir.mkdir(parents=True, exist_ok=True)
    exemplars_dir.mkdir(parents=True, exist_ok=True)
    llm_raw_responses_dir.mkdir(parents=True, exist_ok=True)

    summary_accumulator = SummaryAccumulator()
    case_status_counts = {"passed": 0, "attributable_failure": 0, "data_issue": 0, "join_issue": 0}
    if settings.resume:
        for row in run_store.iter_final_result_rows():
            result = _result_from_row(row)
            summary_accumulator.add(result)
            case_status_counts[result.case_status] = case_status_counts.get(result.case_status, 0) + 1
        llm_warnings, llm_response_stats = _rebuild_llm_state_from_store(run_store)
    else:
        llm_warnings = []
        llm_response_stats = _initial_llm_response_stats()

    with case_analysis_path.open("w", encoding="utf-8") as result_handle:
        if settings.resume:
            for row in run_store.iter_final_result_rows():
                result_handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        llm_enabled = bool(settings.api_key and settings.base_url and settings.model)
        _run_deterministic_stage(
            run_store=run_store,
            settings=settings,
            llm_enabled=llm_enabled,
        )

        with ThreadPoolExecutor(max_workers=settings.llm_max_workers) as executor:
            batch: list[dict[str, Any]] = []
            for item in _iter_llm_pending_items(run_store):
                batch.append(item)
                if len(batch) >= max(1, settings.llm_max_workers * 2):
                    _flush_llm_batch(
                        batch=batch,
                        settings=settings,
                        executor=executor,
                        summary_accumulator=summary_accumulator,
                        case_status_counts=case_status_counts,
                        llm_warnings=llm_warnings,
                        llm_response_stats=llm_response_stats,
                        result_handle=result_handle,
                        checkpoint=None,
                        llm_raw_responses_dir=llm_raw_responses_dir,
                        run_store=run_store,
                    )
                    batch = []
            if batch:
                    _flush_llm_batch(
                        batch=batch,
                        settings=settings,
                        executor=executor,
                        summary_accumulator=summary_accumulator,
                        case_status_counts=case_status_counts,
                        llm_warnings=llm_warnings,
                        llm_response_stats=llm_response_stats,
                        result_handle=result_handle,
                        checkpoint=None,
                        llm_raw_responses_dir=llm_raw_responses_dir,
                        run_store=run_store,
                    )

        _finalize_pending_results(
            run_store=run_store,
            result_handle=result_handle,
            checkpoint=None,
            summary_accumulator=summary_accumulator,
            case_status_counts=case_status_counts,
            llm_warnings=llm_warnings,
            llm_response_stats=llm_response_stats,
        )

    if llm_response_stats["attempted"]:
        llm_response_stats["nonconforming_percentage"] = round(
            llm_response_stats["nonconforming"] / llm_response_stats["attempted"] * 100, 2
        )

    summary = finalize_outputs(
        output_dir=output_dir,
        case_id=case_id,
        llm_warnings=llm_warnings,
        llm_response_stats=llm_response_stats,
        checkpoint_path=None,
        execution_mode="streaming",
        run_store=run_store,
    )
    run_store.close()
    return {
        "resolved": resolved,
        "summary": summary,
        "output_dir": output_dir,
        "llm_warnings": llm_warnings,
        "llm_response_stats": llm_response_stats,
    }


def finalize_outputs(
    *,
    output_dir: Path,
    case_id: Optional[str] = None,
    llm_warnings: Optional[list[str]] = None,
    llm_response_stats: Optional[Dict[str, Any]] = None,
    checkpoint_path: Path | None = None,
    execution_mode: str = "rerender",
    run_store: RunStore | None = None,
):
    should_close = False
    output_dir = Path(output_dir)
    if run_store is None:
        run_store = RunStore(output_dir / "run.db").open()
        should_close = True
    try:
        _export_case_analysis_from_store(run_store, output_dir / "case_analysis.jsonl")
        summary = _summarize_results_from_store(run_store)
        if llm_warnings is None or llm_response_stats is None:
            rebuilt_warnings, rebuilt_stats = _rebuild_llm_state_from_store(run_store)
            llm_warnings = rebuilt_warnings if llm_warnings is None else llm_warnings
            llm_response_stats = rebuilt_stats if llm_response_stats is None else llm_response_stats
        run_context = _build_run_context(
            run_store=run_store,
            summary=summary,
            llm_warnings=llm_warnings,
            llm_response_stats=llm_response_stats,
            checkpoint_path=checkpoint_path,
            execution_mode=execution_mode,
        )
        (output_dir / "analysis_report.md").write_text(
            render_analysis_report(summary, [], run_context),
            encoding="utf-8",
        )
        (output_dir / "summary.json").write_text(
            json.dumps(asdict(summary), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "run_metadata.json").write_text(
            json.dumps(run_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with (output_dir / "hierarchical_root_cause_report.md").open("w", encoding="utf-8") as handle:
            write_hierarchical_root_cause_report(handle, summary, _iter_results(output_dir / "case_analysis.jsonl"))

        cases_dir = output_dir / "cases"
        exemplars_dir = output_dir / "exemplars"
        cases_dir.mkdir(parents=True, exist_ok=True)
        exemplars_dir.mkdir(parents=True, exist_ok=True)
        exemplar_ids = {item for ids in summary.exemplars.values() for item in ids[:1]}
        if case_id:
            exemplar_ids.add(str(case_id))
        _render_selected_cases(output_dir / "case_analysis.jsonl", exemplar_ids, cases_dir, exemplars_dir)
        return summary
    finally:
        if should_close:
            run_store.close()



def _initial_llm_response_stats() -> Dict[str, Any]:
    return {
        "attempted": 0,
        "strict_json": 0,
        "adaptive_parse": 0,
        "salvaged": 0,
        "skipped_invalid": 0,
        "nonconforming": 0,
        "nonconforming_percentage": 0.0,
        "nonconforming_reasons": {},
        "request_errors": 0,
        "raw_response_excerpts": [],
    }



def _prepare_output_dir(output_dir: Path, *, resume: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        return
    for target in [
        output_dir / "analysis_report.md",
        output_dir / "summary.json",
        output_dir / "run_metadata.json",
        output_dir / "hierarchical_root_cause_report.md",
        output_dir / "case_analysis.jsonl",
        output_dir / "faultlens_checkpoint.sqlite3",
        output_dir / "run.db",
        output_dir / "input_manifest.json",
        output_dir / "analysis_manifest.json",
    ]:
        if target.exists():
            target.unlink()
    for directory in [output_dir / "cases", output_dir / "exemplars"]:
        if directory.exists():
            shutil.rmtree(directory)
    raw_responses_dir = output_dir / "llm_raw_responses"
    if raw_responses_dir.exists():
        shutil.rmtree(raw_responses_dir)


def _run_deterministic_stage(*, run_store: RunStore, settings: Settings, llm_enabled: bool) -> None:
    for joined_case in iter_joined_cases_from_store(run_store):
        current_case_id = str(joined_case.get("case_id"))
        if run_store.has_final_result(current_case_id):
            continue
        job = run_store.get_job(current_case_id)
        if job.get("job_status") != "ingested":
            continue

        gated = apply_failure_gate(joined_case)
        analyzed = analyze_cases_deterministically([gated], execution_timeout=settings.execution_timeout)[0]
        record = _to_case_record(analyzed)
        llm_required = bool(record.eligible_for_llm and llm_enabled)
        run_store.save_deterministic_result(
            case_id=record.case_id,
            case_status=record.case_status,
            failure_gate_warnings=list(analyzed.get("failure_gate_warnings", [])),
            deterministic_signals=list(analyzed.get("deterministic_signals", [])),
            deterministic_findings=dict(analyzed.get("deterministic_findings", {})),
            deterministic_root_cause_hint=analyzed.get("deterministic_root_cause_hint"),
            analysis_version=ANALYSIS_VERSION,
        )
        run_store.update_job_after_deterministic(
            case_id=record.case_id,
            job_status="llm_pending" if llm_required else "deterministic_done",
            eligible_for_llm=record.eligible_for_llm,
            llm_required=llm_required,
        )


def _iter_llm_pending_items(run_store: RunStore) -> Iterator[dict[str, Any]]:
    for joined_case in iter_joined_cases_from_store(run_store):
        case_id = str(joined_case.get("case_id"))
        job = run_store.get_job(case_id)
        if job.get("job_status") != "llm_pending":
            continue
        analyzed = _load_analyzed_case_from_store(run_store, case_id)
        yield {
            "case": analyzed,
            "record": _to_case_record(analyzed),
            "findings": _to_findings(analyzed),
        }


def _finalize_pending_results(
    *,
    run_store: RunStore,
    result_handle,
    checkpoint,
    summary_accumulator: SummaryAccumulator,
    case_status_counts: Dict[str, int],
    llm_warnings: list[str],
    llm_response_stats: Dict[str, Any],
) -> None:
    for joined_case in iter_joined_cases_from_store(run_store):
        case_id = str(joined_case.get("case_id"))
        if run_store.has_final_result(case_id):
            continue
        job = run_store.get_job(case_id)
        job_status = job.get("job_status")
        if job_status not in {"deterministic_done", "llm_done", "llm_failed_terminal"}:
            continue
        analyzed = _load_analyzed_case_from_store(run_store, case_id)
        llm_result, llm_parse_info = _load_selected_llm_result(run_store, case_id)
        result = build_final_case_result(
            _to_case_record(analyzed),
            _to_findings(analyzed),
            llm_result,
            llm_parse_info=llm_parse_info,
        )
        _persist_result(
            result,
            summary_accumulator,
            case_status_counts,
            result_handle,
            checkpoint,
            llm_warnings,
            llm_response_stats,
            run_store,
        )


def _is_retryable_llm_failure(parse_info: Dict[str, Any]) -> bool:
    if parse_info.get("status") != "request_error":
        return False
    http_status = parse_info.get("http_status")
    if http_status is None:
        return True
    return http_status == 429 or 500 <= int(http_status) < 600


def _can_retry_llm_failure(parse_info: Dict[str, Any], *, settings: Settings, attempt_index: int) -> bool:
    if not _is_retryable_llm_failure(parse_info):
        return False
    http_status = parse_info.get("http_status")
    if http_status is not None and 500 <= int(http_status) < 600 and not settings.llm_retry_on_5xx:
        return False
    return attempt_index < _max_llm_attempts(settings)


def _load_analyzed_case_from_store(run_store: RunStore, case_id: str) -> Dict[str, Any]:
    joined_case = run_store.load_joined_case(case_id)
    deterministic = run_store.get_deterministic_result(case_id)
    analyzed = dict(joined_case)
    analyzed["case_status"] = deterministic["case_status"]
    analyzed["failure_gate_warnings"] = deterministic["failure_gate_warnings_json"]
    analyzed["deterministic_signals"] = deterministic["deterministic_signals_json"]
    analyzed["deterministic_findings"] = deterministic["deterministic_findings_json"]
    analyzed["deterministic_root_cause_hint"] = deterministic["deterministic_root_cause_hint"]
    analyzed["eligible_for_llm"] = bool((run_store.get_job(case_id).get("eligible_for_llm") or 0))
    return analyzed


def _to_findings(case: Dict[str, Any]) -> DeterministicFindings:
    return DeterministicFindings(
        signals=list(case.get("deterministic_signals", [])),
        findings=dict(case.get("deterministic_findings", {})),
        warnings=list(case.get("failure_gate_warnings", []))
        + list(case.get("deterministic_findings", {}).get("runner_warnings", [])),
        root_cause_hint=case.get("deterministic_root_cause_hint"),
    )


def _build_input_snapshots(input_paths: list[Path], detected_roles: Dict[str, str]) -> list[Dict[str, Any]]:
    snapshots: list[Dict[str, Any]] = []
    for index, path in enumerate(input_paths):
        stat = path.stat()
        observer = JsonlScanObserver()
        for _ in iter_jsonl_records(path, observer=observer):
            pass
        snapshots.append(
            {
                "path": str(path),
                "declared_order": index,
                "detected_role": detected_roles.get(str(path), "unknown"),
                "size_bytes": int(stat.st_size),
                "mtime_epoch": float(stat.st_mtime),
                "sha256": observer.sha256,
                "sample_record_count": observer.sample_record_count,
            }
        )
    return snapshots


def _build_input_metadata(input_paths: list[Path], detected_roles: Dict[str, str]) -> list[Dict[str, Any]]:
    metadata: list[Dict[str, Any]] = []
    for index, path in enumerate(input_paths):
        stat = path.stat()
        metadata.append(
            {
                "path": str(path),
                "declared_order": index,
                "detected_role": detected_roles.get(str(path), "unknown"),
                "size_bytes": int(stat.st_size),
                "mtime_epoch": float(stat.st_mtime),
            }
        )
    return metadata


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _future_iso(*, seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _next_retry_iso(*, seconds: int) -> str:
    return _future_iso(seconds=max(1, seconds))



def _flush_llm_batch(
    *,
    batch: list[dict[str, Any]],
    settings: Settings,
    executor: ThreadPoolExecutor,
    summary_accumulator: SummaryAccumulator,
    case_status_counts: Dict[str, int],
    llm_warnings: list[str],
    llm_response_stats: Dict[str, Any],
    result_handle,
    checkpoint,
    llm_raw_responses_dir: Path,
    run_store: RunStore,
) -> None:
    prepared_batch: list[dict[str, Any]] = []
    for item in batch:
        messages = build_attribution_messages(item["case"])
        started_at = _utcnow_iso()
        lease_token = str(uuid.uuid4())
        lease_until = _future_iso(seconds=LLM_LEASE_SECONDS)
        current_job = run_store.get_job(item["record"].case_id)
        attempt_index = int(current_job.get("attempt_count") or 0) + 1
        run_store.mark_job_llm_running(
            case_id=item["record"].case_id,
            lease_token=lease_token,
            lease_until=lease_until,
        )
        prepared_batch.append(
            {
                **item,
                "messages": messages,
                "started_at": started_at,
                "attempt_index": attempt_index,
            }
        )
    results = list(executor.map(lambda current: _run_llm_case(current["messages"], settings), prepared_batch))
    for item, llm_outcome in zip(prepared_batch, results):
        llm_result, warning, parse_info = llm_outcome
        finished_at = _utcnow_iso()
        _persist_llm_raw_response(llm_raw_responses_dir, item["record"].case_id, parse_info)
        _update_llm_stats(llm_response_stats, item["record"].case_id, parse_info)
        retryable = _can_retry_llm_failure(
            parse_info,
            settings=settings,
            attempt_index=item["attempt_index"],
        )
        next_retry_at = _next_retry_iso(seconds=settings.llm_retry_backoff_seconds) if retryable else None
        run_store.record_llm_attempt(
            case_id=item["record"].case_id,
            attempt_index=item["attempt_index"],
            request_messages=item["messages"],
            provider_model=settings.model,
            provider_base_url=settings.base_url,
            started_at=item["started_at"],
            finished_at=finished_at,
            outcome=parse_info.get("status") or ("completed" if llm_result else "unknown"),
            parse_mode=parse_info.get("status"),
            parse_reason=parse_info.get("invalid_reason"),
            response_text=parse_info.get("raw_response_text"),
            response_sha256=parse_info.get("raw_response_sha256"),
            error_type=parse_info.get("error_type"),
            error_message=warning,
            http_status=parse_info.get("http_status"),
            is_selected=bool(llm_result),
        )
        if warning:
            llm_warnings.append(warning)
        if llm_result:
            run_store.mark_job_llm_done(item["record"].case_id)
        else:
            run_store.mark_job_llm_failed(
                case_id=item["record"].case_id,
                retryable=retryable,
                last_error=warning or parse_info.get("invalid_reason"),
                next_retry_at=next_retry_at,
            )
        result = build_final_case_result(item["record"], item["findings"], llm_result, llm_parse_info=parse_info)
        _persist_result(
            result,
            summary_accumulator,
            case_status_counts,
            result_handle,
            checkpoint,
            llm_warnings,
            llm_response_stats,
            run_store,
            finalize_job=not retryable,
        )



def _run_llm_case(messages: list[dict[str, str]], settings: Settings) -> tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    client = LLMClient(settings)
    try:
        llm_result = client.complete_json(messages)
    except Exception as exc:  # noqa: BLE001
        return None, f"llm unavailable: {exc}", {"status": "request_error", "invalid_reason": type(exc).__name__, "raw_response_excerpt": None, "raw_response_path": None, "raw_response_sha256": None}
    return llm_result, client.last_warning, dict(client.last_completion_info)



def _update_llm_stats(stats: Dict[str, Any], case_id: str, parse_info: Dict[str, Any]) -> None:
    stats["attempted"] += 1
    status = parse_info.get("status")
    reason = parse_info.get("invalid_reason")
    excerpt = parse_info.get("raw_response_excerpt")
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


def _persist_llm_raw_response(llm_raw_responses_dir: Path, case_id: str, parse_info: Dict[str, Any]) -> None:
    raw_response_text = parse_info.get("raw_response_text")
    if not raw_response_text:
        parse_info["raw_response_path"] = None
        parse_info["raw_response_sha256"] = parse_info.get("raw_response_sha256")
        return
    raw_response_path = llm_raw_responses_dir / f"{case_id}.txt"
    raw_response_path.write_text(raw_response_text, encoding="utf-8")
    parse_info["raw_response_path"] = str(raw_response_path.relative_to(llm_raw_responses_dir.parent))
    parse_info["raw_response_sha256"] = parse_info.get("raw_response_sha256") or hashlib.sha256(raw_response_text.encode("utf-8")).hexdigest()



def _persist_result(
    result: AttributionResult,
    summary_accumulator: SummaryAccumulator,
    case_status_counts: Dict[str, int],
    result_handle,
    checkpoint,
    llm_warnings: list[str],
    llm_response_stats: Dict[str, Any],
    run_store: RunStore,
    *,
    finalize_job: bool = True,
) -> None:
    result_row = asdict(result)
    result_handle.write(json.dumps(result_row, ensure_ascii=False) + "\n")
    result_handle.flush()
    summary_accumulator.add(result)
    case_status_counts[result.case_status] = case_status_counts.get(result.case_status, 0) + 1
    if checkpoint is not None:
        checkpoint.store_result(result.case_id, result_row)
        checkpoint.save_metadata("llm_warnings", llm_warnings)
        checkpoint.save_metadata("llm_response_stats", llm_response_stats)
    run_store.save_final_result(result_row)
    if finalize_job:
        run_store.mark_job_finalized(result.case_id)


def _export_case_analysis_from_store(run_store: RunStore, case_analysis_path: Path) -> None:
    with case_analysis_path.open("w", encoding="utf-8") as handle:
        for row in run_store.iter_final_result_rows():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")



def _render_selected_cases(case_analysis_path: Path, exemplar_ids: set[str], cases_dir: Path, exemplars_dir: Path) -> None:
    if not exemplar_ids:
        return
    with case_analysis_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            row = json.loads(raw)
            if str(row.get("case_id")) not in exemplar_ids:
                continue
            result = _result_from_row(row)
            text = render_case_report(result)
            (cases_dir / f"{result.case_id}.md").write_text(text, encoding="utf-8")
            if result.root_cause:
                slug = result.root_cause.replace("/", "-")
                (exemplars_dir / f"{slug}-{result.case_id}.md").write_text(text, encoding="utf-8")



def _increment_reason(counter: Dict[str, int], reason: str) -> None:
    counter[reason] = counter.get(reason, 0) + 1


def _summarize_results_from_store(run_store: RunStore):
    summary_accumulator = SummaryAccumulator()
    for row in run_store.iter_final_result_rows():
        summary_accumulator.add(_result_from_row(row))
    return summary_accumulator.to_summary()


def _build_run_context(
    *,
    run_store: RunStore,
    summary,
    llm_warnings: list[str],
    llm_response_stats: Dict[str, Any],
    checkpoint_path: Path | None,
    execution_mode: str,
) -> Dict[str, Any]:
    metadata = run_store.load_run_metadata()
    stored_settings = metadata.get("settings_json") or {}
    input_files = run_store.load_input_files()
    input_warnings = [row["message"] for row in run_store.list_ingest_events()]
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
        "checkpoint_path": str(checkpoint_path) if checkpoint_path else None,
    }


def _max_llm_attempts(settings: Settings) -> int:
    return max(1, 1 + settings.llm_max_retries)


def _rebuild_llm_state_from_store(run_store: RunStore) -> tuple[list[str], Dict[str, Any]]:
    warnings: list[str] = []
    stats = _initial_llm_response_stats()
    for row in run_store.iter_llm_attempt_rows():
        warning = row.get("error_message")
        if warning:
            warnings.append(warning)
        _update_llm_stats(
            stats,
            str(row.get("case_id")),
            {
                "status": row.get("parse_mode"),
                "invalid_reason": row.get("parse_reason"),
                "raw_response_excerpt": _excerpt_text(row.get("response_text")),
            },
        )
    if stats["attempted"]:
        stats["nonconforming_percentage"] = round(
            stats["nonconforming"] / stats["attempted"] * 100, 2
        )
    return warnings, stats


def _load_selected_llm_result(run_store: RunStore, case_id: str) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    attempts = run_store.list_llm_attempts(case_id)
    if not attempts:
        return None, {
            "status": None,
            "invalid_reason": None,
            "raw_response_excerpt": None,
            "raw_response_path": None,
            "raw_response_sha256": None,
        }
    selected = next((row for row in attempts if row.get("is_selected")), attempts[-1])
    response_text = selected.get("response_text")
    parsed_payload = None
    if response_text:
        parsed = parse_attribution_response(response_text)
        if parsed.payload:
            parsed_payload = parsed.payload
    return parsed_payload, {
        "status": selected.get("parse_mode"),
        "invalid_reason": selected.get("parse_reason"),
        "raw_response_excerpt": _excerpt_text(response_text),
        "raw_response_path": None,
        "raw_response_sha256": selected.get("response_sha256"),
    }


def _excerpt_text(text: str | None, *, limit: int = 200) -> str | None:
    if not text:
        return None
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."



def _result_from_row(row: Dict[str, Any]) -> AttributionResult:
    return AttributionResult(**row)


def _iter_results(case_analysis_path: Path) -> Iterator[AttributionResult]:
    with case_analysis_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            yield _result_from_row(json.loads(raw))



def _to_case_record(case: Dict[str, Any]) -> CaseRecord:
    return CaseRecord(
        case_id=str(case.get("case_id")),
        join_status=case.get("join_status", "unknown"),
        case_status=case.get("case_status", "unknown"),
        task=TaskInfo(
            content_text=case.get("task", {}).get("content_text") or "",
            canonical_code_text=case.get("reference", {}).get("canonical_code_text"),
            test_code_text=case.get("reference", {}).get("test_code_text"),
        ),
        evaluation=EvaluationInfo(
            accepted=case.get("evaluation", {}).get("accepted"),
            pass_metrics=case.get("evaluation", {}).get("pass_metrics") or {},
            results_tags=case.get("evaluation", {}).get("results_tags") or {},
        ),
        completion_raw_text=case.get("completion", {}).get("raw_text") or "",
        raw_inference_record=case.get("raw", {}).get("inference_record") or {},
        raw_results_record=case.get("raw", {}).get("results_record") or {},
        source=case.get("source", {}) or {},
        metadata=case.get("metadata", {}) or {},
        language=case.get("language", {}) or {},
        completion=case.get("completion", {}) or {},
        warnings=(case.get("normalization", {}) or {}).get("warnings", []),
        eligible_for_llm=bool(case.get("eligible_for_llm", False)),
    )
