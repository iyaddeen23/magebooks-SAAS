"""Invoicing REST API Views.

Provides:
1. InvoiceListCreateAPIView: GET paginated list, POST atomic creation with Act 1151 GL posting.
2. InvoiceDetailAPIView: GET invoice detail with customer legal snapshot and lines.
3. InvoiceIssueAPIView: POST transition draft invoice to PENDING_GRA with GL posting.
"""

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.invoicing.models import Invoice
from apps.invoicing.serializers import (
    InvoiceCreateSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
)
from apps.invoicing.services import InvoicingService
from apps.tenancy.middleware import get_current_tenant, get_current_tenant_role
from apps.tenancy.models import Organization, RoleChoices


def resolve_request_tenant(request: Request) -> Organization | None:
    """Helper to extract active tenant organization from request or thread context."""
    tenant = getattr(request, "tenant", None)
    if not tenant:
        tenant = getattr(request, "organization", None)
    if not tenant:
        tenant = get_current_tenant()
    return tenant


class InvoiceListCreateAPIView(APIView):
    """List tenant invoices or compile and issue a new tax invoice."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Retrieves tenant-scoped list of invoices with optional filtering."""
        tenant = resolve_request_tenant(request)
        if not tenant:
            return Response(
                {"detail": "No active tenant organization context found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = (
            Invoice.objects.filter(organization=tenant)
            .select_related("customer")
            .order_by("-issue_date", "-created_at")
        )

        # Filters
        invoice_status = request.query_params.get("status")
        if invoice_status:
            queryset = queryset.filter(status=invoice_status)

        customer_id = request.query_params.get("customer_id")
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)

        search_query = request.query_params.get("search")
        if search_query:
            from django.db.models import Q

            queryset = queryset.filter(
                Q(invoice_number__icontains=search_query)
                | Q(payment_reference__icontains=search_query)
                | Q(customer_name__icontains=search_query)
            )

        serializer = InvoiceListSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request: Request) -> Response:
        """Compiles, calculates Act 1151 taxes, freezes legal snapshot, and posts invoice to GL."""
        tenant = resolve_request_tenant(request)
        if not tenant:
            return Response(
                {"detail": "No active tenant organization context found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Role check: Block Auditor from write operations
        role = getattr(request, "tenant_role", None) or get_current_tenant_role()
        if role == RoleChoices.AUDITOR:
            return Response(
                {"detail": "Auditor role has strictly read-only access."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InvoiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            invoice = InvoicingService.create_and_post_invoice(
                organization=tenant,
                user=request.user,
                data=serializer.validated_data,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = InvoiceDetailSerializer(invoice)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class InvoiceDetailAPIView(APIView):
    """Retrieve complete invoice detail including line items and customer snapshot."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: Any) -> Response:
        """Retrieves single invoice instance by UUID."""
        tenant = resolve_request_tenant(request)
        if not tenant:
            return Response(
                {"detail": "No active tenant organization context found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invoice = (
            Invoice.objects.filter(id=pk, organization=tenant)
            .select_related("customer")
            .prefetch_related("lines__account")
            .first()
        )
        if not invoice:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = InvoiceDetailSerializer(invoice)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InvoiceIssueAPIView(APIView):
    """Transitions a draft invoice to PENDING_GRA and posts balanced lines to General Ledger."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: Any) -> Response:
        """Issues an existing draft invoice."""
        tenant = resolve_request_tenant(request)
        if not tenant:
            return Response(
                {"detail": "No active tenant organization context found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        role = getattr(request, "tenant_role", None) or get_current_tenant_role()
        if role == RoleChoices.AUDITOR:
            return Response(
                {"detail": "Auditor role has strictly read-only access."},
                status=status.HTTP_403_FORBIDDEN,
            )

        invoice = Invoice.objects.filter(id=pk, organization=tenant).first()
        if not invoice:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            issued_invoice = InvoicingService.issue_draft_invoice(
                invoice=invoice,
                user=request.user,
            )
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)

        serializer = InvoiceDetailSerializer(issued_invoice)
        return Response(serializer.data, status=status.HTTP_200_OK)
