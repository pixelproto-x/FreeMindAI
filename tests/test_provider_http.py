import httpx
import pytest

from freemind.config import ProviderConfig
from freemind.providers import ProviderManager


@pytest.mark.asyncio
async def test_openai_compatible_request_uses_expected_endpoint_and_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["payload"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hello from mock"}}]})

    config = ProviderConfig(
        name="custom", label="Custom", kind="openai", api_key="test-key",
        model="test-model", base_url="https://example.test/v1",
    )
    manager = ProviderManager([config])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await manager._request_openai_compatible(
            client, config, [{"role": "user", "content": "Hi"}]
        )

    assert result == "Hello from mock"
    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-key"
    assert seen["payload"]["model"] == "test-model"
    assert seen["payload"]["messages"][-1] == {"role": "user", "content": "Hi"}


@pytest.mark.asyncio
async def test_gemini_request_uses_native_endpoint_and_parses_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-goog-api-key")
        seen["payload"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "Hello"}, {"text": " Gemini"}]}}]
        })

    config = ProviderConfig(
        name="gemini", label="Gemini", kind="gemini", api_key="test-key",
        model="gemini-3.8-flash",
    )
    manager = ProviderManager([config])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await manager._request_gemini(
            client, config, [{"role": "user", "content": "Hi"}]
        )

    assert result == "Hello Gemini"
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    assert seen["api_key"] == "test-key"
    assert seen["payload"]["contents"] == [{"role": "user", "parts": [{"text": "Hi"}]}]
