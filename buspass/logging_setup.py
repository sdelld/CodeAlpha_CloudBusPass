"""Structured JSON logs with a request id, so production logs can be searched and correlated."""

import json
import logging
import time
import uuid

from flask import g, request


class JsonFormatter(logging.Formatter):
    RESERVED = set(vars(logging.makeLogRecord({})))

    def format(self, record):
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in self.RESERVED and not k.startswith("_")})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(app):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(app.config["LOG_LEVEL"])
    access = logging.getLogger("buspass.access")

    @app.before_request
    def start_timer():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        g.started = time.perf_counter()

    @app.after_request
    def log_request(response):
        if request.path.startswith("/static/"):
            return response
        response.headers["X-Request-ID"] = g.get("request_id", "")
        user = g.get("user")
        access.info(
            "request",
            extra={
                "request_id": g.get("request_id"),
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - g.get("started", time.perf_counter())) * 1000, 1),
                "user_id": user.id if user else None,
            },
        )
        return response
