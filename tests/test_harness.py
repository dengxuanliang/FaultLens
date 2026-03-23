from faultlens.deterministic.analyzers.harness import (
    analyze_harness_alignment,
    run_syntax_hook,
)
from faultlens.deterministic.signals import CONTROLLED_SIGNALS


def test_run_syntax_hook_reports_python_syntax_error() -> None:
    status, excerpt = run_syntax_hook("python", "def broken(:\n    pass\n")

    assert status == "syntax_error"
    assert excerpt is not None


def test_analyze_harness_alignment_flags_signature_and_entrypoint() -> None:
    completion = "def solve2(x):\n    return x\n"
    test_code = "assert solve(1) == 1\n"

    report = analyze_harness_alignment(
        test_code=test_code,
        completion_code=completion,
        language="python",
        accepted=False,
        pass_metrics={"all_k_correct": 1},
    )

    assert report["signature_check_status"] == "mismatch"
    assert report["entrypoint_check_status"] in {"ok", "mismatch"}
    assert "signature_mismatch" in report["signals"]
    assert "suspicious_eval_mismatch" in report["signals"]


def test_controlled_signal_vocabulary_contains_required_items() -> None:
    required = {
        "syntax_error",
        "signature_mismatch",
        "entrypoint_mismatch",
        "api_mismatch",
        "logic_mismatch",
        "metadata_conflict",
        "suspicious_eval_mismatch",
    }
    assert required.issubset(CONTROLLED_SIGNALS)
