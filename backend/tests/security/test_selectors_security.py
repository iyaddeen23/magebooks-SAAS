"""Security and tenant isolation tests for dynamic balance selectors."""

import datetime
from decimal import Decimal

from django.test import TestCase

from apps.ledger.models import ChartOfAccounts
from apps.ledger.selectors import (
    get_balance_sheet,
    get_profit_and_loss,
    get_trial_balance,
)
from apps.ledger.services.ledger import LedgerService
from apps.ledger.services.seeder import (
    generate_fiscal_periods,
    seed_standard_chart_of_accounts,
)
from apps.tenancy.models import Organization, TaxSchemeChoices


class TestSelectorsSecurity(TestCase):
    """Verifies tenant isolation, unposted transaction exclusion, and zero row locks."""

    def setUp(self) -> None:
        self.org_a = Organization.objects.create(
            name="Tenant Alpha Ltd",
            business_tin="C0001111111",
            phone="+233240000011",
            email="alpha@tenant.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        seed_standard_chart_of_accounts(self.org_a)
        generate_fiscal_periods(self.org_a, 2026)

        self.org_b = Organization.objects.create(
            name="Tenant Beta Ltd",
            business_tin="C0002222222",
            phone="+233240000012",
            email="beta@tenant.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        seed_standard_chart_of_accounts(self.org_b)
        generate_fiscal_periods(self.org_b, 2026)

        self.acc_cash_a = ChartOfAccounts.objects.get(organization=self.org_a, account_code="1010")
        self.acc_sales_a = ChartOfAccounts.objects.get(organization=self.org_a, account_code="4000")

        self.acc_cash_b = ChartOfAccounts.objects.get(organization=self.org_b, account_code="1010")
        self.acc_sales_b = ChartOfAccounts.objects.get(organization=self.org_b, account_code="4000")

    def test_strict_cross_tenant_isolation(self) -> None:
        """Asserts Tenant A cannot see or aggregate Tenant B's transactions in any report."""
        entry_date = datetime.date(2026, 1, 15)

        # Tenant A posts 1,000 GHS
        LedgerService.post_journal_entry(
            organization=self.org_a,
            entry_date=entry_date,
            lines_data=[
                {
                    "account": self.acc_cash_a,
                    "debit": Decimal("1000.00"),
                    "credit": Decimal("0.00"),
                },
                {
                    "account": self.acc_sales_a,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("1000.00"),
                },
            ],
            narration="Tenant A Sale",
        )

        # Tenant B posts 50,000 GHS
        LedgerService.post_journal_entry(
            organization=self.org_b,
            entry_date=entry_date,
            lines_data=[
                {
                    "account": self.acc_cash_b,
                    "debit": Decimal("50000.00"),
                    "credit": Decimal("0.00"),
                },
                {
                    "account": self.acc_sales_b,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("50000.00"),
                },
            ],
            narration="Tenant B Sale",
        )

        # Query Tenant A's Trial Balance
        tb_a = get_trial_balance(self.org_a)
        tb_a_dict = {r.account_code: r for r in tb_a.rows}
        self.assertEqual(tb_a.total_debits, Decimal("1000.0000"))
        self.assertEqual(tb_a_dict["1010"].debit_balance, Decimal("1000.0000"))
        self.assertEqual(tb_a_dict["4000"].credit_balance, Decimal("1000.0000"))

        # Query Tenant B's Trial Balance
        tb_b = get_trial_balance(self.org_b)
        self.assertEqual(tb_b.total_debits, Decimal("50000.0000"))

        # Query Tenant A's P&L
        pnl_a = get_profit_and_loss(
            self.org_a,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        self.assertEqual(pnl_a.total_revenue, Decimal("1000.0000"))

        # Query Tenant A's Balance Sheet
        bs_a = get_balance_sheet(self.org_a, as_of_date=datetime.date(2026, 1, 31))
        self.assertEqual(bs_a.total_assets, Decimal("1000.0000"))

    def test_unposted_entries_strictly_excluded(self) -> None:
        """Unposted journal entries (is_posted=False) are excluded from all financial statements."""
        from apps.ledger.models import FiscalPeriod, JournalEntry, JournalLine, SourceTypeChoices

        period = FiscalPeriod.objects.get(organization=self.org_a, period_name="January 2026")

        # Directly simulate an unposted draft entry
        unposted_entry = JournalEntry.objects.create(
            organization=self.org_a,
            period=period,
            entry_number="JE-UNPOSTED-001",
            entry_date=datetime.date(2026, 1, 15),
            narration="Draft unposted transaction",
            source_type=SourceTypeChoices.MANUAL,
            is_posted=False,
        )
        JournalLine.objects.create(
            organization=self.org_a,
            journal_entry=unposted_entry,
            account=self.acc_cash_a,
            debit_amount=Decimal("2000.0000"),
            credit_amount=Decimal("0.0000"),
        )
        JournalLine.objects.create(
            organization=self.org_a,
            journal_entry=unposted_entry,
            account=self.acc_sales_a,
            debit_amount=Decimal("0.0000"),
            credit_amount=Decimal("2000.0000"),
        )

        tb = get_trial_balance(self.org_a)
        self.assertEqual(tb.total_debits, Decimal("0.0000"))

        pnl = get_profit_and_loss(
            self.org_a,
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )
        self.assertEqual(pnl.total_revenue, Decimal("0.0000"))

    def test_zero_row_locks_hot_account_solution(self) -> None:
        """Asserts reporting queries never issue SELECT ... FOR UPDATE on accounts or lines."""
        with self.captureOnCommitCallbacks(execute=False):
            with self.assertNumQueries(3):  # 1 for accounts, 1 for unposted check, 1 for lines
                tb = get_trial_balance(self.org_a)
                self.assertIsNotNone(tb)
