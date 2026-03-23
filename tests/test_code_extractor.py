from faultlens.deterministic.analyzers.code_extractor import (
    ExtractionResult,
    extract_code_blocks,
)


def test_extract_code_blocks_prefers_first_fenced_block() -> None:
    completion = (
        "Here is the approach.\n"
        "```python\n"
        "def solve(x):\n"
        "    return x + 1\n"
        "```\n"
        "And an alternative:\n"
        "```python\n"
        "def solve(x):\n"
        "    return x + 2\n"
        "```"
    )

    result = extract_code_blocks(completion)

    assert isinstance(result, ExtractionResult)
    assert len(result.code_blocks) == 2
    assert "return x + 1" in result.primary_code_text
    assert result.parse_status == "parsed"
    assert "approach" in result.explanation_text.lower()


def test_extract_code_blocks_reports_missing_code() -> None:
    result = extract_code_blocks("Only explanation without any code.")

    assert result.code_blocks == []
    assert result.primary_code_text is None
    assert result.parse_status == "no_code_found"
