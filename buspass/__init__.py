"""CloudBus Pass application factory."""

import os

from flask import Flask, request

from .config import Config
from .errors import register_error_handlers
from .extensions import api as rest_api
from .extensions import db, limiter, migrate
from .logging_setup import setup_logging

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' "
    "https://checkout.stripe.com https://accept.paymob.com"
)


def create_app(overrides=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    Config.validate(app.config)

    setup_logging(app)
    db.init_app(app)
    migrate.init_app(app, db, directory=_migrations_dir())
    limiter.init_app(app)
    rest_api.init_app(app)

    from .api.v1 import auth, operations, rider

    for blp in (
        auth.blp,
        rider.me,
        rider.catalog_blp,
        rider.passes_blp,
        operations.pay,
        operations.val,
        operations.spo,
        operations.adm,
    ):
        rest_api.register_blueprint(blp)

    from . import cli, web

    app.register_blueprint(web.bp)
    cli.register(app)
    register_error_handlers(app)

    # Cache-busting stamp for static assets (also makes the offline service worker pick up new code).
    static_mtimes = [os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(app.static_folder) for f in fs]
    asset_version = str(int(max(static_mtimes, default=0)))

    @app.context_processor
    def inject_asset_version():
        return {"asset_version": asset_version}

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if not request.path.startswith("/api/v1/docs"):  # Swagger UI loads its assets from a CDN
            resp.headers.setdefault("Content-Security-Policy", CSP)
        if app.config["COOKIE_SECURE"]:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    return app


def _migrations_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
