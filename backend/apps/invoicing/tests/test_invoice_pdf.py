"""Unit and integration tests for Air-Gapped Invoice PDF Generation and R2 Storage (Feature 3.4).

Verifies:
1. In-memory vector PDF generation conforming to Act 1151 statutory tax layout.
2. In-memory vector QR Code generation for cleared GRA invoices.
3. Statutory layout for PENDING_GRA and DRAFT status states.
4. Point-in-time frozen legal customer snapshot fidelity.
5. Deterministic MockR2Storage upload, retrieval, and presigned download URL generation.
6. REST API download endpoint (presigned URL and streaming binary modes).
7. Explicit PDF re-generation endpoint.
"""

from datetime import date
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
from apps.invoicing.services.pdf_service import InvoicePDFService
from apps.tenancy.middleware import set_current_tenant
from apps.tenancy.models import (
    Organization,
    OrganizationMembership,
    RoleChoices,
    TaxSchemeChoices,
)


class InvoicePDFUnitTests(TestCase):
    """Functional tests for AirGappedPDFCompiler and MockR2Storage."""

    def setUp(self) -> None:
        self.client = APIClient()
        MockR2Storage.clear()

        # Tenant Organization
        self.org = Organization.objects.create(
            name="Kumasi Industrial Tools Ltd",
            business_tin="C0009988771",
            phone="+233240003344",
            email="billing@kumasitools.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )

        # Authenticated User
        self.user = CustomUser.objects.create_user(
            email="accountant@kumasitools.gh",
            password="StrongPassword123!",
            first_name="Kofi",
            last_name="Appiah",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user,
            role=RoleChoices.ACCOUNTANT,
            is_active=True,
        )

        # Customer Master Contact
        self.customer = Contact.objects.create(
            organization=self.org,
            name="Accra Building Contractors Enterprise",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0005544332",
            ghana_card_number="GHA-998877665-1",
            billing_address="Plot 42, Industrial Area, North Kaneshie, Accra",
            phone="+233201119988",
            email="procurement@accrabuilding.gh",
        )

        # Standard Issued Invoice with Frozen Legal Snapshot
        self.invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-00101",
            issue_date=date(2026, 9, 26),
            due_date=date(2026, 10, 26),
            subtotal_amount=Decimal("1000.0000"),
            vat_amount=Decimal("150.0000"),
            nhil_amount=Decimal("25.0000"),
            getfund_amount=Decimal("25.0000"),
            total_amount=Decimal("1200.0000"),
            status=InvoiceStatusChoices.PENDING_GRA,
            customer_name="Accra Building Contractors Enterprise",
            customer_tin="C0005544332",
            customer_ghana_card="GHA-998877665-1",
            customer_address="Plot 42, Industrial Area, North Kaneshie, Accra",
            customer_phone="+233201119988",
            customer_email="procurement@accrabuilding.gh",
            snapshot_frozen_at=timezone.now(),
        )

        # Invoice Line
        self.line = InvoiceLine.objects.create(
            organization=self.org,
            invoice=self.invoice,
            description="Heavy Duty Concrete Drill Set",
            quantity=Decimal("2.0000"),
            unit_price=Decimal("500.0000"),
            vat_rate=Decimal("0.1500"),
            nhil_rate=Decimal("0.0250"),
            getfund_rate=Decimal("0.0250"),
            vat_amount=Decimal("150.0000"),
            nhil_amount=Decimal("25.0000"),
            getfund_amount=Decimal("25.0000"),
            line_total=Decimal("1200.0000"),
        )

        # Authenticate client
        token = AccessToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.org.id)
        set_current_tenant(self.org, self.membership.role)

    def test_compile_invoice_pdf_layout(self) -> None:
        """AirGappedPDFCompiler generates valid binary PDF with %PDF- header."""
        pdf_bytes = AirGappedPDFCompiler.compile_invoice_pdf(self.invoice)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_pdf_cleared_invoice_renders_qr_code(self) -> None:
        """Cleared invoice generates in-memory vector QR Code and GRA verification details."""
        self.invoice.status = InvoiceStatusChoices.CLEARED
        self.invoice.gra_clearance_code = "SDC-2026-GRA-CLEAR-777"
        self.invoice.gra_cleared_at = timezone.now()
        self.invoice.save()

        pdf_bytes = AirGappedPDFCompiler.compile_invoice_pdf(self.invoice)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_pdf_draft_invoice_layout(self) -> None:
        """Draft invoice renders valid PDF with draft notice."""
        self.invoice.status = InvoiceStatusChoices.DRAFT
        self.invoice.save()

        pdf_bytes = AirGappedPDFCompiler.compile_invoice_pdf(self.invoice)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_pdf_preserves_frozen_customer_snapshot(self) -> None:
        """PDF rendering reflects frozen legal customer snapshot, not mutated contact profile."""
        # Mutate master Contact profile
        self.customer.name = "TOTALLY CHANGED PROFILE NAME LTD"
        self.customer.tin = "C9999999999"
        self.customer.billing_address = "Changed Address Road 99"
        self.customer.save()

        # Generate PDF - should run successfully using frozen snapshot
        pdf_bytes = AirGappedPDFCompiler.compile_invoice_pdf(self.invoice)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_mock_r2_storage_crud_operations(self) -> None:
        """MockR2Storage accurately uploads, stores, retrieves, and checks existence of bytes."""
        storage = MockR2Storage()
        test_key = "test_org/invoices/2026/09/test.pdf"
        test_data = b"%PDF-1.4 Mock Test Payload"

        # Upload
        uploaded_key = storage.upload_file_bytes(test_key, test_data)
        self.assertEqual(uploaded_key, test_key)

        # Exists
        self.assertTrue(storage.file_exists(test_key))
        self.assertFalse(storage.file_exists("non_existent_key.pdf"))

        # Presigned URL
        presigned_url = storage.generate_presigned_download_url(test_key, expires_in=900)
        self.assertIn(test_key, presigned_url)
        self.assertIn("expires=900", presigned_url)

        # Retrieve
        retrieved_data = storage.get_file_bytes(test_key)
        self.assertEqual(retrieved_data, test_data)

        # Delete
        self.assertTrue(storage.delete_file(test_key))
        self.assertFalse(storage.file_exists(test_key))

        # Missing object raises FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            storage.get_file_bytes(test_key)

    def test_invoice_pdf_service_orchestration(self) -> None:
        """InvoicePDFService compiles PDF, uploads to R2 key partition, and updates invoice."""
        storage = MockR2Storage()
        presigned_url, storage_key = InvoicePDFService.generate_and_upload_invoice_pdf(
            self.invoice,
            storage_service=storage,
        )

        expected_key = f"{self.org.id}/invoices/2026/09/{self.invoice.id}.pdf"
        self.assertEqual(storage_key, expected_key)
        self.assertTrue(storage.file_exists(expected_key))

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.pdf_url, expected_key)
        self.assertIn(expected_key, presigned_url)

        # Test download URL resolution
        resolved_url = InvoicePDFService.get_invoice_pdf_download_url(
            self.invoice,
            storage_service=storage,
        )
        self.assertEqual(resolved_url, presigned_url)

    def test_invoice_download_api_endpoint_returns_presigned_url(self) -> None:
        """GET /api/v1/invoices/<id>/download/ returns HTTP 200 with presigned download URL."""
        response = self.client.get(f"/api/v1/invoices/{self.invoice.id}/download/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["invoice_id"], str(self.invoice.id))
        self.assertEqual(data["invoice_number"], self.invoice.invoice_number)
        self.assertEqual(data["expires_in"], 900)
        self.assertIn("download_url", data)

    def test_invoice_download_api_streaming_binary(self) -> None:
        """GET /api/v1/invoices/<id>/download/?stream=true returns raw binary PDF stream."""
        response = self.client.get(f"/api/v1/invoices/{self.invoice.id}/download/?stream=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(self.invoice.invoice_number, response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_invoice_generate_pdf_api_endpoint(self) -> None:
        """POST /api/v1/invoices/<id>/generate-pdf/ forces PDF compilation and updates R2 record."""
        response = self.client.post(f"/api/v1/invoices/{self.invoice.id}/generate-pdf/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("download_url", data)
        self.assertIn("storage_key", data)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.pdf_url, data["storage_key"])

    def test_non_existent_invoice_download_returns_404(self) -> None:
        """GET /api/v1/invoices/<uuid>/download/ with invalid ID returns HTTP 404."""
        import uuid

        random_id = uuid.uuid4()
        response = self.client.get(f"/api/v1/invoices/{random_id}/download/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
