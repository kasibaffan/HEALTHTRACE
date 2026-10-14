"""Application settings. Every secret comes from the environment (or backend/.env, which is gitignored)."""
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
log = logging.getLogger("healthtrace.config")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    jwt_secret: str
    jwt_refresh_secret: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    cors_origins: list[str]
    storage_path: Path
    max_upload_mb: int
    cookie_secure: bool
    rate_limit_enabled: bool
    processing_step_delay_ms: int
    frontend_url: str
    demo_password: str | None
    doc_classifier_enabled: bool = True
    doc_classifier_artifact_dir: Path = BACKEND_DIR / "ml" / "artifacts" / "document_classifier"
    doc_classifier_min_score: float = 0.5
    doc_classifier_max_chars: int = 20000

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_settings() -> Settings:
    env = os.getenv("APP_ENV", "development").lower()
    jwt_secret = os.getenv("JWT_SECRET", "")
    refresh_secret = os.getenv("JWT_REFRESH_SECRET", "")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to backend/.env and fill it in.")
    if not jwt_secret or not refresh_secret:
        if env == "production":
            raise RuntimeError("JWT_SECRET and JWT_REFRESH_SECRET must be set in production.")
        log.warning("JWT secrets not set; generating ephemeral secrets. Sessions will not survive a restart.")
        jwt_secret = jwt_secret or secrets.token_urlsafe(48)
        refresh_secret = refresh_secret or secrets.token_urlsafe(48)
    return Settings(
        env=env,
        database_url=database_url,
        jwt_secret=jwt_secret,
        jwt_refresh_secret=refresh_secret,
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")),
        refresh_token_expire_days=int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()],
        storage_path=Path(os.getenv("STORAGE_PATH", str(BACKEND_DIR / "storage_data"))).resolve(),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "15")),
        cookie_secure=_bool("COOKIE_SECURE", env == "production"),
        rate_limit_enabled=_bool("RATE_LIMIT_ENABLED", True),
        processing_step_delay_ms=int(os.getenv("PROCESSING_STEP_DELAY_MS", "0")),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
        demo_password=os.getenv("DEMO_PASSWORD") or None,
        doc_classifier_enabled=_bool("DOC_CLASSIFIER_ENABLED", True),
        doc_classifier_artifact_dir=Path(os.getenv("DOC_CLASSIFIER_ARTIFACT_DIR", str(BACKEND_DIR / "ml" / "artifacts" / "document_classifier"))).resolve(),
        doc_classifier_min_score=float(os.getenv("DOC_CLASSIFIER_MIN_SCORE", "0.5")),
        doc_classifier_max_chars=int(os.getenv("DOC_CLASSIFIER_MAX_CHARS", "20000")),
    )


settings = load_settings()
