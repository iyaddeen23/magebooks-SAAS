"""Security and Misuse Case Penetration Tests for Invoicing API (Feature 3.3).

Covers:
1. MUC-2.1: Cross-Tenant Customer Injection (BOLA/IDOR attempt).
2. MUC-2.1: Cross-Tenant Account Override Injection.
3. RBAC Containment: Auditor role write protection (POST /api/v1/invoices/ returns 403).
4. RBAC Containment: Auditor role allowed read access (GET /api/v1/invoices/ returns 200).
5. Input Boundary Defense: Negative quantities and unit prices strictly blocked.
6. Empty line items attack defense.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.authentication.models import CustomUser
from apps.invoicing.models import Contact, ContactTypeChoices, Invoice, InvoiceStatusChoices
from apps.ledger.models import ChartOfAccounts
from apps.ledger.services.seeder import seed_standard_chart_of_accounts
from apps.tenancy.middleware import set_current_tenant
from apps.tenancy.models import (
    Organization,
    OrganizationMembership,
    RoleChoices,
    TaxSchemeChoices,
)


class InvoicingAPISecurityTests(TestCase):
    """Misuse case penetration test suite for Invoicing API."""

    def setUp(self) -> None:
        self.client = APIClient()

        # Tenant A (Primary)
        self.tenant_a = Organization.objects.create(
            name="Tenant A Trading Ltd",
            business_tin="C0001111111",
            phone="+233240000001",
            email="tenant_a@trade.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.user_a = CustomUser.objects.create_user(
            email="user_a@trade.gh",
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
        seed_standard_chart_of_accounts(self.tenant_b)

        # Authenticate as Tenant A by default
        self._authenticate(self.user_a)
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)
        set_current_tenant(self.tenant_a, self.membership_a.role)

    def _authenticate(self, user: CustomUser) -> None:
        """Helper to inject Bearer JWT credentials for TenantSecurityMiddleware."""
        token = AccessToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_cross_tenant_customer_injection_blocked(self) -> None:
        """MUC-2.1: Attacker in Tenant A cannot create an invoice for Tenant B's customer."""
        malicious_payload = {
            "customer_id": str(self.customer_b.id),  # Belongs to Tenant B!
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "BOLA Probe Item",
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", malicious_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("customer_id", response.data)

    def test_cross_tenant_account_override_blocked(self) -> None:
        """MUC-2.1: Attacker in Tenant A cannot specify Tenant B's General Ledger account."""
        account_b = ChartOfAccounts.objects.filter(organization=self.tenant_b).first()
        self.assertIsNotNone(account_b)

        malicious_payload = {
            "customer_id": str(self.customer_a.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Cross-Tenant Account Probe",
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                    "account_id": str(account_b.id),  # Belongs to Tenant B!
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", malicious_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("account_id", response.data)

    def test_auditor_role_blocked_from_invoice_creation(self) -> None:
        """RBAC Containment: External Auditor attempting POST /api/v1/invoices/ receives 403."""
        auditor_user = CustomUser.objects.create_user(
            email="auditor@pwc.gh",
            password="StrongPassword123!",
            first_name="External",
            last_name="Auditor",
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

        payload = {
            "customer_id": str(self.customer_a.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Unauthorized Auditor Invoice",
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        detail = response.data["detail"] if hasattr(response, "data") else response.json()["detail"]
        self.assertIn("Auditor", detail)

    def test_auditor_role_allowed_to_read_invoices(self) -> None:
        """RBAC Compliance: External Auditor can read invoice lists and detail views."""
        # Create an existing invoice as Accountant
        invoice = Invoice.objects.create(
            organization=self.tenant_a,
            customer=self.customer_a,
            invoice_number="INV-2026-00099",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.PENDING_GRA,
        )

        auditor_user = CustomUser.objects.create_user(
            email="auditor2@kpmg.gh",
            password="StrongPassword123!",
            first_name="Auditor",
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

        # GET List
        res_list = self.client.get("/api/v1/invoices/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_list.data), 1)

        # GET Detail
        res_detail = self.client.get(f"/api/v1/invoices/{invoice.id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data["id"], str(invoice.id))

    def test_auditor_role_blocked_from_invoice_issue(self) -> None:
        """RBAC Containment: External Auditor cannot issue draft invoices via POST /issue/."""
        draft_invoice = Invoice.objects.create(
            organization=self.tenant_a,
            customer=self.customer_a,
            invoice_number="INV-2026-DRAFT-01",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        auditor_user = CustomUser.objects.create_user(
            email="auditor3@ey.gh",
            password="StrongPassword123!",
            first_name="Auditor",
            last_name="EY",
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

        res_issue = self.client.post(
            f"/api/v1/invoices/{draft_invoice.id}/issue/", {}, format="json"
        )
        self.assertEqual(res_issue.status_code, status.HTTP_403_FORBIDDEN)
        detail = (
            res_issue.data["detail"] if hasattr(res_issue, "data") else res_issue.json()["detail"]
        )
        self.assertIn("Auditor", detail)

    def test_expired_auditor_access_blocked(self) -> None:
        """Auditor with expired access_expires_at is blocked with HTTP 403 even for GET."""
        expired_auditor = CustomUser.objects.create_user(
            email="expired@auditor.gh",
            password="StrongPassword123!",
            first_name="Expired",
            last_name="Auditor",
        )
        expired_membership = OrganizationMembership.objects.create(
            organization=self.tenant_a,
            user=expired_auditor,
            role=RoleChoices.AUDITOR,
            is_active=True,
            access_expires_at=timezone.now() - timedelta(days=1),  # Expired yesterday
        )

        self._authenticate(expired_auditor)
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.tenant_a.id)
        set_current_tenant(self.tenant_a, expired_membership.role)

        response = self.client.get("/api/v1/invoices/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        detail = response.data["detail"] if hasattr(response, "data") else response.json()["detail"]
        self.assertIn("expired", detail.lower())

    def test_negative_quantity_or_unit_price_blocked(self) -> None:
        """Input Boundary Defense: Negative quantities and unit prices are strictly rejected."""
        negative_qty_payload = {
            "customer_id": str(self.customer_a.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Negative Quantity Probe",
                    "quantity": "-5.0000",
                    "unit_price": "100.0000",
                }
            ],
        }
        res_qty = self.client.post("/api/v1/invoices/", negative_qty_payload, format="json")
        self.assertEqual(res_qty.status_code, status.HTTP_400_BAD_REQUEST)

        negative_price_payload = {
            "customer_id": str(self.customer_a.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Negative Price Probe",
                    "quantity": "5.0000",
                    "unit_price": "-100.0000",
                }
            ],
        }
        res_price = self.client.post("/api/v1/invoices/", negative_price_payload, format="json")
        self.assertEqual(res_price.status_code, status.HTTP_400_BAD_REQUEST)

    def test_empty_line_items_blocked(self) -> None:
        """Invoices without item lines are rejected with HTTP 400."""
        empty_payload = {
            "customer_id": str(self.customer_a.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [],
        }
        response = self.client.post("/api/v1/invoices/", empty_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lines", response.data)

    def test_auditor_role_blocked_from_all_mutating_http_methods(self) -> None:
        """RBAC Guard: External Auditor cannot execute PUT, PATCH, or DELETE on invoices."""
        invoice = Invoice.objects.create(
            organization=self.tenant_a,
            customer=self.customer_a,
            invoice_number="INV-2026-00055",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )

        auditor_user = CustomUser.objects.create_user(
            email="auditor_mutating@deloitte.gh",
            password="StrongPassword123!",
            first_name="Auditor",
            last_name="Deloitte",
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

        # PUT
        res_put = self.client.put(
            f"/api/v1/invoices/{invoice.id}/", {"notes": "Tampered"}, format="json"
        )
        self.assertEqual(res_put.status_code, status.HTTP_403_FORBIDDEN)

        # PATCH
        res_patch = self.client.patch(
            f"/api/v1/invoices/{invoice.id}/", {"notes": "Tampered"}, format="json"
        )
        self.assertEqual(res_patch.status_code, status.HTTP_403_FORBIDDEN)

        # DELETE
        res_delete = self.client.delete(f"/api/v1/invoices/{invoice.id}/")
        self.assertEqual(res_delete.status_code, status.HTTP_403_FORBIDDEN)
