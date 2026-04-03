from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


UNKNOWN_CODE = "unknown_insufficient_evidence"

L1_LABELS = {
    "output_missing_or_truncated": "输出缺失/截断",
    "syntax_or_parse_error": "语法/解析错误",
    "build_import_dependency_error": "构建/导入/依赖错误",
    "interface_type_symbol_error": "接口/类型/符号错误",
    "runtime_execution_error": "运行时执行错误",
    "functional_semantic_error": "功能/语义错误",
    "environment_evaluation_mismatch": "环境/评测错配",
    UNKNOWN_CODE: "未知/证据不足",
}

L2_LABELS = {
    "requirement_constraint_extraction": "需求理解与约束抽取",
    "solution_design_and_algorithm_planning": "方案设计与算法规划",
    "code_implementation_and_local_logic": "代码实现与局部逻辑",
    "repository_context_and_interface_alignment": "仓库上下文/接口对齐",
    "environment_setup_and_dependency_integration": "环境配置与依赖集成",
    "validation_debugging_and_self_correction": "验证、调试与自修复",
    UNKNOWN_CODE: "未知/证据不足",
}

L3_LABELS = {
    "constraint_extraction_and_adherence": "约束抽取与遵循",
    "input_output_contract_modeling": "输入输出契约建模",
    "task_decomposition_and_solution_planning": "任务分解与求解规划",
    "algorithm_and_data_structure_selection": "算法与数据结构选择",
    "state_control_flow_and_invariant_management": "状态、控制流与不变量维护",
    "interface_type_and_dependency_understanding": "接口、类型与依赖理解",
    "repository_context_localization_and_reuse": "仓库上下文定位与复用",
    "boundary_condition_and_exception_handling": "边界条件与异常处理",
    "toolchain_and_environment_operation": "工具链/环境操作能力",
    "testing_reflection_and_debugging": "测试验证、反思与调试能力",
    UNKNOWN_CODE: "未知/证据不足",
}


def build_hierarchical_cause(
    *,
    case_status: str,
    root_cause: Optional[str],
    secondary_cause: Optional[str],
    deterministic_signals: Iterable[str],
    deterministic_findings: Dict[str, Any],
    llm_judgment: Optional[Dict[str, Any]],
    final_decision_source: str,
) -> Dict[str, Any]:
    signals = list(deterministic_signals or [])
    signal_set = set(signals)
    findings = deterministic_findings or {}

    if case_status != "attributable_failure" or not root_cause:
        return _unknown_hierarchy(
            final_decision_source=final_decision_source,
            root_cause=root_cause,
            secondary_cause=secondary_cause,
            deterministic_signals=signals,
            used_llm=bool(llm_judgment),
            rationale="样本未进入错因归因流程，因此三层错因保持未知占位。",
        )

    l1 = _classify_l1(root_cause, signal_set, findings)
    l2 = _classify_l2(root_cause, l1["code"], signal_set, findings)
    l3 = _classify_l3(root_cause, l1["code"], l2["code"], signal_set, findings)
    return {
        "l1": l1,
        "l2": l2,
        "l3": l3,
        "analysis_basis": {
            "decision_source": final_decision_source,
            "root_cause": root_cause,
            "secondary_cause": secondary_cause,
            "deterministic_signals": signals,
            "used_llm": bool(llm_judgment),
        },
    }


def _classify_l1(root_cause: str, signal_set: set[str], findings: Dict[str, Any]) -> Dict[str, Any]:
    logic_root_causes = {"solution_incorrect", "task_misunderstanding", "implementation_bug"}
    logic_signals = {"test_failure", "logic_mismatch"}

    if signal_set & {"missing_code", "code_extraction_failed"} or root_cause == "incomplete_or_truncated_solution":
        return _level(
            "l1",
            "output_missing_or_truncated",
            _first_matching(signal_set, ["missing_code", "code_extraction_failed"], default="truncated_solution"),
            "回复中缺少有效代码或代码被截断，首先表现为输出不完整。",
            _collect_evidence(signal_set, findings, ["parse_error_excerpt", "completion_code"]),
        )
    if signal_set & {"syntax_error"} or findings.get("parse_status") == "failed":
        return _level(
            "l1",
            "syntax_or_parse_error",
            "syntax_error",
            "代码在解析阶段就失败，属于语法/解析层面的直接错误。",
            _collect_evidence(signal_set, findings, ["parse_error_excerpt"]),
        )
    if root_cause in {"possible_evaluation_mismatch", "environment_or_api_mismatch"} or (
        signal_set & {"suspicious_eval_mismatch"} and root_cause not in logic_root_causes and not signal_set & logic_signals
    ):
        return _level(
            "l1",
            "environment_evaluation_mismatch",
            _first_matching(signal_set, ["suspicious_eval_mismatch", "api_mismatch"], default="environment_or_evaluation_mismatch"),
            "错误更像发生在环境、评测或外部 API 对齐层，而非题解逻辑本身。",
            _collect_evidence(signal_set, findings, ["runner_warnings", "stderr_excerpt"]),
        )
    if signal_set & {"signature_mismatch", "entrypoint_mismatch", "api_mismatch"} or root_cause == "contract_or_interface_violation":
        return _level(
            "l1",
            "interface_type_symbol_error",
            _first_matching(signal_set, ["signature_mismatch", "entrypoint_mismatch", "api_mismatch"], default="contract_mismatch"),
            "失败直接暴露为接口、符号或调用契约不匹配。",
            _collect_evidence(signal_set, findings, ["signature_check_status", "entrypoint_check_status", "api_check_status"]),
        )
    if signal_set & {"compile_error"}:
        return _level(
            "l1",
            "build_import_dependency_error",
            "compile_error",
            "代码在构建/编译阶段失败，属于导入、依赖或构建层面的表层错误。",
            _collect_evidence(signal_set, findings, ["stderr_excerpt", "runtime_error_excerpt"]),
        )
    if signal_set & {"runtime_error"} or _has_non_assert_runtime_error(findings):
        return _level(
            "l1",
            "runtime_execution_error",
            "runtime_error",
            "代码能够开始执行，但在运行期抛出异常。",
            _collect_evidence(signal_set, findings, ["runtime_error_excerpt", "stderr_excerpt"]),
        )
    if signal_set & logic_signals or root_cause in logic_root_causes:
        return _level(
            "l1",
            "functional_semantic_error",
            _first_matching(signal_set, ["logic_mismatch", "test_failure"], default="wrong_output"),
            "代码通过了基础接口进入执行，但功能结果与预期语义不一致。",
            _collect_evidence(signal_set, findings, ["failing_assert_excerpt", "canonical_diff_summary", "test_harness_alignment_summary"]),
        )
    return _level(
        "l1",
        UNKNOWN_CODE,
        "unspecified",
        "当前证据不足以稳定判断表层错误类型。",
        _collect_evidence(signal_set, findings, ["stderr_excerpt", "canonical_diff_summary"]),
    )


def _classify_l2(root_cause: str, l1_code: str, signal_set: set[str], findings: Dict[str, Any]) -> Dict[str, Any]:
    if root_cause == "task_misunderstanding":
        return _level(
            "l2",
            "requirement_constraint_extraction",
            "constraint_missed",
            "根因指向题意或约束理解偏差，错误主要在需求理解阶段引入。",
            _collect_evidence(signal_set, findings, ["canonical_diff_summary"]),
        )
    if root_cause in {"contract_or_interface_violation"} or l1_code == "interface_type_symbol_error":
        return _level(
            "l2",
            "repository_context_and_interface_alignment",
            "api_contract_mismatch",
            "错误主要发生在接口理解、符号对齐或仓库上下文对接阶段。",
            _collect_evidence(signal_set, findings, ["signature_check_status", "entrypoint_check_status", "api_check_status"]),
        )
    if root_cause in {"environment_or_api_mismatch"}:
        return _level(
            "l2",
            "environment_setup_and_dependency_integration",
            "dependency_or_environment_mismatch",
            "根因表明外部环境、依赖或执行上下文集成阶段存在偏差。",
            _collect_evidence(signal_set, findings, ["runner_warnings", "stderr_excerpt"]),
        )
    if root_cause in {"possible_evaluation_mismatch"} or l1_code == "environment_evaluation_mismatch":
        return _level(
            "l2",
            "validation_debugging_and_self_correction",
            "evaluation_validation_gap",
            "问题在验证/调试阶段暴露，系统未能及时识别评测或环境不一致。",
            _collect_evidence(signal_set, findings, ["runner_warnings", "test_harness_alignment_summary"]),
        )
    if root_cause in {"solution_incorrect", "implementation_bug", "incomplete_or_truncated_solution"} or l1_code in {
        "functional_semantic_error",
        "runtime_execution_error",
        "build_import_dependency_error",
        "syntax_or_parse_error",
        "output_missing_or_truncated",
    }:
        return _level(
            "l2",
            "code_implementation_and_local_logic",
            _implementation_subtype(root_cause, l1_code, signal_set),
            "错误主要是在代码实现或局部逻辑展开阶段被引入。",
            _collect_evidence(signal_set, findings, ["canonical_diff_summary", "failing_assert_excerpt", "runtime_error_excerpt"]),
        )
    return _level(
        "l2",
        UNKNOWN_CODE,
        "unspecified",
        "当前证据不足以稳定定位错误发生阶段。",
        _collect_evidence(signal_set, findings, ["canonical_diff_summary"]),
    )


def _classify_l3(
    root_cause: str,
    l1_code: str,
    l2_code: str,
    signal_set: set[str],
    findings: Dict[str, Any],
) -> Dict[str, Any]:
    if root_cause == "task_misunderstanding":
        return _level(
            "l3",
            "constraint_extraction_and_adherence",
            "constraint_omission",
            "模型没有正确抽取或遵循题目约束。",
            _collect_evidence(signal_set, findings, ["canonical_diff_summary"]),
        )
    if root_cause == "contract_or_interface_violation" or l1_code == "interface_type_symbol_error":
        return _level(
            "l3",
            "input_output_contract_modeling",
            _first_matching(signal_set, ["signature_mismatch", "entrypoint_mismatch", "api_mismatch"], default="contract_misread"),
            "模型未正确建模输入输出契约或函数接口要求。",
            _collect_evidence(signal_set, findings, ["signature_check_status", "entrypoint_check_status", "api_check_status"]),
        )
    if l1_code == "build_import_dependency_error":
        return _level(
            "l3",
            "interface_type_and_dependency_understanding",
            "dependency_resolution_failure",
            "失败反映出对依赖、导入或类型/符号关系理解不足。",
            _collect_evidence(signal_set, findings, ["stderr_excerpt", "runtime_error_excerpt"]),
        )
    if l1_code == "runtime_execution_error":
        return _level(
            "l3",
            "boundary_condition_and_exception_handling",
            "runtime_exception_handling_gap",
            "运行期异常通常说明边界处理、空值处理或异常保护不足。",
            _collect_evidence(signal_set, findings, ["runtime_error_excerpt", "stderr_excerpt"]),
        )
    if l1_code == "environment_evaluation_mismatch":
        if root_cause == "environment_or_api_mismatch":
            return _level(
                "l3",
                "toolchain_and_environment_operation",
                "environment_alignment_gap",
                "问题根在工具链、环境变量、依赖版本或执行环境操作能力。",
                _collect_evidence(signal_set, findings, ["runner_warnings", "stderr_excerpt"]),
            )
        return _level(
            "l3",
            "testing_reflection_and_debugging",
            "validation_feedback_gap",
            "问题更多体现为验证反馈识别和调试收敛能力不足。",
            _collect_evidence(signal_set, findings, ["runner_warnings", "test_harness_alignment_summary"]),
        )
    if l1_code == "output_missing_or_truncated":
        return _level(
            "l3",
            "task_decomposition_and_solution_planning",
            "incomplete_solution_plan",
            "输出不完整通常意味着任务展开和解题规划没有闭合。",
            _collect_evidence(signal_set, findings, ["completion_code", "canonical_diff_summary"]),
        )
    if l1_code == "syntax_or_parse_error":
        return _level(
            "l3",
            "state_control_flow_and_invariant_management",
            "syntactic_consistency_gap",
            "语法错误反映出代码生成时局部结构和基本约束维护失败。",
            _collect_evidence(signal_set, findings, ["parse_error_excerpt"]),
        )
    if root_cause == "solution_incorrect":
        return _level(
            "l3",
            "state_control_flow_and_invariant_management",
            "operator_or_logic_error",
            "功能错误通常源于状态更新、条件分支或核心运算不变量维护失误。",
            _collect_evidence(signal_set, findings, ["failing_assert_excerpt", "canonical_diff_summary"]),
        )
    if root_cause == "implementation_bug" or l2_code == "code_implementation_and_local_logic":
        return _level(
            "l3",
            "state_control_flow_and_invariant_management",
            "local_implementation_bug",
            "实现缺陷主要体现为局部控制流和数据状态维护不稳。",
            _collect_evidence(signal_set, findings, ["failing_assert_excerpt", "runtime_error_excerpt", "canonical_diff_summary"]),
        )
    return _level(
        "l3",
        UNKNOWN_CODE,
        "unspecified",
        "当前证据不足以稳定定位到更细的能力项。",
        _collect_evidence(signal_set, findings, ["canonical_diff_summary", "stderr_excerpt"]),
    )


def _unknown_hierarchy(
    *,
    final_decision_source: str,
    root_cause: Optional[str],
    secondary_cause: Optional[str],
    deterministic_signals: list[str],
    used_llm: bool,
    rationale: str,
) -> Dict[str, Any]:
    level = {
        "code": UNKNOWN_CODE,
        "label": L1_LABELS[UNKNOWN_CODE],
        "subtype": "unspecified",
        "rationale": rationale,
        "evidence": [],
    }
    return {
        "l1": dict(level),
        "l2": {**level, "label": L2_LABELS[UNKNOWN_CODE]},
        "l3": {**level, "label": L3_LABELS[UNKNOWN_CODE]},
        "analysis_basis": {
            "decision_source": final_decision_source,
            "root_cause": root_cause,
            "secondary_cause": secondary_cause,
            "deterministic_signals": deterministic_signals,
            "used_llm": used_llm,
        },
    }


def _implementation_subtype(root_cause: str, l1_code: str, signal_set: set[str]) -> str:
    if l1_code == "output_missing_or_truncated":
        return "incomplete_solution_delivery"
    if l1_code == "syntax_or_parse_error":
        return "code_synthesis_breakage"
    if l1_code == "build_import_dependency_error":
        return "build_or_dependency_breakage"
    if l1_code == "runtime_execution_error":
        return "runtime_logic_bug"
    if root_cause == "solution_incorrect":
        return "local_logic_bug"
    if root_cause == "implementation_bug":
        return "implementation_defect"
    return _first_matching(signal_set, ["logic_mismatch", "test_failure"], default="implementation_issue")


def _level(level: str, code: str, subtype: str, rationale: str, evidence: list[str]) -> Dict[str, Any]:
    labels = {"l1": L1_LABELS, "l2": L2_LABELS, "l3": L3_LABELS}[level]
    return {
        "code": code,
        "label": labels[code],
        "subtype": subtype,
        "rationale": rationale,
        "evidence": evidence,
    }


def _first_matching(signal_set: set[str], candidates: list[str], *, default: str) -> str:
    for candidate in candidates:
        if candidate in signal_set:
            return candidate
    return default


def _has_non_assert_runtime_error(findings: Dict[str, Any]) -> bool:
    excerpt = str(findings.get("runtime_error_excerpt") or "")
    if not excerpt.strip():
        return False
    return "assertionerror" not in excerpt.lower()


def _collect_evidence(signal_set: set[str], findings: Dict[str, Any], finding_keys: list[str]) -> list[str]:
    evidence = list(signal_set)
    for key in finding_keys:
        value = findings.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, list):
            evidence.extend(str(item) for item in value if item)
        else:
            evidence.append(str(value))
    deduped: list[str] = []
    seen = set()
    for item in evidence:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped[:6]
