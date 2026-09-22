"""URL patterns for authentication endpoints."""

from django.urls import path

from apps.authentication.views import (
    CurrentUserView,
    LoginView,
    LogoutView,
    RefreshTokenView,
)

app_name = "authentication"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("refresh/", RefreshTokenView.as_view(), name="refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", CurrentUserView.as_view(), name="me"),
]
