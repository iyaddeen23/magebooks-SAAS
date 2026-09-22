"""Tests for Tenancy and RBAC models (Feature 1.3)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.tenancy.models import (
    ExperienceModeChoices,
    Organization,
    OrganizationMembership,
    RoleChoices,
    TaxSchemeChoices,
)

User = get_user_model()


class TenancyModelTests(TestCase):
    """Unit and integration tests for Organization and OrganizationMembership."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="founder@example.com",
            password="FounderPassword123!",
            first_name="Kofi",
            last_name="Mensah",
        )
        self.other_user = User.objects.create_user(
            email="accountant@example.com",
            password="AccountantPassword123!",
            first_name="Kwame",
            last_name="Asante",
        )

    def test_organization_created_with_uuid7_primary_key(self):
        """Organization primary key must be UUIDv7 adhering to Dual-UUID architecture."""
        org = Organization.objects.create(
            name="Accra Wholesale Supplies Ltd",
            phone="+233241234567",
            email="info@accrawholesale.com",
        )
        self.assertIsNotNone(org.id)
        # Verify version 7 timestamp-ordered UUID
        self.assertEqual(org.id.version, 7)
        self.assertEqual(str(org), "Accra Wholesale Supplies Ltd")

    def test_organization_act1151_tax_fields_and_experience_mode(self):
        """Assert statutory Act 1151 fields (GHS 750k threshold, unified standard 20%, etc)."""
        org = Organization.objects.create(
            name="Tema Logistics Enterprise",
            phone="+233201234567",
            email="contact@temalogistics.com",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
            default_experience_mode=ExperienceModeChoices.FULL,
        )
        self.assertTrue(org.vat_registered)
        self.assertEqual(org.vat_scheme, "STANDARD")
        self.assertEqual(org.default_experience_mode, "full")

        # Test EXEMPT and ZERO_RATED schemes under Act 1151
        org.vat_scheme = TaxSchemeChoices.EXEMPT
        org.save()
        self.assertEqual(org.vat_scheme, "EXEMPT")

        org.vat_scheme = TaxSchemeChoices.ZERO_RATED
        org.save()
        self.assertEqual(org.vat_scheme, "ZERO_RATED")

    def test_tin_and_ghana_card_validators(self):
        """Test Ghanaian GRA TIN and Director Ghana Card regex validators."""
        org = Organization(
            name="Cape Coast Fisheries",
            phone="+233240001122",
            email="info@capecoastfish.com",
            business_tin="INVALID_TIN_123",
            ghana_card_number="NOT_A_GHANA_CARD",
        )
        with self.assertRaises(ValidationError) as ctx:
            org.full_clean()

        errors = ctx.exception.message_dict
        self.assertIn("business_tin", errors)
        self.assertIn("ghana_card_number", errors)

        # Correct Ghanaian identifiers
        org.business_tin = "C0001234567"
        org.ghana_card_number = "GHA-123456789-0"
        # full_clean should succeed with zero errors
        org.full_clean()
        org.save()
        self.assertEqual(org.business_tin, "C0001234567")
        self.assertEqual(org.ghana_card_number, "GHA-123456789-0")

    def test_membership_all_five_rbac_roles_with_uuid7(self):
        """Verify creating memberships for all 5 discrete RBAC roles using UUIDv7."""
        org = Organization.objects.create(
            name="Kumasi Distribution Hub",
            phone="+233501234567",
            email="hub@kumasi.com",
        )

        roles = [
            RoleChoices.OWNER,
            RoleChoices.ADMIN,
            RoleChoices.ACCOUNTANT,
            RoleChoices.BOOKKEEPER,
            RoleChoices.AUDITOR,
        ]

        for role in roles:
            user = User.objects.create_user(
                email=f"user_{role.lower()}@magebooks.com",
                password="TestPassword123!",
            )
            membership = OrganizationMembership.objects.create(
                organization=org,
                user=user,
                role=role,
            )
            self.assertEqual(membership.id.version, 7)
            self.assertEqual(membership.role, role)
            self.assertTrue(membership.is_active)

    def test_unique_organization_user_constraint(self):
        """A user can only have one membership per organization."""
        org = Organization.objects.create(
            name="Takoradi Shipping Co",
            phone="+233312000000",
            email="shipping@takoradi.com",
        )
        OrganizationMembership.objects.create(
            organization=org,
            user=self.user,
            role=RoleChoices.OWNER,
        )

        with self.assertRaises(ValidationError) as ctx:
            OrganizationMembership.objects.create(
                organization=org,
                user=self.user,
                role=RoleChoices.ADMIN,
            )
        self.assertIn("already exists", str(ctx.exception))

    def test_organization_owner_property(self):
        """Organization.owner returns the user with the active OWNER membership."""
        org = Organization.objects.create(
            name="Sunyani Agro Ventures",
            phone="+233352000000",
            email="agro@sunyani.com",
        )
        self.assertIsNone(org.owner)

        OrganizationMembership.objects.create(
            organization=org,
            user=self.user,
            role=RoleChoices.OWNER,
        )
        self.assertEqual(org.owner, self.user)

    def test_auditor_access_expiration_and_active_manager_filter(self):
        """Auditor access expiration check and filtering from active() manager query."""
        org = Organization.objects.create(
            name="Tamale Grains Ltd",
            phone="+233372000000",
            email="grains@tamale.com",
        )
        now = timezone.now()

        # Active auditor with future expiration
        active_auditor = OrganizationMembership.objects.create(
            organization=org,
            user=self.user,
            role=RoleChoices.AUDITOR,
            access_expires_at=now + timedelta(days=30),
        )
        self.assertFalse(active_auditor.is_expired())

        # Expired auditor with past expiration
        expired_user = User.objects.create_user(
            email="expired.auditor@deloitte.com",
            password="AuditorPass123!",
        )
        expired_auditor = OrganizationMembership.objects.create(
            organization=org,
            user=expired_user,
            role=RoleChoices.AUDITOR,
            access_expires_at=now - timedelta(hours=1),
        )
        self.assertTrue(expired_auditor.is_expired())

        # Active queryset must include active auditor and exclude expired auditor
        active_memberships = OrganizationMembership.objects.active().filter(organization=org)
        self.assertIn(active_auditor, active_memberships)
        self.assertNotIn(expired_auditor, active_memberships)

    def test_owner_role_cannot_have_access_expiration(self):
        """Domain validation: Owner role cannot have an ephemeral access expiration date."""
        org = Organization.objects.create(
            name="Ho Tech Innovations",
            phone="+233362000000",
            email="tech@ho.com",
        )
        membership = OrganizationMembership(
            organization=org,
            user=self.user,
            role=RoleChoices.OWNER,
            access_expires_at=timezone.now() + timedelta(days=90),
        )
        # full_clean called on save() must block persisting invalid owner state
        with self.assertRaises(ValidationError) as ctx:
            membership.save()

        self.assertIn("access_expires_at", ctx.exception.message_dict)

        # objects.create() must also be blocked
        with self.assertRaises(ValidationError) as ctx:
            OrganizationMembership.objects.create(
                organization=org,
                user=self.other_user,
                role=RoleChoices.OWNER,
                access_expires_at=timezone.now() + timedelta(days=30),
            )
        self.assertIn("access_expires_at", ctx.exception.message_dict)

    def test_owner_demotion_prevented_by_immutability_guard(self):
        """Owner Immutability: Attempting to demote an existing OWNER raises ValidationError."""
        org = Organization.objects.create(
            name="Sunyani Solar Ltd",
            phone="+233352111222",
            email="solar@sunyani.com",
        )
        membership = OrganizationMembership.objects.create(
            organization=org,
            user=self.user,
            role=RoleChoices.OWNER,
        )

        # Attempt to demote OWNER to ADMIN
        membership.role = RoleChoices.ADMIN
        with self.assertRaises(ValidationError) as ctx:
            membership.save()

        self.assertIn("role", ctx.exception.message_dict)
        self.assertEqual(
            ctx.exception.message_dict["role"],
            ["Organization Owner cannot be demoted to another role."],
        )

        # Attempt to demote OWNER to BOOKKEEPER
        membership.role = RoleChoices.BOOKKEEPER
        with self.assertRaises(ValidationError) as ctx:
            membership.save()

        self.assertIn("role", ctx.exception.message_dict)

    def test_owner_deactivation_prevented_by_immutability_guard(self):
        """Owner Immutability: Attempting to deactivate an existing OWNER raises ValidationError."""
        org = Organization.objects.create(
            name="Wa Water Works",
            phone="+233392000111",
            email="water@wa.com",
        )
        membership = OrganizationMembership.objects.create(
            organization=org,
            user=self.user,
            role=RoleChoices.OWNER,
        )

        membership.is_active = False
        with self.assertRaises(ValidationError) as ctx:
            membership.save()

        self.assertIn("is_active", ctx.exception.message_dict)
        self.assertEqual(
            ctx.exception.message_dict["is_active"],
            ["Organization Owner cannot be deactivated."],
        )

    def test_cascade_deletion(self):
        """Deleting an organization or a user cascades to delete their memberships."""
        org = Organization.objects.create(
            name="Koforidua Florals",
            phone="+233342000000",
            email="flowers@koforidua.com",
        )
        membership = OrganizationMembership.objects.create(
            organization=org,
            user=self.user,
            role=RoleChoices.OWNER,
        )
        membership_id = membership.id

        # Delete organization -> cascades to membership
        org.delete()
        self.assertFalse(OrganizationMembership.objects.filter(id=membership_id).exists())

    def test_membership_queryset_scoping_helpers(self):
        """Verify for_user and for_organization query helpers."""
        org1 = Organization.objects.create(name="Org One", phone="+233001", email="1@org.com")
        org2 = Organization.objects.create(name="Org Two", phone="+233002", email="2@org.com")

        m1 = OrganizationMembership.objects.create(organization=org1, user=self.user)
        m2 = OrganizationMembership.objects.create(organization=org2, user=self.user)
        m3 = OrganizationMembership.objects.create(organization=org1, user=self.other_user)

        user_memberships = OrganizationMembership.objects.for_user(self.user)
        self.assertEqual(user_memberships.count(), 2)
        self.assertIn(m1, user_memberships)
        self.assertIn(m2, user_memberships)
        self.assertNotIn(m3, user_memberships)

        org1_memberships = OrganizationMembership.objects.for_organization(org1)
        self.assertEqual(org1_memberships.count(), 2)
        self.assertIn(m1, org1_memberships)
        self.assertIn(m3, org1_memberships)
        self.assertNotIn(m2, org1_memberships)
