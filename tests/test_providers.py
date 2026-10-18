from freemind.config import ProviderConfig
from freemind.providers import AllProvidersFailed, ProviderManager, ProviderFailure, ProviderError, _safe_provider_error
import httpx
import pytest


def test_provider_status_never_contains_api_key():
    cfg = ProviderConfig(name="fake", label="Fake", kind="openai", api_key="do-not-expose", model="test-model", base_url="https://example.invalid/v1")
    manager = ProviderManager([cfg])
    status = manager.status()
    assert status[0]["name"] == "fake"
    assert "api_key" not in status[0]
    assert "do-not-expose" not in repr(status)


def test_429_daily_quota_uses_longer_cooldown(monkeypatch):
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.invalid"),
                              text='{"error":{"message":"daily quota exceeded"}}')
    error = _safe_provider_error(response, ProviderConfig("gemini", "Gemini", "gemini", "secret", "model"))
    assert error.status_code == 429
    assert error.cooldown_seconds >= 60
    assert "額度" in error.reason


@pytest.mark.asyncio
async def test_generate_with_no_providers_fails_cleanly():
    manager = ProviderManager([])
    with pytest.raises(AllProvidersFailed) as captured:
        await manager.generate([{"role": "user", "content": "hello"}])
    assert captured.value.failures == []


def test_failure_repr_does_not_contain_secret():
    failure = ProviderFailure("fake", "API 金鑰無效", status_code=401)
    assert "secret" not in repr(failure)


@pytest.mark.asyncio
async def test_router_falls_back_after_provider_failure(monkeypatch):
    first = ProviderConfig("first", "First", "openai", "secret1", "model1", "https://first.invalid/v1")
    second = ProviderConfig("second", "Second", "openai", "secret2", "model2", "https://second.invalid/v1")
    manager = ProviderManager([first, second])
    calls = []

    async def fake_request(cfg, history):
        calls.append(cfg.name)
        if cfg.name == "first":
            raise ProviderError("rate limited", status_code=429, cooldown_seconds=30)
        return "fallback is available"

    monkeypatch.setattr(manager, "_request", fake_request)
    result = await manager.generate([{"role": "user", "content": "hi"}])
    assert result.content == "fallback is available"
    assert result.provider == "second"
    assert result.fallback_used is True
    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_router_reports_fallback_when_primary_is_already_cooling(monkeypatch):
    import time
    first = ProviderConfig("primary", "Primary", "openai", "secret1", "model1", "https://primary.invalid/v1")
    second = ProviderConfig("backup", "Backup", "openai", "secret2", "model2", "https://backup.invalid/v1")
    manager = ProviderManager([first, second])
    manager.cooldowns["primary"] = time.monotonic() + 120

    async def fake_request(cfg, history):
        assert cfg.name == "backup"
        return "backup response"

    monkeypatch.setattr(manager, "_request", fake_request)
    result = await manager.generate([{"role": "user", "content": "hi"}])
    assert result.fallback_used is True
