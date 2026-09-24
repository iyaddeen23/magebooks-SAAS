"""Negative security and adversarial misuse tests for Act 1151 Ghanaian Statutory Tax Engine."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.tax.services import (
    TaxCalculationEngine,
)
from apps.tenancy.models import Organization, TaxSchemeChoices


class TestTaxSecurityAndMisuse(TestCase):
    """Adversarial and misuse test cases against TaxCalculationEngine."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(
            name="Secure Tech Gh",
            business_tin="C0001122334",
            phone="+233240000004",
            email="security@securetech.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )

    def test_floating_point_injection_prohibited(self) -> None:
        """Passing binary float raises TypeError to prevent IEEE-754 precision drift attacks."""
        with self.assertRaises(TypeError) as ctx:
            TaxCalculationEngine.calculate_exclusive(
                amount=1000.50,  # Prohibited float!
                organization=self.org,
            )
        self.assertIn("Floating-point values are prohibited", str(ctx.exception))

    def test_negative_amount_tax_inversion_exploit_rejected(self) -> None:
        """Supplying negative amounts raises ValidationError to block refund exploits."""
        with self.assertRaises(ValidationError) as ctx:
            TaxCalculationEngine.calculate_exclusive(
                amount=Decimal("-500.0000"),
                organization=self.org,
            )
        self.assertIn("cannot be negative", str(ctx.exception))

    def test_negative_gross_amount_rejected(self) -> None:
        """Supplying negative gross amount in calculate_inclusive raises ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            TaxCalculationEngine.calculate_inclusive(
                gross_amount=Decimal("-1200.0000"),
                organization=self.org,
            )
        self.assertIn("cannot be negative", str(ctx.exception))

    def test_invalid_withholding_tax_type_rejected(self) -> None:
        """Supplying unknown or manipulated WHT type raises ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            TaxCalculationEngine.calculate_withholding_tax(
                gross_amount=Decimal("1000.00"),
                wht_type="MALICIOUS_CUSTOM_0_PERCENT",
            )
        self.assertIn("Invalid WHT type", str(ctx.exception))

    def test_non_vat_registered_tenant_cannot_charge_statutory_taxes(self) -> None:
        """Asserts that non-VAT registered tenant output evaluates strictly to zero tax."""
        non_registered_org = Organization.objects.create(
            name="Unregistered Shop",
            business_tin="P0005544332",
            phone="+233240000005",
            email="unreg@shop.gh",
            vat_registered=False,
        )

        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("10000.0000"),
            organization=non_registered_org,
        )

        # Output taxes must be 0 to prevent unauthorized tax collection
        self.assertEqual(breakdown.vat_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.nhil_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.getfund_amount, Decimal("0.0000"))
        self.assertEqual(breakdown.total_tax, Decimal("0.0000"))
        self.assertEqual(breakdown.gross_amount, Decimal("10000.0000"))
        self.assertFalse(breakdown.is_taxable)

    def test_abolished_covid_levy_cannot_be_revived(self) -> None:
        """Verifies that covid_amount cannot be charged or mutated."""
        breakdown = TaxCalculationEngine.calculate_exclusive(
            amount=Decimal("1000.0000"),
            organization=self.org,
        )
        self.assertEqual(breakdown.covid_amount, Decimal("0.0000"))
        # Attempting to assign to frozen dataclass property raises AttributeError
        with self.assertRaises(AttributeError):
            breakdown.covid_amount = Decimal("10.0000")
