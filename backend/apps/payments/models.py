"""Payment Models for Mage Books SAAS.

Provides:
1. WebhookStatusChoices: Enumeration for webhook lifecycle states.
2. PaymentWebhookLog: Immutable audit log for incoming payment webhooks from aggregators
   (Paystack, Hubtel, MTN MoMo, Telecel Cash).
"""

import uuid6
from django.db import models


class WebhookStatusChoices(models.TextChoices):
    """Lifecycle status choices for incoming payment webhooks."""

    RECEIVED = "RECEIVED", "Received"
    VERIFIED = "VERIFIED", "Signature Verified"
    FAILED_SIGNATURE = "FAILED_SIGNATURE", "Signature Verification Failed"
    PROCESSED = "PROCESSED", "Processed"
    IGNORED = "IGNORED", "Ignored"


class PaymentWebhookLog(models.Model):
    """Immutable audit trail for incoming payment webhooks from aggregators.

    Stores the raw payload, headers, provider, event identifier, and verification status.
    Organization is nullable because failed or unauthenticated calls cannot be bound
    to a tenant until verified and resolved against internal invoices.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid6.uuid7,
        editable=False,
        help_text="Sequential UUIDv7 primary key.",
    )
    organization = models.ForeignKey(
        "tenancy.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_webhook_logs",
        help_text="Associated tenant organization once resolved from invoice reference.",
    )
    provider = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Payment gateway provider (e.g. 'paystack', 'hubtel', 'momo').",
    )
    event_id = models.CharField(
        max_length=255,
        db_index=True,
        blank=True,
        help_text="Aggregator event ID (e.g. Paystack event ID or Hubtel client reference).",
    )
    event_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="Type of webhook event (e.g. 'charge.success').",
    )
    signature_header = models.CharField(
        max_length=512,
        blank=True,
        help_text="Raw cryptographic signature header from the incoming request.",
    )
    status = models.CharField(
        max_length=50,
        choices=WebhookStatusChoices.choices,
        default=WebhookStatusChoices.RECEIVED,
        db_index=True,
        help_text="Current processing and verification status.",
    )
    payload = models.JSONField(
        default=dict,
        help_text="Parsed JSON body of the webhook callback.",
    )
    headers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Relevant HTTP request headers for security forensics.",
    )
    error_message = models.TextField(
        blank=True,
        help_text="Failure reason or security mismatch description if verification fails.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when the webhook was received.",
    )

    class Meta:
        db_table = "payment_webhook_logs"
        ordering = ["-created_at"]
        verbose_name = "Payment Webhook Log"
        verbose_name_plural = "Payment Webhook Logs"
        indexes = [
            models.Index(fields=["provider", "event_id"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        evt = self.event_id or "No-Event-ID"
        return f"[{self.provider}] {evt} ({self.status}) at {self.created_at}"
