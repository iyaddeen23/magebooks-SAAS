"""Security threat modeling and negative abuse tests for Authentication (Sprint 1)."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


class AuthenticationSecurityThreatTests(APITestCase):
    """Abuse and negative threat tests for JWT and session cookie authentication."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="security.test@magebooks.com",
            password="SecureTestPassword123!",
            first_name="Security",
            last_name="Tester",
        )
        self.login_url = reverse("authentication:login")
        self.me_url = reverse("authentication:me")
        self.refresh_url = reverse("authentication:refresh")

    def test_tampered_jwt_signature_rejected_with_401(self):
        """Attacker modifies JWT payload/signature to impersonate another user.

        System must reject tampered token with HTTP 401 Unauthorized.
        """
        token = AccessToken.for_user(self.user)
        token_str = str(token)

        # Tamper with the signature portion (last part of JWT)
        parts = token_str.split(".")
        tampered_sig = parts[2][:-4] + "XXXX"
        tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tampered_token}")
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("code", response.data)
        self.assertEqual(response.data["code"], "token_not_valid")

    def test_forged_user_id_claim_rejected(self):
        """Attacker crafts a token using an invalid secret or non-existent user ID."""
        invalid_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkZvcmdlZCIsInVzZXJfaWQiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAifQ."
            "invalid_signature_mock_hash_12345"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {invalid_token}")
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_brute_force_password_fails_closed_without_user_enumeration(self):
        """Attacker sends repeated invalid credentials; server responds with generic 401."""
        for password_attempt in ["WrongPass1!", "WrongPass2!", "WrongPass3!"]:
            response = self.client.post(
                self.login_url,
                {
                    "email": self.user.email,
                    "password": password_attempt,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertIn("detail", response.data)
            # Must not reveal whether email exists vs password wrong
            self.assertIn(
                "Unable to log in with provided credentials.",
                str(response.data.get("detail", "")),
            )

    def test_login_response_never_leaks_password_hash_or_secrets(self):
        """API response must never expose password hash, salts, or two_factor_secret."""
        response = self.client.post(
            self.login_url,
            {
                "email": "security.test@magebooks.com",
                "password": "SecureTestPassword123!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_str = str(response.content)
        self.assertNotIn("password_hash", response_str)
        self.assertNotIn("pbkdf2", response_str.lower())
        self.assertNotIn("two_factor_secret", response_str)
        self.assertNotIn(self.user.password, response_str)

    def test_cookie_mutating_request_without_csrf_strictly_blocked_403(self):
        """CSRF barrier test: Mutating profile request with session cookie but no CSRF fails 403."""
        login_response = self.client.post(
            self.login_url,
            {
                "email": "security.test@magebooks.com",
                "password": "SecureTestPassword123!",
            },
            format="json",
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)

        # Mutating request with enforce_csrf_checks=True and without X-CSRFToken
        csrf_enforced_client = self.client_class(enforce_csrf_checks=True)
        # Copy auth cookies from login
        for cookie_name in ["access_token", "csrftoken"]:
            if cookie_name in login_response.cookies:
                csrf_enforced_client.cookies[cookie_name] = login_response.cookies[cookie_name]

        patch_response = csrf_enforced_client.patch(
            self.me_url,
            {"first_name": "HackedName"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("detail", patch_response.data)

        # Refresh from DB to assert first_name was NOT modified
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Security")
