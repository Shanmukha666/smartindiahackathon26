from app import rate_limit
from app.rate_limit import RateLimiter


def test_rate_limit_rejects_request_over_server_side_budget() -> None:
    limiter = RateLimiter()

    assert limiter.allow("/ask", "client-1", 2) is True
    assert limiter.allow("/ask", "client-1", 2) is True
    assert limiter.allow("/ask", "client-1", 2) is False


def test_rate_limits_are_isolated_by_route_and_client() -> None:
    limiter = RateLimiter()

    assert limiter.allow("/ask", "client-1", 1) is True
    assert limiter.allow("/retrieve", "client-1", 1) is True
    assert limiter.allow("/ask", "client-2", 1) is True


def test_expired_client_keys_are_pruned(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = RateLimiter()
    assert limiter.allow("/ask", "old-client", 1, window_seconds=10) is True
    now[0] = 111.0
    assert limiter.allow("/ask", "new-client", 1, window_seconds=10) is True
    assert ("/ask", "old-client") not in limiter._events
