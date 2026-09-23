"""Dual-UUID Base Models and QuerySets for Mage Books SAAS multi-tenant architecture.

Enforces:
1. Internal Relational Identifiers (UUIDv7): Sequential, timestamp-ordered B-Tree appends
   preventing index fragmentation and cache thrashing across high-throughput financial tables.
2. Database-level Tenant Isolation: Composite UNIQUE(organization, id) constraint ensuring
   downstream composite foreign keys can bind strictly within the same tenant.
3. Financial Ledger Immutability: on_delete=models.PROTECT preventing accidental cascading
   destruction of tenant financial history.
4. Public Security Perimeter (UUIDv4): High-entropy, unguessable guest tokens eliminating
   timestamp leakage, timing attacks, and sequence enumeration.
"""

import uuid
from typing import Any
from uuid import UUID

import uuid6
from django.db import models


class TenantQuerySet(models.QuerySet):
    """Custom QuerySet providing tenant-scoping helpers for BaseTenantModel."""

    def for_tenant(self, tenant: Any) -> "TenantQuerySet":
        """Filters the queryset strictly to records belonging to the given tenant.

        Accepts an Organization model instance or a tenant UUID / string.
        """
        if hasattr(tenant, "id"):
            return self.filter(organization=tenant)
        return self.filter(organization_id=tenant)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Default model manager for BaseTenantModel exposing TenantQuerySet helpers."""

    pass


class BaseTenantModel(models.Model):
    """Abstract base model for all tenant-scoped business entities in Mage Books SAAS.

    Features:
    - UUIDv7 primary key (internal sequential storage engine).
    - Foreign key to Organization with models.PROTECT (financial ledger safety).
    - Composite UNIQUE(organization, id) constraint for composite tenant foreign keys.
    - Timestamp tracking (created_at, updated_at).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid6.uuid7,
        editable=False,
        help_text="Sequential UUIDv7 primary key for high-throughput B-Tree indexing.",
    )
    organization = models.ForeignKey(
        "tenancy.Organization",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
        help_text="Tenant ownership foreign key protected against accidental deletion.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp when record was created.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when record was last updated.",
    )

    objects = TenantManager()

    class Meta:
        abstract = True
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "id"],
                name="unique_%(app_label)s_%(class)s_tenant_id",
            )
        ]


class PublicShareableMixin(models.Model):
    """Abstract mixin providing high-entropy UUIDv4 bearer tokens for public guest perimeters.

    Used on invoices, payment links, and receipts to prevent timestamp leakage
    and transaction velocity enumeration (German Tank Problem).
    """

    share_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Unguessable UUIDv4 token for public guest URLs and payment links.",
    )

    class Meta:
        abstract = True

    def regenerate_share_token(self, commit: bool = True) -> UUID:
        """Rotates the share_token with a new cryptographically random UUIDv4."""
        self.share_token = uuid.uuid4()
        if commit:
            self.save(update_fields=["share_token"])
        return self.share_token
