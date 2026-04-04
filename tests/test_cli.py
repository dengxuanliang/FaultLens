from faultlens.cli import main
from faultlens.scale.run_store import RunStore


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


def test_cli_accepts_scaling_flags(tmp_path, fixtures_dir, monkeypatch):
    output_dir = tmp_path / "outs"
    monkeypatch.chdir(tmp_path)

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


def test_cli_supports_rerender_subcommand(tmp_path, fixtures_dir, monkeypatch):
    output_dir = tmp_path / "outs"
    monkeypatch.chdir(tmp_path)

    analyze_exit = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
    ])

    assert analyze_exit == 0

    original = (output_dir / "analysis_report.md").read_text(encoding="utf-8")
    (output_dir / "analysis_report.md").write_text("stale", encoding="utf-8")

    rerender_exit = main([
        "rerender",
        "--output-dir",
        str(output_dir),
    ])

    assert rerender_exit == 0
    assert (output_dir / "analysis_report.md").read_text(encoding="utf-8") == original


def test_cli_rejects_legacy_disable_checkpoints_flag(capsys):
    exit_code = main(["analyze", "--input", "a.jsonl", "b.jsonl", "--disable-checkpoints"])

    assert exit_code == 2


def test_cli_supports_status_subcommand(tmp_path, fixtures_dir):
    output_dir = tmp_path / "outs"

    analyze_exit = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
    ])
    assert analyze_exit == 0

    status_exit = main([
        "status",
        "--output-dir",
        str(output_dir),
    ])

    assert status_exit == 0


def test_cli_supports_export_case_subcommand(tmp_path, fixtures_dir):
    output_dir = tmp_path / "outs"

    analyze_exit = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
    ])
    assert analyze_exit == 0

    target = output_dir / "exported-case-2.md"
    export_exit = main([
        "export-case",
        "--output-dir",
        str(output_dir),
        "--case-id",
        "2",
        "--dest",
        str(target),
    ])

    assert export_exit == 0
    assert target.exists()
    assert "# 案例 2" in target.read_text(encoding="utf-8")


def test_cli_case_id_only_affects_extra_exemplar_export(tmp_path, fixtures_dir):
    output_dir = tmp_path / "outs"

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
    rows = (output_dir / "case_analysis.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([line for line in rows if line.strip()]) == 2
    assert any(path.name.endswith("-2.md") for path in (output_dir / "exemplars").glob("*.md"))
