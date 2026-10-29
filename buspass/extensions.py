from flask import request
from flask_limiter import Limiter
from flask_migrate import Migrate
from flask_smorest import Api
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from werkzeug.exceptions import HTTPException

# Stable constraint names so Alembic migrations are portable between SQLite and PostgreSQL.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

db = SQLAlchemy(metadata=metadata)
migrate = Migrate()


def _client_ip():
    # Behind Render / nginx the real client is the first X-Forwarded-For entry.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr or "unknown"


limiter = Limiter(key_func=_client_ip, default_limits=["300 per minute"])


class JsonErrorApi(Api):
    """flask-smorest Api whose HTTP errors use the same envelope as AppError."""

    def handle_http_exception(self, error: HTTPException):
        from .errors import error_response

        details = getattr(error, "data", {}).get("messages") if hasattr(error, "data") else None
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            409: "conflict",
            413: "payload_too_large",
            422: "validation_error",
            429: "rate_limited",
        }.get(error.code, "http_error")
        message = "Some fields are invalid." if error.code == 422 else (error.description or error.name)
        return error_response(code, message, error.code, details)


api = JsonErrorApi()
