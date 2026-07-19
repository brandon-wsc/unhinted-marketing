from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://unhinted:unhinted@localhost:5432/unhinted"
    jwt_secret: str = "change-me-to-a-long-random-secret-at-least-32-chars"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
