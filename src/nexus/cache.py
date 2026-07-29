"""Redis client.

Used for the credential revocation cache and, later, rate-limit counters.

The revocation cache is an optimisation, never an authority: a cache miss falls
through to the database rather than assuming the credential is fine. Getting
that backwards would mean a Redis outage silently disables revocation.
"""

from __future__ import annotations

from functools import lru_cache

import redis.asyncio as redis

from nexus.config import get_settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.from_url(get_settings().redis.url, decode_responses=True)
