"""Invoicing Domain Service.

Coordinates:
1. Act 1151 statutory sales tax calculation and multi-line itemization.
2. Point-in-time customer legal identity snapshot freezing.
3. Automatic Luhn payment reference generation.
4. Atomic double-entry General Ledger journal posting (Dr 1200, Cr 4000, Cr 2100/2110/2120).
5. Asynchronous GRA E-VAT clearance task dispatching.
"""

import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.invoicing.dispatchers import enqueue_gra_clearance
from apps.invoicing.models import (
    Contact,
    Invoice,
    InvoiceLine,
    InvoiceStatusChoices,
)
from apps.ledger.models import ChartOfAccounts, SourceTypeChoices
from apps.ledger.services.ledger import LedgerService
from apps.ledger.services.seeder import seed_standard_chart_of_accounts
from apps.tax.services import (
    ACCOUNT_CODE_AR,
    ACCOUNT_CODE_GETFUND_OUTPUT,
    ACCOUNT_CODE_NHIL_OUTPUT,
    ACCOUNT_CODE_REVENUE_STANDARD,
    ACCOUNT_CODE_VAT_OUTPUT,
    STATUTORY_GETFUND_RATE,
    STATUTORY_NHIL_RATE,
    STATUTORY_VAT_RATE,
    LineTaxItem,
    TaxBreakdown,
    TaxCalculationEngine,
)
from apps.tenancy.models import Organization, TaxSchemeChoices

logger = logging.getLogger(__name__)


def ensure_organization_tax_accounts(organization: Organization) -> dict[str, ChartOfAccounts]:
    """Ensures standard Chart of Accounts (1200, 4000, 2100, 2110, 2120) exist for the organization.

    If any are missing, seeds the standard Ghanaian Chart of Accounts idempotently.
    """
    needed_codes = [
        ACCOUNT_CODE_AR,
        ACCOUNT_CODE_REVENUE_STANDARD,
        ACCOUNT_CODE_VAT_OUTPUT,
        ACCOUNT_CODE_NHIL_OUTPUT,
        ACCOUNT_CODE_GETFUND_OUTPUT,
    ]

    accounts = {
        acc.account_code: acc
        for acc in ChartOfAccounts.objects.filter(
            organization=organization,
            account_code__in=needed_codes,
        )
    }

    missing_codes = [code for code in needed_codes if code not in accounts]
    if missing_codes:
        # Auto-seed standard Ghanaian chart of accounts
        seed_standard_chart_of_accounts(organization)
        accounts = {
            acc.account_code: acc
            for acc in ChartOfAccounts.objects.filter(
                organization=organization,
                account_code__in=needed_codes,
            )
        }

    return accounts


class InvoicingService:
    """Core domain service for Invoice creation, tax breakdown, and General Ledger posting."""

    @classmethod
    @transaction.atomic
    def create_and_post_invoice(
        cls,
        organization: Organization,
        user: Any,
        data: dict[str, Any],
    ) -> Invoice:
        """Compiles, calculates, freezes snapshots, and atomically posts an invoice.

        Parameters:
            organization: Authenticated tenant organization.
            user: Initiating user.
            data: Validated dictionary from InvoiceCreateSerializer.

        Returns:
            The created Invoice instance.
        """
        customer_id = data["customer_id"]
        customer = Contact.objects.filter(id=customer_id, organization=organization).first()
        if not customer:
            raise ValidationError(
                {"customer_id": "Customer does not exist or does not belong to this organization."}
            )

        lines_data = data["lines"]
        if not lines_data:
            raise ValidationError({"lines": "At least one invoice line item is required."})

        # 1. Multi-line tax calculation via Act 1151 TaxCalculationEngine
        tax_lines_input: list[LineTaxItem] = []
        for idx, line in enumerate(lines_data):
            qty = Decimal(str(line["quantity"]))
            unit_price = Decimal(str(line["unit_price"]))
            supply_type = line.get("supply_type", TaxSchemeChoices.STANDARD)
            is_taxable = supply_type != TaxSchemeChoices.EXEMPT

            tax_lines_input.append(
                LineTaxItem(
                    description=line["description"],
                    quantity=qty,
                    unit_price=unit_price,
                    supply_type=supply_type,
                    is_taxable=is_taxable,
                    line_id=str(idx),
                )
            )

        tax_summary = TaxCalculationEngine.calculate_line_taxes(
            lines=tax_lines_input,
            organization=organization,
        )

        aggregate_breakdown = TaxBreakdown(
            taxable_amount=tax_summary.total_subtotal,
            vat_amount=tax_summary.total_vat,
            nhil_amount=tax_summary.total_nhil,
            getfund_amount=tax_summary.total_getfund,
            total_tax=tax_summary.total_tax,
            gross_amount=tax_summary.total_gross,
            effective_rate=Decimal("0.2000"),
        )

        # 2. Sequential Invoice Number Generation (INV-YYYY-XXXXX)
        issue_date = data["issue_date"]
        existing_count = Invoice.objects.filter(
            organization=organization,
            issue_date__year=issue_date.year,
        ).count()
        invoice_number = f"INV-{issue_date.year}-{existing_count + 1:05d}"

        # 3. Instantiate Invoice
        action = data.get("action", "issue")
        currency = data.get("currency", "GHS")

        invoice = Invoice(
            organization=organization,
            customer=customer,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=data["due_date"],
            currency=currency,
            subtotal_amount=aggregate_breakdown.taxable_amount,
            vat_amount=aggregate_breakdown.vat_amount,
            nhil_amount=aggregate_breakdown.nhil_amount,
            getfund_amount=aggregate_breakdown.getfund_amount,
            covid_levy_amount=Decimal("0.0000"),
            total_amount=aggregate_breakdown.gross_amount,
            paid_amount=Decimal("0.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        # 4. Freeze customer point-in-time legal snapshot
        invoice.freeze_customer_snapshot(force=True)
        invoice.save()

        # 5. Create InvoiceLine items
        created_lines: list[InvoiceLine] = []
        for idx, line in enumerate(lines_data):
            line_breakdown = tax_summary.line_breakdowns[idx]
            account_id = line.get("account_id")
            line_account = None

            if account_id:
                line_account = ChartOfAccounts.objects.filter(
                    id=account_id, organization=organization
                ).first()
                if not line_account:
                    raise ValidationError(
                        {"account_id": f"Account {account_id} not found in this organization."}
                    )

            inv_line = InvoiceLine(
                organization=organization,
                invoice=invoice,
                description=line["description"],
                quantity=Decimal(str(line["quantity"])),
                unit_price=Decimal(str(line["unit_price"])),
                vat_rate=STATUTORY_VAT_RATE if line_breakdown.vat_amount > 0 else Decimal("0.0000"),
                nhil_rate=(
                    STATUTORY_NHIL_RATE if line_breakdown.nhil_amount > 0 else Decimal("0.0000")
                ),
                getfund_rate=(
                    STATUTORY_GETFUND_RATE
                    if line_breakdown.getfund_amount > 0
                    else Decimal("0.0000")
                ),
                vat_amount=line_breakdown.vat_amount,
                nhil_amount=line_breakdown.nhil_amount,
                getfund_amount=line_breakdown.getfund_amount,
                line_total=line_breakdown.gross_amount,
                account=line_account,
            )
            inv_line.save()
            created_lines.append(inv_line)

        # 6. Post to General Ledger if action is 'issue'
        if action == "issue":
            cls._post_invoice_to_ledger(
                organization=organization,
                invoice=invoice,
                tax_breakdown=aggregate_breakdown,
                user=user,
            )
            invoice.status = InvoiceStatusChoices.PENDING_GRA
            invoice.save(update_fields=["status"])

            # 7. Enqueue asynchronous GRA clearance
            enqueue_gra_clearance(invoice.id)

        return invoice

    @classmethod
    @transaction.atomic
    def issue_draft_invoice(
        cls,
        invoice: Invoice,
        user: Any,
    ) -> Invoice:
        """Transitions a draft invoice to PENDING_GRA and posts to General Ledger."""
        if invoice.status != InvoiceStatusChoices.DRAFT:
            raise ValidationError(
                {"status": f"Only DRAFT invoices can be issued. Current status: {invoice.status}"}
            )

        # Reconstruct TaxBreakdown from stored invoice totals
        from apps.tax.services import TaxBreakdown

        tax_breakdown = TaxBreakdown(
            taxable_amount=invoice.subtotal_amount,
            vat_amount=invoice.vat_amount,
            nhil_amount=invoice.nhil_amount,
            getfund_amount=invoice.getfund_amount,
            total_tax=invoice.vat_amount + invoice.nhil_amount + invoice.getfund_amount,
            gross_amount=invoice.total_amount,
            effective_rate=Decimal("0.2000"),
        )

        cls._post_invoice_to_ledger(
            organization=invoice.organization,
            invoice=invoice,
            tax_breakdown=tax_breakdown,
            user=user,
        )

        invoice.status = InvoiceStatusChoices.PENDING_GRA
        invoice.save(update_fields=["status"])

        # Enqueue asynchronous GRA clearance
        enqueue_gra_clearance(invoice.id)

        return invoice

    @classmethod
    def _post_invoice_to_ledger(
        cls,
        organization: Organization,
        invoice: Invoice,
        tax_breakdown: Any,
        user: Any,
    ) -> Any:
        """Resolves standard chart of accounts and posts balanced journal lines to LedgerService."""
        accounts = ensure_organization_tax_accounts(organization)

        ar_account = accounts[ACCOUNT_CODE_AR]
        revenue_account = accounts[ACCOUNT_CODE_REVENUE_STANDARD]
        vat_account = accounts.get(ACCOUNT_CODE_VAT_OUTPUT)
        nhil_account = accounts.get(ACCOUNT_CODE_NHIL_OUTPUT)
        getfund_account = accounts.get(ACCOUNT_CODE_GETFUND_OUTPUT)

        ledger_lines = TaxCalculationEngine.get_invoice_ledger_lines(
            tax_breakdown=tax_breakdown,
            ar_account=ar_account,
            revenue_account=revenue_account,
            vat_account=vat_account,
            nhil_account=nhil_account,
            getfund_account=getfund_account,
            narration=f"Invoice {invoice.invoice_number}",
        )

        journal_entry = LedgerService.post_journal_entry(
            organization=organization,
            entry_date=invoice.issue_date,
            lines_data=ledger_lines,
            narration=f"Tax Invoice {invoice.invoice_number} - {invoice.customer_name}",
            user=user,
            source_type=SourceTypeChoices.INVOICE,
            source_id=invoice.id,
        )

        logger.info(
            "Posted balanced journal entry %s for invoice %s",
            journal_entry.entry_number,
            invoice.invoice_number,
        )
        return journal_entry
