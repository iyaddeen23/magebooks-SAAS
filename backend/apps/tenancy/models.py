"""Multi-tenancy and Role-Based Access Control (RBAC) models for Mage Books SAAS."""

import uuid6
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

ghana_tin_validator = RegexValidator(
    regex=r"^[CPGVT]\d{10}$",
    message="Enter a valid GRA Taxpayer Identification Number (e.g., C0001234567).",
)

ghana_card_validator = RegexValidator(
    regex=r"^GHA-\d{9}-\d$",
    message="Enter a valid Director Ghana Card PIN (e.g., GHA-123456789-0).",
)


class TaxSchemeChoices(models.TextChoices):
    """Statutory tax supply classifications under Ghanaian Value Added Tax Act, 2025 (Act 1151)."""

    STANDARD = "STANDARD", "Standard (20.0% Unified Rate)"
    EXEMPT = "EXEMPT", "Exempt Supply"
    ZERO_RATED = "ZERO_RATED", "Zero-Rated (Exports)"


class ExperienceModeChoices(models.TextChoices):
    """Dual-experience mode: Simple (Sole Trader) vs Full (Professional/Accountant)."""

    SIMPLE = "simple", "Simple Mode (Kofi)"
    FULL = "full", "Full Accounting Mode (Kwame)"


class RoleChoices(models.TextChoices):
    """The 5 discrete RBAC roles defined in Section 4.6 of Engineering Specification."""

    OWNER = "OWNER", "Owner (Principal)"
    ADMIN = "ADMIN", "Admin (General Manager)"
    ACCOUNTANT = "ACCOUNTANT", "Accountant (Chartered)"
    BOOKKEEPER = "BOOKKEEPER", "Bookkeeper (Data Entry / Cashier)"
    AUDITOR = "AUDITOR", "External Auditor (Read-Only Ephemeral)"


class Organization(models.Model):
    """Tenant master entity encapsulating Ghanaian business details and Act 1151 tax compliance."""

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    name = models.CharField(max_length=255)
    business_tin = models.CharField(
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        validators=[ghana_tin_validator],
        help_text="GRA Taxpayer Identification Number (e.g. C0001234567)",
    )
    ghana_card_number = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        validators=[ghana_card_validator],
        help_text="Director's Ghana Card PIN (e.g. GHA-123456789-0)",
    )
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(max_length=255)
    vat_registered = models.BooleanField(
        default=False,
        help_text="True if taxable supplies exceed Act 1151 statutory threshold of GHS 750,000",
    )
    vat_scheme = models.CharField(
        max_length=20,
        choices=TaxSchemeChoices.choices,
        default=TaxSchemeChoices.STANDARD,
    )
    default_experience_mode = models.CharField(
        max_length=20,
        choices=ExperienceModeChoices.choices,
        default=ExperienceModeChoices.SIMPLE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organizations"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def owner(self):
        """Returns the User holding the active OWNER membership for this organization."""
        membership = (
            self.memberships.filter(role=RoleChoices.OWNER, is_active=True)
            .select_related("user")
            .first()
        )
        return membership.user if membership else None


class OrganizationMembershipQuerySet(models.QuerySet):
    """Custom QuerySet with active and scoped query helpers."""

    def active(self):
        """Returns active memberships excluding expired ephemeral auditor memberships."""
        now = timezone.now()
        return self.filter(is_active=True).filter(
            models.Q(access_expires_at__isnull=True) | models.Q(access_expires_at__gt=now)
        )

    def for_user(self, user):
        """Scopes memberships for a given user."""
        return self.filter(user=user)

    def for_organization(self, organization):
        """Scopes memberships for a given organization."""
        return self.filter(organization=organization)


class OrganizationMembershipManager(models.Manager.from_queryset(OrganizationMembershipQuerySet)):
    """Manager for OrganizationMembership providing active and scoped querysets."""

    pass


class OrganizationMembership(models.Model):
    """User membership within an organization defining RBAC role and ephemeral access lifecycle."""

    id = models.UUIDField(primary_key=True, default=uuid6.uuid7, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )
    role = models.CharField(
        max_length=30,
        choices=RoleChoices.choices,
        default=RoleChoices.BOOKKEEPER,
    )
    is_active = models.BooleanField(default=True)
    access_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Configurable expiration timestamp for temporary access (primarily AUDITOR role)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationMembershipManager()

    class Meta:
        db_table = "organization_memberships"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_org_user_membership",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.email} - {self.organization.name} ({self.get_role_display()})"

    def is_expired(self) -> bool:
        """Evaluates whether this membership's access has expired."""
        if not self.access_expires_at:
            return False
        return timezone.now() >= self.access_expires_at

    def clean(self):
        """Enforces domain integrity rules (Owner immutability and role expiration constraints)."""
        super().clean()
        if self.role == RoleChoices.OWNER and self.access_expires_at is not None:
            raise ValidationError(
                {"access_expires_at": "Owner role cannot have an access expiration date."}
            )

        # Owner immutability: Prevent demotion or deactivation of an existing OWNER
        if self.pk:
            orig = (
                OrganizationMembership.objects.filter(pk=self.pk)
                .values("role", "is_active")
                .first()
            )
            if orig and orig["role"] == RoleChoices.OWNER:
                if self.role != RoleChoices.OWNER:
                    raise ValidationError(
                        {"role": "Organization Owner cannot be demoted to another role."}
                    )
                if not self.is_active:
                    raise ValidationError(
                        {"is_active": "Organization Owner cannot be deactivated."}
                    )

    def save(self, *args, **kwargs):
        """Enforce domain invariants and validation rules on all save operations."""
        self.full_clean()
        super().save(*args, **kwargs)
