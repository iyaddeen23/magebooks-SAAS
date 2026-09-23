"""Django admin configuration for Ledger Foundation models."""

from typing import Any

from django.contrib import admin

from apps.ledger.models import (
    AccountCategory,
    ChartOfAccounts,
    FiscalCalendar,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
)


@admin.register(AccountCategory)
class AccountCategoryAdmin(admin.ModelAdmin):
    """Admin configuration for master Account Categories."""

    list_display = ("code", "name", "normal_balance")
    search_fields = ("code", "name")
    list_filter = ("normal_balance",)
    ordering = ("code",)


@admin.register(FiscalCalendar)
class FiscalCalendarAdmin(admin.ModelAdmin):
    """Admin configuration for tenant Fiscal Calendars."""

    list_display = (
        "organization",
        "period_length",
        "fiscal_year_end_month",
        "fiscal_year_end_day",
        "created_at",
    )
    list_filter = ("period_length", "fiscal_year_end_month")
    search_fields = ("organization__name",)
    raw_id_fields = ("organization",)


@admin.register(FiscalPeriod)
class FiscalPeriodAdmin(admin.ModelAdmin):
    """Admin configuration for Fiscal Periods."""

    list_display = (
        "period_name",
        "organization",
        "start_date",
        "end_date",
        "is_closed",
        "closed_at",
        "closed_by",
    )
    list_filter = ("is_closed", "organization")
    search_fields = ("period_name", "organization__name")
    raw_id_fields = ("organization", "calendar", "closed_by")
    ordering = ("start_date",)


@admin.register(ChartOfAccounts)
class ChartOfAccountsAdmin(admin.ModelAdmin):
    """Admin configuration for tenant Chart of Accounts."""

    list_display = (
        "account_code",
        "account_name",
        "simple_label",
        "organization",
        "category",
        "currency",
        "is_active",
    )
    list_filter = ("is_active", "category", "organization")
    search_fields = ("account_code", "account_name", "simple_label", "organization__name")
    raw_id_fields = ("organization", "category", "parent_account")
    ordering = ("account_code",)


class JournalLineInline(admin.TabularInline):
    """Tabular inline for line items of a journal entry."""

    model = JournalLine
    extra = 0
    fields = ("account", "debit_amount", "credit_amount", "description")
    raw_id_fields = ("account", "organization")

    def has_add_permission(self, request: Any, obj: Any = None) -> bool:
        if obj and obj.is_posted:
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        if obj and obj.is_posted:
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        if obj and obj.is_posted:
            return False
        return super().has_change_permission(request, obj)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    """Admin configuration for Journal Entries."""

    list_display = (
        "entry_number",
        "organization",
        "entry_date",
        "period",
        "source_type",
        "is_posted",
        "created_by",
        "created_at",
    )
    list_filter = ("is_posted", "source_type", "organization")
    search_fields = ("entry_number", "narration", "organization__name")
    raw_id_fields = ("organization", "period", "posted_by", "created_by")
    inlines = [JournalLineInline]
    ordering = ("-entry_date", "-created_at")

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        if obj and obj.is_posted:
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        if obj and obj.is_posted:
            return False
        return super().has_change_permission(request, obj)
