from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib import error, request

from faultlens.config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.last_warning: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.api_key and self.settings.base_url and self.settings.model)

    def complete_json(self, messages: list[dict[str, str]]) -> Optional[Dict[str, Any]]:
        self.last_warning = None
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
            content = body.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                return None
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            return json.loads(content)
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
            self.last_warning = f"llm unavailable: {exc}"
            return None
