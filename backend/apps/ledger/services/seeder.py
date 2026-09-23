"""Ghanaian Standard Chart of Accounts and Fiscal Calendar Seeder Service.

Provides idempotent initialization of:
1. Standard Account Categories (Assets, Liabilities, Equity, Income, Expenses).
2. Standard Ghanaian 4-digit Chart of Accounts compliant with Act 1151 (VAT, NHIL, GETFund).
3. Fiscal Calendar and Fiscal Periods generation.
"""

import calendar
import datetime
from typing import Any

from django.db import transaction

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

# Standard 5 master categories under Ghanaian double-entry accounting
STANDARD_CATEGORIES = [
    {
        "code": CategoryCodeChoices.ASSETS,
        "name": "Assets",
        "normal_balance": NormalBalanceChoices.DEBIT,
    },
    {
        "code": CategoryCodeChoices.LIABILITIES,
        "name": "Liabilities",
        "normal_balance": NormalBalanceChoices.CREDIT,
    },
    {
        "code": CategoryCodeChoices.EQUITY,
        "name": "Equity",
        "normal_balance": NormalBalanceChoices.CREDIT,
    },
    {
        "code": CategoryCodeChoices.INCOME,
        "name": "Income",
        "normal_balance": NormalBalanceChoices.CREDIT,
    },
    {
        "code": CategoryCodeChoices.EXPENSES,
        "name": "Expenses",
        "normal_balance": NormalBalanceChoices.DEBIT,
    },
]

# Ghanaian standard Chart of Accounts template tailored for SME commerce & Act 1151
STANDARD_GHANAIAN_ACCOUNTS = [
    # --- 1000: Assets (Normal Balance: DEBIT) ---
    {
        "code": "1010",
        "name": "Cash on Hand",
        "simple_label": "Petty Cash",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    {
        "code": "1015",
        "name": "Mobile Money Clearing Account",
        "simple_label": "MoMo Wallet",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    {
        "code": "1020",
        "name": "Bank Account - Main",
        "simple_label": "Business Bank Account",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    {
        "code": "1200",
        "name": "Accounts Receivable",
        "simple_label": "Customer Unpaid Invoices",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    {
        "code": "1300",
        "name": "Merchandise Inventory",
        "simple_label": "Goods for Resale",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    {
        "code": "1400",
        "name": "Prepaid Expenses",
        "simple_label": "Advance Payments",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    {
        "code": "1500",
        "name": "Office Furniture & Equipment",
        "simple_label": "Equipment & Machines",
        "category_code": CategoryCodeChoices.ASSETS,
    },
    # --- 2000: Liabilities (Normal Balance: CREDIT) ---
    {
        "code": "2010",
        "name": "Accounts Payable",
        "simple_label": "Supplier Bills to Pay",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2100",
        "name": "GRA Standard VAT Output (15.0%)",
        "simple_label": "VAT Collected",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2110",
        "name": "GRA NHIL Output (2.5%)",
        "simple_label": "NHIL Collected",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2120",
        "name": "GRA GETFund Output (2.5%)",
        "simple_label": "GETFund Collected",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2130",
        "name": "GRA Standard VAT Input (15.0%)",
        "simple_label": "VAT Paid on Purchases",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2140",
        "name": "GRA NHIL Input (2.5%)",
        "simple_label": "NHIL Paid on Purchases",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2145",
        "name": "GRA GETFund Input (2.5%)",
        "simple_label": "GETFund Paid on Purchases",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2150",
        "name": "Suspense Account",
        "simple_label": "Unreconciled Payments",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2200",
        "name": "PAYE Withholding Tax Payable",
        "simple_label": "Staff Tax Payable",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    {
        "code": "2210",
        "name": "SSNIT Contribution Payable",
        "simple_label": "Pension Payable",
        "category_code": CategoryCodeChoices.LIABILITIES,
    },
    # --- 3000: Equity (Normal Balance: CREDIT) ---
    {
        "code": "3010",
        "name": "Owner's Stated Capital",
        "simple_label": "Owner's Investment",
        "category_code": CategoryCodeChoices.EQUITY,
    },
    {
        "code": "3020",
        "name": "Retained Earnings",
        "simple_label": "Cumulative Profit",
        "category_code": CategoryCodeChoices.EQUITY,
    },
    {
        "code": "3030",
        "name": "Owner's Drawings",
        "simple_label": "Money Taken Out",
        "category_code": CategoryCodeChoices.EQUITY,
    },
    # --- 4000: Income (Normal Balance: CREDIT) ---
    {
        "code": "4000",
        "name": "Sales Revenue - Standard Supplies",
        "simple_label": "Sales Income",
        "category_code": CategoryCodeChoices.INCOME,
    },
    {
        "code": "4010",
        "name": "Service Revenue",
        "simple_label": "Service Income",
        "category_code": CategoryCodeChoices.INCOME,
    },
    {
        "code": "4020",
        "name": "Sales Revenue - Exempt Supplies",
        "simple_label": "Exempt Sales",
        "category_code": CategoryCodeChoices.INCOME,
    },
    {
        "code": "4030",
        "name": "Sales Revenue - Zero Rated Exports",
        "simple_label": "Export Sales",
        "category_code": CategoryCodeChoices.INCOME,
    },
    {
        "code": "4090",
        "name": "Other Miscellaneous Income",
        "simple_label": "Other Income",
        "category_code": CategoryCodeChoices.INCOME,
    },
    # --- 5000: Expenses (Normal Balance: DEBIT) ---
    {
        "code": "5010",
        "name": "Cost of Goods Sold (COGS)",
        "simple_label": "Cost of Stock Sold",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5020",
        "name": "Rent Expense",
        "simple_label": "Store / Office Rent",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5030",
        "name": "Electricity & Water Utilities",
        "simple_label": "Light & Water Bills",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5040",
        "name": "Salaries & Staff Wages",
        "simple_label": "Staff Salaries",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5050",
        "name": "Mobile Money & Bank Charges",
        "simple_label": "MoMo & Bank Fees",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5060",
        "name": "Office Supplies & Stationery",
        "simple_label": "Office Supplies",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5070",
        "name": "Marketing & Advertising",
        "simple_label": "Advertising & Promos",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
    {
        "code": "5080",
        "name": "Repairs & Maintenance",
        "simple_label": "Equipment Repairs",
        "category_code": CategoryCodeChoices.EXPENSES,
    },
]


def seed_account_categories() -> dict[str, AccountCategory]:
    """Idempotently creates standard account categories (Assets, Liabilities, etc.).

    Returns a mapping of CategoryCode -> AccountCategory instance.
    """
    categories_by_code: dict[str, AccountCategory] = {}
    for cat_data in STANDARD_CATEGORIES:
        category, _ = AccountCategory.objects.get_or_create(
            code=cat_data["code"],
            defaults={
                "name": cat_data["name"],
                "normal_balance": cat_data["normal_balance"],
            },
        )
        categories_by_code[cat_data["code"]] = category
    return categories_by_code


@transaction.atomic
def seed_standard_chart_of_accounts(organization: Organization) -> list[ChartOfAccounts]:
    """Seeds the standard Ghanaian Chart of Accounts for the given organization.

    Idempotent: skips accounts whose account_code is already registered for this organization.
    """
    categories = seed_account_categories()
    created_accounts: list[ChartOfAccounts] = []

    for acc_data in STANDARD_GHANAIAN_ACCOUNTS:
        category = categories[acc_data["category_code"]]
        account, created = ChartOfAccounts.objects.get_or_create(
            organization=organization,
            account_code=acc_data["code"],
            defaults={
                "account_name": acc_data["name"],
                "simple_label": acc_data["simple_label"],
                "category": category,
                "currency": "GHS",
            },
        )
        if created:
            created_accounts.append(account)

    return created_accounts


@transaction.atomic
def generate_fiscal_periods(
    organization: Organization,
    year: int,
    calendar_instance: FiscalCalendar | None = None,
) -> list[FiscalPeriod]:
    """Generates monthly or quarterly fiscal periods for the specified calendar year.

    Creates a FiscalCalendar if none exists for the organization.
    """
    if not calendar_instance:
        calendar_instance, _ = FiscalCalendar.objects.get_or_create(
            organization=organization,
            defaults={
                "period_length": PeriodLengthChoices.MONTHLY,
                "fiscal_year_end_month": 12,
                "fiscal_year_end_day": 31,
            },
        )

    periods: list[FiscalPeriod] = []

    if calendar_instance.period_length == PeriodLengthChoices.MONTHLY:
        for month in range(1, 13):
            _, last_day = calendar.monthrange(year, month)
            start_date = datetime.date(year, month, 1)
            end_date = datetime.date(year, month, last_day)
            period_name = f"{calendar.month_name[month]} {year}"

            period, _ = FiscalPeriod.objects.get_or_create(
                organization=organization,
                start_date=start_date,
                end_date=end_date,
                defaults={
                    "calendar": calendar_instance,
                    "period_name": period_name,
                    "is_closed": False,
                },
            )
            periods.append(period)

    elif calendar_instance.period_length == PeriodLengthChoices.QUARTERLY:
        quarters = [
            ("Q1", 1, 3),
            ("Q2", 4, 6),
            ("Q3", 7, 9),
            ("Q4", 10, 12),
        ]
        for q_name, start_m, end_m in quarters:
            _, last_day = calendar.monthrange(year, end_m)
            start_date = datetime.date(year, start_m, 1)
            end_date = datetime.date(year, end_m, last_day)
            period_name = f"{year}-{q_name}"

            period, _ = FiscalPeriod.objects.get_or_create(
                organization=organization,
                start_date=start_date,
                end_date=end_date,
                defaults={
                    "calendar": calendar_instance,
                    "period_name": period_name,
                    "is_closed": False,
                },
            )
            periods.append(period)

    return periods
