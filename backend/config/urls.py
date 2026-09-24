"""Mage Books SAAS Root URL Configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("apps.authentication.urls")),
    path("api/v1/tenancy/", include("apps.tenancy.urls")),
    path("api/v1/", include("apps.invoicing.urls")),
]
