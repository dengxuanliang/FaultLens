from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
import re
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


class JavaRunner(BaseRunner):
    language = "java"

    def run(self, solution_code: str, test_code: str, timeout_seconds: int) -> RunnerResult:
        javac_path = shutil.which("javac")
        java_path = shutil.which("java")
        if not sandbox_available() or not javac_path or not java_path:
            return self._unavailable()
        if not command_available([javac_path, "-version"]) or not command_available([java_path, "-version"]):
            return self._unavailable()

        entrypoint = self._entrypoint_class_name(test_code) or "TestMain"
        solution_class = self._solution_class_name(solution_code) or "Main"
        with TemporaryDirectory(prefix="faultlens-java-runner-", dir=os.getcwd()) as tmp_dir:
            workspace = Path(tmp_dir)
            files = {
                f"{solution_class}.java": solution_code,
                f"{entrypoint}.java": test_code,
            }
            write_workspace_files(workspace, files)
            compile_result = run_command(
                [javac_path, f"{solution_class}.java", f"{entrypoint}.java"],
                cwd=workspace,
                timeout_seconds=timeout_seconds,
                env=workspace_env(),
            )
            if compile_result.warnings and compile_result.returncode is None and not compile_result.timed_out:
                return self._unavailable(compile_result.warnings)
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
                [java_path, entrypoint],
                cwd=workspace,
                timeout_seconds=timeout_seconds,
                env=workspace_env(),
            )
            if run_result.warnings and run_result.returncode is None and not run_result.timed_out:
                return self._unavailable(run_result.warnings)

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

    def _entrypoint_class_name(self, code: str) -> str | None:
        match = re.search(r"public\s+class\s+([A-Za-z_][A-Za-z0-9_]*)", code)
        if match:
            return match.group(1)
        return None

    def _solution_class_name(self, code: str) -> str | None:
        match = re.search(r"public\s+class\s+([A-Za-z_][A-Za-z0-9_]*)", code)
        if match:
            return match.group(1)
        return None

    def _unavailable(self, warnings: list[str] | None = None) -> RunnerResult:
        return RunnerResult(
            language=self.language,
            available=False,
            compile_status="unavailable",
            test_status="unavailable",
            timed_out=False,
            exit_code=None,
            stdout_excerpt="",
            stderr_excerpt="",
            warnings=warnings or ["java toolchain unavailable or sandbox disabled"],
        )
