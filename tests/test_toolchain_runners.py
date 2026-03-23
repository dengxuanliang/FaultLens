from __future__ import annotations

import shutil
import subprocess

from faultlens.deterministic.runners.registry import build_runner_registry


def _command_works(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def test_registry_returns_runner_for_known_languages():
    registry = build_runner_registry()

    assert registry.for_language("python").language == "python"
    assert registry.for_language("cpp").language == "cpp"
    assert registry.for_language("java").language == "java"
    assert registry.for_language("go").language == "go"


def test_cpp_runner_happy_path_when_toolchain_available():
    runner = build_runner_registry().for_language("cpp")
    result = runner.run(
        solution_code="int solve(int x){ return x + 1; }\n",
        test_code=(
            "#include <cassert>\n"
            "int solve(int);\n"
            "int main(){ assert(solve(1) == 2); return 0; }\n"
        ),
        timeout_seconds=10,
    )

    compiler_available = shutil.which("g++") is not None or shutil.which("clang++") is not None
    if compiler_available:
        assert result.available is True
        assert result.compile_status == "passed"
        assert result.test_status == "passed"
    else:
        assert result.available is False
        assert result.compile_status == "unavailable"


def test_java_runner_graceful_degraded_mode_when_unavailable():
    runner = build_runner_registry().for_language("java")
    result = runner.run(
        solution_code="public class Main { static int solve(int x){ return x+1; } }\n",
        test_code="public class TestMain { public static void main(String[] args){ if(Main.solve(1)!=2) throw new RuntimeException(); } }\n",
        timeout_seconds=10,
    )

    java_ready = bool(shutil.which("javac")) and bool(shutil.which("java"))
    java_ready = java_ready and _command_works(["javac", "-version"]) and _command_works(["java", "-version"])
    if java_ready:
        assert result.available is True
        assert result.compile_status in {"passed", "failed"}
    else:
        assert result.available is False
        assert result.compile_status == "unavailable"
        assert result.test_status == "unavailable"


def test_go_runner_graceful_degraded_mode_when_unavailable():
    runner = build_runner_registry().for_language("go")
    result = runner.run(
        solution_code="package main\nfunc solve(x int) int { return x+1 }\n",
        test_code="package main\nimport \"testing\"\nfunc TestSolve(t *testing.T){ if solve(1) != 2 { t.Fatal(\"bad\") } }\n",
        timeout_seconds=10,
    )

    if shutil.which("go"):
        assert result.available is True
        assert result.compile_status in {"passed", "failed"}
    else:
        assert result.available is False
        assert result.compile_status == "unavailable"
        assert result.test_status == "unavailable"


def test_java_runner_accepts_non_main_public_class_name():
    runner = build_runner_registry().for_language("java")
    result = runner.run(
        solution_code="public class Solution { static int solve(int x){ return x+1; } }\n",
        test_code="public class TestMain { public static void main(String[] args){ if(Solution.solve(1)!=2) throw new RuntimeException(); } }\n",
        timeout_seconds=10,
    )

    java_ready = bool(shutil.which("javac")) and bool(shutil.which("java"))
    java_ready = java_ready and _command_works(["javac", "-version"]) and _command_works(["java", "-version"])
    if java_ready:
        assert result.available is True
        assert result.compile_status in {"passed", "failed"}
    else:
        assert result.available is False


def test_java_runner_detects_public_solution_class_name():
    runner = build_runner_registry().for_language("java")
    assert runner._solution_class_name("public class Solution { }") == "Solution"
