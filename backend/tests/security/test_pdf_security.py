"""Security Misuse Case Penetration Tests for Invoice PDF Generation & R2 Storage (Feature 3.4).

Covers:
1. MUC-4.1: Server-Side Request Forgery (SSRF) & Local File Inclusion Defense.
2. MUC-2.1: Cross-Tenant PDF Download & Generation Isolation (BOLA/IDOR attempt).
3. RBAC Containment: External Auditor write block on POST /generate-pdf/ (HTTP 403).
4. RBAC Compliance: External Auditor allowed read access on GET /download/ (HTTP 200).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.authentication.models import CustomUser
from apps.core.services.storage import MockR2Storage
from apps.invoicing.models import (
    Contact,
    ContactTypeChoices,
    Invoice,
    InvoiceLine,
    InvoiceStatusChoices,
)
from apps.invoicing.services.pdf_compiler import AirGappedPDFCompiler
from apps.tenancy.middleware import set_current_tenant
from apps.tenancy.models import (
    Organization,
    OrganizationMembership,
    RoleChoices,
    TaxSchemeChoices,
)


class InvoicePDFSecurityTests(TestCase):
    """Misuse case penetration test suite for invoice PDF generation and R2 download endpoints."""

    def setUp(self) -> None:
        self.client = APIClient()
        MockR2Storage.clear()

        # Tenant A (Primary)
        self.tenant_a = Organization.objects.create(
            name="Tenant A Logistics Ltd",
            business_tin="C0001111111",
            phone="+233240000001",
            email="tenant_a@logistics.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.user_a = CustomUser.objects.create_user(
            email="accountant_a@logistics.gh",
            password="StrongPassword123!",
            first_name="User",
            last_name="A",
        )
        self.membership_a = OrganizationMembership.objects.create(
            organization=self.tenant_a,
            user=self.user_a,
            role=RoleChoices.ACCOUNTANT,
            is_active=True,
        )
        self.customer_a = Contact.objects.create(
            organization=self.tenant_a,
            name="Customer A",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0002222222",
        )
        self.invoice_a = Invoice.objects.create(
            organization=self.tenant_a,
            customer=self.customer_a,
            invoice_number="INV-2026-A0001",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            subtotal_amount=Decimal("1000.0000"),
            total_amount=Decimal("1200.0000"),
            status=InvoiceStatusChoices.PENDING_GRA,
            customer_name="Customer A",
            customer_tin="C0002222222",
        )
        InvoiceLine.objects.create(
            organization=self.tenant_a,
            invoice=self.invoice_a,
            description="Freight Forwarding Services",
            quantity=Decimal("1.0000"),
            unit_price=Decimal("1000.0000"),
            line_total=Decimal("1200.0000"),
        )

        # Tenant B (Victim)
        self.tenant_b = Organization.objects.create(
            name="Tenant B Competitor Ltd",
            business_tin="C0003333333",
            phone="+233240000002",
            email="tenant_b@comp.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.customer_b = Contact.objects.create(
            organization=self.tenant_b,
            name="Customer B (Victim)",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0004444444",
        )
        self.invoice_b = Invoice.objects.create(
            organization=self.tenant_b,
            customer=self.customer_b,
            invoice_number="INV-2026-B0001",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            subtotal_amount=Decimal("5000.0000"),
            total_amount=Decimal("6000.0000"),
            status=InvoiceStatusChoices.PENDING_GRA,
            customer_name="Customer B (Victim)",
            customer_tin="C0004444444",
        )

        # Authenticate as Tenant A by default
        self._authenticate(self.user_a)
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)
        set_current_tenant(self.tenant_a, self.membership_a.role)

    def _authenticate(self, user: CustomUser) -> None:
        """Inject Bearer JWT credentials for TenantSecurityMiddleware."""
        token = AccessToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_ssrf_cloud_metadata_injection_blocked(self) -> None:
        """MUC-4.1 SSRF Defense: Injected AWS/GCP/Cloud metadata IP raises PermissionError."""
        # 1. Attacker attempts cloud metadata leak via customer name
        self.invoice_a.customer_name = "<img src='http://169.254.169.254/latest/meta-data/'>"
        with self.assertRaises(PermissionError) as ctx:
            AirGappedPDFCompiler.compile_invoice_pdf(self.invoice_a)
        self.assertIn("SSRF Prevention (MUC-4.1)", str(ctx.exception))

    def test_ssrf_external_url_injection_blocked(self) -> None:
        """MUC-4.1 SSRF Defense: Injected outbound HTTP image raises PermissionError."""
        line = self.invoice_a.lines.first()
        self.assertIsNotNone(line)
        line.description = "<img src='https://malicious-hacker.com/exfiltrate.png'>"
        line.save()

        with self.assertRaises(PermissionError) as ctx:
            AirGappedPDFCompiler.compile_invoice_pdf(self.invoice_a)
        self.assertIn("SSRF Prevention (MUC-4.1)", str(ctx.exception))

    def test_ssrf_local_file_inclusion_blocked(self) -> None:
        """MUC-4.1 SSRF Defense: Injected local file URI raises PermissionError."""
        self.invoice_a.customer_address = "<iframe src='file:///etc/passwd'>"
        with self.assertRaises(PermissionError) as ctx:
            AirGappedPDFCompiler.compile_invoice_pdf(self.invoice_a)
        self.assertIn("SSRF Prevention (MUC-4.1)", str(ctx.exception))

    def test_cross_tenant_pdf_download_blocked(self) -> None:
        """MUC-2.1: Attacker in Tenant A cannot download Tenant B's invoice PDF."""
        response = self.client.get(f"/api/v1/invoices/{self.invoice_b.id}/download/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_tenant_pdf_generate_blocked(self) -> None:
        """MUC-2.1: Attacker in Tenant A cannot trigger PDF generation for Tenant B's invoice."""
        response = self.client.post(f"/api/v1/invoices/{self.invoice_b.id}/generate-pdf/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_auditor_role_blocked_from_generating_pdf(self) -> None:
        """RBAC Containment: External Auditor cannot call mutating POST /generate-pdf/."""
        auditor_user = CustomUser.objects.create_user(
            email="auditor@pwc.gh",
            password="StrongPassword123!",
            first_name="Audit",
            last_name="PwC",
        )
        auditor_membership = OrganizationMembership.objects.create(
            organization=self.tenant_a,
            user=auditor_user,
            role=RoleChoices.AUDITOR,
            is_active=True,
            access_expires_at=timezone.now() + timedelta(days=7),
        )

        self._authenticate(auditor_user)
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)
        set_current_tenant(self.tenant_a, auditor_membership.role)

        response = self.client.post(f"/api/v1/invoices/{self.invoice_a.id}/generate-pdf/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        detail = response.data["detail"] if hasattr(response, "data") else response.json()["detail"]
        self.assertIn("Auditor", detail)

    def test_auditor_role_allowed_to_download_pdf(self) -> None:
        """RBAC Compliance: External Auditor can download invoice PDF workpapers."""
        auditor_user = CustomUser.objects.create_user(
            email="auditor_read@kpmg.gh",
            password="StrongPassword123!",
            first_name="Audit",
            last_name="KPMG",
        )
        auditor_membership = OrganizationMembership.objects.create(
            organization=self.tenant_a,
            user=auditor_user,
            role=RoleChoices.AUDITOR,
            is_active=True,
            access_expires_at=timezone.now() + timedelta(days=7),
        )

        self._authenticate(auditor_user)
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)
        set_current_tenant(self.tenant_a, auditor_membership.role)

        # 1. Download URL endpoint
        res_download = self.client.get(f"/api/v1/invoices/{self.invoice_a.id}/download/")
        self.assertEqual(res_download.status_code, status.HTTP_200_OK)
        self.assertIn("download_url", res_download.data)

        # 2. Binary stream endpoint
        res_stream = self.client.get(f"/api/v1/invoices/{self.invoice_a.id}/download/?stream=true")
        self.assertEqual(res_stream.status_code, status.HTTP_200_OK)
        self.assertEqual(res_stream["Content-Type"], "application/pdf")
        self.assertTrue(res_stream.content.startswith(b"%PDF-"))
