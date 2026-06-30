# core/utilities/jobs.py
"""
Shared lightweight job manager for all Utilities commands.

Handles per-user cooldowns, per-guild concurrency caps, per-key dedup with a
short in-memory TTL cache, and temp-file cleanup. No permanent storage — nothing
here is written to disk or DB. Everything lives in memory and expires.
"""
from __future__ import annotations

import os
import time
import asyncio
import contextlib

# hard ceilings (the spec's "strict limits"); providers may lower these
MAX_VIDEO_SECONDS = 600         # 10 min
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_TEXT_CHARS = 8000
CACHE_TTL = 600                 # 10 minutes


class CooldownError(Exception):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after


class BusyError(Exception):
    """Raised when a guild is at its concurrency cap for a job type."""


class JobManager:
    def __init__(self):
        # (job, user_id) -> ready_at
        self._cooldowns: dict[tuple[str, int], float] = {}
        # (job, guild_id) -> active count
        self._active: dict[tuple[str, int], int] = {}
        # cache_key -> (expires_at, value)
        self._cache: dict[str, tuple[float, object]] = {}

    # ---- cooldowns -------------------------------------------------------
    def check_cooldown(self, job: str, user_id: int, seconds: float) -> None:
        now = time.time()
        ready = self._cooldowns.get((job, user_id), 0)
        if now < ready:
            raise CooldownError(round(ready - now, 1))

    def arm_cooldown(self, job: str, user_id: int, seconds: float) -> None:
        self._cooldowns[(job, user_id)] = time.time() + seconds

    # ---- per-guild concurrency ------------------------------------------
    def _count(self, job: str, guild_id: int) -> int:
        return self._active.get((job, guild_id), 0)

    @contextlib.asynccontextmanager
    async def slot(self, job: str, guild_id: int, max_concurrent: int):
        """Acquire a concurrency slot for a guild+job, or raise BusyError."""
        if self._count(job, guild_id) >= max_concurrent:
            raise BusyError()
        self._active[(job, guild_id)] = self._count(job, guild_id) + 1
        try:
            yield
        finally:
            n = self._count(job, guild_id) - 1
            if n <= 0:
                self._active.pop((job, guild_id), None)
            else:
                self._active[(job, guild_id)] = n

    # ---- short-lived dedup cache ----------------------------------------
    def cache_get(self, key: str):
        ent = self._cache.get(key)
        if not ent:
            return None
        exp, val = ent
        if time.time() > exp:
            self._cache.pop(key, None)
            return None
        return val

    def cache_put(self, key: str, value, ttl: float = CACHE_TTL):
        self._cache[key] = (time.time() + ttl, value)

    def purge_expired(self):
        now = time.time()
        for k in [k for k, (exp, _) in self._cache.items() if now > exp]:
            self._cache.pop(k, None)

    # ---- temp file cleanup ----------------------------------------------
    @contextlib.contextmanager
    def temp_files(self):
        """Track temp paths and guarantee deletion on success/failure/cancel."""
        paths: list[str] = []
        try:
            yield paths
        finally:
            for p in paths:
                with contextlib.suppress(Exception):
                    if p and os.path.exists(p):
                        os.remove(p)


# a single shared instance the cogs import
manager = JobManager()
