# CodeAlpha — Task 3: Cloud-Based Bus Pass System

An online bus ticket and pass booking system built to run on the cloud behind a load balancer, with
auto-scaling app servers and a managed PostgreSQL database.

**Stack:** Python · Flask · SQLAlchemy · PostgreSQL (SQLite locally) · Gunicorn · Docker · Nginx · AWS Elastic Beanstalk (auto scaling)

## How each requirement is met

| Requirement | How |
|---|---|
| Online booking hosted on the cloud | Flask web app + JSON API, containerised with Docker, deployable to AWS Elastic Beanstalk / Google Cloud Run / Render |
| **Prevent ticket loss** | Tickets are stored in the passenger's account, not on paper. They can be reopened from any device at any time. |
| **Prevent ticket theft / forgery** | Each QR code holds `BP1.<random id>.<HMAC-SHA256 signature>`. The signature covers owner, route, dates and price, keyed with a server secret, so forged or edited tickets are rejected. Single-ride tickets are **single-use**: the first scan marks them used. A lost or stolen ticket can be **reported**: the old QR code is blocked immediately and a free replacement is issued. The conductor sees the passenger's name on every scan. |
| **Prevent incorrect pricing** | Prices are computed **only on the server** from the fare table (`pricing.py`) using integer cents (no float rounding errors). Any price sent by the browser is ignored, and the price is part of the signed ticket. |
| No double booking / overselling | Idempotency key per booking form (double clicks create one ticket), and a database row lock on the route while checking seat capacity, so two buyers can't take the last seat at once. |
| Handle high traffic with dynamically provisioned servers | The app is **stateless** (sessions in signed cookies, data in Postgres), so any number of identical containers can run behind a load balancer. `.ebextensions/01-autoscaling.config` gives AWS a group of **2–8 servers** that grows above 60% CPU and shrinks below 25%. Locally, `docker compose up --scale app=5` does the same by hand. |
| Scalability & reliability vs traditional sites | Minimum 2 servers across availability zones, `/healthz` health checks so the load balancer replaces failed servers, rolling zero-downtime deploys, DB connection health checks (`pool_pre_ping`). |
| Test and deploy | 14 automated tests (`pytest`) + a Locust load test (`locustfile.py`). |

## Architecture

```
Passengers ──► Load balancer (AWS ALB / nginx)
                    │
         ┌──────────┼──────────┐        auto scaling group: 2..8 instances
         ▼          ▼          ▼
      app #1     app #2  ...  app #N    Flask + Gunicorn in Docker (stateless)
         └──────────┼──────────┘
                    ▼
          PostgreSQL (AWS RDS)          users, routes, tickets
```

## Run locally (no Docker)

```bash
pip install -r requirements.txt
```
```bash
python app.py
```
Open http://127.0.0.1:5000, sign up, book a ticket and open it to see the QR code.
To try the conductor scanner, go to `/conductor`, use the key `conductor-dev-key` and paste the ticket code
(shown under "Ticket code" on the ticket page). Scan it twice to see the single-use check.

## Run the scaled version locally (Docker)

```bash
docker compose up --build --scale app=3
```
Open http://localhost:8080. `/healthz` shows which container answered (`instance`), so refreshing it shows
the load balancer spreading requests.

## Tests

```bash
python -m pytest -q
```

Load test (with the Docker setup running):
```bash
pip install locust
```
```bash
locust -f locustfile.py --host http://localhost:8080 --users 200 --spawn-rate 20
```

## Deploy to AWS (Elastic Beanstalk, free tier eligible)

1. Install the EB CLI: `pip install awsebcli`, then `aws configure` with your IAM user keys.
2. In this folder: `eb init -p docker codealpha-buspass` (choose your region).
3. Create the environment with a Postgres database:
   `eb create buspass-prod --database.engine postgres --database.username buspass`
4. Set secrets (Beanstalk exposes the RDS settings; build `DATABASE_URL` from them):
   `eb setenv SECRET_KEY=<long random string> CONDUCTOR_KEY=<another secret> SESSION_COOKIE_SECURE=1 DATABASE_URL=postgresql://USER:PASS@HOST:5432/ebdb`
5. `eb open`. Scaling rules come from `.ebextensions/01-autoscaling.config`.

**Alternative: Google Cloud Run** (scales from 0 to N automatically per request load):
`gcloud run deploy buspass --source . --max-instances 10 --set-env-vars SECRET_KEY=...,DATABASE_URL=...`
(use Cloud SQL, or a free Postgres from Neon/Supabase, for `DATABASE_URL`).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///buspass.db` | Postgres URL in the cloud |
| `SECRET_KEY` | dev value | Signs sessions **and tickets**. Must be the same on every server and kept secret. |
| `CONDUCTOR_KEY` | `conductor-dev-key` | Key for the ticket scanner API |
| `CURRENCY` | `USD` | Display currency |
| `SESSION_COOKIE_SECURE` | off | Set to `1` behind HTTPS |

## Notes

Payment is simulated. A real deployment would plug in a payment provider (e.g. Stripe or Paymob) before
`issue_ticket` and only issue the ticket after the payment succeeds.
