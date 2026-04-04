import os

from faultlens.config import load_settings
from faultlens.env import load_dotenv


def test_load_dotenv_reads_project_env(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FAULTLENS_MODEL=test-model\n", encoding="utf-8")

    values = load_dotenv(env_path)

    assert values["FAULTLENS_MODEL"] == "test-model"


def test_load_dotenv_supports_export_quotes_and_inline_comments(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        'export FAULTLENS_MODEL="quoted-model" # keep this comment\n'
        "FAULTLENS_BASE_URL='https://example.invalid/v1'  # trailing comment\n"
        "FAULTLENS_API_KEY=plain-value\n",
        encoding="utf-8",
    )

    values = load_dotenv(env_path)

    assert values["FAULTLENS_MODEL"] == "quoted-model"
    assert values["FAULTLENS_BASE_URL"] == "https://example.invalid/v1"
    assert values["FAULTLENS_API_KEY"] == "plain-value"


def test_load_settings_prefers_explicit_values(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FAULTLENS_MODEL=env-model\nFAULTLENS_OUTPUT_DIR=env-outputs\n",
        encoding="utf-8",
    )

    settings = load_settings(env_path=env_path, model="cli-model")

    assert settings.model == "cli-model"
    assert settings.output_dir.name == "env-outputs"


def test_load_settings_auto_loads_default_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FAULTLENS_MODEL=auto-model\n", encoding="utf-8")

    settings = load_settings()

    assert settings.model == "auto-model"


def test_load_settings_reads_scaling_defaults(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FAULTLENS_LLM_MAX_WORKERS=4\nFAULTLENS_LLM_MAX_RETRIES=2\nFAULTLENS_LLM_RETRY_BACKOFF_SECONDS=3\nFAULTLENS_LLM_RETRY_ON_5XX=false\nFAULTLENS_RESUME=true\n",
        encoding="utf-8",
    )

    settings = load_settings(env_path=env_path)

    assert settings.llm_max_workers == 4
    assert settings.llm_max_retries == 2
    assert settings.llm_retry_backoff_seconds == 3
    assert settings.llm_retry_on_5xx is False
    assert settings.resume is True


def test_tests_do_not_inherit_real_llm_credentials_from_shell(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = load_settings()

    assert os.environ.get("FAULTLENS_API_KEY") is None
    assert os.environ.get("FAULTLENS_BASE_URL") is None
    assert os.environ.get("FAULTLENS_MODEL") is None
    assert settings.api_key is None
    assert settings.base_url is None
    assert settings.model is None
