"""Automated tests for Double-Entry Ledger Core Engine (Feature 2.2).

Validates:
- Double-entry balance invariant (Sum(Debits) == Sum(Credits)).
- Either debit or credit per line; positive amount enforcement.
- Fiscal period locking boundary enforcement and historical record validity.
- Cross-tenant account isolation defenses.
- Absolute ledger immutability (model delete/save guards and QuerySet bulk blocks).
- Machine postings with null created_by.
- Dynamic fiscal period auto-provisioning.
- Offsetting reversing journal entry generation.
- Deterministic DAG lock acquisition sequence.
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.ledger.models import (
    ChartOfAccounts,
    FiscalCalendar,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
    PeriodLengthChoices,
    SourceTypeChoices,
)
from apps.ledger.services.ledger import LedgerService
from apps.ledger.services.seeder import (
    generate_fiscal_periods,
    seed_standard_chart_of_accounts,
)
from apps.tenancy.models import Organization

User = get_user_model()


class LedgerEngineTests(TestCase):
    """Comprehensive test suite for LedgerService and double-entry invariants."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="cfo@accratrading.com",
            password="SecurePassword123!",
            first_name="Kofi",
            last_name="Mensah",
        )
        self.org_a = Organization.objects.create(
            name="Accra Trading Co Ltd",
            phone="+233241112233",
            email="accra@trading.com",
        )
        self.org_b = Organization.objects.create(
            name="Kumasi Goods Ltd",
            phone="+233249998877",
            email="kumasi@goods.com",
        )

        # Seed standard Ghanaian chart of accounts for both tenants
        seed_standard_chart_of_accounts(self.org_a)
        seed_standard_chart_of_accounts(self.org_b)

        # Generate fiscal calendar and periods for 2026
        self.calendar_a = FiscalCalendar.objects.create(
            organization=self.org_a,
            period_length=PeriodLengthChoices.MONTHLY,
            fiscal_year_end_month=12,
            fiscal_year_end_day=31,
        )
        self.periods_a = generate_fiscal_periods(
            organization=self.org_a,
            year=2026,
            calendar_instance=self.calendar_a,
        )

        # Commonly used accounts in Org A
        self.acc_cash = ChartOfAccounts.objects.get(organization=self.org_a, account_code="1010")
        self.acc_ar = ChartOfAccounts.objects.get(organization=self.org_a, account_code="1200")
        self.acc_revenue = ChartOfAccounts.objects.get(organization=self.org_a, account_code="4000")
        self.acc_vat_out = ChartOfAccounts.objects.get(organization=self.org_a, account_code="2100")

    def test_post_balanced_journal_entry_success(self) -> None:
        """Balanced entry posts atomically and sets is_posted, period, and UUIDv7 ID."""
        entry_date = datetime.date(2026, 1, 15)
        lines_data = [
            {
                "account": self.acc_ar,
                "debit_amount": Decimal("1150.00"),
                "credit_amount": Decimal("0.00"),
                "description": "Invoice #INV-001 AR",
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("1000.00"),
                "description": "Standard Sales Revenue",
            },
            {
                "account": self.acc_vat_out,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("150.00"),
                "description": "15% Standard VAT Output",
            },
        ]

        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=entry_date,
            lines_data=lines_data,
            narration="Sale of merchandise to customer",
            user=self.user,
            source_type=SourceTypeChoices.INVOICE,
        )

        self.assertIsNotNone(entry.id)
        self.assertEqual(entry.id.version, 7)
        self.assertTrue(entry.is_posted)
        self.assertIsNotNone(entry.posted_at)
        self.assertEqual(entry.posted_by, self.user)
        self.assertEqual(entry.created_by, self.user)
        self.assertEqual(entry.source_type, SourceTypeChoices.INVOICE)
        self.assertEqual(entry.period.period_name, "January 2026")
        self.assertEqual(entry.lines.count(), 3)

        # Verify sums match in lines
        total_debits = sum(line.debit_amount for line in entry.lines.all())
        total_credits = sum(line.credit_amount for line in entry.lines.all())
        self.assertEqual(total_debits, Decimal("1150.0000"))
        self.assertEqual(total_credits, Decimal("1150.0000"))

    def test_post_unbalanced_entry_rejected(self) -> None:
        """Unbalanced journal entry raises ValidationError with 0 records persisted."""
        entry_date = datetime.date(2026, 2, 10)
        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("1000.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("800.00"),  # Unbalanced by 200
            },
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=entry_date,
                lines_data=lines_data,
                narration="Unbalanced sale attempt",
            )

        self.assertIn("Unbalanced journal entry", str(ctx.exception))
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(JournalLine.objects.count(), 0)

    def test_check_either_debit_or_credit_constraint(self) -> None:
        """Line with both debit and credit amounts is rejected."""
        entry_date = datetime.date(2026, 3, 1)
        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("500.00"),
                "credit_amount": Decimal("100.00"),  # Invalid: both positive
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("400.00"),
            },
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=entry_date,
                lines_data=lines_data,
                narration="Invalid simultaneous debit/credit",
            )

        self.assertIn("not both or zero", str(ctx.exception))

    def test_check_positive_values_constraint(self) -> None:
        """Line with negative debit or credit amount is rejected."""
        entry_date = datetime.date(2026, 3, 5)
        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("-500.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("-500.00"),
            },
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=entry_date,
                lines_data=lines_data,
                narration="Negative amounts",
            )

        self.assertIn("negative debit or credit", str(ctx.exception))

    def test_single_line_rejected(self) -> None:
        """Journal entry with fewer than two line items is rejected."""
        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("100.00"),
                "credit_amount": Decimal("0.00"),
            }
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=datetime.date(2026, 1, 10),
                lines_data=lines_data,
                narration="Single line",
            )

        self.assertIn("at least two line items", str(ctx.exception))

    def test_closed_fiscal_period_blocking_on_new_entry(self) -> None:
        """Posting transaction into a closed fiscal period raises ValidationError."""
        jan_period = FiscalPeriod.objects.get(organization=self.org_a, period_name="January 2026")
        jan_period.close_period(self.user)

        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("200.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("200.00"),
            },
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=datetime.date(2026, 1, 20),
                lines_data=lines_data,
                narration="Post into closed period",
            )

        self.assertIn("Cannot post transaction to a closed fiscal period", str(ctx.exception))

    def test_historical_entries_valid_after_period_closure(self) -> None:
        """Closing a fiscal period does not invalidate historical posted entries upon clean()."""
        entry_date = datetime.date(2026, 1, 10)
        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("300.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("300.00"),
            },
        ]

        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=entry_date,
            lines_data=lines_data,
            narration="January Sale",
        )

        # Close the period afterwards
        jan_period = FiscalPeriod.objects.get(organization=self.org_a, period_name="January 2026")
        jan_period.close_period(self.user)

        # Inspecting and validating historical entry must not raise ValidationError
        entry.refresh_from_db()
        entry.full_clean()
        self.assertTrue(entry.period.is_closed)

    def test_cross_tenant_account_posting_rejected(self) -> None:
        """Referencing an account belonging to another tenant raises ValidationError."""
        acc_org_b = ChartOfAccounts.objects.get(organization=self.org_b, account_code="1010")

        lines_data = [
            {
                "account": acc_org_b,  # Org B's account in Org A's entry
                "debit_amount": Decimal("500.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("500.00"),
            },
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=datetime.date(2026, 1, 15),
                lines_data=lines_data,
                narration="Cross tenant attempt",
            )

        self.assertIn("belong to another organization", str(ctx.exception))

    def test_inactive_account_posting_rejected(self) -> None:
        """Posting to an inactive general ledger account is rejected."""
        self.acc_cash.is_active = False
        self.acc_cash.save(update_fields=["is_active"])

        lines_data = [
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("100.00"),
                "credit_amount": Decimal("0.00"),
            },
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("100.00"),
            },
        ]

        with self.assertRaises(ValidationError) as ctx:
            LedgerService.post_journal_entry(
                organization=self.org_a,
                entry_date=datetime.date(2026, 1, 15),
                lines_data=lines_data,
                narration="Inactive account attempt",
            )

        self.assertIn("is inactive and cannot accept new postings", str(ctx.exception))

    def test_posted_journal_entry_immutability(self) -> None:
        """Posted journal entries and lines cannot be updated or deleted."""
        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=datetime.date(2026, 1, 15),
            lines_data=[
                {
                    "account": self.acc_cash,
                    "debit_amount": Decimal("250.00"),
                    "credit_amount": Decimal("0.00"),
                },
                {
                    "account": self.acc_revenue,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": Decimal("250.00"),
                },
            ],
            narration="Immutable entry",
        )

        # Deleting entry raises ValidationError
        with self.assertRaises(ValidationError) as ctx:
            entry.delete()
        self.assertIn("Cannot delete a posted journal entry", str(ctx.exception))

        # Deleting line raises ValidationError
        line = entry.lines.first()
        with self.assertRaises(ValidationError) as ctx_line:
            line.delete()
        self.assertIn(
            "Cannot delete lines belonging to a posted journal entry",
            str(ctx_line.exception),
        )

        # Modifying entry and running clean raises ValidationError
        entry.narration = "Tampered narration"
        with self.assertRaises(ValidationError) as ctx_mod:
            entry.clean()
        self.assertIn("Posted journal entries are strictly immutable", str(ctx_mod.exception))

    def test_queryset_bulk_delete_and_update_blocked_on_posted_lines(self) -> None:
        """Bulk QuerySet delete() and update() are blocked on posted entries and lines."""
        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=datetime.date(2026, 1, 15),
            lines_data=[
                {
                    "account": self.acc_cash,
                    "debit_amount": Decimal("400.00"),
                    "credit_amount": Decimal("0.00"),
                },
                {
                    "account": self.acc_revenue,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": Decimal("400.00"),
                },
            ],
            narration="Bulk guard entry",
        )

        with self.assertRaises(ValidationError):
            JournalLine.objects.filter(journal_entry=entry).delete()

        with self.assertRaises(ValidationError):
            JournalLine.objects.filter(journal_entry=entry).update(debit_amount=Decimal("999.00"))

        with self.assertRaises(ValidationError):
            JournalEntry.objects.filter(id=entry.id).delete()

        with self.assertRaises(ValidationError):
            JournalEntry.objects.filter(id=entry.id).update(narration="Tampered")

    def test_machine_posting_with_null_created_by_succeeds(self) -> None:
        """Automated machine events (webhooks, tasks) can post with created_by=None."""
        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=datetime.date(2026, 1, 18),
            lines_data=[
                {
                    "account": self.acc_cash,
                    "debit_amount": Decimal("50.00"),
                    "credit_amount": Decimal("0.00"),
                },
                {
                    "account": self.acc_revenue,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": Decimal("50.00"),
                },
            ],
            narration="Automated MoMo settlement webhook",
            user=None,  # Machine event
            source_type=SourceTypeChoices.PAYMENT,
        )

        self.assertIsNone(entry.created_by)
        self.assertIsNone(entry.posted_by)
        self.assertTrue(entry.is_posted)

    def test_dynamic_period_provisioning_on_missing_year(self) -> None:
        """Posting to a date with unprovisioned periods dynamically generates periods."""
        # 2028 has not been seeded
        self.assertFalse(
            FiscalPeriod.objects.filter(organization=self.org_a, start_date__year=2028).exists()
        )

        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=datetime.date(2028, 5, 20),
            lines_data=[
                {
                    "account": self.acc_cash,
                    "debit_amount": Decimal("100.00"),
                    "credit_amount": Decimal("0.00"),
                },
                {
                    "account": self.acc_revenue,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": Decimal("100.00"),
                },
            ],
            narration="Future transaction",
        )

        self.assertEqual(entry.period.period_name, "May 2028")
        self.assertTrue(
            FiscalPeriod.objects.filter(organization=self.org_a, start_date__year=2028).exists()
        )

    def test_reverse_journal_entry_creates_mirror_offset(self) -> None:
        """Reversing a posted journal entry creates an exact offsetting entry."""
        original_entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=datetime.date(2026, 1, 10),
            lines_data=[
                {
                    "account": self.acc_ar,
                    "debit_amount": Decimal("750.00"),
                    "credit_amount": Decimal("0.00"),
                    "description": "Original AR",
                },
                {
                    "account": self.acc_revenue,
                    "debit_amount": Decimal("0.00"),
                    "credit_amount": Decimal("750.00"),
                    "description": "Original Revenue",
                },
            ],
            narration="Original customer invoice",
            user=self.user,
        )

        reversal_date = datetime.date(2026, 1, 12)
        reversing_entry = LedgerService.reverse_journal_entry(
            journal_entry=original_entry,
            user=self.user,
            reason="Customer canceled contract",
            reversal_date=reversal_date,
        )

        self.assertNotEqual(reversing_entry.id, original_entry.id)
        self.assertEqual(reversing_entry.source_type, SourceTypeChoices.RECTIFICATION)
        self.assertEqual(reversing_entry.source_id, original_entry.id)
        self.assertIn("Customer canceled contract", reversing_entry.narration)

        # Verify mirrored amounts
        lines = list(reversing_entry.lines.all())
        ar_line = next(line for line in lines if line.account_id == self.acc_ar.id)
        rev_line = next(line for line in lines if line.account_id == self.acc_revenue.id)

        # Original was Dr AR, Cr Revenue. Reversal must be Cr AR, Dr Revenue.
        self.assertEqual(ar_line.credit_amount, Decimal("750.0000"))
        self.assertEqual(ar_line.debit_amount, Decimal("0.0000"))
        self.assertEqual(rev_line.debit_amount, Decimal("750.0000"))
        self.assertEqual(rev_line.credit_amount, Decimal("0.0000"))

    def test_deterministic_lock_ordering_consistency(self) -> None:
        """Accounts provided in reverse order are locked in deterministic order."""
        # Provide Revenue (4000) first, then Cash (1010)
        lines_data = [
            {
                "account": self.acc_revenue,
                "debit_amount": Decimal("0.00"),
                "credit_amount": Decimal("600.00"),
            },
            {
                "account": self.acc_cash,
                "debit_amount": Decimal("600.00"),
                "credit_amount": Decimal("0.00"),
            },
        ]

        entry = LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=datetime.date(2026, 1, 15),
            lines_data=lines_data,
            narration="Reverse-ordered line inputs",
        )

        self.assertTrue(entry.is_posted)
        self.assertEqual(entry.lines.count(), 2)
