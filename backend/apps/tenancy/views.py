"""Views for the Tenancy application."""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class TenantContextTestView(APIView):
    """Test verification endpoint that returns the resolved tenant context.

    Protected by TenantSecurityMiddleware and IsAuthenticated.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        """Returns the active tenant ID, name, and user's role within the tenant."""
        tenant = getattr(request, "tenant", None)
        tenant_role = getattr(request, "tenant_role", None)

        if not tenant:
            return Response(
                {"detail": "No tenant context resolved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "tenant_role": tenant_role,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        """Mutating endpoint for testing auditor write containment and authorized writes."""
        tenant = getattr(request, "tenant", None)
        return Response(
            {
                "status": "success",
                "tenant_id": str(tenant.id) if tenant else None,
            },
            status=status.HTTP_201_CREATED,
        )
