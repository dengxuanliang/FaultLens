from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def isolate_llm_credentials(monkeypatch) -> None:
    for key in ("FAULTLENS_API_KEY", "FAULTLENS_BASE_URL", "FAULTLENS_MODEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def isolate_default_dotenv(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
