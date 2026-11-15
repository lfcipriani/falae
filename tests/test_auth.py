import pytest
from fastapi.testclient import TestClient

from falae import api
from falae.auth import AccessPolicy, parse_networks

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
    c = client(AccessPolicy(api_key="s3cret", allowed_networks=parse_networks("10.0.0.1")))
    assert c.get("/healthz").status_code == 200


def test_ip_allowlist_uses_rightmost_forwarded_entry(client):
    c = client(AccessPolicy(allowed_networks=parse_networks("203.0.113.7, 198.51.100.0/24")))

    def post(xff):
        return c.post("/synthesize", json=BODY, headers={"X-Forwarded-For": xff}).status_code

    assert post("203.0.113.7") == 202
    assert post("198.51.100.42") == 202
    assert post("192.0.2.1") == 403
    assert post("203.0.113.7, 192.0.2.1") == 403  # client-forged entry on the left is ignored
    assert post("192.0.2.1, 203.0.113.7") == 202


def test_ip_and_key_together(client):
    c = client(AccessPolicy(api_key="k", allowed_networks=parse_networks("203.0.113.7")))
    ok_ip, bad_ip = {"X-Forwarded-For": "203.0.113.7"}, {"X-Forwarded-For": "192.0.2.1"}
    assert c.post("/synthesize", json=BODY, headers={**bad_ip, "X-API-Key": "k"}).status_code == 403
    assert c.post("/synthesize", json=BODY, headers=ok_ip).status_code == 401
    assert c.post("/synthesize", json=BODY, headers={**ok_ip, "X-API-Key": "k"}).status_code == 202


def test_policy_from_env():
    assert AccessPolicy.from_env({}) == AccessPolicy()
    p = AccessPolicy.from_env({"FALAE_API_KEY": "k", "FALAE_ALLOWED_IPS": " 1.2.3.4 ,10.0.0.0/8, ::1 "})
    assert p.api_key == "k"
    assert [str(n) for n in p.allowed_networks] == ["1.2.3.4/32", "10.0.0.0/8", "::1/128"]
    with pytest.raises(ValueError):
        AccessPolicy.from_env({"FALAE_ALLOWED_IPS": "not-an-ip"})
