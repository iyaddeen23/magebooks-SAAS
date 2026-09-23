"""Unit tests for TenantSecurityMiddleware helper functions and thread-local context."""

from django.test import TestCase

from apps.tenancy.middleware import (
    clear_current_tenant,
    get_current_tenant,
    get_current_tenant_id,
    get_current_tenant_role,
    set_current_tenant,
)
from apps.tenancy.models import Organization, RoleChoices


class TenantMiddlewareUnitTests(TestCase):
    """Verifies thread-local binding, getter functions, and lifecycle cleanup."""

    def setUp(self):
        clear_current_tenant()
        self.org = Organization.objects.create(
            name="Unit Test Org",
            phone="+233241112233",
            email="test@unittestorg.com",
        )

    def tearDown(self):
        clear_current_tenant()

    def test_thread_local_initial_state_is_none(self):
        """Thread-local context must default to None when unset."""
        self.assertIsNone(get_current_tenant())
        self.assertIsNone(get_current_tenant_id())
        self.assertIsNone(get_current_tenant_role())

    def test_thread_local_set_and_get(self):
        """set_current_tenant binds the active organization and role."""
        set_current_tenant(self.org, RoleChoices.ADMIN)

        self.assertEqual(get_current_tenant(), self.org)
        self.assertEqual(get_current_tenant_id(), self.org.id)
        self.assertEqual(get_current_tenant_role(), RoleChoices.ADMIN)

    def test_thread_local_clear(self):
        """clear_current_tenant thoroughly deallocates all bound context."""
        set_current_tenant(self.org, RoleChoices.OWNER)
        self.assertIsNotNone(get_current_tenant())

        clear_current_tenant()
        self.assertIsNone(get_current_tenant())
        self.assertIsNone(get_current_tenant_id())
        self.assertIsNone(get_current_tenant_role())
