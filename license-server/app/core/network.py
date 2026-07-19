from __future__ import annotations

from ipaddress import ip_address

from fastapi import Request


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return None


def resolve_client_ip(request: Request, trusted_proxy_count: int) -> str | None:
    direct = _valid_ip(request.client.host if request.client else None)
    if trusted_proxy_count <= 0:
        return direct

    forwarded = [
        value.strip()
        for value in request.headers.get("x-forwarded-for", "").split(",")
        if value.strip()
    ]
    chain = forwarded + ([direct] if direct else [])
    if len(chain) <= trusted_proxy_count:
        return direct
    return _valid_ip(chain[-(trusted_proxy_count + 1)]) or direct
