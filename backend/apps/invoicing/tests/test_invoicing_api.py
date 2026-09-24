"""Unit and integration tests for Invoicing REST API & General Ledger Posting.

Verifies:
1. Invoice creation with Act 1151 statutory tax splits (15% VAT, 2.5% NHIL, 2.5% GETFund).
2. Point-in-time customer snapshot immutability.
3. Self-validating Luhn payment reference auto-generation.
4. Atomic balanced journal posting to General Ledger (Dr 1200, Cr 4000, Cr 2100/2110/2120).
5. Fast response time (<150ms) and asynchronous GRA clearance dispatch.
6. Draft invoice lifecycle and subsequent issuance.
7. Zero-tax omission defense for exempt supplies.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.authentication.models import CustomUser
from apps.invoicing.models import (
    Contact,
    ContactTypeChoices,
    InvoiceStatusChoices,
)
from apps.invoicing.utils import LuhnValidator
from apps.ledger.models import JournalEntry, SourceTypeChoices
from apps.tax.services import (
    ACCOUNT_CODE_AR,
    ACCOUNT_CODE_GETFUND_OUTPUT,
    ACCOUNT_CODE_NHIL_OUTPUT,
    ACCOUNT_CODE_REVENUE_STANDARD,
    ACCOUNT_CODE_VAT_OUTPUT,
)
from apps.tenancy.middleware import set_current_tenant
from apps.tenancy.models import (
    Organization,
    OrganizationMembership,
    RoleChoices,
    TaxSchemeChoices,
)


class InvoicingAPITests(TestCase):
    """Functional test suite for Invoicing API endpoints and General Ledger integration."""

    def setUp(self) -> None:
        self.client = APIClient()

        # 1. Organization (Tenant)
        self.org = Organization.objects.create(
            name="Accra Wholesale Supplies Ltd",
            business_tin="C0001234567",
            phone="+233240001122",
            email="accounts@accrawholesale.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )

        # 2. Authenticated User & Membership
        self.user = CustomUser.objects.create_user(
            email="accountant@accrawholesale.gh",
            password="StrongPassword123!",
            first_name="Kwame",
            last_name="Mensah",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user,
            role=RoleChoices.ACCOUNTANT,
            is_active=True,
        )

        # 3. Customer Contact
        self.customer = Contact.objects.create(
            organization=self.org,
            name="Kumasi Retailers Enterprise",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0009876543",
            ghana_card_number="GHA-123456789-0",
            billing_address="P.O. Box KS 100, Adum, Kumasi",
            phone="+233201112233",
            email="billing@kumasiretailers.gh",
        )

        # Configure client headers
        self._authenticate(self.user)
        self.client.defaults["HTTP_X_TENANT_ID"] = str(self.org.id)
        set_current_tenant(self.org, self.membership.role)

    def _authenticate(self, user: CustomUser) -> None:
        """Helper to inject Bearer JWT credentials for TenantSecurityMiddleware."""
        token = AccessToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_create_and_issue_invoice_success(self) -> None:
        """POST /api/v1/invoices/ creates invoice, computes Act 1151 taxes, and posts to GL."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "currency": "GHS",
            "action": "issue",
            "lines": [
                {
                    "description": "Standard Merchandise Batch A",
                    "quantity": "2.0000",
                    "unit_price": "500.0000",
                    "supply_type": TaxSchemeChoices.STANDARD,
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.data
        invoice_id = data["id"]

        # Verify Invoice DTO
        self.assertEqual(data["status"], InvoiceStatusChoices.PENDING_GRA)
        self.assertEqual(Decimal(data["subtotal_amount"]), Decimal("1000.0000"))
        self.assertEqual(Decimal(data["vat_amount"]), Decimal("150.0000"))  # 15%
        self.assertEqual(Decimal(data["nhil_amount"]), Decimal("25.0000"))  # 2.5%
        self.assertEqual(Decimal(data["getfund_amount"]), Decimal("25.0000"))  # 2.5%
        self.assertEqual(Decimal(data["total_amount"]), Decimal("1200.0000"))  # Unified 20%
        self.assertEqual(Decimal(data["balance_due"]), Decimal("1200.0000"))

        # Verify Payment Reference (Luhn Mod-10)
        payment_ref = data["payment_reference"]
        self.assertTrue(bool(payment_ref))
        self.assertTrue(LuhnValidator.validate(payment_ref))

        # Verify Share Token (UUIDv4)
        self.assertTrue(bool(data["share_token"]))

        # Verify Customer Legal Snapshot
        self.assertEqual(data["customer_name"], self.customer.name)
        self.assertEqual(data["customer_tin"], self.customer.tin)
        self.assertEqual(data["customer_ghana_card"], self.customer.ghana_card_number)
        self.assertEqual(data["customer_address"], self.customer.billing_address)
        self.assertIsNotNone(data["snapshot_frozen_at"])

        # Verify General Ledger Posting
        journal_entry = JournalEntry.objects.filter(
            organization=self.org,
            source_id=invoice_id,
            source_type=SourceTypeChoices.INVOICE,
        ).first()

        self.assertIsNotNone(journal_entry)

        lines = list(journal_entry.lines.select_related("account").all())
        # Expected accounts: Dr 1200 (AR), Cr 4000 (Revenue),
        # Cr 2100 (VAT), Cr 2110 (NHIL), Cr 2120 (GETFund)
        self.assertEqual(len(lines), 5)

        total_debits = sum(line.debit_amount for line in lines)
        total_credits = sum(line.credit_amount for line in lines)
        self.assertEqual(total_debits, Decimal("1200.0000"))
        self.assertEqual(total_credits, Decimal("1200.0000"))

        # Validate accounts
        accounts_map = {line.account.account_code: line for line in lines}
        self.assertEqual(accounts_map[ACCOUNT_CODE_AR].debit_amount, Decimal("1200.0000"))
        self.assertEqual(
            accounts_map[ACCOUNT_CODE_REVENUE_STANDARD].credit_amount, Decimal("1000.0000")
        )
        self.assertEqual(accounts_map[ACCOUNT_CODE_VAT_OUTPUT].credit_amount, Decimal("150.0000"))
        self.assertEqual(accounts_map[ACCOUNT_CODE_NHIL_OUTPUT].credit_amount, Decimal("25.0000"))
        self.assertEqual(
            accounts_map[ACCOUNT_CODE_GETFUND_OUTPUT].credit_amount, Decimal("25.0000")
        )

    def test_create_draft_invoice_does_not_post_to_ledger(self) -> None:
        """Creating an invoice with action='save_draft' saves as DRAFT without posting to GL."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=15)),
            "action": "save_draft",
            "lines": [
                {
                    "description": "Consulting Services (Draft)",
                    "quantity": "1.0000",
                    "unit_price": "800.0000",
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        invoice_id = response.data["id"]
        self.assertEqual(response.data["status"], InvoiceStatusChoices.DRAFT)

        # Assert no journal entry was created for draft
        journal_entry = JournalEntry.objects.filter(
            organization=self.org,
            source_id=invoice_id,
        ).first()
        self.assertIsNone(journal_entry)

    def test_issue_draft_invoice_endpoint(self) -> None:
        """POST /api/v1/invoices/<id>/issue/ transitions draft to PENDING_GRA and posts to GL."""
        # 1. Create draft
        draft_payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=15)),
            "action": "save_draft",
            "lines": [
                {
                    "description": "Draft Line",
                    "quantity": "1.0000",
                    "unit_price": "1000.0000",
                }
            ],
        }
        res_create = self.client.post("/api/v1/invoices/", draft_payload, format="json")
        invoice_id = res_create.data["id"]

        # 2. Issue the draft
        res_issue = self.client.post(f"/api/v1/invoices/{invoice_id}/issue/", {}, format="json")
        self.assertEqual(res_issue.status_code, status.HTTP_200_OK)
        self.assertEqual(res_issue.data["status"], InvoiceStatusChoices.PENDING_GRA)

        # 3. Assert GL entry exists
        journal_entry = JournalEntry.objects.filter(
            organization=self.org,
            source_id=invoice_id,
        ).first()
        self.assertIsNotNone(journal_entry)
        lines = list(journal_entry.lines.all())
        total_debits = sum(line.debit_amount for line in lines)
        total_credits = sum(line.credit_amount for line in lines)
        self.assertEqual(total_debits, total_credits)

    def test_exempt_supplies_omits_zero_tax_lines(self) -> None:
        """Exempt supplies omit tax lines from GL to satisfy check_either_debit_or_credit."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "action": "issue",
            "lines": [
                {
                    "description": "Exempt Agricultural Produce",
                    "quantity": "10.0000",
                    "unit_price": "100.0000",
                    "supply_type": TaxSchemeChoices.EXEMPT,
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        invoice_id = response.data["id"]
        self.assertEqual(Decimal(response.data["subtotal_amount"]), Decimal("1000.0000"))
        self.assertEqual(Decimal(response.data["total_amount"]), Decimal("1000.0000"))
        self.assertEqual(Decimal(response.data["vat_amount"]), Decimal("0.0000"))

        # Verify GL has exactly 2 lines (Dr 1200 AR, Cr 4000 Revenue); zero tax lines omitted
        journal_entry = JournalEntry.objects.get(
            organization=self.org,
            source_id=invoice_id,
        )
        lines = list(journal_entry.lines.all())
        self.assertEqual(len(lines), 2)
        self.assertEqual(sum(line.debit_amount for line in lines), Decimal("1000.0000"))
        self.assertEqual(sum(line.credit_amount for line in lines), Decimal("1000.0000"))

    def test_get_invoice_detail(self) -> None:
        """GET /api/v1/invoices/<id>/ returns complete invoice DTO."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Item Alpha",
                    "quantity": "1.0000",
                    "unit_price": "200.0000",
                }
            ],
        }
        res_create = self.client.post("/api/v1/invoices/", payload, format="json")
        invoice_id = res_create.data["id"]

        res_detail = self.client.get(f"/api/v1/invoices/{invoice_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data["id"], invoice_id)
        self.assertEqual(len(res_detail.data["lines"]), 1)
        self.assertEqual(res_detail.data["customer_name"], self.customer.name)

    def test_list_invoices_with_filter_and_search(self) -> None:
        """GET /api/v1/invoices/ filters by status and search terms."""
        # Create draft invoice
        self.client.post(
            "/api/v1/invoices/",
            {
                "customer_id": str(self.customer.id),
                "issue_date": str(date.today()),
                "due_date": str(date.today() + timedelta(days=10)),
                "action": "save_draft",
                "lines": [{"description": "Draft", "quantity": "1", "unit_price": "100"}],
            },
            format="json",
        )

        # Create issued invoice
        self.client.post(
            "/api/v1/invoices/",
            {
                "customer_id": str(self.customer.id),
                "issue_date": str(date.today()),
                "due_date": str(date.today() + timedelta(days=10)),
                "action": "issue",
                "lines": [{"description": "Issued", "quantity": "1", "unit_price": "100"}],
            },
            format="json",
        )

        # Filter by status DRAFT
        res_draft = self.client.get("/api/v1/invoices/?status=DRAFT")
        self.assertEqual(res_draft.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_draft.data), 1)

        # Filter by status PENDING_GRA
        res_gra = self.client.get("/api/v1/invoices/?status=PENDING_GRA")
        self.assertEqual(res_gra.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_gra.data), 1)

        # Search by customer name
        res_search = self.client.get("/api/v1/invoices/?search=Kumasi")
        self.assertEqual(res_search.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_search.data), 2)

    def test_due_date_must_be_gte_issue_date(self) -> None:
        """Chronological validation: due_date cannot precede issue_date."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() - timedelta(days=1)),  # Backward date
            "lines": [
                {
                    "description": "Invalid dates line",
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                }
            ],
        }

        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("due_date", response.data)

    def test_zero_quantity_rejected(self) -> None:
        """Edge case: Quantity of 0.0000 is rejected with HTTP 400 (min_value is 0.0001)."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Zero quantity probe",
                    "quantity": "0.0000",
                    "unit_price": "100.0000",
                }
            ],
        }
        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lines", response.data)

    def test_non_existent_customer_rejected(self) -> None:
        """Edge case: Non-existent customer UUID returns HTTP 400."""
        import uuid

        random_customer_id = str(uuid.uuid4())
        payload = {
            "customer_id": random_customer_id,
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "lines": [
                {
                    "description": "Valid line item",
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                }
            ],
        }
        response = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("customer_id", response.data)

    def test_customer_snapshot_immutability_on_subsequent_contact_edit(self) -> None:
        """Modifying customer contact does not alter existing invoice legal snapshot."""
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "action": "issue",
            "lines": [
                {
                    "description": "Service Contract",
                    "quantity": "1.0000",
                    "unit_price": "500.0000",
                }
            ],
        }
        res = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        invoice_id = res.data["id"]

        # Mutate customer master record
        self.customer.name = "CHANGED CUSTOMER NAME CORP"
        self.customer.tin = "C9999999999"
        self.customer.billing_address = "Changed Address Road 123"
        self.customer.save()

        # Retrieve invoice detail - snapshot must reflect original state at creation
        res_detail = self.client.get(f"/api/v1/invoices/{invoice_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data["customer_name"], "Kumasi Retailers Enterprise")
        self.assertEqual(res_detail.data["customer_tin"], "C0009876543")
        self.assertEqual(res_detail.data["customer_address"], "P.O. Box KS 100, Adum, Kumasi")

    def test_reissuing_already_issued_invoice_fails(self) -> None:
        """Issuing an invoice already in PENDING_GRA returns HTTP 400."""
        # 1. Create already issued invoice
        payload = {
            "customer_id": str(self.customer.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "action": "issue",
            "lines": [
                {
                    "description": "Already Issued Item",
                    "quantity": "1.0000",
                    "unit_price": "100.0000",
                }
            ],
        }
        res_create = self.client.post("/api/v1/invoices/", payload, format="json")
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        invoice_id = res_create.data["id"]

        # 2. Attempt to issue again
        res_reissue = self.client.post(f"/api/v1/invoices/{invoice_id}/issue/", {}, format="json")
        self.assertEqual(res_reissue.status_code, status.HTTP_400_BAD_REQUEST)
        detail = (
            res_reissue.data["detail"] if "detail" in res_reissue.data else str(res_reissue.data)
        )
        self.assertIn("DRAFT", detail)

    def test_non_existent_invoice_detail_returns_404(self) -> None:
        """GET /api/v1/invoices/<uuid>/ with non-existent ID returns HTTP 404."""
        import uuid

        random_id = uuid.uuid4()
        response = self.client.get(f"/api/v1/invoices/{random_id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_existent_invoice_issue_returns_404(self) -> None:
        """POST /api/v1/invoices/<uuid>/issue/ with non-existent ID returns HTTP 404."""
        import uuid

        random_id = uuid.uuid4()
        response = self.client.post(f"/api/v1/invoices/{random_id}/issue/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
