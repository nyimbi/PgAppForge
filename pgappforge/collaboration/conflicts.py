"""Field classification for conflict resolution.

Monetary, quantity and identifier fields must never be auto-resolved by a
collaboration sync engine; they require a human decision (or a ledger posting).
This module is the single place that decides which is which, so both the sync
engine and the resolver agree.
"""

from __future__ import annotations

import re
from typing import Final

_MONETARY = (
    r"amount|balance|price|cost|total|subtotal|tax|fee|charge|discount|duty|tariff|"
    r"interest|principal|repayment|outstanding|payment|salary|wage|penalt|profit|"
    r"revenue|expense|debit|credit|ledger|rate|fx|value"
)
_QUANTITY = r"qty|quantity|units|stock|weight|volume|count|shares?"
_IDENTIFIER = r"(^id$|_id$|^uuid|account_number$|^iban$|^msisdn$|phone$|email$|reference$)"

MANUAL_CONFLICT_FIELDS: Final[tuple[str, ...]] = (
    "amount", "balance", "available_balance", "pending_balance", "price",
    "cost", "total", "subtotal", "tax", "fee", "interest", "principal",
    "outstanding_principal_cents", "outstanding_interest_cents", "penalty_cents",
    "quantity", "qty", "units", "account_number", "iban", "msisdn",
)

_MONETARY_RE = re.compile(_MONETARY, re.IGNORECASE)
_QUANTITY_RE = re.compile(_QUANTITY, re.IGNORECASE)
_IDENTIFIER_RE = re.compile(_IDENTIFIER, re.IGNORECASE)


class ConflictDetectionError(RuntimeError):
    """Raised when the current state cannot be determined; callers must fail
    closed (treat as a conflict) rather than assume there is none."""


def is_manual_conflict_field(field_name: str | None) -> bool:
    """True when a field must never be auto-resolved by a sync engine."""
    if not field_name:
        return False
    name = field_name.strip()
    if name in MANUAL_CONFLICT_FIELDS:
        return True
    return bool(_MONETARY_RE.search(name) or _QUANTITY_RE.search(name))


def is_identifier_field(field_name: str | None) -> bool:
    return bool(field_name) and bool(_IDENTIFIER_RE.search(field_name.strip()))


def classify_field(field_name: str | None) -> str:
    if is_manual_conflict_field(field_name):
        return "monetary_or_quantity"
    if is_identifier_field(field_name):
        return "identifier"
    return "ordinary"
