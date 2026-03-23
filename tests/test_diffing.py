from faultlens.deterministic.analyzers.diffing import summarize_canonical_diff


def test_summarize_canonical_diff_reports_similarity_and_summary() -> None:
    canonical = "def solve(x):\n    return x + 1\n"
    completion = "def solve(x):\n    return x - 1\n"

    summary = summarize_canonical_diff(canonical, completion)

    assert summary["status"] == "ok"
    assert 0.0 <= summary["similarity"] <= 1.0
    assert "return x" in summary["summary"]


def test_summarize_canonical_diff_handles_missing_reference() -> None:
    summary = summarize_canonical_diff(None, "def solve(x):\n    return x\n")

    assert summary["status"] == "missing_reference"
    assert summary["summary"] == "canonical solution missing"
