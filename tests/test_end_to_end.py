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
    assert (output_dir / "case_analysis.jsonl").exists()
    assert (output_dir / "summary.json").exists()
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
