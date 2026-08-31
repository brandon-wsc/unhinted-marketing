# ADR 0021 — Org BYOK: native Gemini + Vertex Express

- **Status:** Accepted
- **Date:** 2026-08-31
- **Amends:** [ADR 0020](./0020-org-byok-keys-models-routing.md) (`provider_type` enum; Chat Completions + Images surface is no longer universal)
- **Related:** [ADR 0019](./0019-pydantic-ai-inner-harness.md) (`live_harness_model` gains `GoogleModel` branches; do not add the `openai` extra)

## Context

ADR 0020 locked org BYOK to three `provider_type` values — `openai`, `anthropic`, `openai_compatible` — on the premise that every call is Chat Completions + Images API. That premise holds for DeepSeek / OpenRouter / Groq and similar clones, and for Anthropic because we already speak Messages natively.

Google’s Gemini stack does **not** hold. Two API-key products share `generateContent` but **not** the same host or auth envelope:

1. **Google AI Studio** (`generativelanguage.googleapis.com`) — API key, `GET …/v1beta/models`, `x-goog-api-key`.
2. **Vertex AI Express Mode** (`aiplatform.googleapis.com/v1/publishers/google/models/{id}:generateContent?key=`) — API key, no project / location. After an Express account is upgraded to full Vertex, the wire becomes OAuth + `projects/{project}/locations/{location}/…`.

Neither is Chat Completions + Images:

- **Tool loops** on Gemini 2.5/3 require round-tripping `thought_signature`. `OpenAIChatModel` against Google’s OpenAI-compat URL (`…/v1beta/openai/`) drops that field.
- **Image** is Imagen / `generateContent` image parts, not `/v1/images/generations`.
- Pasting an Express key into `gemini` (AI Studio host) typically **401**. Pasting an AI Studio key into Express does the same. The types must stay distinct.

A first-class native type is the same reason `anthropic` exists: native wire, native harness class. Express is still API-key auth, so it is in scope here. Vertex **OAuth / ADC / service account / project+location** is a different credential shape and stays out.

## Decision

### 1. Native `provider_type` only when the wire is not Chat Completions + Images

Do not add a dropdown row per brand. Clones stay `openai_compatible`.

| Type | Wire | Auth in scope |
|------|------|----------------|
| `openai` | Chat Completions + Images | API key |
| `openai_compatible` | Same, custom `api_base` (DeepSeek, OpenRouter, Groq, Together, Fireworks, xAI, DashScope compatible-mode, Azure-as-base, …) | API key |
| `anthropic` | Messages API | API key |
| `gemini` | AI Studio `generateContent` + Imagen / Gemini image gen (`generativelanguage.googleapis.com`) | API key |
| `vertex_ai` | Vertex **Express Mode** `generateContent` (`aiplatform.googleapis.com/v1/publishers/google/…`) | API key only |

### 2. Enum is `openai \| anthropic \| openai_compatible \| gemini \| vertex_ai`

CHECK-constrained. `api_base` remains required **only** for `openai_compatible`. Both `gemini` and `vertex_ai` ignore a stored `api_base` (fixed hosts).

### 3. `gemini` = AI Studio API key

- Org rows: `provider_type=gemini`, Fernet key, no base URL field in the UI.
- Env fallback: `GEMINI_API_KEY`, parallel to `ANTHROPIC_API_KEY`. Model ids that look like `gemini*` / `imagen*` resolve as `gemini` when `LLM_API_BASE` is unset **and** `GEMINI_API_KEY` is set. If the Studio key is unset, Express env (`VERTEX_AI_API_KEY`, or `GOOGLE_API_KEY` + `GOOGLE_GENAI_USE_VERTEXAI=true`) resolves as `vertex_ai`. If none of those are set, the type still defaults to `gemini` (same as before this ADR) with no key.
- LiteLLM ids are `gemini/{id}` (existing `gemini/` / `imagen/` prefixes kept). Never `openai/` for this type. `effective_api_base` is `None` (AI Studio default).
- Harness: `GoogleModel` + `GoogleProvider(api_key=…)` (`vertexai=False`). Missing `pydantic-ai-slim[google]` → `LlmProviderError kind=unsupported`.
- Model list: `GET https://generativelanguage.googleapis.com/v1beta/models` with `x-goog-api-key`. Parse `{models:[{name, supportedGenerationMethods}]}`; strip `models/`; Imagen / predict-only / `*-image*` → `capability=image`.
- Image slot still goes through `litellm.aimage_generation`; inline Gemini b64 is normalized to the existing data-URL path. `litellm.drop_params = True` still drops OpenAI `size` for Imagen.

Pasting Google’s OpenAI-compat URL as `openai_compatible` is not blocked (Completions-only orgs may still do it) but is the wrong path for tools and image.

### 4. `vertex_ai` = Vertex Express API key (not OAuth)

- Org rows: `provider_type=vertex_ai`, Fernet key, no base URL field in the UI. UI label **Vertex AI (Express)**.
- Env fallback: `VERTEX_AI_API_KEY`, **or** the SDK pair `GOOGLE_API_KEY` + `GOOGLE_GENAI_USE_VERTEXAI=true` (flag is **read**, never written in-process). **Never** treat `GEMINI_API_KEY` as Express. When a gemini-looking env model id is set, `GEMINI_API_KEY` wins (`gemini`); Express env is used only when the AI Studio key is unset. `GEMINI_API_KEY` alone is not Express.
- Harness: `GoogleModel` + `GoogleCloudProvider(api_key=…)` **only**. Do not pass `project`, `location`, or `credentials` — those kwargs make the SDK take ADC / OAuth. Missing google extra → same `unsupported` error as `gemini`.
- Wire: `google.genai.Client(vertexai=True, api_key=…)`. Documented REST is `POST https://aiplatform.googleapis.com/v1/publishers/google/models/{id}:generateContent?key=`. GCP console API keys as ``?key=`` (google-genai also sends ``x-goog-api-key``).
- Do **not** use LiteLLM’s ``vertex_ai/`` prefix (OAuth Bearer + `projects/{project}/locations/{location}/…`). Do **not** use LiteLLM ``gemini/`` plus a publishers `api_base` (HTTP/1.1 POST to `aiplatform.googleapis.com` hangs). Do **not** set process-global `GOOGLE_GENAI_USE_VERTEXAI` (would hijack AI Studio `GoogleProvider`). JSON / text / stream / image for this type go through the same SDK client as the harness. Stored `api_base` is ignored.
- Auth probe: `generate_content` (max 1 token) with retry `attempts=1` and a timeout longer than the 8s HTTP SSRF probe — not `countTokens`, not raw httpx/SSRF POST. Do not pass project/location (ADC). Express REST has **no ListModels**; catalog GET may be unfetchable and must not mark the key as failed.
- Model list: `GET https://aiplatform.googleapis.com/v1/publishers/google/models?key=` when the publisher list exists. Parse `{models|publisherModels:[{name}]}`; strip `publishers/google/models/` and `models/`; capability from the same image-id markers as Gemini when the publisher list has no `supportedGenerationMethods`.
- Image slot: same `generate_content` + inline-b64 normalize as the chat path (not LiteLLM `aimage_generation`).

Third-party “Gemini” fields almost always hit `generativelanguage.googleapis.com`. Pasting an Express key there (or into `openai_compatible` / `OPENAI_BASE_URL`) typically **401 / 404**. The types stay distinct.

### 5. Explicitly deferred (not types)

Vertex **OAuth / service account / ADC / project+location** (post-upgrade full Agent Platform). Bedrock (AWS SigV4), Cohere Chat v2, Ollama native `/api/chat`, Azure as a dedicated type (`api-version` / deployment envelope). Custom Gemini safety settings. Responses API (still a separate ADR).

## Consequences

- Alembic hex revisions recreate `ck_byok_providers_type` to include `'gemini'` then `'vertex_ai'` (do not rewrite earlier CHECK revisions).
- Resolver, router, probes, and `live_harness_model` branch on `provider_type`.
- `pydantic-ai-slim[google]` is a direct extra (not the `openai` extra — ADR 0019 conflict stands). `GoogleCloudProvider` lives in that extra.
- Contracts + TS mirrors regenerated; Settings dropdown gains Gemini and Vertex AI (Express).
- Changing the native-type rule (§1), merging the two Google hosts into one type, or adding Vertex OAuth requires a superseding ADR.
