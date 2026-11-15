import pytest
from fastapi.testclient import TestClient

from falae import api
from falae.auth import AccessPolicy

BODY = {"language": "en", "content": "Hi."}


@pytest.fixture
def client(monkeypatch):
    """API client with no real work behind it; `use(policy)` installs an access policy."""
    calls = []
    monkeypatch.setattr(api, "run_synthesis", lambda *a: calls.append(a))

    def use(policy: AccessPolicy) -> TestClient:
        api.app.dependency_overrides[api.get_access_policy] = lambda: policy
        c = TestClient(api.app)
        c.calls = calls
        return c

    yield use
    api.app.dependency_overrides.clear()


def test_no_policy_allows_everything(client):
    c = client(AccessPolicy())
    assert c.post("/synthesize", json=BODY).status_code == 202


def test_api_key_required(client):
    c = client(AccessPolicy(api_key="s3cret"))
    assert c.post("/synthesize", json=BODY).status_code == 401
    assert c.post("/synthesize", json=BODY, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/synthesize", json=BODY, headers={"X-API-Key": "s3cret"}).status_code == 202
    assert len(c.calls) == 1  # rejected requests never start a job


def test_auth_checked_before_body_validation(client):
    c = client(AccessPolicy(api_key="s3cret"))
    assert c.post("/synthesize", json={"bogus": 1}).status_code == 401


def test_healthz_is_open(client):
    c = client(AccessPolicy(api_key="s3cret"))
    assert c.get("/healthz").status_code == 200


def test_policy_from_env():
    assert AccessPolicy.from_env({}) == AccessPolicy()
    assert AccessPolicy.from_env({"FALAE_API_KEY": ""}) == AccessPolicy()
    assert AccessPolicy.from_env({"FALAE_API_KEY": "k"}).api_key == "k"
