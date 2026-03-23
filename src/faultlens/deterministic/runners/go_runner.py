from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
import shutil

from faultlens.deterministic.runners.base import (
    BaseRunner,
    RunnerResult,
    command_available,
    run_command,
    workspace_env,
    write_workspace_files,
)


class GoRunner(BaseRunner):
    language = "go"

    def run(self, solution_code: str, test_code: str, timeout_seconds: int) -> RunnerResult:
        go_path = shutil.which("go")
        if not go_path or not command_available([go_path, "version"]):
            return RunnerResult(
                language=self.language,
                available=False,
                compile_status="unavailable",
                test_status="unavailable",
                timed_out=False,
                exit_code=None,
                stdout_excerpt="",
                stderr_excerpt="",
                warnings=["go toolchain unavailable"],
            )

        with TemporaryDirectory(prefix="faultlens-go-runner-") as tmp_dir:
            workspace = Path(tmp_dir)
            write_workspace_files(
                workspace,
                {
                    "solution.go": solution_code,
                    "solution_test.go": test_code,
                },
            )
            run_result = run_command(
                [go_path, "test", "."],
                cwd=workspace,
                timeout_seconds=timeout_seconds,
                env=workspace_env({"GO111MODULE": "off"}),
            )

        if run_result.timed_out:
            return RunnerResult(
                language=self.language,
                available=True,
                compile_status="passed",
                test_status="timeout",
                timed_out=True,
                exit_code=None,
                stdout_excerpt=run_result.stdout_excerpt,
                stderr_excerpt=run_result.stderr_excerpt,
                warnings=run_result.warnings,
            )
        return RunnerResult(
            language=self.language,
            available=True,
            compile_status="passed" if run_result.returncode == 0 else "failed",
            test_status="passed" if run_result.returncode == 0 else "failed",
            timed_out=False,
            exit_code=run_result.returncode,
            stdout_excerpt=run_result.stdout_excerpt,
            stderr_excerpt=run_result.stderr_excerpt,
            warnings=run_result.warnings,
        )
