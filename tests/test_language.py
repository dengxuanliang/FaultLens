from faultlens.deterministic.analyzers.language import (
    LanguageInference,
    infer_language,
)


def test_infer_language_prefers_inference_labels() -> None:
    result = infer_language(
        inference_labels={"programming_language": "python"},
        results_tags={"programming_language": "go"},
        fence_language="java",
        completion_code="public class Main {}",
    )

    assert isinstance(result, LanguageInference)
    assert result.primary == "python"
    assert result.source == "inference_labels"


def test_infer_language_falls_back_to_code_heuristic() -> None:
    result = infer_language(
        inference_labels={},
        results_tags={},
        fence_language=None,
        completion_code="func main() { println(\"hello\") }",
    )

    assert result.primary == "go"
    assert result.source == "heuristic"
