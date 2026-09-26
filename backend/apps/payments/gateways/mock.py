"""Deterministic Mock Payment Gateway Adapters.

Provides:
1. MockPaystackGateway: Deterministic adapter for Paystack callbacks and signature generation.
2. MockHubtelGateway: Deterministic adapter for Hubtel callbacks and signature generation.
"""

import json
from decimal import Decimal
from typing import Any

from apps.payments.gateways.hubtel import HubtelGateway
from apps.payments.gateways.paystack import PaystackGateway

MOCK_PAYSTACK_SECRET = "sk_test_mock_paystack_secret_key"
MOCK_HUBTEL_SECRET = "mock_hubtel_secret_key"


class MockPaystackGateway(PaystackGateway):
    """Deterministic Mock Gateway for Paystack Ghana."""

    def __init__(self, secret_key: str = MOCK_PAYSTACK_SECRET) -> None:
        super().__init__(secret_key=secret_key)

    def create_mock_webhook_payload(
        self,
        reference: str,
        amount_ghs: Decimal | float | str,
        event_id: str = "evt_mock_paystack_1001",
        status: str = "success",
        customer_email: str = "test.payer@example.com",
        customer_phone: str = "+233241234567",
    ) -> tuple[dict[str, Any], bytes, str]:
        """Constructs a deterministic mock Paystack webhook payload and valid signature.

        Returns:
            Tuple of (payload_dict, raw_bytes, valid_signature_header).
        """
        pesewas = int(Decimal(str(amount_ghs)) * Decimal("100"))
        payload = {
            "event": "charge.success",
            "data": {
                "id": event_id,
                "domain": "test",
                "status": status,
                "reference": reference,
                "amount": pesewas,
                "message": None,
                "gateway_response": "Successful",
                "paid_at": "2026-09-26T01:00:00.000Z",
                "channel": "mobile_money",
                "currency": "GHS",
                "customer": {
                    "id": 99999,
                    "email": customer_email,
                    "phone": customer_phone,
                },
            },
        }
        raw_bytes = json.dumps(payload).encode("utf-8")
        signature = self.generate_signature(raw_bytes)
        return payload, raw_bytes, signature


class MockHubtelGateway(HubtelGateway):
    """Deterministic Mock Gateway for Hubtel Ghana."""

    def __init__(self, client_secret: str = MOCK_HUBTEL_SECRET) -> None:
        super().__init__(client_secret=client_secret)

    def create_mock_webhook_payload(
        self,
        reference: str,
        amount_ghs: Decimal | float | str,
        event_id: str = "hubtel_tx_mock_2002",
        status: str = "Success",
        customer_phone: str = "0241234567",
    ) -> tuple[dict[str, Any], bytes, str]:
        """Constructs a deterministic mock Hubtel webhook payload and valid signature.

        Returns:
            Tuple of (payload_dict, raw_bytes, valid_signature_header).
        """
        payload = {
            "ResponseCode": "0000",
            "Status": status,
            "Data": {
                "TransactionId": event_id,
                "ClientReference": reference,
                "Amount": float(Decimal(str(amount_ghs))),
                "Charges": 0.00,
                "AmountAfterCharges": float(Decimal(str(amount_ghs))),
                "CustomerMobileNumber": customer_phone,
                "PaymentDate": "2026-09-26T01:00:00Z",
            },
        }
        raw_bytes = json.dumps(payload).encode("utf-8")
        signature = self.generate_signature(raw_bytes)
        return payload, raw_bytes, signature
