# Roadmap

Priorities: **P0** = must ship for the investor demo · **P1** = should ship · **P2** = nice to have.
Status reflects the end of this rebuild (✅ done · 🟡 partial/mocked · ⬜ not started).

## P0 — Must
| Item | Fixes | Status |
|---|---|---|
| Layered architecture: `api/v1` → `services` → `repositories`, app factory, config from env | maintainability | ✅ |
| Versioned REST API `/api/v1` with OpenAPI + Swagger UI, consistent error format | validation | ✅ |
| JWT access + refresh tokens (rotation, revocation), roles: rider / validator / admin / sponsor | S4, S6 | ✅ |
| Argon2 password hashing, rate limiting on auth + scanning, input validation on every endpoint | S1, validation | ✅ |
| Refuse to start in production without real secrets | S2 | ✅ |
| Database migrations (Alembic) + realistic seed data for every role | maintainability | ✅ |
| Rotating, HMAC-signed, short-lived QR tokens + anti-passback | B1, B6 | ✅ |
| Per-validator accounts with audit trail of every scan | S3 | ✅ |
| Pass products: daily / weekly / monthly / semester, buy + renew | features | ✅ |
| Wallet with ledger, top-up, pay-per-ride | features | ✅ |
| Payment provider interface: mock (default), Stripe test mode, Paymob/Fawry-ready adapters; idempotent webhooks | features | ✅ (Paymob/Fawry 🟡 adapter skeletons) |
| Local timezone (Africa/Cairo by default) for all validity dates | B3 | ✅ |
| Rider app: bottom tabs, pass in ≤ 3 taps, loading/empty/error/success states | UX | ✅ |
| Validator app: camera QR scanner + manual entry, clear valid/expired/fraud result | UX | ✅ |
| Admin dashboard: routes, stops, buses, fares, pass types, discounts, users | S4 | ✅ |
| Landing page: hero, how it works, pricing, for universities/companies, FAQ, CTA | business | ✅ |
| Unit + integration + E2E tests, lint config | quality | ✅ |

## P1 — Should
| Item | Status |
|---|---|
| Email/phone OTP login (console/log delivery adapter; SMS/email provider pluggable) | 🟡 delivery mocked |
| Student / senior verification upload + admin approval → automatic discount | ✅ |
| Promo codes (percent/fixed, limits, expiry) | ✅ |
| Auto-renew from wallet (`flask renew-passes` job) | ✅ |
| Receipts per payment | ✅ |
| Notifications: payment success, pass expiring, service delays | ✅ in-app (push/SMS ⬜) |
| Routes & stops browser, schedules, favourite routes | ✅ |
| Live bus location | 🟡 simulated feed (GPS integration ⬜) |
| Trip history, support/feedback form | ✅ |
| English + Arabic with full RTL, dark mode | ✅ |
| Validator offline queue that syncs | ✅ |
| Admin analytics charts (revenue, active passes, rides per route, peak hours) | ✅ |
| Refunds, user suspension, audit log, CSV export | ✅ |
| Corporate / university sponsor portal: bulk seats + invite codes | ✅ |

## P2 — Nice
| Item | Status |
|---|---|
| Offline signature verification on validator devices (asymmetric Ed25519 credential) | ⬜ |
| Real push notifications (Web Push / FCM) and SMS OTP (Twilio / Vonage / local Egyptian gateway) | ⬜ |
| Real GPS feed (GTFS-Realtime) instead of simulated buses | ⬜ |
| Native mobile apps (the rider web app is installable-ready but not a PWA yet) | ⬜ |
| Seat reservation per trip for intercity routes | ⬜ |
| Operator multi-tenancy (one deployment serving several bus companies — the SaaS model) | ⬜ |
| Partner offers marketplace with tracking | 🟡 static offers shown in app |
