"""Access control for the HTTP API: a shared API key.

It comes from the environment and is fixed per process:
  FALAE_API_KEY  required value of the X-API-Key header. Unset disables the check.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import HTTPException, status

API_KEY_HEADER = "X-API-Key"


@dataclass(frozen=True)
class AccessPolicy:
    api_key: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AccessPolicy:
        env = os.environ if env is None else env
        return cls(api_key=env.get("FALAE_API_KEY") or None)

    def key_valid(self, key: str | None) -> bool:
        if self.api_key is None:
            return True
        return key is not None and hmac.compare_digest(key.encode(), self.api_key.encode())

    def check(self, key: str | None) -> None:
        if not self.key_valid(key):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"missing or invalid {API_KEY_HEADER}",
                                headers={"WWW-Authenticate": API_KEY_HEADER})
