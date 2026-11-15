from pathlib import Path

import pytest

from falae import api
from falae.models import SynthesisOptions
from falae.service import synthesize_article
from falae.storage import DEFAULT_GCS_BUCKET, GCSStorage, LocalStorage, storage_from_env

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
