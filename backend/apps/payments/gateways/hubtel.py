"""Hubtel Payment Gateway Adapter.

Implements:
1. HMAC-SHA256 signature verification over raw request body in constant time.
2. Parsing and normalization for Hubtel Merchant payment callbacks.
3. Extraction of ClientReference (Luhn sequence code) and Decimal GHS amounts.
"""

import hashlib
import hmac
import logging
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.utils.dateparse import parse_datetime

from apps.payments.gateways.base import BasePaymentGateway, NormalizedPaymentEvent

logger = logging.getLogger(__name__)


class HubtelGateway(BasePaymentGateway):
    """Hubtel Ghana Mobile Money Aggregator Adapter."""

    provider_name: str = "hubtel"
    signature_header_name: str = "x-hubtel-signature"

    def __init__(self, client_secret: str | None = None) -> None:
        self.client_secret = client_secret or getattr(
            settings, "HUBTEL_CLIENT_SECRET", "mock_hubtel_secret_key"
        )

    def generate_signature(self, raw_body: bytes, secret: str | None = None) -> str:
        """Generates HMAC-SHA256 hex signature for Hubtel payload bytes."""
        key = (secret or self.client_secret).encode("utf-8")
        return hmac.new(key, raw_body, hashlib.sha256).hexdigest()

    def verify_signature(
        self,
        raw_body: bytes,
        signature: str | None,
        secret: str | None = None,
    ) -> bool:
        """Cryptographically verifies Hubtel HMAC-SHA256 signature in constant time.

        Parameters:
            raw_body: Exact raw request payload bytes.
            signature: Hex signature string from 'x-hubtel-signature' header.
            secret: Optional override secret key.

        Returns:
            True if signature matches; False otherwise.
        """
        if not signature or not signature.strip():
            logger.warning("[HubtelGateway] Missing signature header.")
            return False

        key = (secret or self.client_secret).encode("utf-8")
        expected_sig = hmac.new(key, raw_body, hashlib.sha256).hexdigest()

        # Constant-time comparison to prevent timing attacks (MUC-1.2)
        return hmac.compare_digest(expected_sig.lower(), signature.strip().lower())

    def parse_webhook(self, payload: dict[str, Any]) -> NormalizedPaymentEvent:
        """Normalizes Hubtel webhook payload into universal NormalizedPaymentEvent.

        Handles both standard Hubtel callback envelopes (with nested 'Data') and flat callbacks.
        """
        data = payload.get("Data", {}) if isinstance(payload.get("Data"), dict) else payload

        event_id = (
            str(data.get("TransactionId", ""))
            or str(payload.get("TransactionId", ""))
            or str(data.get("PaymentId", ""))
        )
        reference = (
            data.get("ClientReference", "")
            or payload.get("ClientReference", "")
            or data.get("ExternalTransactionId", "")
        )

        amount_raw = data.get("Amount", payload.get("Amount", 0))
        try:
            amount_ghs = Decimal(str(amount_raw))
        except Exception:
            amount_ghs = Decimal("0.00")

        raw_status = (
            data.get("Status", "") or payload.get("Status", "") or payload.get("ResponseCode", "")
        )
        status = (
            "success"
            if str(raw_status).lower() in ("success", "paid", "0000", "00")
            else str(raw_status)
        )

        phone = data.get("CustomerMobileNumber", "") or payload.get("CustomerMobileNumber", "")
        date_str = data.get("PaymentDate", "") or payload.get("PaymentDate", "")
        paid_at = parse_datetime(date_str) if date_str else None

        return NormalizedPaymentEvent(
            event_id=str(event_id),
            provider=self.provider_name,
            reference=str(reference),
            amount=amount_ghs,
            currency="GHS",
            status=status,
            customer_phone=str(phone),
            customer_email="",
            paid_at=paid_at,
            raw_payload=payload,
        )
