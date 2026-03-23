from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from faultlens.deterministic.runners.base import BaseRunner
from faultlens.deterministic.runners.cpp_runner import CppRunner
from faultlens.deterministic.runners.go_runner import GoRunner
from faultlens.deterministic.runners.java_runner import JavaRunner
from faultlens.deterministic.runners.python_runner import PythonRunner


class UnsupportedRunner(BaseRunner):
    language = "unsupported"

    def __init__(self, requested_language: str) -> None:
        self.requested_language = requested_language

    def run(self, solution_code: str, test_code: str, timeout_seconds: int):
        raise ValueError(f"unsupported language: {self.requested_language}")


@dataclass
class RunnerRegistry:
    runners: Dict[str, BaseRunner]

    def for_language(self, language: str) -> BaseRunner:
        normalized = _normalize_language(language)
        return self.runners.get(normalized, UnsupportedRunner(normalized))


def _normalize_language(language: str) -> str:
    raw = (language or "").strip().lower()
    aliases = {
        "python3": "python",
        "py": "python",
        "c++": "cpp",
        "cc": "cpp",
        "cpp": "cpp",
        "golang": "go",
    }
    return aliases.get(raw, raw)


def build_runner_registry() -> RunnerRegistry:
    return RunnerRegistry(
        runners={
            "python": PythonRunner(),
            "cpp": CppRunner(),
            "java": JavaRunner(),
            "go": GoRunner(),
        }
    )
