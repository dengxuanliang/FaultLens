from faultlens.normalize.failure_gate import apply_failure_gate


def test_failure_gate_marks_passed_case() -> None:
    case = {
        "case_id": "1",
        "case_status": "unknown",
        "join_status": "ok",
        "completion": {"raw_text": "```python\npass\n```"},
        "evaluation": {"accepted": True, "pass_metrics": {"passed_at_1": 1}},
        "normalization": {"warnings": []},
        "deterministic_signals": [],
    }

    gated = apply_failure_gate(case)

    assert gated["case_status"] == "passed"
    assert gated["eligible_for_llm"] is False


def test_failure_gate_marks_attributable_failure() -> None:
    case = {
        "case_id": "2",
        "case_status": "unknown",
        "join_status": "ok",
        "completion": {"raw_text": "```python\nprint(1)\n```"},
        "evaluation": {"accepted": False, "pass_metrics": {"passed_at_1": 0}},
        "normalization": {"warnings": []},
        "deterministic_signals": [],
    }

    gated = apply_failure_gate(case)

    assert gated["case_status"] == "attributable_failure"
    assert gated["eligible_for_llm"] is True


def test_failure_gate_marks_data_issue_for_missing_completion() -> None:
    case = {
        "case_id": "3",
        "case_status": "unknown",
        "join_status": "ok",
        "completion": {"raw_text": ""},
        "evaluation": {"accepted": False, "pass_metrics": {"passed_at_1": 0}},
        "normalization": {"warnings": []},
        "deterministic_signals": [],
    }

    gated = apply_failure_gate(case)

    assert gated["case_status"] == "data_issue"
    assert gated["eligible_for_llm"] is False


def test_failure_gate_flags_suspicious_eval_mismatch() -> None:
    case = {
        "case_id": "4",
        "case_status": "unknown",
        "join_status": "ok",
        "completion": {"raw_text": "```python\nx=1\n```"},
        "evaluation": {
            "accepted": False,
            "pass_metrics": {"passed_at_1": 1, "pass_at_k": 1, "all_k_correct": 1},
        },
        "normalization": {"warnings": []},
        "deterministic_signals": [],
    }

    gated = apply_failure_gate(case)

    assert "suspicious_eval_mismatch" in gated["deterministic_signals"]
    assert any("pass metrics" in warning for warning in gated["failure_gate_warnings"])
