from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from freemind.main import ConversationLockPool, create_app
from freemind.providers import ChatResult, ProviderManager
from freemind.storage import Base, ChatStore


class FakeProviderManager(ProviderManager):
    def __init__(self):
        super().__init__([])
        self.configs = []

    async def generate(self, history):
        assert history[-1]["role"] == "user"
        return ChatResult("你好，這是測試回覆。", "fake", "fake-model", False)


def test_health_and_chat_round_trip(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    # Keep the app isolated from the default project database.
    monkeypatch.setattr(storage, "SessionLocal", TestSession)
    store = ChatStore()
    manager = FakeProviderManager()
    app = create_app(store=store, provider_manager=manager)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        created = client.post("/api/conversations", json={"title": "新對話"})
        assert created.status_code == 200
        conversation_id = created.json()["conversation"]["id"]
        response = client.post("/api/chat", json={"conversation_id": conversation_id, "message": "你好"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["content"] == "你好，這是測試回覆。"
        messages = client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"]
        assert [item["role"] for item in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "你好"
        deleted = client.delete(f"/api/conversations/{conversation_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/conversations/{conversation_id}/messages").status_code == 404


def test_no_provider_failure_does_not_save_half_turn(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'no-provider.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    store = ChatStore()
    app = create_app(store=store, provider_manager=ProviderManager([]))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["conversation"]["id"]
        response = client.post("/api/chat", json={"conversation_id": conversation_id, "message": "Test prompt"})
        assert response.status_code == 503
        assert response.json()["configured_provider_count"] == 0
        assert client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"] == []


def test_password_protects_api_routes(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setenv("APP_PASSWORD", "local-test-password")
    app = create_app(store=ChatStore(), provider_manager=ProviderManager([]))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/conversations").status_code == 401
        response = client.get("/api/conversations", headers={"Authorization": "Bearer local-test-password"})
        assert response.status_code == 200


def test_remote_api_fails_closed_when_password_is_unset(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'no-password-remote.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    app = create_app(store=ChatStore(), provider_manager=ProviderManager([]))
    with TestClient(app, client=("192.0.2.20", 12345)) as client:
        assert client.get("/api/health").status_code == 200
        response = client.get("/api/providers")
        assert response.status_code == 503
        assert "APP_PASSWORD" in response.json()["error"]


def test_app_password_preserves_leading_and_trailing_whitespace(tmp_path, monkeypatch):
    import base64
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'whitespace-password.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setenv("ENVIRONMENT", "production")
    password = "  exact password  "
    monkeypatch.setenv("APP_PASSWORD", password)
    app = create_app(store=ChatStore(), provider_manager=ProviderManager([]))
    token = base64.b64encode(password.encode("utf-8")).decode("ascii")
    with TestClient(app, client=("192.0.2.21", 12345)) as client:
        response = client.get("/api/providers", headers={"Authorization": f"Bearer-UTF8 {token}"})
        assert response.status_code == 200


def test_localhost_development_does_not_require_app_password(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'local-auth.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("APP_PASSWORD", "local-test-password")
    app = create_app(store=ChatStore(), provider_manager=ProviderManager([]))
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        assert client.get("/api/providers").status_code == 200
        assert client.get("/api/conversations").status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "no-store" in page.headers.get("cache-control", "")
        assert "/static/app.js?v=auth-utf8-20261024" in page.text
        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert "no-store" in script.headers.get("cache-control", "")


def test_non_ascii_app_password_is_supported(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'unicode-auth.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_PASSWORD", "測試密碼123")
    app = create_app(store=ChatStore(), provider_manager=ProviderManager([]))
    with TestClient(app, client=("192.0.2.10", 12345)) as client:
        assert client.get("/api/providers").status_code == 401
        response = client.get("/api/providers", headers={"Authorization": "Bearer-UTF8 5ris6Kmm5a+G56K8MTIz"})
        assert response.status_code == 200


def test_unicode_auth_rejects_bad_and_malformed_tokens_without_500(tmp_path, monkeypatch):
    import base64
    import freemind.storage as storage

    engine = create_engine(f"sqlite:///{tmp_path / 'unicode-auth-invalid.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setenv("ENVIRONMENT", "production")
    password = "繁體中文密碼🔐"
    monkeypatch.setenv("APP_PASSWORD", password)
    app = create_app(store=ChatStore(), provider_manager=ProviderManager([]))

    with TestClient(app, client=("192.0.2.11", 12345)) as client:
        endpoint = "/api/providers"
        assert client.get(endpoint).status_code == 401
        assert client.get(endpoint, headers={"Authorization": "Bearer-UTF8 !!!"}).status_code == 401
        wrong = base64.b64encode("錯誤密碼".encode("utf-8")).decode("ascii")
        assert client.get(endpoint, headers={"Authorization": f"Bearer-UTF8 {wrong}"}).status_code == 401
        correct = base64.b64encode(password.encode("utf-8")).decode("ascii")
        response = client.get(endpoint, headers={"Authorization": f"Bearer-UTF8 {correct}"})
        assert response.status_code == 200
        assert response.json()["configured_count"] == 0


def test_provider_order_can_disable_a_configured_provider(monkeypatch):
    from freemind.config import get_provider_configs
    monkeypatch.setenv("PROVIDER_ORDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    configured = get_provider_configs()
    assert [provider.name for provider in configured] == ["groq"]


import asyncio


def test_conversation_lock_pool_serializes_writes():
    async def scenario():
        pool = ConversationLockPool()
        events = []

        async def worker(name):
            async with pool.hold("one-conversation"):
                events.append(f"start:{name}")
                await asyncio.sleep(0.01)
                events.append(f"end:{name}")

        await asyncio.gather(worker("A"), worker("B"))
        assert events in (["start:A", "end:A", "start:B", "end:B"],
                          ["start:B", "end:B", "start:A", "end:A"])
        assert pool._locks == {}

    asyncio.run(scenario())



def test_media_endpoint_rejects_unsupported_file_type(tmp_path, monkeypatch):
    import freemind.storage as storage
    engine = create_engine(f"sqlite:///{tmp_path / 'media.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    monkeypatch.setattr(storage, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    store = ChatStore()
    app = create_app(store=store, provider_manager=FakeProviderManager())
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["conversation"]["id"]
        response = client.post("/api/chat/media", json={
            "conversation_id": conversation_id,
            "message": "請分析",
            "attachments": [{"filename": "unknown.bin", "mime_type": "application/octet-stream", "data": "dGVzdA=="}],
        })
        assert response.status_code == 415
        assert "不支援的檔案格式" in response.json()["detail"]
        assert client.get(f"/api/conversations/{conversation_id}/messages").json()["messages"] == []
