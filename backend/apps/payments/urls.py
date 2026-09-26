"""URL Configuration for Payment Webhooks and Aggregators."""

from django.urls import path

from apps.payments.views import (
    HubtelWebhookView,
    MomoWebhookView,
    PaystackWebhookView,
)

app_name = "payments"

urlpatterns = [
    path("webhooks/momo/", MomoWebhookView.as_view(), name="momo-webhook"),
    path("webhooks/paystack/", PaystackWebhookView.as_view(), name="paystack-webhook"),
    path("webhooks/hubtel/", HubtelWebhookView.as_view(), name="hubtel-webhook"),
]
