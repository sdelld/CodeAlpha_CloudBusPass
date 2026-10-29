"""High-traffic load test.

    pip install locust
    locust -f locustfile.py --host http://localhost:8080 --users 200 --spawn-rate 20

Open http://localhost:8089 to watch requests/sec and latency while you scale the app tier.
"""

import random
import re
import uuid

from locust import HttpUser, between, task


class Passenger(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.client.get("/register")
        token = self._csrf("/register")
        self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": "Load Tester",
                "email": f"load-{uuid.uuid4().hex[:12]}@example.com",
                "password": "password123",
            },
        )

    def _csrf(self, path):
        html = self.client.get(path, name=path).text
        m = re.search(r'name="csrf_token" value="([^"]+)"', html)
        return m.group(1) if m else ""

    @task(5)
    def browse_routes(self):
        self.client.get("/api/routes")

    @task(3)
    def get_quote(self):
        self.client.get(f"/api/quote?route_id={random.randint(1, 6)}&pass_type=single", name="/api/quote")

    @task(1)
    def book(self):
        html = self.client.get("/book").text
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        key = re.search(r'name="idempotency_key" value="([^"]+)"', html).group(1)
        day = re.search(r'name="travel_date"[^>]*value="([^"]+)"', html).group(1)
        self.client.post(
            "/book",
            data={
                "csrf_token": token,
                "idempotency_key": key,
                "route_id": random.randint(1, 6),
                "pass_type": random.choice(["single", "day", "weekly"]),
                "travel_date": day,
            },
        )
