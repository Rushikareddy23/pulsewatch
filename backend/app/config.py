import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/pulsewatch")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-change-me")
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "720"))
    cors_origins: list[str] = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","))
    # Never let users point the checker at internal addresses (e.g. 169.254.169.254) in production.
    allow_private_targets: bool = _bool("ALLOW_PRIVATE_TARGETS", False)
    failure_threshold: int = int(os.getenv("FAILURE_THRESHOLD", "2"))
    worker_batch_size: int = int(os.getenv("WORKER_BATCH_SIZE", "100"))
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "50"))
    retention_days: int = int(os.getenv("RETENTION_DAYS", "30"))
    notifier: str = os.getenv("NOTIFIER", "log")  # log | smtp | ses
    alert_from: str = os.getenv("ALERT_FROM", "alerts@example.com")
    smtp_host: str = os.getenv("SMTP_HOST", "localhost")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))
    min_interval_s: int = int(os.getenv("MIN_INTERVAL_S", "30"))


settings = Settings()
