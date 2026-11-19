import unittest

from fastapi import HTTPException
from starlette.requests import Request

import app as app_module
from nepse_analyst.rate_limit import SlidingWindowLimiter, retry_after_header


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SlidingWindowLimiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.limiter = SlidingWindowLimiter([(3, 60.0), (5, 3600.0)], clock=self.clock)

    def test_allows_up_to_the_limit_then_refuses(self) -> None:
        self.assertEqual([self.limiter.hit("a") for _ in range(3)], [None, None, None])
        self.assertAlmostEqual(self.limiter.hit("a"), 60.0)

    def test_window_slides(self) -> None:
        for offset in (0, 10, 20):
            self.clock.now = 1000 + offset
            self.limiter.hit("a")
        self.clock.now = 1030
        self.assertAlmostEqual(self.limiter.hit("a"), 30.0)  # the request at t=1000 leaves at 1060
        self.clock.now = 1060.5
        self.assertIsNone(self.limiter.hit("a"))

    def test_longer_window_applies_after_the_short_one_resets(self) -> None:
        for minute in range(2):
            self.clock.now = 1000 + minute * 61
            for _ in range(3 if minute == 0 else 2):
                self.assertIsNone(self.limiter.hit("a"))
        self.clock.now = 1000 + 2 * 61
        retry = self.limiter.hit("a")
        self.assertIsNotNone(retry)
        self.assertGreater(retry, 60)  # waiting for the hourly window, not the minute one

    def test_refused_requests_are_not_counted(self) -> None:
        for _ in range(3):
            self.limiter.hit("a")
        for _ in range(10):
            self.limiter.hit("a")
        self.clock.now += 60.1
        self.assertEqual([self.limiter.hit("a") for _ in range(2)], [None, None])

    def test_clients_are_counted_separately(self) -> None:
        for _ in range(3):
            self.limiter.hit("a")
        self.assertIsNotNone(self.limiter.hit("a"))
        self.assertIsNone(self.limiter.hit("b"))

    def test_zero_disables_a_window(self) -> None:
        limiter = SlidingWindowLimiter([(0, 60.0), (0, 86400.0)], clock=self.clock)
        self.assertTrue(all(limiter.hit("a") is None for _ in range(1000)))

    def test_idle_clients_are_pruned(self) -> None:
        limiter = SlidingWindowLimiter([(3, 60.0)], clock=self.clock, max_clients=2)
        limiter.hit("a")
        limiter.hit("b")
        self.clock.now += 120
        limiter.hit("c")
        self.assertEqual(set(limiter._events), {"c"})

    def test_retry_after_header_rounds_up(self) -> None:
        self.assertEqual(retry_after_header(0.2), "1")
        self.assertEqual(retry_after_header(30.01), "31")


def _request(host: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/chat", "headers": [], "client": (host, 5000)})


class ChatRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = app_module.chat_limiter
        app_module.chat_limiter = SlidingWindowLimiter([(2, 60.0)], clock=FakeClock())

    def tearDown(self) -> None:
        app_module.chat_limiter = self.original

    def test_chat_route_applies_the_rate_limit(self) -> None:
        route = next(r for r in app_module.app.routes if getattr(r, "path", None) == "/api/chat")
        calls = [d.call for d in route.dependant.dependencies]
        self.assertIn(app_module.enforce_chat_rate_limit, calls)

    def test_over_the_limit_returns_429_with_retry_after(self) -> None:
        app_module.enforce_chat_rate_limit(_request("203.0.113.5"))
        app_module.enforce_chat_rate_limit(_request("203.0.113.5"))
        with self.assertRaises(HTTPException) as ctx:
            app_module.enforce_chat_rate_limit(_request("203.0.113.5"))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers["Retry-After"], "60")
        app_module.enforce_chat_rate_limit(_request("198.51.100.7"))  # another client is unaffected

    def test_forwarded_header_is_not_trusted_by_the_app(self) -> None:
        spoofed = Request({
            "type": "http", "method": "POST", "path": "/api/chat",
            "headers": [(b"x-forwarded-for", b"1.2.3.4")], "client": ("203.0.113.5", 5000),
        })
        self.assertEqual(app_module.client_key(spoofed), "203.0.113.5")


if __name__ == "__main__":
    unittest.main()
