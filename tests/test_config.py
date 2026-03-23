from faultlens.config import load_settings
from faultlens.env import load_dotenv


def test_load_dotenv_reads_project_env(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("FAULTLENS_MODEL=test-model\n", encoding="utf-8")

    values = load_dotenv(env_path)

    assert values["FAULTLENS_MODEL"] == "test-model"


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
