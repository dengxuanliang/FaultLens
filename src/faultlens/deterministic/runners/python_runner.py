from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import ast
import sys
import os

from faultlens.deterministic.runners.base import (
    BaseRunner,
    RunnerResult,
    run_command,
    sandbox_available,
    workspace_env,
    write_workspace_files,
)


class PythonRunner(BaseRunner):
    language = "python"

    def run(self, solution_code: str, test_code: str, timeout_seconds: int) -> RunnerResult:
        if not sandbox_available():
            return RunnerResult(
                language=self.language,
                available=False,
                compile_status="unavailable",
                test_status="unavailable",
                timed_out=False,
                exit_code=None,
                stdout_excerpt="",
                stderr_excerpt="",
                warnings=["sandbox-exec unavailable; runtime execution disabled"],
            )
        try:
            ast.parse(solution_code)
        except SyntaxError as exc:
            message = f"SyntaxError: {exc.msg} (line {exc.lineno})"
            return RunnerResult(
                language=self.language,
                available=True,
                compile_status="failed",
                test_status="not_run",
                timed_out=False,
                exit_code=1,
                stdout_excerpt="",
                stderr_excerpt=message,
                warnings=[],
            )

        combined_code = f"{solution_code.rstrip()}\n\n{test_code.rstrip()}\n"
        with TemporaryDirectory(prefix="faultlens-python-runner-", dir=os.getcwd()) as tmp_dir:
            write_workspace_files(
                workspace=Path(tmp_dir),
                files={"main.py": combined_code},
            )
            result = run_command(
                [sys.executable, "main.py"],
                cwd=Path(tmp_dir),
                timeout_seconds=timeout_seconds,
                env=workspace_env(),
            )

        if result.warnings and result.returncode is None and not result.timed_out:
            return RunnerResult(
                language=self.language,
                available=False,
                compile_status="unavailable",
                test_status="unavailable",
                timed_out=False,
                exit_code=None,
                stdout_excerpt=result.stdout_excerpt,
                stderr_excerpt=result.stderr_excerpt,
                warnings=result.warnings,
            )
        if result.timed_out:
            return RunnerResult(
                language=self.language,
                available=True,
                compile_status="passed",
                test_status="timeout",
                timed_out=True,
                exit_code=None,
                stdout_excerpt=result.stdout_excerpt,
                stderr_excerpt=result.stderr_excerpt,
                warnings=result.warnings,
            )
        return RunnerResult(
            language=self.language,
            available=True,
            compile_status="passed",
            test_status="passed" if result.returncode == 0 else "failed",
            timed_out=False,
            exit_code=result.returncode,
            stdout_excerpt=result.stdout_excerpt,
            stderr_excerpt=result.stderr_excerpt,
            warnings=result.warnings,
        )
