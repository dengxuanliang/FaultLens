from faultlens.models import AttributionResult
from faultlens.reporting.render import render_case_report


def test_case_report_localizes_internal_enums_but_keeps_original_language_text():
    result = AttributionResult(
        case_id="42",
        case_status="attributable_failure",
        accepted=False,
        root_cause="solution_incorrect",
        deterministic_signals=["test_failure", "logic_mismatch"],
        deterministic_findings={
            "primary_language": "python",
            "completion_code": "def solve(x): return x + 2",
            "parse_status": "parsed",
            "compile_status": "passed",
            "test_status": "failed",
            "canonical_diff_summary": "diff",
            "test_harness_alignment_summary": "aligned",
        },
        explanation="The implementation adds 2 instead of doubling x.",
        improvement_hints=["Use multiplication instead of addition."],
        llm_parse_mode="adaptive_parse",
        llm_parse_reason="sectioned_text",
        llm_raw_response_excerpt="Root Cause: solution incorrect",
        review_reason="possible_evaluation_mismatch",
    )

    text = render_case_report(result)

    assert "可归因失败" in text
    assert "解答逻辑错误" in text
    assert "测试失败、逻辑不匹配" in text
    assert "The implementation adds 2 instead of doubling x." in text
    assert "LLM 解析模式" in text
    assert "Root Cause: solution incorrect" in text
