"""Tests for the signing module -- round-trip and contract verification."""

import base64
import json
import re

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from jupyter_positron_verifier.signing import Signer, _js_timestamp


def test_timestamp_format():
    ts = _js_timestamp()
    # Must match JavaScript toISOString(): YYYY-MM-DDTHH:MM:SS.mmmZ
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts), ts


def test_mint_returns_valid_json(test_key_pair):
    _, private_pem, _ = test_key_pair
    signer = Signer.from_pem(private_pem, issuer="Test Hub", licensee="Test Corp")
    result = signer.mint("test-token-abc")
    obj = json.loads(result)
    assert obj["connection_token"] == "test-token-abc"
    assert obj["issuer"] == "Test Hub"
    assert obj["licensee"] == "Test Corp"
    assert "timestamp" in obj
    assert "signature" in obj


def test_signature_verifies_with_public_key(test_key_pair):
    private_key, private_pem, public_pem = test_key_pair
    signer = Signer.from_pem(private_pem, issuer="Hub", licensee="Corp")
    license_str = signer.mint("round-trip-token")
    obj = json.loads(license_str)

    # Reconstruct payload the same way remoteLicenseKey.ts does it.
    payload = (
        obj["connection_token"] + obj["issuer"] + obj["licensee"] + obj["timestamp"]
    ).encode()
    signature = base64.b64decode(obj["signature"])

    public_key = serialization.load_pem_public_key(public_pem.encode())
    # Should not raise -- raises InvalidSignature on failure.
    public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())


def test_different_tokens_produce_different_signatures(test_key_pair):
    _, private_pem, _ = test_key_pair
    signer = Signer.from_pem(private_pem, issuer="Hub", licensee="Corp")
    a = json.loads(signer.mint("token-a"))
    b = json.loads(signer.mint("token-b"))
    assert a["signature"] != b["signature"]


def test_from_env_missing_key(monkeypatch):
    monkeypatch.delenv("POSITRON_MINTING_KEY", raising=False)
    monkeypatch.delenv("POSITRON_MINTING_KEY_FILE", raising=False)
    with pytest.raises(ValueError, match="No signing key"):
        Signer.from_env()


def test_from_env_missing_issuer(monkeypatch, test_key_pair):
    _, private_pem, _ = test_key_pair
    monkeypatch.setenv("POSITRON_MINTING_KEY", private_pem)
    monkeypatch.setenv("POSITRON_LICENSE_LICENSEE", "Corp")
    monkeypatch.delenv("POSITRON_LICENSE_ISSUER", raising=False)
    with pytest.raises(ValueError, match="POSITRON_LICENSE_ISSUER"):
        Signer.from_env()
