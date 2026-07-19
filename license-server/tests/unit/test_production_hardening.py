from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.errors import ErrorCode, LicenseServiceError
from app.core.rate_limiting import ApplicationRateLimiter, LimitRule


@pytest.mark.asyncio
async def test_rate_limiter_rejects_the_first_request_over_the_limit() -> None:
    limiter = ApplicationRateLimiter()
    rule = LimitRule("login", "client", 2, 60)
    await limiter._consume(rule)
    await limiter._consume(rule)
    with pytest.raises(LicenseServiceError) as error:
        await limiter._consume(rule)
    assert error.value.code == ErrorCode.RATE_LIMITED
    assert error.value.retryable is True


def test_trial_activation_has_ip_and_device_rate_limits() -> None:
    request = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/v1/trials/activate"),
    )
    rules = ApplicationRateLimiter._rules(
        request,
        b'{"deviceId":"device-id-never-stored-in-rule-name"}',
        "127.0.0.1",
    )
    assert {rule.namespace for rule in rules} == {
        "trial-activate-ip",
        "trial-activate-device",
    }
    assert all("device-id-never-stored" not in rule.key for rule in rules)
