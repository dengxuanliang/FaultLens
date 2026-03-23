from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from faultlens.attribution.engine import build_final_case_result
from faultlens.config import Settings
from faultlens.deterministic.pipeline import analyze_cases_deterministically
from faultlens.ingest.resolver import detect_input_roles
from faultlens.llm.client import LLMClient
from faultlens.llm.prompting import build_attribution_messages
from faultlens.models import CaseRecord, DeterministicFindings, EvaluationInfo, TaskInfo
from faultlens.normalize.failure_gate import apply_failure_gate
from faultlens.normalize.joiner import join_records
from faultlens.reporting.aggregate import summarize_cases
from faultlens.reporting.render import render_analysis_report, render_case_report


def run_analysis(
    *,
    input_paths: Iterable[Path],
    settings: Settings,
    output_dir: Path,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    input_paths = [Path(path) for path in input_paths]
    resolved = detect_input_roles(input_paths)
    joined = join_records(resolved.inference_path, resolved.results_path)
    gated = [apply_failure_gate(case) for case in joined]
    analyzed = analyze_cases_deterministically(gated, execution_timeout=settings.execution_timeout)

    client = LLMClient(settings)
    results = []
    for case in analyzed:
        record = _to_case_record(case)
        findings = DeterministicFindings(
            signals=list(case.get("deterministic_signals", [])),
            findings=dict(case.get("deterministic_findings", {})),
            warnings=list(case.get("failure_gate_warnings", [])),
            root_cause_hint=case.get("deterministic_root_cause_hint"),
        )
        llm_result = None
        if record.eligible_for_llm and client.enabled:
            llm_result = client.complete_json(build_attribution_messages(case))
        results.append(build_final_case_result(record, findings, llm_result))

    output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = output_dir / "cases"
    exemplars_dir = output_dir / "exemplars"
    cases_dir.mkdir(parents=True, exist_ok=True)
    exemplars_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize_cases(results)
    (output_dir / "analysis_report.md").write_text(render_analysis_report(summary, results), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "case_analysis.jsonl").write_text(
        "\n".join(json.dumps(asdict(result), ensure_ascii=False) for result in results) + "\n",
        encoding="utf-8",
    )

    exemplar_ids = {case_id for ids in summary.exemplars.values() for case_id in ids[:1]}
    if case_id:
        exemplar_ids.add(str(case_id))
    result_by_id = {result.case_id: result for result in results}
    for exemplar_case_id in sorted(exemplar_ids):
        result = result_by_id.get(str(exemplar_case_id))
        if result is None:
            continue
        text = render_case_report(result)
        (cases_dir / f"{result.case_id}.md").write_text(text, encoding="utf-8")
        if result.root_cause:
            slug = result.root_cause.replace("/", "-")
            (exemplars_dir / f"{slug}-{result.case_id}.md").write_text(text, encoding="utf-8")

    return {"resolved": resolved, "results": results, "summary": summary, "output_dir": output_dir}


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
