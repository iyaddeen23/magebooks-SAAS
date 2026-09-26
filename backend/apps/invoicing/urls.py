"""URL configuration for Invoicing domain."""

from django.urls import path

from apps.invoicing.views import (
    InvoiceDetailAPIView,
    InvoiceDownloadAPIView,
    InvoiceGeneratePDFAPIView,
    InvoiceIssueAPIView,
    InvoiceListCreateAPIView,
)

app_name = "invoicing"

urlpatterns = [
    path("invoices/", InvoiceListCreateAPIView.as_view(), name="invoice-list-create"),
    path("invoices/<uuid:pk>/", InvoiceDetailAPIView.as_view(), name="invoice-detail"),
    path("invoices/<uuid:pk>/issue/", InvoiceIssueAPIView.as_view(), name="invoice-issue"),
    path(
        "invoices/<uuid:pk>/download/",
        InvoiceDownloadAPIView.as_view(),
        name="invoice-download",
    ),
    path(
        "invoices/<uuid:pk>/generate-pdf/",
        InvoiceGeneratePDFAPIView.as_view(),
        name="invoice-generate-pdf",
    ),
]
