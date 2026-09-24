"""Unit tests for Customer Legal Snapshots and Invoicing Domain Models (Feature 3.1).

Validates:
1. Customer and Supplier contact management and unique constraints.
2. Immutable point-in-time legal identity snapshot freezing on invoice issuance.
3. Decoupling of historical invoices from future contact mutations.
4. Prevention of legal snapshot tampering on non-draft invoices.
5. Due date and amount check constraints.
6. Invoice line item calculations and protective deletion boundaries.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
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


class InvoicingModelSnapshotTests(TestCase):
    """Test suite verifying point-in-time legal snapshots and invoice model invariants."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(
            name="Accra Wholesale Supplies Ltd",
            business_tin="C0009876543",
            phone="+233240001122",
            email="billing@accrawholesale.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.customer = Contact.objects.create(
            organization=self.org,
            name="Kofi Mensah Trading Co",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0001234567",
            ghana_card_number="GHA-123456789-1",
            billing_address="P.O. Box 1234, Makola Market, Accra",
            phone="+233241234567",
            email="kofi@mensahtrading.gh",
        )
        self.income_category = AccountCategory.objects.create(
            code=CategoryCodeChoices.INCOME,
            name="Income",
            normal_balance=NormalBalanceChoices.CREDIT,
        )
        self.sales_account = ChartOfAccounts.objects.create(
            organization=self.org,
            account_code="4000",
            account_name="Sales Revenue",
            category=self.income_category,
            is_active=True,
        )

    def test_contact_creation_and_unique_constraint(self) -> None:
        """Contacts enforce unique name within the same organization."""
        self.assertEqual(
            str(self.customer), "Kofi Mensah Trading Co (Customer) [Accra Wholesale Supplies Ltd]"
        )

        # Attempt to create duplicate name in same org should fail
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Contact.objects.create(
                    organization=self.org,
                    name="Kofi Mensah Trading Co",
                    contact_type=ContactTypeChoices.SUPPLIER,
                )

    def test_contact_same_name_different_org_allowed(self) -> None:
        """Different organizations can have contacts with the identical name."""
        other_org = Organization.objects.create(
            name="Kumasi Distributors Ltd",
            phone="+233242000333",
            email="info@kumasidist.gh",
        )
        contact_b = Contact.objects.create(
            organization=other_org,
            name="Kofi Mensah Trading Co",
            contact_type=ContactTypeChoices.CUSTOMER,
        )
        self.assertEqual(contact_b.name, self.customer.name)
        self.assertNotEqual(contact_b.organization_id, self.customer.organization_id)

    def test_snapshot_freezing_on_invoice_save(self) -> None:
        """Creating an invoice automatically freezes the customer legal snapshot."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0001",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            subtotal_amount=Decimal("1000.0000"),
            vat_amount=Decimal("150.0000"),
            nhil_amount=Decimal("25.0000"),
            getfund_amount=Decimal("25.0000"),
            total_amount=Decimal("1200.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        self.assertEqual(invoice.customer_name, "Kofi Mensah Trading Co")
        self.assertEqual(invoice.customer_tin, "C0001234567")
        self.assertEqual(invoice.customer_ghana_card, "GHA-123456789-1")
        self.assertEqual(invoice.customer_address, "P.O. Box 1234, Makola Market, Accra")
        self.assertEqual(invoice.customer_phone, "+233241234567")
        self.assertEqual(invoice.customer_email, "kofi@mensahtrading.gh")
        self.assertIsNotNone(invoice.snapshot_frozen_at)

        snapshot_dict = invoice.get_customer_snapshot_dict()
        self.assertEqual(snapshot_dict["tin"], "C0001234567")
        self.assertEqual(snapshot_dict["ghana_card_number"], "GHA-123456789-1")

    def test_customer_mutation_does_not_affect_existing_invoice_snapshot(self) -> None:
        """Mutating or updating a customer profile does not mutate historical invoice snapshots."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0002",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.CLEARED,
        )
        frozen_time = invoice.snapshot_frozen_at

        # Customer changes legal business name, address, and TIN
        self.customer.name = "Kofi Mensah Global Enterprise"
        self.customer.tin = "C0009999999"
        self.customer.billing_address = "Airport City, Accra"
        self.customer.save()

        # Reload invoice from database
        invoice.refresh_from_db()

        # Invoice legal snapshot remains preserved point-in-time
        self.assertEqual(invoice.customer_name, "Kofi Mensah Trading Co")
        self.assertEqual(invoice.customer_tin, "C0001234567")
        self.assertEqual(invoice.customer_address, "P.O. Box 1234, Makola Market, Accra")
        self.assertEqual(invoice.snapshot_frozen_at, frozen_time)

    def test_issued_invoice_blocks_snapshot_tampering(self) -> None:
        """Once an invoice is issued (not DRAFT), tampering with snapshot fields is blocked."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0003",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1000.0000"),
            status=InvoiceStatusChoices.CLEARED,
        )

        # Attempt to tamper with customer_tin
        invoice.customer_tin = "C0009999999"
        with self.assertRaises(ValidationError) as ctx:
            invoice.save()
        self.assertIn(
            "Customer legal snapshot cannot be altered on an issued invoice", str(ctx.exception)
        )

        # Attempt to alter customer reference
        invoice.refresh_from_db()
        other_customer = Contact.objects.create(
            organization=self.org,
            name="Ama Serwaa Retail",
            contact_type=ContactTypeChoices.CUSTOMER,
        )
        invoice.customer = other_customer
        with self.assertRaises(ValidationError) as ctx:
            invoice.save()
        self.assertIn("Customer cannot be changed on an issued invoice", str(ctx.exception))

    def test_draft_invoice_allows_snapshot_refresh(self) -> None:
        """In DRAFT status, customer updates can be manually re-frozen before issuance."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0004",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1000.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        self.customer.billing_address = "New Suite 400, Ridge, Accra"
        self.customer.save()

        # Re-freeze customer snapshot while still DRAFT
        invoice.freeze_customer_snapshot(force=True)
        invoice.save()

        invoice.refresh_from_db()
        self.assertEqual(invoice.customer_address, "New Suite 400, Ridge, Accra")

    def test_due_date_must_be_gte_issue_date(self) -> None:
        """Due date earlier than issue date violates validation and check constraint."""
        invoice = Invoice(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0005",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 9, 20),  # 4 days prior!
            total_amount=Decimal("100.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )
        with self.assertRaises(ValidationError) as ctx:
            invoice.full_clean()
        self.assertIn("due_date", ctx.exception.message_dict)

    def test_invoice_balance_due_and_cleared_properties(self) -> None:
        """Verify balance_due calculation and GRA clearance property."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0006",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1200.0000"),
            paid_amount=Decimal("400.0000"),
            status=InvoiceStatusChoices.PARTIALLY_PAID,
        )
        self.assertEqual(invoice.balance_due, Decimal("800.0000"))
        self.assertFalse(invoice.is_cleared_with_gra)

        invoice.status = InvoiceStatusChoices.CLEARED
        invoice.gra_clearance_code = "SDC-2026-GH-XYZ-9988"
        self.assertTrue(invoice.is_cleared_with_gra)

    def test_invoice_line_calculation_and_validation(self) -> None:
        """InvoiceLine computes line_total and enforces positive quantities."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0007",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        line = InvoiceLine.objects.create(
            organization=self.org,
            invoice=invoice,
            account=self.sales_account,
            description="Consulting Services - IT Audit",
            quantity=Decimal("5.0000"),
            unit_price=Decimal("100.0000"),
        )
        self.assertEqual(line.line_total, Decimal("500.0000"))
        self.assertEqual(line.vat_rate, Decimal("0.1500"))
        self.assertEqual(line.nhil_rate, Decimal("0.0250"))
        self.assertEqual(line.getfund_rate, Decimal("0.0250"))

        # Zero quantity rejected
        invalid_line = InvoiceLine(
            organization=self.org,
            invoice=invoice,
            description="Zero Qty Service",
            quantity=Decimal("0.0000"),
            unit_price=Decimal("50.0000"),
        )
        with self.assertRaises(ValidationError):
            invalid_line.full_clean()

    def test_protected_contact_deletion(self) -> None:
        """Contacts referenced by invoices cannot be deleted (PROTECT)."""
        Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-0008",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("300.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )
        with self.assertRaises(ProtectedError):
            self.customer.delete()
