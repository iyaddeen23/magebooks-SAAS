"""Unit tests for IdempotencyService and MockRedisClient."""

import time

from django.test import TestCase

from apps.payments.services.idempotency import IdempotencyService, MockRedisClient


class IdempotencyServiceTestCase(TestCase):
    """Tests for distributed idempotency locking and provider namespacing."""

    def setUp(self) -> None:
        IdempotencyService.reset_mock_state()

    def tearDown(self) -> None:
        IdempotencyService.reset_mock_state()

    def test_acquire_lock_first_time_succeeds(self) -> None:
        """First attempt to acquire lock on an event key must succeed."""
        key = "momo:evt:paystack:evt_1001"
        self.assertTrue(IdempotencyService.acquire_lock(key, timeout=60))

    def test_acquire_lock_duplicate_fails(self) -> None:
        """Subsequent attempt to acquire lock on the same active key must fail."""
        key = "momo:evt:paystack:evt_1002"
        self.assertTrue(IdempotencyService.acquire_lock(key, timeout=60))
        self.assertFalse(IdempotencyService.acquire_lock(key, timeout=60))

    def test_lock_expires_after_ttl(self) -> None:
        """Key becomes re-acquirable once the TTL expires."""
        mock_client = MockRedisClient()
        # Set with 0-second TTL
        mock_client.set("momo:evt:test:expire", "1", ex=0, nx=True)
        time.sleep(0.01)
        # Should be expired and re-acquirable
        self.assertTrue(mock_client.set("momo:evt:test:expire", "1", ex=60, nx=True))

    def test_format_event_key_fallback_on_empty_event_id(self) -> None:
        """When event ID is missing or empty, generates deterministic sha256 fallback key."""
        raw_body = b'{"amount": 1000, "customer": "Kofi"}'
        key = IdempotencyService.format_event_key(
            provider="paystack",
            event_id="",
            raw_body=raw_body,
        )
        self.assertTrue(key.startswith("momo:evt:paystack:sha256:"))
        self.assertEqual(len(key.split(":")[-1]), 64)  # 64-char hex SHA-256

        # Identical payload yields identical key
        key2 = IdempotencyService.format_event_key(
            provider="paystack",
            event_id=None,
            raw_body=raw_body,
        )
        self.assertEqual(key, key2)

    def test_provider_namespacing_prevents_id_collisions(self) -> None:
        """Asserts that identical event IDs from different providers do not collide."""
        key_paystack = IdempotencyService.format_event_key(
            provider="paystack",
            event_id="tx_12345",
        )
        key_hubtel = IdempotencyService.format_event_key(
            provider="hubtel",
            event_id="tx_12345",
        )

        self.assertEqual(key_paystack, "momo:evt:paystack:tx_12345")
        self.assertEqual(key_hubtel, "momo:evt:hubtel:tx_12345")
        self.assertNotEqual(key_paystack, key_hubtel)

        # Both can be locked simultaneously without collision
        self.assertTrue(IdempotencyService.acquire_lock(key_paystack))
        self.assertTrue(IdempotencyService.acquire_lock(key_hubtel))

    def test_release_lock_allows_reacquisition(self) -> None:
        """Releasing an active lock allows subsequent acquisition."""
        key = "momo:evt:paystack:release_test"
        self.assertTrue(IdempotencyService.acquire_lock(key))
        self.assertTrue(IdempotencyService.is_locked(key))

        IdempotencyService.release_lock(key)
        self.assertFalse(IdempotencyService.is_locked(key))
        self.assertTrue(IdempotencyService.acquire_lock(key))
