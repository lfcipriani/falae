"""Destinations for the final MP3: the local filesystem or a Google Cloud Storage bucket."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from google.cloud import storage as gcs

DEFAULT_GCS_BUCKET = "com-talleye-falae"


class Storage(Protocol):
    kind: str  # "local" or "gcs", reported to the webhook

    def path_for(self, filename: str) -> Path:
        """Local path where the MP3 should be written."""
        ...

    def location_for(self, filename: str) -> str:
        """Where the file will be once published, known before it's written."""
        ...

    def publish(self, path: Path) -> str:
        """Move/upload the written file to its destination; return its location."""
        ...


class LocalStorage:
    kind = "local"

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).expanduser().resolve()

    def path_for(self, filename: str) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir / filename

    def location_for(self, filename: str) -> str:
        return str(self.base_dir / filename)

    def publish(self, path: Path) -> str:
        return self.location_for(path.name)


class GCSStorage:
    """Writes the MP3 to a local temp dir, uploads it to `bucket`, then deletes the local copy.

    The bucket is fixed per instance. The client is created on first upload, using
    Application Default Credentials, unless one is passed in (tests pass a fake).
    """

    kind = "gcs"

    def __init__(
        self,
        bucket: str = DEFAULT_GCS_BUCKET,
        client: gcs.Client | None = None,
        staging_dir: str | Path | None = None,
    ):
        self.bucket_name = bucket
        self._client = client
        self.staging_dir = Path(staging_dir or Path(tempfile.gettempdir()) / "falae-gcs")

    @property
    def client(self) -> gcs.Client:
        if self._client is None:
            from google.cloud import storage as gcs

            self._client = gcs.Client()
        return self._client

    def path_for(self, filename: str) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        return self.staging_dir / filename

    def publish(self, path: Path) -> str:
        blob = self.client.bucket(self.bucket_name).blob(path.name)
        try:
            blob.upload_from_filename(str(path), content_type="audio/mpeg")
        finally:
            path.unlink(missing_ok=True)
        return self.location_for(path.name)

    def location_for(self, filename: str) -> str:
        return f"gs://{self.bucket_name}/{filename}"


def storage_from_env(env: dict[str, str] | None = None) -> Storage:
    """FALAE_STORAGE picks the backend: "local" (default) or "gcs".
    local: FALAE_OUTPUT_DIR (default "output"). gcs: FALAE_GCS_BUCKET (default com-talleye-falae)."""
    env = os.environ if env is None else env
    kind = env.get("FALAE_STORAGE", "local").strip().lower()
    if kind == "local":
        return LocalStorage(env.get("FALAE_OUTPUT_DIR", "output"))
    if kind == "gcs":
        return GCSStorage(env.get("FALAE_GCS_BUCKET") or DEFAULT_GCS_BUCKET)
    raise ValueError(f'FALAE_STORAGE must be "local" or "gcs", got {kind!r}')


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "article"
