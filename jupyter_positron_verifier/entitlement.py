"""
Entitlement check via license-manager subprocess.

The result is cached for CACHE_TTL_SECONDS to avoid repeated subprocess
calls on every mint request.
"""

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes


class EntitlementResult:
    def __init__(self, valid: bool, licensee: str = "", issuer: str = ""):
        self.valid = valid
        self.licensee = licensee
        self.issuer = issuer
        self._fetched_at = time.monotonic()

    def is_fresh(self) -> bool:
        return (time.monotonic() - self._fetched_at) < CACHE_TTL_SECONDS


class EntitlementChecker:
    """Checks entitlement via license-manager and caches the result."""

    def __init__(self, license_manager_path: str | None, skip: bool = False):
        self._path = license_manager_path
        self._skip = skip
        self._cache: EntitlementResult | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "EntitlementChecker":
        """
        Configure from environment variables.

          POSITRON_LICENSE_MANAGER_PATH  Path to the license-manager binary.
          POSITRON_SKIP_ENTITLEMENT_CHECK  Set to '1' to skip checks (dev only).
        """
        skip = os.environ.get("POSITRON_SKIP_ENTITLEMENT_CHECK", "") == "1"
        path = os.environ.get("POSITRON_LICENSE_MANAGER_PATH")
        return cls(license_manager_path=path, skip=skip)

    async def check(self) -> EntitlementResult:
        """Return the (cached) entitlement result, refreshing it if stale."""
        async with self._lock:
            if self._cache is None or not self._cache.is_fresh():
                self._cache = await self._fetch()
            return self._cache

    async def is_valid(self) -> bool:
        """Return True if the entitlement is valid (uses cache)."""
        return (await self.check()).valid

    async def _fetch(self) -> EntitlementResult:
        if self._skip:
            logger.warning(
                "Entitlement check skipped (POSITRON_SKIP_ENTITLEMENT_CHECK=1)"
            )
            return EntitlementResult(valid=True, licensee="Development")

        if not self._path:
            logger.error(
                "POSITRON_LICENSE_MANAGER_PATH not set; cannot verify entitlement"
            )
            return EntitlementResult(valid=False)

        try:
            proc = await asyncio.create_subprocess_exec(
                self._path,
                "verify",
                "--output=json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if stderr:
                logger.debug(f"license-manager stderr: {stderr.decode()}")

            raw = stdout.decode()
            # The verify command prefixes output with a hash line; find the JSON.
            json_start = raw.find("{")
            if json_start >= 0:
                raw = raw[json_start:]
            data = json.loads(raw)

            status = (data.get("status") or "").lower()
            if status in ("activated", "evaluation"):
                licensee = data.get("licensee", "")
                issuer = data.get("issuer", "")
                logger.info(f"Entitlement valid: status={status}, licensee={licensee}")
                return EntitlementResult(valid=True, licensee=licensee, issuer=issuer)
            else:
                logger.error(f"Entitlement invalid: {data}")
                return EntitlementResult(valid=False)

        except asyncio.TimeoutError:
            logger.error("license-manager timed out")
            return EntitlementResult(valid=False)
        except Exception as e:
            logger.error(f"license-manager error: {e}")
            return EntitlementResult(valid=False)
