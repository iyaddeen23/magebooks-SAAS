"""Payment Gateway Adapters Package.

Exports:
1. NormalizedPaymentEvent
2. BasePaymentGateway
3. PaystackGateway
4. HubtelGateway
5. MockPaystackGateway
6. MockHubtelGateway
7. get_payment_gateway factory
"""

from typing import Literal

from django.conf import settings

from apps.payments.gateways.base import BasePaymentGateway, NormalizedPaymentEvent
from apps.payments.gateways.hubtel import HubtelGateway
from apps.payments.gateways.mock import MockHubtelGateway, MockPaystackGateway
from apps.payments.gateways.paystack import PaystackGateway


def get_payment_gateway(
    provider: Literal[
        "paystack", "hubtel", "mock_paystack", "mock_hubtel", "mock", "momo"
    ] = "paystack",
) -> BasePaymentGateway:
    """Factory to retrieve configured or mock payment gateway adapter."""
    active_mode = getattr(settings, "ACTIVE_PAYMENT_GATEWAY", "mock").lower()
    provider_lower = provider.lower()

    if provider_lower in ("hubtel", "mock_hubtel"):
        return (
            MockHubtelGateway()
            if active_mode == "mock" or provider_lower == "mock_hubtel"
            else HubtelGateway()
        )
    elif provider_lower in ("paystack", "mock_paystack", "mock", "momo"):
        return (
            MockPaystackGateway()
            if active_mode == "mock" or provider_lower == "mock_paystack"
            else PaystackGateway()
        )
    else:
        return MockPaystackGateway() if active_mode == "mock" else PaystackGateway()


__all__ = [
    "BasePaymentGateway",
    "HubtelGateway",
    "MockHubtelGateway",
    "MockPaystackGateway",
    "NormalizedPaymentEvent",
    "PaystackGateway",
    "get_payment_gateway",
]
