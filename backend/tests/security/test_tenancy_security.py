"""Security threat modeling and negative abuse tests for Tenancy Middleware (Sprint 1).

Covers:
- MUC-2.1: Cross-Tenant Header Spoofing BOLA
- MUC-2.2: RLS Connection Pool Leak Defense & Thread-Local Cleanup
- Ephemeral Auditor Access Expiration & Mutating Write Containment (Seq. Diagram Line 432)
- Dual-Header Support (X-Tenant-ID / X-Organization-ID)
- Public Path Exemption
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.tenancy.middleware import (
    TenantSecurityMiddleware,
    get_current_tenant,
    get_current_tenant_id,
    get_current_tenant_role,
)
from apps.tenancy.models import Organization, OrganizationMembership, RoleChoices

User = get_user_model()


class TenancySecurityThreatTests(APITestCase):
    """Threat model and negative test suite for multi-tenant isolation and security middleware."""

    def setUp(self):
        # Create User A and User B
        self.user_a = User.objects.create_user(
            email="tenant.a@magebooks.com",
            password="SecurePassword123!",
            first_name="User",
            last_name="A",
        )
        self.user_b = User.objects.create_user(
            email="tenant.b@magebooks.com",
            password="SecurePassword123!",
            first_name="User",
            last_name="B",
        )

        # Create Organization Alpha and Beta
        self.org_alpha = Organization.objects.create(
            name="Alpha Corp",
            phone="+233241000001",
            email="contact@alphacorp.com",
        )
        self.org_beta = Organization.objects.create(
            name="Beta Ltd",
            phone="+233241000002",
            email="contact@betaltd.com",
        )

        # Assign User A to Org Alpha as OWNER
        self.membership_a = OrganizationMembership.objects.create(
            organization=self.org_alpha,
            user=self.user_a,
            role=RoleChoices.OWNER,
            is_active=True,
        )

        # Assign User B to Org Beta as ADMIN
        self.membership_b = OrganizationMembership.objects.create(
            organization=self.org_beta,
            user=self.user_b,
            role=RoleChoices.ADMIN,
            is_active=True,
        )

        self.context_url = reverse("tenancy:tenant-context")
        self.login_url = reverse("authentication:login")
        self.csrf_url = reverse("authentication:csrf")

    def _authenticate(self, user):
        """Helper to set Bearer token credentials on API client."""
        token = AccessToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_unauthenticated_request_to_tenant_endpoint_returns_401(self):
        """Requests without JWT or session cookie must be rejected with HTTP 401."""
        response = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("detail", response.json())

    def test_public_routes_exempt_from_tenant_headers(self):
        """Public auth and csrf routes must pass without requiring tenant headers."""
        # /api/v1/auth/csrf/
        csrf_response = self.client.get(self.csrf_url)
        self.assertEqual(csrf_response.status_code, status.HTTP_200_OK)

        # /api/v1/auth/login/
        login_response = self.client.post(
            self.login_url,
            {"email": "tenant.a@magebooks.com", "password": "WrongPassword!"},
            format="json",
        )
        # Reaches auth view (fails password), NOT blocked with 400 tenant header missing
        self.assertEqual(login_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_tenant_header_returns_400(self):
        """Authenticated request missing X-Tenant-ID/X-Organization-ID header fails 400."""
        self._authenticate(self.user_a)
        response = self.client.get(self.context_url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json().get("detail"),
            "X-Tenant-ID or X-Organization-ID header is required.",
        )

    def test_malformed_tenant_header_returns_400(self):
        """Header with non-UUID value fails closed with HTTP 400."""
        self._authenticate(self.user_a)
        for bad_header in ["not-a-valid-uuid", "12345", "'; DROP TABLE organizations; --"]:
            response = self.client.get(
                self.context_url,
                HTTP_X_TENANT_ID=bad_header,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json().get("detail"),
                "Invalid tenant ID header format.",
            )

    def test_cross_tenant_header_spoofing_bola_blocked_403(self):
        """MUC-2.1: Attacker (User A) specifies Org Beta's ID in header.

        System must reject the cross-tenant access attempt with HTTP 403 Forbidden.
        """
        self._authenticate(self.user_a)
        response = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_beta.id),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json().get("detail"),
            "You do not have active access to this organization.",
        )

    def test_inactive_membership_blocked_403(self):
        """User whose membership has been deactivated (is_active=False) is blocked."""
        self.membership_b.is_active = False
        self.membership_b.save()

        self._authenticate(self.user_b)
        response = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_beta.id),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json().get("detail"),
            "You do not have active access to this organization.",
        )

    def test_expired_auditor_membership_blocked_403(self):
        """Auditor whose access window has lapsed (access_expires_at < now) is blocked."""
        auditor_user = User.objects.create_user(
            email="expired.auditor@magebooks.com",
            password="SecurePassword123!",
        )
        OrganizationMembership.objects.create(
            organization=self.org_alpha,
            user=auditor_user,
            role=RoleChoices.AUDITOR,
            is_active=True,
            access_expires_at=timezone.now() - timedelta(hours=1),
        )

        self._authenticate(auditor_user)
        response = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json().get("detail"),
            "Auditor access has expired for this organization.",
        )

    def test_active_auditor_read_allowed_write_strictly_blocked_403(self):
        """Auditor read-only containment (Sequence Diagram Line 432).

        Active auditor can GET data, but mutating operations (POST, PUT, PATCH, DELETE)
        are intercepted and blocked with HTTP 403.
        """
        auditor_user = User.objects.create_user(
            email="active.auditor@magebooks.com",
            password="SecurePassword123!",
        )
        OrganizationMembership.objects.create(
            organization=self.org_alpha,
            user=auditor_user,
            role=RoleChoices.AUDITOR,
            is_active=True,
            access_expires_at=timezone.now() + timedelta(days=7),
        )

        self._authenticate(auditor_user)

        # GET request succeeds
        get_response = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
        )
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.json()["tenant_role"], RoleChoices.AUDITOR)

        # POST mutating request is blocked by Guard 4
        post_response = self.client.post(
            self.context_url,
            {"some": "mutation"},
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
            format="json",
        )
        self.assertEqual(post_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            post_response.json().get("detail"),
            "Auditor role has strictly read-only access.",
        )

    def test_dual_header_support_x_organization_id(self):
        """Fallback header X-Organization-ID is properly recognized and processed."""
        self._authenticate(self.user_a)
        response = self.client.get(
            self.context_url,
            HTTP_X_ORGANIZATION_ID=str(self.org_alpha.id),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tenant_id"], str(self.org_alpha.id))
        self.assertEqual(response.json()["tenant_role"], RoleChoices.OWNER)

    def test_authorized_owner_read_and_write_succeeds(self):
        """Legitimate tenant owner can perform both read (GET) and write (POST) operations."""
        self._authenticate(self.user_a)

        get_resp = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
        )
        self.assertEqual(get_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(get_resp.json()["tenant_name"], "Alpha Corp")

        post_resp = self.client.post(
            self.context_url,
            {"payload": "test"},
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
            format="json",
        )
        self.assertEqual(post_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(post_resp.json()["status"], "success")

    def test_rls_session_deallocation_and_thread_local_cleanup(self):
        """MUC-2.2: Context must be cleanly wiped after request completion.

        Thread-local context must be None before and after each request.
        Security response headers must be present on outgoing response.
        """
        self.assertIsNone(get_current_tenant())
        self.assertIsNone(get_current_tenant_id())
        self.assertIsNone(get_current_tenant_role())

        self._authenticate(self.user_a)
        response = self.client.get(
            self.context_url,
            HTTP_X_TENANT_ID=str(self.org_alpha.id),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert security headers applied
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")

        # Assert thread-local context was deallocated in `finally:` block
        self.assertIsNone(get_current_tenant())
        self.assertIsNone(get_current_tenant_id())
        self.assertIsNone(get_current_tenant_role())

    def test_bind_db_session_failure_fails_closed_with_500(self):
        """Fail-Closed Defense: If database session binding fails, request must return HTTP 500."""
        self._authenticate(self.user_a)
        with patch.object(
            TenantSecurityMiddleware,
            "_bind_db_session",
            side_effect=DatabaseError("Simulated PostgreSQL SET LOCAL failure"),
        ):
            response = self.client.get(
                self.context_url,
                HTTP_X_TENANT_ID=str(self.org_alpha.id),
            )
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(
                response.json().get("detail"),
                "Failed to establish secure tenant database context.",
            )

        # Thread-local context must still be cleanly wiped on failure
        self.assertIsNone(get_current_tenant())
        self.assertIsNone(get_current_tenant_id())
        self.assertIsNone(get_current_tenant_role())
