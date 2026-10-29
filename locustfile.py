"""Load test against the v1 API (run with the docker-compose stack, demo data loaded).

    pip install locust
    locust -f locustfile.py --host http://localhost:8080 --users 200 --spawn-rate 20

Riders browse routes, get quotes and open their passes; conductors validate scans.
Rate limits are per client IP, so run with RATELIMIT_ENABLED=0 (or from several machines) for big loads.
"""

import random
import uuid

from locust import HttpUser, between, task

PASSWORD = "Demo@12345"


class Rider(HttpUser):
    weight = 5
    wait_time = between(1, 3)

    def on_start(self):
        r = self.client.post("/api/v1/auth/login", json={"identifier": "rider@cloudbus.test", "password": PASSWORD})
        self.headers = {"Authorization": f"Bearer {r.json().get('access_token', '')}"}

    @task(5)
    def routes(self):
        self.client.get("/api/v1/routes")

    @task(3)
    def quote(self):
        self.client.get(f"/api/v1/passes/quote?route_id={random.randint(1, 6)}&pass_type=monthly", name="/passes/quote")

    @task(3)
    def live(self):
        self.client.get(f"/api/v1/routes/{random.randint(1, 6)}/live", name="/routes/:id/live")

    @task(4)
    def my_passes(self):
        self.client.get("/api/v1/passes", headers=self.headers)

    @task(1)
    def buy_daily(self):
        self.client.post(
            "/api/v1/passes",
            headers=self.headers,
            name="/passes [buy]",
            json={"route_id": 5, "pass_type": "single", "idempotency_key": uuid.uuid4().hex},
        )


class Conductor(HttpUser):
    weight = 1
    wait_time = between(0.5, 2)

    def on_start(self):
        r = self.client.post("/api/v1/auth/login", json={"identifier": "validator@cloudbus.test", "password": PASSWORD})
        self.headers = {"Authorization": f"Bearer {r.json().get('access_token', '')}"}
        buses = self.client.get("/api/v1/validator/buses", headers=self.headers).json().get("items", [])
        self.bus_id = buses[0]["id"] if buses else 1

    @task
    def scan(self):
        # Unknown codes still exercise the full validation path (parse, lookup, audit write).
        self.client.post(
            "/api/v1/validator/scan",
            headers=self.headers,
            name="/validator/scan",
            json={"token": f"CB1.P.{uuid.uuid4().hex}.1.{'0' * 20}", "bus_id": self.bus_id},
        )
