"""Distributed Idempotency Service for Mobile Money Webhooks.

Provides:
1. Distributed atomic locking using Redis (SET momo:evt:{provider}:{event_id} EX 60 NX).
2. Provider-namespaced key generation preventing cross-provider ID collisions (Paystack vs Hubtel).
3. Thread-safe MockRedisClient for deterministic offline testing and local development (Rule 4 & 5).
4. Graceful connection degradation on Redis connection drops (prevents HTTP 500 outages).
"""

import hashlib
import logging
import threading
import time
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


class MockRedisClient:
    """Thread-safe, in-memory mock Redis client supporting atomic 'SET key value EX ttl NX'."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[str, float]] = {}

    def set(
        self,
        name: str,
        value: Any,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        """Simulates Redis 'SET key value [EX seconds] [NX]'."""
        with self._lock:
            now = time.monotonic()
            # Clean expired keys
            if name in self._store:
                _, expire_at = self._store[name]
                if now >= expire_at:
                    del self._store[name]

            if nx and name in self._store:
                # Key already exists and has not expired; NX fails
                return None

            ttl = ex if ex is not None else 60
            self._store[name] = (str(value), now + ttl)
            return True

    def get(self, name: str) -> str | None:
        """Retrieves value if not expired."""
        with self._lock:
            now = time.monotonic()
            if name in self._store:
                val, expire_at = self._store[name]
                if now < expire_at:
                    return val
                del self._store[name]
            return None

    def delete(self, *names: str) -> int:
        """Deletes keys."""
        deleted = 0
        with self._lock:
            for name in names:
                if name in self._store:
                    del self._store[name]
                    deleted += 1
        return deleted

    def exists(self, name: str) -> bool:
        """Checks if key exists and is unexpired."""
        return self.get(name) is not None

    def clear(self) -> None:
        """Clears all stored keys."""
        with self._lock:
            self._store.clear()


# Module-level singletons
_mock_redis_instance = MockRedisClient()
_live_redis_client = None


def get_redis_client() -> Any:
    """Returns configured live Redis client or mock instance."""
    global _live_redis_client
    use_mock = getattr(settings, "USE_MOCK_REDIS", False)

    if use_mock:
        return _mock_redis_instance

    if _live_redis_client is None:
        try:
            import redis

            redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
            _live_redis_client = redis.from_url(redis_url, decode_responses=True)
        except Exception as exc:
            logger.warning(
                f"[IdempotencyService] Failed to initialize live Redis client ({exc}). "
                "Falling back to in-memory mock."
            )
            return _mock_redis_instance

    return _live_redis_client


class IdempotencyService:
    """Service managing distributed atomic locks for webhook callbacks."""

    DEFAULT_TTL = 60  # seconds

    @classmethod
    def format_event_key(
        cls,
        provider: str,
        event_id: str | None,
        raw_body: bytes | None = None,
    ) -> str:
        """Constructs a provider-namespaced idempotency key.

        Format:
            - With event_id: momo:evt:{provider}:{event_id}
            - Fallback (empty ID): momo:evt:{provider}:sha256:{body_hash}
        """
        clean_provider = (provider or "generic").lower().strip()
        clean_id = (event_id or "").strip()

        if clean_id:
            return f"momo:evt:{clean_provider}:{clean_id}"

        # Fallback to payload body SHA-256 digest
        body_digest = (
            hashlib.sha256(raw_body).hexdigest() if raw_body else hashlib.sha256(b"").hexdigest()
        )
        return f"momo:evt:{clean_provider}:sha256:{body_digest}"

    @classmethod
    def acquire_lock(cls, key: str, timeout: int | None = None) -> bool:
        """Atomically acquires an idempotency lock using 'SET key 1 EX ttl NX'.

        Parameters:
            key: Namespaced idempotency key.
            timeout: Lock TTL in seconds (defaults to IDEMPOTENCY_LOCK_TTL or 60).

        Returns:
            True if lock was successfully acquired (first-time event).
            False if lock already exists (duplicate event).
        """
        ttl = timeout or getattr(settings, "IDEMPOTENCY_LOCK_TTL", cls.DEFAULT_TTL)
        client = get_redis_client()

        try:
            result = client.set(key, "1", ex=ttl, nx=True)
            return bool(result)
        except Exception as exc:
            # Graceful degradation on Redis outage: log and fallback to in-memory mock
            logger.error(
                f"[IdempotencyService] Redis error acquiring lock for '{key}': {exc}. "
                "Failing safe to in-memory lock."
            )
            fallback_result = _mock_redis_instance.set(key, "1", ex=ttl, nx=True)
            return bool(fallback_result)

    @classmethod
    def release_lock(cls, key: str) -> bool:
        """Releases an active idempotency lock."""
        client = get_redis_client()
        try:
            client.delete(key)
            return True
        except Exception as exc:
            logger.warning(f"[IdempotencyService] Error releasing lock '{key}': {exc}")
            _mock_redis_instance.delete(key)
            return False

    @classmethod
    def is_locked(cls, key: str) -> bool:
        """Inspects whether an idempotency lock is actively held."""
        client = get_redis_client()
        try:
            return bool(client.exists(key))
        except Exception:
            return _mock_redis_instance.exists(key)

    @classmethod
    def reset_mock_state(cls) -> None:
        """Resets in-memory mock store (used in test teardown)."""
        _mock_redis_instance.clear()
