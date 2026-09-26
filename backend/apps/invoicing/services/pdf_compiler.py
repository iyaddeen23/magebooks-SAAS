"""Air-Gapped Invoice PDF Generation Engine (ReportLab Vector Implementation).

Features:
1. Act 1151 Statutory Tax Breakdown (15% VAT, 2.5% NHIL, 2.5% GETFund).
2. Point-in-time Frozen Legal Customer Snapshot.
3. Dynamic In-Memory Vector QR Code generation (QrCodeWidget) for GRA E-VAT clearance.
4. MUC-4.1 SSRF Defense: Complete air-gapping with zero outbound network dialing,
   disallowing remote URL fetching and raising PermissionError on malicious input.
5. In-Memory Execution (io.BytesIO): Zero unencrypted temporary disk files.
"""

import html
import io
import re
from typing import Any

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.invoicing.models import Invoice, InvoiceStatusChoices

# Malicious SSRF injection pattern (MUC-4.1)
_SSRF_INJECTION_PATTERN = re.compile(
    r"(?i)(https?://|ftp://|file://|data:|javascript:|169\.254\.169\.254|<img|<iframe|<script|<object|<embed)",
)


class AirGappedPDFCompiler:
    """Compiles statutory Act 1151 invoice PDFs strictly in memory without network calls."""

    @staticmethod
    def assert_air_gapped_safety(value: Any) -> str:
        """MUC-4.1 SSRF Defense: Scans input text for outbound network injection payloads.

        Raises:
            PermissionError: If text contains outbound URLs, metadata endpoints, or HTML tags.
        """
        if value is None:
            return ""
        text = str(value)
        match = _SSRF_INJECTION_PATTERN.search(text)
        if match:
            raise PermissionError(
                f"SSRF Prevention (MUC-4.1): Injected network/scheme reference blocked: "
                f"'{match.group(0)}'"
            )
        return html.escape(text)

    @classmethod
    def compile_invoice_pdf(cls, invoice: Invoice) -> bytes:
        """Builds an Act 1151 statutory tax invoice PDF in memory as raw bytes."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()

        # Custom corporate palette
        primary_color = colors.HexColor("#0F172A")  # Slate 900
        secondary_color = colors.HexColor("#334155")  # Slate 700
        cleared_color = colors.HexColor("#059669")  # Emerald 600
        pending_color = colors.HexColor("#D97706")  # Amber 600
        draft_color = colors.HexColor("#64748B")  # Slate 500
        table_header_bg = colors.HexColor("#F1F5F9")  # Slate 100
        alt_row_bg = colors.HexColor("#F8FAFC")  # Slate 50

        # Typography styles
        style_title = ParagraphStyle(
            "InvoiceTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=primary_color,
        )
        style_company_name = ParagraphStyle(
            "CompanyName",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=primary_color,
        )
        style_meta = ParagraphStyle(
            "MetaText",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=secondary_color,
        )
        style_meta_bold = ParagraphStyle(
            "MetaTextBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=13,
            textColor=primary_color,
        )
        style_section_title = ParagraphStyle(
            "SectionTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=primary_color,
        )
        style_table_cell = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=primary_color,
        )
        style_table_cell_bold = ParagraphStyle(
            "TableCellBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=primary_color,
        )
        style_table_header = ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=primary_color,
        )
        style_footer = ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=secondary_color,
            alignment=1,  # Center
        )

        story: list[Any] = []

        # -------------------------------------------------------------
        # 1. Header: Merchant Details (Left) & Invoice Meta (Right)
        # -------------------------------------------------------------
        org = invoice.organization
        safe_org_name = cls.assert_air_gapped_safety(org.name)
        safe_org_tin = cls.assert_air_gapped_safety(org.business_tin)
        safe_org_phone = cls.assert_air_gapped_safety(org.phone or "")
        safe_org_email = cls.assert_air_gapped_safety(org.email or "")

        safe_inv_num = cls.assert_air_gapped_safety(invoice.invoice_number)
        safe_payment_ref = cls.assert_air_gapped_safety(invoice.payment_reference)
        safe_issue_date = cls.assert_air_gapped_safety(str(invoice.issue_date))
        safe_due_date = cls.assert_air_gapped_safety(str(invoice.due_date))

        # Status text & color
        status_label = invoice.status.replace("_", " ")
        if invoice.status == InvoiceStatusChoices.CLEARED:
            status_color = cleared_color
        elif invoice.status == InvoiceStatusChoices.PENDING_GRA:
            status_color = pending_color
        else:
            status_color = draft_color

        status_style = ParagraphStyle(
            "StatusBadge",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=status_color,
        )

        merchant_details = [
            Paragraph(safe_org_name, style_company_name),
            Paragraph(f"TIN: {safe_org_tin}", style_meta_bold),
            Paragraph(f"Phone: {safe_org_phone} | Email: {safe_org_email}", style_meta),
            Paragraph(
                f"VAT Registered: {'Yes (Standard Scheme)' if org.vat_registered else 'No'}",
                style_meta,
            ),
        ]

        invoice_details = [
            Paragraph("TAX INVOICE", style_title),
            Spacer(1, 4),
            Paragraph(f"<b>Status:</b> {status_label}", status_style),
            Paragraph(f"<b>Invoice #:</b> {safe_inv_num}", style_meta),
            Paragraph(f"<b>Payment Ref:</b> {safe_payment_ref}", style_meta_bold),
            Paragraph(f"<b>Issue Date:</b> {safe_issue_date}", style_meta),
            Paragraph(f"<b>Due Date:</b> {safe_due_date}", style_meta),
        ]

        header_table = Table(
            [[merchant_details, invoice_details]],
            colWidths=[4.0 * inch, 3.2 * inch],
        )
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(header_table)
        story.append(Spacer(1, 14))

        story.append(
            HRFlowable(
                width="100%",
                thickness=1,
                color=colors.HexColor("#E2E8F0"),
                spaceAfter=14,
            )
        )

        # -------------------------------------------------------------
        # 2. Customer Frozen Legal Snapshot Box
        # -------------------------------------------------------------
        safe_cust_name = cls.assert_air_gapped_safety(invoice.customer_name)
        safe_cust_tin = cls.assert_air_gapped_safety(invoice.customer_tin or "N/A")
        safe_cust_ghcard = cls.assert_air_gapped_safety(invoice.customer_ghana_card or "N/A")
        safe_cust_addr = cls.assert_air_gapped_safety(invoice.customer_address or "N/A")
        safe_cust_phone = cls.assert_air_gapped_safety(invoice.customer_phone or "N/A")
        safe_cust_email = cls.assert_air_gapped_safety(invoice.customer_email or "N/A")

        bill_to_content = [
            Paragraph("BILLED TO (LEGAL CUSTOMER SNAPSHOT)", style_section_title),
            Spacer(1, 4),
            Paragraph(f"<b>Name:</b> {safe_cust_name}", style_meta_bold),
            Paragraph(
                f"<b>TIN:</b> {safe_cust_tin} | <b>Ghana Card:</b> {safe_cust_ghcard}", style_meta
            ),
            Paragraph(f"<b>Address:</b> {safe_cust_addr}", style_meta),
            Paragraph(
                f"<b>Phone:</b> {safe_cust_phone} | <b>Email:</b> {safe_cust_email}", style_meta
            ),
        ]

        bill_to_table = Table([[bill_to_content]], colWidths=[7.2 * inch])
        bill_to_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), table_header_bg),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        story.append(bill_to_table)
        story.append(Spacer(1, 14))

        # -------------------------------------------------------------
        # 3. Itemized Line Items Table
        # -------------------------------------------------------------
        headers = [
            Paragraph("#", style_table_header),
            Paragraph("Description", style_table_header),
            Paragraph("Qty", style_table_header),
            Paragraph("Unit Price (GHS)", style_table_header),
            Paragraph("VAT (15%)", style_table_header),
            Paragraph("NHIL (2.5%)", style_table_header),
            Paragraph("GETFund (2.5%)", style_table_header),
            Paragraph("Total (GHS)", style_table_header),
        ]
        table_rows = [headers]

        lines = list(invoice.lines.all().order_by("created_at"))
        for idx, line in enumerate(lines, start=1):
            safe_desc = cls.assert_air_gapped_safety(line.description)
            row = [
                Paragraph(str(idx), style_table_cell),
                Paragraph(safe_desc, style_table_cell),
                Paragraph(f"{line.quantity:,.2f}", style_table_cell),
                Paragraph(f"{line.unit_price:,.2f}", style_table_cell),
                Paragraph(f"{line.vat_amount:,.2f}", style_table_cell),
                Paragraph(f"{line.nhil_amount:,.2f}", style_table_cell),
                Paragraph(f"{line.getfund_amount:,.2f}", style_table_cell),
                Paragraph(f"{line.line_total:,.2f}", style_table_cell_bold),
            ]
            table_rows.append(row)

        lines_table = Table(
            table_rows,
            colWidths=[
                0.3 * inch,
                2.1 * inch,
                0.6 * inch,
                1.0 * inch,
                0.8 * inch,
                0.8 * inch,
                0.8 * inch,
                0.8 * inch,
            ],
        )
        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), table_header_bg),
            ("TEXTCOLOR", (0, 0), (-1, 0), primary_color),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#94A3B8")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        # Alternating row background
        for i in range(1, len(table_rows)):
            if i % 2 == 0:
                table_style.append(("BACKGROUND", (0, i), (-1, i), alt_row_bg))

        lines_table.setStyle(TableStyle(table_style))
        story.append(lines_table)
        story.append(Spacer(1, 14))

        # -------------------------------------------------------------
        # 4. Financial Totals & Act 1151 Tax Schedule
        # -------------------------------------------------------------
        totals_data = [
            [
                Paragraph("Subtotal (Taxable Base):", style_meta),
                Paragraph(f"GHS {invoice.subtotal_amount:,.2f}", style_meta_bold),
            ],
            [
                Paragraph("VAT (15.0% Act 1151):", style_meta),
                Paragraph(f"GHS {invoice.vat_amount:,.2f}", style_meta),
            ],
            [
                Paragraph("NHIL (2.5% Act 1151):", style_meta),
                Paragraph(f"GHS {invoice.nhil_amount:,.2f}", style_meta),
            ],
            [
                Paragraph("GETFund (2.5% Act 1151):", style_meta),
                Paragraph(f"GHS {invoice.getfund_amount:,.2f}", style_meta),
            ],
            [
                Paragraph("<b>Total Amount Due:</b>", style_section_title),
                Paragraph(f"<b>GHS {invoice.total_amount:,.2f}</b>", style_section_title),
            ],
            [
                Paragraph("Payments Applied:", style_meta),
                Paragraph(f"GHS {invoice.paid_amount:,.2f}", style_meta),
            ],
            [
                Paragraph("<b>Balance Due:</b>", style_meta_bold),
                Paragraph(f"<b>GHS {invoice.balance_due:,.2f}</b>", style_meta_bold),
            ],
        ]
        totals_table = Table(totals_data, colWidths=[2.2 * inch, 1.4 * inch])
        totals_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("LINEABOVE", (0, 4), (1, 4), 1, primary_color),
                    ("LINEBELOW", (0, 4), (1, 4), 1, primary_color),
                ]
            )
        )

        # -------------------------------------------------------------
        # 5. GRA E-VAT Clearance Verification Box
        # -------------------------------------------------------------
        if invoice.gra_clearance_code:
            # Cleared invoice: generate in-memory vector QR Code
            verification_payload = f"https://gra.gov.gh/verify/{invoice.gra_clearance_code}"
            qr_drawing = Drawing(70, 70)
            qr_widget = QrCodeWidget(verification_payload)
            qr_widget.barWidth = 70
            qr_widget.barHeight = 70
            qr_drawing.add(qr_widget)

            safe_clearance_code = cls.assert_air_gapped_safety(invoice.gra_clearance_code)
            cleared_time_str = (
                invoice.gra_cleared_at.strftime("%Y-%m-%d %H:%M:%S")
                if invoice.gra_cleared_at
                else "Verified"
            )
            clearance_content = [
                Paragraph("GRA E-VAT CERTIFIED INVOICE", style_section_title),
                Spacer(1, 3),
                Paragraph(f"<b>SDC Clearance Code:</b> {safe_clearance_code}", style_meta_bold),
                Paragraph(f"<b>Cleared At:</b> {cleared_time_str}", style_meta),
                Paragraph(
                    "Scan QR code using GRA Taxpayer App to verify authenticity.", style_meta
                ),
            ]
            clearance_table = Table(
                [[qr_drawing, clearance_content]],
                colWidths=[1.1 * inch, 2.3 * inch],
            )
            clearance_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ECFDF5")),  # Emerald 50
                        ("BOX", (0, 0), (-1, -1), 1, cleared_color),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
        elif invoice.status == InvoiceStatusChoices.PENDING_GRA:
            clearance_content = [
                Paragraph("STATUS: PENDING GRA E-VAT CLEARANCE", style_section_title),
                Spacer(1, 3),
                Paragraph(
                    "Submitted to the Ghana Revenue Authority for cryptographic clearance.",
                    style_meta,
                ),
                Paragraph(
                    "Official GRA QR verification code will attach automatically upon clearance.",
                    style_meta,
                ),
            ]
            clearance_table = Table([[clearance_content]], colWidths=[3.4 * inch])
            clearance_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFBEB")),  # Amber 50
                        ("BOX", (0, 0), (-1, -1), 1, pending_color),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
        else:
            clearance_content = [
                Paragraph("STATUS: DRAFT QUOTATION", style_section_title),
                Spacer(1, 3),
                Paragraph("NOT A VALID TAX INVOICE — FOR ESTIMATION ONLY", style_meta_bold),
                Paragraph(
                    "General Ledger journal lines are not posted for draft invoices.", style_meta
                ),
            ]
            clearance_table = Table([[clearance_content]], colWidths=[3.4 * inch])
            clearance_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),  # Slate 50
                        ("BOX", (0, 0), (-1, -1), 1, draft_color),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )

        # Combine Clearance Box (Left) and Totals Table (Right)
        bottom_table = Table([[clearance_table, totals_table]], colWidths=[3.6 * inch, 3.6 * inch])
        bottom_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(bottom_table)
        story.append(Spacer(1, 24))

        # -------------------------------------------------------------
        # 6. Notes & Statutory Footer
        # -------------------------------------------------------------
        notes = getattr(invoice, "notes", None)
        if notes:
            safe_notes = cls.assert_air_gapped_safety(notes)
            story.append(Paragraph(f"<b>Notes:</b> {safe_notes}", style_meta))
            story.append(Spacer(1, 12))

        footer_text = (
            "Thank you for your business. Generated by Mage Books SAAS — "
            "Fully compliant with Ghana Revenue Authority Act 1151 (2025)."
        )
        story.append(Paragraph(footer_text, style_footer))

        # Build PDF strictly in memory
        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
