"""Smoke and configuration tests for Mage Books SAAS foundation."""

from django.conf import settings
from django.test import SimpleTestCase


class CoreBootTestCase(SimpleTestCase):
    """Verifies that the Django configuration initializes cleanly for testing."""

    def test_is_testing_flag_is_active(self):
        """Asserts that IS_TESTING evaluates to True in test runner context."""
        self.assertTrue(settings.IS_TESTING)

    def test_database_is_sqlite_in_memory(self):
        """Asserts that automated tests run exclusively against in-memory SQLite."""
        db_config = settings.DATABASES["default"]
        self.assertEqual(db_config["ENGINE"], "django.db.backends.sqlite3")
        db_name = db_config["NAME"]
        self.assertTrue(
            db_name == ":memory:"
            or (
                isinstance(db_name, str)
                and db_name.startswith("file:")
                and "mode=memory" in db_name
            ),
            f"Expected in-memory SQLite database, got {db_config['NAME']}",
        )

    def test_all_domain_apps_registered(self):
        """Asserts that all nine core domain apps are registered in INSTALLED_APPS."""
        expected_apps = [
            "apps.core",
            "apps.authentication",
            "apps.tenancy",
            "apps.ledger",
            "apps.tax",
            "apps.invoicing",
            "apps.payments",
            "apps.payroll",
            "apps.audit",
        ]
        for app in expected_apps:
            self.assertIn(app, settings.INSTALLED_APPS)

    def test_timezone_is_accra(self):
        """Asserts that the application timezone is set to Ghana (Africa/Accra)."""
        self.assertEqual(settings.TIME_ZONE, "Africa/Accra")

    def test_rest_framework_configured(self):
        """Asserts that Django REST Framework is configured with JSON parser/renderer."""
        self.assertIn("rest_framework", settings.INSTALLED_APPS)
        self.assertIn(
            "rest_framework.renderers.JSONRenderer",
            settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"],
        )
