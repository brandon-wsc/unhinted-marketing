"""Vertex Express Mode (API key, not OAuth). ADR 0021 §4.

SDK: ``genai.Client(vertexai=True, api_key=...)``.
REST: ``https://aiplatform.googleapis.com/v1/publishers/google/models/{id}:generateContent?key=``.

Do not route Express through LiteLLM ``gemini/`` + publishers ``api_base``
(HTTP/1.1 POST to ``aiplatform.googleapis.com`` hangs) or ``vertex_ai/``
(OAuth Bearer + project/location). Do not mutate process-global
``GOOGLE_GENAI_USE_VERTEXAI`` — that would hijack AI Studio ``GoogleProvider``.
"""

from __future__ import annotations

from google import genai
from google.genai import types

# Auth ping: documented generateContent (not countTokens). SDK 401 with default
# retries can exceed BYOK's 8s HTTP probe timeout.
VERTEX_EXPRESS_PROBE_TIMEOUT_MS = 25_000
VERTEX_EXPRESS_PROBE_WAIT_SECONDS = 30.0
VERTEX_EXPRESS_PROBE_MODEL = "gemini-2.5-flash"


def express_client(api_key: str, *, timeout_ms: int) -> genai.Client:
    """Per-call Express client. Never pass project / location / credentials."""
    return genai.Client(
        vertexai=True,
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
