"""Payment Webhook Receiver Views.

Provides:
1. MomoWebhookView: Unified Mobile Money webhook receiver with automatic aggregator detection
   (Paystack vs. Hubtel), constant-time HMAC signature verification (MUC-1.2), and audit logging.
2. PaystackWebhookView: Provider-specific receiver enforcing Paystack HMAC-SHA512 verification.
3. HubtelWebhookView: Provider-specific receiver enforcing Hubtel HMAC-SHA256 verification.
"""

import json
import logging
from typing import Any

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.gateways import (
    BasePaymentGateway,
    HubtelGateway,
    PaystackGateway,
    get_payment_gateway,
)
from apps.payments.models import PaymentWebhookLog, WebhookStatusChoices
from apps.payments.services.idempotency import IdempotencyService

logger = logging.getLogger(__name__)


def extract_safe_headers(request: Request) -> dict[str, str]:
    """Extracts diagnostic headers for security forensics, omitting sensitive auth tokens."""
    safe_keys = {
        "HTTP_X_PAYSTACK_SIGNATURE",
        "HTTP_X_HUBTEL_SIGNATURE",
        "HTTP_X_SIGNATURE",
        "CONTENT_TYPE",
        "HTTP_USER_AGENT",
        "REMOTE_ADDR",
    }
    return {k: str(v) for k, v in request.META.items() if k in safe_keys}


class BaseWebhookReceiverView(APIView):
    """Base class for payment webhook receivers with constant-time HMAC verification and logging."""

    permission_classes = [AllowAny]
    authentication_classes = []  # Server-to-server callbacks do not use client session cookies

    def get_gateway(self, request: Request) -> BasePaymentGateway:
        """Resolves the appropriate payment gateway for the request."""
        raise NotImplementedError

    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Receives, cryptographically verifies, parses, and logs the payment callback."""
        raw_body = request.body
        headers_snapshot = extract_safe_headers(request)

        # 1. Resolve Gateway Adapter
        gateway = self.get_gateway(request)

        # 2. Extract Signature Header
        sig_name = gateway.signature_header_name
        # Convert to META key (e.g. 'x-paystack-signature' -> 'HTTP_X_PAYSTACK_SIGNATURE')
        meta_key = "HTTP_" + sig_name.upper().replace("-", "_")
        signature = request.META.get(meta_key) or request.headers.get(sig_name)

        # Parse JSON payload defensively for logging
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            payload = {"raw": raw_body.decode("utf-8", errors="replace")}

        # 3. Missing Signature Gate (MUC-1.2)
        if not signature:
            logger.warning(
                f"[{gateway.provider_name}] Webhook rejected: missing '{sig_name}' header."
            )
            PaymentWebhookLog.objects.create(
                provider=gateway.provider_name,
                status=WebhookStatusChoices.FAILED_SIGNATURE,
                signature_header="",
                payload=payload,
                headers=headers_snapshot,
                error_message=f"Missing signature header '{sig_name}'",
            )
            return Response(
                {"detail": f"Missing signature header '{sig_name}'."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 4. Cryptographic Constant-Time HMAC Verification (MUC-1.2)
        is_valid = gateway.verify_signature(raw_body=raw_body, signature=signature)
        if not is_valid:
            logger.warning(
                f"[{gateway.provider_name}] Webhook rejected: HMAC signature verification failed."
            )
            PaymentWebhookLog.objects.create(
                provider=gateway.provider_name,
                status=WebhookStatusChoices.FAILED_SIGNATURE,
                signature_header=signature,
                payload=payload,
                headers=headers_snapshot,
                error_message="Invalid HMAC signature (constant-time verification mismatch)",
            )
            return Response(
                {"detail": "Invalid signature."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 5. Normalization & Event Parsing
        try:
            event = gateway.parse_webhook(payload)
        except Exception as exc:
            logger.error(f"[{gateway.provider_name}] Error parsing webhook payload: {exc}")
            PaymentWebhookLog.objects.create(
                provider=gateway.provider_name,
                status=WebhookStatusChoices.VERIFIED,
                signature_header=signature,
                payload=payload,
                headers=headers_snapshot,
                error_message=f"Normalization warning: {exc}",
            )
            return Response({"status": "received"}, status=status.HTTP_200_OK)

        # 6. Distributed Atomic Idempotency Lock (SET momo:evt:{provider}:{event_id} EX 60 NX)
        lock_key = IdempotencyService.format_event_key(
            provider=gateway.provider_name,
            event_id=event.event_id,
            raw_body=raw_body,
        )
        acquired = IdempotencyService.acquire_lock(lock_key)
        if not acquired:
            logger.info(
                f"[{gateway.provider_name}] Duplicate webhook detected for lock '{lock_key}'. "
                "Discarding with HTTP 200 without reprocessing."
            )
            PaymentWebhookLog.objects.create(
                provider=gateway.provider_name,
                event_id=event.event_id,
                event_type=payload.get("event", "payment_callback"),
                signature_header=signature,
                status=WebhookStatusChoices.IGNORED,
                payload=payload,
                headers=headers_snapshot,
                error_message=f"Duplicate event discarded: idempotency lock active on '{lock_key}'",
            )
            return Response(
                {
                    "status": "ignored",
                    "detail": "Duplicate webhook event already processed or in progress.",
                    "event_id": event.event_id,
                    "provider": gateway.provider_name,
                },
                status=status.HTTP_200_OK,
            )

        # 7. Downstream Event Processing & Reconciliation Hook (Feature 4.3)
        self.process_payment_event(event)

        # 8. Record Verified Audit Log
        PaymentWebhookLog.objects.create(
            provider=gateway.provider_name,
            event_id=event.event_id,
            event_type=payload.get("event", "payment_callback"),
            signature_header=signature,
            status=WebhookStatusChoices.VERIFIED,
            payload=payload,
            headers=headers_snapshot,
        )

        logger.info(
            f"[{gateway.provider_name}] Verified payment webhook: event_id={event.event_id}, "
            f"ref={event.reference}, amount={event.amount} {event.currency}"
        )

        return Response(
            {
                "status": "success",
                "provider": gateway.provider_name,
                "event_id": event.event_id,
                "reference": event.reference,
            },
            status=status.HTTP_200_OK,
        )

    def process_payment_event(self, event: Any) -> None:
        """Hook for downstream reconciliation and general ledger posting (Feature 4.3)."""
        # In Feature 4.3, this will delegate to ReconciliationService.reconcile_payment(event)
        pass


class MomoWebhookView(BaseWebhookReceiverView):
    """Unified Mobile Money webhook receiver.

    Auto-detects aggregator (Paystack vs Hubtel) based on incoming headers or parameters.
    """

    def get_gateway(self, request: Request) -> BasePaymentGateway:
        # Check header indicators
        if "HTTP_X_PAYSTACK_SIGNATURE" in request.META or "x-paystack-signature" in request.headers:
            return get_payment_gateway("paystack")
        elif "HTTP_X_HUBTEL_SIGNATURE" in request.META or "x-hubtel-signature" in request.headers:
            return get_payment_gateway("hubtel")

        # Check query param
        provider_param = request.query_params.get("provider", "").lower()
        if provider_param in ("hubtel", "mock_hubtel"):
            return get_payment_gateway("hubtel")

        # Default fallback
        return get_payment_gateway("paystack")


class PaystackWebhookView(BaseWebhookReceiverView):
    """Dedicated Paystack webhook receiver enforcing HMAC-SHA512 verification."""

    def get_gateway(self, request: Request) -> BasePaymentGateway:
        return PaystackGateway()


class HubtelWebhookView(BaseWebhookReceiverView):
    """Dedicated Hubtel webhook receiver enforcing HMAC-SHA256 verification."""

    def get_gateway(self, request: Request) -> BasePaymentGateway:
        return HubtelGateway()
