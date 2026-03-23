from __future__ import annotations

from typing import Any, Dict, Optional

from faultlens.models import AttributionResult, CaseRecord, DeterministicFindings

_ALLOWED_ROOT_CAUSES = {
    "task_misunderstanding",
    "contract_or_interface_violation",
    "solution_incorrect",
    "implementation_bug",
    "incomplete_or_truncated_solution",
    "environment_or_api_mismatch",
    "possible_evaluation_mismatch",
    "insufficient_evidence",
}


def _normalize_root_cause(value: Optional[str]) -> str:
    if value in _ALLOWED_ROOT_CAUSES:
        return value  # type: ignore[return-value]
    return "insufficient_evidence"


def build_final_case_result(
    case: CaseRecord,
    findings: DeterministicFindings,
    llm_result: Optional[Dict[str, Any]],
) -> AttributionResult:
    if case.case_status != "attributable_failure":
        return AttributionResult(
            case_id=case.case_id,
            case_status=case.case_status,
            accepted=case.evaluation.accepted,
            root_cause=None,
            deterministic_signals=list(findings.signals),
            llm_signals=[],
            observable_evidence=[f"case status: {case.case_status}"],
            evidence_refs=[{"source": "failure_gate"}],
            deterministic_findings=dict(findings.findings),
            llm_judgment=None,
            final_decision_source="deterministic_only",
            confidence=None,
            needs_human_review=case.case_status in {"data_issue", "join_issue"},
            review_reason=case.case_status if case.case_status in {"data_issue", "join_issue"} else None,
            improvement_hints=[],
            explanation=f"Case did not enter attribution because status is {case.case_status}.",
            secondary_cause=None,
            slice_fields=dict(case.metadata.get("slice_fields", {})),
        )

    root_cause = _normalize_root_cause(findings.root_cause_hint)
    llm_payload = None
    final_decision_source = "deterministic_only"
    llm_signals = []
    explanation = f"Root cause classified as {root_cause} using deterministic-first analysis."
    improvement_hints = ["inspect failing deterministic findings"]
    secondary_cause = None
    if llm_result:
        llm_payload = llm_result
        llm_signals = list(llm_result.get("llm_signals", []))
        final_decision_source = "deterministic_plus_llm"
        root_cause = _normalize_root_cause(llm_result.get("root_cause") or root_cause)
        secondary_cause = _normalize_root_cause(llm_result.get("secondary_cause")) if llm_result.get("secondary_cause") else None
        explanation = llm_result.get("explanation") or explanation
        improvement_hints = list(llm_result.get("improvement_hints") or improvement_hints)

    evidence = list(llm_result.get("observable_evidence", [])) if llm_result else []
    if not evidence:
        evidence = [f"deterministic signal: {signal}" for signal in findings.signals] or ["no deterministic evidence available"]

    review_reason = None
    needs_human_review = root_cause in {"insufficient_evidence", "possible_evaluation_mismatch"}
    if needs_human_review:
        review_reason = root_cause

    return AttributionResult(
        case_id=case.case_id,
        case_status=case.case_status,
        accepted=case.evaluation.accepted,
        root_cause=root_cause,
        deterministic_signals=list(findings.signals),
        llm_signals=llm_signals,
        observable_evidence=evidence,
        evidence_refs=list(llm_result.get("evidence_refs", [])) if llm_result else [{"source": "deterministic_findings"}],
        deterministic_findings=dict(findings.findings),
        llm_judgment=llm_payload,
        final_decision_source=final_decision_source,
        confidence=0.7 if findings.signals else 0.3,
        needs_human_review=needs_human_review,
        review_reason=review_reason,
        improvement_hints=improvement_hints,
        explanation=explanation,
        secondary_cause=secondary_cause,
        slice_fields=dict(case.metadata.get("slice_fields", {})),
    )
