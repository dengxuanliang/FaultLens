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
    enable_checkpoints: bool = True



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
    enable_checkpoints: Optional[bool] = None,
) -> Settings:
    env_values = merge_env(load_dotenv(env_path))
    return Settings(
        api_key=api_key or env_values.get("FAULTLENS_API_KEY"),
        base_url=base_url or env_values.get("FAULTLENS_BASE_URL"),
        model=model or env_values.get("FAULTLENS_MODEL"),
        output_dir=Path(output_dir or env_values.get("FAULTLENS_OUTPUT_DIR", "outputs")),
        request_timeout=int(request_timeout or env_values.get("FAULTLENS_REQUEST_TIMEOUT", 60)),
        execution_timeout=int(execution_timeout or env_values.get("FAULTLENS_EXECUTION_TIMEOUT", 10)),
        llm_max_workers=max(1, int(llm_max_workers or env_values.get("FAULTLENS_LLM_MAX_WORKERS", 4))),
        llm_max_retries=max(0, int(llm_max_retries or env_values.get("FAULTLENS_LLM_MAX_RETRIES", 2))),
        llm_retry_backoff_seconds=max(1, int(llm_retry_backoff_seconds or env_values.get("FAULTLENS_LLM_RETRY_BACKOFF_SECONDS", 2))),
        llm_retry_on_5xx=_parse_bool(llm_retry_on_5xx, env_values.get("FAULTLENS_LLM_RETRY_ON_5XX"), default=True),
        resume=_parse_bool(resume, env_values.get("FAULTLENS_RESUME"), default=False),
        enable_checkpoints=_parse_bool(enable_checkpoints, env_values.get("FAULTLENS_ENABLE_CHECKPOINTS"), default=True),
    )



def _parse_bool(explicit: Optional[bool], raw: Optional[str], *, default: bool) -> bool:
    if explicit is not None:
        return explicit
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
