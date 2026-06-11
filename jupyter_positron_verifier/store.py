"""
In-memory single-use token store for replay prevention.

Each issued connection_token is recorded with a TTL. Attempting to issue a
second license for the same token raises ValueError. Entries expire after
TTL_SECONDS (default 10 min, 2x the Positron +/-5 min window).
"""

import asyncio
import time

TTL_SECONDS = 600  # 10 minutes


class TokenStore:
    """Thread-safe in-memory store that prevents double-issuance of tokens."""

    def __init__(self, ttl_seconds: int = TTL_SECONDS):
        self._ttl = ttl_seconds
        self._issued: dict[str, float] = {}  # token -> expiry monotonic time
        self._lock = asyncio.Lock()

    async def record(self, token: str) -> None:
        """
        Record that a license has been issued for this token.

        Raises ValueError if a license for this token was already issued and
        has not yet expired.
        """
        async with self._lock:
            self._evict()
            if token in self._issued:
                raise ValueError(f"Token already issued: {token!r}")
            self._issued[token] = time.monotonic() + self._ttl

    def _evict(self) -> None:
        now = time.monotonic()
        self._issued = {t: exp for t, exp in self._issued.items() if exp > now}

    async def size(self) -> int:
        async with self._lock:
            self._evict()
            return len(self._issued)
