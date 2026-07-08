"""Hardening tests for anomaly detection service operations."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pgappforge.plugins.erp.platform.anomaly_detection.services import (
    AnomalyDetectionService,
    AnomalyNotFoundError,
    InvalidAnomalyResolutionError,
)


class _ScalarResult:
    def __init__(self, anomaly):
        self.anomaly = anomaly

    def scalar_one_or_none(self):
        return self.anomaly


class _Session:
    def __init__(self, anomaly=None) -> None:
        self.anomaly = anomaly
        self.executed = []
        self.flushed = False

    def execute(self, statement):
        self.executed.append(statement)
        return _ScalarResult(self.anomaly)

    def flush(self):
        self.flushed = True


def test_resolve_anomaly_normalizes_status_and_updates_resolution_fields():
    anomaly = SimpleNamespace(id="anom-1", status="OPEN")
    session = _Session(anomaly)

    result = AnomalyDetectionService().resolve_anomaly(
        " anom-1 ",
        " analyst-1 ",
        " duplicate invoice confirmed ",
        " resolved ",
        session,
    )

    assert result is anomaly
    assert anomaly.status == "RESOLVED"
    assert anomaly.resolved_by == "analyst-1"
    assert anomaly.resolution == "duplicate invoice confirmed"
    assert anomaly.resolved_at is not None
    assert session.flushed is True


def test_resolve_anomaly_rejects_invalid_status_before_querying():
    session = _Session(SimpleNamespace(id="anom-1", status="OPEN"))

    with pytest.raises(InvalidAnomalyResolutionError, match="Invalid anomaly resolution status"):
        AnomalyDetectionService().resolve_anomaly(
            "anom-1",
            "analyst-1",
            "reviewed",
            "closed",
            session,
        )

    assert session.executed == []


def test_resolve_anomaly_raises_not_found_without_asserts():
    with pytest.raises(AnomalyNotFoundError, match="not found"):
        AnomalyDetectionService().resolve_anomaly(
            "missing",
            "analyst-1",
            "reviewed",
            "RESOLVED",
            _Session(None),
        )


def test_resolve_anomaly_rejects_already_closed_anomaly():
    anomaly = SimpleNamespace(id="anom-1", status="FALSE_POSITIVE")

    with pytest.raises(InvalidAnomalyResolutionError, match="already"):
        AnomalyDetectionService().resolve_anomaly(
            "anom-1",
            "analyst-1",
            "reviewed",
            "RESOLVED",
            _Session(anomaly),
        )
