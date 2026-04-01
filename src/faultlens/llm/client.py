from __future__ import annotations

import json
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
        self.last_completion_info = {"status": "disabled"}
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
        try:
            with request.urlopen(req, timeout=self.settings.request_timeout) as resp:  # noqa: S310
                body = json.loads(resp.read().decode("utf-8"))
            content = _normalize_content(body.get("choices", [{}])[0].get("message", {}).get("content"))
            parsed = parse_attribution_response(content)
            self.last_completion_info = {
                "status": parsed.status,
                "invalid_reason": parsed.invalid_reason,
            }
            if parsed.status == "strict_json":
                return parsed.payload
            if parsed.status in {"adaptive_parse", "salvaged"}:
                self.last_warning = f"llm response adapted: {parsed.invalid_reason}"
                return parsed.payload
            self.last_warning = f"llm invalid response format: {parsed.invalid_reason}"
            return None
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
            self.last_warning = f"llm unavailable: {exc}"
            self.last_completion_info = {"status": "request_error", "error_type": type(exc).__name__}
            return None



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
