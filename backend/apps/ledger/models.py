"""Double-Entry Ledger Foundation: Fiscal Calendar, Period Locking, and Chart of Accounts.

Implements:
1. FiscalCalendar: Tenant-scoped calendar specifying period length and fiscal year-end date.
2. FiscalPeriod: Period-locking boundaries for ledger immutability and statutory audit.
3. AccountCategory: Master classifications (Assets, Liabilities, Equity, Income, Expenses).
4. ChartOfAccounts: 4-digit hierarchy accounts (1000-5999) with Ghanaian standard mappings.
"""

from decimal import Decimal
from typing import Any

import uuid6
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import BaseTenantModel, TenantQuerySet


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


class SourceTypeChoices(models.TextChoices):
    """Statutory and operational origin of the double-entry transaction."""

    MANUAL = "MANUAL", "Manual Journal Entry"
    INVOICE = "INVOICE", "Customer Invoice"
    BILL = "BILL", "Vendor Bill"
    PAYMENT = "PAYMENT", "Payment Receipt / Disbursement"
    PAYROLL = "PAYROLL", "Payroll Run Disbursal"
    RECTIFICATION = "RECTIFICATION", "Prior Period Rectification"


class JournalEntryQuerySet(TenantQuerySet):
    """QuerySet enforcing immutability across posted journal entries."""

    def delete(self) -> tuple[int, dict[str, int]]:
        if self.filter(is_posted=True).exists():
            raise ValidationError("Cannot delete posted journal entries.")
        return super().delete()

    def update(self, **kwargs: Any) -> int:
        if self.filter(is_posted=True).exists():
            raise ValidationError("Cannot modify posted journal entries.")
        return super().update(**kwargs)


class JournalLineQuerySet(TenantQuerySet):
    """QuerySet enforcing immutability across lines of posted journal entries."""

    def delete(self) -> tuple[int, dict[str, int]]:
        if self.filter(journal_entry__is_posted=True).exists():
            raise ValidationError("Cannot delete lines belonging to a posted journal entry.")
        return super().delete()

    def update(self, **kwargs: Any) -> int:
        if self.filter(journal_entry__is_posted=True).exists():
            raise ValidationError("Cannot modify lines belonging to a posted journal entry.")
        return super().update(**kwargs)


class JournalEntry(BaseTenantModel):
    """Double-entry General Ledger transaction header.

    Strictly immutable once posted (is_posted=True).
    """

    period = models.ForeignKey(
        FiscalPeriod,
        on_delete=models.PROTECT,
        related_name="journal_entries",
        help_text="Fiscal period governing this accounting transaction.",
    )
    entry_number = models.CharField(
        max_length=50,
        help_text="Tenant-scoped unique identifier (e.g. 'JE-2026-00042').",
    )
    entry_date = models.DateField(
        help_text="Formal transaction date for accounting recognition.",
    )
    narration = models.TextField(
        help_text="Business description and audit explanation of the transaction.",
    )
    source_type = models.CharField(
        max_length=50,
        choices=SourceTypeChoices.choices,
        default=SourceTypeChoices.MANUAL,
        help_text="Originating operational subsystem.",
    )
    source_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Polymorphic UUID reference to originating document (Invoice, Payment, etc.).",
    )
    is_posted = models.BooleanField(
        default=True,
        help_text="Immutability lock. Posted entries cannot be updated or deleted via SQL.",
    )
    posted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when entry was committed to the general ledger.",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_journal_entries",
        help_text="User who authorized or posted the entry. Null for automated machine events.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_journal_entries",
        help_text="User who drafted the entry. Null for automated machine events.",
    )

    objects = JournalEntryQuerySet.as_manager()

    class Meta(BaseTenantModel.Meta):
        db_table = "journal_entries"
        verbose_name = "Journal Entry"
        verbose_name_plural = "Journal Entries"
        ordering = ["-entry_date", "-created_at"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["organization", "entry_number"],
                name="unique_org_journal_entry_number",
            )
        ]

    def __str__(self) -> str:
        return f"{self.entry_number} ({self.entry_date}) [{self.source_type}]"

    def clean(self) -> None:
        super().clean()

        if self.period:
            if self.period.organization_id != self.organization_id:
                raise ValidationError(
                    {"period": "Fiscal period must belong to the same organization."}
                )
            if self.entry_date and not (
                self.period.start_date <= self.entry_date <= self.period.end_date
            ):
                raise ValidationError(
                    {
                        "entry_date": (
                            f"Entry date {self.entry_date} falls outside fiscal period "
                            f"'{self.period.period_name}' "
                            f"({self.period.start_date} to {self.period.end_date})."
                        )
                    }
                )
            # Safeguard 1: Restrict is_closed validation strictly to new entries being added
            if self._state.adding and self.period.is_closed:
                raise ValidationError(
                    {"period": "Cannot post transaction to a closed fiscal period."}
                )

        if not self._state.adding and self.pk:
            orig = (
                JournalEntry.objects.filter(pk=self.pk)
                .values(
                    "is_posted",
                    "entry_number",
                    "entry_date",
                    "period_id",
                    "narration",
                    "source_type",
                    "source_id",
                    "organization_id",
                )
                .first()
            )
            if (
                orig
                and orig["is_posted"]
                and (
                    self.entry_number != orig["entry_number"]
                    or self.entry_date != orig["entry_date"]
                    or self.period_id != orig["period_id"]
                    or self.narration != orig["narration"]
                    or self.source_type != orig["source_type"]
                    or self.source_id != orig["source_id"]
                    or self.organization_id != orig["organization_id"]
                )
            ):
                raise ValidationError("Posted journal entries are strictly immutable.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding and self.pk:
            orig = JournalEntry.objects.filter(pk=self.pk).values("is_posted").first()
            if orig and orig["is_posted"]:
                raise ValidationError("Posted journal entries are strictly immutable.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.is_posted:
            raise ValidationError("Cannot delete a posted journal entry.")
        return super().delete(*args, **kwargs)


class JournalLine(BaseTenantModel):
    """Individual debit or credit ledger line belonging to a JournalEntry."""

    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
        help_text="Parent journal entry header.",
    )
    account = models.ForeignKey(
        ChartOfAccounts,
        on_delete=models.PROTECT,
        related_name="journal_lines",
        help_text="Target general ledger account.",
    )
    description = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Line-item memo or specific transaction detail.",
    )
    debit_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Debit value in tenant base currency (GHS).",
    )
    credit_amount = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Credit value in tenant base currency (GHS).",
    )

    objects = JournalLineQuerySet.as_manager()

    class Meta(BaseTenantModel.Meta):
        db_table = "journal_lines"
        verbose_name = "Journal Line"
        verbose_name_plural = "Journal Lines"
        ordering = ["created_at"]
        constraints = BaseTenantModel.Meta.constraints + [
            models.CheckConstraint(
                condition=models.Q(debit_amount__gte=Decimal("0.0000"))
                & models.Q(credit_amount__gte=Decimal("0.0000")),
                name="jline_check_positive_values",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(debit_amount__gt=Decimal("0.0000"), credit_amount=Decimal("0.0000"))
                    | models.Q(credit_amount__gt=Decimal("0.0000"), debit_amount=Decimal("0.0000"))
                ),
                name="jline_check_either_debit_or_credit",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "account", "debit_amount", "credit_amount"],
                name="idx_jl_org_acc_deb_cred",
            ),
        ]

    def __str__(self) -> str:
        if self.debit_amount > Decimal("0.0000"):
            return f"Dr {self.account.account_code} - GHS {self.debit_amount}"
        return f"Cr {self.account.account_code} - GHS {self.credit_amount}"

    def clean(self) -> None:
        super().clean()

        if self.journal_entry_id and self.journal_entry.organization_id != self.organization_id:
            raise ValidationError(
                {
                    "journal_entry": (
                        "Journal line organization must match journal entry organization."
                    )
                }
            )

        if self.account_id and self.account.organization_id != self.organization_id:
            raise ValidationError(
                {"account": "Account must belong to the same organization as the journal line."}
            )

        if self.debit_amount == Decimal("0.0000") and self.credit_amount == Decimal("0.0000"):
            raise ValidationError(
                "Journal line must have either a positive debit or credit amount."
            )

        if self.debit_amount > Decimal("0.0000") and self.credit_amount > Decimal("0.0000"):
            raise ValidationError("Journal line cannot have both debit and credit amounts.")

        if (
            not self._state.adding
            and self.pk
            and self.journal_entry_id
            and self.journal_entry.is_posted
        ):
            orig = (
                JournalLine.objects.filter(pk=self.pk)
                .values("account_id", "debit_amount", "credit_amount", "description")
                .first()
            )
            if orig and (
                self.account_id != orig["account_id"]
                or self.debit_amount != orig["debit_amount"]
                or self.credit_amount != orig["credit_amount"]
                or self.description != orig["description"]
            ):
                raise ValidationError("Cannot modify lines belonging to a posted journal entry.")

    def save(self, *args: Any, **kwargs: Any) -> None:
        if (
            not self._state.adding
            and self.pk
            and self.journal_entry_id
            and self.journal_entry.is_posted
        ):
            raise ValidationError("Cannot modify lines belonging to a posted journal entry.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        if self.journal_entry_id and self.journal_entry.is_posted:
            raise ValidationError("Cannot delete lines belonging to a posted journal entry.")
        return super().delete(*args, **kwargs)
