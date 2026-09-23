"""Unit tests for Ledger Foundation Models (Feature 2.1).

Covers:
- FiscalCalendar: creation, defaults, unique organization constraint.
- FiscalPeriod: date boundary validation, period locking lifecycle (close/reopen).
- AccountCategory: master reference categories and normal balance definitions.
- ChartOfAccounts: 4-digit hierarchy validation, cross-tenant isolation, parent account integrity.
- Protective deletion boundaries (models.PROTECT).
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from apps.ledger.models import (
    AccountCategory,
    CategoryCodeChoices,
    ChartOfAccounts,
    FiscalCalendar,
    FiscalPeriod,
    NormalBalanceChoices,
    PeriodLengthChoices,
)
from apps.tenancy.models import Organization

User = get_user_model()


class LedgerModelTests(TestCase):
    """Test suite validating fiscal calendars, periods, and chart of accounts."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="accountant@magebooks.com",
            password="SecurePassword123!",
            first_name="Kwame",
            last_name="Accountant",
        )
        self.org_a = Organization.objects.create(
            name="Alpha Trading Ltd",
            phone="+233241000111",
            email="alpha@alphatrading.com",
        )
        self.org_b = Organization.objects.create(
            name="Beta Enterprise",
            phone="+233241000222",
            email="beta@betaenterprise.com",
        )

        # Create master account categories
        self.cat_assets = AccountCategory.objects.create(
            code=CategoryCodeChoices.ASSETS,
            name="Assets",
            normal_balance=NormalBalanceChoices.DEBIT,
        )
        self.cat_liabilities = AccountCategory.objects.create(
            code=CategoryCodeChoices.LIABILITIES,
            name="Liabilities",
            normal_balance=NormalBalanceChoices.CREDIT,
        )
        self.cat_equity = AccountCategory.objects.create(
            code=CategoryCodeChoices.EQUITY,
            name="Equity",
            normal_balance=NormalBalanceChoices.CREDIT,
        )
        self.cat_income = AccountCategory.objects.create(
            code=CategoryCodeChoices.INCOME,
            name="Income",
            normal_balance=NormalBalanceChoices.CREDIT,
        )
        self.cat_expenses = AccountCategory.objects.create(
            code=CategoryCodeChoices.EXPENSES,
            name="Expenses",
            normal_balance=NormalBalanceChoices.DEBIT,
        )

    # -------------------------------------------------------------------------
    # FiscalCalendar Tests
    # -------------------------------------------------------------------------

    def test_fiscal_calendar_creation_and_defaults(self):
        """FiscalCalendar creates successfully with default monthly period length and 12/31 end."""
        calendar = FiscalCalendar.objects.create(organization=self.org_a)

        self.assertIsNotNone(calendar.id)
        self.assertEqual(calendar.id.version, 7)
        self.assertEqual(calendar.period_length, PeriodLengthChoices.MONTHLY)
        self.assertEqual(calendar.fiscal_year_end_month, 12)
        self.assertEqual(calendar.fiscal_year_end_day, 31)

    def test_fiscal_calendar_unique_per_organization(self):
        """An organization can only have one active FiscalCalendar."""
        FiscalCalendar.objects.create(organization=self.org_a)

        with self.assertRaises(IntegrityError):
            FiscalCalendar.objects.create(organization=self.org_a)

    # -------------------------------------------------------------------------
    # FiscalPeriod Tests
    # -------------------------------------------------------------------------

    def test_fiscal_period_creation_and_locking_lifecycle(self):
        """FiscalPeriod locks correctly on close_period and unlocks on reopen_period."""
        calendar = FiscalCalendar.objects.create(organization=self.org_a)
        period = FiscalPeriod.objects.create(
            organization=self.org_a,
            calendar=calendar,
            period_name="January 2026",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )

        self.assertFalse(period.is_closed)
        self.assertIsNone(period.closed_at)
        self.assertIsNone(period.closed_by)

        # Lock period
        period.close_period(self.user)
        period.refresh_from_db()

        self.assertTrue(period.is_closed)
        self.assertIsNotNone(period.closed_at)
        self.assertEqual(period.closed_by, self.user)

        # Reopen period
        period.reopen_period()
        period.refresh_from_db()

        self.assertFalse(period.is_closed)
        self.assertIsNone(period.closed_at)
        self.assertIsNone(period.closed_by)

    def test_fiscal_period_invalid_date_range_rejected(self):
        """Period where end_date < start_date raises ValidationError."""
        calendar = FiscalCalendar.objects.create(organization=self.org_a)
        invalid_period = FiscalPeriod(
            organization=self.org_a,
            calendar=calendar,
            period_name="Invalid Period",
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 1, 1),
        )

        with self.assertRaises(ValidationError) as ctx:
            invalid_period.clean()

        self.assertIn("end_date", ctx.exception.message_dict)

    def test_fiscal_period_duplicate_dates_in_same_org_rejected(self):
        """Duplicate period date ranges within the same organization raise IntegrityError."""
        calendar = FiscalCalendar.objects.create(organization=self.org_a)
        FiscalPeriod.objects.create(
            organization=self.org_a,
            calendar=calendar,
            period_name="Jan 2026",
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 31),
        )

        with self.assertRaises(IntegrityError):
            FiscalPeriod.objects.create(
                organization=self.org_a,
                calendar=calendar,
                period_name="Jan 2026 Duplicate",
                start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 1, 31),
            )

    # -------------------------------------------------------------------------
    # ChartOfAccounts Tests
    # -------------------------------------------------------------------------

    def test_chart_of_accounts_creation_and_normal_balance(self):
        """Account creates successfully with UUIDv7 primary key and inherits category balance."""
        cash_account = ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="1010",
            account_name="Cash on Hand",
            simple_label="Petty Cash",
            category=self.cat_assets,
        )

        self.assertIsNotNone(cash_account.id)
        self.assertEqual(cash_account.id.version, 7)
        self.assertEqual(cash_account.normal_balance, NormalBalanceChoices.DEBIT)
        self.assertTrue(cash_account.is_active)

    def test_chart_of_accounts_category_code_prefix_enforced(self):
        """Account code must match the category code prefix (e.g. Assets must start with '1')."""
        # Attempting to assign account code 2010 (Liabilities prefix) to Assets category
        invalid_account = ChartOfAccounts(
            organization=self.org_a,
            account_code="2010",
            account_name="Mismatched Account",
            category=self.cat_assets,
        )

        with self.assertRaises(ValidationError) as ctx:
            invalid_account.clean()

        self.assertIn("account_code", ctx.exception.message_dict)
        self.assertIn("must begin with '1'", ctx.exception.message_dict["account_code"][0])

    def test_chart_of_accounts_unique_per_organization(self):
        """Account code uniqueness is strictly scoped to the tenant organization."""
        # Create 1010 in Org A
        ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="1010",
            account_name="Cash Alpha",
            category=self.cat_assets,
        )

        # Duplicate 1010 in Org A must raise IntegrityError
        with self.assertRaises(IntegrityError):
            ChartOfAccounts.objects.create(
                organization=self.org_a,
                account_code="1010",
                account_name="Duplicate Cash Alpha",
                category=self.cat_assets,
            )

        # Same 1010 code in Org B must succeed (multi-tenant isolation)
        org_b_account = ChartOfAccounts.objects.create(
            organization=self.org_b,
            account_code="1010",
            account_name="Cash Beta",
            category=self.cat_assets,
        )
        self.assertIsNotNone(org_b_account.id)

    def test_parent_account_validation_cross_tenant_rejected(self):
        """Parent account must belong to the exact same organization."""
        parent_in_org_b = ChartOfAccounts.objects.create(
            organization=self.org_b,
            account_code="1000",
            account_name="Current Assets Header",
            category=self.cat_assets,
        )

        child_in_org_a = ChartOfAccounts(
            organization=self.org_a,
            account_code="1010",
            account_name="Child Cash",
            category=self.cat_assets,
            parent_account=parent_in_org_b,
        )

        with self.assertRaises(ValidationError) as ctx:
            child_in_org_a.clean()

        self.assertIn("parent_account", ctx.exception.message_dict)
        self.assertIn("must belong to the same organization", str(ctx.exception))

    def test_parent_account_validation_cross_category_rejected(self):
        """Parent account must share the same category."""
        parent_liability = ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="2000",
            account_name="Current Liabilities Header",
            category=self.cat_liabilities,
        )

        child_asset = ChartOfAccounts(
            organization=self.org_a,
            account_code="1010",
            account_name="Cash Asset",
            category=self.cat_assets,
            parent_account=parent_liability,
        )

        with self.assertRaises(ValidationError) as ctx:
            child_asset.clean()

        self.assertIn("parent_account", ctx.exception.message_dict)
        self.assertIn("must belong to the same account category", str(ctx.exception))

    def test_self_parenting_rejected(self):
        """An account cannot be assigned as its own parent."""
        account = ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="1010",
            account_name="Self Parent Test",
            category=self.cat_assets,
        )
        account.parent_account = account

        with self.assertRaises(ValidationError) as ctx:
            account.clean()

        self.assertIn("parent_account", ctx.exception.message_dict)
        self.assertIn("cannot be its own parent", str(ctx.exception))

    def test_deletion_protection_on_category_and_parent_account(self):
        """Option 2 Protection: Models protected with models.PROTECT prevent cascading deletes."""
        parent = ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="1000",
            account_name="Cash Header",
            category=self.cat_assets,
        )
        ChartOfAccounts.objects.create(
            organization=self.org_a,
            account_code="1010",
            account_name="Cash Sub",
            category=self.cat_assets,
            parent_account=parent,
        )

        # Deleting parent account is blocked by ProtectedError
        with self.assertRaises(ProtectedError):
            parent.delete()

        # Deleting category is blocked by ProtectedError
        with self.assertRaises(ProtectedError):
            self.cat_assets.delete()

        # Deleting organization is blocked by ProtectedError (from BaseTenantModel)
        with self.assertRaises(ProtectedError):
            self.org_a.delete()
