FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 APP_ENV=production
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home appuser && mkdir -p instance/uploads && chown -R appuser instance
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz')"

# init-db runs migrations under a PostgreSQL advisory lock, so many containers can boot at once.
# Workers are stateless (JWT auth, data in PostgreSQL) and can scale horizontally behind a load balancer.
CMD flask --app wsgi init-db && \
    gunicorn wsgi:app --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-3} --threads 2 --access-logfile -
