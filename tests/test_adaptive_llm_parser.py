from faultlens.llm.adaptive_parser import parse_attribution_response


def test_parse_strict_json_response():
    parsed = parse_attribution_response(
        '{"root_cause":"solution_incorrect","explanation":"logic mismatch","observable_evidence":["assert failed"],"improvement_hints":["check math"],"llm_signals":["json"]}'
    )

    assert parsed.status == "strict_json"
    assert parsed.payload["root_cause"] == "solution_incorrect"


def test_parse_english_sectioned_prose_response():
    parsed = parse_attribution_response(
        """Root Cause: implementation bug
Explanation: The code is incorrect because it adds 2 instead of doubling x.
Evidence:
- solve(7) returned 9 instead of 14
Improvement Hints:
- Replace + 2 with * 2
"""
    )

    assert parsed.status == "adaptive_parse"
    assert parsed.payload["root_cause"] == "implementation_bug"
    assert "adds 2 instead of doubling x" in parsed.payload["explanation"]
    assert parsed.payload["observable_evidence"] == ["solve(7) returned 9 instead of 14"]


def test_parse_chinese_sectioned_prose_response():
    parsed = parse_attribution_response(
        """根因：评测结果不一致
解释：代码与题意一致，并且通过给定测试，但 accepted=false。
证据：
- 代码实现为 x*x
- 给定测试通过
建议：
- 检查评测流水线或标签
"""
    )

    assert parsed.status == "adaptive_parse"
    assert parsed.payload["root_cause"] == "possible_evaluation_mismatch"
    assert "accepted=false" in parsed.payload["explanation"]
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
