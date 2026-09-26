"""Security Penetration and Misuse Case Tests for Payment Webhooks.

Validates:
- Misuse Case 1.2 (MUC-1.2: Forged Webhook HMAC Signature):
  Attacker attempts to post fake payment payloads to credit invoices without real funds.
- Constant-time cryptographic comparison (timing side-channel defense).
- Payload tampering detection (1-bit / 1-character difference rejects with HTTP 401).
- Audit trail logging for failed security intrusions.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.payments.gateways import MockHubtelGateway, MockPaystackGateway
from apps.payments.models import PaymentWebhookLog, WebhookStatusChoices


class WebhookHMACSecurityTestCase(TestCase):
    """Misuse Case 1.2: Forged HMAC Signature & Payload Tampering Penetration Suite."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.paystack_mock = MockPaystackGateway(secret_key="sk_test_mock_paystack_secret_key")
        self.hubtel_mock = MockHubtelGateway(client_secret="mock_hubtel_secret_key")

    def test_missing_signature_header_blocked_with_401(self) -> None:
        """Asserts that requests lacking the signature header are rejected with HTTP 401."""
        payload, raw_bytes, _ = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )
        url = reverse("payments:paystack-webhook")
        response = self.client.post(url, data=raw_bytes, content_type="application/json")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Missing signature header", response.data.get("detail", ""))

        # Verify failed security attempt is logged
        log = PaymentWebhookLog.objects.filter(status=WebhookStatusChoices.FAILED_SIGNATURE).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.provider, "paystack")
        self.assertIn("Missing signature", log.error_message)

    def test_forged_hmac_signature_blocked_with_401(self) -> None:
        """Asserts that fabricated/forged signatures are blocked with HTTP 401."""
        payload, raw_bytes, _ = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )
        forged_sig = "a" * 128  # 128 hex chars of dummy data
        url = reverse("payments:paystack-webhook")
        response = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=forged_sig,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get("detail"), "Invalid signature.")

        # Verify failed attempt is logged
        log = PaymentWebhookLog.objects.filter(status=WebhookStatusChoices.FAILED_SIGNATURE).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.signature_header, forged_sig)
        self.assertIn("Invalid HMAC signature", log.error_message)

    def test_tampered_payload_blocked_with_401(self) -> None:
        """Asserts that modifying 1 character in body invalidates HMAC (HTTP 401)."""
        payload, raw_bytes, valid_sig = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )

        # Attacker tampers with the reference in the payload
        tampered_bytes = raw_bytes.replace(b"INV-10001-3", b"INV-99999-9")

        url = reverse("payments:paystack-webhook")
        response = self.client.post(
            url,
            data=tampered_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=valid_sig,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get("detail"), "Invalid signature.")

    def test_tampered_amount_underpayment_attack_blocked_with_401(self) -> None:
        """Asserts that an attacker attempting to forge an amount is blocked with HTTP 401."""
        payload, raw_bytes, valid_sig = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )

        # Attacker paid GHS 1.00 but modifies JSON body to say GHS 1200.00
        # Or conversely, signed for GHS 1.00, but sends valid signature with tampered amount
        tampered_bytes = raw_bytes.replace(b"1200.0", b"1.0")

        url = reverse("payments:hubtel-webhook")
        response = self.client.post(
            url,
            data=tampered_bytes,
            content_type="application/json",
            HTTP_X_HUBTEL_SIGNATURE=valid_sig,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data.get("detail"), "Invalid signature.")

    def test_cross_provider_signature_mismatch_blocked(self) -> None:
        """Asserts that a valid Hubtel HMAC signature is rejected when sent to Paystack endpoint."""
        payload, raw_bytes, hubtel_sig = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("500.00"),
        )

        url = reverse("payments:paystack-webhook")
        response = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=hubtel_sig,
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_constant_time_comparison_used_in_verification(self) -> None:
        """Asserts that hmac.compare_digest is strictly invoked to prevent timing attacks."""
        payload, raw_bytes, valid_sig = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )

        with patch(
            "apps.payments.gateways.paystack.hmac.compare_digest", return_value=True
        ) as mock_cmp:
            is_valid = self.paystack_mock.verify_signature(raw_bytes, valid_sig)
            self.assertTrue(is_valid)
            self.assertTrue(mock_cmp.called)

    def test_unauthenticated_public_access_permitted_only_with_valid_hmac(self) -> None:
        """Asserts that webhooks are public endpoints, but strictly protected by HMAC."""
        # Ensure client is completely unauthenticated
        self.client.cookies.clear()
        self.client.credentials()

        payload, raw_bytes, valid_sig = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )

        url = reverse("payments:paystack-webhook")
        # Valid signature succeeds without login cookies
        response_ok = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=valid_sig,
        )
        self.assertEqual(response_ok.status_code, status.HTTP_200_OK)

        # Invalid signature fails without login cookies
        response_fail = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid",
        )
        self.assertEqual(response_fail.status_code, status.HTTP_401_UNAUTHORIZED)
