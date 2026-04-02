from faultlens.attribution.engine import build_final_case_result
from faultlens.models import AttributionResult, CaseRecord, DeterministicFindings, EvaluationInfo, TaskInfo


def make_case() -> CaseRecord:
    return CaseRecord(
        case_id="1",
        join_status="joined",
        case_status="attributable_failure",
        task=TaskInfo(content_text="Add one"),
        evaluation=EvaluationInfo(accepted=False),
        completion_raw_text="```python\ndef solve(x): return x\n```",
    )


def test_build_final_case_result_uses_deterministic_fallback_when_no_llm():
    case = make_case()
    findings = DeterministicFindings(
        signals=["test_failure"],
        root_cause_hint="solution_incorrect",
        findings={"test_status": "failed"},
    )

    result = build_final_case_result(case, findings, llm_result=None)

    assert result.case_status == "attributable_failure"
    assert result.accepted is False
    assert result.root_cause == "solution_incorrect"
    assert result.final_decision_source == "deterministic_only"
    assert result.deterministic_signals == ["test_failure"]
    assert result.llm_signals == []
    assert result.deterministic_findings["test_status"] == "failed"
    assert result.observable_evidence
    assert result.llm_judgment is None
    assert result.improvement_hints
    assert result.hierarchical_cause["l1"]["code"] == "functional_semantic_error"
    assert result.hierarchical_cause["l2"]["code"] == "code_implementation_and_local_logic"
    assert result.hierarchical_cause["l3"]["code"] == "state_control_flow_and_invariant_management"


def test_build_final_case_result_skips_passed_cases():
    case = make_case()
    case.case_status = "passed"
    case.evaluation.accepted = True
    findings = DeterministicFindings(signals=[], findings={})

    result = build_final_case_result(case, findings, llm_result=None)

    assert result.root_cause is None
    assert result.explanation.startswith("Case did not enter attribution")
    assert result.hierarchical_cause["l1"]["code"] == "unknown_insufficient_evidence"
