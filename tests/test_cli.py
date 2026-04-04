from faultlens.cli import main
import json
from pathlib import Path


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


def test_cli_status_includes_health_summary(tmp_path, fixtures_dir, capsys):
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

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert status_exit == 0
    assert payload["health_summary"]["run_health"] in {"healthy", "warning", "blocked"}
    assert payload["health_summary"]["finalized_ratio"].endswith("%")
    assert "ready_for_delivery" in payload["health_summary"]


def test_cli_supports_inspect_output_subcommand(tmp_path, fixtures_dir, capsys):
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

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 0
    assert payload["healthy"] is True
    assert payload["missing_artifacts"] == []


def test_cli_inspect_output_detects_missing_artifacts(tmp_path, fixtures_dir, capsys):
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

    (output_dir / "summary.json").unlink()

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert "summary.json" in payload["missing_artifacts"]


def test_cli_inspect_output_detects_missing_manifest(tmp_path, fixtures_dir, capsys):
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

    (output_dir / "analysis_manifest.json").unlink()

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["consistency_checks"]["manifests"]["healthy"] is False
    assert "analysis_manifest.json" in payload["consistency_checks"]["manifests"]["missing"]


def test_cli_inspect_output_detects_case_markdown_mismatch(tmp_path, fixtures_dir, capsys):
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

    (output_dir / "cases" / "2.md").unlink()

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["healthy"] is False
    assert payload["consistency_checks"]["case_markdown"]["healthy"] is False
    assert "2" in payload["consistency_checks"]["case_markdown"]["missing_case_ids"]


def test_cli_inspect_output_detects_summary_count_mismatch(tmp_path, fixtures_dir, capsys):
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

    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["total_cases"] = 999
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["consistency_checks"]["summary"]["healthy"] is False
    assert payload["consistency_checks"]["summary"]["reported_total_cases"] == 999
    assert payload["consistency_checks"]["summary"]["derived_total_cases"] == 2


def test_cli_inspect_output_detects_run_metadata_case_count_mismatch(tmp_path, fixtures_dir, capsys):
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

    metadata_path = output_dir / "run_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["case_counts"]["passed"] = 999
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["consistency_checks"]["run_metadata"]["healthy"] is False
    assert payload["consistency_checks"]["run_metadata"]["reported_case_counts"]["passed"] == 999


def test_cli_inspect_output_detects_missing_exemplar_file(tmp_path, fixtures_dir, capsys):
    output_dir = tmp_path / "outs"

    analyze_exit = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--case-id",
        "2",
    ])
    assert analyze_exit == 0

    exemplar = next((output_dir / "exemplars").glob("*.md"))
    exemplar.unlink()

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["consistency_checks"]["exemplars"]["healthy"] is False
    assert payload["consistency_checks"]["exemplars"]["rendered_count"] == 0


def test_cli_inspect_output_detects_missing_llm_raw_response_artifact(tmp_path, fixtures_dir, capsys, monkeypatch):
    output_dir = tmp_path / "outs"
    raw_response = '{"root_cause":"solution_incorrect","explanation":"logic mismatch"}'

    class FakeClient:
        def __init__(self, settings):
            self.enabled = True
            self.last_warning = None
            self.last_completion_info = {
                "status": "strict_json",
                "invalid_reason": None,
                "raw_response_excerpt": '{"root_cause":"solution_incorrect"}',
                "raw_response_text": raw_response,
                "raw_response_sha256": "abc123",
            }

        def complete_json(self, messages):
            return {
                "root_cause": "solution_incorrect",
                "explanation": "logic mismatch",
                "observable_evidence": ["assert failed"],
                "improvement_hints": ["compare against reference"],
                "llm_signals": ["json"],
                "evidence_refs": [{"source": "tests"}],
            }

    monkeypatch.setattr("faultlens.orchestrator.LLMClient", FakeClient)

    analyze_exit = main([
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
    assert analyze_exit == 0

    (output_dir / "llm_raw_responses" / "2.txt").unlink()

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["consistency_checks"]["llm_raw_responses"]["healthy"] is False
    assert payload["consistency_checks"]["llm_raw_responses"]["missing_paths"] == ["llm_raw_responses/2.txt"]


def test_cli_inspect_output_detects_unexpected_case_markdown_file(tmp_path, fixtures_dir, capsys):
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

    (output_dir / "cases" / "999.md").write_text("# stray\n", encoding="utf-8")

    inspect_exit = main([
        "inspect-output",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert inspect_exit == 1
    assert payload["consistency_checks"]["case_markdown"]["healthy"] is False
    assert "999" in payload["consistency_checks"]["case_markdown"]["unexpected_case_ids"]


def test_cli_rejects_resume_when_output_dir_has_no_existing_run(tmp_path, fixtures_dir, capsys):
    output_dir = tmp_path / "missing-run"

    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(output_dir),
        "--resume",
    ])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "resume requested" in captured.err


def test_cli_prints_user_friendly_error_for_invalid_settings(tmp_path, fixtures_dir, capsys):
    exit_code = main([
        "analyze",
        "--input",
        str(fixtures_dir / "inference_sample.jsonl"),
        str(fixtures_dir / "results_sample.jsonl"),
        "--output-dir",
        str(tmp_path / "outs"),
        "--llm-max-workers",
        "0",
    ])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "llm_max_workers" in captured.err
    assert "Traceback" not in captured.err


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


def test_cli_supports_diagnose_env_subcommand(tmp_path, capsys):
    output_dir = tmp_path / "outs"

    exit_code = main([
        "diagnose-env",
        "--output-dir",
        str(output_dir),
    ])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["output_dir"] == str(output_dir)
    assert "python" in payload
    assert "sandbox" in payload
    assert "runners" in payload
    assert "llm_env" in payload


def test_ci_workflow_runs_pytest_without_real_llm_overrides():
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "pytest -q" in content
    assert "FAULTLENS_API_KEY: \"\"" in content
    assert "FAULTLENS_BASE_URL: \"\"" in content
    assert "FAULTLENS_MODEL: \"\"" in content


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
