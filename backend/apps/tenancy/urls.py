"""URL routing for Tenancy endpoints."""

from django.urls import path

from apps.tenancy.views import TenantContextTestView

app_name = "tenancy"

urlpatterns = [
    path("context/", TenantContextTestView.as_view(), name="tenant-context"),
]
