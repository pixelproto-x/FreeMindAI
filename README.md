# FreeMind AI

FreeMind AI is a compact, self-hostable chat application focused on reliability rather than an oversized feature list. It has a responsive Traditional Chinese UI, persistent chat history, a provider-fallback router, circuit-breaker cooldowns for rate-limited providers, server-side secrets, and basic access-password protection.

## What is included

- **Provider adapters:** Gemini's native `generateContent` API and OpenAI-compatible APIs (Groq, OpenRouter, OpenAI, Mistral, Ollama, or a custom endpoint).
- **Automatic failover:** Tries configured providers in `PROVIDER_ORDER`. HTTP 429, invalid keys, missing models, temporary service outages, and network timeouts are classified separately. Providers are cooled down instead of being retried on every message.
- **Persistent conversations:** SQLAlchemy supports SQLite for local use and PostgreSQL for hosted deployments. A user/assistant turn is saved together only after a successful AI response, so failed API calls do not create half-complete turns.
- **Protection:** API keys stay on the server. `APP_PASSWORD` can protect all app APIs; production mode refuses to start without it.
- **Testing:** Automated tests for API round trips, persistence, rate-limit classification, and provider status key-safety.
- **Deployment:** Dockerfile and a Render Blueprint are included. The Blueprint uses a paid web service and database plan to prioritize persistence over a sleeping/ephemeral free instance. Check current provider/platform pricing before deploying.

## Important limits (please read)

No application can promise that third-party cloud AI services remain free, unlimited, or always online. This project avoids depending on just one provider and skips providers during cooldown, but each configured provider still applies its own terms, rate limits, billing, and availability. Use only providers and models you have verified in their current official dashboards. A `:free` model on an aggregator may be removed or become unavailable without notice.

If you need no cloud API quota at all, configure a local Ollama model. That option consumes the computer's CPU/GPU/RAM and does not meet the goal of keeping all inference off your computer.

## Local run on Windows

1. Install Python 3.11 or 3.12 (recommended for the supported dependency set).
2. Extract the project into a folder such as `C:\FreeMindAI`.
3. For the simplest startup, double-click `run.bat`. It creates the virtual environment, installs runtime dependencies, and opens `.env` the first time. Alternatively, open that folder in PowerShell and continue with the manual steps below.
4. Create an environment and install dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   Copy-Item .env.example .env
   ```

5. Edit `.env`, adding at least one API key and the correct model name. `GROQ_API_KEY` is enough to start, because a default Groq model is provided. Add Gemini/OpenRouter for failover, after verifying the models are enabled in their provider accounts.
6. After the initial setup, run `run.bat` or:

   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```

7. Open <http://127.0.0.1:8080>.

`APP_PASSWORD` may stay empty only for local development on `127.0.0.1`. Do not bind a passwordless instance to `0.0.0.0` or expose it to the internet.

## Configure model providers

Copy values into `.env`; never commit the real `.env` file.

- **Groq:** set `GROQ_API_KEY` and confirm `GROQ_MODEL` in Groq Console.
- **Gemini:** set `GEMINI_API_KEY` and the model available to the selected Google AI Studio project.
- **OpenRouter:** set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`. Do not assume all free models are permanently available.
- **OpenAI/Mistral:** optionally add their API key and model.
- **Custom:** set `CUSTOM_API_KEY`, `CUSTOM_MODEL`, and an OpenAI-compatible `CUSTOM_BASE_URL`.
- **Ollama:** set `OLLAMA_MODEL` to explicitly enable a local model. This runs on your own computer.

Change provider order with `PROVIDER_ORDER=groq,openrouter,gemini,custom`. Providers that are not configured are silently skipped. API keys are never returned by the status API.

## Hosting on Render

The included `render.yaml` is a starting blueprint for a persistent hosted deployment; the web service and database use paid plans because the priority here is a persistent database and predictable availability. Review the live Render pricing and change service names/regions as needed before deployment. After provisioning, open the service's environment settings, set the provider keys, and retrieve the generated `APP_PASSWORD` through the dashboard's supported secret controls. Use HTTPS only. Do not publish that password or API keys.

For any host that uses PostgreSQL, set `DATABASE_URL` to its PostgreSQL connection string. The app normalizes `postgres://` to the Psycopg SQLAlchemy driver. SQLite is appropriate for local use and single-instance self-hosting; the database file must live on persistent storage if hosted.

## Reliability notes

- A provider's HTTP 429 response starts a cooldown; daily quota-like errors use a longer default cooldown (`DAILY_QUOTA_COOLDOWN_SECONDS`, six hours by default). This is a conservative app-level rule, not a guarantee about the provider's actual reset time.
- Temporary 5xx/timeout failures receive one bounded retry and then fall through to the next provider. 401/403 and 404 errors do not get blindly retried.
- Request size, model output size, timeouts and chat context are bounded by environment variables.
- Provider error bodies and secrets are not shown or logged. Statuses return only safe summaries.
- SQLite enables foreign keys, WAL, and a busy timeout.
- Back up the database before upgrades. This first release uses SQLAlchemy `create_all` for initial schema creation, not a full migration framework; future schema changes should introduce Alembic migrations.

## Back up local chat history

Before making updates, you can create a consistent SQLite backup:

```powershell
.\.venv\Scripts\python.exe scripts\backup_sqlite.py
```

PostgreSQL deployments should use the database provider's backup/snapshot features. Do not use a copied live database file as a substitute for a managed PostgreSQL backup.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions runs Python compilation, JavaScript syntax checks, and the tests on pushes and pull requests. The tests do not call any paid or free AI APIs. They use a fake provider to validate the application flow. Install `requirements-dev.txt` to include pytest; production Docker images install only `requirements.txt`.

## Project inspiration

This project implements its own small core, drawing architectural ideas from public projects rather than copying their code wholesale: Open WebUI/LibreChat/LobeChat for conversation UX, LiteLLM for provider routing and fallback concepts, Letta for stateful memory as a future direction, and Dify/AnythingLLM/Flowise for possible future knowledge and workflow features. Their licenses differ and can change; review the exact source and license before integrating third-party code. FreeMind AI's original code in this package is provided under the MIT License; third-party dependencies retain their own licenses.
