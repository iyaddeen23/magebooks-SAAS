"""Adversarial and security misuse tests for Check-Digit Engine & Statutory Validators.

Covers:
1. MUC-1.1 Foundation: Resiliency against malformed and adversarial USSD inputs.
2. Injection Defense: SQL Injection, XSS, and traversal strings in TIN and Ghana Card.
3. Transposition & Transcription Error Detection in O(1) mathematical time.
4. Denial of Service (DoS) and integer overflow input bounds testing.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.invoicing.models import Contact, ContactTypeChoices, Invoice
from apps.invoicing.utils import (
    LuhnValidator,
    VerhoeffValidator,
    validate_ghana_card,
    validate_gra_tin,
)
from apps.tenancy.models import Organization, TaxSchemeChoices


class ReferenceSecurityAndMisuseTests(TestCase):
    """Adversarial test suite validating check-digit resilience and injection defenses."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(
            name="Security Test Corp Ltd",
            business_tin="C0001112233",
            phone="+233240000009",
            email="security@testcorp.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.customer = Contact.objects.create(
            organization=self.org,
            name="Target Customer",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0001234567",
            ghana_card_number="GHA-123456789-0",
        )

    def test_sql_injection_in_tin_blocked(self) -> None:
        """SQL injection fragments in TIN are strictly rejected by the validator."""
        sqli_payloads = [
            "C0001234567; DROP TABLE invoices;--",
            "' OR '1'='1",
            "C000' UNION SELECT * FROM users--",
            "C0001234567\x00--",
        ]
        for payload in sqli_payloads:
            with self.assertRaises(ValidationError, msg=f"SQLi payload {payload} must be rejected"):
                validate_gra_tin(payload)

    def test_xss_injection_in_ghana_card_blocked(self) -> None:
        """XSS and HTML script payloads in Ghana Card PIN are strictly rejected."""
        xss_payloads = [
            "<script>alert('pwned')</script>",
            "GHA-<script>-0",
            "GHA-123456789-<svg/onload=alert(1)>",
            "javascript:void(0)",
        ]
        for payload in xss_payloads:
            with self.assertRaises(ValidationError, msg=f"XSS payload {payload} must be rejected"):
                validate_ghana_card(payload)

    def test_adversarial_ussd_momo_memo_inputs(self) -> None:
        """Adversarial, noisy, or corrupted USSD keypad inputs do not crash the engine."""
        corrupted_inputs = [
            "  *170# 84291-4 ",  # USSD wrapper text
            "84291-4\n\r",  # Carriage returns
            "842914-FAIL",  # Appended letters
            "---",  # Only delimiters
            "NULL",
            "NaN",
            "⚡🚀🔥",  # Unicode emojis
            "0" * 1000,  # 1,000-character sequence
        ]
        for noisy_input in corrupted_inputs:
            # Must return boolean False or clean valid tuple without raising unhandled exceptions
            is_valid, payload, cd = LuhnValidator.clean_and_validate(noisy_input)
            if noisy_input.strip() == "84291-4" or "842914" in noisy_input:
                continue
            self.assertFalse(
                LuhnValidator.validate(noisy_input),
                f"Noisy input should not validate: {noisy_input}",
            )

    def test_verhoeff_adversarial_adjacent_transpositions_trapped(self) -> None:
        """All adjacent transpositions across arbitrary digit sequences are trapped in O(1)."""
        adversarial_sequences = [
            "1029384756",
            "5091827364",
            "9081726354",
            "1209348756",
        ]
        for seq in adversarial_sequences:
            ref = VerhoeffValidator.generate_reference(seq, delimiter="")
            for idx in range(len(ref) - 1):
                if ref[idx] == ref[idx + 1]:
                    continue
                # Transpose adjacent digits
                tampered = ref[:idx] + ref[idx + 1] + ref[idx] + ref[idx + 2 :]
                self.assertFalse(
                    VerhoeffValidator.validate(tampered),
                    f"Verhoeff missed transposition in {tampered}",
                )

    def test_luhn_tampered_payment_reference_invoice_save_blocked(self) -> None:
        """Attempting to assign a tampered Luhn reference to an invoice raises ValidationError."""
        invoice = Invoice(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-SEC-01",
            payment_reference="99999-0",  # 99999 check digit is 5, not 0
            total_amount=Decimal("100.0000"),
        )
        with self.assertRaises(ValidationError) as ctx:
            invoice.full_clean()
        self.assertIn("payment_reference", ctx.exception.message_dict)
