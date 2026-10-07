import asyncio
import time

from opportunity_radar.utilities.rate_limit import API_HOST_LIMITS, DomainGate, RateLimiter


async def test_default_domain_is_one_at_a_time():
    limiter = RateLimiter(max_global=8, min_domain_interval=1.0)
    gate = limiter.gate_for("careers.example.com")
    assert gate.max_concurrent == 1
    assert gate.min_interval_seconds == 1.0


async def test_api_hosts_get_parallel_slots():
    limiter = RateLimiter(max_global=8, min_domain_interval=1.0)
    gate = limiter.gate_for("boards-api.greenhouse.io")
    slots, interval = API_HOST_LIMITS["boards-api.greenhouse.io"]
    assert gate.max_concurrent == slots > 1
    assert gate.min_interval_seconds == interval


async def test_gate_bounds_concurrency_and_spaces_starts():
    gate = DomainGate(min_interval_seconds=0.05, max_concurrent=2)
    active = 0
    peak = 0
    starts: list[float] = []

    async def worker():
        nonlocal active, peak
        async with gate:
            starts.append(time.monotonic())
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak == 2
    gaps = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:], strict=False)]
    assert all(gap >= 0.045 for gap in gaps)
