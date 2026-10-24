from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    label: str
    kind: str
    api_key: str
    model: str
    base_url: str = ""


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def get_provider_configs() -> list[ProviderConfig]:
    candidates = {
        "groq": ProviderConfig(
            name="groq", label="Groq", kind="openai",
            api_key=_get("GROQ_API_KEY"),
            model=_get("GROQ_MODEL", "openai/gpt-oss-120b"),
            base_url=_get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        ),
        "openrouter": ProviderConfig(
            name="openrouter", label="OpenRouter", kind="openai",
            api_key=_get("OPENROUTER_API_KEY"), model=_get("OPENROUTER_MODEL"),
            base_url=_get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        ),
        "gemini": ProviderConfig(
            name="gemini", label="Gemini", kind="gemini",
            api_key=_get("GEMINI_API_KEY"),
            model=_get("GEMINI_MODEL", "gemini-3.8-flash"),
        ),
        "openai": ProviderConfig(
            name="openai", label="OpenAI", kind="openai",
            api_key=_get("OPENAI_API_KEY"),
            model=_get("OPENAI_MODEL", "gpt-4o-mini"),
            base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        ),
        "mistral": ProviderConfig(
            name="mistral", label="Mistral", kind="openai",
            api_key=_get("MISTRAL_API_KEY"),
            model=_get("MISTRAL_MODEL", "mistral-small-latest"),
            base_url=_get("MISTRAL_BASE_URL", "https://api.mistral.ai/v1"),
        ),
        "custom": ProviderConfig(
            name="custom", label=_get("CUSTOM_PROVIDER_NAME", "Custom API"), kind="openai",
            api_key=_get("CUSTOM_API_KEY"), model=_get("CUSTOM_MODEL"),
            base_url=_get("CUSTOM_BASE_URL"),
        ),
        "ollama": ProviderConfig(
            name="ollama", label="Ollama（本機）", kind="openai",
            api_key=_get("OLLAMA_API_KEY", "ollama"), model=_get("OLLAMA_MODEL"),
            base_url=_get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        ),
    }
    order = [part.strip().lower() for part in _get(
        "PROVIDER_ORDER", "groq,openrouter,gemini,openai,mistral,custom,ollama"
    ).split(",") if part.strip()]
    configs: list[ProviderConfig] = []
    seen: set[str] = set()
    for name in order:
        if name in seen or name not in candidates:
            continue
        seen.add(name)
        cfg = candidates[name]
        # Do not activate local Ollama merely because it is installed: its model must be explicitly set.
        if cfg.api_key and cfg.model and (cfg.kind != "openai" or cfg.base_url):
            configs.append(cfg)
    return configs


def get_app_password() -> str:
    # Passwords are secrets, not ordinary configuration labels: preserve intentional
    # leading/trailing whitespace exactly as supplied by the environment or .env.
    return os.getenv("APP_PASSWORD", "")


def get_database_url() -> str:
    url = _get("DATABASE_URL", "sqlite:///./data/freemind.db")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+" not in url.split(":", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url
