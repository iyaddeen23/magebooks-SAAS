"""Invoicing and Accounts Receivable models for Mage Books SAAS.

Implements:
1. Contact model: Customers and Suppliers with Ghanaian TIN and Ghana Card PIN.
2. Invoice model: B2B/B2C billing with composite tenant foreign key
   ((organization_id, customer_id) -> contacts).
3. Immutable point-in-time customer legal snapshot (legal name, TIN/Ghana Card PIN, address).
4. Statutory Act 1151 tax fields (15% VAT, 2.5% NHIL, 2.5% GETFund; 0% abolished COVID levy).
5. Public UUIDv4 bearer token for guest viewing and Luhn-compatible sequence reference.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import BaseTenantModel, PublicShareableMixin
from apps.tax.services import (
    STATUTORY_GETFUND_RATE,
    STATUTORY_NHIL_RATE,
    STATUTORY_VAT_RATE,
)

ZERO_MONEY = Decimal("0.0000")


class ContactTypeChoices(models.TextChoices):
    """Classification of business contacts."""

    CUSTOMER = "CUSTOMER", "Customer"
    SUPPLIER = "SUPPLIER", "Supplier"
    BOTH = "BOTH", "Customer & Supplier"


class Contact(BaseTenantModel):
    """Business contact entity representing customers and suppliers within a tenant."""

    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Legal commercial or individual name.",
    )
    contact_type = models.CharField(
        max_length=20,
        choices=ContactTypeChoices.choices,
        default=ContactTypeChoices.CUSTOMER,
        db_index=True,
        help_text="Relationship classification.",
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Primary phone number (e.g. +233240000000).",
    )
    email = models.EmailField(
        max_length=255,
        blank=True,
        help_text="Primary billing email address.",
    )
    tin = models.CharField(
        max_length=20,
        blank=True,
        help_text="Ghanaian Taxpayer Identification Number (e.g. C0001234567).",
    )
    ghana_card_number = models.CharField(
        max_length=25,
        blank=True,
        help_text="Ghana Card National ID PIN (e.g. GHA-123456789-0).",
    )
    billing_address = models.TextField(
        blank=True,
        help_text="Physical or postal billing address for tax invoices.",
    )
    currency = models.CharField(
        max_length=3,
        default="GHS",
        help_text="ISO 4217 currency code.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Soft-activation flag. Inactive contacts cannot accept new invoices.",
    )

    class Meta(BaseTenantModel.Meta):
        db_table = "contacts"
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"
        ordering = ["name"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_org_contact_name",
            )
        ]

    def clean(self) -> None:
        super().clean()
        from apps.invoicing.validators import validate_ghana_card, validate_gra_tin

        if self.tin:
            try:
                self.tin = validate_gra_tin(self.tin)
            except ValidationError as exc:
                raise ValidationError({"tin": exc.message}) from exc

        if self.ghana_card_number:
            try:
                self.ghana_card_number = validate_ghana_card(self.ghana_card_number)
            except ValidationError as exc:
                raise ValidationError({"ghana_card_number": exc.message}) from exc

    def __str__(self) -> str:
        return f"{self.name} ({self.get_contact_type_display()}) [{self.organization.name}]"


class InvoiceStatusChoices(models.TextChoices):
    """Lifecycle statuses for invoices in Ghanaian commerce and statutory clearance."""

    DRAFT = "DRAFT", "Draft"
    PENDING_GRA = "PENDING_GRA", "Pending GRA Clearance"
    CLEARED = "CLEARED", "Cleared by GRA"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
    PAID = "PAID", "Paid"
    OVERDUE = "OVERDUE", "Overdue"
    CANCELLED = "CANCELLED", "Cancelled"


class Invoice(BaseTenantModel, PublicShareableMixin):
    """Customer tax invoice with composite tenant isolation and immutable legal snapshot."""

    customer = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="invoices",
        help_text="Target customer contact record.",
    )
    invoice_number = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Unique sequence reference or Luhn check number.",
    )
    payment_reference = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text=(
            "Compact numeric sequence with Luhn check-digit for USSD and MoMo reconciliation."
        ),
    )
    issue_date = models.DateField(
        db_index=True,
        help_text="Invoice tax point date.",
    )
    due_date = models.DateField(
        db_index=True,
        help_text="Payment due date.",
    )
    subtotal_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Net taxable base amount before statutory levies.",
    )
    vat_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="15.0% Standard VAT under Act 1151.",
    )
    nhil_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="2.5% National Health Insurance Levy under Act 1151.",
    )
    getfund_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="2.5% GETFund Levy under Act 1151.",
    )
    covid_levy_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Abolished under Act 1151; maintained at 0.0000 for statutory compatibility.",
    )
    total_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Gross total invoice amount payable by customer.",
    )
    paid_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Cumulative payments received against this invoice.",
    )
    status = models.CharField(
        max_length=30,
        choices=InvoiceStatusChoices.choices,
        default=InvoiceStatusChoices.DRAFT,
        db_index=True,
        help_text="Current lifecycle state of the invoice.",
    )
    currency = models.CharField(
        max_length=3,
        default="GHS",
        help_text="ISO 4217 billing currency.",
    )

    # GRA E-VAT Clearance Fields
    gra_clearance_code = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Cryptographic clearance verification code or SDC ID from GRA.",
    )
    gra_qr_code = models.TextField(
        null=True,
        blank=True,
        help_text="Raw or vector SVG payload for official GRA E-VAT QR code.",
    )
    gra_submitted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when invoice was dispatched to GRA clearance service.",
    )
    gra_cleared_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when GRA returned affirmative clearance.",
    )
    pdf_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Cloudflare R2 pre-signed or public document storage URL.",
    )

    # Immutable Customer Legal Snapshot (Point-in-Time)
    customer_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Immutable legal name of customer at invoice issuance.",
    )
    customer_tin = models.CharField(
        max_length=20,
        blank=True,
        help_text="Immutable customer TIN at invoice issuance.",
    )
    customer_ghana_card = models.CharField(
        max_length=25,
        blank=True,
        help_text="Immutable customer Ghana Card PIN at invoice issuance.",
    )
    customer_address = models.TextField(
        blank=True,
        help_text="Immutable billing address at invoice issuance.",
    )
    customer_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text="Immutable customer phone at invoice issuance.",
    )
    customer_email = models.CharField(
        max_length=255,
        blank=True,
        help_text="Immutable customer billing email at invoice issuance.",
    )
    snapshot_frozen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the customer legal snapshot was permanently frozen.",
    )

    class Meta(BaseTenantModel.Meta):
        db_table = "invoices"
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        ordering = ["-issue_date", "-created_at"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["organization", "invoice_number"],
                name="unique_org_invoice_number",
            ),
            models.CheckConstraint(
                condition=models.Q(due_date__gte=models.F("issue_date")),
                name="invoice_check_due_date_after_issue",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal_amount__gte=Decimal("0.0000")),
                name="invoice_check_subtotal_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(total_amount__gte=Decimal("0.0000")),
                name="invoice_check_total_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(paid_amount__gte=Decimal("0.0000")),
                name="invoice_check_paid_positive",
            ),
        ]

    def __str__(self) -> str:
        cust = self.customer_name or self.customer.name
        return f"{self.invoice_number} - {cust} (GHS {self.total_amount})"

    @property
    def balance_due(self) -> Decimal:
        """Returns outstanding balance due on this invoice."""
        return max(ZERO_MONEY, self.total_amount - self.paid_amount)

    @property
    def is_cleared_with_gra(self) -> bool:
        """Indicates if the invoice has been affirmed and signed by GRA."""
        return self.status == InvoiceStatusChoices.CLEARED and bool(self.gra_clearance_code)

    def freeze_customer_snapshot(self, force: bool = False) -> None:
        """Freezes point-in-time legal identity snapshot from the customer contact record."""
        if self.snapshot_frozen_at and not force:
            return

        if self.customer:
            self.customer_name = self.customer.name
            self.customer_tin = self.customer.tin
            self.customer_ghana_card = self.customer.ghana_card_number
            self.customer_address = self.customer.billing_address
            self.customer_phone = self.customer.phone
            self.customer_email = self.customer.email
            self.snapshot_frozen_at = timezone.now()

    def clean(self) -> None:
        super().clean()

        # 1. Composite Tenant Foreign Key Enforcement
        if self.customer_id and self.customer.organization_id != self.organization_id:
            raise ValidationError(
                {"customer": "Customer must belong to the same organization as the invoice."}
            )

        # 2. Date consistency check
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            raise ValidationError({"due_date": "Due date cannot be earlier than issue date."})

        # 3. Snapshot Immutability Enforcement for Issued Invoices
        if not self._state.adding and self.pk:
            orig = (
                Invoice.objects.filter(pk=self.pk)
                .values(
                    "status",
                    "customer_id",
                    "customer_name",
                    "customer_tin",
                    "customer_ghana_card",
                    "customer_address",
                    "customer_phone",
                    "customer_email",
                    "snapshot_frozen_at",
                )
                .first()
            )
            if orig and orig["status"] != InvoiceStatusChoices.DRAFT:
                # Disallow mutating customer reference
                if self.customer_id != orig["customer_id"]:
                    raise ValidationError(
                        {"customer": "Customer cannot be changed on an issued invoice."}
                    )
                # Disallow modifying customer legal snapshot fields
                if (
                    self.customer_name != orig["customer_name"]
                    or self.customer_tin != orig["customer_tin"]
                    or self.customer_ghana_card != orig["customer_ghana_card"]
                    or self.customer_address != orig["customer_address"]
                    or self.customer_phone != orig["customer_phone"]
                    or self.customer_email != orig["customer_email"]
                ):
                    raise ValidationError(
                        "Customer legal snapshot cannot be altered on an issued invoice."
                    )

        # 4. Luhn Check-Digit Payment Reference Validation
        if self.payment_reference:
            from apps.invoicing.utils import LuhnValidator

            if not LuhnValidator.validate(self.payment_reference):
                raise ValidationError(
                    {
                        "payment_reference": (
                            "Invalid payment reference: failed Luhn check-digit verification."
                        )
                    }
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Auto-generate Luhn-protected payment reference if blank
        if not self.payment_reference and self.organization_id:
            from apps.invoicing.utils import generate_invoice_payment_reference

            self.payment_reference = generate_invoice_payment_reference(self.organization)

        # Auto-freeze snapshot on initial save or when transitioning from DRAFT
        if self.customer and (not self.snapshot_frozen_at or not self.customer_name):
            self.freeze_customer_snapshot()

        self.clean()
        super().save(*args, **kwargs)

    def get_customer_snapshot_dict(self) -> dict[str, str]:
        """Returns structured dictionary of the frozen legal snapshot."""
        return {
            "name": self.customer_name or (self.customer.name if self.customer else ""),
            "tin": self.customer_tin or (self.customer.tin if self.customer else ""),
            "ghana_card_number": self.customer_ghana_card
            or (self.customer.ghana_card_number if self.customer else ""),
            "address": self.customer_address
            or (self.customer.billing_address if self.customer else ""),
            "phone": self.customer_phone or (self.customer.phone if self.customer else ""),
            "email": self.customer_email or (self.customer.email if self.customer else ""),
        }


class InvoiceLine(BaseTenantModel):
    """Itemized transaction line belonging to an Invoice."""

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="lines",
        help_text="Parent invoice header.",
    )
    account = models.ForeignKey(
        "ledger.ChartOfAccounts",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoice_lines",
        help_text="Revenue account in general ledger (defaults to 4000 Sales Revenue).",
    )
    description = models.CharField(
        max_length=255,
        help_text="Description of goods supplied or service rendered.",
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("1.0000"),
        help_text="Billed quantity or hours.",
    )
    unit_price = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        help_text="Price per unit exclusive of statutory levies.",
    )
    line_total = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        help_text="Total base amount before statutory levies (quantity * unit_price).",
    )
    is_taxable = models.BooleanField(
        default=True,
        help_text="Flag indicating whether statutory VAT/NHIL/GETFund apply.",
    )
    vat_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=STATUTORY_VAT_RATE,
        help_text="Applied VAT rate (15.0% under Act 1151).",
    )
    nhil_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=STATUTORY_NHIL_RATE,
        help_text="Applied NHIL rate (2.5% under Act 1151).",
    )
    getfund_rate = models.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=STATUTORY_GETFUND_RATE,
        help_text="Applied GETFund rate (2.5% under Act 1151).",
    )
    vat_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Computed VAT amount for this line.",
    )
    nhil_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Computed NHIL amount for this line.",
    )
    getfund_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=ZERO_MONEY,
        help_text="Computed GETFund amount for this line.",
    )

    class Meta(BaseTenantModel.Meta):
        db_table = "invoice_lines"
        verbose_name = "Invoice Line"
        verbose_name_plural = "Invoice Lines"
        ordering = ["created_at"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=Decimal("0.0000")),
                name="invoice_line_check_quantity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=Decimal("0.0000")),
                name="invoice_line_check_unit_price_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(line_total__gte=Decimal("0.0000")),
                name="invoice_line_check_line_total_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.description} ({self.quantity} @ GHS {self.unit_price})"

    def clean(self) -> None:
        super().clean()

        if self.invoice_id and self.invoice.organization_id != self.organization_id:
            raise ValidationError(
                {"invoice": "Invoice line organization must match invoice organization."}
            )

        if self.account_id and self.account.organization_id != self.organization_id:
            raise ValidationError(
                {"account": "Revenue account must belong to the same organization."}
            )

        if self.quantity <= Decimal("0.0000"):
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

        if self.unit_price < Decimal("0.0000"):
            raise ValidationError({"unit_price": "Unit price cannot be negative."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.line_total is None or self.line_total == ZERO_MONEY:
            self.line_total = (self.quantity * self.unit_price).quantize(Decimal("0.0001"))
        self.clean()
        super().save(*args, **kwargs)
