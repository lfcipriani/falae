"""Access control for the HTTP API: a shared API key and an optional client IP allowlist.

Both come from the environment and are fixed per process:
  FALAE_API_KEY      required value of the X-API-Key header. Unset disables the check.
  FALAE_ALLOWED_IPS  comma-separated IPs or CIDRs, e.g. "203.0.113.7, 198.51.100.0/24".
                     Unset allows any IP.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

API_KEY_HEADER = "X-API-Key"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(value: str) -> tuple[Network, ...]:
    """'1.2.3.4, 10.0.0.0/8' -> networks. A bare IP becomes a /32 (or /128). Raises ValueError."""
    return tuple(ipaddress.ip_network(part.strip(), strict=False)
                 for part in value.split(",") if part.strip())


def client_ip(request: Request) -> str | None:
    """The caller's IP. Cloud Run's front end appends the address it saw to X-Forwarded-For,
    so the rightmost entry is the real client; anything to its left was sent by the client and
    can be forged. Without the header (local runs), use the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else None


@dataclass(frozen=True)
class AccessPolicy:
    api_key: str | None = None
    allowed_networks: tuple[Network, ...] = field(default=())

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AccessPolicy:
        env = os.environ if env is None else env
        return cls(
            api_key=env.get("FALAE_API_KEY") or None,
            allowed_networks=parse_networks(env.get("FALAE_ALLOWED_IPS", "")),
        )

    def ip_allowed(self, ip: str | None) -> bool:
        if not self.allowed_networks:
            return True
        try:
            addr = ipaddress.ip_address(ip or "")
        except ValueError:
            return False
        return any(addr in net for net in self.allowed_networks)

    def key_valid(self, key: str | None) -> bool:
        if self.api_key is None:
            return True
        return key is not None and hmac.compare_digest(key.encode(), self.api_key.encode())

    def check(self, request: Request, key: str | None) -> None:
        if not self.ip_allowed(client_ip(request)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "client IP not allowed")
        if not self.key_valid(key):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"missing or invalid {API_KEY_HEADER}",
                                headers={"WWW-Authenticate": API_KEY_HEADER})
