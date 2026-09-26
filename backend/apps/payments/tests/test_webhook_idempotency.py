"""Integration and Abuse Tests for Distributed Webhook Idempotency Locking.

Validates:
1. Aggregator webhook retries are dropped with HTTP 200 without duplicate execution.
2. Failed HMAC attempts do not pollute the idempotency lock cache (Lock Pollution Defense).
3. Redis ConnectionError / TimeoutError degrades gracefully to in-memory fallback without HTTP 500.
4. Downstream reconciliation hooks are called strictly once across duplicate requests.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.payments.gateways import MockHubtelGateway, MockPaystackGateway
from apps.payments.models import PaymentWebhookLog, WebhookStatusChoices
from apps.payments.services.idempotency import IdempotencyService


class WebhookIdempotencyTestCase(TestCase):
    """Integration and resilience suite for webhook deduplication."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.paystack_mock = MockPaystackGateway(secret_key="sk_test_mock_paystack_secret_key")
        self.hubtel_mock = MockHubtelGateway(client_secret="mock_hubtel_secret_key")
        IdempotencyService.reset_mock_state()

    def tearDown(self) -> None:
        IdempotencyService.reset_mock_state()

    def test_webhook_replay_exact_payload_returns_200_and_drops_duplicate(self) -> None:
        """Replaying exact same webhook event twice returns HTTP 200, dropping the duplicate."""
        payload, raw_bytes, sig = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
            event_id="evt_replay_test_101",
        )
        url = reverse("payments:paystack-webhook")

        # First delivery: processed & verified
        resp1 = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data.get("status"), "success")

        # Second delivery (replay): discarded with HTTP 200
        resp2 = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data.get("status"), "ignored")
        self.assertIn("Duplicate", resp2.data.get("detail", ""))

        # Verify audit logs in database: 1 VERIFIED, 1 IGNORED
        logs = list(
            PaymentWebhookLog.objects.filter(event_id="evt_replay_test_101").order_by("created_at")
        )
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].status, WebhookStatusChoices.VERIFIED)
        self.assertEqual(logs[1].status, WebhookStatusChoices.IGNORED)
        self.assertIn("Duplicate event discarded", logs[1].error_message)

    def test_different_event_ids_both_succeed(self) -> None:
        """Different webhook events process independently without cross-locking."""
        url = reverse("payments:paystack-webhook")

        payload1, raw1, sig1 = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
            event_id="evt_tx_alpha",
        )
        resp1 = self.client.post(
            url,
            data=raw1,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig1,
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data.get("status"), "success")

        payload2, raw2, sig2 = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-20002-8",
            amount_ghs=Decimal("550.00"),
            event_id="evt_tx_beta",
        )
        resp2 = self.client.post(
            url,
            data=raw2,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig2,
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data.get("status"), "success")

    def test_failed_hmac_does_not_acquire_or_pollute_idempotency_lock(self) -> None:
        """Attacker with forged HMAC signature must NOT acquire the lock, preventing DoS."""
        payload, raw_bytes, _ = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
            event_id="evt_target_victim_100",
        )
        url = reverse("payments:paystack-webhook")

        # Attacker sends forged signature
        resp_attack = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="forged_signature_hex",
        )
        self.assertEqual(resp_attack.status_code, status.HTTP_401_UNAUTHORIZED)

        # Assert the lock was NOT acquired
        lock_key = IdempotencyService.format_event_key(
            provider="paystack",
            event_id="evt_target_victim_100",
        )
        self.assertFalse(IdempotencyService.is_locked(lock_key))

        # Legitimate aggregator callback with valid signature can now succeed unhindered
        valid_sig = self.paystack_mock.generate_signature(raw_bytes)
        resp_legit = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=valid_sig,
        )
        self.assertEqual(resp_legit.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_legit.data.get("status"), "success")

    def test_redis_connection_error_falls_back_gracefully(self) -> None:
        """Simulates Redis connection failure; asserts webhook succeeds via memory fallback."""
        payload, raw_bytes, sig = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("800.00"),
            event_id="hubtel_fallback_tx",
        )
        url = reverse("payments:hubtel-webhook")

        # Mock Redis client raising ConnectionError
        broken_client = MagicMock()
        broken_client.set.side_effect = ConnectionError("Redis connection refused")

        with patch(
            "apps.payments.services.idempotency.get_redis_client", return_value=broken_client
        ):
            response = self.client.post(
                url,
                data=raw_bytes,
                content_type="application/json",
                HTTP_X_HUBTEL_SIGNATURE=sig,
            )
            # Must NOT return HTTP 500
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data.get("status"), "success")

    def test_duplicate_webhook_triggers_reconciliation_hook_exactly_once(self) -> None:
        """Asserts that downstream processing is invoked strictly 1 time across retried webhooks."""
        payload, raw_bytes, sig = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
            event_id="evt_hook_test_once",
        )
        url = reverse("payments:paystack-webhook")

        with patch(
            "apps.payments.views.BaseWebhookReceiverView.process_payment_event"
        ) as mock_process:
            # First request
            self.client.post(
                url,
                data=raw_bytes,
                content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=sig,
            )
            # Duplicate request
            self.client.post(
                url,
                data=raw_bytes,
                content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=sig,
            )

            # Assert called strictly ONCE
            self.assertEqual(mock_process.call_count, 1)
