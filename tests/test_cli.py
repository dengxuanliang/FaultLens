from faultlens.cli import main


def test_cli_requires_two_input_files(capsys):
    exit_code = main(["analyze", "--input", "only-one.jsonl"])
    assert exit_code == 2


def test_cli_auto_loads_dotenv_output_dir(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FAULTLENS_OUTPUT_DIR=env-outs\n", encoding="utf-8")

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
    ])

    assert exit_code == 0
    assert (tmp_path / "env-outs" / "analysis_report.md").exists()
    assert (tmp_path / "env-outs" / "hierarchical_root_cause_report.md").exists()
    summary = (tmp_path / "env-outs" / "summary.json").read_text(encoding="utf-8")
    assert "hierarchy_subtype_counts" in summary
    assert "hierarchy_root_cause_cross" in summary


def test_cli_accepts_scaling_flags(tmp_path, fixtures_dir):
    output_dir = tmp_path / "outs"

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--llm-max-workers",
        "2",
        "--llm-max-retries",
        "5",
        "--llm-retry-backoff-seconds",
        "3",
        "--no-llm-retry-on-5xx",
        "--resume",
    ])

    assert exit_code == 0
    assert (output_dir / "analysis_report.md").exists()
    assert (output_dir / "hierarchical_root_cause_report.md").exists()
