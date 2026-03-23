from __future__ import annotations

from faultlens.deterministic.runners.python_runner import PythonRunner


def test_python_runner_executes_solution_and_harness():
    runner = PythonRunner()
    result = runner.run(
        solution_code="def solve(x):\n    return x + 1\n",
        test_code="assert solve(1) == 2\n",
        timeout_seconds=5,
    )

    assert result.available is True
    assert result.compile_status == "passed"
    assert result.test_status == "passed"
    assert result.timed_out is False


def test_python_runner_reports_syntax_error():
    runner = PythonRunner()
    result = runner.run(
        solution_code="def solve(x)\n    return x\n",
        test_code="assert True\n",
        timeout_seconds=5,
    )

    assert result.available is True
    assert result.compile_status == "failed"
    assert result.test_status == "not_run"
    assert "syntax" in result.stderr_excerpt.lower() or "invalid" in result.stderr_excerpt.lower()
