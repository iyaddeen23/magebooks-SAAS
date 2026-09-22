from typing import Optional, Tuple

from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import Token

from apps.authentication.models import CustomUser


class JWTCookieAuthentication(JWTAuthentication):
    """Authenticates requests using JWT from either HttpOnly cookies or Authorization header.

    Priority:
    1. 'access_token' cookie (secure session for web apps).
       - Enforces Django CSRF validation on mutating HTTP methods.
    2. 'Authorization: Bearer <token>' header (for mobile / external clients).
       - CSRF-exempt since browsers do not attach custom headers cross-site.
    """

    def enforce_csrf(self, request: Request) -> None:
        """Enforce Django CSRF validation for cookie-authenticated requests."""

        def dummy_get_response(request):
            return None

        check = CSRFCheck(dummy_get_response)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")

    def authenticate(self, request: Request) -> Optional[Tuple[CustomUser, Token]]:
        cookie_name = getattr(settings, "JWT_AUTH_COOKIE", "access_token")
        raw_token = request.COOKIES.get(cookie_name)

        if raw_token:
            try:
                validated_token = self.get_validated_token(raw_token)
                # Enforce CSRF protection on cookie-based sessions (mirrors SessionAuthentication)
                self.enforce_csrf(request)
                return self.get_user(validated_token), validated_token
            except (InvalidToken, TokenError):
                # Fall through to inspect the Authorization header if cookie is expired/invalid
                pass

        # Fallback to standard Authorization: Bearer <token> (CSRF exempt)
        return super().authenticate(request)
