from pathlib import Path

from faultlens.deterministic.pipeline import analyze_cases_deterministically
from faultlens.deterministic.runners.base import sandbox_available
from faultlens.ingest.resolver import detect_input_roles
from faultlens.normalize.failure_gate import apply_failure_gate
from faultlens.normalize.joiner import join_records


def test_deterministic_pipeline_emits_structured_findings(fixtures_dir: Path):
    resolved = detect_input_roles([
        fixtures_dir / "results_sample.jsonl",
        fixtures_dir / "inference_sample.jsonl",
    ])
    joined = join_records(resolved.inference_path, resolved.results_path)
    gated = [apply_failure_gate(case) for case in joined]

    analyzed = analyze_cases_deterministically(gated, execution_timeout=2)
    failure = next(case for case in analyzed if case["case_id"] == "2")

    if sandbox_available():
        assert failure["deterministic_findings"]["test_status"] == "failed"
    else:
        assert failure["deterministic_findings"]["test_status"] == "unavailable"
    assert "suspicious_eval_mismatch" in failure["deterministic_signals"]
    assert failure["deterministic_findings"]["canonical_diff_summary"]
    assert failure["deterministic_findings"]["test_harness_alignment_summary"]
    assert failure["deterministic_root_cause_hint"]
