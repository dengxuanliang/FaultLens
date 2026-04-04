from __future__ import annotations

from faultlens.models import AttributionResult
from faultlens.reporting.aggregate import summarize_cases
from faultlens.reporting.render import render_analysis_report, render_case_report, render_hierarchical_root_cause_report


def make_result(
    case_id: str,
    root_cause: str,
    *,
    l1_subtype: str = "wrong_output",
    l2_subtype: str = "local_logic_bug",
    l3_subtype: str = "operator_logic_error",
    needs_human_review: bool = False,
) -> AttributionResult:
    return AttributionResult(
        case_id=case_id,
        case_status="attributable_failure",
        accepted=False,
        root_cause=root_cause,
        deterministic_signals=["test_failure"],
        llm_signals=[],
        observable_evidence=["test failed"],
        evidence_refs=[{"source": "tests"}],
        deterministic_findings={"test_status": "failed"},
        llm_judgment=None,
        final_decision_source="deterministic_only",
        confidence=0.7,
        needs_human_review=needs_human_review,
        review_reason=root_cause if needs_human_review else None,
        improvement_hints=["check logic"],
        explanation="logic mismatch",
        hierarchical_cause={
            "l1": {
                "code": "functional_semantic_error",
                "label": "功能/语义错误",
                "subtype": l1_subtype,
                "rationale": "测试断言失败，且无接口或运行时错误证据。",
                "evidence": ["test_failure"],
            },
            "l2": {
                "code": "code_implementation_and_local_logic",
                "label": "代码实现与局部逻辑",
                "subtype": l2_subtype,
                "rationale": "实现逻辑与预期不一致。",
                "evidence": ["logic_mismatch"],
            },
            "l3": {
                "code": "state_control_flow_and_invariant_management",
                "label": "状态、控制流与不变量维护",
                "subtype": l3_subtype,
                "rationale": "核心运算逻辑错误。",
                "evidence": ["solve(2) returned 5"],
            },
            "analysis_basis": {
                "decision_source": "deterministic_only",
                "root_cause": root_cause,
                "secondary_cause": None,
                "deterministic_signals": ["test_failure"],
                "used_llm": False,
            },
        },
    )


def make_non_attributable_result(
    case_id: str,
    *,
    case_status: str,
    accepted: bool | None,
    needs_human_review: bool = False,
) -> AttributionResult:
    return AttributionResult(
        case_id=case_id,
        case_status=case_status,
        accepted=accepted,
        root_cause=None,
        deterministic_signals=["metadata_conflict"] if case_status != "passed" else [],
        llm_signals=[],
        observable_evidence=["join incomplete"] if case_status != "passed" else [],
        evidence_refs=[{"source": "ingest"}] if case_status != "passed" else [],
        deterministic_findings={"test_status": "not_run"},
        llm_judgment=None,
        final_decision_source="deterministic_only",
        confidence=0.2 if needs_human_review else None,
        needs_human_review=needs_human_review,
        review_reason=case_status if needs_human_review else None,
        improvement_hints=[],
        explanation=f"case marked as {case_status}",
        hierarchical_cause={},
    )


def test_summarize_cases_counts_root_causes_and_signals():
    summary = summarize_cases(
        [
            make_result("1", "solution_incorrect", l1_subtype="wrong_output"),
            make_result("2", "implementation_bug", l1_subtype="test_failure", needs_human_review=True),
        ]
    )

    assert summary.total_cases == 2
    assert summary.root_cause_counts["solution_incorrect"] == 1
    assert summary.deterministic_signal_counts["test_failure"] == 2
    assert summary.hierarchy_counts["l1"]["functional_semantic_error"] == 2
    assert summary.hierarchy_counts["l2"]["code_implementation_and_local_logic"] == 2
    assert summary.hierarchy_counts["l3"]["state_control_flow_and_invariant_management"] == 2
    assert summary.hierarchy_subtype_counts["l1"]["functional_semantic_error"]["wrong_output"] == 1
    assert summary.hierarchy_subtype_counts["l1"]["functional_semantic_error"]["test_failure"] == 1
    assert summary.hierarchy_root_cause_cross["l1"]["functional_semantic_error"]["solution_incorrect"] == 1
    assert summary.hierarchy_root_cause_cross["l1"]["functional_semantic_error"]["implementation_bug"] == 1
    assert summary.review_queue == ["2"]


def test_render_reports_contain_required_sections():
    result = make_result("1", "solution_incorrect", needs_human_review=True)
    summary = summarize_cases([result])

    report = render_analysis_report(summary, [result])
    case_report = render_case_report(result)
    hierarchy_report = render_hierarchical_root_cause_report(summary, [result])

    assert "# 运行摘要" in report
    assert "# 确定性分析摘要" in report
    assert "# LLM 根因分布" in report
    assert "# 三层错因聚合" in report
    assert "# 交叉分析" in report
    assert "# 切片分析" in report
    assert "# 代表性案例" in report
    assert "# 待人工复核" in report
    assert "# 输入警告" in report
    assert "# LLM 警告" in report
    assert "结论：" in report
    assert "●●●●●●●●●●" in report or "●●●●●○○○○○" in report or "●●○○○○○○○○" in report
    assert "| 类别 | 数量 | 占失败样本比例 | 图示 |" in report
    assert "| 类别 | 数量 | 占可归因失败比例 | 图示 |" in report
    assert "| 待复核数量 | 占失败样本比例 | 图示 | Case IDs |" in report
    assert "100.0%" in report
    assert "# 三层错因总览" in hierarchy_report
    assert "# 方法说明" in hierarchy_report
    assert "# L1 表层错误分布" in hierarchy_report
    assert "# L2 过程阶段错误原因分布" in hierarchy_report
    assert "# L3 根能力项原因分布" in hierarchy_report
    assert "# 主类到细类拆解" in hierarchy_report
    assert "# 根因与三层错因交叉映射" in hierarchy_report
    assert "# 失败样本逐题明细" in hierarchy_report
    assert "# 待人工复核样本" in hierarchy_report
    assert "| 主类 | 计数 |" in hierarchy_report
    assert "| 层级 | 主类 | 细类 | 计数 |" in hierarchy_report
    assert "| 层级 | 主类 | root_cause | 计数 |" in hierarchy_report
    assert "| Case ID | Root Cause | L1 | L2 | L3 | 关键证据 | 解释来源 |" in hierarchy_report
    assert "| Case ID | 复核原因 |" in hierarchy_report
    assert "wrong_output" in hierarchy_report
    assert "solution_incorrect" in hierarchy_report

    assert "# 案例 1" in case_report
    assert "## 语言" in case_report
    assert "## 生成代码" in case_report
    assert "## 解析 / 编译 / 测试" in case_report
    assert "## 三层错因分析" in case_report
    assert "### L1 表层错误" in case_report
    assert "### L2 过程阶段错误原因" in case_report
    assert "### L3 根能力项原因" in case_report
    assert "## 根因" in case_report
    assert "## 警告" in case_report
    assert "## 解释" in case_report
    assert "logic mismatch" in case_report


def test_render_analysis_report_surfaces_llm_job_backlog():
    result = make_result("1", "solution_incorrect")
    summary = summarize_cases([result])

    report = render_analysis_report(
        summary,
        [result],
        run_context={
            "input_files": ["inference.jsonl", "results.jsonl"],
            "role_detection": {"inference.jsonl": "inference", "results.jsonl": "results"},
            "join_stats": {"joined": 1, "join_issue": 0},
            "case_counts": {"attributable_failure": 1},
            "model_summary": "gpt-test",
            "llm_max_workers": 4,
            "job_status_counts": {
                "finalized": 1,
                "llm_pending": 3,
                "llm_running": 2,
                "llm_failed_retryable": 4,
            },
            "pending_llm_backlog": 9,
        },
    )

    assert "# 任务状态" in report
    assert "llm_pending" in report
    assert "llm_running" in report
    assert "llm_failed_retryable" in report
    assert "待处理 LLM backlog：9" in report


def test_render_analysis_report_uses_section_specific_denominators():
    results = [
        make_result("1", "solution_incorrect"),
        make_non_attributable_result("2", case_status="data_issue", accepted=False, needs_human_review=True),
        make_non_attributable_result("3", case_status="passed", accepted=True),
    ]
    summary = summarize_cases(results)

    report = render_analysis_report(
        summary,
        results,
        run_context={
            "input_files": ["inference.jsonl", "results.jsonl"],
            "role_detection": {"inference.jsonl": "inference", "results.jsonl": "results"},
            "join_stats": {"joined": 3, "join_issue": 0},
            "case_counts": {"attributable_failure": 1, "data_issue": 1, "passed": 1},
            "model_summary": "deterministic-only",
            "llm_max_workers": 1,
        },
    )

    assert "| 类别 | 数量 | 占可归因失败比例 | 图示 |" in report
    assert "| 待复核数量 | 占失败样本比例 | 图示 | Case IDs |" in report
    assert "解答逻辑错误 | 1 | 100.0%" in report
    assert "| 1 | 50.0% |" in report
