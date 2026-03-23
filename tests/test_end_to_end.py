import json
from pathlib import Path

from faultlens.cli import main


def test_cli_analyze_generates_outputs(tmp_path: Path, fixtures_dir: Path):
    output_dir = tmp_path / "outputs"

    exit_code = main(
        [
            "analyze",
            "--input",
            str(fixtures_dir / "inference_sample.jsonl"),
            str(fixtures_dir / "results_sample.jsonl"),
            "--output-dir",
            str(output_dir),
            "--case-id",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "analysis_report.md").exists()
    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# Input Warnings" in report_text
    assert "# LLM Warnings" in report_text
    assert (output_dir / "case_analysis.jsonl").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "run_metadata.json").exists()
    assert (output_dir / "cases" / "2.md").exists()
    exemplar_dir = output_dir / "exemplars"
    assert exemplar_dir.exists()

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# Run Summary" in report_text
    assert "# Deterministic Analysis Summary" in report_text
    assert "# LLM Root Cause Distribution" in report_text
    assert "# Cross Analysis" in report_text
    assert "# Slice Analysis" in report_text
    assert "# Representative Exemplars" in report_text
    assert "# Review Queue" in report_text

    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "## Root Cause" in case_text
    assert "## Explanation" in case_text
    assert "## Parse / Compile / Test" in case_text

    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {row["case_id"] for row in rows} == {"1", "2"}


def test_cli_survives_llm_failure_and_falls_back(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    def boom(self, messages):
        raise RuntimeError("network down")

    monkeypatch.setattr("faultlens.llm.client.LLMClient.complete_json", boom)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--api-key",
        "k",
        "--base-url",
        "http://invalid.local",
        "--model",
        "m",
    ])

    assert exit_code == 0
    assert (output_dir / "analysis_report.md").exists()
    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# Input Warnings" in report_text
    assert "# LLM Warnings" in report_text


def test_case_report_surfaces_runner_degradation_warnings(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    class FakeClient:  # pragma: no cover - simple monkeypatch target
        pass

    def fake_analyze(cases, execution_timeout=10):
        analyzed = []
        for case in cases:
            case = dict(case)
            case["deterministic_findings"] = {
                "test_status": "unavailable",
                "compile_status": "unavailable",
                "runner_warnings": ["go toolchain unavailable or sandbox disabled"],
                "completion_code": "package main",
                "primary_language": "go",
                "canonical_diff_summary": "n/a",
                "test_harness_alignment_summary": "n/a",
            }
            case["deterministic_signals"] = ["suspicious_eval_mismatch"]
            case["deterministic_root_cause_hint"] = "possible_evaluation_mismatch"
            analyzed.append(case)
        return analyzed

    monkeypatch.setattr("faultlens.orchestrator.analyze_cases_deterministically", fake_analyze)

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--case-id",
        "2",
    ])

    assert exit_code == 0
    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "go toolchain unavailable or sandbox disabled" in case_text
