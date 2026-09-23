"""Unit tests for Ghanaian Standard Chart of Accounts and Fiscal Calendar Seeder Service."""

import datetime

from django.test import TestCase

from apps.ledger.models import (
    AccountCategory,
    CategoryCodeChoices,
    ChartOfAccounts,
    FiscalCalendar,
    FiscalPeriod,
    PeriodLengthChoices,
)
from apps.ledger.services.seeder import (
    generate_fiscal_periods,
    seed_account_categories,
    seed_standard_chart_of_accounts,
)
from apps.tenancy.models import Organization


class LedgerSeederTests(TestCase):
    """Test suite validating initial ledger provisioning and seed idempotency."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Kumasi Merchants Ltd",
            phone="+233241888999",
            email="kumasi@merchants.com",
        )

    def test_seed_account_categories_creates_five_categories(self):
        """seed_account_categories creates exactly the 5 primary accounting categories."""
        categories = seed_account_categories()

        self.assertEqual(len(categories), 5)
        self.assertEqual(AccountCategory.objects.count(), 5)

        for code in [
            CategoryCodeChoices.ASSETS,
            CategoryCodeChoices.LIABILITIES,
            CategoryCodeChoices.EQUITY,
            CategoryCodeChoices.INCOME,
            CategoryCodeChoices.EXPENSES,
        ]:
            self.assertIn(code, categories)

    def test_seed_account_categories_is_idempotent(self):
        """Calling seed_account_categories multiple times does not duplicate categories."""
        seed_account_categories()
        initial_count = AccountCategory.objects.count()

        seed_account_categories()
        self.assertEqual(AccountCategory.objects.count(), initial_count)

    def test_seed_standard_chart_of_accounts_provisions_ghanaian_ledger(self):
        """seed_standard_chart_of_accounts provisions standard Ghanaian accounts under Act 1151."""
        created_accounts = seed_standard_chart_of_accounts(self.org)

        self.assertGreater(len(created_accounts), 20)
        self.assertEqual(
            ChartOfAccounts.objects.filter(organization=self.org).count(),
            len(created_accounts),
        )

        # Verify key Ghanaian statutory & commerce accounts exist
        account_codes = {acc.account_code: acc for acc in created_accounts}

        # Mobile Money and Cash
        self.assertIn("1010", account_codes)
        self.assertIn("1015", account_codes)  # MoMo Clearing

        # Act 1151 Statutory Taxes (20% total: 15% VAT + 2.5% NHIL + 2.5% GETFund)
        self.assertIn("2100", account_codes)  # VAT Output
        self.assertIn("2110", account_codes)  # NHIL Output
        self.assertIn("2120", account_codes)  # GETFund Output

        # Suspense Account (for unresolvable MoMo payments)
        self.assertIn("2150", account_codes)

        # Revenue and COGS
        self.assertIn("4000", account_codes)
        self.assertIn("5010", account_codes)

        # Assert all accounts belong to self.org and currency is GHS
        for acc in created_accounts:
            self.assertEqual(acc.organization, self.org)
            self.assertEqual(acc.currency, "GHS")
            # Verify category prefix invariant
            self.assertTrue(acc.account_code.startswith(acc.category.code[0]))

    def test_seed_standard_chart_of_accounts_is_idempotent(self):
        """Calling seed_standard_chart_of_accounts repeatedly does not duplicate accounts."""
        initial_accounts = seed_standard_chart_of_accounts(self.org)
        initial_count = ChartOfAccounts.objects.filter(organization=self.org).count()

        second_run_accounts = seed_standard_chart_of_accounts(self.org)
        second_count = ChartOfAccounts.objects.filter(organization=self.org).count()

        self.assertEqual(len(second_run_accounts), 0)
        self.assertEqual(initial_count, second_count)
        self.assertEqual(len(initial_accounts), initial_count)

    def test_generate_fiscal_periods_creates_twelve_monthly_periods(self):
        """generate_fiscal_periods creates 12 monthly periods covering the whole year."""
        periods = generate_fiscal_periods(self.org, year=2026)

        self.assertEqual(len(periods), 12)
        self.assertEqual(FiscalPeriod.objects.filter(organization=self.org).count(), 12)

        # Verify January period
        jan_period = periods[0]
        self.assertEqual(jan_period.start_date, datetime.date(2026, 1, 1))
        self.assertEqual(jan_period.end_date, datetime.date(2026, 1, 31))
        self.assertEqual(jan_period.period_name, "January 2026")
        self.assertFalse(jan_period.is_closed)

        # Verify December period
        dec_period = periods[11]
        self.assertEqual(dec_period.start_date, datetime.date(2026, 12, 1))
        self.assertEqual(dec_period.end_date, datetime.date(2026, 12, 31))
        self.assertEqual(dec_period.period_name, "December 2026")

        # Verify FiscalCalendar was auto-created
        calendar = FiscalCalendar.objects.get(organization=self.org)
        self.assertEqual(calendar.period_length, PeriodLengthChoices.MONTHLY)

    def test_generate_fiscal_periods_is_idempotent(self):
        """Calling generate_fiscal_periods multiple times for the same year does not duplicate."""
        generate_fiscal_periods(self.org, year=2026)
        initial_count = FiscalPeriod.objects.filter(organization=self.org).count()

        generate_fiscal_periods(self.org, year=2026)
        second_count = FiscalPeriod.objects.filter(organization=self.org).count()

        self.assertEqual(initial_count, 12)
        self.assertEqual(initial_count, second_count)
