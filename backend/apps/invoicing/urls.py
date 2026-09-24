"""URL configuration for Invoicing domain."""

from django.urls import path

from apps.invoicing.views import (
    InvoiceDetailAPIView,
    InvoiceIssueAPIView,
    InvoiceListCreateAPIView,
)

app_name = "invoicing"

urlpatterns = [
    path("invoices/", InvoiceListCreateAPIView.as_view(), name="invoice-list-create"),
    path("invoices/<uuid:pk>/", InvoiceDetailAPIView.as_view(), name="invoice-detail"),
    path("invoices/<uuid:pk>/issue/", InvoiceIssueAPIView.as_view(), name="invoice-issue"),
]
