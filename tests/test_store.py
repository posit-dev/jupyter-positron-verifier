"""Tests for the TokenStore replay-prevention store."""

import asyncio
import time

import pytest

from jupyter_positron_verifier.store import TokenStore


async def test_record_new_token():
    store = TokenStore()
    await store.record("tok-1")
    assert await store.size() == 1


async def test_record_duplicate_raises():
    store = TokenStore()
    await store.record("tok-dup")
    with pytest.raises(ValueError, match="already issued"):
        await store.record("tok-dup")


async def test_record_different_tokens_both_stored():
    store = TokenStore()
    await store.record("tok-a")
    await store.record("tok-b")
    assert await store.size() == 2


async def test_expired_token_can_be_reissued():
    store = TokenStore(ttl_seconds=0)  # immediate expiry
    await store.record("tok-exp")
    await asyncio.sleep(0)  # yield so eviction runs on next record
    # After TTL expires, a new record should succeed.
    await store.record("tok-exp")
