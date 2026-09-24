"""Django admin registration for Invoicing models."""

from django.contrib import admin

from apps.invoicing.models import Contact, Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    fields = [
        "description",
        "quantity",
        "unit_price",
        "line_total",
        "is_taxable",
        "vat_amount",
        "nhil_amount",
        "getfund_amount",
    ]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_type", "tin", "phone", "email", "organization", "is_active"]
    list_filter = ["contact_type", "is_active", "organization"]
    search_fields = ["name", "tin", "ghana_card_number", "phone", "email"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "invoice_number",
        "payment_reference",
        "customer_name",
        "status",
        "issue_date",
        "due_date",
        "total_amount",
        "paid_amount",
        "organization",
    ]
    list_filter = ["status", "organization", "issue_date"]
    search_fields = [
        "invoice_number",
        "payment_reference",
        "customer_name",
        "customer_tin",
        "gra_clearance_code",
    ]
    inlines = [InvoiceLineInline]
    readonly_fields = [
        "share_token",
        "customer_name",
        "customer_tin",
        "customer_ghana_card",
        "customer_address",
        "customer_phone",
        "customer_email",
        "snapshot_frozen_at",
    ]
