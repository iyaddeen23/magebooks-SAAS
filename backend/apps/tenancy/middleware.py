"""5-Stage TenantSecurityMiddleware for Mage Books SAAS multi-tenant architecture.

Enforces:
1. Public route exemption & JWT authentication resolution.
2. X-Tenant-ID / X-Organization-ID header extraction & UUID validation.
3. Active organization membership verification (MUC-2.1: Cross-Tenant Header Spoofing BOLA).
4. Ephemeral auditor expiration check & read-only write operation blocking (Seq. Diagram Line 432).
5. PostgreSQL RLS session binding (SET LOCAL app.current_tenant_id) & leak defense (MUC-2.2).
"""

import logging
import threading
import uuid
from typing import Any
from uuid import UUID

from django.db import DatabaseError, connection, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.authentication.authentication import JWTCookieAuthentication
from apps.tenancy.models import Organization, OrganizationMembership, RoleChoices

logger = logging.getLogger(__name__)

# Thread-local storage for request-scoped tenant context
_thread_locals = threading.local()


def get_current_tenant() -> Organization | None:
    """Returns the active Organization tenant for the current request thread."""
    return getattr(_thread_locals, "tenant", None)


def get_current_tenant_id() -> UUID | None:
    """Returns the UUID of the active Organization tenant for the current request thread."""
    return getattr(_thread_locals, "tenant_id", None)


def get_current_tenant_role() -> str | None:
    """Returns the RBAC role of the authenticated user in the current tenant."""
    return getattr(_thread_locals, "tenant_role", None)


def set_current_tenant(tenant: Organization, role: str | None = None) -> None:
    """Binds tenant context to thread-local storage."""
    _thread_locals.tenant = tenant
    _thread_locals.tenant_id = tenant.id
    _thread_locals.tenant_role = role


def clear_current_tenant() -> None:
    """Deallocates tenant context from thread-local storage."""
    _thread_locals.tenant = None
    _thread_locals.tenant_id = None
    _thread_locals.tenant_role = None


class TenantSecurityMiddleware:
    """5-Stage Defensive Security Pipeline executing multi-tenant validation guards."""

    # URL prefixes exempt from tenant-header validation
    EXEMPT_PATH_PREFIXES = (
        "/api/v1/auth/",
        "/api/v1/payments/webhooks/",
        "/admin/",
        "/health/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response: Any):
        self.get_response = get_response
        self.jwt_authenticator = JWTCookieAuthentication()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # ------------------------------------------------------------------
        # GUARD 1: Route Exemption & Authentication Resolution
        # ------------------------------------------------------------------
        if self._is_exempt_path(request.path):
            return self.get_response(request)

        # Resolve user identity if not already authenticated by earlier middleware
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            auth_user = self._resolve_jwt_user(request)
            if auth_user:
                request.user = auth_user
            else:
                return JsonResponse(
                    {"detail": "Authentication credentials were not provided."},
                    status=401,
                )

        # ------------------------------------------------------------------
        # GUARD 2: Header Parsing & UUID Validation (Dual Header Support)
        # ------------------------------------------------------------------
        raw_tenant_id = self._extract_tenant_header(request)
        if not raw_tenant_id:
            return JsonResponse(
                {"detail": "X-Tenant-ID or X-Organization-ID header is required."},
                status=400,
            )

        try:
            tenant_uuid = uuid.UUID(str(raw_tenant_id).strip())
        except (ValueError, TypeError, AttributeError):
            return JsonResponse(
                {"detail": "Invalid tenant ID header format."},
                status=400,
            )

        # ------------------------------------------------------------------
        # GUARD 3: Organization Active Membership Verification (MUC-2.1)
        # ------------------------------------------------------------------
        membership = (
            OrganizationMembership.objects.filter(
                organization_id=tenant_uuid,
                user=request.user,
                is_active=True,
            )
            .select_related("organization")
            .first()
        )

        if not membership:
            logger.warning(
                "Cross-tenant access attempt (MUC-2.1): user=%s requested tenant=%s",
                request.user.id,
                tenant_uuid,
            )
            return JsonResponse(
                {"detail": "You do not have active access to this organization."},
                status=403,
            )

        # Inject validated tenant context into request object
        request.tenant = membership.organization
        request.tenant_role = membership.role
        request.membership = membership

        # ------------------------------------------------------------------
        # GUARD 4: Auditor Expiration & Read-Only Operation Containment
        # ------------------------------------------------------------------
        if membership.role == RoleChoices.AUDITOR:
            # Check ephemeral expiration
            if membership.is_expired():
                logger.warning(
                    "Expired auditor access attempt: user=%s org=%s",
                    request.user.id,
                    tenant_uuid,
                )
                return JsonResponse(
                    {"detail": "Auditor access has expired for this organization."},
                    status=403,
                )

            # Enforce read-only containment (block mutating write methods)
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                logger.warning(
                    "Auditor write operation blocked (Seq. Diagram 432): user=%s method=%s",
                    request.user.id,
                    request.method,
                )
                return JsonResponse(
                    {"detail": "Auditor role has strictly read-only access."},
                    status=403,
                )

        # ------------------------------------------------------------------
        # GUARD 5: PostgreSQL RLS Session Binding & Leak Defense (MUC-2.2)
        # ------------------------------------------------------------------
        set_current_tenant(membership.organization, membership.role)

        try:
            with transaction.atomic():
                self._bind_db_session(tenant_uuid)
                response = self.get_response(request)
            self._apply_security_headers(response)
            return response
        except DatabaseError as e:
            logger.error("Failed to establish secure tenant database context: %s", e)
            return JsonResponse(
                {"detail": "Failed to establish secure tenant database context."},
                status=500,
            )
        finally:
            self._deallocate_db_session()
            clear_current_tenant()

    def _is_exempt_path(self, path: str) -> bool:
        """Determines if the requested path is exempt from tenant isolation."""
        return any(path.startswith(prefix) for prefix in self.EXEMPT_PATH_PREFIXES)

    def _extract_tenant_header(self, request: HttpRequest) -> str | None:
        """Extracts X-Tenant-ID or fallback X-Organization-ID header."""
        return (
            request.headers.get("X-Tenant-ID")
            or request.headers.get("X-Organization-ID")
            or request.META.get("HTTP_X_TENANT_ID")
            or request.META.get("HTTP_X_ORGANIZATION_ID")
        )

    def _resolve_jwt_user(self, request: HttpRequest) -> Any:
        """Extracts and verifies JWT token from cookies or Authorization header."""
        try:
            auth_result = self.jwt_authenticator.authenticate(request)
            if auth_result is not None:
                user, _ = auth_result
                return user
        except (InvalidToken, TokenError, Exception):
            pass
        return None

    def _bind_db_session(self, tenant_id: UUID) -> None:
        """Binds tenant_id to PostgreSQL RLS session parameter using SET LOCAL.

        Fails closed by raising DatabaseError if session configuration fails.
        """
        if connection.vendor == "postgresql":
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SET LOCAL app.current_tenant_id = %s;",
                        [str(tenant_id)],
                    )
            except Exception as e:
                logger.error("Failed to execute SET LOCAL app.current_tenant_id: %s", e)
                raise DatabaseError("Failed to establish secure tenant database context.") from e

    def _deallocate_db_session(self) -> None:
        """Resets session variable to guarantee clean connection return to pool (MUC-2.2)."""
        if connection.vendor == "postgresql":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("RESET app.current_tenant_id;")
            except Exception:
                pass

    def _apply_security_headers(self, response: HttpResponse) -> None:
        """Applies baseline HTTP security headers (Seq. Diagram Step 18)."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
