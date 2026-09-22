"""Views for JWT authentication and session cookie management."""

from django.conf import settings
from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.serializers import (
    LoginSerializer,
    UserResponseSerializer,
    UserUpdateSerializer,
)


def set_jwt_cookies(
    response: Response,
    access_token: str,
    refresh_token: str | None = None,
) -> None:
    """Attach JWT access and refresh tokens to response as HttpOnly, SameSite=Strict cookies."""
    cookie_secure = getattr(settings, "JWT_COOKIE_SECURE", not settings.DEBUG)
    cookie_samesite = getattr(settings, "JWT_COOKIE_SAMESITE", "Strict")
    access_cookie_name = getattr(settings, "JWT_AUTH_COOKIE", "access_token")
    refresh_cookie_name = getattr(settings, "JWT_REFRESH_COOKIE", "refresh_token")

    simple_jwt = getattr(settings, "SIMPLE_JWT", {})
    access_lifetime = simple_jwt.get("ACCESS_TOKEN_LIFETIME")
    refresh_lifetime = simple_jwt.get("REFRESH_TOKEN_LIFETIME")

    access_max_age = int(access_lifetime.total_seconds()) if access_lifetime else 900

    response.set_cookie(
        key=access_cookie_name,
        value=access_token,
        max_age=access_max_age,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        path="/",
    )

    if refresh_token is not None:
        refresh_max_age = int(refresh_lifetime.total_seconds()) if refresh_lifetime else 604800

        response.set_cookie(
            key=refresh_cookie_name,
            value=refresh_token,
            max_age=refresh_max_age,
            httponly=True,
            secure=cookie_secure,
            samesite=cookie_samesite,
            path="/api/v1/auth/",
        )


def delete_jwt_cookies(response: Response) -> None:
    """Clear JWT cookies from client session."""
    access_cookie_name = getattr(settings, "JWT_AUTH_COOKIE", "access_token")
    refresh_cookie_name = getattr(settings, "JWT_REFRESH_COOKIE", "refresh_token")

    response.delete_cookie(access_cookie_name, path="/")
    response.delete_cookie(refresh_cookie_name, path="/api/v1/auth/")


class LoginView(APIView):
    """Authenticate user with email/password and set HttpOnly JWT session cookies."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_401_UNAUTHORIZED)

        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)

        user_data = UserResponseSerializer(user).data
        csrf_token = get_token(request)
        response = Response(
            {
                "user": user_data,
                "csrf_token": csrf_token,
                "detail": "Login successful.",
            },
            status=status.HTTP_200_OK,
        )

        set_jwt_cookies(response, access_token=access_token, refresh_token=refresh_token)
        return response


class CSRFTokenView(APIView):
    """Provide a fresh CSRF token and cookie for single-page applications."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        csrf_token = get_token(request)
        return Response({"csrf_token": csrf_token}, status=status.HTTP_200_OK)


class RefreshTokenView(APIView):
    """Refresh JWT access token using the HttpOnly refresh token cookie."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        refresh_cookie_name = getattr(settings, "JWT_REFRESH_COOKIE", "refresh_token")
        raw_refresh = request.COOKIES.get(refresh_cookie_name) or request.data.get("refresh")

        if not raw_refresh:
            return Response(
                {"detail": "Refresh token cookie missing."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(raw_refresh)
            new_access_token = str(refresh.access_token)
        except (TokenError, InvalidToken) as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        response = Response(
            {"detail": "Token refreshed successfully."},
            status=status.HTTP_200_OK,
        )
        set_jwt_cookies(response, access_token=new_access_token)
        return response


class LogoutView(APIView):
    """Clear JWT cookies and end user session."""

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        response = Response(
            {"detail": "Successfully logged out."},
            status=status.HTTP_200_OK,
        )
        delete_jwt_cookies(response)
        return response


class CurrentUserView(APIView):
    """Return profile details for currently authenticated user."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        serializer = UserResponseSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request: Request) -> Response:
        """Update mutable profile details for currently authenticated user."""
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserResponseSerializer(request.user).data, status=status.HTTP_200_OK)
