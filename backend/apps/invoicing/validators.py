"""Statutory and identity format validators for Mage Books SAAS.

Implements strict validation for:
1. Ghanaian Taxpayer Identification Number (GRA TIN): [CPQVG]\\d{10} (11 characters).
2. Ghana Card National ID PIN: GHA-\\d{9}-\\d (15 characters).
"""

import re
from typing import Final

from django.core.exceptions import ValidationError

GRA_TIN_REGEX: Final[re.Pattern[str]] = re.compile(r"^[CPQVG]\d{10}$")
GHANA_CARD_REGEX: Final[re.Pattern[str]] = re.compile(r"^GHA-\d{9}-\d$")

DUMMY_TIN_SEQUENCES: Final[set[str]] = {f"{prefix}{'0' * 10}" for prefix in "CPQVG"}
DUMMY_GHANA_CARDS: Final[set[str]] = {"GHA-000000000-0"}


def normalize_gra_tin(raw_tin: str | None) -> str:
    """Strips whitespace, hyphens, and coerces the prefix character to uppercase."""
    if not raw_tin:
        return ""
    return re.sub(r"[\s\-]", "", str(raw_tin)).upper()


def is_valid_gra_tin(raw_tin: str | None) -> bool:
    """Returns True if the input conforms to official GRA TIN format."""
    tin = normalize_gra_tin(raw_tin)
    if len(tin) != 11 or tin in DUMMY_TIN_SEQUENCES:
        return False
    return bool(GRA_TIN_REGEX.match(tin))


def validate_gra_tin(raw_tin: str | None) -> str:
    """Validates Ghanaian GRA TIN format.

    Format requirements:
    - Exactly 11 characters.
    - Prefix: 'C' (Corporate), 'P' (Personal), 'Q' (Partnership),
      'V' (Charity/Trust), or 'G' (Government).
    - Suffix: Exactly 10 numerical digits.

    Returns the normalized uppercase 11-character string or raises ValidationError.
    """
    tin = normalize_gra_tin(raw_tin)
    if not tin:
        raise ValidationError("GRA TIN cannot be blank.")

    if len(tin) != 11:
        raise ValidationError(f"Invalid GRA TIN length: expected 11 characters, got {len(tin)}.")

    prefix = tin[0]
    if prefix not in "CPQVG":
        raise ValidationError(
            f"Invalid GRA TIN prefix '{prefix}'. Must start with C, P, Q, V, or G."
        )

    if not GRA_TIN_REGEX.match(tin):
        raise ValidationError(
            "Invalid GRA TIN format. Must be an entity prefix (C, P, Q, V, G) "
            "followed by 10 digits (e.g. C0001234567)."
        )

    if tin in DUMMY_TIN_SEQUENCES:
        raise ValidationError("Invalid GRA TIN: degenerate all-zero sequences are prohibited.")

    return tin


def normalize_ghana_card(raw_pin: str | None) -> str:
    """Strips whitespace and coerces the GHA prefix to uppercase."""
    if not raw_pin:
        return ""
    cleaned = re.sub(r"\s", "", str(raw_pin)).upper()
    return cleaned


def is_valid_ghana_card(raw_pin: str | None) -> bool:
    """Returns True if the input conforms to official Ghana Card National ID format."""
    pin = normalize_ghana_card(raw_pin)
    if len(pin) != 15 or pin in DUMMY_GHANA_CARDS:
        return False
    return bool(GHANA_CARD_REGEX.match(pin))


def validate_ghana_card(raw_pin: str | None) -> str:
    """Validates Ghanaian National ID Card PIN format.

    Format requirements:
    - Exactly 15 characters: GHA-XXXXXXXXX-X (e.g. GHA-123456789-0).
    - Starts with literal 'GHA-'.
    - Followed by 9 numeric digits, a hyphen, and 1 terminal check digit.

    Returns the normalized uppercase string or raises ValidationError.
    """
    pin = normalize_ghana_card(raw_pin)
    if not pin:
        raise ValidationError("Ghana Card PIN cannot be blank.")

    if len(pin) != 15:
        raise ValidationError(
            f"Invalid Ghana Card PIN length: expected 15 characters, got {len(pin)}."
        )

    if not pin.startswith("GHA-"):
        raise ValidationError(
            "Invalid Ghana Card PIN: must start with the statutory prefix 'GHA-'."
        )

    if not GHANA_CARD_REGEX.match(pin):
        raise ValidationError(
            "Invalid Ghana Card PIN format. Expected 'GHA-XXXXXXXXX-X' (e.g. GHA-123456789-0)."
        )

    if pin in DUMMY_GHANA_CARDS:
        raise ValidationError(
            "Invalid Ghana Card PIN: degenerate all-zero sequences are prohibited."
        )

    return pin
