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
