# CloudBus Pass — Business Model

**One-liner:** CloudBus Pass replaces paper bus tickets with a phone wallet and rotating QR passes, so riders
never queue for tickets, operators stop losing fare revenue to fraud, and universities and companies can
sponsor commuting for thousands of people from one dashboard.

**Launch market:** Egypt (Greater Cairo intercity & campus shuttles). Currency EGP. Arabic + English.

## Problem
- Riders queue for paper tickets and lose them; monthly cards are shared with friends.
- Operators lose an estimated 5–15% of fare revenue to cash leakage, re-used tickets and wrong pricing,
  and have no data on which routes and hours are full.
- Universities and companies subsidise transport but have no way to see who actually uses it.

## User roles

| Role | Who | Main job |
|---|---|---|
| **Rider** | Commuters, students, seniors | Buy/renew passes, pay per ride from wallet, show pass, track buses |
| **Validator** | Bus driver or conductor | Scan rider QR codes, see valid/expired/fraud instantly, work offline |
| **Operator / Admin** | Bus company staff | Manage routes, stops, buses, fares, pass types, discounts, users, refunds; see analytics |
| **Sponsor** | University or company HR | Buy bulk seats, invite members, see utilisation |

## Revenue streams

| Stream | How it works | Who pays |
|---|---|---|
| Pass subscriptions | Daily / weekly / monthly / semester passes per route; optional auto-renew | Rider |
| Pay-per-ride wallet | Top up wallet, each scan deducts the single fare (cheaper than cash) | Rider |
| Student & senior discounts | 40% / 50% off after document verification — drives volume, partly subsidised by sponsors | Rider |
| B2B bulk passes | Universities/companies buy seats at volume pricing and hand out invite codes | Sponsor |
| Operator SaaS fee | Per-bus monthly fee + 2.5% of fares processed through the platform | Operator |
| In-app ads / partner offers | Cafés, gyms, telecoms near stops promote offers on the rider home screen | Partner |

## Pricing tiers (rider-facing, per route)

Base single fare **F** is set per route by the operator (seed data: 12–40 EGP).

| Product | Price | Validity | Rides |
|---|---|---|---|
| Pay-per-ride (wallet) | 1 × F | single trip | 1 |
| Daily pass | 2.5 × F | 1 day | unlimited on route |
| Weekly pass | 12 × F | 7 days | unlimited on route |
| Monthly pass | 40 × F | 30 days | unlimited on route |
| Semester pass | 140 × F | 120 days | unlimited on route |

| Discount | Rule |
|---|---|
| Student | −40% on passes, after student-ID verification |
| Senior (60+) | −50% on passes, after ID verification |
| Promo codes | Percent or fixed amount, max uses, expiry |
| Sponsor seats | 100% covered by sponsor (rider pays nothing) |

**B2B / operator pricing**

| Plan | Price | Includes |
|---|---|---|
| Sponsor — Campus | 30 × F per seat per month, min 100 seats | invite codes, utilisation report |
| Sponsor — Enterprise | custom (volume) | SSO, monthly invoicing, dedicated support |
| Operator — Starter | 400 EGP / bus / month + 2.5% of fares | validator app, rider app, dashboard |
| Operator — Pro | 700 EGP / bus / month + 1.5% of fares | + live tracking, API access, priority support |

## KPIs

| KPI | Definition | Target (month 6) |
|---|---|---|
| MAU | Riders with ≥ 1 scan or purchase in 30 days | 25,000 |
| Conversion | Sign-ups that buy a pass or top up within 7 days | 45% |
| Churn | Monthly-pass holders who do not renew within 7 days of expiry | < 20% |
| Rides / day | Validated scans per day | 30,000 |
| ARPU | Rider revenue / MAU per month | 180 EGP |
| Fraud rate | Scans rejected as fraud / total scans | < 0.5% |
| Validation time | Scan to result shown | < 1 s p95 |

All KPIs except MAU growth targets are computed by the admin analytics dashboard from live data.

## Use cases, user stories and acceptance criteria

### Rider
| ID | Story | Acceptance criteria |
|---|---|---|
| R1 | As a rider I sign up with email or phone and verify with a one-time code | OTP is 6 digits, expires in 5 min, max 5 attempts; account usable right after verification; password ≥ 8 chars |
| R2 | As a rider I log in with password or OTP | Wrong password limited to 10/min per IP; suspended users are refused with a clear message |
| R3 | As a student/senior I upload my ID to get a discount | Upload jpg/png/pdf ≤ 5 MB; status pending → approved/rejected by admin; approved discount applied automatically to pass prices |
| R4 | As a rider I buy a pass for a route | Price is computed server-side incl. discount and promo; payment via wallet or card; pass active immediately; receipt created; notification sent |
| R5 | As a rider I top up my wallet | Amounts 20–5,000 EGP; card payment through provider; balance updated only after payment confirmation (webhook), never twice for one payment |
| R6 | As a rider I turn on auto-renew | On expiry day the pass is renewed from wallet; if balance is insufficient, the rider is notified and auto-renew pauses |
| R7 | As a rider I apply a promo code | Invalid/expired/used-up codes show an inline error; discount visible before paying |
| R8 | As a rider I show my pass | ≤ 3 taps from opening the app; QR changes every 30 s; still works offline until the pass expires |
| R9 | As a rider I browse routes, stops, schedules and see where the bus is | Route list, stop list in order, departures, live bus position and ETA (simulated feed); can favourite routes |
| R10 | As a rider I see my trip history, receipts and notifications | Lists paginated; empty states explain what to do |
| R11 | As a rider I contact support | Form with category + message; ticket visible in admin |
| R12 | As a rider I use the app in Arabic or English, light or dark | Full RTL layout in Arabic; choice remembered |

### Validator
| ID | Story | Acceptance criteria |
|---|---|---|
| V1 | As a validator I log in with my own account | Only users with the validator role can scan |
| V2 | As a validator I scan a QR with the phone camera (or type the code) | Result in < 1 s: **VALID** (green, passenger name, product), **EXPIRED** (amber), **FRAUD/INVALID** (red, reason) |
| V3 | As a validator I can keep scanning without internet | Scans are queued on the device and synced when online; results of synced scans are shown |
| V4 | As an operator I need every scan audited | Each scan stores validator, bus/route, time, result and reason |

Fraud rules: forged signature, expired token (> 30 s old + grace), replayed token, pass revoked/suspended,
anti-passback (same pass scanned on a different bus within 10 min), wrong route.

### Operator / Admin
| ID | Story | Acceptance criteria |
|---|---|---|
| A1 | Manage routes, stops, buses, fares | CRUD with validation; changes audited |
| A2 | Manage pass types and discounts/promo codes | Price multipliers, validity days, active flag; promo limits/expiry |
| A3 | Manage users | Search, change role, suspend/unsuspend, approve verification documents |
| A4 | See analytics | Revenue per day, active passes, rides per route, peak hours, KPI tiles |
| A5 | Refund a payment | Refund to wallet (instant) or to card via provider; pass cancelled; audited |
| A6 | Export data | CSV export of payments, rides, users |
| A7 | Audit log | Every admin action and every scan recorded with actor and time |
| A8 | Post a service alert (delay) | Riders with that route in favourites or an active pass get a notification |

### Sponsor (university / company)
| ID | Story | Acceptance criteria |
|---|---|---|
| S1 | As a sponsor admin I buy N seats of a monthly pass on a route | Paid via card provider; seats added to organisation |
| S2 | I share an invite code with members | Members redeem the code in the rider app and get a free pass; seats decrease; optional email-domain restriction |
| S3 | I see utilisation | Seats used vs. bought, rides by members |

## Go-to-market
1. Pilot with one university shuttle operator (campus routes, sponsor pays) — fastest path to daily usage.
2. Expand to the operator's public intercity routes (riders pay).
3. Sell the operator SaaS to other bus companies.
