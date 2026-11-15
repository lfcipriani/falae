"""Notifies a webhook when a background synthesis job finishes, successfully or not."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

log = logging.getLogger("falae")

SUCCESS_MESSAGE = "The audio file is ready for you!"


@dataclass(frozen=True)
class Webhook:
    url: str
    timeout: float = 10.0

    def __post_init__(self):
        parsed = urlparse(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"FALAE_WEBHOOK_URL must be an http(s) URL, got {self.url!r}")

    def notify(self, storage: str, file_path: str, message: str) -> None:
        """POST {"storage", "file_path", "message"} as JSON. Never raises: the job is already
        done, so a failed delivery is only logged."""
        body = json.dumps({"storage": storage, "file_path": file_path, "message": message}).encode()
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "falae"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except Exception as exc:
            log.warning("webhook delivery failed for %s: %s", file_path, exc)


def webhook_from_env(env: dict[str, str] | None = None) -> Webhook | None:
    """FALAE_WEBHOOK_URL; unset or blank means no webhook."""
    env = os.environ if env is None else env
    url = env.get("FALAE_WEBHOOK_URL", "").strip()
    return Webhook(url) if url else None
