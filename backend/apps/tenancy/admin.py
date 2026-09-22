"""Django admin configuration for Tenancy models."""

from django.contrib import admin

from apps.tenancy.models import Organization, OrganizationMembership


class OrganizationMembershipInline(admin.TabularInline):
    """Inline view of memberships inside Organization admin."""

    model = OrganizationMembership
    extra = 0
    fields = ("user", "role", "is_active", "access_expires_at", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin configuration for Organization tenant master data."""

    list_display = (
        "name",
        "business_tin",
        "phone",
        "email",
        "vat_registered",
        "vat_scheme",
        "default_experience_mode",
        "created_at",
    )
    list_filter = (
        "vat_registered",
        "vat_scheme",
        "default_experience_mode",
        "created_at",
    )
    search_fields = ("name", "business_tin", "ghana_card_number", "email", "phone")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [OrganizationMembershipInline]


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    """Admin configuration for OrganizationMembership RBAC roles."""

    list_display = (
        "user",
        "organization",
        "role",
        "is_active",
        "access_expires_at",
        "created_at",
    )
    list_filter = ("role", "is_active", "created_at")
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "organization__name",
    )
    readonly_fields = ("id", "created_at")
