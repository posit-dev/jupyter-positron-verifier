"""
RSA-PKCS1v1.5-SHA256 license minting.

Matches the verification in Positron's remoteLicenseKey.ts:
  verifier.update(connection_token)
  verifier.update(issuer)
  verifier.update(licensee)
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

    def __init__(self, private_key: RSAPrivateKey, issuer: str, licensee: str):
        self._key = private_key
        self.issuer = issuer
        self.licensee = licensee

    @classmethod
    def from_pem(cls, pem: str, issuer: str, licensee: str) -> "Signer":
        """Create a Signer directly from a PEM string (useful for tests)."""
        private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(private_key, RSAPrivateKey):
            raise TypeError("pem must be an RSA private key")
        return cls(private_key, issuer, licensee)

    @classmethod
    def from_env(cls) -> "Signer":
        """
        Load signing key and identities from environment variables.

        Key sources (first match wins):
          POSITRON_MINTING_KEY      PEM-encoded RSA private key (literal string)
          POSITRON_MINTING_KEY_FILE Path to a PEM-encoded RSA private key file

        Identity:
          POSITRON_LICENSE_ISSUER   Issuer name embedded in every license (required)
          POSITRON_LICENSE_LICENSEE Licensee name embedded in every license (required)
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

        issuer = os.environ.get("POSITRON_LICENSE_ISSUER")
        licensee = os.environ.get("POSITRON_LICENSE_LICENSEE")
        if not issuer or not licensee:
            raise ValueError(
                "POSITRON_LICENSE_ISSUER and POSITRON_LICENSE_LICENSEE must be set."
            )

        return cls(private_key, issuer, licensee)

    def mint(self, connection_token: str) -> str:
        """
        Sign a license for the given connection token and return the license JSON string.

        The payload is the concatenation (as UTF-8 bytes) of:
          connection_token + issuer + licensee + timestamp
        matching the field update order in remoteLicenseKey.ts.
        """
        timestamp = _js_timestamp()
        payload = (connection_token + self.issuer + self.licensee + timestamp).encode()

        signature_bytes = self._key.sign(payload, padding.PKCS1v15(), hashes.SHA256())
        signature_b64 = base64.b64encode(signature_bytes).decode()

        license_obj = {
            "connection_token": connection_token,
            "issuer": self.issuer,
            "licensee": self.licensee,
            "timestamp": timestamp,
            "signature": signature_b64,
        }
        return json.dumps(license_obj)
