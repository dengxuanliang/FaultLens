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
    assert "# 输入警告" in report_text
    assert "# LLM 警告" in report_text
    assert (output_dir / "case_analysis.jsonl").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "run_metadata.json").exists()
    assert (output_dir / "cases" / "2.md").exists()
    exemplar_dir = output_dir / "exemplars"
    assert exemplar_dir.exists()

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# 运行摘要" in report_text
    assert "# 确定性分析摘要" in report_text
    assert "# LLM 根因分布" in report_text
    assert "# 交叉分析" in report_text
    assert "# 切片分析" in report_text
    assert "# 代表性案例" in report_text
    assert "# 待人工复核" in report_text

    case_text = (output_dir / "cases" / "2.md").read_text(encoding="utf-8")
    assert "## 根因" in case_text
    assert "## 解释" in case_text
    assert "## 解析 / 编译 / 测试" in case_text

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
    assert "# 输入警告" in report_text
    assert "# LLM 警告" in report_text


def test_cli_records_invalid_llm_response_stats_without_blocking(tmp_path: Path, fixtures_dir: Path, monkeypatch):
    output_dir = tmp_path / "outputs"

    class FakeClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {}

        def complete_json(self, messages):
            self.last_warning = "llm invalid response format: non_json_content"
            self.last_completion_info = {
                "status": "invalid",
                "invalid_reason": "non_json_content",
            }
            return None

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", FakeClient)

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

    run_metadata = json.loads((output_dir / "run_metadata.json").read_text(encoding="utf-8"))
    stats = run_metadata["llm_response_stats"]
    assert stats["attempted"] == 1
    assert stats["strict_json"] == 0
    assert stats["adaptive_parse"] == 0
    assert stats["salvaged"] == 0
    assert stats["skipped_invalid"] == 1
    assert stats["nonconforming"] == 1
    assert stats["nonconforming_percentage"] == 100.0
    assert stats["nonconforming_reasons"] == {"non_json_content": 1}

    rows = [json.loads(line) for line in (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    failure = next(row for row in rows if row["case_id"] == "2")
    assert failure["final_decision_source"] == "deterministic_only"

    report_text = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    assert "# LLM 响应质量" in report_text
    assert "non_json_content" in report_text


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
