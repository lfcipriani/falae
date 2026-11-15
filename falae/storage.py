"""Destinations for the final MP3: the local filesystem, a Google Cloud Storage bucket or Dropbox."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import dropbox
    from google.cloud import storage as gcs

DEFAULT_GCS_BUCKET = "com-talleye-falae"
STORAGE_KINDS = ("local", "gcs", "dropbox")


class Storage(Protocol):
    kind: str  # "local", "gcs" or "dropbox", reported to the webhook

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


class DropboxStorage:
    """Writes the MP3 to a local temp dir, uploads it to `folder` in Dropbox, then deletes the
    local copy. An existing file with the same name is overwritten, as with GCS.

    The folder is fixed per instance. With an "App folder" Dropbox app, paths are relative to
    Apps/<app name>, so "" (the default) is the app folder itself. The client is created on first
    upload from a refresh token, so it never expires, unless one is passed in (tests pass a fake).
    """

    kind = "dropbox"
    # Dropbox's single-request upload limit is 150 MB; bigger files go through an upload session.
    SINGLE_UPLOAD_LIMIT = 150 * 1024 * 1024
    CHUNK_SIZE = 8 * 1024 * 1024

    def __init__(
        self,
        folder: str = "",
        *,
        app_key: str | None = None,
        app_secret: str | None = None,
        refresh_token: str | None = None,
        client: dropbox.Dropbox | None = None,
        staging_dir: str | Path | None = None,
    ):
        if client is None and not (app_key and app_secret and refresh_token):
            raise ValueError("Dropbox storage needs FALAE_DROPBOX_APP_KEY, FALAE_DROPBOX_APP_SECRET "
                             "and FALAE_DROPBOX_REFRESH_TOKEN")
        self.folder = normalize_dropbox_folder(folder)
        self._credentials = (app_key, app_secret, refresh_token)
        self._client = client
        self.staging_dir = Path(staging_dir or Path(tempfile.gettempdir()) / "falae-dropbox")

    @property
    def client(self) -> dropbox.Dropbox:
        if self._client is None:
            import dropbox

            app_key, app_secret, refresh_token = self._credentials
            self._client = dropbox.Dropbox(
                app_key=app_key, app_secret=app_secret, oauth2_refresh_token=refresh_token
            )
        return self._client

    def path_for(self, filename: str) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        return self.staging_dir / filename

    def dropbox_path(self, filename: str) -> str:
        return f"{self.folder}/{filename}"

    def publish(self, path: Path) -> str:
        try:
            self._upload(path, self.dropbox_path(path.name))
        finally:
            path.unlink(missing_ok=True)
        return self.location_for(path.name)

    def location_for(self, filename: str) -> str:
        return f"dropbox:{self.dropbox_path(filename)}"

    def _upload(self, path: Path, dest: str) -> None:
        from dropbox.files import CommitInfo, UploadSessionCursor, WriteMode

        size = path.stat().st_size
        with path.open("rb") as f:
            if size <= self.SINGLE_UPLOAD_LIMIT:
                self.client.files_upload(f.read(), dest, mode=WriteMode.overwrite)
                return
            session = self.client.files_upload_session_start(f.read(self.CHUNK_SIZE))
            cursor = UploadSessionCursor(session_id=session.session_id, offset=f.tell())
            commit = CommitInfo(path=dest, mode=WriteMode.overwrite)
            while size - f.tell() > self.CHUNK_SIZE:
                self.client.files_upload_session_append_v2(f.read(self.CHUNK_SIZE), cursor)
                cursor.offset = f.tell()
            self.client.files_upload_session_finish(f.read(), cursor, commit)


def normalize_dropbox_folder(folder: str) -> str:
    """"", "/", "falae/", "/falae" -> "" or "/falae": a leading slash, no trailing one."""
    folder = folder.strip().strip("/")
    return f"/{folder}" if folder else ""


def storage_from_env(env: dict[str, str] | None = None) -> Storage:
    """FALAE_STORAGE picks the backend: "local" (default), "gcs" or "dropbox".
    local: FALAE_OUTPUT_DIR (default "output"). gcs: FALAE_GCS_BUCKET (default com-talleye-falae).
    dropbox: FALAE_DROPBOX_FOLDER (default: the app folder root) plus FALAE_DROPBOX_APP_KEY,
    FALAE_DROPBOX_APP_SECRET and FALAE_DROPBOX_REFRESH_TOKEN, all required."""
    env = os.environ if env is None else env
    kind = env.get("FALAE_STORAGE", "local").strip().lower()
    if kind == "local":
        return LocalStorage(env.get("FALAE_OUTPUT_DIR", "output"))
    if kind == "gcs":
        return GCSStorage(env.get("FALAE_GCS_BUCKET") or DEFAULT_GCS_BUCKET)
    if kind == "dropbox":
        return dropbox_storage_from_env(env)
    raise ValueError(f"FALAE_STORAGE must be one of {', '.join(STORAGE_KINDS)}; got {kind!r}")


def dropbox_storage_from_env(env: dict[str, str] | None = None, folder: str | None = None) -> DropboxStorage:
    """Credentials always come from the environment; `folder` overrides FALAE_DROPBOX_FOLDER."""
    env = os.environ if env is None else env
    return DropboxStorage(
        env.get("FALAE_DROPBOX_FOLDER", "") if folder is None else folder,
        app_key=env.get("FALAE_DROPBOX_APP_KEY", "").strip() or None,
        app_secret=env.get("FALAE_DROPBOX_APP_SECRET", "").strip() or None,
        refresh_token=env.get("FALAE_DROPBOX_REFRESH_TOKEN", "").strip() or None,
    )


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "article"
