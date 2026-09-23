"""Unit tests for Dual-UUID Architecture Base Models and Mixins (Feature 1.5).

Verifies:
1. BaseTenantModel uses sequential UUIDv7 primary keys.
2. PublicShareableMixin uses cryptographically unguessable UUIDv4 tokens.
3. Composite UNIQUE(organization, id) constraint is applied.
4. on_delete=models.PROTECT prevents deletion of parent organization.
5. TenantQuerySet.for_tenant() accurately isolates records by Organization instance or UUID.
"""

import time

from django.db import models
from django.db.models import ProtectedError
from django.test import TestCase

from apps.core.models import BaseTenantModel, PublicShareableMixin
from apps.tenancy.models import Organization


class ConcreteTenantItem(BaseTenantModel, PublicShareableMixin):
    """Concrete model inheriting from BaseTenantModel and PublicShareableMixin for testing."""

    name = models.CharField(max_length=100)

    class Meta(BaseTenantModel.Meta):
        app_label = "core"


class DualUUIDArchitectureTests(TestCase):
    """Test suite validating Dual-UUID internal storage vs public perimeter architecture."""

    def setUp(self):
        self.org_a = Organization.objects.create(
            name="Org Alpha",
            phone="+233241000001",
            email="alpha@example.com",
        )
        self.org_b = Organization.objects.create(
            name="Org Beta",
            phone="+233241000002",
            email="beta@example.com",
        )

    def test_base_tenant_model_uses_uuidv7_primary_key(self):
        """Internal database primary key must strictly be UUIDv7 (timestamp-ordered)."""
        item = ConcreteTenantItem.objects.create(organization=self.org_a, name="Test Item")

        self.assertIsNotNone(item.id)
        self.assertEqual(item.id.version, 7)

    def test_uuidv7_preserves_chronological_ordering(self):
        """Sequential UUIDv7 values must preserve chronological sort order for B-Tree appends."""
        items = []
        for i in range(5):
            items.append(
                ConcreteTenantItem.objects.create(
                    organization=self.org_a,
                    name=f"Chronological Item {i}",
                )
            )
            # Micro-pause to guarantee timestamp delta
            time.sleep(0.002)

        for i in range(len(items) - 1):
            self.assertLess(
                items[i].id,
                items[i + 1].id,
                f"Expected UUIDv7 {items[i].id} to be less than {items[i + 1].id}",
            )

    def test_public_shareable_mixin_uses_uuidv4(self):
        """Public guest tokens must strictly be UUIDv4 to eliminate timestamp leakage."""
        item = ConcreteTenantItem.objects.create(organization=self.org_a, name="Public Document")

        self.assertIsNotNone(item.share_token)
        self.assertEqual(item.share_token.version, 4)

    def test_regenerate_share_token_rotates_to_new_uuidv4(self):
        """Calling regenerate_share_token replaces the token with a fresh UUIDv4."""
        item = ConcreteTenantItem.objects.create(organization=self.org_a, name="Rotating Token")
        initial_token = item.share_token

        new_token = item.regenerate_share_token()

        self.assertNotEqual(initial_token, new_token)
        self.assertEqual(new_token.version, 4)

        # Confirm persisted in DB
        item.refresh_from_db()
        self.assertEqual(item.share_token, new_token)

    def test_composite_unique_constraint_configured(self):
        """BaseTenantModel must define composite UNIQUE(organization, id) constraint."""
        constraints = ConcreteTenantItem._meta.constraints
        unique_tenant_id_constraints = [
            c
            for c in constraints
            if isinstance(c, models.UniqueConstraint) and c.fields == ("organization", "id")
        ]
        self.assertEqual(len(unique_tenant_id_constraints), 1)
        self.assertEqual(
            unique_tenant_id_constraints[0].name,
            "unique_core_concretetenantitem_tenant_id",
        )

    def test_organization_deletion_is_protected(self):
        """Option 2: Deleting an organization with active child records raises ProtectedError."""
        ConcreteTenantItem.objects.create(organization=self.org_a, name="Protected Ledger Item")

        with self.assertRaises(ProtectedError):
            self.org_a.delete()

    def test_tenant_queryset_for_tenant_scoping(self):
        """TenantQuerySet.for_tenant() filters strictly to the specified organization."""
        item_a1 = ConcreteTenantItem.objects.create(organization=self.org_a, name="Item A1")
        item_a2 = ConcreteTenantItem.objects.create(organization=self.org_a, name="Item A2")
        item_b1 = ConcreteTenantItem.objects.create(organization=self.org_b, name="Item B1")

        # Test filtering by Organization instance
        org_a_items = ConcreteTenantItem.objects.for_tenant(self.org_a)
        self.assertEqual(org_a_items.count(), 2)
        self.assertIn(item_a1, org_a_items)
        self.assertIn(item_a2, org_a_items)
        self.assertNotIn(item_b1, org_a_items)

        # Test filtering by tenant UUID
        org_b_items = ConcreteTenantItem.objects.for_tenant(self.org_b.id)
        self.assertEqual(org_b_items.count(), 1)
        self.assertIn(item_b1, org_b_items)
        self.assertNotIn(item_a1, org_b_items)
