"""Demo data for Greater Cairo. Demo accounts all use the password DEMO_PASSWORD (see README)."""

import random
from datetime import UTC, datetime, time, timedelta

from .extensions import db
from .models import (
    Bus,
    Departure,
    DiscountRule,
    FavoriteRoute,
    Notification,
    Organization,
    PartnerOffer,
    Pass,
    PassType,
    Payment,
    PromoCode,
    Receipt,
    Ride,
    Route,
    RouteStop,
    SponsorBlock,
    Stop,
    User,
    WalletTransaction,
    utcnow,
)
from .security import hash_password
from .timeutil import local_today, tz

DEMO_PASSWORD = "Demo@12345"

STOPS = {
    "ramses": ("Ramses Square", "ميدان رمسيس", 30.0626, 31.2468),
    "tahrir": ("Tahrir Square", "ميدان التحرير", 30.0444, 31.2357),
    "abbassia": ("Abbassia", "العباسية", 30.0722, 31.2833),
    "azhar_uni": ("Al-Azhar University", "جامعة الأزهر", 30.0597, 31.3157),
    "city_stars": ("Nasr City – City Stars", "مدينة نصر – سيتي ستارز", 30.0731, 31.3456),
    "korba": ("Heliopolis – Korba", "مصر الجديدة – الكوربة", 30.0911, 31.3225),
    "airport": ("Cairo Airport T3", "مطار القاهرة مبنى 3", 30.1114, 31.4006),
    "maadi": ("Maadi", "المعادي", 29.9602, 31.2569),
    "dokki": ("Dokki", "الدقي", 30.0385, 31.2123),
    "cairo_uni": ("Cairo University", "جامعة القاهرة", 30.0276, 31.2101),
    "giza": ("Giza Square", "ميدان الجيزة", 30.0131, 31.2089),
    "zayed": ("Sheikh Zayed", "الشيخ زايد", 30.0441, 30.9765),
    "smart_village": ("Smart Village", "القرية الذكية", 30.0717, 31.0167),
    "hosary": ("6th of October – Hosary", "6 أكتوبر – الحصري", 29.9737, 30.9441),
    "ninety": ("Fifth Settlement – 90th St", "التجمع الخامس – شارع التسعين", 30.0283, 31.4703),
    "auc": ("New Cairo – AUC", "القاهرة الجديدة – الجامعة الأمريكية", 30.0198, 31.4996),
}

ROUTES = [
    # code, en, ar, color, fare (piastres), [(stop, minute)], first, last, every (min)
    (
        "R1",
        "Ramses – Cairo University",
        "رمسيس – جامعة القاهرة",
        "#2563eb",
        1200,
        [("ramses", 0), ("tahrir", 9), ("dokki", 18), ("cairo_uni", 25), ("giza", 32)],
        "06:00",
        "22:00",
        20,
    ),
    (
        "R2",
        "Tahrir – Cairo Airport",
        "التحرير – مطار القاهرة",
        "#7c3aed",
        3500,
        [("tahrir", 0), ("abbassia", 14), ("korba", 28), ("airport", 45)],
        "05:30",
        "23:30",
        30,
    ),
    (
        "R3",
        "Ramses – New Cairo (AUC)",
        "رمسيس – القاهرة الجديدة",
        "#059669",
        2500,
        [("ramses", 0), ("abbassia", 10), ("azhar_uni", 20), ("city_stars", 30), ("ninety", 50), ("auc", 58)],
        "06:30",
        "21:30",
        15,
    ),
    (
        "R4",
        "Giza – 6th of October",
        "الجيزة – 6 أكتوبر",
        "#d97706",
        2000,
        [("giza", 0), ("zayed", 30), ("smart_village", 40), ("hosary", 55)],
        "06:00",
        "21:00",
        30,
    ),
    (
        "R5",
        "Maadi – Ramses",
        "المعادي – رمسيس",
        "#dc2626",
        1000,
        [("maadi", 0), ("tahrir", 22), ("ramses", 32)],
        "06:00",
        "23:00",
        15,
    ),
    (
        "R6",
        "Heliopolis – AUC Campus Shuttle",
        "مصر الجديدة – شاتل الجامعة الأمريكية",
        "#0891b2",
        1800,
        [("korba", 0), ("city_stars", 15), ("ninety", 35), ("auc", 42)],
        "07:00",
        "19:00",
        30,
    ),
]

PASS_TYPES = [
    ("single", "Single ride", "تذكرة رحلة واحدة", 1, 1, 1, 1, False, 0),
    ("daily", "Day pass", "اشتراك يومي", 5, 2, 1, None, True, 1),
    ("weekly", "Weekly pass", "اشتراك أسبوعي", 12, 1, 7, None, True, 2),
    ("monthly", "Monthly pass", "اشتراك شهري", 40, 1, 30, None, True, 3),
    ("semester", "Semester pass", "اشتراك فصل دراسي", 140, 1, 120, None, True, 4),
]

PLATE_LETTERS = ["أ ب ج", "س ط ر", "ق ص م", "ن هـ و", "ع ف ل", "ك ي د"]
FIRST = [
    "Ahmed",
    "Mohamed",
    "Mahmoud",
    "Omar",
    "Youssef",
    "Mostafa",
    "Karim",
    "Hassan",
    "Ali",
    "Amr",
    "Nour",
    "Mariam",
    "Salma",
    "Yasmin",
    "Habiba",
    "Farida",
    "Menna",
    "Aya",
    "Rana",
    "Laila",
]
LAST = ["Hassan", "Ibrahim", "Mahmoud", "El-Sayed", "Abdelrahman", "Farouk", "Mansour", "Saleh", "Kamel", "Fathy"]


def _times(first, last, every):
    h, m = map(int, first.split(":"))
    end_h, end_m = map(int, last.split(":"))
    t, end, out = h * 60 + m, end_h * 60 + end_m, []
    while t <= end:
        out.append(f"{t // 60:02d}:{t % 60:02d}")
        t += every
    return out


def _utc(day, hour, minute):
    return datetime.combine(day, time(hour, minute), tzinfo=tz()).astimezone(UTC).replace(tzinfo=None)


def seed_demo(n_riders=120, days=30, rng_seed=7):
    rng = random.Random(rng_seed)
    today = local_today()
    pw = hash_password(DEMO_PASSWORD)

    stops = {k: Stop(name_en=v[0], name_ar=v[1], lat=v[2], lng=v[3]) for k, v in STOPS.items()}
    db.session.add_all(stops.values())
    routes = {}
    for code, en, ar, color, fare, path, first, last, every in ROUTES:
        r = Route(code=code, name_en=en, name_ar=ar, color=color, base_fare_cents=fare, daily_single_capacity=300)
        r.stops = [RouteStop(stop=stops[s], seq=i, minutes_from_start=m) for i, (s, m) in enumerate(path)]
        r.departures = [Departure(time=t) for t in _times(first, last, every)]
        routes[code] = r
    db.session.add_all(routes.values())

    types = {}
    for code, en, ar, num, den, days_valid, max_rides, discountable, sort in PASS_TYPES:
        types[code] = PassType(
            code=code,
            name_en=en,
            name_ar=ar,
            multiplier_num=num,
            multiplier_den=den,
            validity_days=days_valid,
            max_rides=max_rides,
            discountable=discountable,
            sort=sort,
        )
    db.session.add_all(types.values())
    db.session.add_all([DiscountRule(code="student", percent=40), DiscountRule(code="senior", percent=50)])
    db.session.add_all(
        [
            PromoCode(code="WELCOME20", kind="percent", value=20, max_uses=1000),
            PromoCode(code="CAMPUS50", kind="fixed", value=5000, max_uses=200),
            PromoCode(code="SUMMER10", kind="percent", value=10, expires_at=utcnow() - timedelta(days=30)),
        ]
    )

    buses = []
    for i, code in enumerate(routes):
        for _ in range(3):
            buses.append(
                Bus(
                    plate=f"{PLATE_LETTERS[i]} {rng.randint(1000, 9999)}",
                    route=routes[code],
                    capacity=rng.choice([30, 45, 50]),
                )
            )
    db.session.add_all(buses)

    cu = Organization(name="Cairo University", kind="university", email_domain="cu.test")
    acme = Organization(name="Nile Tech Park", kind="company", email_domain="niletech.test")
    db.session.add_all([cu, acme])

    def user(email, name, role="rider", **kw):
        u = User(email=email, name=name, role=role, password_hash=pw, status="active", **kw)
        db.session.add(u)
        return u

    admin = user("admin@cloudbus.test", "Operations Admin", "admin")
    validator = user("validator@cloudbus.test", "Hassan the Conductor", "validator")
    user("validator2@cloudbus.test", "Mona the Conductor", "validator")
    rider = user("rider@cloudbus.test", "Omar Rider", balance_cents=25000)
    student = user(
        "student@cu.test",
        "Salma Student",
        discount_type="student",
        discount_status="approved",
        balance_cents=8000,
        organization=cu,
    )
    user(
        "senior@cloudbus.test", "Mahmoud Senior", discount_type="senior", discount_status="pending", balance_cents=5000
    )
    sponsor = user("sponsor@cu.test", "CU Transport Office", "sponsor", organization=cu)
    db.session.flush()

    db.session.add(
        SponsorBlock(
            organization=cu,
            route=routes["R1"],
            pass_type=types["monthly"],
            seats_total=200,
            seats_used=0,
            invite_code="CUFALL26",
            status="active",
        )
    )
    db.session.add_all(
        [
            PartnerOffer(
                partner="Cilantro Café",
                title_en="15% off coffee",
                title_ar="خصم 15% على القهوة",
                body_en="Show your active pass at any Cilantro near a CloudBus stop.",
                body_ar="اعرض اشتراكك الساري في أي فرع سيلانترو قريب من محطة كلاود باص.",
            ),
            PartnerOffer(
                partner="Gold's Gym",
                title_en="Free week trial",
                title_ar="أسبوع مجاني",
                body_en="Monthly pass holders get a free week at Gold's Gym Nasr City.",
                body_ar="أصحاب الاشتراك الشهري يحصلون على أسبوع مجاني في جولدز جيم مدينة نصر.",
            ),
            PartnerOffer(
                partner="Vodafone",
                title_en="5 GB bonus",
                title_ar="5 جيجا هدية",
                body_en="Top up 200 EGP or more and get 5 GB on Vodafone.",
                body_ar="اشحن 200 جنيه أو أكثر واحصل على 5 جيجا من فودافون.",
            ),
        ]
    )

    # Active passes for the demo riders.
    demo_pass = Pass(
        user=rider,
        route=routes["R3"],
        pass_type=types["monthly"],
        valid_from=today - timedelta(days=5),
        valid_until=today + timedelta(days=24),
        price_cents=40 * 2500,
        auto_renew=True,
    )
    student_pass = Pass(
        user=student,
        route=routes["R1"],
        pass_type=types["semester"],
        valid_from=today - timedelta(days=20),
        valid_until=today + timedelta(days=99),
        price_cents=140 * 1200 * 60 // 100,
        discount_cents=140 * 1200 * 40 // 100,
    )
    db.session.add_all(
        [
            demo_pass,
            student_pass,
            FavoriteRoute(user_id=rider.id, route_id=routes["R3"].id),
            FavoriteRoute(user_id=rider.id, route_id=routes["R2"].id),
        ]
    )
    db.session.add(
        Notification(
            user_id=rider.id,
            kind="account",
            title="Welcome to CloudBus Pass",
            body="Your monthly pass on R3 is ready. Tap Pass to show your QR code.",
        )
    )
    db.session.flush()
    _receipt(
        rider.id,
        "Monthly pass — R3 Ramses – New Cairo (AUC)",
        demo_pass.price_cents,
        "wallet",
        _utc(today - timedelta(days=5), 8, 3),
        pass_id=demo_pass.id,
    )

    # Synthetic history so the analytics dashboard has realistic shapes.
    route_list = list(routes.values())
    weights = [5, 3, 6, 2, 4, 2]
    peak_hours = [6, 7, 7, 8, 8, 8, 9, 12, 13, 15, 16, 16, 17, 17, 18, 19, 21]
    riders = []
    for i in range(n_riders):
        created = today - timedelta(days=rng.randint(0, 60))
        u = User(
            name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            email=f"rider{i:03d}@example.test",
            role="rider",
            status="active",
            password_hash=pw,
            created_at=_utc(created, rng.randint(7, 22), rng.randint(0, 59)),
            balance_cents=rng.choice([0, 0, 2000, 5000, 15000]),
            discount_type="student" if i % 4 == 0 else "none",
            discount_status="approved" if i % 4 == 0 else "none",
        )
        riders.append(u)
    db.session.add_all(riders)
    db.session.flush()

    for u in riders:
        if rng.random() < 0.3:
            continue  # signed up, never bought (feeds the conversion KPI)
        route = rng.choices(route_list, weights)[0]
        product = rng.choices(["daily", "weekly", "monthly", "semester"], [3, 4, 6, 1])[0]
        pt = types[product]
        start = today - timedelta(days=rng.randint(0, days))
        price = route.base_fare_cents * pt.multiplier_num // pt.multiplier_den
        if u.discount_status == "approved":
            price = price * 60 // 100
        p = Pass(
            user=u,
            route=route,
            pass_type=pt,
            valid_from=start,
            valid_until=start + timedelta(days=pt.validity_days - 1),
            price_cents=price,
            status="active" if start + timedelta(days=pt.validity_days - 1) >= today else "expired",
            auto_renew=product == "monthly" and rng.random() < 0.4,
        )
        db.session.add(p)
        db.session.flush()
        bought_at = _utc(start, rng.randint(6, 22), rng.randint(0, 59))
        method = rng.choice(["card", "card", "wallet"])
        pay_id = None
        if method == "card":
            pay = Payment(
                user_id=u.id,
                purpose="pass",
                amount_cents=price,
                currency="EGP",
                provider="mock",
                provider_ref=f"mock_seed_{p.id[:10]}",
                status="succeeded",
                idempotency_key=f"seed-{p.id}",
                meta={"description": f"{pt.name_en} — {route.code}"},
                created_at=bought_at,
                completed_at=bought_at,
            )
            db.session.add(pay)
            db.session.flush()
            pay_id = p.payment_id = pay.id
        _receipt(
            u.id,
            f"{pt.name_en} — {route.code} {route.name_en}",
            price,
            method,
            bought_at,
            pass_id=p.id,
            payment_id=pay_id,
        )
        bus_choices = [b for b in buses if b.route is route]
        last_day = min(today, p.valid_until)
        day = start
        while day <= last_day:
            if day.weekday() != 4 and rng.random() < 0.75:  # fewer rides on Fridays
                for _ in range(rng.choice([1, 2, 2])):
                    hour = rng.choice(peak_hours)
                    db.session.add(
                        Ride(
                            pass_id=p.id,
                            user_id=u.id,
                            validator_id=validator.id,
                            bus=rng.choice(bus_choices),
                            route=route,
                            result="valid",
                            scanned_at=_utc(day, hour, rng.randint(0, 59)),
                        )
                    )
            day += timedelta(days=1)

    # Pay-per-ride wallet scans + a sprinkling of rejected scans (fraud/expired) for the scan-result chart.
    for _ in range(400):
        u = rng.choice(riders)
        route = rng.choices(route_list, weights)[0]
        when = _utc(today - timedelta(days=rng.randint(0, days - 1)), rng.choice(peak_hours), rng.randint(0, 59))
        result = rng.choices(["valid", "expired", "fraud", "insufficient_funds"], [90, 5, 2, 3])[0]
        db.session.add(
            Ride(
                user_id=u.id,
                validator_id=validator.id,
                bus=rng.choice([b for b in buses if b.route is route]),
                route=route,
                result=result,
                scanned_at=when,
                fare_cents=route.base_fare_cents if result == "valid" else 0,
                reason=None
                if result == "valid"
                else {
                    "expired": "Pass expired.",
                    "fraud": "Code is too old — likely a screenshot.",
                    "insufficient_funds": "Not enough wallet balance.",
                }[result],
            )
        )
    db.session.add(
        WalletTransaction(
            user_id=rider.id, amount_cents=25000, kind="topup", reference="seed", balance_after_cents=25000
        )
    )
    db.session.commit()
    return {
        "routes": len(routes),
        "buses": len(buses),
        "riders": n_riders + 3,
        "demo_accounts": [
            "admin@cloudbus.test",
            "validator@cloudbus.test",
            "rider@cloudbus.test",
            "student@cu.test",
            "senior@cloudbus.test",
            "sponsor@cu.test",
        ],
        "password": DEMO_PASSWORD,
        "sponsor_invite_code": "CUFALL26",
        "admin_id": admin.id,
        "sponsor_id": sponsor.id,
    }


_receipt_counter = [0]


def _receipt(user_id, description, amount, method, when, pass_id=None, payment_id=None):
    _receipt_counter[0] += 1
    db.session.add(
        Receipt(
            number=f"CB-{when.year}-S{_receipt_counter[0]:05d}",
            user_id=user_id,
            description=description,
            amount_cents=amount,
            method=method,
            created_at=when,
            pass_id=pass_id,
            payment_id=payment_id,
        )
    )
