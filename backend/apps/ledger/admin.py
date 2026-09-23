"""Django admin configuration for Ledger Foundation models."""

from django.contrib import admin

from apps.ledger.models import AccountCategory, ChartOfAccounts, FiscalCalendar, FiscalPeriod


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
