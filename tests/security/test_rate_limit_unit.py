from app.core.rate_limit import InMemoryRateLimiter


def test_in_memory_rate_limiter_blocks_after_limit() -> None:
    limiter = InMemoryRateLimiter()
    assert limiter.allow("user", 2)
    assert limiter.allow("user", 2)
    assert not limiter.allow("user", 2)
