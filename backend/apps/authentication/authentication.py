from typing import Optional, Tuple

from django.conf import settings
from rest_framework.request import Request
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import Token

from apps.authentication.models import CustomUser


class JWTCookieAuthentication(JWTAuthentication):
    """Authenticates requests using JWT from either HttpOnly cookies or Authorization header.

    Priority:
    1. 'access_token' cookie (secure session for web apps).
    2. 'Authorization: Bearer <token>' header (for mobile / external clients).
    """

    def authenticate(self, request: Request) -> Optional[Tuple[CustomUser, Token]]:
        cookie_name = getattr(settings, "JWT_AUTH_COOKIE", "access_token")
        raw_token = request.COOKIES.get(cookie_name)

        if raw_token:
            try:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token
            except (InvalidToken, TokenError):
                return None

        # Fallback to standard Authorization: Bearer <token>
        return super().authenticate(request)
