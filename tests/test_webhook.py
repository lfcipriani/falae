import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from falae import api
from falae.service import synthesize_article
from falae.storage import LocalStorage
from falae.webhook import SUCCESS_MESSAGE, Webhook, webhook_from_env

from .conftest import FakeSynthesizer


@pytest.fixture
def receiver():
    """A local HTTP server that records the JSON bodies POSTed to it."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append((self.headers["Content-Type"], json.loads(self.rfile.read(length))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/hook", received
    server.shutdown()


class Recorder:
    def __init__(self):
        self.calls = []

    def notify(self, storage, file_path, message):
        self.calls.append({"storage": storage, "file_path": file_path, "message": message})


@pytest.fixture
def hooked_api(tmp_path):
    recorder = Recorder()
    api.app.dependency_overrides[api.get_storage] = lambda: LocalStorage(tmp_path)
    api.app.dependency_overrides[api.get_webhook] = lambda: recorder
    yield recorder
    api.app.dependency_overrides.clear()


def test_notify_posts_json(receiver):
    url, received = receiver
    Webhook(url).notify("gcs", "gs://b/x.mp3", "hi")
    assert received == [("application/json", {"storage": "gcs", "file_path": "gs://b/x.mp3",
                                              "message": "hi"})]


def test_notify_failure_is_logged_not_raised(caplog):
    Webhook("http://127.0.0.1:1/hook", timeout=1).notify("local", "/x.mp3", "hi")
    assert "webhook delivery failed for /x.mp3" in caplog.text


def test_webhook_from_env():
    assert webhook_from_env({}) is None
    assert webhook_from_env({"FALAE_WEBHOOK_URL": "  "}) is None
    assert webhook_from_env({"FALAE_WEBHOOK_URL": " https://n8n.example/hook "}).url == \
        "https://n8n.example/hook"
    with pytest.raises(ValueError):
        webhook_from_env({"FALAE_WEBHOOK_URL": "n8n.example/hook"})


def test_api_notifies_on_success(hooked_api, monkeypatch, silent_mp3):
    fake = FakeSynthesizer(silent_mp3)
    monkeypatch.setattr(api, "synthesize_article",
                        lambda a, s, o: synthesize_article(a, s, o, synthesizer=fake))
    resp = TestClient(api.app).post("/synthesize", json={"language": "en", "content": "Hi.",
                                                         "title": "Hello"})
    assert resp.status_code == 202
    assert hooked_api.calls == [{"storage": "local", "file_path": resp.json()["location"],
                                 "message": SUCCESS_MESSAGE}]


def test_api_notifies_on_failure_with_error_message(hooked_api, monkeypatch):
    def boom(a, s, o):
        raise RuntimeError("TTS down")

    monkeypatch.setattr(api, "synthesize_article", boom)
    resp = TestClient(api.app).post("/synthesize", json={"language": "en", "content": "Hi."})
    assert resp.status_code == 202
    assert hooked_api.calls == [{"storage": "local", "file_path": resp.json()["location"],
                                 "message": "TTS down"}]
