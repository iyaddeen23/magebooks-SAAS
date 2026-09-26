"""Tests for Payment Webhook Receivers and Gateway Adapters."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.payments.gateways import (
    HubtelGateway,
    MockHubtelGateway,
    MockPaystackGateway,
    PaystackGateway,
    get_payment_gateway,
)
from apps.payments.models import PaymentWebhookLog, WebhookStatusChoices


class PaymentGatewayAdapterTestCase(TestCase):
    """Unit tests for BasePaymentGateway implementations and Mock adapters."""

    def setUp(self) -> None:
        self.paystack_mock = MockPaystackGateway(secret_key="test_paystack_secret")
        self.hubtel_mock = MockHubtelGateway(client_secret="test_hubtel_secret")

    def test_mock_paystack_signature_generation_and_verification(self) -> None:
        payload, raw_bytes, signature = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
        )
        self.assertTrue(self.paystack_mock.verify_signature(raw_bytes, signature))
        self.assertFalse(self.paystack_mock.verify_signature(raw_bytes, "invalid_signature"))
        self.assertFalse(self.paystack_mock.verify_signature(raw_bytes, None))

    def test_mock_hubtel_signature_generation_and_verification(self) -> None:
        payload, raw_bytes, signature = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("500.50"),
        )
        self.assertTrue(self.hubtel_mock.verify_signature(raw_bytes, signature))
        self.assertFalse(self.hubtel_mock.verify_signature(raw_bytes, "wrong_sig"))
        self.assertFalse(self.hubtel_mock.verify_signature(raw_bytes, ""))

    def test_paystack_payload_parsing_and_pesewas_conversion(self) -> None:
        payload, _, _ = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
            event_id="evt_paystack_999",
        )
        event = self.paystack_mock.parse_webhook(payload)
        self.assertEqual(event.event_id, "evt_paystack_999")
        self.assertEqual(event.reference, "INV-10001-3")
        self.assertEqual(event.amount, Decimal("1200.00"))
        self.assertEqual(event.currency, "GHS")
        self.assertEqual(event.status, "success")

    def test_hubtel_payload_parsing(self) -> None:
        payload, _, _ = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-20002-8",
            amount_ghs=Decimal("750.25"),
            event_id="hubtel_tx_123",
        )
        event = self.hubtel_mock.parse_webhook(payload)
        self.assertEqual(event.event_id, "hubtel_tx_123")
        self.assertEqual(event.reference, "INV-20002-8")
        self.assertEqual(event.amount, Decimal("750.25"))
        self.assertEqual(event.status, "success")

    def test_get_payment_gateway_factory(self) -> None:
        gw_paystack = get_payment_gateway("paystack")
        self.assertIsInstance(gw_paystack, (PaystackGateway, MockPaystackGateway))

        gw_hubtel = get_payment_gateway("hubtel")
        self.assertIsInstance(gw_hubtel, (HubtelGateway, MockHubtelGateway))


class PaymentWebhookReceiverAPITestCase(TestCase):
    """Functional tests for Webhook Receiver API endpoints and database logging."""

    def setUp(self) -> None:
        self.client = APIClient()
        self.paystack_mock = MockPaystackGateway(secret_key="sk_test_mock_paystack_secret_key")
        self.hubtel_mock = MockHubtelGateway(client_secret="mock_hubtel_secret_key")

    def test_paystack_webhook_valid_signature_accepted(self) -> None:
        payload, raw_bytes, signature = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("1200.00"),
            event_id="evt_ps_test_101",
        )
        url = reverse("payments:paystack-webhook")
        response = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("status"), "success")
        self.assertEqual(response.data.get("event_id"), "evt_ps_test_101")

        # Verify database audit log
        log_entry = PaymentWebhookLog.objects.filter(event_id="evt_ps_test_101").first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.provider, "paystack")
        self.assertEqual(log_entry.status, WebhookStatusChoices.VERIFIED)
        self.assertEqual(log_entry.signature_header, signature)

    def test_hubtel_webhook_valid_signature_accepted(self) -> None:
        payload, raw_bytes, signature = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("850.00"),
            event_id="evt_hubtel_test_202",
        )
        url = reverse("payments:hubtel-webhook")
        response = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_HUBTEL_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("status"), "success")
        self.assertEqual(response.data.get("event_id"), "evt_hubtel_test_202")

        # Verify database audit log
        log_entry = PaymentWebhookLog.objects.filter(event_id="evt_hubtel_test_202").first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.provider, "hubtel")
        self.assertEqual(log_entry.status, WebhookStatusChoices.VERIFIED)

    def test_momo_webhook_autodetects_paystack_via_header(self) -> None:
        payload, raw_bytes, signature = self.paystack_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("300.00"),
            event_id="evt_momo_ps_303",
        )
        url = reverse("payments:momo-webhook")
        response = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("provider"), "paystack")

    def test_momo_webhook_autodetects_hubtel_via_header(self) -> None:
        payload, raw_bytes, signature = self.hubtel_mock.create_mock_webhook_payload(
            reference="INV-10001-3",
            amount_ghs=Decimal("450.00"),
            event_id="evt_momo_hubtel_404",
        )
        url = reverse("payments:momo-webhook")
        response = self.client.post(
            url,
            data=raw_bytes,
            content_type="application/json",
            HTTP_X_HUBTEL_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("provider"), "hubtel")

    def test_empty_payload_handled_gracefully(self) -> None:
        url = reverse("payments:paystack-webhook")
        response = self.client.post(
            url,
            data="",
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="dummy_signature",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_json_body_handled_gracefully(self) -> None:
        url = reverse("payments:hubtel-webhook")
        malformed_bytes = b"not-a-valid-json-string{["
        valid_sig = self.hubtel_mock.generate_signature(malformed_bytes)
        response = self.client.post(
            url,
            data=malformed_bytes,
            content_type="application/json",
            HTTP_X_HUBTEL_SIGNATURE=valid_sig,
        )
        # Signature is valid, parsing handles raw payload safely
        self.assertEqual(response.status_code, status.HTTP_200_OK)
