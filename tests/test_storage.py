from pathlib import Path

import pytest

from falae import api
from falae.models import SynthesisOptions
from falae.service import synthesize_article
from dropbox.files import WriteMode

from falae.storage import (
    DEFAULT_GCS_BUCKET, DropboxStorage, GCSStorage, LocalStorage, dropbox_storage_from_env,
    storage_from_env,
)

from .conftest import FakeSynthesizer


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    def upload_from_filename(self, filename, content_type=None):
        self.bucket.uploads[self.name] = (Path(filename).read_bytes(), content_type)


class FakeBucket:
    def __init__(self, name):
        self.name = name
        self.uploads: dict[str, tuple[bytes, str | None]] = {}

    def blob(self, name):
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self):
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(name))


def test_gcs_storage_uploads_and_removes_local_copy(tmp_path):
    client = FakeClient()
    storage = GCSStorage("my-bucket", client=client, staging_dir=tmp_path)
    path = storage.path_for("a.mp3")
    path.write_bytes(b"ID3data")

    assert storage.publish(path) == "gs://my-bucket/a.mp3"
    assert client.buckets["my-bucket"].uploads == {"a.mp3": (b"ID3data", "audio/mpeg")}
    assert not path.exists()


def test_gcs_storage_default_bucket():
    assert GCSStorage().bucket_name == DEFAULT_GCS_BUCKET == "com-talleye-falae"


def test_synthesize_article_to_gcs(tmp_path, article, silent_mp3):
    client = FakeClient()
    storage = GCSStorage("b", client=client, staging_dir=tmp_path)
    result = synthesize_article(article, storage, SynthesisOptions(),
                                synthesizer=FakeSynthesizer(silent_mp3))

    assert result.location == "gs://b/2026-11-11-um-titulo.mp3"
    data, _ = client.buckets["b"].uploads["2026-11-11-um-titulo.mp3"]
    assert result.bytes == len(data) > 0
    assert list(tmp_path.iterdir()) == []


def test_storage_from_env():
    assert isinstance(storage_from_env({}), LocalStorage)
    assert storage_from_env({"FALAE_STORAGE": "gcs"}).bucket_name == "com-talleye-falae"
    assert storage_from_env({"FALAE_STORAGE": "GCS", "FALAE_GCS_BUCKET": "other"}).bucket_name == "other"
    with pytest.raises(ValueError):
        storage_from_env({"FALAE_STORAGE": "s3"})


def test_api_storage_is_created_once_per_process(monkeypatch):
    api.get_storage.cache_clear()
    monkeypatch.setenv("FALAE_STORAGE", "gcs")
    try:
        first = api.get_storage()
        monkeypatch.setenv("FALAE_GCS_BUCKET", "changed")
        assert api.get_storage() is first
        assert first.bucket_name == "com-talleye-falae"
    finally:
        api.get_storage.cache_clear()


class FakeDropbox:
    """Records files_upload calls and reassembles upload sessions."""

    def __init__(self):
        self.files: dict[str, tuple[bytes, WriteMode]] = {}
        self.sessions: dict[str, bytearray] = {}
        self.appends = 0

    def files_upload(self, data, path, mode=None):
        self.files[path] = (data, mode)

    def files_upload_session_start(self, data):
        sid = f"s{len(self.sessions)}"
        self.sessions[sid] = bytearray(data)
        return type("Session", (), {"session_id": sid})()

    def files_upload_session_append_v2(self, data, cursor):
        assert cursor.offset == len(self.sessions[cursor.session_id])
        self.sessions[cursor.session_id] += data
        self.appends += 1

    def files_upload_session_finish(self, data, cursor, commit):
        assert cursor.offset == len(self.sessions[cursor.session_id])
        self.files[commit.path] = (bytes(self.sessions.pop(cursor.session_id) + data), commit.mode)


DROPBOX_ENV = {"FALAE_STORAGE": "dropbox", "FALAE_DROPBOX_APP_KEY": "k",
               "FALAE_DROPBOX_APP_SECRET": "s", "FALAE_DROPBOX_REFRESH_TOKEN": "r"}


def test_dropbox_storage_uploads_overwriting_and_removes_local_copy(tmp_path):
    client = FakeDropbox()
    storage = DropboxStorage("Podcasts/falae/", client=client, staging_dir=tmp_path)
    path = storage.path_for("a.mp3")
    path.write_bytes(b"ID3data")

    assert storage.location_for("a.mp3") == "dropbox:/Podcasts/falae/a.mp3"
    assert storage.publish(path) == "dropbox:/Podcasts/falae/a.mp3"
    assert client.files == {"/Podcasts/falae/a.mp3": (b"ID3data", WriteMode.overwrite)}
    assert not path.exists()


def test_dropbox_storage_root_folder(tmp_path):
    for folder in ("", "/", "  "):
        assert DropboxStorage(folder, client=FakeDropbox()).location_for("a.mp3") == "dropbox:/a.mp3"


def test_dropbox_storage_large_file_uses_upload_session(tmp_path, monkeypatch):
    monkeypatch.setattr(DropboxStorage, "SINGLE_UPLOAD_LIMIT", 10)
    monkeypatch.setattr(DropboxStorage, "CHUNK_SIZE", 4)
    client = FakeDropbox()
    storage = DropboxStorage("/f", client=client, staging_dir=tmp_path)
    path = storage.path_for("big.mp3")
    data = bytes(range(23))
    path.write_bytes(data)

    storage.publish(path)
    assert client.files == {"/f/big.mp3": (data, WriteMode.overwrite)}
    assert client.appends == 4  # 4 bytes to start, 4 appends of 4, 3 bytes to finish
    assert not path.exists()


def test_dropbox_storage_removes_local_copy_when_upload_fails(tmp_path):
    class Failing(FakeDropbox):
        def files_upload(self, data, path, mode=None):
            raise RuntimeError("boom")

    storage = DropboxStorage(client=Failing(), staging_dir=tmp_path)
    path = storage.path_for("a.mp3")
    path.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        storage.publish(path)
    assert not path.exists()


def test_synthesize_article_to_dropbox(tmp_path, article, silent_mp3):
    client = FakeDropbox()
    storage = DropboxStorage("/falae", client=client, staging_dir=tmp_path)
    result = synthesize_article(article, storage, SynthesisOptions(),
                                synthesizer=FakeSynthesizer(silent_mp3))

    assert result.location == "dropbox:/falae/2026-11-11-um-titulo.mp3"
    data, _ = client.files["/falae/2026-11-11-um-titulo.mp3"]
    assert result.bytes == len(data) > 0
    assert list(tmp_path.iterdir()) == []


def test_dropbox_storage_from_env():
    storage = storage_from_env({**DROPBOX_ENV, "FALAE_DROPBOX_FOLDER": "falae"})
    assert isinstance(storage, DropboxStorage)
    assert storage.kind == "dropbox"
    assert storage.folder == "/falae"
    assert storage._credentials == ("k", "s", "r")
    assert storage_from_env(DROPBOX_ENV).folder == ""
    assert dropbox_storage_from_env({**DROPBOX_ENV, "FALAE_DROPBOX_FOLDER": "a"}, folder="b").folder == "/b"


def test_dropbox_storage_client_built_from_refresh_token():
    client = storage_from_env(DROPBOX_ENV).client  # no network: the SDK refreshes lazily
    assert client._oauth2_refresh_token == "r"
    assert client._app_key == "k"


@pytest.mark.parametrize("missing", ["FALAE_DROPBOX_APP_KEY", "FALAE_DROPBOX_APP_SECRET",
                                     "FALAE_DROPBOX_REFRESH_TOKEN"])
def test_dropbox_storage_from_env_requires_credentials(missing):
    with pytest.raises(ValueError, match="FALAE_DROPBOX_"):
        storage_from_env({**DROPBOX_ENV, missing: " "})
