"""Unit tests for Luhn and Verhoeff Check-Digit Engines & Statutory ID Validators (Feature 3.2).

Validates:
1. Luhn Mod 10 algorithm check-digit generation and O(1) error detection.
2. 100% single-digit transcription error detection and transposition trapping.
3. Verhoeff D5 algorithm check digits and 100% transposition trapping (including 09 <-> 90).
4. Ghana Card PIN strict validation and normalization.
5. GRA TIN strict statutory prefix and length validation.
6. Automatic Invoice payment_reference generation and validation.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.invoicing.models import (
    Contact,
    ContactTypeChoices,
    Invoice,
    InvoiceStatusChoices,
)
from apps.invoicing.utils import (
    LuhnValidator,
    VerhoeffValidator,
    is_valid_ghana_card,
    is_valid_gra_tin,
    validate_ghana_card,
    validate_gra_tin,
)
from apps.tenancy.models import Organization, TaxSchemeChoices


class LuhnAlgorithmTests(TestCase):
    """Test suite verifying Luhn Mod 10 check-digit calculations and mathematical error trapping."""

    def test_luhn_check_digit_calculation_known_vectors(self) -> None:
        """Verify check digits against standard mathematical vectors."""
        # 84291 -> check digit 4
        self.assertEqual(LuhnValidator.calculate_check_digit("84291"), 4)
        # 123456 -> check digit 6
        self.assertEqual(LuhnValidator.calculate_check_digit("123456"), 6)
        # 7992739871 -> check digit 3
        self.assertEqual(LuhnValidator.calculate_check_digit("7992739871"), 3)
        # Integer input support
        self.assertEqual(LuhnValidator.calculate_check_digit(84291), 4)

    def test_luhn_generate_and_validate_reference(self) -> None:
        """Generating a reference and validating it must return True."""
        ref = LuhnValidator.generate_reference("84291", delimiter="-")
        self.assertEqual(ref, "84291-4")
        self.assertTrue(LuhnValidator.validate(ref))
        self.assertTrue(LuhnValidator.validate("842914"))

    def test_luhn_clean_and_validate_utility(self) -> None:
        """Verify clean_and_validate handles formatted and dirty input."""
        valid, payload, cd = LuhnValidator.clean_and_validate("INV-84291-4")
        self.assertTrue(valid)
        self.assertEqual(payload, "84291")
        self.assertEqual(cd, 4)

        valid_bad, payload_bad, cd_bad = LuhnValidator.clean_and_validate("INV-84291-9")
        self.assertFalse(valid_bad)
        self.assertEqual(payload_bad, "84291")
        self.assertEqual(cd_bad, 9)

    def test_luhn_traps_all_single_digit_transcription_errors(self) -> None:
        """Mod 10 traps 100% of single-digit substitution errors."""
        base = "84291"
        valid_ref = LuhnValidator.generate_reference(base, delimiter="")  # "842914"

        # Mutate each position to all other 9 possible digits
        for pos in range(len(valid_ref)):
            original_digit = valid_ref[pos]
            for replacement in "0123456789":
                if replacement == original_digit:
                    continue
                tampered = valid_ref[:pos] + replacement + valid_ref[pos + 1 :]
                self.assertFalse(
                    LuhnValidator.validate(tampered),
                    f"Luhn failed to detect transcription error at pos {pos}: {tampered}",
                )

    def test_luhn_traps_adjacent_transpositions(self) -> None:
        """Mod 10 traps adjacent transpositions (except 09 <-> 90)."""
        test_cases = ["84291", "13579", "24680", "50193"]
        for base in test_cases:
            ref = LuhnValidator.generate_reference(base, delimiter="")
            # Swap every adjacent pair
            for i in range(len(ref) - 1):
                d1, d2 = ref[i], ref[i + 1]
                if d1 == d2 or {d1, d2} == {"0", "9"}:
                    continue
                # Transpose
                transposed = ref[:i] + d2 + d1 + ref[i + 2 :]
                self.assertFalse(
                    LuhnValidator.validate(transposed),
                    f"Luhn failed to trap transposition {d1}{d2} <-> {d2}{d1} in {transposed}",
                )

    def test_luhn_empty_or_invalid_inputs(self) -> None:
        """Supplying string with no digits raises ValueError or returns False."""
        with self.assertRaises(ValueError):
            LuhnValidator.calculate_check_digit("abc")
        self.assertFalse(LuhnValidator.validate(""))
        self.assertFalse(LuhnValidator.validate("5"))


class VerhoeffAlgorithmTests(TestCase):
    """Test suite verifying Verhoeff D5 Dihedral group check-digit calculations."""

    def test_verhoeff_standard_vectors(self) -> None:
        """Verify Verhoeff check digits against established mathematical test vectors."""
        # 236 -> 3 (full: 2363)
        self.assertEqual(VerhoeffValidator.calculate_check_digit("236"), 3)
        self.assertTrue(VerhoeffValidator.validate("2363"))

        # 142857 -> 0 (full: 1428570)
        self.assertEqual(VerhoeffValidator.calculate_check_digit("142857"), 0)
        self.assertTrue(VerhoeffValidator.validate("1428570"))

        # 12345 -> 1 (full: 123451)
        self.assertEqual(VerhoeffValidator.calculate_check_digit(12345), 1)
        self.assertTrue(VerhoeffValidator.validate("123451"))

    def test_verhoeff_generate_reference(self) -> None:
        """Generate formatted reference with Verhoeff check digit."""
        ref = VerhoeffValidator.generate_reference("7492", delimiter="-")
        self.assertEqual(ref, "7492-3")
        self.assertTrue(VerhoeffValidator.validate(ref))

    def test_verhoeff_traps_all_single_digit_substitutions(self) -> None:
        """Verhoeff traps 100% of single-digit substitution errors across all positions."""
        test_vectors = ["236", "142857", "7492", "5092"]
        for base in test_vectors:
            ref = VerhoeffValidator.generate_reference(base, delimiter="")
            for pos in range(len(ref)):
                original_digit = ref[pos]
                for replacement in "0123456789":
                    if replacement == original_digit:
                        continue
                    tampered = ref[:pos] + replacement + ref[pos + 1 :]
                    self.assertFalse(
                        VerhoeffValidator.validate(tampered),
                        f"Verhoeff failed to detect substitution at pos {pos}: {tampered}",
                    )

    def test_verhoeff_traps_all_transpositions_including_09_90(self) -> None:
        """Verhoeff traps 100% of adjacent transpositions without exception."""
        # Specifically test 09 <-> 90 where Luhn is known to be blind
        num_with_09 = "5092"
        ref_09 = VerhoeffValidator.generate_reference(num_with_09, delimiter="")
        # Transpose '09' to '90'
        transposed_09 = ref_09.replace("09", "90", 1)
        self.assertFalse(
            VerhoeffValidator.validate(transposed_09),
            "Verhoeff must detect 09 <-> 90 transposition",
        )

        # Full check across all adjacent positions
        base = "987654"
        ref = VerhoeffValidator.generate_reference(base, delimiter="")
        for i in range(len(ref) - 1):
            if ref[i] != ref[i + 1]:
                swapped = ref[:i] + ref[i + 1] + ref[i] + ref[i + 2 :]
                self.assertFalse(
                    VerhoeffValidator.validate(swapped),
                    f"Verhoeff failed to detect transposition in {swapped}",
                )

    def test_verhoeff_detects_jump_transpositions(self) -> None:
        """Verhoeff detects jump transpositions (e.g., abc -> cba)."""
        ref = VerhoeffValidator.generate_reference("142857", delimiter="")  # "1428570"
        # Swap pos 0 and pos 2: "2418570"
        jump_transposed = "2" + ref[1] + "1" + ref[3:]
        self.assertFalse(VerhoeffValidator.validate(jump_transposed))

    def test_leading_zeros_handling(self) -> None:
        """Both Luhn and Verhoeff handle leading zeros correctly without dropping digits."""
        # Luhn with leading zeros
        luhn_ref = LuhnValidator.generate_reference("00123", delimiter="-")
        self.assertEqual(luhn_ref, "00123-0")
        self.assertTrue(LuhnValidator.validate("00123-0"))
        self.assertTrue(LuhnValidator.validate("0123-0"))

        # Verhoeff with leading zeros
        verhoeff_ref = VerhoeffValidator.generate_reference("00123", delimiter="-")
        self.assertEqual(verhoeff_ref, "00123-7")
        self.assertTrue(VerhoeffValidator.validate("00123-7"))
        self.assertTrue(VerhoeffValidator.validate("0123-6"))

    def test_luhn_blind_spot_vs_verhoeff_resilience(self) -> None:
        """Demonstrate mathematically why Luhn misses 09 <-> 90 but Verhoeff traps it."""
        # Sequence containing '09'
        base_09 = "1092"
        luhn_ref = LuhnValidator.generate_reference(base_09, delimiter="")
        # Swapping '09' to '90' in Luhn produces identical checksum
        luhn_swapped = luhn_ref.replace("09", "90", 1)
        # Note: Luhn will mathematically validate because 2*0+9 == 2*9-9+0 == 9
        self.assertTrue(
            LuhnValidator.validate(luhn_swapped),
            "Luhn Mod 10 mathematically cannot trap 09 <-> 90 transpositions",
        )

        # Conversely, Verhoeff D5 algorithm traps it without fail
        verhoeff_ref = VerhoeffValidator.generate_reference(base_09, delimiter="")
        verhoeff_swapped = verhoeff_ref.replace("09", "90", 1)
        self.assertFalse(
            VerhoeffValidator.validate(verhoeff_swapped),
            "Verhoeff D5 algorithm must trap 09 <-> 90 transpositions",
        )


class StatutoryIdValidatorTests(TestCase):
    """Test suite validating Ghanaian TIN and Ghana Card National ID formats."""

    def test_valid_gra_tins(self) -> None:
        """Valid GRA TINs with authorized prefixes (C, P, Q, V, G) pass validation."""
        valid_tins = [
            "C0001234567",  # Corporate
            "P0009876543",  # Personal
            "Q0004567890",  # Partnership
            "V0001122334",  # Trust / Charity
            "G0005544332",  # Government MDA
            "c0001234567",  # Lowercase normalized
            "C-0001234567",  # Hyphen normalized
            " C0001234567 ",  # Whitespace normalized
        ]
        for tin in valid_tins:
            self.assertTrue(is_valid_gra_tin(tin), f"Expected {tin} to be valid TIN")
            validated = validate_gra_tin(tin)
            self.assertEqual(len(validated), 11)
            self.assertTrue(validated.startswith(("C", "P", "Q", "V", "G")))

    def test_invalid_gra_tins(self) -> None:
        """Invalid prefixes, wrong length, and dummy sequences raise ValidationError."""
        invalid_tins = [
            "X0001234567",  # Invalid prefix
            "10001234567",  # Numeric prefix
            "C000123456",  # 10 chars (too short)
            "C00012345678",  # 12 chars (too long)
            "C000123456A",  # Non-digit in body
            "C0000000000",  # Degenerate all-zero
            "",  # Empty
            None,  # None
        ]
        for tin in invalid_tins:
            self.assertFalse(is_valid_gra_tin(tin), f"Expected {tin} to be invalid TIN")
            with self.assertRaises(ValidationError):
                validate_gra_tin(tin)

    def test_valid_ghana_cards(self) -> None:
        """Valid Ghana Card PINs conforming to GHA-XXXXXXXXX-X pass validation."""
        valid_cards = [
            "GHA-123456789-0",
            "GHA-718293041-9",
            "gha-123456789-0",  # Lowercase prefix normalized
            " GHA-123456789-0 ",  # Whitespace trimmed
        ]
        for card in valid_cards:
            self.assertTrue(is_valid_ghana_card(card), f"Expected {card} to be valid Ghana Card")
            validated = validate_ghana_card(card)
            self.assertEqual(len(validated), 15)
            self.assertTrue(validated.startswith("GHA-"))

    def test_invalid_ghana_cards(self) -> None:
        """Invalid prefixes, wrong lengths, or missing hyphens raise ValidationError."""
        invalid_cards = [
            "NGA-123456789-0",  # Wrong country prefix
            "GHA-12345678-0",  # 8 digits in sequence (too short)
            "GHA-1234567890-0",  # 10 digits in sequence (too long)
            "GHA1234567890",  # Missing hyphens
            "GHA-123456789-X",  # Non-digit check character
            "GHA-000000000-0",  # Degenerate all-zero
            "",
            None,
        ]
        for card in invalid_cards:
            self.assertFalse(is_valid_ghana_card(card), f"Expected {card} to be invalid")
            with self.assertRaises(ValidationError):
                validate_ghana_card(card)


class InvoicePaymentReferenceIntegrationTests(TestCase):
    """Test suite verifying Invoice and Contact integration with reference generator."""

    def setUp(self) -> None:
        self.org = Organization.objects.create(
            name="Kumasi Merchants Ltd",
            business_tin="C0009876543",
            phone="+233240001199",
            email="accounts@kumasimerchants.gh",
            vat_registered=True,
            vat_scheme=TaxSchemeChoices.STANDARD,
        )
        self.customer = Contact.objects.create(
            organization=self.org,
            name="Kwame Mensah Ent",
            contact_type=ContactTypeChoices.CUSTOMER,
            tin="C0001112233",
            ghana_card_number="GHA-123456789-1",
        )

    def test_invoice_auto_generates_valid_payment_reference(self) -> None:
        """Saving an invoice without payment_reference automatically assigns a valid Luhn code."""
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-00010",
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("1500.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )
        self.assertTrue(bool(invoice.payment_reference))
        # Verify it has Luhn format <seq>-<digit> and validates
        self.assertTrue(LuhnValidator.validate(invoice.payment_reference))

    def test_invoice_manual_valid_payment_reference_accepted(self) -> None:
        """Supplying a valid manual Luhn payment reference succeeds."""
        valid_ref = LuhnValidator.generate_reference("84291", delimiter="-")
        invoice = Invoice.objects.create(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-00011",
            payment_reference=valid_ref,
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )
        self.assertEqual(invoice.payment_reference, valid_ref)

    def test_invoice_invalid_payment_reference_rejected(self) -> None:
        """Supplying a tampered or invalid Luhn payment reference raises ValidationError."""
        invoice = Invoice(
            organization=self.org,
            customer=self.customer,
            invoice_number="INV-2026-00012",
            payment_reference="84291-9",  # Invalid check digit (should be 4)
            issue_date=date(2026, 9, 24),
            due_date=date(2026, 10, 24),
            total_amount=Decimal("500.0000"),
            status=InvoiceStatusChoices.DRAFT,
        )
        with self.assertRaises(ValidationError) as ctx:
            invoice.full_clean()
        self.assertIn("payment_reference", ctx.exception.message_dict)

    def test_contact_statutory_validation_on_clean(self) -> None:
        """Contact clean() validates TIN and Ghana Card PIN."""
        invalid_contact = Contact(
            organization=self.org,
            name="Bad Taxpayer Ltd",
            tin="INVALID-TIN-123",
        )
        with self.assertRaises(ValidationError) as ctx:
            invalid_contact.full_clean()
        self.assertIn("tin", ctx.exception.message_dict)
