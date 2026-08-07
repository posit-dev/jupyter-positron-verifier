"""
Entitlement check via license-manager subprocess.

Determinate results are cached for CACHE_TTL_SECONDS to avoid repeated
subprocess calls on every mint request. Indeterminate results (license-manager
did not answer) are never cached, so a transient failure does not deny mints
for the whole TTL.

A failed check comes in two flavours, distinguished by ``determinate``:

* determinate -- license-manager answered and the answer was "not entitled", or
  the deployment can never be entitled as configured (no binary path, binary
  missing or not executable). Retrying will not change the outcome, so the
  service refuses to start.
* indeterminate -- license-manager did not answer (timeout, crash,
  unparseable output). The state is unknown, so mints still fail closed, but
  the service is allowed to start and retry.
"""

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300  # 5 minutes


class EntitlementResult:
    def __init__(
        self,
        valid: bool,
        licensee: str = "",
        issuer: str = "",
        determinate: bool = True,
    ):
        self.valid = valid
        self.licensee = licensee
        self.issuer = issuer
        # False when license-manager could not be consulted, i.e. we do not know
        # whether this host is entitled. See the module docstring.
        self.determinate = determinate
        self._fetched_at = time.monotonic()

    def is_fresh(self) -> bool:
        return (time.monotonic() - self._fetched_at) < CACHE_TTL_SECONDS


class EntitlementChecker:
    """Checks entitlement via license-manager and caches the result."""

    def __init__(self, license_manager_path: str | None):
        self._path = license_manager_path
        self._cache: EntitlementResult | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "EntitlementChecker":
        """
        Configure from environment variables.

          POSITRON_LICENSE_MANAGER_PATH  Path to the license-manager binary.
        """
        path = os.environ.get("POSITRON_LICENSE_MANAGER_PATH")
        return cls(license_manager_path=path)

    async def check(self) -> EntitlementResult:
        """Return the (cached) entitlement result, refreshing it if stale."""
        async with self._lock:
            if self._cache is None or not self._cache.is_fresh():
                result = await self._fetch()
                # Only cache answers we actually got. Caching an indeterminate
                # result would turn a 10-second license-manager blip into
                # CACHE_TTL_SECONDS of denied mints.
                self._cache = result if result.determinate else None
                return result
            return self._cache

    async def is_valid(self) -> bool:
        """Return True if the entitlement is valid (uses cache)."""
        return (await self.check()).valid

    async def _fetch(self) -> EntitlementResult:
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
                # license-manager answered, and the answer was no.
                logger.error(f"Entitlement invalid: {data}")
                return EntitlementResult(valid=False)

        except FileNotFoundError:
            logger.error(f"license-manager not found at {self._path}")
            return EntitlementResult(valid=False)
        except PermissionError:
            logger.error(f"license-manager at {self._path} is not executable")
            return EntitlementResult(valid=False)
        except asyncio.TimeoutError:
            # Did not answer in time; entitlement state is unknown.
            logger.error("license-manager timed out")
            return EntitlementResult(valid=False, determinate=False)
        except Exception as e:
            # Crashed, or emitted output we could not parse. Also unknown.
            logger.error(f"license-manager error: {e}")
            return EntitlementResult(valid=False, determinate=False)
