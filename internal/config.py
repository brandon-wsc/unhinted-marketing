from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # development | production — non-development refuses known-default / short JWT_SECRET
    app_env: str = "development"
    allow_insecure_jwt: bool = False

    database_url: str = "postgresql+asyncpg://unhinted:unhinted@localhost:5432/unhinted"
    jwt_secret: str = "change-me-to-a-long-random-secret-at-least-32-chars"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"

    # Auth rate limit (in-memory sliding window per client IP; Redis later)
    auth_rate_limit_enabled: bool = True
    auth_rate_limit_max: int = 30
    auth_rate_limit_window_seconds: int = 60

    # LLM (BYOK via env; org keys in DB deferred to Phase 4)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
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

    # S3-compatible media (MinIO locally — see docker-compose `minio` service)
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "unhinted-media"
    s3_region: str = "us-east-1"
    # Browser-facing base (path-style). Default derived as {endpoint}/{bucket}.
    s3_public_base_url: str | None = None

    # Perception / workers
    question_cache_ttl_hours: int = 12
    news_promote_trends_rank_max: int = 10
    news_promote_window_hours: int = 24
    scheduler_hot_search_interval_minutes: int = 60
    scheduler_questions_interval_hours: int = 12

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
