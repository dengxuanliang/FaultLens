from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import shutil
from typing import Any, Dict, Iterable, Iterator, Optional

from faultlens.attribution.engine import build_final_case_result
from faultlens.config import Settings
from faultlens.deterministic.pipeline import analyze_case_deterministically, analyze_cases_deterministically
from faultlens.deterministic.runners.registry import build_runner_registry
from faultlens.ingest.resolver import detect_input_roles
from faultlens.llm.client import LLMClient
from faultlens.llm.prompting import build_attribution_messages
from faultlens.models import AttributionResult, CaseRecord, DeterministicFindings, EvaluationInfo, TaskInfo
from faultlens.normalize.failure_gate import apply_failure_gate
from faultlens.normalize.joiner import join_records_iter
from faultlens.reporting.aggregate import SummaryAccumulator
from faultlens.reporting.render import (
    render_analysis_report,
    render_case_report,
    write_hierarchical_root_cause_report,
)
from faultlens.scale.checkpointing import CheckpointStore



def run_analysis(
    *,
    input_paths: Iterable[Path],
    settings: Settings,
    output_dir: Path,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    input_paths = [Path(path) for path in input_paths]
    resolved = detect_input_roles(input_paths)

    _prepare_output_dir(output_dir, resume=settings.resume)

    checkpoint = CheckpointStore(output_dir / "faultlens_checkpoint.sqlite3", enabled=settings.enable_checkpoints).open()
    case_analysis_path = output_dir / "case_analysis.jsonl"
    cases_dir = output_dir / "cases"
    exemplars_dir = output_dir / "exemplars"
    cases_dir.mkdir(parents=True, exist_ok=True)
    exemplars_dir.mkdir(parents=True, exist_ok=True)

    summary_accumulator = SummaryAccumulator()
    case_status_counts = {"passed": 0, "attributable_failure": 0, "data_issue": 0, "join_issue": 0}
    llm_warnings = checkpoint.load_metadata("llm_warnings", []) if settings.resume else []
    llm_response_stats = checkpoint.load_metadata("llm_response_stats", _initial_llm_response_stats()) if settings.resume else _initial_llm_response_stats()

    with case_analysis_path.open("w", encoding="utf-8") as result_handle:
        if settings.resume and settings.enable_checkpoints:
            for row in checkpoint.iter_result_rows():
                result = _result_from_row(row)
                summary_accumulator.add(result)
                case_status_counts[result.case_status] = case_status_counts.get(result.case_status, 0) + 1
                result_handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        llm_enabled = bool(settings.api_key and settings.base_url and settings.model)
        batch: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=settings.llm_max_workers) as executor:
            for joined_case in join_records_iter(resolved.inference_path, resolved.results_path):
                current_case_id = str(joined_case.get("case_id"))
                if settings.resume and checkpoint.has_case(current_case_id):
                    continue

                gated = apply_failure_gate(joined_case)
                analyzed = analyze_cases_deterministically([gated], execution_timeout=settings.execution_timeout)[0]
                record = _to_case_record(analyzed)
                findings = DeterministicFindings(
                    signals=list(analyzed.get("deterministic_signals", [])),
                    findings=dict(analyzed.get("deterministic_findings", {})),
                    warnings=list(analyzed.get("failure_gate_warnings", [])) + list(analyzed.get("deterministic_findings", {}).get("runner_warnings", [])),
                    root_cause_hint=analyzed.get("deterministic_root_cause_hint"),
                )

                if record.eligible_for_llm and llm_enabled:
                    batch.append({"case": analyzed, "record": record, "findings": findings})
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
                            checkpoint=checkpoint,
                        )
                        batch = []
                else:
                    result = build_final_case_result(record, findings, llm_result=None, llm_parse_info={"status": None, "invalid_reason": None, "raw_response_excerpt": None})
                    _persist_result(result, summary_accumulator, case_status_counts, result_handle, checkpoint, llm_warnings, llm_response_stats)

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
                    checkpoint=checkpoint,
                )

    if llm_response_stats["attempted"]:
        llm_response_stats["nonconforming_percentage"] = round(
            llm_response_stats["nonconforming"] / llm_response_stats["attempted"] * 100, 2
        )

    checkpoint.save_metadata("llm_warnings", llm_warnings)
    checkpoint.save_metadata("llm_response_stats", llm_response_stats)

    summary = summary_accumulator.to_summary()
    run_context = {
        "input_files": [str(path) for path in input_paths],
        "role_detection": resolved.detected_roles,
        "join_stats": {
            "joined": summary.total_cases - case_status_counts.get("join_issue", 0),
            "join_issue": case_status_counts.get("join_issue", 0),
        },
        "case_counts": case_status_counts,
        "model_summary": settings.model if llm_enabled else "deterministic-only",
        "input_warnings": resolved.warnings,
        "llm_warnings": llm_warnings,
        "llm_response_stats": llm_response_stats,
        "llm_max_workers": settings.llm_max_workers,
        "execution_mode": "streaming",
        "checkpoint_path": str(checkpoint.path) if settings.enable_checkpoints else None,
    }
    (output_dir / "analysis_report.md").write_text(render_analysis_report(summary, [], run_context), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "run_metadata.json").write_text(json.dumps(run_context, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "hierarchical_root_cause_report.md").open("w", encoding="utf-8") as handle:
        write_hierarchical_root_cause_report(handle, summary, _iter_results(case_analysis_path))

    exemplar_ids = {item for ids in summary.exemplars.values() for item in ids[:1]}
    if case_id:
        exemplar_ids.add(str(case_id))
    _render_selected_cases(case_analysis_path, exemplar_ids, cases_dir, exemplars_dir)

    checkpoint.close()
    return {
        "resolved": resolved,
        "summary": summary,
        "output_dir": output_dir,
        "llm_warnings": llm_warnings,
        "llm_response_stats": llm_response_stats,
    }



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
    ]:
        if target.exists():
            target.unlink()
    for directory in [output_dir / "cases", output_dir / "exemplars"]:
        if directory.exists():
            shutil.rmtree(directory)



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
    checkpoint: CheckpointStore,
) -> None:
    cases = [item["case"] for item in batch]
    results = list(executor.map(lambda current: _run_llm_case(current, settings), cases))
    for item, llm_outcome in zip(batch, results):
        llm_result, warning, parse_info = llm_outcome
        _update_llm_stats(llm_response_stats, item["record"].case_id, parse_info)
        if warning:
            llm_warnings.append(warning)
        result = build_final_case_result(item["record"], item["findings"], llm_result, llm_parse_info=parse_info)
        _persist_result(result, summary_accumulator, case_status_counts, result_handle, checkpoint, llm_warnings, llm_response_stats)



def _run_llm_case(case: Dict[str, Any], settings: Settings) -> tuple[Optional[Dict[str, Any]], Optional[str], Dict[str, Any]]:
    client = LLMClient(settings)
    try:
        llm_result = client.complete_json(build_attribution_messages(case))
    except Exception as exc:  # noqa: BLE001
        return None, f"llm unavailable: {exc}", {"status": "request_error", "invalid_reason": type(exc).__name__, "raw_response_excerpt": None}
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



def _persist_result(
    result: AttributionResult,
    summary_accumulator: SummaryAccumulator,
    case_status_counts: Dict[str, int],
    result_handle,
    checkpoint: CheckpointStore,
    llm_warnings: list[str],
    llm_response_stats: Dict[str, Any],
) -> None:
    result_row = asdict(result)
    result_handle.write(json.dumps(result_row, ensure_ascii=False) + "\n")
    result_handle.flush()
    summary_accumulator.add(result)
    case_status_counts[result.case_status] = case_status_counts.get(result.case_status, 0) + 1
    checkpoint.store_result(result.case_id, result_row)
    checkpoint.save_metadata("llm_warnings", llm_warnings)
    checkpoint.save_metadata("llm_response_stats", llm_response_stats)



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
