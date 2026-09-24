"""Django REST Framework Serializers for Invoicing Domain.

Handles validation and serialization for:
1. Contact records (Customers & Suppliers).
2. InvoiceLine creation and detail rendering.
3. Invoice creation, drafting, and detailed DTO presentation.
"""

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.invoicing.models import Contact, Invoice, InvoiceLine
from apps.tenancy.models import TaxSchemeChoices


class ContactSerializer(serializers.ModelSerializer):
    """Serializer for Contact entities (Customers & Suppliers)."""

    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "contact_type",
            "tin",
            "ghana_card_number",
            "billing_address",
            "phone",
            "email",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class InvoiceLineCreateSerializer(serializers.Serializer):
    """Input serializer for invoice itemized billing lines."""

    description = serializers.CharField(max_length=255, required=True)
    quantity = serializers.DecimalField(
        max_digits=12,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=True,
    )
    unit_price = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0000"),
        required=True,
    )
    account_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    supply_type = serializers.ChoiceField(
        choices=TaxSchemeChoices.choices,
        default=TaxSchemeChoices.STANDARD,
    )


class InvoiceCreateSerializer(serializers.Serializer):
    """Input serializer for invoice compilation and issuance."""

    customer_id = serializers.UUIDField(required=True)
    issue_date = serializers.DateField(required=True)
    due_date = serializers.DateField(required=True)
    currency = serializers.CharField(max_length=3, default="GHS")
    action = serializers.ChoiceField(
        choices=["issue", "save_draft"],
        default="issue",
        help_text="'issue' posts to GL and marks PENDING_GRA; 'save_draft' saves as DRAFT.",
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = serializers.ListSerializer(
        child=InvoiceLineCreateSerializer(),
        min_length=1,
        help_text="At least one item line is required.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validates chronological date invariant (due_date >= issue_date)."""
        issue_date = attrs.get("issue_date")
        due_date = attrs.get("due_date")

        if issue_date and due_date and due_date < issue_date:
            raise serializers.ValidationError(
                {"due_date": "Due date cannot precede the issue tax point date."}
            )

        return attrs


class InvoiceLineDetailSerializer(serializers.ModelSerializer):
    """Output serializer for detailed line items."""

    account_code = serializers.CharField(source="account.account_code", read_only=True)
    account_name = serializers.CharField(source="account.account_name", read_only=True)

    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "description",
            "quantity",
            "unit_price",
            "vat_rate",
            "nhil_rate",
            "getfund_rate",
            "vat_amount",
            "nhil_amount",
            "getfund_amount",
            "line_total",
            "account_id",
            "account_code",
            "account_name",
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(serializers.ModelSerializer):
    """Comprehensive DTO for Invoice detail views and API responses."""

    lines = InvoiceLineDetailSerializer(many=True, read_only=True)
    balance_due = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    is_cleared = serializers.BooleanField(read_only=True)
    customer_id = serializers.UUIDField(source="customer.id", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "payment_reference",
            "share_token",
            "customer_id",
            "issue_date",
            "due_date",
            "status",
            "currency",
            "subtotal_amount",
            "vat_amount",
            "nhil_amount",
            "getfund_amount",
            "covid_levy_amount",
            "total_amount",
            "paid_amount",
            "balance_due",
            "is_cleared",
            # Legal point-in-time customer snapshot
            "customer_name",
            "customer_tin",
            "customer_ghana_card",
            "customer_address",
            "customer_phone",
            "customer_email",
            "snapshot_frozen_at",
            # GRA E-VAT fields
            "gra_clearance_code",
            "gra_qr_code",
            "gra_submitted_at",
            "gra_cleared_at",
            "pdf_url",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class InvoiceListSerializer(serializers.ModelSerializer):
    """Concise DTO for paginated invoice listings."""

    balance_due = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    customer_id = serializers.UUIDField(source="customer.id", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "payment_reference",
            "share_token",
            "customer_id",
            "customer_name",
            "issue_date",
            "due_date",
            "status",
            "currency",
            "subtotal_amount",
            "total_amount",
            "paid_amount",
            "balance_due",
            "created_at",
        ]
        read_only_fields = fields
