"""Base Payment Gateway Interface and Data Transfer Objects.

Defines:
1. NormalizedPaymentEvent: Universal DTO for Mobile Money and card payment events.
2. BasePaymentGateway: Abstract Base Class defining HMAC verification, payload normalization,
   and deterministic signature generation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class NormalizedPaymentEvent:
    """Universal payment event DTO decoupling aggregator schemas from Mage Books domain."""

    event_id: str
    provider: str
    reference: str
    amount: Decimal
    currency: str = "GHS"
    status: str = "success"
    customer_phone: str = ""
    customer_email: str = ""
    paid_at: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class BasePaymentGateway(ABC):
    """Abstract Base Class for Payment Gateway Aggregators (Paystack, Hubtel, MTN MoMo)."""

    provider_name: str = "generic"
    signature_header_name: str = "x-signature"

    @abstractmethod
    def verify_signature(
        self,
        raw_body: bytes,
        signature: str | None,
        secret: str | None = None,
    ) -> bool:
        """Cryptographically verifies incoming webhook signature in constant time.

        Uses hmac.compare_digest to prevent timing attacks.

        Parameters:
            raw_body: Exact raw request payload bytes.
            signature: Signature string sent in HTTP header.
            secret: Optional override secret. If None, uses configured settings secret.

        Returns:
            True if signature matches; False otherwise.
        """
        pass

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> NormalizedPaymentEvent:
        """Parses aggregator-specific JSON payload into NormalizedPaymentEvent.

        Parameters:
            payload: Deserialized JSON payload dictionary.

        Returns:
            NormalizedPaymentEvent containing standardized payment fields.
        """
        pass

    @abstractmethod
    def generate_signature(
        self,
        raw_body: bytes,
        secret: str | None = None,
    ) -> str:
        """Generates valid signature for mock callbacks, tests, and verification checks.

        Parameters:
            raw_body: Payload bytes to sign.
            secret: Secret key to use.

        Returns:
            Hex-encoded signature string.
        """
        pass
