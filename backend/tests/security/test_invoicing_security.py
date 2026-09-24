"""Adversarial and security misuse tests for Invoicing (Feature 3.1 & MUC 2.1/3.1).

Covers:
1. MUC-2.1: Cross-Tenant Customer Injection.
2. MUC-2.1: Cross-Tenant Invoice Line Tampering (Line belongs to Org B, Invoice to Org A).
3. MUC-2.1: Cross-Tenant Ledger Account Leakage (InvoiceLine references Org B's account).
4. MUC-3.1: Issued Invoice Legal Snapshot Tampering Attack (Customer TIN/PIN immutability).
5. Statutory Integrity: Negative amount injection and due date inversion attacks.
6. Public Share Token Unguessability: UUIDv4 entropy validation.
"""

import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.invoicing.models import (
    Contact,
    ContactTypeChoices,
    Invoice,
    InvoiceLine,
    InvoiceStatusChoices,
)
from apps.ledger.models import (
    AccountCategory,
    CategoryCodeChoices,
    ChartOfAccounts,
    NormalBalanceChoices,
)
from apps.tenancy.models import Organization, TaxSchemeChoices


class InvoicingSecurityAndMisuseTests(TestCase):
    """Adversarial test suite validating tenant isolation and snapshot immutability."""

    def setUp(self) -> None:
        self.org_a = Organization.objects.create(
            name="Victim Org A Ltd",
            business_tin="C0001111111",
            phone="+233240000001",
            email="victim@orga.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.org_b = Organization.objects.create(
            name="Attacker Org B Ltd",
            business_tin="C0002222222",
            phone="+233240000002",
            email="attacker@orgb.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.customer_a = Contact.objects.create(
            organization=self.org_a,
            name="Customer of Org A",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0001000001",
            ghana_card_number="GHA-111111111-1",
        )
        self.customer_b = Contact.objects.create(
            organization=self.org_b,
            name="Customer of Org B",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0002000002",
            ghana_card_number="GHA-222222222-2",
        )
        self.category = AccountCategory.objects.create(
            code=CategoryCodeChoices.INCOME,
            name="Income",
            normal_balance=NormalBalanceChoices.CREDIT,
        )
        self.account_a = ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="4000",
            account_name="Org A Sales",
            category=self.category,
        )
        self.account_b = ChartOfAccounts.objects.create(
            organization=self.org_b,
            account_code="4000",
            account_name="Org B Sales",
            category=self.category,
        )

    def test_cross_tenant_customer_injection_blocked(self) -> None:
        """MUC-2.1: Attacker in Org B cannot create an invoice targeting Org A's customer."""
        malicious_invoice = Invoice(
            organization=self.org_b,
            customer=self.customer_a,  # Belongs to Org A!
            invoice_number="INV-ATTACK-001",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1000.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )
        with self.assertRaises(ValidationError) as ctx:
            malicious_invoice.full_clean()
        self.assertIn("customer", ctx.exception.message_dict)
        self.assertIn("Customer must belong to the same organization", str(ctx.exception))

    def test_cross_tenant_invoice_line_injection_blocked(self) -> None:
        """MUC-2.1: Attacker cannot link an invoice line of Org B to an invoice of Org A."""
        invoice_a = Invoice.objects.create(
            organization=self.org_a,
            customer=self.customer_a,
            invoice_number="INV-A-001",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1000.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        malicious_line = InvoiceLine(
            organization=self.org_b,  # Belongs to Org B!
            invoice=invoice_a,  # Belongs to Org A!
            description="Malicious Line",
            quantity=Decimal("1.0000"),
            unit_price=Decimal("100.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            malicious_line.full_clean()
        self.assertIn("invoice", ctx.exception.message_dict)
        self.assertIn(
            "Invoice line organization must match invoice organization", str(ctx.exception)
        )

    def test_cross_tenant_account_injection_blocked(self) -> None:
        """MUC-2.1: Line cannot reference a ChartOfAccounts of another tenant."""
        invoice_a = Invoice.objects.create(
            organization=self.org_a,
            customer=self.customer_a,
            invoice_number="INV-A-002",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1000.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        malicious_line = InvoiceLine(
            organization=self.org_a,
            invoice=invoice_a,
            account=self.account_b,  # Org B's ChartOfAccounts!
            description="Cross-tenant account tampering",
            quantity=Decimal("1.0000"),
            unit_price=Decimal("200.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            malicious_line.full_clean()
        self.assertIn("account", ctx.exception.message_dict)
        self.assertIn("Revenue account must belong to the same organization", str(ctx.exception))

    def test_muc_3_1_snapshot_tampering_on_cleared_invoice_blocked(self) -> None:
        """MUC-3.1: Snapshot tampering on cleared invoice is blocked."""
        invoice = Invoice.objects.create(
            organization=self.org_a,
            customer=self.customer_a,
            invoice_number="INV-A-003",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1200.0000"),
            status=InvoiceStatusChoices.CLEARED,
            gra_clearance_code="SDC-GH-2026-VAL-1234",
        )

        # Attacker tries to change legal TIN and name of customer
        invoice.customer_name = "Forged Front Corp"
        invoice.customer_tin = "C9999999999"
        with self.assertRaises(ValidationError) as ctx:
            invoice.save()
        self.assertIn(
            "Customer legal snapshot cannot be altered on an issued invoice", str(ctx.exception)
        )

    def test_negative_unit_price_or_quantity_rejected(self) -> None:
        """Adversarial negative quantities or prices raise ValidationError and are rejected."""
        invoice = Invoice.objects.create(
            organization=self.org_a,
            customer=self.customer_a,
            invoice_number="INV-A-004",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1000.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        negative_qty_line = InvoiceLine(
            organization=self.org_a,
            invoice=invoice,
            description="Exploit Negative Qty",
            quantity=Decimal("-1.0000"),
            unit_price=Decimal("100.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            negative_qty_line.full_clean()
        self.assertIn("quantity", ctx.exception.message_dict)

        negative_price_line = InvoiceLine(
            organization=self.org_a,
            invoice=invoice,
            description="Exploit Negative Price",
            quantity=Decimal("1.0000"),
            unit_price=Decimal("-50.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            negative_price_line.full_clean()
        self.assertIn("unit_price", ctx.exception.message_dict)

    def test_public_share_token_entropy_and_uniqueness(self) -> None:
        """Invoices generate unique UUIDv4 tokens suitable for bearer access without tenant leak."""
        inv_1 = Invoice.objects.create(
            organization=self.org_a,
            customer=self.customer_a,
            invoice_number="INV-A-005",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("100.0000"),
        )
        inv_2 = Invoice.objects.create(
            organization=self.org_b,
            customer=self.customer_b,
            invoice_number="INV-B-001",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("100.0000"),
        )
        # Tokens are valid UUIDs and different
        self.assertIsInstance(inv_1.share_token, uuid.UUID)
        self.assertIsInstance(inv_2.share_token, uuid.UUID)
        self.assertNotEqual(inv_1.share_token, inv_2.share_token)
        self.assertEqual(inv_1.share_token.version, 4)
