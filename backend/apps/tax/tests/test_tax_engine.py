"""Unit tests for Ghanaian Statutory Tax Engine under Value Added Tax Act, 2025 (Act 1151)."""

import datetime
from decimal import Decimal

from django.test import TestCase

from apps.ledger.models import ChartOfAccounts
from apps.ledger.services.ledger import LedgerService
from apps.ledger.services.seeder import seed_standard_chart_of_accounts
from apps.tax.services import (
    ACCOUNT_CODE_AP,
    ACCOUNT_CODE_AR,
    ACCOUNT_CODE_GETFUND_INPUT,
    ACCOUNT_CODE_GETFUND_OUTPUT,
    ACCOUNT_CODE_NHIL_INPUT,
    ACCOUNT_CODE_NHIL_OUTPUT,
    ACCOUNT_CODE_REVENUE_STANDARD,
    ACCOUNT_CODE_VAT_INPUT,
    ACCOUNT_CODE_VAT_OUTPUT,
    ACCOUNT_CODE_WHT_PAYABLE,
    LineTaxItem,
    TaxCalculationEngine,
)
from apps.tenancy.models import Organization, TaxSchemeChoices


class TestAct1151TaxEngine(TestCase):
    """Test suite verifying statutory Act 1151 compliance and ledger integration."""

    def setUp(self) -> None:
        self.vat_org = Organization.objects.create(
            name="Accra Tech Solutions Ltd",
            business_tin="C0001234567",
            phone="+233240000001",
            email="finance@accratech.com",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.non_vat_org = Organization.objects.create(
            name="Kofi Enterprise",
            business_tin="P0009876543",
            phone="+233240000002",
            email="kofi@shop.gh",
            vat_registered=False,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )

    def test_standard_tax_calculation_benchmark(self) -> None:
        """Benchmark: GHS 1,000 base yields 150 VAT, 25 NHIL, 25 GETFund, GHS 1,200 Gross."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.vat_org,
        )

        self.assertEqual(breakdown.taxable_amount, Decimal("1000.0000"))
        self.assertEqual(breakdown.vat_amount, Decimal("150.0000"))  # 15.0%
        self.assertEqual(breakdown.nhil_amount, Decimal("25.0000"))  # 2.5%
        self.assertEqual(breakdown.getfund_amount, Decimal("25.0000"))  # 2.5%
        self.assertEqual(breakdown.total_tax, Decimal("200.0000"))  # 20.0% flat
        self.assertEqual(breakdown.gross_amount, Decimal("1200.0000"))
        self.assertEqual(breakdown.effective_rate, Decimal("0.2000"))
        self.assertTrue(breakdown.is_taxable)

    def test_non_cascading_math_defense(self) -> None:
        """Verifies that the old pre-2026 cascading tax formula is NOT applied.

        Under the old cascading system:
            Base = 1000
            NHIL = 25
            GETFund = 25
            VAT Base = 1000 + 25 + 25 = 1050
            VAT (15%) = 157.50 (Cascading!)
        Under Act 1151:
            VAT Base = 1000
            VAT (15%) = 150.00 (Strictly Flat Non-Cascading!)
        """
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.vat_org,
        )

        # Assert VAT is exactly 150.00 and not 157.50
        self.assertNotEqual(breakdown.vat_amount, Decimal("157.5000"))
        self.assertEqual(breakdown.vat_amount, Decimal("150.0000"))
        self.assertEqual(breakdown.total_tax, Decimal("200.0000"))

    def test_covid_levy_permanently_abolished(self) -> None:
        """Verifies that the COVID-19 Health Recovery Levy evaluates strictly to 0.0000."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("5000.0000"),
            organization=self.vat_org,
        )

        self.assertEqual(breakdown.covid_amount, Decimal("0.0000"))
        # Total tax should be exactly VAT + NHIL + GETFund without any COVID levy
        self.assertEqual(
            breakdown.total_tax,
            breakdown.vat_amount + breakdown.nhil_amount + breakdown.getfund_amount,
        )

    def test_non_vat_registered_organization_zero_tax(self) -> None:
        """Non-registered merchants (turnover < GHS 750,000) cannot charge statutory taxes."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.non_vat_org,
        )

        self.assertEqual(breakdown.taxable_amount, Decimal("1000.0000"))
        self.assertEqual(breakdown.vat_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.nhil_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.getfund_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.total_tax, Decimal("0.0000"))
        self.assertEqual(breakdown.gross_amount, Decimal("1000.0000"))
        self.assertEqual(breakdown.effective_rate, Decimal("0.0000"))
        self.assertFalse(breakdown.is_taxable)

    def test_exempt_supply_classification(self) -> None:
        """Exempt supplies under the First Schedule of Act 1151 yield zero taxes."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("2500.0000"),
            supply_type=TaxSchemeChoices.EXEMPT,
            organization=self.vat_org,
        )

        self.assertEqual(breakdown.vat_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.nhil_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.getfund_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.total_tax, Decimal("0.0000"))
        self.assertEqual(breakdown.gross_amount, Decimal("2500.0000"))
        self.assertEqual(breakdown.supply_type, TaxSchemeChoices.EXEMPT)
        self.assertFalse(breakdown.is_taxable)

    def test_zero_rated_export_supply_classification(self) -> None:
        """Zero-rated export supplies yield zero tax while remaining taxable at 0%."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("10000.0000"),
            supply_type=TaxSchemeChoices.ZERO_RATED,
            organization=self.vat_org,
        )

        self.assertEqual(breakdown.vat_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.nhil_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.getfund_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.total_tax, Decimal("0.0000"))
        self.assertEqual(breakdown.gross_amount, Decimal("10000.0000"))
        self.assertEqual(breakdown.supply_type, TaxSchemeChoices.ZERO_RATED)
        self.assertTrue(breakdown.is_taxable)  # Legally distinct from exempt: input credits allowed

    def test_tax_inclusive_pricing_retail_kofi(self) -> None:
        """Retail pricing (tax-inclusive): Gross GHS 1,200.00 extracts base GHS 1,000.00."""
        breakdown = TaxCalculationEngine.calculate_inclusive(
            gross_amount=Decimal("1200.0000"),
            organization=self.vat_org,
        )

        self.assertEqual(breakdown.taxable_amount, Decimal("1000.0000"))
        self.assertEqual(breakdown.vat_amount, Decimal("150.0000"))
        self.assertEqual(breakdown.nhil_amount, Decimal("25.0000"))
        self.assertEqual(breakdown.getfund_amount, Decimal("25.0000"))
        self.assertEqual(breakdown.total_tax, Decimal("200.0000"))
        self.assertEqual(breakdown.gross_amount, Decimal("1200.0000"))

    def test_linear_cumulative_multi_line_rounding_balance(self) -> None:
        """Verifies the Linear Cumulative Method eliminates the 1-pesewa multi-line discrepancy.

        3 items of GHS 10.05 each:
        Subtotal = 30.15
        Expected total VAT on 30.15 @ 15% = 4.52 (not 4.53)
        Sum of lines must equal invoice totals exactly!
        """
        lines = [
            LineTaxItem(description="Item 1", quantity=Decimal("1"), unit_price=Decimal("10.05")),
            LineTaxItem(description="Item 2", quantity=Decimal("1"), unit_price=Decimal("10.05")),
            LineTaxItem(description="Item 3", quantity=Decimal("1"), unit_price=Decimal("10.05")),
        ]

        summary = TaxCalculationEngine.calculate_line_taxes(
            lines=lines,
            organization=self.vat_org,
        )

        self.assertEqual(summary.total_subtotal, Decimal("30.15"))
        # 30.15 * 0.15 = 4.5225 -> 4.52
        self.assertEqual(summary.total_vat, Decimal("4.52"))
        # 30.15 * 0.025 = 0.75375 -> 0.75
        self.assertEqual(summary.total_nhil, Decimal("0.75"))
        # 30.15 * 0.025 = 0.75375 -> 0.75
        self.assertEqual(summary.total_getfund, Decimal("0.75"))

        # Verify line sums match summary totals exactly
        sum_line_vat = sum(line.vat_amount for line in summary.line_breakdowns)
        sum_line_nhil = sum(line.nhil_amount for line in summary.line_breakdowns)
        sum_line_getfund = sum(line.getfund_amount for line in summary.line_breakdowns)
        sum_line_subtotal = sum(line.taxable_amount for line in summary.line_breakdowns)
        sum_line_gross = sum(line.gross_amount for line in summary.line_breakdowns)

        self.assertEqual(sum_line_vat, summary.total_vat)
        self.assertEqual(sum_line_nhil, summary.total_nhil)
        self.assertEqual(sum_line_getfund, summary.total_getfund)
        self.assertEqual(sum_line_subtotal, summary.total_subtotal)
        self.assertEqual(sum_line_gross, summary.total_gross)
        self.assertEqual(
            summary.total_gross,
            summary.total_subtotal + summary.total_vat + summary.total_nhil + summary.total_getfund,
        )

    def test_input_tax_deductibility(self) -> None:
        """Act 1151 restored input tax credits for NHIL (2.5%) and GETFund (2.5%) with VAT (15%)."""
        input_tax = TaxCalculationEngine.calculate_input_tax(
            amount=Decimal("1000.0000"),
            organization=self.vat_org,
        )

        self.assertEqual(input_tax.vat_amount, Decimal("150.0000"))
        self.assertEqual(input_tax.nhil_amount, Decimal("25.0000"))
        self.assertEqual(input_tax.getfund_amount, Decimal("25.0000"))
        self.assertEqual(input_tax.total_tax, Decimal("200.0000"))

    def test_withholding_tax_schedules(self) -> None:
        """Verifies statutory Ghanaian Withholding Tax (WHT) rates across all categories."""
        # 1. Supply of Goods: 3.0%
        wht_goods = TaxCalculationEngine.calculate_withholding_tax(
            gross_amount=Decimal("1000.00"), wht_type="GOODS"
        )
        self.assertEqual(wht_goods.wht_rate, Decimal("0.0300"))
        self.assertEqual(wht_goods.wht_amount, Decimal("30.00"))
        self.assertEqual(wht_goods.net_payable, Decimal("970.00"))

        # 2. Services (Resident): 5.0%
        wht_srv_res = TaxCalculationEngine.calculate_withholding_tax(
            gross_amount=Decimal("1000.00"), wht_type="SERVICES_RESIDENT"
        )
        self.assertEqual(wht_srv_res.wht_rate, Decimal("0.0500"))
        self.assertEqual(wht_srv_res.wht_amount, Decimal("50.00"))
        self.assertEqual(wht_srv_res.net_payable, Decimal("950.00"))

        # 3. Services (Non-Resident): 20.0%
        wht_srv_nonres = TaxCalculationEngine.calculate_withholding_tax(
            gross_amount=Decimal("1000.00"), wht_type="SERVICES_NON_RESIDENT"
        )
        self.assertEqual(wht_srv_nonres.wht_rate, Decimal("0.2000"))
        self.assertEqual(wht_srv_nonres.wht_amount, Decimal("200.00"))
        self.assertEqual(wht_srv_nonres.net_payable, Decimal("800.00"))

        # 4. Rent (Residential): 8.0%
        wht_rent_res = TaxCalculationEngine.calculate_withholding_tax(
            gross_amount=Decimal("1000.00"), wht_type="RENT_RESIDENTIAL"
        )
        self.assertEqual(wht_rent_res.wht_rate, Decimal("0.0800"))
        self.assertEqual(wht_rent_res.wht_amount, Decimal("80.00"))
        self.assertEqual(wht_rent_res.net_payable, Decimal("920.00"))

        # 5. Rent (Commercial): 15.0%
        wht_rent_comm = TaxCalculationEngine.calculate_withholding_tax(
            gross_amount=Decimal("1000.00"), wht_type="RENT_COMMERCIAL"
        )
        self.assertEqual(wht_rent_comm.wht_rate, Decimal("0.1500"))
        self.assertEqual(wht_rent_comm.wht_amount, Decimal("150.00"))
        self.assertEqual(wht_rent_comm.net_payable, Decimal("850.00"))

    def test_statutory_vat_threshold_helper(self) -> None:
        """Verifies GHS 750,000 threshold check."""
        self.assertFalse(TaxCalculationEngine.is_threshold_exceeded(Decimal("749999.99")))
        self.assertTrue(TaxCalculationEngine.is_threshold_exceeded(Decimal("750000.00")))
        self.assertTrue(TaxCalculationEngine.is_threshold_exceeded(Decimal("1000000.00")))

    def test_gra_payload_generation(self) -> None:
        """Verifies to_gra_payload() generates the exact schema required for GRA E-VAT clearance."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.vat_org,
        )
        payload = breakdown.to_gra_payload()

        self.assertEqual(payload["taxable_amount"], "1000.00")
        self.assertEqual(payload["vat_rate"], "0.1500")
        self.assertEqual(payload["vat_amount"], "150.00")
        self.assertEqual(payload["nhil_rate"], "0.0250")
        self.assertEqual(payload["nhil_amount"], "25.00")
        self.assertEqual(payload["getfund_rate"], "0.0250")
        self.assertEqual(payload["getfund_amount"], "25.00")
        self.assertEqual(payload["covid_rate"], "0.00")
        self.assertEqual(payload["covid_amount"], "0.00")
        self.assertEqual(payload["total_amount"], "1200.00")
        self.assertEqual(payload["effective_rate"], "0.2000")

    def test_to_invoice_fields(self) -> None:
        """Verifies to_invoice_fields() produces exact keys matching Django Invoice table schema."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.vat_org,
        )
        fields = breakdown.to_invoice_fields()

        self.assertEqual(fields["subtotal_amount"], Decimal("1000.00"))
        self.assertEqual(fields["nhil_amount"], Decimal("25.00"))
        self.assertEqual(fields["getfund_amount"], Decimal("25.00"))
        self.assertEqual(fields["vat_amount"], Decimal("150.00"))
        self.assertEqual(fields["total_amount"], Decimal("1200.00"))


class TestTaxLedgerIntegration(TestCase):
    """Integration test verifying tax lines commit to LedgerService without constraint errors."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(
            name="Accra Ledger Works",
            business_tin="C0009988776",
            phone="+233240000003",
            email="ledger@accraworks.com",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        seed_standard_chart_of_accounts(self.org)

        self.ar_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_AR
        )
        self.rev_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_REVENUE_STANDARD
        )
        self.vat_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_VAT_OUTPUT
        )
        self.nhil_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_NHIL_OUTPUT
        )
        self.getfund_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_GETFUND_OUTPUT
        )

        self.ap_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_AP
        )
        self.vat_input = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_VAT_INPUT
        )
        self.nhil_input = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_NHIL_INPUT
        )
        self.getfund_input = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_GETFUND_INPUT
        )
        self.wht_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code=ACCOUNT_CODE_WHT_PAYABLE
        )
        self.expense_account = ChartOfAccounts.objects.get(
            organization=self.org, account_code="5010"
        )  # COGS

    def test_standard_invoice_ledger_posting(self) -> None:
        """Standard tax invoice generates 5 balanced lines and posts to General Ledger."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.org,
        )
        lines_data = TaxCalculationEngine.get_invoice_ledger_lines(
            tax_breakdown=breakdown,
            ar_account=self.ar_account,
            revenue_account=self.rev_account,
            vat_account=self.vat_account,
            nhil_account=self.nhil_account,
            getfund_account=self.getfund_account,
            narration="INV-2026-0001 Standard Supply",
        )

        self.assertEqual(len(lines_data), 5)
        # Verify debits == credits
        total_debit = sum(line["debit"] for line in lines_data)
        total_credit = sum(line["credit"] for line in lines_data)
        self.assertEqual(total_debit, Decimal("1200.00"))
        self.assertEqual(total_credit, Decimal("1200.00"))

        # Post to actual LedgerService engine!
        entry = LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 3, 15),
            lines_data=lines_data,
            narration="Invoice #INV-2026-0001",
        )
        self.assertIsNotNone(entry.id)
        self.assertTrue(entry.is_posted)
        self.assertEqual(entry.lines.count(), 5)

    def test_exempt_invoice_omits_zero_tax_lines(self) -> None:
        """Exempt invoice omits 0.00 tax lines, preventing JournalLine check constraint crash."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            supply_type=TaxSchemeChoices.EXEMPT,
            organization=self.org,
        )
        lines_data = TaxCalculationEngine.get_invoice_ledger_lines(
            tax_breakdown=breakdown,
            ar_account=self.ar_account,
            revenue_account=self.rev_account,
            vat_account=self.vat_account,
            nhil_account=self.nhil_account,
            getfund_account=self.getfund_account,
        )

        # Tax lines must be omitted: only AR and Revenue lines present
        self.assertEqual(len(lines_data), 2)
        total_debit = sum(line["debit"] for line in lines_data)
        total_credit = sum(line["credit"] for line in lines_data)
        self.assertEqual(total_debit, Decimal("1000.00"))
        self.assertEqual(total_credit, Decimal("1000.00"))

        # Posting must succeed without database check constraint failure
        entry = LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 3, 15),
            lines_data=lines_data,
            narration="Invoice #INV-2026-0002 Exempt",
        )
        self.assertEqual(entry.lines.count(), 2)

    def test_vendor_bill_with_input_tax_and_wht_ledger_posting(self) -> None:
        """Vendor bill with input tax deductions and WHT posts balanced entry to General Ledger."""
        input_tax = TaxCalculationEngine.calculate_input_tax(
            amount=Decimal("1000.0000"),
            organization=self.org,
        )
        wht = TaxCalculationEngine.calculate_withholding_tax(
            gross_amount=Decimal("1000.00"),
            wht_type="GOODS",  # 3% WHT
        )

        lines_data = TaxCalculationEngine.get_bill_ledger_lines(
            tax_breakdown=input_tax,
            ap_account=self.ap_account,
            expense_account=self.expense_account,
            vat_input_account=self.vat_input,
            nhil_input_account=self.nhil_input,
            getfund_input_account=self.getfund_input,
            wht_breakdown=wht,
            wht_account=self.wht_account,
            narration="BILL-2026-0042 Stock Purchase",
        )

        total_debit = sum(line["debit"] for line in lines_data)
        total_credit = sum(line["credit"] for line in lines_data)
        self.assertEqual(total_debit, total_credit)

        entry = LedgerService.post_journal_entry(
            organization=self.org,
            entry_date=datetime.date(2026, 3, 15),
            lines_data=lines_data,
            narration="Bill #BILL-2026-0042",
        )
        self.assertIsNotNone(entry.id)
        self.assertTrue(entry.is_posted)
