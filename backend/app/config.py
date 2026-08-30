from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    environment: str = "development"
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://fpl_user:fpl_password@localhost:5432/fpl_copilot"
    sql_echo: bool = False   # set SQL_ECHO=true to log every query

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # CORS — comma-separated string in env, parsed here
    cors_origins: str = "http://localhost:3000"

    # External APIs
    anthropic_api_key: str = ""
    api_football_key: str = ""

    # ── Background refresh ───────────────────────────────────────────────────
    # Only useful where the process stays alive. On a free tier that idles out,
    # trigger POST /api/v1/jobs/refresh from an external cron instead.
    scheduler_enabled: bool = False
    refresh_interval_minutes: int = 30

    # Shared secret for the job endpoint. Leave empty to allow unauthenticated
    # calls (fine locally); set it before exposing the API publicly, or anyone
    # can trigger a full rebuild.
    job_token: str = ""

    # ── FPL response cache ───────────────────────────────────────────────────
    # Collapses the duplicate manager lookups one dashboard load produces. Kept
    # short because the picks response also carries live points and rank; see
    # services/cache.py for why the bootstrap is never cached.
    cache_enabled: bool = True
    fpl_cache_ttl_seconds: int = 90

    # ── Telegram alerts (opt-in per manager) ─────────────────────────────────
    # From @BotFather. Empty disables delivery entirely: the endpoints still
    # respond and the UI reports it as unavailable rather than erroring.
    telegram_bot_token: str = ""
    # Echoed by Telegram in X-Telegram-Bot-Api-Secret-Token on every update.
    # Without it the webhook would accept anything that found the URL.
    telegram_webhook_secret: str = ""
    # Only these severities are pushed. `info` is genuine but not worth a
    # phone buzz, and sending it would train people to ignore the channel.
    telegram_min_severities: str = "critical,warning"

    @property
    def telegram_severities(self) -> set[str]:
        return {s.strip() for s in self.telegram_min_severities.split(",") if s.strip()}

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


settings = Settings()
