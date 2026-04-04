from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from faultlens.env import load_dotenv, merge_env


@dataclass(frozen=True)
class Settings:
    api_key: Optional[str]
    base_url: Optional[str]
    model: Optional[str]
    output_dir: Path
    request_timeout: int
    execution_timeout: int
    llm_max_workers: int = 4
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: int = 2
    llm_retry_on_5xx: bool = True
    resume: bool = False



def load_settings(
    *,
    env_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    output_dir: Optional[Path] = None,
    request_timeout: Optional[int] = None,
    execution_timeout: Optional[int] = None,
    llm_max_workers: Optional[int] = None,
    llm_max_retries: Optional[int] = None,
    llm_retry_backoff_seconds: Optional[int] = None,
    llm_retry_on_5xx: Optional[bool] = None,
    resume: Optional[bool] = None,
) -> Settings:
    env_values = merge_env(load_dotenv(env_path))
    resolved_api_key = api_key or env_values.get("FAULTLENS_API_KEY")
    resolved_base_url = base_url or env_values.get("FAULTLENS_BASE_URL")
    resolved_model = model or env_values.get("FAULTLENS_MODEL")

    settings = Settings(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        model=resolved_model,
        output_dir=Path(output_dir or env_values.get("FAULTLENS_OUTPUT_DIR", "outputs")),
        request_timeout=_parse_int_setting(
            explicit=request_timeout,
            raw=env_values.get("FAULTLENS_REQUEST_TIMEOUT"),
            env_name="FAULTLENS_REQUEST_TIMEOUT",
            label="request_timeout",
            default=60,
            minimum=1,
        ),
        execution_timeout=_parse_int_setting(
            explicit=execution_timeout,
            raw=env_values.get("FAULTLENS_EXECUTION_TIMEOUT"),
            env_name="FAULTLENS_EXECUTION_TIMEOUT",
            label="execution_timeout",
            default=10,
            minimum=1,
        ),
        llm_max_workers=_parse_int_setting(
            explicit=llm_max_workers,
            raw=env_values.get("FAULTLENS_LLM_MAX_WORKERS"),
            env_name="FAULTLENS_LLM_MAX_WORKERS",
            label="llm_max_workers",
            default=4,
            minimum=1,
        ),
        llm_max_retries=_parse_int_setting(
            explicit=llm_max_retries,
            raw=env_values.get("FAULTLENS_LLM_MAX_RETRIES"),
            env_name="FAULTLENS_LLM_MAX_RETRIES",
            label="llm_max_retries",
            default=2,
            minimum=0,
        ),
        llm_retry_backoff_seconds=_parse_int_setting(
            explicit=llm_retry_backoff_seconds,
            raw=env_values.get("FAULTLENS_LLM_RETRY_BACKOFF_SECONDS"),
            env_name="FAULTLENS_LLM_RETRY_BACKOFF_SECONDS",
            label="llm_retry_backoff_seconds",
            default=2,
            minimum=1,
        ),
        llm_retry_on_5xx=_parse_bool(llm_retry_on_5xx, env_values.get("FAULTLENS_LLM_RETRY_ON_5XX"), default=True),
        resume=_parse_bool(resume, env_values.get("FAULTLENS_RESUME"), default=False),
    )
    _validate_llm_settings(settings)
    return settings


def _parse_int_setting(*, explicit: Optional[int], raw: Optional[str], env_name: str, label: str, default: int, minimum: int) -> int:
    value = explicit if explicit is not None else (raw if raw is not None else default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} ({env_name}) must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{label} ({env_name}) must be >= {minimum}")
    return parsed


def _validate_llm_settings(settings: Settings) -> None:
    credentials_started = bool(settings.api_key or settings.base_url)
    if credentials_started and not (settings.api_key and settings.base_url and settings.model):
        missing = [
            name
            for name, value in {
                "FAULTLENS_API_KEY": settings.api_key,
                "FAULTLENS_BASE_URL": settings.base_url,
                "FAULTLENS_MODEL": settings.model,
            }.items()
            if not value
        ]
        raise ValueError(f"incomplete LLM configuration; missing {', '.join(missing)}")



def _parse_bool(explicit: Optional[bool], raw: Optional[str], *, default: bool) -> bool:
    if explicit is not None:
        return explicit
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
