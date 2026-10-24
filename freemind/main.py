from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# Load local .env before reading settings. Environment variables always take precedence.
load_dotenv()

from .config import env_int, get_app_password, get_provider_configs  # noqa: E402
from .providers import AllProvidersFailed, ProviderManager  # noqa: E402
from .storage import ChatStore, init_db  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("freemind")
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


class CreateConversationRequest(BaseModel):
    title: str = Field(default="新對話", max_length=120)


class ChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36)
    message: str = Field(min_length=1, max_length=12000)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("訊息不能是空白")
        return value



class MediaAttachment(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    mime_type: str = Field(min_length=3, max_length=100)
    data: str = Field(min_length=1, max_length=21_000_000)


class MediaChatRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=36)
    message: str = Field(default="請分析我附上的檔案。", max_length=12000)
    attachments: list[MediaAttachment] = Field(min_length=1, max_length=5)

    @field_validator("message")
    @classmethod
    def strip_media_message(cls, value: str) -> str:
        return value.strip() or "請分析我附上的檔案。"


ALLOWED_MEDIA_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/ogg",
    "audio/webm", "audio/aac", "audio/flac",
    "video/mp4", "video/mpeg", "video/quicktime", "video/webm",
    "application/pdf", "text/plain", "text/markdown", "text/csv",
}
MAX_MEDIA_FILE_BYTES = 15 * 1024 * 1024
MAX_MEDIA_TOTAL_BYTES = 20 * 1024 * 1024


class ConversationLockPool:
    """Serialize writes per conversation without retaining unused locks forever."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, key: str):
        async with self._guard:
            entry = self._locks.get(key)
            if entry is None:
                lock, users = asyncio.Lock(), 0
            else:
                lock, users = entry
            self._locks[key] = (lock, users + 1)
        acquired = False
        try:
            await lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                lock.release()
            async with self._guard:
                current_lock, users = self._locks.get(key, (lock, 1))
                if current_lock is lock and users <= 1 and not lock.locked():
                    self._locks.pop(key, None)
                else:
                    self._locks[key] = (current_lock, max(0, users - 1))


def create_app(store: ChatStore | None = None, provider_manager: ProviderManager | None = None) -> FastAPI:
    chat_store = store or ChatStore()
    manager = provider_manager or ProviderManager(get_provider_configs())

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        if environment in {"production", "prod"} and not get_app_password():
            raise RuntimeError("在正式環境公開部署前，必須設定 APP_PASSWORD。")
        init_db()
        if not manager.configs:
            logger.warning("No AI provider configured. Copy .env.example to .env and configure at least one provider.")
        yield

    app = FastAPI(title="FreeMind AI", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store = chat_store
    app.state.provider_manager = manager
    app.state.conversation_locks = ConversationLockPool()

    @app.middleware("http")
    async def security_and_auth(request: Request, call_next):
        path = request.url.path
        app_password = get_app_password()
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        client_host = request.client.host if request.client else ""
        is_local_development = environment not in {"production", "prod"} and client_host in {"127.0.0.1", "::1", "localhost"}
        if path.startswith("/api/") and path != "/api/health" and app_password and not is_local_development:
            auth = request.headers.get("authorization", "")
            expected = "Bearer " + app_password
            if not secrets.compare_digest(auth.encode("utf-8"), expected.encode("utf-8")):
                return JSONResponse(status_code=401, content={"error": "需要應用程式存取密碼。"}, headers={"WWW-Authenticate": "Bearer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
        if path.startswith("/api/") and len(request.url.query) > 2000:
            return JSONResponse(status_code=414, content={"error": "查詢參數過長。"}, headers={"X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "app": "FreeMind AI", "version": "0.1.0"}

    @app.get("/api/providers")
    def providers(request: Request) -> dict[str, Any]:
        current: ProviderManager = request.app.state.provider_manager
        return {"providers": current.status(), "configured_count": len(current.configs)}

    @app.get("/api/conversations")
    def list_conversations(request: Request) -> dict[str, Any]:
        current_store: ChatStore = request.app.state.store
        return {"conversations": current_store.list_conversations()}

    @app.post("/api/conversations")
    def create_conversation(payload: CreateConversationRequest, request: Request) -> dict[str, Any]:
        current_store: ChatStore = request.app.state.store
        return {"conversation": current_store.create_conversation(payload.title.strip() or "新對話")}

    @app.get("/api/conversations/{conversation_id}/messages")
    def get_messages(conversation_id: str, request: Request) -> dict[str, Any]:
        current_store: ChatStore = request.app.state.store
        if not current_store.get_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="找不到這段對話。")
        return {"messages": current_store.get_messages(conversation_id)}

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, request: Request) -> Response:
        current_store: ChatStore = request.app.state.store
        async with request.app.state.conversation_locks.hold(conversation_id):
            if not current_store.delete_conversation(conversation_id):
                raise HTTPException(status_code=404, detail="找不到這段對話。")
        return Response(status_code=204)

    @app.post("/api/chat")
    async def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
        current_store: ChatStore = request.app.state.store
        current_manager: ProviderManager = request.app.state.provider_manager
        async with request.app.state.conversation_locks.hold(payload.conversation_id):
            conversation = current_store.get_conversation(payload.conversation_id)
            if not conversation:
                raise HTTPException(status_code=404, detail="找不到這段對話，請重新開啟或建立新對話。")

            # Build context from stored messages plus this user turn. Persist the turn only on success.
            prior = current_store.get_messages(payload.conversation_id)
            max_context = env_int("MAX_CONTEXT_MESSAGES", 24, 4, 100)
            max_context -= max_context % 2  # Preserve complete user/assistant pairs.
            history = [{"role": m["role"], "content": m["content"]} for m in prior if m["role"] in ("user", "assistant")]
            history = history[-max_context:]
            history.append({"role": "user", "content": payload.message})
            try:
                result = await current_manager.generate(history)
            except AllProvidersFailed as exc:
                logger.warning("All providers failed; conversation_id=%s configured=%s", payload.conversation_id, len(current_manager.configs))
                return JSONResponse(status_code=503, content={
                    "error": "目前沒有可用的 AI 服務。這則訊息尚未存入對話紀錄；請檢查服務額度、API 設定，或稍後再試。",
                    "retry_after_seconds": exc.retry_after_seconds,
                    "configured_provider_count": len(current_manager.configs),
                    "failures": [{"provider": x.provider, "reason": x.reason, "status_code": x.status_code,
                                  "cooldown_seconds": x.cooldown_seconds} for x in exc.failures],
                })
            try:
                current_store.append_turn(payload.conversation_id, payload.message, result.content, result.provider, result.model)
            except KeyError:
                raise HTTPException(status_code=404, detail="對話已被刪除，請建立新對話。")
            logger.info("chat_complete provider=%s model=%s fallback=%s", result.provider, result.model, result.fallback_used)
            return {"conversation_id": payload.conversation_id, "content": result.content, "provider": result.provider,
                    "model": result.model, "fallback_used": result.fallback_used}


    @app.post("/api/chat/media")
    async def chat_media(payload: MediaChatRequest, request: Request) -> Any:
        current_store: ChatStore = request.app.state.store
        current_manager: ProviderManager = request.app.state.provider_manager
        decoded_attachments: list[dict[str, str]] = []
        total_bytes = 0
        for item in payload.attachments:
            mime_type = item.mime_type.lower().split(";", 1)[0].strip()
            if mime_type not in ALLOWED_MEDIA_TYPES:
                raise HTTPException(status_code=415, detail=f"不支援的檔案格式：{item.filename}（{mime_type}）")
            try:
                raw = base64.b64decode(item.data, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(status_code=400, detail=f"檔案資料無效：{item.filename}")
            if not raw:
                raise HTTPException(status_code=400, detail=f"檔案是空的：{item.filename}")
            if len(raw) > MAX_MEDIA_FILE_BYTES:
                raise HTTPException(status_code=413, detail=f"單一檔案不可超過 15 MB：{item.filename}")
            total_bytes += len(raw)
            if total_bytes > MAX_MEDIA_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="所有附件合計不可超過 20 MB。")
            decoded_attachments.append({"filename": item.filename, "mime_type": mime_type, "data": base64.b64encode(raw).decode("ascii")})

        filenames = "、".join(item["filename"] for item in decoded_attachments)
        user_message = f"{payload.message.strip() or '請分析我附上的檔案。'}\n\n附件：{filenames}"
        async with request.app.state.conversation_locks.hold(payload.conversation_id):
            conversation = current_store.get_conversation(payload.conversation_id)
            if not conversation:
                raise HTTPException(status_code=404, detail="找不到這段對話，請重新開啟或建立新對話。")
            prior = current_store.get_messages(payload.conversation_id)
            max_context = env_int("MAX_CONTEXT_MESSAGES", 24, 4, 100)
            max_context -= max_context % 2
            history = [{"role": m["role"], "content": m["content"]} for m in prior if m["role"] in ("user", "assistant")]
            history = history[-max_context:]
            history.append({"role": "user", "content": user_message})
            try:
                result = await current_manager.generate_with_media(history, decoded_attachments)
            except AllProvidersFailed as exc:
                logger.warning("Media analysis unavailable; conversation_id=%s", payload.conversation_id)
                return JSONResponse(status_code=503, content={
                    "error": "目前沒有可用的多模態 AI。請確認 .env 已設定可用的 GEMINI_API_KEY，且 PROVIDER_ORDER 包含 gemini；附件尚未存入對話紀錄。",
                    "retry_after_seconds": exc.retry_after_seconds,
                    "failures": [{"provider": x.provider, "reason": x.reason, "status_code": x.status_code,
                                  "cooldown_seconds": x.cooldown_seconds} for x in exc.failures],
                })
            try:
                current_store.append_turn(payload.conversation_id, user_message, result.content, result.provider, result.model)
            except KeyError:
                raise HTTPException(status_code=404, detail="對話已被刪除，請建立新對話。")
            logger.info("media_analysis_complete provider=%s model=%s files=%s", result.provider, result.model, len(decoded_attachments))
            return {"conversation_id": payload.conversation_id, "content": result.content, "provider": result.provider,
                    "model": result.model, "fallback_used": result.fallback_used, "attachments": [x["filename"] for x in decoded_attachments]}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
