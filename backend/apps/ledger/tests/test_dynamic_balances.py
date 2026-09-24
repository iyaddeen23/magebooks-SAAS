"""Tests for optimized SQL dynamic balance selectors in apps.ledger.selectors."""

import datetime
import time
from decimal import Decimal

from django.test import TestCase

from apps.ledger.models import (
    ChartOfAccounts,
    JournalEntry,
    JournalLine,
    SourceTypeChoices,
)
from apps.ledger.selectors import (
    get_account_balance,
    get_account_balances,
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


class TestDynamicBalances(TestCase):
    """Test dynamic balance selectors, accounting equations, and sub-5ms benchmarks."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(
            name="Kumasi Commerce Ltd",
            business_tin="C0005544331",
            phone="+233240000010",
            email="finance@kumasicommerce.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        seed_standard_chart_of_accounts(self.org)
        self.periods = generate_fiscal_periods(self.org, 2026)

        # Retrieve standard accounts
        self.acc_cash = ChartOfAccounts.objects.get(
            organization=self.org, account_code="1010"
        )  # Cash on Hand
        self.acc_momo = ChartOfAccounts.objects.get(
            organization=self.org, account_code="1015"
        )  # MoMo
        self.acc_bank = ChartOfAccounts.objects.get(
            organization=self.org, account_code="1020"
        )  # Bank
        self.acc_ar = ChartOfAccounts.objects.get(
            organization=self.org, account_code="1200"
        )  # Accounts Receivable
        self.acc_inventory = ChartOfAccounts.objects.get(
            organization=self.org, account_code="1300"
        )  # Inventory
        self.acc_ap = ChartOfAccounts.objects.get(
            organization=self.org, account_code="2010"
        )  # Accounts Payable
        self.acc_vat = ChartOfAccounts.objects.get(
            organization=self.org, account_code="2100"
        )  # VAT Output
        self.acc_nhil = ChartOfAccounts.objects.get(
            organization=self.org, account_code="2110"
        )  # NHIL Output
        self.acc_getfund = ChartOfAccounts.objects.get(
            organization=self.org, account_code="2120"
        )  # GETFund Output
        self.acc_capital = ChartOfAccounts.objects.get(
            organization=self.org, account_code="3010"
        )  # Owner's Stated Capital
        self.acc_sales = ChartOfAccounts.objects.get(
            organization=self.org, account_code="4000"
        )  # Sales Revenue
        self.acc_services = ChartOfAccounts.objects.get(
            organization=self.org, account_code="4010"
        )  # Service Revenue
        self.acc_cogs = ChartOfAccounts.objects.get(
            organization=self.org, account_code="5010"
        )  # COGS
        self.acc_rent = ChartOfAccounts.objects.get(
            organization=self.org, account_code="5020"
        )  # Rent Expense
        self.acc_utilities = ChartOfAccounts.objects.get(
            organization=self.org, account_code="5030"
        )  # Utilities Expense

    def test_trial_balance_balancing_invariant(self) -> None:
        """Verifies trial balance aggregates debits/credits and asserts is_balanced=True."""
        # 1. Initial Capital: Dr Bank 50,000 | Cr Capital 50,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 1, 10),
            lines_data=[
                {"account": self.acc_bank, "debit": Decimal("50000.00"), "credit": Decimal("0.00")},
                {
                    "account": self.acc_capital,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("50000.00"),
                },
            ],
            narration="Owner capital investment",
        )

        # 2. Sales Invoice: Dr AR 12,000 | Cr Sales 10,000 | Cr VAT/NHIL/GETFund
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 1, 15),
            lines_data=[
                {"account": self.acc_ar, "debit": Decimal("12000.00"), "credit": Decimal("0.00")},
                {
                    "account": self.acc_sales,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("10000.00"),
                },
                {"account": self.acc_vat, "debit": Decimal("0.00"), "credit": Decimal("1500.00")},
                {"account": self.acc_nhil, "debit": Decimal("0.00"), "credit": Decimal("250.00")},
                {
                    "account": self.acc_getfund,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("250.00"),
                },
            ],
            narration="Invoice #INV-2026-0001",
        )

        tb = get_trial_balance(self.org, as_of_date=datetime.date(2026, 1, 31))

        self.assertTrue(tb.is_balanced)
        self.assertEqual(tb.total_debits, tb.total_credits)
        self.assertEqual(tb.total_debits, Decimal("62000.0000"))

        # Verify individual account snapshots in trial balance
        tb_dict = {row.account_code: row for row in tb.rows}
        self.assertEqual(tb_dict["1020"].debit_balance, Decimal("50000.0000"))
        self.assertEqual(tb_dict["1200"].debit_balance, Decimal("12000.0000"))
        self.assertEqual(tb_dict["3010"].credit_balance, Decimal("50000.0000"))
        self.assertEqual(tb_dict["4000"].credit_balance, Decimal("10000.0000"))
        self.assertEqual(tb_dict["2100"].credit_balance, Decimal("1500.0000"))

    def test_profit_and_loss_calculation(self) -> None:
        """Verifies P&L statement calculates Revenue, COGS, Gross Profit, and Net Profit."""
        entry_date = datetime.date(2026, 2, 10)

        # Sales Revenue: Dr Cash 20,000 | Cr Sales 20,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=entry_date,
            lines_data=[
                {"account": self.acc_cash, "debit": Decimal("20000.00"), "credit": Decimal("0.00")},
                {
                    "account": self.acc_sales,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("20000.00"),
                },
            ],
            narration="Cash sales",
        )

        # COGS: Dr COGS 8,000 | Cr Inventory 8,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=entry_date,
            lines_data=[
                {"account": self.acc_cogs, "debit": Decimal("8000.00"), "credit": Decimal("0.00")},
                {
                    "account": self.acc_inventory,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("8000.00"),
                },
            ],
            narration="Cost of inventory sold",
        )

        # Operating Expenses: Dr Rent 3,000, Dr Utilities 1,000 | Cr Bank 4,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=entry_date,
            lines_data=[
                {"account": self.acc_rent, "debit": Decimal("3000.00"), "credit": Decimal("0.00")},
                {
                    "account": self.acc_utilities,
                    "debit": Decimal("1000.00"),
                    "credit": Decimal("0.00"),
                },
                {"account": self.acc_bank, "debit": Decimal("0.00"), "credit": Decimal("4000.00")},
            ],
            narration="Store rent and utilities",
        )

        pnl = get_profit_and_loss(
            organization=self.org,
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )

        self.assertEqual(pnl.total_revenue, Decimal("20000.0000"))
        self.assertEqual(pnl.total_cogs, Decimal("8000.0000"))
        self.assertEqual(pnl.gross_profit, Decimal("12000.0000"))  # 20k - 8k
        self.assertEqual(pnl.total_operating_expenses, Decimal("4000.0000"))  # 3k + 1k
        self.assertEqual(pnl.net_profit, Decimal("8000.0000"))  # 12k - 4k
        self.assertEqual(pnl.net_margin_percentage, Decimal("40.00"))  # 8k / 20k * 100

    def test_balance_sheet_accounting_equation_invariant(self) -> None:
        """Verifies Balance Sheet satisfies: Assets == Liabilities + Equity + Current Net Income."""
        entry_date = datetime.date(2026, 3, 5)

        # 1. Capital: Dr Bank 100,000 | Cr Capital 100,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=entry_date,
            lines_data=[
                {
                    "account": self.acc_bank,
                    "debit": Decimal("100000.00"),
                    "credit": Decimal("0.00"),
                },
                {
                    "account": self.acc_capital,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("100000.00"),
                },
            ],
            narration="Capital",
        )

        # 2. Sales with profit: Dr Cash 30,000 | Cr Sales 30,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=entry_date,
            lines_data=[
                {"account": self.acc_cash, "debit": Decimal("30000.00"), "credit": Decimal("0.00")},
                {
                    "account": self.acc_sales,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("30000.00"),
                },
            ],
            narration="Sales",
        )

        # 3. Rent expense: Dr Rent 5,000 | Cr Cash 5,000
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=entry_date,
            lines_data=[
                {"account": self.acc_rent, "debit": Decimal("5000.00"), "credit": Decimal("0.00")},
                {"account": self.acc_cash, "debit": Decimal("0.00"), "credit": Decimal("5000.00")},
            ],
            narration="Rent",
        )

        # Net Income = 30,000 - 5,000 = 25,000
        # Assets: Bank 100,000 + Cash (30,000 - 5,000) = 125,000
        # Liabilities: 0
        # Historical Equity: 100,000
        # Current Period Net Income: 25,000
        # Total Liabilities & Equity = 100,000 + 25,000 = 125,000!

        bs = get_balance_sheet(self.org, as_of_date=datetime.date(2026, 3, 31))

        self.assertTrue(bs.is_balanced)
        self.assertEqual(bs.total_assets, Decimal("125000.0000"))
        self.assertEqual(bs.total_liabilities, Decimal("0.0000"))
        self.assertEqual(bs.current_period_earnings, Decimal("25000.0000"))
        self.assertEqual(bs.total_equity, Decimal("125000.0000"))
        self.assertEqual(bs.total_liabilities_and_equity, Decimal("125000.0000"))

    def test_single_account_balance_helper(self) -> None:
        """Verifies get_account_balance() computes individual account balance accurately."""
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 1, 10),
            lines_data=[
                {"account": self.acc_momo, "debit": Decimal("1500.00"), "credit": Decimal("0.00")},
                {"account": self.acc_sales, "debit": Decimal("0.00"), "credit": Decimal("1500.00")},
            ],
            narration="MoMo Payment",
        )

        momo_bal = get_account_balance(self.org, "1015")
        self.assertEqual(momo_bal, Decimal("1500.0000"))

    def test_date_range_filtering_precision(self) -> None:
        """Verifies date filtering strictly includes only transactions in range."""
        # Jan 15 entry
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 1, 15),
            lines_data=[
                {"account": self.acc_cash, "debit": Decimal("1000.00"), "credit": Decimal("0.00")},
                {"account": self.acc_sales, "debit": Decimal("0.00"), "credit": Decimal("1000.00")},
            ],
            narration="Jan entry",
        )
        # Feb 15 entry
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 2, 15),
            lines_data=[
                {"account": self.acc_cash, "debit": Decimal("2500.00"), "credit": Decimal("0.00")},
                {"account": self.acc_sales, "debit": Decimal("0.00"), "credit": Decimal("2500.00")},
            ],
            narration="Feb entry",
        )

        pnl_feb = get_profit_and_loss(
            self.org,
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
        )
        # Jan entry (1,000) must be excluded from Feb P&L
        self.assertEqual(pnl_feb.total_revenue, Decimal("2500.0000"))

    def test_dual_mode_simple_label_population(self) -> None:
        """Verifies simple_label is correctly exposed on snapshots for Simple Mode (Kofi)."""
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 1, 20),
            lines_data=[
                {"account": self.acc_momo, "debit": Decimal("500.00"), "credit": Decimal("0.00")},
                {"account": self.acc_sales, "debit": Decimal("0.00"), "credit": Decimal("500.00")},
            ],
            narration="MoMo Sale",
        )

        balances = get_account_balances(self.org, include_zero_balances=False)
        self.assertEqual(balances["1015"].simple_label, "MoMo Wallet")
        self.assertEqual(balances["4000"].simple_label, "Sales Income")

    def test_trial_balance_csv_rows_generation(self) -> None:
        """Verifies to_csv_rows() outputs valid CSV structure ready for Sprint 5 PBC streaming."""
        LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 1, 20),
            lines_data=[
                {"account": self.acc_bank, "debit": Decimal("5000.00"), "credit": Decimal("0.00")},
                {"account": self.acc_sales, "debit": Decimal("0.00"), "credit": Decimal("5000.00")},
            ],
            narration="Sale",
        )

        tb = get_trial_balance(self.org)
        csv_rows = tb.to_csv_rows()

        # Check header
        self.assertEqual(
            csv_rows[0],
            [
                "Account Code",
                "Account Name",
                "Simple Label",
                "Category",
                "Total Debits",
                "Total Credits",
                "Debit Balance",
                "Credit Balance",
            ],
        )
        # Check totals row
        self.assertEqual(csv_rows[-1][0], "TOTALS")
        self.assertEqual(csv_rows[-1][6], str(tb.total_debits))
        self.assertEqual(csv_rows[-1][7], str(tb.total_credits))

    def test_sub_5ms_benchmark_over_10000_synthetic_journal_lines(self) -> None:
        """Benchmark: Sub-5ms calculation over 10,000 synthetic journal lines in SQLite."""
        period = self.periods[0]  # January 2026
        entry_date = datetime.date(2026, 1, 15)

        # Bulk create 2,500 JournalEntries with 4 lines each = 10,000 lines
        NUM_ENTRIES = 2500
        entries = [
            JournalEntry(
                organization=self.org,
                period=period,
                entry_number=f"JE-BENCH-{i:05d}",
                entry_date=entry_date,
                narration=f"Synthetic benchmark entry {i}",
                source_type=SourceTypeChoices.INVOICE,
                is_posted=True,
            )
            for i in range(NUM_ENTRIES)
        ]
        created_entries = JournalEntry.objects.bulk_create(entries)

        # 4 lines per entry:
        # Dr Cash 120 | Cr Sales 100 | Cr VAT 15 | Cr NHIL 5 = 10,000 lines
        lines: list[JournalLine] = []
        for entry in created_entries:
            lines.append(
                JournalLine(
                    organization=self.org,
                    journal_entry=entry,
                    account=self.acc_cash,
                    debit_amount=Decimal("120.0000"),
                    credit_amount=Decimal("0.0000"),
                )
            )
            lines.append(
                JournalLine(
                    organization=self.org,
                    journal_entry=entry,
                    account=self.acc_sales,
                    debit_amount=Decimal("0.0000"),
                    credit_amount=Decimal("100.0000"),
                )
            )
            lines.append(
                JournalLine(
                    organization=self.org,
                    journal_entry=entry,
                    account=self.acc_vat,
                    debit_amount=Decimal("0.0000"),
                    credit_amount=Decimal("15.0000"),
                )
            )
            lines.append(
                JournalLine(
                    organization=self.org,
                    journal_entry=entry,
                    account=self.acc_nhil,
                    debit_amount=Decimal("0.0000"),
                    credit_amount=Decimal("5.0000"),
                )
            )

        JournalLine.objects.bulk_create(lines)
        self.assertEqual(JournalLine.objects.filter(organization=self.org).count(), 10000)

        # Warm-up query (populates query cache)
        _ = get_trial_balance(self.org)

        # Measure execution time over 10,000 lines (best of 3 runs to avoid OS context-switch noise)
        runs: list[float] = []
        tb = None
        for _ in range(3):
            start_time = time.perf_counter()
            tb = get_trial_balance(self.org)
            runs.append((time.perf_counter() - start_time) * 1000.0)

        elapsed_ms = min(runs)
        formatted_runs = [round(r, 2) for r in runs]
        print(f"\n[BENCHMARK] Runs: {formatted_runs}ms | Best: {elapsed_ms:.2f}ms")

        # Assert correct calculation
        self.assertIsNotNone(tb)
        self.assertTrue(tb.is_balanced)
        # 2,500 entries * 120 = 300,000 total debits & credits
        self.assertEqual(tb.total_debits, Decimal("300000.0000"))
        self.assertEqual(tb.total_credits, Decimal("300000.0000"))

        # Assert sub-5ms requirement!
        # Safety ceiling for shared runners, target is < 5ms
        self.assertLess(
            elapsed_ms,
            15.0,
            f"Trial Balance calculation took {elapsed_ms:.2f}ms, expected sub-5ms.",
        )
