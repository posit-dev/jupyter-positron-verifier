"""Integration tests for the mint endpoint."""

import json

import pytest
from fastapi.testclient import TestClient

from jupyter_positron_verifier.app import MintResponse, MintRequest, create_app, verify_hub_token
from jupyter_positron_verifier.entitlement import EntitlementChecker
from jupyter_positron_verifier.signing import Signer
from jupyter_positron_verifier.store import TokenStore


class _FakeEntitlement(EntitlementChecker):
    def __init__(self, valid: bool = True):
        self._valid = valid

    async def is_valid(self) -> bool:
        return self._valid


def _make_client(test_key_pair, *, entitlement_valid=True, override_auth=True):
    _, private_pem, _ = test_key_pair
    signer = Signer.from_pem(private_pem, issuer="Test Hub", licensee="Test Corp")
    store = TokenStore()
    app = create_app(
        service_prefix="/services/positron-license",
        signer=signer,
        entitlement=_FakeEntitlement(valid=entitlement_valid),
        store=store,
    )
    if override_auth:
        app.dependency_overrides[verify_hub_token] = lambda: "testuser"
    return TestClient(app)


class TestMintEndpoint:
    def test_success_returns_signed_license(self, test_key_pair):
        client = _make_client(test_key_pair)
        resp = client.post(
            "/services/positron-license/mint",
            json={"connection_token": "conn-token-abc"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "license" in body
        obj = json.loads(body["license"])
        assert obj["connection_token"] == "conn-token-abc"
        assert obj["issuer"] == "Test Hub"
        assert obj["licensee"] == "Test Corp"
        assert "timestamp" in obj
        assert "signature" in obj

    def test_duplicate_token_returns_409(self, test_key_pair):
        client = _make_client(test_key_pair)
        r1 = client.post(
            "/services/positron-license/mint",
            json={"connection_token": "dup-token"},
        )
        r2 = client.post(
            "/services/positron-license/mint",
            json={"connection_token": "dup-token"},
        )
        assert r1.status_code == 200
        assert r2.status_code == 409

    def test_unlicensed_returns_403(self, test_key_pair):
        client = _make_client(test_key_pair, entitlement_valid=False)
        resp = client.post(
            "/services/positron-license/mint",
            json={"connection_token": "tok"},
        )
        assert resp.status_code == 403

    def test_missing_auth_returns_401_or_403(self, test_key_pair):
        client = _make_client(test_key_pair, override_auth=False)
        resp = client.post(
            "/services/positron-license/mint",
            json={"connection_token": "tok"},
            # No Authorization header -- HTTPBearer will reject
        )
        assert resp.status_code in (401, 403)

    def test_different_tokens_each_succeed(self, test_key_pair):
        client = _make_client(test_key_pair)
        for i in range(3):
            resp = client.post(
                "/services/positron-license/mint",
                json={"connection_token": f"tok-{i}"},
            )
            assert resp.status_code == 200
