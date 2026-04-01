from faultlens.models import AttributionResult
from faultlens.reporting.aggregate import summarize_cases
from faultlens.reporting.render import render_analysis_report, render_case_report


def make_result(case_id: str, root_cause: str) -> AttributionResult:
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
        needs_human_review=False,
        review_reason=None,
        improvement_hints=["check logic"],
        explanation="logic mismatch",
    )


def test_summarize_cases_counts_root_causes_and_signals():
    summary = summarize_cases([make_result("1", "solution_incorrect"), make_result("2", "implementation_bug")])

    assert summary.total_cases == 2
    assert summary.root_cause_counts["solution_incorrect"] == 1
    assert summary.deterministic_signal_counts["test_failure"] == 2


def test_render_reports_contain_required_sections():
    result = make_result("1", "solution_incorrect")
    summary = summarize_cases([result])

    report = render_analysis_report(summary, [result])
    case_report = render_case_report(result)

    assert "# 运行摘要" in report
    assert "# 确定性分析摘要" in report
    assert "# LLM 根因分布" in report
    assert "# 交叉分析" in report
    assert "# 切片分析" in report
    assert "# 代表性案例" in report
    assert "# 待人工复核" in report
    assert "# 输入警告" in report
    assert "# LLM 警告" in report

    assert "# 案例 1" in case_report
    assert "## 语言" in case_report
    assert "## 生成代码" in case_report
    assert "## 解析 / 编译 / 测试" in case_report
    assert "## 根因" in case_report
    assert "## 警告" in case_report
    assert "## 解释" in case_report
    assert "logic mismatch" in case_report
