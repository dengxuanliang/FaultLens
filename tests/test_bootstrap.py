from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_bootstrap_script_exists_and_installs_project() -> None:
    script_path = REPO_ROOT / "scripts/bootstrap.sh"

    assert script_path.exists()
    content = script_path.read_text(encoding="utf-8")
    assert "python3.11" in content
    assert "python3" in content
    assert "sys.version_info[:2] < (3, 11)" in content
    assert 'PYTHON_BIN="${PYTHON_BIN:-"' not in content
    assert ".venv" in content
    assert "install -e ." in content
    assert "bin/pip" in content
    assert "faultlens --help" in content or ".venv/bin/faultlens --help" in content


def test_run_wrapper_exists_and_executes_project_cli() -> None:
    script_path = REPO_ROOT / "scripts/run.sh"

    assert script_path.exists()
    content = script_path.read_text(encoding="utf-8")
    assert ".venv/bin/faultlens" in content
    assert 'exec "$ROOT_DIR/.venv/bin/faultlens" "$@"' in content


def test_quickstart_documents_bootstrap_and_env_configuration() -> None:
    content = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "./scripts/bootstrap.sh" in content
    assert "source .venv/bin/activate" in content
    assert "./scripts/run.sh analyze" in content
    assert "cp .env.example .env" in content
    assert "export FAULTLENS_API_KEY" in content


def test_gitignore_ignores_project_virtualenv() -> None:
    content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".venv/" in content
    assert "*.egg-info/" in content or "src/faultlens.egg-info/" in content


def test_env_example_removes_stale_checkpoint_setting() -> None:
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "FAULTLENS_ENABLE_CHECKPOINTS" not in content
