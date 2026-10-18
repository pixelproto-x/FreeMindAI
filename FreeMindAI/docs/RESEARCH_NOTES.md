# FreeMind AI — Open-source research notes

Research pass: 2026-10-18. This is a curated review of major projects and relevant official documentation, not a claim that every public repository on the internet has been reviewed. Open-source ecosystems are too large and change too quickly to make an honest “all projects reviewed” claim.

## Projects reviewed for architecture ideas

| Project | Useful ideas considered | License / reuse note | Adopted in this first version |
|---|---|---|---|
| [LibreChat](https://github.com/danny-avila/LibreChat) | Multi-provider chat UX, conversations, file/tool integrations | Review the repository's current license before copying source code | Conversation list, model provider metadata; no source copied |
| [Open WebUI](https://github.com/open-webui/open-webui) | Provider connections, chat history, knowledge workflows | Current source has a branding restriction clause; contributions made under earlier licenses retain their original terms. Inspect exact versions before reuse | High-level ideas only; no code or branding copied |
| [LobeChat](https://github.com/lobehub/lobe-chat) | Polished responsive chat UX, provider switching, assistant settings | Its current license includes additional conditions for derivative works; check the repository license before using source | General UX ideas only; original UI and code authored here |
| [LiteLLM](https://github.com/BerriAI/litellm) | Unified provider interfaces, retries, fallbacks, cooldown policies | It is a large dependency; security advisories have emphasized keeping deployments patched. We do not depend on it in this first build | Small local router implemented directly, reducing dependency and configuration surface |
| [Letta](https://github.com/letta-ai/letta) | Persistent agent memory and conversation state | Apache-2.0 shown on the project repository, but validate the precise current package/license | Persistent conversation and message records; advanced agent memory deferred |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | Document retrieval and personal knowledge spaces | Review license of the exact revision before reuse | Not yet included; avoid declaring retrieval working before implementing and testing it |
| [Dify](https://github.com/langgenius/dify) | AI workflows, tools, retrieval pipelines | Dify's published license is based on Apache-2.0 with additional conditions including multi-tenant and branding provisions | Workflow design inspiration only; no Dify code included |
| [Flowise](https://github.com/FlowiseAI/Flowise) | Visual workflow builder and composition of AI tools | Repository contains license/edition conditions; inspect the exact component and release before reuse | Deferred; current release prioritizes a smaller, testable core |
| [Jan](https://github.com/janhq/jan) | Local/offline model path and a desktop-friendly mental model | AGPLv3 as shown in repository; derivative use can carry corresponding obligations | Optional Ollama adapter only; local mode is disabled unless explicitly configured |
| [Ollama](https://github.com/ollama/ollama) | Local and cloud model API integration | See project license and model-specific licenses separately | OpenAI-compatible local endpoint adapter |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Efficient local inference | Check code and model licenses separately | Not bundled; local inference is out of scope for the initial cloud-first release |

## Official operational documentation considered

- [Gemini API error handling](https://ai.google.dev/gemini-api/docs/api-errors): distinguish short-term rate limits from daily quota exhaustion; retry/backoff needs to be bounded.
- [LiteLLM routing documentation](https://docs.litellm.ai/docs/routing): fallback routing and provider cooldown are useful patterns. FreeMind uses a small first-party implementation instead of pulling in the gateway.
- [HTTPX timeout documentation](https://www.python-httpx.org/advanced/timeouts/): explicitly bound network waits rather than allowing a stalled provider call to hang the application.
- [Ollama API introduction](https://github.com/ollama/ollama/blob/main/docs/api/introduction.mdx): local endpoints do not need a cloud API key but local inference uses the host machine's compute resources.

## Design decisions made for stability

1. **Keep the runtime small.** A compact FastAPI app, a single provider-router module, SQLAlchemy persistence, and plain static HTML/CSS/JS are easier to inspect than an entire monorepo or workflow builder.
2. **Fail over instead of hammering.** Each provider has an app-level cooldown after quota/auth/model/transient failures. A temporary error gets at most one bounded retry before switching providers.
3. **Do not claim free means unlimited.** Provider availability and quotas remain external facts. A fallback cannot bypass another provider's terms.
4. **Persist complete turns together.** Failed requests do not write a user message without its assistant answer. This makes retry behavior less confusing.
5. **Keep secrets server-side.** The frontend never receives API keys. `APP_PASSWORD` protects API routes in hosted deployments; production startup refuses to run without it.
6. **Use durable hosted storage.** SQLite is suitable for local/single-instance use. Use PostgreSQL for a hosted multi-restart deployment; in-memory or ephemeral filesystems are not durable storage.
7. **Tests must avoid paid services.** The first automated tests use fake providers and local SQLite. Real provider smoke tests are intentionally separate because they require real keys and can consume free quota.

## Out of scope for this first stable core

File uploads, browser search tools, long-term semantic memory/RAG, user accounts, streaming tokens, and autonomous tool execution are not represented as “done.” They should be added one at a time with tests, migrations, permission boundaries, and explicit UI feedback.
