"""Tests for collaboration conflict classification and fail-closed detection."""

import pytest

from pgappforge.collaboration.conflicts import (
    ConflictDetectionError,
    classify_field,
    is_identifier_field,
    is_manual_conflict_field,
)


@pytest.mark.parametrize(
    "field",
    ["amount", "balance", "available_balance", "outstanding_interest_cents", "penalty_cents",
     "unit_price", "total_tax", "interest_rate", "qty", "quantity", "units", "iban", "msisdn"],
)
def test_protected_fields_never_auto_resolve(field):
    assert is_manual_conflict_field(field) is True
    assert classify_field(field) in {"monetary_or_quantity", "identifier"} or is_identifier_field(field)


@pytest.mark.parametrize("field", ["description", "status", "colour", "title", "name"])
def test_ordinary_fields_may_auto_resolve(field):
    assert is_manual_conflict_field(field) is False
    assert classify_field(field) == "ordinary"


def test_identifier_fields():
    assert is_identifier_field("user_id") is True
    assert is_identifier_field("account_number") is True
    assert is_identifier_field("description") is False


def test_empty_field_is_not_protected():
    assert is_manual_conflict_field(None) is False
    assert is_manual_conflict_field("") is False


def test_detection_error_is_a_runtime_error():
    assert issubclass(ConflictDetectionError, RuntimeError)
