from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .config import ProviderConfig, env_int

SYSTEM_PROMPT = """你是 FreeMind AI，一位可靠、自然、坦誠的繁體中文 AI 助手。
請直接回答問題，理解多輪對話脈絡；不確定的事要清楚說明，不要捏造來源或宣稱做過沒有做的事。
使用者以其他語言提問時，使用者沒有指定語言就跟隨對方的語言。程式碼要完整、可執行，並注意安全性。
"""


@dataclass
class ChatResult:
    content: str
    provider: str
    model: str
    fallback_used: bool


@dataclass
class ProviderFailure:
    provider: str
    reason: str
    status_code: int | None = None
    cooldown_seconds: int = 0


class ProviderError(Exception):
    def __init__(self, reason: str, *, status_code: int | None = None, retryable: bool = False,
                 cooldown_seconds: int = 0, retry_after: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code
        self.retryable = retryable
        self.cooldown_seconds = cooldown_seconds
        self.retry_after = retry_after


class AllProvidersFailed(Exception):
    def __init__(self, failures: list[ProviderFailure], retry_after_seconds: int):
        super().__init__("all_providers_unavailable")
        self.failures = failures
        self.retry_after_seconds = retry_after_seconds


def _safe_provider_error(response: httpx.Response, config: ProviderConfig) -> ProviderError:
    status = response.status_code
    # Inspect the body only to classify quota errors. Never send provider response text back to the UI.
    try:
        body = response.text[:6000].lower()
    except Exception:
        body = ""
    if status == 429:
        is_daily = any(token in body for token in ("daily quota", "quota_exceeded", "requests per day", "per day limit", "resource_exhausted"))
        default_cooldown = env_int("DAILY_QUOTA_COOLDOWN_SECONDS", 21600, 60, 86400) if is_daily else env_int("RATE_LIMIT_COOLDOWN_SECONDS", 90, 15, 3600)
        retry_after = response.headers.get("Retry-After")
        try:
            retry_seconds = max(1, min(86400, int(retry_after))) if retry_after else None
        except ValueError:
            retry_seconds = None
        seconds = max(default_cooldown, retry_seconds or 0)
        reason = "每日或短時間額度限制（429），暫時跳過此服務" if is_daily else "請求過於頻繁或額度不足（429），暫時跳過此服務"
        return ProviderError(reason, status_code=status, cooldown_seconds=seconds, retry_after=retry_seconds)
    if status in (401, 403):
        return ProviderError("API 金鑰無效、權限不足或帳務設定有問題", status_code=status, cooldown_seconds=3600)
    if status == 404:
        return ProviderError("模型名稱或 API 路徑不存在（404）", status_code=status, cooldown_seconds=600)
    if status in (408, 425, 500, 502, 503, 504):
        return ProviderError(f"服務暫時無法使用（HTTP {status}）", status_code=status, retryable=True,
                             cooldown_seconds=env_int("PROVIDER_ERROR_COOLDOWN_SECONDS", 60, 15, 1800))
    if 400 <= status < 500:
        return ProviderError(f"請求被服務拒絕（HTTP {status}），請檢查模型名稱與參數", status_code=status,
                             cooldown_seconds=600)
    return ProviderError(f"服務回傳異常狀態（HTTP {status}）", status_code=status, retryable=True, cooldown_seconds=60)


class ProviderManager:
    """Small provider router with bounded retries, circuit breaking, and safe error messages."""

    def __init__(self, configs: list[ProviderConfig] | None = None):
        self.configs = configs if configs is not None else []
        self.cooldowns: dict[str, float] = {}
        self.last_status: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self.request_timeout = env_int("REQUEST_TIMEOUT_SECONDS", 45, 5, 180)
        self.max_output_tokens = env_int("MAX_OUTPUT_TOKENS", 1200, 128, 8192)

    def status(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        out = []
        for cfg in self.configs:
            remaining = max(0, int(self.cooldowns.get(cfg.name, 0) - now))
            last = self.last_status.get(cfg.name, {})
            out.append({"name": cfg.name, "label": cfg.label, "model": cfg.model,
                        "state": "cooldown" if remaining else "ready", "cooldown_seconds": remaining,
                        "last_error": last.get("last_error"), "last_success": last.get("last_success")})
        return out

    async def generate(self, history: list[dict[str, str]]) -> ChatResult:
        if not self.configs:
            raise AllProvidersFailed([], 0)
        failures: list[ProviderFailure] = []
        now = time.monotonic()
        ordered: list[ProviderConfig] = []
        for cfg in self.configs:
            if self.cooldowns.get(cfg.name, 0) > now:
                remaining = int(self.cooldowns[cfg.name] - now)
                failures.append(ProviderFailure(cfg.name, f"冷卻中，約 {remaining} 秒後重試", cooldown_seconds=remaining))
            else:
                ordered.append(cfg)
        if not ordered:
            shortest = min((x.cooldown_seconds for x in failures if x.cooldown_seconds), default=60)
            raise AllProvidersFailed(failures, shortest)

        for index, cfg in enumerate(ordered):
            attempts = 2
            for attempt in range(attempts):
                try:
                    answer = await self._request(cfg, history)
                    if not answer.strip():
                        raise ProviderError("服務回傳空白內容", retryable=True, cooldown_seconds=30)
                    self.cooldowns.pop(cfg.name, None)
                    self.last_status[cfg.name] = {"last_success": int(time.time()), "last_error": None}
                    return ChatResult(answer.strip(), cfg.name, cfg.model, fallback_used=(index > 0 or any(item.provider != cfg.name for item in failures)))
                except ProviderError as exc:
                    if exc.cooldown_seconds:
                        self.cooldowns[cfg.name] = time.monotonic() + exc.cooldown_seconds
                    self.last_status[cfg.name] = {"last_error": exc.reason}
                    if exc.retryable and attempt == 0:
                        await asyncio.sleep(0.35)
                        continue
                    failures.append(ProviderFailure(cfg.name, exc.reason, exc.status_code, exc.cooldown_seconds))
                    break
                except (httpx.TimeoutException, httpx.NetworkError):
                    reason = "連線逾時或網路中斷"
                    cool = env_int("PROVIDER_ERROR_COOLDOWN_SECONDS", 60, 15, 1800)
                    self.cooldowns[cfg.name] = time.monotonic() + cool
                    self.last_status[cfg.name] = {"last_error": reason}
                    if attempt == 0:
                        await asyncio.sleep(0.35)
                        continue
                    failures.append(ProviderFailure(cfg.name, reason, cooldown_seconds=cool))
                    break
                except Exception:
                    reason = "服務回應格式異常或發生未預期錯誤"
                    self.last_status[cfg.name] = {"last_error": reason}
                    failures.append(ProviderFailure(cfg.name, reason, cooldown_seconds=30))
                    self.cooldowns[cfg.name] = time.monotonic() + 30
                    break
        retry_values = [x.cooldown_seconds for x in failures if x.cooldown_seconds > 0]
        raise AllProvidersFailed(failures, min(retry_values) if retry_values else 60)

    async def _request(self, cfg: ProviderConfig, history: list[dict[str, str]]) -> str:
        timeout = httpx.Timeout(connect=10.0, read=float(self.request_timeout), write=15.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if cfg.kind == "gemini":
                return await self._request_gemini(client, cfg, history)
            return await self._request_openai_compatible(client, cfg, history)

    async def _request_openai_compatible(self, client: httpx.AsyncClient, cfg: ProviderConfig,
                                         history: list[dict[str, str]]) -> str:
        base = cfg.base_url.rstrip("/")
        url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
        if cfg.name == "openrouter":
            headers["X-Title"] = "FreeMind AI"
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
            {"role": item["role"], "content": item["content"]} for item in history
            if item.get("role") in ("user", "assistant")
        ]
        payload = {"model": cfg.model, "messages": messages, "temperature": 0.7,
                   "max_tokens": self.max_output_tokens, "stream": False}
        response = await client.post(url, headers=headers, json=payload)
        if not response.is_success:
            raise _safe_provider_error(response, cfg)
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
            if not isinstance(content, str):
                raise ValueError("invalid content")
            return content
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("服務回傳格式不符合 OpenAI 相容 API", retryable=True, cooldown_seconds=30) from exc

    async def _request_gemini(self, client: httpx.AsyncClient, cfg: ProviderConfig,
                              history: list[dict[str, str]]) -> str:
        model = quote(cfg.model, safe="-._")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": cfg.api_key, "Content-Type": "application/json"}
        contents = []
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if role not in ("user", "assistant"):
                continue
            contents.append({"role": "model" if role == "assistant" else "user",
                             "parts": [{"text": content}]})
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": self.max_output_tokens},
        }
        response = await client.post(url, headers=headers, json=payload)
        if not response.is_success:
            raise _safe_provider_error(response, cfg)
        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
            if not text:
                raise ValueError("empty")
            return text
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Gemini 回傳格式異常或沒有可用文字", retryable=True, cooldown_seconds=30) from exc
