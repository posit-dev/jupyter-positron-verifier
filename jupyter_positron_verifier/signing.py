"""
RSA-PKCS1v1.5-SHA256 license minting.

Matches the verification in Positron's remoteLicenseKey.ts:
  verifier.update(connection_token)
  verifier.update(timestamp)
  verifier.verify(publicKey, base64Decode(signature))
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

logger = logging.getLogger(__name__)


def _js_timestamp() -> str:
    """Return a timestamp matching JavaScript's new Date().toISOString()."""
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


class Signer:
    """Mints signed Positron license tokens."""

    def __init__(self, private_key: RSAPrivateKey):
        self._key = private_key

    @classmethod
    def from_pem(cls, pem: str) -> "Signer":
        """Create a Signer directly from a PEM string (useful for tests)."""
        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise TypeError("pem must be an RSA private key")
        return cls(private_key)

    @classmethod
    def from_env(cls) -> "Signer":
        """
        Load the signing key from environment variables.

        Key sources (first match wins):
          POSITRON_MINTING_KEY      PEM-encoded RSA private key (literal string)
          POSITRON_MINTING_KEY_FILE Path to a PEM-encoded RSA private key file
        """
        pem = os.environ.get("POSITRON_MINTING_KEY")
        if not pem:
            key_file = os.environ.get("POSITRON_MINTING_KEY_FILE")
            if not key_file:
                raise ValueError(
                    "No signing key configured. Set POSITRON_MINTING_KEY or "
                    "POSITRON_MINTING_KEY_FILE."
                )
            with open(key_file, "rb") as f:
                pem = f.read().decode()

        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise TypeError("POSITRON_MINTING_KEY must be an RSA private key")

        return cls(private_key)

    def mint(self, connection_token: str, licensee: str = "") -> str:
        """
        Sign a license for the given connection token and return the license JSON string.

        Only the connection token and timestamp are signed -- the payload is the
        concatenation (as UTF-8 bytes) of connection_token + timestamp, matching
        the field update order in remoteLicenseKey.ts. The licensee is included in
        the JSON for display but is informational and not part of the signed payload.
        """
        timestamp = _js_timestamp()
        payload = (connection_token + timestamp).encode()

        signature_bytes = self._key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        signature_b64 = base64.b64encode(signature_bytes).decode()

        license_obj = {
            "connection_token": connection_token,
            "timestamp": timestamp,
            "licensee": licensee,
            "signature": signature_b64,
        }
        return json.dumps(license_obj)
