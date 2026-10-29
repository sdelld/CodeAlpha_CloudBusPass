"""Command line: `flask --app wsgi <command>`."""

import json

import click
from flask_migrate import upgrade
from sqlalchemy import text

from .extensions import db


def register(app):
    @app.cli.command("init-db")
    @click.option(
        "--seed/--no-seed", default=None, help="Load demo data if the database is empty (default: in DEMO_MODE)."
    )
    def init_db(seed):
        """Run migrations (and seed). Safe when many instances boot at once."""
        with db.engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                # Session-level advisory lock: one instance migrates, the others wait.
                conn.execute(text("SELECT pg_advisory_lock(724001)"))
            try:
                upgrade()
                from .models import Route

                should_seed = app.config["DEMO_MODE"] if seed is None else seed
                if should_seed and db.session.query(Route.id).first() is None:
                    from .seed import seed_demo

                    click.echo(json.dumps(seed_demo()))
            finally:
                if conn.dialect.name == "postgresql":
                    conn.execute(text("SELECT pg_advisory_unlock(724001)"))
        click.echo("database ready")

    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Drop all data first (development only).")
    def seed(reset):
        """Load realistic demo data (routes, buses, users of every role, 30 days of history)."""
        from .seed import seed_demo

        if reset:
            if app.config["ENV"] == "production":
                raise click.ClickException("Refusing to reset a production database.")
            db.drop_all()
            db.create_all()
        click.echo(json.dumps(seed_demo(), indent=2))

    @app.cli.command("daily-jobs")
    def daily_jobs():
        """Auto-renew passes, expire old ones, send expiry reminders. Schedule once a day (e.g. 00:05)."""
        from .services.passes import run_daily_jobs

        click.echo(json.dumps(run_daily_jobs()))
