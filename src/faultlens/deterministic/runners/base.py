from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Mapping, Optional, Sequence
import os
import shutil
import subprocess

DEFAULT_OUTPUT_LIMIT = 4096
DEFAULT_TIMEOUT_SECONDS = 10
CONFINEMENT_BOUNDARY = (
    "Execution is sandboxed with sandbox-exec and confined to a temporary workspace. "
    "If sandbox-exec is unavailable, runtime execution is disabled."
)


@dataclass
class CommandResult:
    returncode: Optional[int]
    timed_out: bool
    stdout_excerpt: str
    stderr_excerpt: str
    warnings: List[str] = field(default_factory=list)
    workspace_path: str = ""
    workspace_removed: bool = False


@dataclass
class RunnerResult:
    language: str
    available: bool
    compile_status: str
    test_status: str
    timed_out: bool
    exit_code: Optional[int]
    stdout_excerpt: str
    stderr_excerpt: str
    warnings: List[str] = field(default_factory=list)
    confinement_boundary: str = CONFINEMENT_BOUNDARY


class BaseRunner:
    language: str = "unknown"

    def run(self, solution_code: str, test_code: str, timeout_seconds: int) -> RunnerResult:
        raise NotImplementedError


def truncate_output(text: str, limit: int = DEFAULT_OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def sandbox_available() -> bool:
    return shutil.which("sandbox-exec") is not None


def workspace_env(extra_env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in ("PATH", "TMPDIR", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["PYTHONNOUSERSITE"] = "1"
    if extra_env:
        for key, value in extra_env.items():
            env[key] = value
    env.pop("PYTHONPATH", None)
    env.pop("HOME", None)
    return env


def write_workspace_files(workspace: Path, files: Mapping[str, str]) -> None:
    for relative_path, content in files.items():
        file_path = workspace / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


def _sandboxed_command(command: Sequence[str], cwd: Path) -> Sequence[str]:
    if not sandbox_available():
        raise RuntimeError("sandbox-exec unavailable")
    allowed_roots = [str(cwd), "/usr", "/bin", "/System", "/Library", "/Applications", "/opt"]
    rules = [
        "(version 1)",
        '(import "system.sb")',
        "(allow process*)",
        '(deny file-read* (subpath "/Users"))',
        '(deny file-read* (subpath "/tmp"))',
        '(deny file-read* (subpath "/private/tmp"))',
        '(deny file-read* (subpath "/private/var/folders"))',
    ]
    for root in allowed_roots:
        rules.append(f'(allow file-read* (subpath "{root}"))')
    rules.append(f'(allow file-write* (subpath "{cwd}"))')
    profile = " ".join(rules)
    return ["/usr/bin/sandbox-exec", "-p", profile, *command]


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    env: Optional[Mapping[str, str]] = None,
) -> CommandResult:
    if not sandbox_available():
        return CommandResult(
            returncode=None,
            timed_out=False,
            stdout_excerpt="",
            stderr_excerpt="",
            warnings=["sandbox-exec unavailable; runtime execution disabled"],
        )
    try:
        completed = subprocess.run(
            list(_sandboxed_command(command, cwd)),
            cwd=str(cwd),
            env={**workspace_env(), **(dict(env) if env else {}), "TMPDIR": str(cwd), "TEMP": str(cwd), "TMP": str(cwd)},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            timed_out=False,
            stdout_excerpt=truncate_output(completed.stdout or "", output_limit),
            stderr_excerpt=truncate_output(completed.stderr or "", output_limit),
            warnings=[],
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return CommandResult(
            returncode=None,
            timed_out=True,
            stdout_excerpt=truncate_output(stdout, output_limit),
            stderr_excerpt=truncate_output(stderr, output_limit),
            warnings=["process timed out"],
        )


def run_command_in_workspace(
    *,
    command: Sequence[str],
    files: Mapping[str, str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    env: Optional[Mapping[str, str]] = None,
) -> CommandResult:
    workspace_path = ""
    with TemporaryDirectory(prefix="faultlens-runner-", dir=os.getcwd()) as tmp_dir:
        workspace = Path(tmp_dir)
        workspace_path = str(workspace)
        write_workspace_files(workspace, files)
        result = run_command(
            command,
            cwd=workspace,
            timeout_seconds=timeout_seconds,
            output_limit=output_limit,
            env=env,
        )
        result.workspace_path = workspace_path
    result.workspace_removed = not Path(workspace_path).exists()
    return result


def command_available(command: Sequence[str], timeout_seconds: int = 3) -> bool:
    try:
        probe = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=workspace_env(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0
