from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# ADR 0032 §3 — hosted vendor relay shared by every relay-mode install.
# Product surface (a fixed service endpoint), not user input; override via
# OAUTH_RELAY_URL only for a self-hosted/dev relay.
HOSTED_OAUTH_RELAY_URL = "https://unhinted-oauth-relay.unhinted.workers.dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # development | production — non-development refuses known-default / short JWT_SECRET
    app_env: str = "development"
    # cloud | onprem (ADR 0023) — read once at process start and treated as
    # immutable for the process lifetime. On-prem Docker images bake it via
    # build ARG; changing it requires a restart (or rebuild), never a toggle.
    deployment_mode: Literal["cloud", "onprem"] = "onprem"
    allow_insecure_jwt: bool = False

    database_url: str = "postgresql+asyncpg://unhinted:unhinted@localhost:5432/unhinted"
    jwt_secret: str = "change-me-to-a-long-random-secret-at-least-32-chars"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "https://unhinted.localhost:5173"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"

    # Auth rate limit (in-memory sliding window per client IP; Redis later)
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_max: int = 30
    auth_rate_limit_window_seconds: int = 60

    # Org invite create rate limit (per inviting user; Redis later)
    invite_rate_limit_enabled: bool = True
    invite_rate_limit_max: int = 20
    invite_rate_limit_window_seconds: int = 60

    # BYOK probe / model-list proxy (per editor; Redis later)
    byok_probe_rate_limit_enabled: bool = True
    byok_probe_rate_limit_max: int = 20
    byok_probe_rate_limit_window_seconds: int = 60

    # Invite links + optional email delivery (on-prem: link mode default)
    web_base_url: str = "https://unhinted.localhost:5173"
    email_backend: str = "link"  # link | smtp | console
    email_from: str = "noreply@localhost"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_tls: bool = True

    # LLM (env fallback; org BYOK keys encrypted with BYOK_ENCRYPTION_KEY — ADR 0020)
    byok_encryption_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    vertex_ai_api_key: str | None = None
    # SDK Express pair (read-only; never set GOOGLE_GENAI_USE_VERTEXAI in-process).
    google_api_key: str | None = None
    google_genai_use_vertexai: bool = False
    llm_api_base: str | None = None
    llm_cheap_model: str = "gpt-4o-mini"
    llm_medium_model: str = "gpt-4o-mini"
    llm_strong_model: str = "gpt-4o"
    # Dedicated image model (e.g. dall-e-3). Chat-only ids will fail at runtime.
    # Empty = image gen disabled (error when credentials exist). "placeholder" = mock URL.
    llm_image_model: str | None = None
    llm_timeout_seconds: float = 45.0
    # ADR 0005: persist every LLM call to llm_call_records (prompts, response, tokens).
    llm_record_enabled: bool = True
    # Persist graph node-step I/O to session_node_steps (admin Trace viewer).
    node_trace_enabled: bool = True

    # Media (ADR 0024 + 0025). On-prem default is local disk; S3_* seeds the
    # first storage_configs row only. Portal config is the source of truth.
    media_root: str = "data/media"
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    # Browser-facing base. Default derived from endpoint/bucket or AWS virtual-host.
    s3_public_base_url: str | None = None

    # Perception / workers
    # ADR 0018: TTL must outlive the 12h scheduler tick so cache does not
    # expire just before the next run.
    question_cache_ttl_hours: int = 13
    # Question worker graph (ADR 0018)
    question_dedupe_days: int = 7
    question_run_max_concurrency: int = 2
    question_run_stale_minutes: int = 8
    news_promote_trends_rank_max: int = 10
    news_promote_window_hours: int = 24
    scheduler_hot_search_interval_minutes: int = 60
    scheduler_questions_interval_hours: int = 12

    # Tavily web search ingest (ADR 0009) — session research upserts into raw_news_events
    tavily_api_key: str | None = None

    # Semantic research gate (ADR 0009) — FastEmbed local ONNX via semantic-router
    semantic_router_enabled: bool = True
    # FastEmbed registry has no multilingual-e5-small; default MiniLM multilingual small.
    # e5-large works but ~2GB — set explicitly if desired.
    semantic_router_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    semantic_router_score_threshold: float = 0.5

    # Real publish (ADR 0022) — stub never hits Meta; instagram uses social_accounts
    publish_adapter: str = "stub"  # stub | instagram
    meta_graph_api_version: str = "v22.0"

    # Instagram Login connect (ADR 0022 OAuth slice). These are the Instagram App
    # ID / Secret from App Dashboard → Instagram (often not the Facebook App ID).
    # Callback URI is `{web_base_url}/api/social/oauth/callback` — whitelist that
    # exact string in the Meta dashboard (no separate META_OAUTH_REDIRECT_URI).
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    # Where the browser lands after a successful connect (defaults to WEB_BASE_URL)
    meta_oauth_success_url: str | None = None
    # ADR 0032 §3 — vendor relay base URL. Defaults to the hosted Unhinted
    # relay (HOSTED_OAUTH_RELAY_URL); set only to point at a self-hosted/dev
    # relay. Seeds instance_settings.meta_oauth_relay_url; portal wins after.
    oauth_relay_url: str | None = None
    # Optional override for meta_oauth_instance_id (normally auto-generated) —
    # handy for pinning a pre-registered REGISTRY slug in dev/UAT.
    meta_oauth_instance_id: str | None = None
    # ADR 0034 — per-install shared secret the relay issues at registration.
    # Seeds instance_settings.meta_oauth_relay_secret (Fernet) while unset;
    # afterwards the portal wins. Dev/UAT convenience — production installs
    # paste it via System → Instance.
    oauth_relay_secret: str | None = None

    # Product catalog embeddings (COLLECT K4) — same FastEmbed family as semantic gate
    product_embeddings_enabled: bool = True
    # Empty → reuse semantic_router_model
    product_embedding_model: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
