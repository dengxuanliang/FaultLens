from faultlens.llm.adaptive_parser import parse_attribution_response


def test_parse_strict_json_response():
    parsed = parse_attribution_response(
        '{"root_cause":"solution_incorrect","secondary_cause":null,"failure_stage":"implementation","summary":"Wrong logic for doubling.","explanation":"logic mismatch","observable_evidence":["assert failed"],"evidence_refs":["deterministic_findings.test_status"],"deterministic_alignment":"consistent","confidence":0.92,"needs_human_review":false,"review_reason":null,"improvement_hints":["check math"],"llm_signals":["json"]}'
    )

    assert parsed.status == "strict_json"
    assert parsed.payload["root_cause"] == "solution_incorrect"
    assert parsed.payload["failure_stage"] == "implementation"
    assert parsed.payload["deterministic_alignment"] == "consistent"
    assert parsed.payload["confidence"] == 0.92
    assert parsed.payload["needs_human_review"] is False


def test_parse_english_sectioned_prose_response():
    parsed = parse_attribution_response(
        """Root Cause: implementation bug
Failure Stage: implementation
Summary: The code uses the wrong operator.
Explanation: The code is incorrect because it adds 2 instead of doubling x.
Evidence:
- solve(7) returned 9 instead of 14
Deterministic Alignment: consistent
Confidence: 0.88
Needs Human Review: false
Improvement Hints:
- Replace + 2 with * 2
"""
    )

    assert parsed.status == "adaptive_parse"
    assert parsed.payload["root_cause"] == "implementation_bug"
    assert parsed.payload["failure_stage"] == "implementation"
    assert parsed.payload["summary"] == "The code uses the wrong operator."
    assert "adds 2 instead of doubling x" in parsed.payload["explanation"]
    assert parsed.payload["observable_evidence"] == ["solve(7) returned 9 instead of 14"]
    assert parsed.payload["deterministic_alignment"] == "consistent"
    assert parsed.payload["confidence"] == 0.88
    assert parsed.payload["needs_human_review"] is False


def test_parse_chinese_sectioned_prose_response():
    parsed = parse_attribution_response(
        """根因：评测结果不一致
失败阶段：evaluation_judgment
摘要：代码正确但评测结果冲突。
解释：代码与题意一致，并且通过给定测试，但 accepted=false。
证据：
- 代码实现为 x*x
- 给定测试通过
置信度：0.71
需要人工复核：true
复核原因：accepted=false 与测试通过冲突
建议：
- 检查评测流水线或标签
"""
    )

    assert parsed.status == "adaptive_parse"
    assert parsed.payload["root_cause"] == "possible_evaluation_mismatch"
    assert parsed.payload["failure_stage"] == "evaluation_judgment"
    assert parsed.payload["summary"] == "代码正确但评测结果冲突。"
    assert "accepted=false" in parsed.payload["explanation"]
    assert parsed.payload["confidence"] == 0.71
    assert parsed.payload["needs_human_review"] is True
    assert parsed.payload["review_reason"] == "accepted=false 与测试通过冲突"
    assert parsed.payload["improvement_hints"] == ["检查评测流水线或标签"]


def test_parse_code_only_reply_as_salvage():
    parsed = parse_attribution_response(
        """```cpp
int solve(int x) {
    return x - 1;
}
```"""
    )

    assert parsed.status == "salvaged"
    assert "code_only_response" in parsed.payload["llm_signals"]
    assert parsed.payload["observable_evidence"]


def test_parse_unstructured_bilingual_reply():
    parsed = parse_attribution_response(
        """The submission appears correct.
结论：更像是评测问题，不是代码逻辑问题。
Evidence:
- passes provided tests
- accepted=false
"""
    )

    assert parsed.status == "adaptive_parse"
    assert parsed.payload["root_cause"] == "possible_evaluation_mismatch"
    assert len(parsed.payload["observable_evidence"]) == 2


def test_parse_new_fields_with_defaults_when_missing():
    parsed = parse_attribution_response(
        """Root Cause: solution incorrect
Explanation: The logic is wrong.
Evidence:
- output is 3, expected 4
"""
    )

    assert parsed.status == "adaptive_parse"
    assert parsed.payload["failure_stage"] == "unknown"
    assert parsed.payload["summary"] == "The logic is wrong."
    assert parsed.payload["deterministic_alignment"] == "insufficient_deterministic_evidence"
    assert parsed.payload["confidence"] == 0.5
    assert parsed.payload["needs_human_review"] is False
    assert parsed.payload["review_reason"] is None
