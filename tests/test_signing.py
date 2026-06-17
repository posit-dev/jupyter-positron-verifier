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
    signer = Signer.from_pem(private_pem)
    result = signer.mint("test-token-abc", licensee="Test Corp")
    obj = json.loads(result)
    assert obj["connection_token"] == "test-token-abc"
    assert obj["licensee"] == "Test Corp"
    assert "timestamp" in obj
    assert "signature" in obj
    assert "issuer" not in obj


def test_signature_verifies_with_public_key(test_key_pair):
    private_key, private_pem, public_pem = test_key_pair
    signer = Signer.from_pem(private_pem)
    license_str = signer.mint("round-trip-token", licensee="Corp")
    obj = json.loads(license_str)

    # Only connection_token + timestamp are signed; licensee is not part of the payload.
    payload = (obj["connection_token"] + obj["timestamp"]).encode()
    signature = base64.b64decode(obj["signature"])

    public_key = serialization.load_pem_public_key(public_pem.encode())
    # Should not raise -- raises InvalidSignature on failure.
    public_key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())


def test_different_tokens_produce_different_signatures(test_key_pair):
    _, private_pem, _ = test_key_pair
    signer = Signer.from_pem(private_pem)
    a = json.loads(signer.mint("token-a"))
    b = json.loads(signer.mint("token-b"))
    assert a["signature"] != b["signature"]


def test_from_env_missing_key(monkeypatch):
    monkeypatch.delenv("POSITRON_MINTING_KEY", raising=False)
    monkeypatch.delenv("POSITRON_MINTING_KEY_FILE", raising=False)
    with pytest.raises(ValueError, match="No signing key"):
        Signer.from_env()


def test_from_env_with_key_succeeds(monkeypatch, test_key_pair):
    _, private_pem, _ = test_key_pair
    monkeypatch.setenv("POSITRON_MINTING_KEY", private_pem)
    # No issuer/licensee env vars are required any longer.
    monkeypatch.delenv("POSITRON_LICENSE_ISSUER", raising=False)
    monkeypatch.delenv("POSITRON_LICENSE_LICENSEE", raising=False)
    signer = Signer.from_env()
    obj = json.loads(signer.mint("tok"))
    assert obj["connection_token"] == "tok"
    assert "issuer" not in obj
