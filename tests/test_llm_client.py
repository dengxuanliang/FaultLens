import json
from pathlib import Path
from urllib import error

from faultlens.config import Settings
from faultlens.llm.client import LLMClient
from faultlens.llm.prompting import build_attribution_messages


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")
        self.status = 200
        self.headers = {"Content-Type": "application/json"}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeHTTPError(error.HTTPError):
    def __init__(self, url: str, code: int, msg: str, headers: dict | None = None, body: str = ""):
        super().__init__(url, code, msg, headers or {}, None)
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body



def _settings() -> Settings:
    return Settings(
        api_key="k",
        base_url="http://example.test/v1/chat/completions",
        model="gpt-5.4",
        output_dir=Path("outputs"),
        request_timeout=5,
        execution_timeout=5,
        llm_max_retries=2,
        llm_retry_backoff_seconds=2,
        llm_retry_on_5xx=True,
    )



def test_build_attribution_messages_serializes_json_payload():
    messages = build_attribution_messages(
        {
            "task": {"content_text": "Multiply x by 2"},
            "reference": {"canonical_code_text": "def solve(x): return x * 2"},
            "completion": {"raw_text": "```python\ndef solve(x): return x + 2\n```"},
            "evaluation": {"accepted": False, "pass_metrics": {"passed_at_1": 0}},
            "deterministic_findings": {"test_status": "failed"},
            "deterministic_signals": ["test_failure"],
        }
    )

    payload = json.loads(messages[1]["content"])
    system_prompt = messages[0]["content"]

    assert payload["task"]["content_text"] == "Multiply x by 2"
    assert payload["deterministic_findings"]["test_status"] == "failed"
    assert "must contain exactly these fields" in system_prompt
    assert "failure_stage" in system_prompt
    assert "deterministic_alignment" in system_prompt
    assert "needs_human_review" in system_prompt
    assert "Return valid JSON only." in system_prompt



def test_complete_json_parses_fenced_json_response(monkeypatch):
    def fake_urlopen(req, timeout):
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": """```json
{"root_cause":"solution_incorrect","explanation":"logic mismatch","observable_evidence":["assert failed"],"improvement_hints":["compare against reference"],"llm_signals":["structured_output"]}
```"""
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result["root_cause"] == "solution_incorrect"
    assert client.last_completion_info["status"] == "adaptive_parse"
    assert client.last_completion_info["raw_response_excerpt"]
    assert "logic mismatch" in client.last_completion_info["raw_response_text"]



def test_complete_json_records_invalid_non_json_response_without_raising(monkeypatch):
    def fake_urlopen(req, timeout):
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": """???: ???
<not useful>
"""
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result is None
    assert client.last_completion_info["status"] == "invalid"
    assert client.last_completion_info["invalid_reason"] == "non_json_content"
    assert "invalid response format" in client.last_warning



def test_complete_json_adapts_english_prose_response(monkeypatch):
    def fake_urlopen(req, timeout):
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": """Root Cause: solution incorrect
Explanation: The task asks for doubling x, but the implementation adds 2.
Evidence:
- solve(7) returned 9
Improvement Hints:
- Use multiplication instead of addition
"""
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result["root_cause"] == "solution_incorrect"
    assert result["observable_evidence"] == ["solve(7) returned 9"]
    assert client.last_completion_info["status"] == "adaptive_parse"



def test_complete_json_salvages_code_only_response(monkeypatch):
    def fake_urlopen(req, timeout):
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": """```cpp
int solve(int x) {
    return x - 1;
}
```"""
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert "code_only_response" in result["llm_signals"]
    assert client.last_completion_info["status"] == "salvaged"
    assert client.last_completion_info["invalid_reason"] == "code_only_response"
    assert "int solve" in client.last_completion_info["raw_response_excerpt"]
    assert "return x - 1;" in client.last_completion_info["raw_response_text"]


def test_complete_json_retries_http_429_and_then_succeeds(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def fake_urlopen(req, timeout):
        calls["count"] += 1
        if calls["count"] < 3:
            raise error.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "1"},
                None,
            )
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"root_cause":"solution_incorrect","secondary_cause":null,"failure_stage":"implementation","summary":"Wrong logic.","explanation":"logic mismatch","observable_evidence":["assert failed"],"evidence_refs":["deterministic_findings.test_status"],"deterministic_alignment":"consistent","confidence":0.9,"needs_human_review":false,"review_reason":null,"improvement_hints":["check math"]}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)
    monkeypatch.setattr("faultlens.llm.client.time.sleep", fake_sleep)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result["root_cause"] == "solution_incorrect"
    assert calls["count"] == 3
    assert sleeps == [1.0, 1.0]
    assert client.last_completion_info["status"] == "strict_json"


def test_complete_json_uses_exponential_backoff_when_retry_after_missing(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def fake_urlopen(req, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"root_cause":"implementation_bug","secondary_cause":null,"failure_stage":"implementation","summary":"Syntax error.","explanation":"syntax issue","observable_evidence":["invalid syntax"],"evidence_refs":["deterministic_findings.parse_status"],"deterministic_alignment":"consistent","confidence":0.8,"needs_human_review":false,"review_reason":null,"improvement_hints":["fix syntax"]}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)
    monkeypatch.setattr("faultlens.llm.client.time.sleep", fake_sleep)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result["root_cause"] == "implementation_bug"
    assert sleeps == [2.0]


def test_complete_json_does_not_retry_http_400(monkeypatch):
    calls = {"count": 0}
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def fake_urlopen(req, timeout):
        calls["count"] += 1
        raise error.HTTPError(req.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)
    monkeypatch.setattr("faultlens.llm.client.time.sleep", fake_sleep)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result is None
    assert calls["count"] == 1
    assert sleeps == []
    assert client.last_completion_info["status"] == "request_error"


def test_complete_json_records_http_error_details_and_body(monkeypatch):
    def fake_urlopen(req, timeout):
        raise _FakeHTTPError(
            req.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            '{"error":{"message":"rate limit exceeded","type":"rate_limit"}}',
        )

    monkeypatch.setattr("faultlens.llm.client.request.urlopen", fake_urlopen)

    client = LLMClient(_settings())
    result = client.complete_json([{"role": "user", "content": "{}"}])

    assert result is None
    assert client.last_completion_info["status"] == "request_error"
    assert client.last_completion_info["invalid_reason"] == "HTTPError 429: Too Many Requests"
    assert client.last_completion_info["raw_response_text"] == '{"error":{"message":"rate limit exceeded","type":"rate_limit"}}'
    assert client.last_completion_info["raw_response_excerpt"] == '{"error":{"message":"rate limit exceeded","type":"rate_limit"}}'
    assert client.last_completion_info["http_status"] == 429
