"""Double-Entry Ledger Foundation: Fiscal Calendar, Period Locking, and Chart of Accounts.

Implements:
1. FiscalCalendar: Tenant-scoped calendar specifying period length and fiscal year-end date.
2. FiscalPeriod: Period-locking boundaries for ledger immutability and statutory audit.
3. AccountCategory: Master classifications (Assets, Liabilities, Equity, Income, Expenses).
4. ChartOfAccounts: 4-digit hierarchy accounts (1000-5999) with Ghanaian standard mappings.
"""

from typing import Any

import uuid6
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import BaseTenantModel


class PeriodLengthChoices(models.TextChoices):
    """Supported accounting period lengths for fiscal reporting."""

    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    ANNUALLY = "annually", "Annually"


class NormalBalanceChoices(models.TextChoices):
    """Normal accounting balance direction under double-entry bookkeeping."""

    DEBIT = "DEBIT", "Debit"
    CREDIT = "CREDIT", "Credit"


class CategoryCodeChoices(models.TextChoices):
    """The 5 primary 4-digit master account classifications."""

    ASSETS = "1000", "Assets"
    LIABILITIES = "2000", "Liabilities"
    EQUITY = "3000", "Equity"
    INCOME = "4000", "Income"
    EXPENSES = "5000", "Expenses"


class FiscalCalendar(BaseTenantModel):
    """Defines the organization's fiscal year configuration and period lengths."""

    period_length = models.CharField(
        max_length=20,
        choices=PeriodLengthChoices.choices,
        default=PeriodLengthChoices.MONTHLY,
        help_text="Frequency of financial reporting periods.",
    )
    fiscal_year_end_month = models.PositiveSmallIntegerField(
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Month of fiscal year end (1 = January, 12 = December).",
    )
    fiscal_year_end_day = models.PositiveSmallIntegerField(
        default=31,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Day of fiscal year end.",
    )

    class Meta(BaseTenantModel.Meta):
        db_table = "fiscal_calendars"
        verbose_name = "Fiscal Calendar"
        verbose_name_plural = "Fiscal Calendars"
        constraints = BaseTenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["organization"],
                name="unique_org_fiscal_calendar",
            )
        ]

    def __str__(self) -> str:
        return f"{self.organization.name} Calendar ({self.get_period_length_display()})"


class FiscalPeriod(BaseTenantModel):
    """Discrete, bounded accounting period enforcing closed-period ledger locking."""

    calendar = models.ForeignKey(
        FiscalCalendar,
        on_delete=models.CASCADE,
        related_name="periods",
        null=True,
        blank=True,
        help_text="Parent fiscal calendar defining this period.",
    )
    period_name = models.CharField(
        max_length=50,
        help_text="Descriptive period label (e.g., 'January 2026', '2026-Q1').",
    )
    start_date = models.DateField(help_text="First calendar day of the period.")
    end_date = models.DateField(help_text="Last calendar day of the period.")
    is_closed = models.BooleanField(
        default=False,
        help_text="When True, transactions can no longer be posted without signed rectification.",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when period was locked.",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_fiscal_periods",
        help_text="Authorized user who closed the financial period.",
    )

    class Meta(BaseTenantModel.Meta):
        db_table = "fiscal_periods"
        verbose_name = "Fiscal Period"
        verbose_name_plural = "Fiscal Periods"
        ordering = ["start_date"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["organization", "start_date", "end_date"],
                name="unique_org_fiscal_period_dates",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="fiscal_period_date_range_valid",
            ),
        ]

    def __str__(self) -> str:
        status_label = "Closed" if self.is_closed else "Open"
        return f"{self.period_name} ({self.start_date} to {self.end_date}) [{status_label}]"

    def clean(self) -> None:
        """Enforces period date boundaries."""
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date must be greater than or equal to start date."}
            )

    def close_period(self, user: Any) -> None:
        """Locks the period preventing future journal entries."""
        self.is_closed = True
        self.closed_at = timezone.now()
        self.closed_by = user
        self.save(update_fields=["is_closed", "closed_at", "closed_by", "updated_at"])

    def reopen_period(self) -> None:
        """Reopens the period for rectification."""
        self.is_closed = False
        self.closed_at = None
        self.closed_by = None
        self.save(update_fields=["is_closed", "closed_at", "closed_by", "updated_at"])


class AccountCategory(models.Model):
    """Global reference entity defining standard double-entry account categories."""

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    code = models.CharField(
        max_length=10,
        unique=True,
        choices=CategoryCodeChoices.choices,
        help_text="Statutory category prefix code (1000, 2000, 3000, 4000, 5000).",
    )
    name = models.CharField(max_length=100, help_text="Category name (Assets, Liabilities, etc.).")
    normal_balance = models.CharField(
        max_length=10,
        choices=NormalBalanceChoices.choices,
        help_text="Standard normal balance direction for accounts in this category.",
    )

    class Meta:
        db_table = "account_categories"
        verbose_name = "Account Category"
        verbose_name_plural = "Account Categories"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name} ({self.normal_balance})"


class ChartOfAccounts(BaseTenantModel):
    """Tenant-scoped General Ledger accounts adhering to Ghanaian 4-digit hierarchy."""

    account_code = models.CharField(
        max_length=20,
        help_text="4-digit accounting code (e.g., '1010', '2100', '4000', '5010').",
    )
    account_name = models.CharField(
        max_length=150,
        help_text="Formal accounting title (e.g., 'Cash on Hand', 'GRA Standard VAT Output').",
    )
    simple_label = models.CharField(
        max_length=150,
        blank=True,
        help_text="Simplified human-friendly title for Simple Mode (Kofi).",
    )
    category = models.ForeignKey(
        AccountCategory,
        on_delete=models.PROTECT,
        related_name="accounts",
        help_text="Master category classifying this account.",
    )
    parent_account = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sub_accounts",
        help_text="Optional parent account for sub-ledger aggregation.",
    )
    currency = models.CharField(
        max_length=3,
        default="GHS",
        help_text="Currency ISO code for this account.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Soft-activation flag. Inactive accounts cannot accept new postings.",
    )

    class Meta(BaseTenantModel.Meta):
        db_table = "chart_of_accounts"
        verbose_name = "Chart of Accounts"
        verbose_name_plural = "Charts of Accounts"
        ordering = ["account_code"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["organization", "account_code"],
                name="unique_org_account_code",
            )
        ]

    def __str__(self) -> str:
        return f"{self.account_code} - {self.account_name} ({self.organization.name})"

    @property
    def normal_balance(self) -> str:
        """Returns the normal balance direction (DEBIT or CREDIT) from the parent category."""
        return self.category.normal_balance

    def clean(self) -> None:
        """Enforces 4-digit category prefix and parent account tenant isolation."""
        super().clean()

        # Validate that account_code matches the category code prefix
        if self.account_code and hasattr(self, "category") and self.category:
            expected_prefix = self.category.code[0]
            if not self.account_code.startswith(expected_prefix):
                raise ValidationError(
                    {
                        "account_code": (
                            f"Account code '{self.account_code}' must begin with "
                            f"'{expected_prefix}' for category '{self.category.name}'."
                        )
                    }
                )

        # Validate parent account belongs to the same organization and category
        if self.parent_account:
            if self.parent_account.organization_id != self.organization_id:
                raise ValidationError(
                    {"parent_account": "Parent account must belong to the same organization."}
                )
            if self.parent_account.category_id != self.category_id:
                raise ValidationError(
                    {"parent_account": "Parent account must belong to the same account category."}
                )
            if self.parent_account_id == self.id:
                raise ValidationError({"parent_account": "An account cannot be its own parent."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Runs clean() to ensure account invariants are preserved upon persistence."""
        self.clean()
        super().save(*args, **kwargs)
