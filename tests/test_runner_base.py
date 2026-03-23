from __future__ import annotations

from pathlib import Path

from faultlens.deterministic.runners.base import (
    DEFAULT_OUTPUT_LIMIT,
    run_command_in_workspace,
    sandbox_available,
    workspace_env,
)


def test_workspace_env_keeps_path_and_removes_pythonpath(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PYTHONPATH", "/tmp/unsafe")

    env = workspace_env()

    assert env["PATH"] == "/usr/bin:/bin"
    assert "PYTHONPATH" not in env


def test_run_command_truncates_output_and_cleans_workspace():
    command = [
        "python3",
        "-c",
        (
            "import pathlib; "
            "pathlib.Path('inside.txt').write_text('ok', encoding='utf-8'); "
            "print('x'*1000)"
        ),
    ]
    result = run_command_in_workspace(
        command=command,
        files={},
        timeout_seconds=5,
        output_limit=64,
    )

    assert result.returncode == 0
    assert len(result.stdout_excerpt) <= DEFAULT_OUTPUT_LIMIT
    assert result.workspace_removed is True
    assert not Path(result.workspace_path).exists()


def test_run_command_times_out():
    command = ["python3", "-c", "import time; time.sleep(2)"]
    result = run_command_in_workspace(
        command=command,
        files={},
        timeout_seconds=1,
        output_limit=128,
    )

    assert result.timed_out is True
    assert result.returncode is None
    assert result.workspace_removed is True


def test_run_command_confines_file_access_when_sandbox_available(tmp_path: Path):
    if not sandbox_available():
        return
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    command = [
        "python3",
        "-c",
        f"from pathlib import Path; print(Path({outside.as_posix()!r}).read_text())",
    ]
    result = run_command_in_workspace(command=command, files={}, timeout_seconds=5, output_limit=128)

    assert result.returncode != 0
