"""Paystack Payment Gateway Adapter.

Implements:
1. HMAC-SHA512 signature verification over raw request body in constant time.
2. Parsing and normalization for Paystack 'charge.success' and related webhook events.
3. Conversion of Paystack pesewas to Ghanaian Cedis (GHS Decimal).
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


class PaystackGateway(BasePaymentGateway):
    """Paystack Ghana Mobile Money and Card Gateway Adapter."""

    provider_name: str = "paystack"
    signature_header_name: str = "x-paystack-signature"

    def __init__(self, secret_key: str | None = None) -> None:
        self.secret_key = secret_key or getattr(
            settings, "PAYSTACK_SECRET_KEY", "sk_test_mock_paystack_secret_key"
        )

    def generate_signature(self, raw_body: bytes, secret: str | None = None) -> str:
        """Generates HMAC-SHA512 hex signature for Paystack payload bytes."""
        key = (secret or self.secret_key).encode("utf-8")
        return hmac.new(key, raw_body, hashlib.sha512).hexdigest()

    def verify_signature(
        self,
        raw_body: bytes,
        signature: str | None,
        secret: str | None = None,
    ) -> bool:
        """Cryptographically verifies Paystack HMAC-SHA512 signature in constant time.

        Parameters:
            raw_body: Exact raw request payload bytes.
            signature: Hex signature string from 'x-paystack-signature' header.
            secret: Optional override secret key.

        Returns:
            True if signature matches; False otherwise.
        """
        if not signature or not signature.strip():
            logger.warning("[PaystackGateway] Missing signature header.")
            return False

        key = (secret or self.secret_key).encode("utf-8")
        expected_sig = hmac.new(key, raw_body, hashlib.sha512).hexdigest()

        # Constant-time comparison to prevent timing attacks (MUC-1.2)
        return hmac.compare_digest(expected_sig.lower(), signature.strip().lower())

    def parse_webhook(self, payload: dict[str, Any]) -> NormalizedPaymentEvent:
        """Normalizes Paystack webhook payload into universal NormalizedPaymentEvent.

        Paystack amounts are integers in pesewas (100 pesewas = 1 GHS).
        """
        data = payload.get("data", {})
        event_id = str(data.get("id", "")) or payload.get("id", "")
        reference = data.get("reference", "") or ""

        # Amount in pesewas -> GHS Decimal
        amount_raw = data.get("amount", 0)
        try:
            amount_pesewas = Decimal(str(amount_raw))
            amount_ghs = amount_pesewas / Decimal("100")
        except Exception:
            amount_ghs = Decimal("0.00")

        currency = data.get("currency", "GHS")
        paystack_status = data.get("status", "")
        status = "success" if paystack_status == "success" else paystack_status

        customer = data.get("customer", {})
        customer_email = customer.get("email", "") if isinstance(customer, dict) else ""
        customer_phone = customer.get("phone", "") if isinstance(customer, dict) else ""

        paid_at_str = data.get("paid_at") or data.get("paidAt")
        paid_at = parse_datetime(paid_at_str) if paid_at_str else None

        return NormalizedPaymentEvent(
            event_id=str(event_id),
            provider=self.provider_name,
            reference=reference,
            amount=amount_ghs,
            currency=currency,
            status=status,
            customer_phone=customer_phone,
            customer_email=customer_email,
            paid_at=paid_at,
            raw_payload=payload,
        )
