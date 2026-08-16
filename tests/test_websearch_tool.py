from types import SimpleNamespace

from xiaomei_brain.tools.builtin import websearch
from xiaomei_brain.tools.provider.websearch import SearchResult


class _Registry:
    def __init__(self, provider):
        self.provider = provider

    def get_web_search_providers(self):
        return [self.provider]


class _Provider:
    provider_id = "test"
    priority = 0

    def __init__(self, result=None, error=None):
        self.result = result or []
        self.error = error

    def is_available(self):
        return True

    def search(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return self.result


def test_web_search_returns_structured_real_results():
    provider = _Provider([
        SearchResult(title="Example", url="https://example.com", time="2026-08-16"),
    ])
    websearch.set_registry(_Registry(provider))

    result = websearch.web_search.execute(query="example")

    assert result == {
        "success": True,
        "provider": "test",
        "query": "example",
        "count": 1,
        "results": [{
            "title": "Example",
            "url": "https://example.com",
            "time": "2026-08-16",
        }],
    }


def test_web_search_preserves_http_failure_details():
    error = RuntimeError("429 Client Error: Too Many Requests")
    error.response = SimpleNamespace(
        status_code=429,
        text='{"error":"quota exceeded"}',
        headers={"Retry-After": "60"},
    )
    websearch.set_registry(_Registry(_Provider(error=error)))

    result = websearch.web_search.execute(query="example")

    assert result["success"] is False
    assert result["provider"] == "test"
    assert result["query"] == "example"
    assert result["error"] == {
        "type": "rate_limited",
        "message": "429 Client Error: Too Many Requests",
        "retryable": True,
        "http_status": 429,
        "response": '{"error":"quota exceeded"}',
        "retry_after": "60",
    }
