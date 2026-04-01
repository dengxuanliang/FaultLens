import json
from pathlib import Path

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



def _settings() -> Settings:
    return Settings(
        api_key="k",
        base_url="http://example.test/v1/chat/completions",
        model="gpt-5.4",
        output_dir=Path("outputs"),
        request_timeout=5,
        execution_timeout=5,
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

    assert payload["task"]["content_text"] == "Multiply x by 2"
    assert payload["deterministic_findings"]["test_status"] == "failed"



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
