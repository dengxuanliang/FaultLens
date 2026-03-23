from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
import shutil
import os

from faultlens.deterministic.runners.base import (
    BaseRunner,
    RunnerResult,
    run_command,
    sandbox_available,
    workspace_env,
    write_workspace_files,
)


class CppRunner(BaseRunner):
    language = "cpp"

    def run(self, solution_code: str, test_code: str, timeout_seconds: int) -> RunnerResult:
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not sandbox_available() or not compiler:
            return RunnerResult(
                language=self.language,
                available=False,
                compile_status="unavailable",
                test_status="unavailable",
                timed_out=False,
                exit_code=None,
                stdout_excerpt="",
                stderr_excerpt="",
                warnings=["sandbox-exec unavailable or no C++ compiler found on PATH"],
            )

        source = f"{solution_code.rstrip()}\n\n{test_code.rstrip()}\n"
        with TemporaryDirectory(prefix="faultlens-cpp-runner-", dir=os.getcwd()) as tmp_dir:
            workspace = Path(tmp_dir)
            write_workspace_files(workspace, {"main.cpp": source})
            compile_result = run_command(
                [compiler, "main.cpp", "-std=c++17", "-O0", "-o", "program"],
                cwd=workspace,
                timeout_seconds=timeout_seconds,
                env=workspace_env(),
            )
            if compile_result.warnings and compile_result.returncode is None and not compile_result.timed_out:
                return RunnerResult(
                    language=self.language,
                    available=False,
                    compile_status="unavailable",
                    test_status="unavailable",
                    timed_out=False,
                    exit_code=None,
                    stdout_excerpt=compile_result.stdout_excerpt,
                    stderr_excerpt=compile_result.stderr_excerpt,
                    warnings=compile_result.warnings,
                )
            if compile_result.timed_out:
                return RunnerResult(
                    language=self.language,
                    available=True,
                    compile_status="failed",
                    test_status="not_run",
                    timed_out=True,
                    exit_code=None,
                    stdout_excerpt=compile_result.stdout_excerpt,
                    stderr_excerpt=compile_result.stderr_excerpt,
                    warnings=compile_result.warnings,
                )
            if compile_result.returncode != 0:
                return RunnerResult(
                    language=self.language,
                    available=True,
                    compile_status="failed",
                    test_status="not_run",
                    timed_out=False,
                    exit_code=compile_result.returncode,
                    stdout_excerpt=compile_result.stdout_excerpt,
                    stderr_excerpt=compile_result.stderr_excerpt,
                    warnings=compile_result.warnings,
                )

            run_result = run_command(
                ["./program"],
                cwd=workspace,
                timeout_seconds=timeout_seconds,
                env=workspace_env(),
            )
            if run_result.warnings and run_result.returncode is None and not run_result.timed_out:
                return RunnerResult(
                    language=self.language,
                    available=False,
                    compile_status="unavailable",
                    test_status="unavailable",
                    timed_out=False,
                    exit_code=None,
                    stdout_excerpt=run_result.stdout_excerpt,
                    stderr_excerpt=run_result.stderr_excerpt,
                    warnings=run_result.warnings,
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
            compile_status="passed",
            test_status="passed" if run_result.returncode == 0 else "failed",
            timed_out=False,
            exit_code=run_result.returncode,
            stdout_excerpt=run_result.stdout_excerpt,
            stderr_excerpt=run_result.stderr_excerpt,
            warnings=run_result.warnings,
        )
