"""Self-Validating Check-Digit and Reference Generation Utilities.

Implements:
1. LuhnValidator: Mod 10 algorithm for USSD biller codes & Mobile Money payment references.
2. VerhoeffValidator: Dihedral group D5 permutation check digits for account IDs.
3. Invoice payment reference generation utilities.
"""

import re
from collections.abc import Sequence
from typing import Final

from apps.invoicing.validators import (
    is_valid_ghana_card,
    is_valid_gra_tin,
    normalize_ghana_card,
    normalize_gra_tin,
    validate_ghana_card,
    validate_gra_tin,
)

__all__ = [
    "LuhnValidator",
    "VerhoeffValidator",
    "generate_invoice_payment_reference",
    "is_valid_ghana_card",
    "is_valid_gra_tin",
    "normalize_ghana_card",
    "normalize_gra_tin",
    "validate_ghana_card",
    "validate_gra_tin",
]


class LuhnValidator:
    """Mod 10 Luhn check-digit validator and reference generator.

    Traps:
    - 100% of single-digit transcription errors.
    - 98.9% of adjacent transposition errors (all except 09 <-> 90).
    Runs in strict O(N) linear time / O(1) for fixed-length sequence codes.
    """

    @staticmethod
    def calculate_check_digit(number_str: str | int) -> int:
        """Calculates Mod 10 check digit for the given payload string or integer.

        Algorithm:
        1. Extract numerical digits.
        2. Reverse the digits.
        3. Double every digit at even indices (0, 2, 4...) and subtract 9 if > 9.
        4. Sum the result.
        5. Check digit = (10 - (sum % 10)) % 10.
        """
        digits = [int(d) for d in str(number_str) if d.isdigit()]
        if not digits:
            raise ValueError("Cannot calculate Luhn check digit on a string without digits.")

        checksum = 0
        for idx, digit in enumerate(digits[::-1]):
            if idx % 2 == 0:
                doubled = digit * 2
                checksum += (doubled - 9) if doubled > 9 else doubled
            else:
                checksum += digit

        return (10 - (checksum % 10)) % 10

    @classmethod
    def generate_reference(cls, base_sequence: str | int, delimiter: str = "-") -> str:
        """Appends the calculated Luhn check digit to a base sequence.

        Example:
            LuhnValidator.generate_reference("84291", delimiter="-") -> "84291-4"
        """
        payload = str(base_sequence).strip()
        check_digit = cls.calculate_check_digit(payload)
        return f"{payload}{delimiter}{check_digit}"

    @classmethod
    def validate(cls, reference_str: str) -> bool:
        """Validates that the trailing digit matches the Luhn check digit of preceding digits.

        Returns True if valid, False if tampered, transposed, malformed, or degenerate.
        """
        cleaned = re.sub(r"[^0-9]", "", str(reference_str))
        if len(cleaned) < 2 or not cleaned.strip("0"):
            return False

        payload, check_digit_str = cleaned[:-1], cleaned[-1]
        try:
            return cls.calculate_check_digit(payload) == int(check_digit_str)
        except ValueError:
            return False

    @classmethod
    def clean_and_validate(cls, reference_str: str) -> tuple[bool, str, int | None]:
        """Cleans reference string, extracts payload and check digit, and validates.

        Returns:
            (is_valid, cleaned_payload, check_digit_or_none)
        """
        cleaned = re.sub(r"[^0-9]", "", str(reference_str))
        if len(cleaned) < 2 or not cleaned.strip("0"):
            return False, cleaned, None

        payload, check_digit = cleaned[:-1], int(cleaned[-1])
        is_valid = cls.calculate_check_digit(payload) == check_digit
        return is_valid, payload, check_digit


class VerhoeffValidator:
    """Verhoeff algorithm validator and generator using Dihedral group D5 arithmetic.

    Traps:
    - 100% of single-digit substitutions.
    - 100% of all adjacent transpositions without exception.
    """

    # Multiplication table over D5
    _D_TABLE: Final[Sequence[Sequence[int]]] = (
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
        (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
        (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
        (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
        (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
        (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
        (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
        (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
        (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
    )

    # Permutation table over period 8
    _P_TABLE: Final[Sequence[Sequence[int]]] = (
        (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
        (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
        (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
        (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
        (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
        (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
        (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
    )

    # Inverse table over D5
    _INV_TABLE: Final[Sequence[int]] = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)

    @classmethod
    def calculate_check_digit(cls, number_str: str | int) -> int:
        """Calculates Verhoeff check digit for given payload string or integer."""
        digits = [int(d) for d in str(number_str) if d.isdigit()]
        if not digits:
            raise ValueError("Cannot calculate Verhoeff check digit on empty input.")

        c = 0
        for i, digit in enumerate(digits[::-1]):
            c = cls._D_TABLE[c][cls._P_TABLE[(i + 1) % 8][digit]]
        return cls._INV_TABLE[c]

    @classmethod
    def generate_reference(cls, base_sequence: str | int, delimiter: str = "-") -> str:
        """Appends the calculated Verhoeff check digit to a base sequence."""
        payload = str(base_sequence).strip()
        check_digit = cls.calculate_check_digit(payload)
        return f"{payload}{delimiter}{check_digit}"

    @classmethod
    def validate(cls, reference_str: str) -> bool:
        """Validates that a full string including Verhoeff check digit satisfies D5 checksum."""
        digits = [int(d) for d in str(reference_str) if d.isdigit()]
        if len(digits) < 2 or all(d == 0 for d in digits):
            return False

        c = 0
        for i, digit in enumerate(digits[::-1]):
            c = cls._D_TABLE[c][cls._P_TABLE[i % 8][digit]]
        return c == 0


def generate_invoice_payment_reference(organization, seq_number: int | None = None) -> str:
    """Generates a compact, error-detecting payment reference with a Luhn check digit.

    Format: <numeric_seq>-<luhn_digit> (e.g. '10001-3')
    Used on physical receipts and USSD (*170#) Mobile Money deposits.
    """
    from apps.invoicing.models import Invoice

    if seq_number is None:
        count = Invoice.objects.filter(organization=organization).count()
        seq_number = 10001 + count

    return LuhnValidator.generate_reference(seq_number, delimiter="-")
