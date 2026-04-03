from faultlens.attribution.hierarchy import build_hierarchical_cause


def test_hierarchy_maps_solution_incorrect_to_functional_local_logic_and_state_control():
    result = build_hierarchical_cause(
        case_status="attributable_failure",
        root_cause="solution_incorrect",
        secondary_cause=None,
        deterministic_signals=["test_failure", "logic_mismatch"],
        deterministic_findings={"test_status": "failed", "failing_assert_excerpt": "assert solve(2) == 4"},
        llm_judgment=None,
        final_decision_source="deterministic_only",
    )

    assert result["l1"]["code"] == "functional_semantic_error"
    assert result["l2"]["code"] == "code_implementation_and_local_logic"
    assert result["l3"]["code"] == "state_control_flow_and_invariant_management"
    assert result["analysis_basis"]["root_cause"] == "solution_incorrect"


def test_hierarchy_keeps_solution_incorrect_in_logic_bucket_even_with_eval_mismatch_signal():
    result = build_hierarchical_cause(
        case_status="attributable_failure",
        root_cause="solution_incorrect",
        secondary_cause=None,
        deterministic_signals=["test_failure", "logic_mismatch", "suspicious_eval_mismatch"],
        deterministic_findings={
            "test_status": "failed",
            "failing_assert_excerpt": "assert solve(2) == 4",
            "test_harness_alignment_summary": "parse=parsed, signature=ok, entrypoint=ok, api=ok",
        },
        llm_judgment=None,
        final_decision_source="llm",
    )

    assert result["l1"]["code"] == "functional_semantic_error"
    assert result["l2"]["code"] == "code_implementation_and_local_logic"
    assert result["l3"]["code"] == "state_control_flow_and_invariant_management"


def test_hierarchy_treats_assertion_traceback_as_logic_failure_not_runtime_error():
    result = build_hierarchical_cause(
        case_status="attributable_failure",
        root_cause="solution_incorrect",
        secondary_cause=None,
        deterministic_signals=["test_failure", "logic_mismatch"],
        deterministic_findings={
            "test_status": "failed",
            "runtime_error_excerpt": "Traceback (most recent call last):\nAssertionError\n",
            "failing_assert_excerpt": "assert solve(2) == 4",
        },
        llm_judgment=None,
        final_decision_source="deterministic_only",
    )

    assert result["l1"]["code"] == "functional_semantic_error"
    assert result["l3"]["code"] == "state_control_flow_and_invariant_management"


def test_hierarchy_maps_interface_violation_to_contract_alignment_layers():
    result = build_hierarchical_cause(
        case_status="attributable_failure",
        root_cause="contract_or_interface_violation",
        secondary_cause=None,
        deterministic_signals=["signature_mismatch"],
        deterministic_findings={"signature_check_status": "mismatched"},
        llm_judgment=None,
        final_decision_source="deterministic_only",
    )

    assert result["l1"]["code"] == "interface_type_symbol_error"
    assert result["l2"]["code"] == "repository_context_and_interface_alignment"
    assert result["l3"]["code"] == "input_output_contract_modeling"
    assert result["l1"]["subtype"] == "signature_mismatch"


def test_hierarchy_maps_runtime_bug_to_runtime_execution_and_boundary_handling():
    result = build_hierarchical_cause(
        case_status="attributable_failure",
        root_cause="implementation_bug",
        secondary_cause=None,
        deterministic_signals=["runtime_error"],
        deterministic_findings={"runtime_error_excerpt": "IndexError: list index out of range"},
        llm_judgment=None,
        final_decision_source="deterministic_only",
    )

    assert result["l1"]["code"] == "runtime_execution_error"
    assert result["l2"]["code"] == "code_implementation_and_local_logic"
    assert result["l3"]["code"] == "boundary_condition_and_exception_handling"


def test_hierarchy_falls_back_to_unknown_when_evidence_is_insufficient():
    result = build_hierarchical_cause(
        case_status="attributable_failure",
        root_cause="insufficient_evidence",
        secondary_cause=None,
        deterministic_signals=[],
        deterministic_findings={},
        llm_judgment=None,
        final_decision_source="deterministic_only",
    )

    assert result["l1"]["code"] == "unknown_insufficient_evidence"
    assert result["l2"]["code"] == "unknown_insufficient_evidence"
    assert result["l3"]["code"] == "unknown_insufficient_evidence"
