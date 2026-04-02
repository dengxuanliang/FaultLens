from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional
from urllib import error, request

from faultlens.config import Settings
from faultlens.llm.adaptive_parser import parse_attribution_response


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_warning: Optional[str] = None
        self.last_completion_info: Dict[str, Any] = {"status": "idle"}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.api_key and self.settings.base_url and self.settings.model)

    def complete_json(self, messages: list[dict[str, str]]) -> Optional[Dict[str, Any]]:
        self.last_warning = None
        self.last_completion_info = {"status": "disabled", "raw_response_excerpt": None, "raw_response_text": None, "raw_response_sha256": None}
        if not self.enabled:
            return None

        payload = json.dumps(
            {
                "model": self.settings.model,
                "messages": messages,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        req = request.Request(
            self.settings.base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.api_key}",
            },
            method="POST",
        )
        attempts = self.settings.llm_max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                with request.urlopen(req, timeout=self.settings.request_timeout) as resp:  # noqa: S310
                    body = json.loads(resp.read().decode("utf-8"))
                content = _normalize_content(body.get("choices", [{}])[0].get("message", {}).get("content"))
                excerpt = _excerpt(content)
                parsed = parse_attribution_response(content)
                self.last_completion_info = {
                    "status": parsed.status,
                    "invalid_reason": parsed.invalid_reason,
                    "raw_response_excerpt": excerpt,
                    "raw_response_text": content,
                    "raw_response_sha256": _sha256_text(content),
                }
                if parsed.status == "strict_json":
                    return parsed.payload
                if parsed.status in {"adaptive_parse", "salvaged"}:
                    self.last_warning = f"llm response adapted: {parsed.invalid_reason}"
                    return parsed.payload
                self.last_warning = f"llm invalid response format: {parsed.invalid_reason}"
                return None
            except error.HTTPError as exc:
                if self._should_retry_http_error(exc) and attempt < attempts:
                    delay = _retry_delay_seconds(exc.headers, self.settings.llm_retry_backoff_seconds, attempt)
                    self.last_warning = f"llm retry {attempt}/{self.settings.llm_max_retries} after HTTP {exc.code}, sleeping {delay}s"
                    time.sleep(delay)
                    continue
                error_body = _read_http_error_body(exc)
                self.last_warning = f"llm unavailable: {exc}"
                self.last_completion_info = {
                    "status": "request_error",
                    "error_type": type(exc).__name__,
                    "invalid_reason": f"HTTPError {exc.code}: {exc.reason}",
                    "http_status": exc.code,
                    "raw_response_excerpt": _excerpt(error_body) if error_body else None,
                    "raw_response_text": error_body,
                    "raw_response_sha256": _sha256_text(error_body),
                }
                return None
            except (error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
                self.last_warning = f"llm unavailable: {exc}"
                self.last_completion_info = {
                    "status": "request_error",
                    "error_type": type(exc).__name__,
                    "raw_response_excerpt": None,
                    "raw_response_text": None,
                    "raw_response_sha256": None,
                }
                return None
        return None

    def _should_retry_http_error(self, exc: error.HTTPError) -> bool:
        if exc.code == 429:
            return True
        return self.settings.llm_retry_on_5xx and 500 <= exc.code < 600



def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return ""



def _excerpt(content: str, limit: int = 240) -> str:
    stripped = (content or "").strip()
    return stripped[:limit]


def _sha256_text(content: str) -> Optional[str]:
    stripped = (content or "").strip()
    if not stripped:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _retry_delay_seconds(headers: Any, base_seconds: int, attempt: int) -> float:
    if headers:
        retry_after = headers.get("Retry-After")
        try:
            if retry_after is not None:
                return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return float(base_seconds * (2 ** (attempt - 1)))


def _read_http_error_body(exc: error.HTTPError) -> str:
    try:
        payload = exc.read()
    except OSError:
        return ""
    if not payload:
        return ""
    try:
        return payload.decode("utf-8", errors="replace")
    except AttributeError:
        return str(payload)
