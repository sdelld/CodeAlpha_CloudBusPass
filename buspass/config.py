"""Configuration, read from environment variables (see .env.example)."""

import os
from datetime import timedelta

DEV_SECRET = "dev-only-insecure-secret-change-me"


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///buspass.db")
    # Render/Heroku/RDS style URLs -> SQLAlchemy's psycopg3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Config:
    ENV = os.environ.get("APP_ENV", "development")  # development | test | production
    SECRET_KEY = os.environ.get("SECRET_KEY", DEV_SECRET)
    JWT_SECRET = os.environ.get("JWT_SECRET") or SECRET_KEY
    QR_SECRET = os.environ.get("QR_SECRET") or SECRET_KEY
    ACCESS_TOKEN_TTL = timedelta(minutes=int(os.environ.get("ACCESS_TOKEN_MINUTES", "15")))
    REFRESH_TOKEN_TTL = timedelta(days=int(os.environ.get("REFRESH_TOKEN_DAYS", "30")))

    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    TIMEZONE = os.environ.get("TIMEZONE", "Africa/Cairo")
    CURRENCY = os.environ.get("CURRENCY", "EGP")
    DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "en")

    # Demo mode returns OTP codes in API responses and enables the mock payment provider UI.
    DEMO_MODE = _bool("DEMO_MODE", ENV != "production")
    PAYMENT_PROVIDER = os.environ.get("PAYMENT_PROVIDER", "mock")  # mock | stripe | paymob | fawry
    MOCK_WEBHOOK_SECRET = os.environ.get("MOCK_WEBHOOK_SECRET") or SECRET_KEY + ":mock-webhook"
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    PAYMOB_API_KEY = os.environ.get("PAYMOB_API_KEY", "")
    PAYMOB_HMAC_SECRET = os.environ.get("PAYMOB_HMAC_SECRET", "")
    PAYMOB_INTEGRATION_ID = os.environ.get("PAYMOB_INTEGRATION_ID", "")
    FAWRY_MERCHANT_CODE = os.environ.get("FAWRY_MERCHANT_CODE", "")
    FAWRY_SECURITY_KEY = os.environ.get("FAWRY_SECURITY_KEY", "")
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000")

    QR_WINDOW_SECONDS = int(os.environ.get("QR_WINDOW_SECONDS", "30"))
    QR_ALLOWED_DRIFT_WINDOWS = int(os.environ.get("QR_ALLOWED_DRIFT_WINDOWS", "1"))
    ANTI_PASSBACK_MINUTES = int(os.environ.get("ANTI_PASSBACK_MINUTES", "10"))

    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.getcwd(), "instance", "uploads"))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", True)
    RATELIMIT_HEADERS_ENABLED = True

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    COOKIE_SECURE = _bool("COOKIE_SECURE", ENV == "production")

    API_TITLE = "CloudBus Pass API"
    API_VERSION = "v1"
    OPENAPI_VERSION = "3.0.3"
    OPENAPI_URL_PREFIX = "/api/v1"
    OPENAPI_JSON_PATH = "openapi.json"
    OPENAPI_SWAGGER_UI_PATH = "/docs"
    OPENAPI_SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/"
    API_SPEC_OPTIONS = {
        "info": {
            "description": "Rider, validator, admin and sponsor API. Authenticate with "
            "`POST /api/v1/auth/login`, then send `Authorization: Bearer <access_token>`."
        },
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
    }

    @classmethod
    def validate(cls, cfg):
        """Refuse to boot a production instance with development secrets."""
        if cfg["ENV"] != "production":
            return
        missing = [k for k in ("SECRET_KEY",) if not cfg.get(k) or cfg[k] == DEV_SECRET]
        if cfg["PAYMENT_PROVIDER"] == "stripe" and not cfg["STRIPE_WEBHOOK_SECRET"]:
            missing.append("STRIPE_WEBHOOK_SECRET")
        if cfg["PAYMENT_PROVIDER"] == "mock" and not cfg["DEMO_MODE"]:
            missing.append("PAYMENT_PROVIDER (mock payments in production need DEMO_MODE=1)")
        if missing:
            raise RuntimeError(f"Production config is missing secure values for: {', '.join(missing)}")
