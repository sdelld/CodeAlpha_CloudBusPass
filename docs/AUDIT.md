# Audit — CloudBus Pass (v0.1, commit `b331484`)

## Stack

| Layer | Current |
|---|---|
| Frontend | Server-rendered Jinja2 templates, one CSS file, small inline JS (price quote, conductor scanner form) |
| Backend | Flask 3 app in a single `app.py` (routes + business logic mixed), `pricing.py`, `tickets.py` |
| Database | SQLAlchemy models (`User`, `Route`, `Ticket`); SQLite locally, PostgreSQL in Docker/cloud; tables created with `create_all()`, no migrations |
| Auth | Flask signed-cookie session, password hash via Werkzeug (scrypt), hand-written CSRF token |
| Hosting | Dockerfile + Gunicorn, docker-compose (Postgres + 3 app replicas + nginx), AWS Elastic Beanstalk auto-scaling config, Render blueprint |
| Tests | 14 pytest integration tests through the Flask test client |

### Folder structure
```
app.py  models.py  pricing.py  tickets.py  wsgi.py
templates/ (8 pages)  static/style.css  tests/test_app.py
Dockerfile  docker-compose.yml  nginx.conf  .ebextensions/  render.yaml  locustfile.py
```

### Current features
Sign up / log in, browse 6 seeded routes, book single / day / weekly / monthly tickets with server-side pricing,
capacity check for single rides, idempotent booking, signed QR ticket, report lost/stolen (revoke + reissue),
conductor validation API with single-use enforcement, health check.

## Bugs

| # | Severity | Finding |
|---|---|---|
| B1 | High | **Static QR code.** The QR never changes, so a screenshot of a day/weekly/monthly pass can be shared and used by several people the same day (only single rides are consumed on scan). |
| B2 | Medium | Seat capacity lock relies on `SELECT … FOR UPDATE`, which SQLite ignores, so local/dev runs can oversell under concurrency. |
| B3 | Medium | All dates use UTC. In Cairo (UTC+2/+3) a ticket bought after 22:00 local time is dated "yesterday"/"tomorrow" incorrectly; validity windows are off by hours. |
| B4 | Low | Pass "start date" for multi-day passes is chosen freely up to 30 days ahead but capacity is only counted for single rides, so passes do not reserve seats at all. |
| B5 | Low | Ticket list marks a pass "expired" in the template, but the database status stays `active` forever; reports and queries can't filter real active passes. |
| B6 | Low | `scan_count` on passes has no anti-passback: one pass can be scanned on two different buses one minute apart. |

## Security issues

| # | Severity | Finding |
|---|---|---|
| S1 | High | No rate limiting on `/login`, `/register` or `/api/validate` → password brute force and scanner key guessing are possible. |
| S2 | High | `SECRET_KEY` and `CONDUCTOR_KEY` fall back to hard-coded dev values if the env var is missing; a misconfigured deploy runs with public secrets. |
| S3 | Medium | One shared conductor key for all validators; no per-device/user identity, no audit trail of who scanned what, key can't be revoked per person. |
| S4 | Medium | No role model at all (no admin), so fares/routes can only be changed in the database by hand. |
| S5 | Medium | No account verification (email/phone), no password reset, no account lockout. |
| S6 | Low | Session cookie lifetime is the browser session; no server-side revocation of a stolen session. |
| S7 | Low | No security headers (CSP, X-Frame-Options, HSTS). |

## Missing validation
- Name/email only checked for presence and an `@`; no length limits (name could be megabytes until DB rejects).
- `route_id` accepted as any integer; non-numeric handled, but no schema validation layer; errors are flash messages only.
- API endpoints return ad-hoc JSON shapes; no consistent error format, no OpenAPI contract.
- `/api/quote` silently ignores a malformed date.

## Dead code / maintainability
- `Ticket.used_at` only set for single rides, `replaces_id` never shown in lists.
- Business logic (`book_from_form`, `seats_sold`, `issue_ticket`) lives inside `app.py` route closures → not unit-testable in isolation.
- No structured logging; errors are invisible in production.
- No migrations: any model change in production requires manual SQL.

## UX pain points
- Desktop-first layout, no bottom navigation; showing a pass takes 3–4 taps (log in → My tickets → Open).
- No loading/empty/error states except a single flash message; booking errors reload the whole page.
- No wallet, no pay-per-ride, no discounts, no renewals, no receipts, no notifications, no trip history.
- English only, no RTL/Arabic, no dark mode.
- Payment is simulated with no explanation of what would happen in production.
- Conductor scanner needs the code to be pasted; no camera scanning.

## Conclusion
The core is sound (server-side pricing, signed tickets, idempotency, stateless scaling) but it is a single-file
prototype. Moving to an investor-ready product needs: a layered architecture with a versioned API, real auth (JWT +
roles + OTP), migrations, a payment abstraction, rotating QR codes, and a proper rider/validator/admin UI.
See [ROADMAP.md](ROADMAP.md).
