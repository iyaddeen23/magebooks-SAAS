"""Ghanaian Statutory Tax Engine under Value Added Tax Act, 2025 (Act 1151).

Effective January 1, 2026:
1. Unified 20.0% Non-Cascading Rate: 15.0% Standard VAT + 2.5% NHIL + 2.5% GETFund flat on base.
2. Input Tax Deductibility: NHIL and GETFund are fully deductible input tax credits alongside VAT.
3. COVID-19 Health Recovery Levy (1.0%) permanently abolished.
4. VAT Flat Rate Scheme (VFRS) permanently abolished.
5. Statutory Turnover Registration Threshold: GHS 750,000.
6. Multi-Line Linear Cumulative Rounding: Guarantees zero 1-pesewa discrepancies across lines.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import ValidationError

from apps.tenancy.models import Organization, TaxSchemeChoices

# ============================================================================
# STATUTORY CONSTANTS (ACT 1151 — EFFECTIVE JANUARY 1, 2026)
# ============================================================================
ACT_1151_STATUTORY_YEAR: int = 2026
STATUTORY_VAT_RATE: Decimal = Decimal("0.1500")  # 15.0% Standard VAT
STATUTORY_NHIL_RATE: Decimal = Decimal("0.0250")  # 2.5% NHIL (Input-Deductible)
STATUTORY_GETFUND_RATE: Decimal = Decimal("0.0250")  # 2.5% GETFund (Input-Deductible)
STATUTORY_UNIFIED_RATE: Decimal = Decimal("0.2000")  # 20.0% Unified Non-Cascading Flat Rate
STATUTORY_VAT_THRESHOLD: Decimal = Decimal("750000.0000")  # GHS 750,000 Mandatory Turnover

# Withholding Tax (WHT) Rates (Standard Ghanaian Statutory Rates)
WHT_GOODS_RATE: Decimal = Decimal("0.0300")  # 3.0% on Goods
WHT_SERVICES_RESIDENT_RATE: Decimal = Decimal("0.0500")  # 5.0% on Services (Resident)
WHT_SERVICES_NON_RESIDENT_RATE: Decimal = Decimal("0.2000")  # 20.0% on Services (Non-Resident)
WHT_RENT_RESIDENTIAL_RATE: Decimal = Decimal("0.0800")  # 8.0% Residential Rent
WHT_RENT_COMMERCIAL_RATE: Decimal = Decimal("0.1500")  # 15.0% Commercial Rent

# Standard Chart of Accounts 4-Digit Hierarchy Code Mappings
ACCOUNT_CODE_AR: str = "1200"  # Accounts Receivable
ACCOUNT_CODE_AP: str = "2010"  # Accounts Payable
ACCOUNT_CODE_REVENUE_STANDARD: str = "4000"  # Sales Revenue - Standard Supplies
ACCOUNT_CODE_REVENUE_EXEMPT: str = "4020"  # Sales Revenue - Exempt Supplies
ACCOUNT_CODE_REVENUE_ZERO_RATED: str = "4030"  # Sales Revenue - Zero Rated Exports
ACCOUNT_CODE_VAT_OUTPUT: str = "2100"  # GRA Standard VAT Output (15.0%)
ACCOUNT_CODE_NHIL_OUTPUT: str = "2110"  # GRA NHIL Output (2.5%)
ACCOUNT_CODE_GETFUND_OUTPUT: str = "2120"  # GRA GETFund Output (2.5%)
ACCOUNT_CODE_VAT_INPUT: str = "2130"  # GRA Standard VAT Input (15.0%)
ACCOUNT_CODE_NHIL_INPUT: str = "2140"  # GRA NHIL Input (2.5%)
ACCOUNT_CODE_GETFUND_INPUT: str = "2145"  # GRA GETFund Input (2.5%)
ACCOUNT_CODE_WHT_PAYABLE: str = "2200"  # PAYE / Withholding Tax Payable

# Decimal Quantization Precision Constants
PRECISION_INTERNAL = Decimal("0.0001")
PRECISION_CURRENCY = Decimal("0.01")


# ============================================================================
# DOMAIN DATA STRUCTURES & DTOS
# ============================================================================
@dataclass(frozen=True)
class TaxBreakdown:
    """Immutable point-in-time calculation output under Act 1151."""

    taxable_amount: Decimal
    vat_amount: Decimal
    nhil_amount: Decimal
    getfund_amount: Decimal
    total_tax: Decimal
    gross_amount: Decimal
    effective_rate: Decimal
    supply_type: str = TaxSchemeChoices.STANDARD
    is_taxable: bool = True

    @property
    def covid_amount(self) -> Decimal:
        """Abolished under Act 1151; strictly returns Decimal('0.0000')."""
        return Decimal("0.0000")

    def round_to_currency(self, precision: Decimal = PRECISION_CURRENCY) -> "TaxBreakdown":
        """Returns a currency-rounded snapshot (2 decimal places, ROUND_HALF_UP)."""
        rounded_vat = self.vat_amount.quantize(precision, rounding=ROUND_HALF_UP)
        rounded_nhil = self.nhil_amount.quantize(precision, rounding=ROUND_HALF_UP)
        rounded_getfund = self.getfund_amount.quantize(precision, rounding=ROUND_HALF_UP)
        rounded_taxable = self.taxable_amount.quantize(precision, rounding=ROUND_HALF_UP)
        rounded_total_tax = rounded_vat + rounded_nhil + rounded_getfund
        rounded_gross = rounded_taxable + rounded_total_tax

        return TaxBreakdown(
            taxable_amount=rounded_taxable,
            vat_amount=rounded_vat,
            nhil_amount=rounded_nhil,
            getfund_amount=rounded_getfund,
            total_tax=rounded_total_tax,
            gross_amount=rounded_gross,
            effective_rate=self.effective_rate,
            supply_type=self.supply_type,
            is_taxable=self.is_taxable,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializes breakdown values to strings with 4 decimal places."""
        return {
            "taxable_amount": str(self.taxable_amount),
            "vat_amount": str(self.vat_amount),
            "nhil_amount": str(self.nhil_amount),
            "getfund_amount": str(self.getfund_amount),
            "total_tax": str(self.total_tax),
            "gross_amount": str(self.gross_amount),
            "effective_rate": str(self.effective_rate),
            "supply_type": self.supply_type,
            "is_taxable": self.is_taxable,
        }

    def to_gra_payload(self) -> dict[str, Any]:
        """Formats the payload structure required by the GRA E-VAT clearance gateway.

        Injects covid_amount: '0.00' strictly at the serialization edge if legacy
        GRA clearance endpoints require the key for backwards-compatible validation.
        """
        curr = self.round_to_currency()
        return {
            "taxable_amount": str(curr.taxable_amount),
            "vat_rate": str(STATUTORY_VAT_RATE),
            "vat_amount": str(curr.vat_amount),
            "nhil_rate": str(STATUTORY_NHIL_RATE),
            "nhil_amount": str(curr.nhil_amount),
            "getfund_rate": str(STATUTORY_GETFUND_RATE),
            "getfund_amount": str(curr.getfund_amount),
            "covid_rate": "0.00",
            "covid_amount": "0.00",
            "total_amount": str(curr.gross_amount),
            "effective_rate": str(curr.effective_rate),
        }

    def to_invoice_fields(self) -> dict[str, Decimal]:
        """Returns dictionary mapping directly to Django Invoice model fields."""
        curr = self.round_to_currency()
        return {
            "subtotal_amount": curr.taxable_amount,
            "nhil_amount": curr.nhil_amount,
            "getfund_amount": curr.getfund_amount,
            "vat_amount": curr.vat_amount,
            "total_amount": curr.gross_amount,
        }


@dataclass(frozen=True)
class LineTaxItem:
    """Represents a discrete line item input for multi-line invoice tax calculations."""

    description: str
    quantity: Decimal
    unit_price: Decimal
    supply_type: str = TaxSchemeChoices.STANDARD
    is_taxable: bool = True
    line_id: str | None = None

    @property
    def line_subtotal(self) -> Decimal:
        """Computes line subtotal as quantity * unit_price."""
        return (self.quantity * self.unit_price).quantize(
            PRECISION_INTERNAL, rounding=ROUND_HALF_UP
        )


@dataclass(frozen=True)
class InvoiceTaxSummary:
    """Multi-line aggregated tax breakdown with discrepancy-free pesewa balancing."""

    line_breakdowns: list[TaxBreakdown]
    total_subtotal: Decimal
    total_vat: Decimal
    total_nhil: Decimal
    total_getfund: Decimal
    total_tax: Decimal
    total_gross: Decimal

    def to_invoice_fields(self) -> dict[str, Decimal]:
        """Returns fields matching the Invoices table schema."""
        return {
            "subtotal_amount": self.total_subtotal,
            "nhil_amount": self.total_nhil,
            "getfund_amount": self.total_getfund,
            "vat_amount": self.total_vat,
            "total_amount": self.total_gross,
        }


@dataclass(frozen=True)
class WithholdingTaxBreakdown:
    """Ghanaian statutory Withholding Tax calculation result."""

    gross_amount: Decimal
    wht_type: str
    wht_rate: Decimal
    wht_amount: Decimal
    net_payable: Decimal


# ============================================================================
# STATUTORY TAX CALCULATION ENGINE
# ============================================================================
class TaxCalculationEngine:
    """2026 Ghanaian Statutory Tax Calculation Core Engine (Act 1151)."""

    @classmethod
    def _coerce_decimal(cls, value: Any, field_name: str = "amount") -> Decimal:
        """Coerces input value to Decimal, rejecting binary float to prevent precision drift."""
        if isinstance(value, float):
            raise TypeError(
                f"Floating-point values are prohibited in tax calculations ({field_name}={value}). "
                "Use Decimal, str, or int to prevent IEEE-754 precision drift."
            )
        try:
            dec = Decimal(str(value)) if not isinstance(value, Decimal) else value
        except Exception as e:
            raise ValidationError({field_name: f"Invalid numeric amount '{value}': {e}"}) from e

        if dec < Decimal("0.0000"):
            raise ValidationError({field_name: "Financial tax amounts cannot be negative."})

        return dec.quantize(PRECISION_INTERNAL, rounding=ROUND_HALF_UP)

    @classmethod
    def is_threshold_exceeded(cls, annual_turnover: Decimal | str | int) -> bool:
        """Evaluates whether annual taxable turnover reaches the Act 1151 GHS 750,000 threshold."""
        turnover = cls._coerce_decimal(annual_turnover, "annual_turnover")
        return turnover >= STATUTORY_VAT_THRESHOLD

    @classmethod
    def calculate_exclusive(
        cls,
        amount: Decimal | str | int,
        supply_type: str = TaxSchemeChoices.STANDARD,
        organization: Organization | None = None,
        is_vat_registered: bool | None = None,
    ) -> TaxBreakdown:
        """Calculates Act 1151 statutory taxes added onto a net (tax-exclusive) base amount.

        Formula:
            NHIL = Base * 0.025
            GETFund = Base * 0.025
            Standard VAT = Base * 0.150
            Total Tax = NHIL + GETFund + Standard VAT (20.0% non-cascading flat)
            Gross Total = Base + Total Tax
        """
        base = cls._coerce_decimal(amount, "amount")

        # 1. Evaluate organization VAT registration status
        vat_registered = True
        if is_vat_registered is not None:
            vat_registered = is_vat_registered
        elif organization is not None:
            vat_registered = organization.vat_registered

        # If tenant is not VAT-registered, zero statutory taxes can be charged
        if not vat_registered:
            zero = Decimal("0.0000")
            return TaxBreakdown(
                taxable_amount=base,
                vat_amount=zero,
                nhil_amount=zero,
                getfund_amount=zero,
                total_tax=zero,
                gross_amount=base,
                effective_rate=zero,
                supply_type=supply_type,
                is_taxable=False,
            )

        # 2. Evaluate statutory supply classification
        if supply_type in (TaxSchemeChoices.EXEMPT, TaxSchemeChoices.ZERO_RATED):
            zero = Decimal("0.0000")
            return TaxBreakdown(
                taxable_amount=base,
                vat_amount=zero,
                nhil_amount=zero,
                getfund_amount=zero,
                total_tax=zero,
                gross_amount=base,
                effective_rate=zero,
                supply_type=supply_type,
                is_taxable=(supply_type == TaxSchemeChoices.ZERO_RATED),
            )

        # 3. Standard Act 1151 Unified 20.0% Non-Cascading Calculation
        nhil = (base * STATUTORY_NHIL_RATE).quantize(PRECISION_INTERNAL, rounding=ROUND_HALF_UP)
        getfund = (base * STATUTORY_GETFUND_RATE).quantize(
            PRECISION_INTERNAL, rounding=ROUND_HALF_UP
        )
        vat = (base * STATUTORY_VAT_RATE).quantize(PRECISION_INTERNAL, rounding=ROUND_HALF_UP)
        total_tax = nhil + getfund + vat
        gross = base + total_tax

        return TaxBreakdown(
            taxable_amount=base,
            vat_amount=vat,
            nhil_amount=nhil,
            getfund_amount=getfund,
            total_tax=total_tax,
            gross_amount=gross,
            effective_rate=STATUTORY_UNIFIED_RATE,
            supply_type=TaxSchemeChoices.STANDARD,
            is_taxable=True,
        )

    @classmethod
    def calculate_inclusive(
        cls,
        gross_amount: Decimal | str | int,
        supply_type: str = TaxSchemeChoices.STANDARD,
        organization: Organization | None = None,
        is_vat_registered: bool | None = None,
    ) -> TaxBreakdown:
        """Extracts Act 1151 statutory taxes from a gross (tax-inclusive) price.

        Formula:
            Base = Gross / (1 + 0.2000) = Gross / 1.2000
            NHIL = Base * 0.025
            GETFund = Base * 0.025
            Standard VAT = Base * 0.150
            Total Tax = Gross - Base
        """
        gross = cls._coerce_decimal(gross_amount, "gross_amount")

        vat_registered = True
        if is_vat_registered is not None:
            vat_registered = is_vat_registered
        elif organization is not None:
            vat_registered = organization.vat_registered

        if not vat_registered or supply_type in (
            TaxSchemeChoices.EXEMPT,
            TaxSchemeChoices.ZERO_RATED,
        ):
            zero = Decimal("0.0000")
            return TaxBreakdown(
                taxable_amount=gross,
                vat_amount=zero,
                nhil_amount=zero,
                getfund_amount=zero,
                total_tax=zero,
                gross_amount=gross,
                effective_rate=zero,
                supply_type=supply_type,
                is_taxable=(
                    vat_registered and supply_type != TaxSchemeChoices.EXEMPT
                    if supply_type
                    else False
                ),
            )

        # Base = Gross / (1 + 0.20)
        divisor = Decimal("1.0000") + STATUTORY_UNIFIED_RATE
        base = (gross / divisor).quantize(PRECISION_INTERNAL, rounding=ROUND_HALF_UP)
        nhil = (base * STATUTORY_NHIL_RATE).quantize(PRECISION_INTERNAL, rounding=ROUND_HALF_UP)
        getfund = (base * STATUTORY_GETFUND_RATE).quantize(
            PRECISION_INTERNAL, rounding=ROUND_HALF_UP
        )
        vat = (base * STATUTORY_VAT_RATE).quantize(PRECISION_INTERNAL, rounding=ROUND_HALF_UP)
        total_tax = gross - base

        return TaxBreakdown(
            taxable_amount=base,
            vat_amount=vat,
            nhil_amount=nhil,
            getfund_amount=getfund,
            total_tax=total_tax,
            gross_amount=gross,
            effective_rate=STATUTORY_UNIFIED_RATE,
            supply_type=TaxSchemeChoices.STANDARD,
            is_taxable=True,
        )

    @classmethod
    def calculate_line_taxes(
        cls,
        lines: list[LineTaxItem | dict[str, Any]],
        organization: Organization | None = None,
        is_vat_registered: bool | None = None,
    ) -> InvoiceTaxSummary:
        """Calculates multi-line invoice taxes using the Linear Cumulative Rounding Method.

        Linear Cumulative Method Invariant:
            Line Tax[i] = Round(Sum(Base[1..i]) * Rate) - Sum(Line Tax[1..i-1])

        Guarantees:
            1. sum(line.subtotal) == invoice.subtotal
            2. sum(line.vat) == invoice.vat
            3. sum(line.nhil) == invoice.nhil
            4. sum(line.getfund) == invoice.getfund
            5. invoice.total == invoice.subtotal + invoice.vat + invoice.nhil + invoice.getfund
            6. Zero 1-pesewa rounding mismatch between line items and header ledger debits.
        """
        vat_registered = True
        if is_vat_registered is not None:
            vat_registered = is_vat_registered
        elif organization is not None:
            vat_registered = organization.vat_registered

        coerced_lines: list[LineTaxItem] = []
        for line in lines:
            if isinstance(line, LineTaxItem):
                coerced_lines.append(line)
            elif isinstance(line, dict):
                qty = cls._coerce_decimal(line.get("quantity", 1), "quantity")
                price = cls._coerce_decimal(line.get("unit_price", 0), "unit_price")
                coerced_lines.append(
                    LineTaxItem(
                        description=str(line.get("description", "")),
                        quantity=qty,
                        unit_price=price,
                        supply_type=line.get("supply_type", TaxSchemeChoices.STANDARD),
                        is_taxable=bool(line.get("is_taxable", True)),
                        line_id=str(line.get("line_id")) if line.get("line_id") else None,
                    )
                )
            else:
                raise ValidationError(f"Invalid line item specification: {line}")

        line_breakdowns: list[TaxBreakdown] = []

        cumulative_taxable_base = Decimal("0.0000")
        cumulative_vat_cents = Decimal("0.00")
        cumulative_nhil_cents = Decimal("0.00")
        cumulative_getfund_cents = Decimal("0.00")

        total_subtotal_cents = Decimal("0.00")
        total_vat_cents = Decimal("0.00")
        total_nhil_cents = Decimal("0.00")
        total_getfund_cents = Decimal("0.00")

        for line_item in coerced_lines:
            line_subtotal_raw = line_item.line_subtotal
            line_subtotal_cents = line_subtotal_raw.quantize(
                PRECISION_CURRENCY, rounding=ROUND_HALF_UP
            )
            total_subtotal_cents += line_subtotal_cents

            # Check if this line attracts standard statutory VAT
            is_standard = (
                vat_registered
                and line_item.is_taxable
                and line_item.supply_type == TaxSchemeChoices.STANDARD
            )

            if not is_standard:
                zero = Decimal("0.00")
                bd = TaxBreakdown(
                    taxable_amount=line_subtotal_cents,
                    vat_amount=zero,
                    nhil_amount=zero,
                    getfund_amount=zero,
                    total_tax=zero,
                    gross_amount=line_subtotal_cents,
                    effective_rate=Decimal("0.0000"),
                    supply_type=line_item.supply_type,
                    is_taxable=line_item.is_taxable if vat_registered else False,
                )
                line_breakdowns.append(bd)
            else:
                # Linear Cumulative Method execution
                cumulative_taxable_base += line_subtotal_cents

                target_cumulative_vat = (cumulative_taxable_base * STATUTORY_VAT_RATE).quantize(
                    PRECISION_CURRENCY, rounding=ROUND_HALF_UP
                )
                line_vat = target_cumulative_vat - cumulative_vat_cents
                cumulative_vat_cents = target_cumulative_vat

                target_cumulative_nhil = (cumulative_taxable_base * STATUTORY_NHIL_RATE).quantize(
                    PRECISION_CURRENCY, rounding=ROUND_HALF_UP
                )
                line_nhil = target_cumulative_nhil - cumulative_nhil_cents
                cumulative_nhil_cents = target_cumulative_nhil

                target_cumulative_getfund = (
                    cumulative_taxable_base * STATUTORY_GETFUND_RATE
                ).quantize(PRECISION_CURRENCY, rounding=ROUND_HALF_UP)
                line_getfund = target_cumulative_getfund - cumulative_getfund_cents
                cumulative_getfund_cents = target_cumulative_getfund

                line_tax = line_vat + line_nhil + line_getfund
                line_gross = line_subtotal_cents + line_tax

                total_vat_cents += line_vat
                total_nhil_cents += line_nhil
                total_getfund_cents += line_getfund

                bd = TaxBreakdown(
                    taxable_amount=line_subtotal_cents,
                    vat_amount=line_vat,
                    nhil_amount=line_nhil,
                    getfund_amount=line_getfund,
                    total_tax=line_tax,
                    gross_amount=line_gross,
                    effective_rate=STATUTORY_UNIFIED_RATE,
                    supply_type=TaxSchemeChoices.STANDARD,
                    is_taxable=True,
                )
                line_breakdowns.append(bd)

        total_tax_cents = total_vat_cents + total_nhil_cents + total_getfund_cents
        total_gross_cents = total_subtotal_cents + total_tax_cents

        return InvoiceTaxSummary(
            line_breakdowns=line_breakdowns,
            total_subtotal=total_subtotal_cents,
            total_vat=total_vat_cents,
            total_nhil=total_nhil_cents,
            total_getfund=total_getfund_cents,
            total_tax=total_tax_cents,
            total_gross=total_gross_cents,
        )

    @classmethod
    def calculate_input_tax(
        cls,
        amount: Decimal | str | int,
        supply_type: str = TaxSchemeChoices.STANDARD,
        organization: Organization | None = None,
    ) -> TaxBreakdown:
        """Calculates input tax credits claimable on business purchases under Act 1151.

        Under Act 1151, NHIL (2.5%) and GETFund (2.5%) are fully deductible alongside
        Standard VAT (15.0%).
        """
        return cls.calculate_exclusive(
            amount=amount,
            supply_type=supply_type,
            organization=organization,
        )

    @classmethod
    def calculate_withholding_tax(
        cls,
        gross_amount: Decimal | str | int,
        wht_type: str = "GOODS",
    ) -> WithholdingTaxBreakdown:
        """Calculates statutory Ghanaian Withholding Tax (WHT) on vendor disbursements."""
        gross = cls._coerce_decimal(gross_amount, "gross_amount")

        rates_map = {
            "GOODS": WHT_GOODS_RATE,  # 3.0%
            "SERVICES_RESIDENT": WHT_SERVICES_RESIDENT_RATE,  # 5.0%
            "SERVICES_NON_RESIDENT": WHT_SERVICES_NON_RESIDENT_RATE,  # 20.0%
            "RENT_RESIDENTIAL": WHT_RENT_RESIDENTIAL_RATE,  # 8.0%
            "RENT_COMMERCIAL": WHT_RENT_COMMERCIAL_RATE,  # 15.0%
        }

        if wht_type not in rates_map:
            valid_types = list(rates_map.keys())
            raise ValidationError(
                {"wht_type": f"Invalid WHT type '{wht_type}'. Valid types: {valid_types}"}
            )

        rate = rates_map[wht_type]
        wht_amount = (gross * rate).quantize(PRECISION_CURRENCY, rounding=ROUND_HALF_UP)
        net_payable = gross - wht_amount

        return WithholdingTaxBreakdown(
            gross_amount=gross.quantize(PRECISION_CURRENCY, rounding=ROUND_HALF_UP),
            wht_type=wht_type,
            wht_rate=rate,
            wht_amount=wht_amount,
            net_payable=net_payable,
        )

    @classmethod
    def get_invoice_ledger_lines(
        cls,
        tax_breakdown: TaxBreakdown,
        ar_account: Any,
        revenue_account: Any,
        vat_account: Any = None,
        nhil_account: Any = None,
        getfund_account: Any = None,
        narration: str = "",
    ) -> list[dict[str, Any]]:
        """Constructs balanced double-entry lines for LedgerService.post_journal_entry.

        Database Check Constraint Defense:
            apps.ledger.models.JournalLine has check_either_debit_or_credit:
            ((debit > 0 and credit == 0) or (credit > 0 and debit == 0)).
            If an amount is Decimal('0.0000') (e.g. exempt, zero-rated, non-registered),
            that tax line is STRICTLY OMITTED to prevent violating database constraints.
        """
        curr = tax_breakdown.round_to_currency()
        zero = Decimal("0.0000")

        lines: list[dict[str, Any]] = [
            # Debit: Accounts Receivable (Gross Total)
            {
                "account": ar_account,
                "debit_amount": curr.gross_amount,
                "credit_amount": zero,
                "debit": curr.gross_amount,
                "credit": zero,
                "description": narration or "Accounts Receivable - Invoice Gross Total",
                "narration": narration or "Accounts Receivable - Invoice Gross Total",
            },
            # Credit: Sales Revenue (Base Subtotal)
            {
                "account": revenue_account,
                "debit_amount": zero,
                "credit_amount": curr.taxable_amount,
                "debit": zero,
                "credit": curr.taxable_amount,
                "description": narration or "Sales Revenue - Base Subtotal",
                "narration": narration or "Sales Revenue - Base Subtotal",
            },
        ]

        # Only append statutory tax credit lines if their amount is strictly > 0
        if curr.vat_amount > zero and vat_account is not None:
            lines.append(
                {
                    "account": vat_account,
                    "debit_amount": zero,
                    "credit_amount": curr.vat_amount,
                    "debit": zero,
                    "credit": curr.vat_amount,
                    "description": narration or "GRA Standard VAT Output (15.0%)",
                    "narration": narration or "GRA Standard VAT Output (15.0%)",
                }
            )

        if curr.nhil_amount > zero and nhil_account is not None:
            lines.append(
                {
                    "account": nhil_account,
                    "debit_amount": zero,
                    "credit_amount": curr.nhil_amount,
                    "debit": zero,
                    "credit": curr.nhil_amount,
                    "description": narration or "GRA NHIL Output (2.5%)",
                    "narration": narration or "GRA NHIL Output (2.5%)",
                }
            )

        if curr.getfund_amount > zero and getfund_account is not None:
            lines.append(
                {
                    "account": getfund_account,
                    "debit_amount": zero,
                    "credit_amount": curr.getfund_amount,
                    "debit": zero,
                    "credit": curr.getfund_amount,
                    "description": narration or "GRA GETFund Output (2.5%)",
                    "narration": narration or "GRA GETFund Output (2.5%)",
                }
            )

        return lines

    @classmethod
    def get_bill_ledger_lines(
        cls,
        tax_breakdown: TaxBreakdown,
        ap_account: Any,
        expense_account: Any,
        vat_input_account: Any = None,
        nhil_input_account: Any = None,
        getfund_input_account: Any = None,
        wht_breakdown: WithholdingTaxBreakdown | None = None,
        wht_account: Any = None,
        narration: str = "",
    ) -> list[dict[str, Any]]:
        """Constructs balanced double-entry lines for vendor bills with input taxes and WHT."""
        curr = tax_breakdown.round_to_currency()
        zero = Decimal("0.0000")

        lines: list[dict[str, Any]] = [
            # Debit: Expense / Inventory (Base Subtotal)
            {
                "account": expense_account,
                "debit_amount": curr.taxable_amount,
                "credit_amount": zero,
                "debit": curr.taxable_amount,
                "credit": zero,
                "description": narration or "Supplier Purchase / Expense Base",
                "narration": narration or "Supplier Purchase / Expense Base",
            },
        ]

        # Debit: Input Tax Deductible Credits (only if > 0)
        if curr.vat_amount > zero and vat_input_account is not None:
            lines.append(
                {
                    "account": vat_input_account,
                    "debit_amount": curr.vat_amount,
                    "credit_amount": zero,
                    "debit": curr.vat_amount,
                    "credit": zero,
                    "description": narration or "GRA Standard VAT Input Credit (15.0%)",
                    "narration": narration or "GRA Standard VAT Input Credit (15.0%)",
                }
            )

        if curr.nhil_amount > zero and nhil_input_account is not None:
            lines.append(
                {
                    "account": nhil_input_account,
                    "debit_amount": curr.nhil_amount,
                    "credit_amount": zero,
                    "debit": curr.nhil_amount,
                    "credit": zero,
                    "description": narration or "GRA NHIL Input Credit (2.5%)",
                    "narration": narration or "GRA NHIL Input Credit (2.5%)",
                }
            )

        if curr.getfund_amount > zero and getfund_input_account is not None:
            lines.append(
                {
                    "account": getfund_input_account,
                    "debit_amount": curr.getfund_amount,
                    "credit_amount": zero,
                    "debit": curr.getfund_amount,
                    "credit": zero,
                    "description": narration or "GRA GETFund Input Credit (2.5%)",
                    "narration": narration or "GRA GETFund Input Credit (2.5%)",
                }
            )

        # Credits: Accounts Payable & Optional Withholding Tax
        if wht_breakdown and wht_breakdown.wht_amount > zero and wht_account is not None:
            wht_amt = wht_breakdown.wht_amount
            net_ap = curr.gross_amount - wht_amt
            lines.append(
                {
                    "account": ap_account,
                    "debit_amount": zero,
                    "credit_amount": net_ap,
                    "debit": zero,
                    "credit": net_ap,
                    "description": narration or "Accounts Payable (Net of WHT)",
                    "narration": narration or "Accounts Payable (Net of WHT)",
                }
            )
            wht_desc = narration or f"Withholding Tax Payable ({wht_breakdown.wht_type})"
            lines.append(
                {
                    "account": wht_account,
                    "debit_amount": zero,
                    "credit_amount": wht_amt,
                    "debit": zero,
                    "credit": wht_amt,
                    "description": wht_desc,
                    "narration": wht_desc,
                }
            )
        else:
            lines.append(
                {
                    "account": ap_account,
                    "debit_amount": zero,
                    "credit_amount": curr.gross_amount,
                    "debit": zero,
                    "credit": curr.gross_amount,
                    "description": narration or "Accounts Payable - Supplier Gross Total",
                    "narration": narration or "Accounts Payable - Supplier Gross Total",
                }
            )

        return lines
