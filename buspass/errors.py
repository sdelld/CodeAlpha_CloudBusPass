"""Centralised error handling: every API error is {"error": {"code", "message", "details"}}."""

import logging

from flask import jsonify, render_template, request

log = logging.getLogger(__name__)


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message, code=None, status=None, details=None):
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status = status or self.status
        self.details = details


class NotFound(AppError):
    status, code = 404, "not_found"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class Conflict(AppError):
    status, code = 409, "conflict"


class ValidationFailed(AppError):
    status, code = 422, "validation_error"


class PaymentError(AppError):
    status, code = 402, "payment_error"


def error_response(code, message, status, details=None):
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(e):
        return error_response(e.code, e.message, e.status, e.details)

    @app.errorhandler(404)
    def handle_404(e):
        if request.path.startswith("/api/"):
            return error_response("not_found", "Resource not found.", 404)
        return render_template("error.html", status=404, message="Page not found"), 404

    @app.errorhandler(429)
    def handle_429(e):
        return error_response("rate_limited", "Too many requests. Please wait a moment and try again.", 429)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        from werkzeug.exceptions import HTTPException

        if isinstance(e, HTTPException):
            if request.path.startswith("/api/"):
                return error_response("http_error", e.description or e.name, e.code)
            return e
        log.exception("unhandled_error", extra={"path": request.path})
        if request.path.startswith("/api/"):
            return error_response("internal_error", "Something went wrong on our side.", 500)
        return render_template("error.html", status=500, message="Something went wrong"), 500
