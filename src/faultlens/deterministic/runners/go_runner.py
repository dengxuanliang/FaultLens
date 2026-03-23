from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
import shutil
import os

from faultlens.deterministic.runners.base import (
    BaseRunner,
    RunnerResult,
    command_available,
    run_command,
    sandbox_available,
    workspace_env,
    write_workspace_files,
)


class GoRunner(BaseRunner):
    language = "go"

    def run(self, solution_code: str, test_code: str, timeout_seconds: int) -> RunnerResult:
        go_path = shutil.which("go")
        if not sandbox_available() or not go_path or not command_available([go_path, "version"]):
            return RunnerResult(
                language=self.language,
                available=False,
                compile_status="unavailable",
                test_status="unavailable",
                timed_out=False,
                exit_code=None,
                stdout_excerpt="",
                stderr_excerpt="",
                warnings=["go toolchain unavailable or sandbox disabled"],
            )

        with TemporaryDirectory(prefix="faultlens-go-runner-", dir=os.getcwd()) as tmp_dir:
            workspace = Path(tmp_dir)
            write_workspace_files(
                workspace,
                {
                    "solution.go": solution_code,
                    "solution_test.go": test_code,
                },
            )
            result = run_command(
                [go_path, "test", "./..."],
                cwd=workspace,
                timeout_seconds=timeout_seconds,
                env=workspace_env({"GO111MODULE": "off"}),
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
            compile_status="passed" if result.returncode == 0 else "failed",
            test_status="passed" if result.returncode == 0 else "failed",
            timed_out=False,
            exit_code=result.returncode,
            stdout_excerpt=result.stdout_excerpt,
            stderr_excerpt=result.stderr_excerpt,
            warnings=result.warnings,
        )
