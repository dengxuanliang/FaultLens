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
