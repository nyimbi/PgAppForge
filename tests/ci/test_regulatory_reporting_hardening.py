"""Hardening tests for regulatory reporting exports."""
from __future__ import annotations

from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from pgappforge.plugins.erp.platform.regulatory_reporting.services import (
    RegulatoryReportingError,
    SaftReportService,
    _SAFT_NS,
)


class _ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []

    def execute(self, statement):
        self.executed.append(statement)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return _ScalarRows(result)


def _root(xml_str: str):
    return ET.fromstring(xml_str.split("\n", 1)[1])


def test_saft_gl_keeps_valid_xml_when_gl_queries_fail():
    session = _Session([Exception("no account table"), Exception("no journal table")])

    xml_str = SaftReportService().generate_saft_gl(" tenant-a ", 2024, session)
    root = _root(xml_str)

    assert xml_str.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert root.tag == f"{{{_SAFT_NS}}}AuditFile"
    assert root.find(f".//{{{_SAFT_NS}}}GeneralLedgerAccounts") is not None
    assert root.find(f".//{{{_SAFT_NS}}}GeneralLedgerEntries") is not None
    assert root.findtext(f".//{{{_SAFT_NS}}}CompanyID") == "tenant-a"


def test_saft_gl_validates_export_identity_inputs():
    svc = SaftReportService()

    with pytest.raises(RegulatoryReportingError, match="tenant_id"):
        svc.generate_saft_gl(" ", 2024, _Session([[], []]))
    with pytest.raises(RegulatoryReportingError, match="integer year"):
        svc.generate_saft_gl("tenant-a", True, _Session([[], []]))
    with pytest.raises(RegulatoryReportingError, match="between 1900 and 2200"):
        svc.generate_saft_gl("tenant-a", 1800, _Session([[], []]))


def test_saft_gl_exports_accounts_and_entries_with_actual_gl_field_names():
    account = SimpleNamespace(
        account_code="1000",
        account_name="Cash",
        account_type="ASSET",
    )
    entry = SimpleNamespace(
        id="entry-1",
        description="Opening balance",
    )
    session = _Session([[account], [entry]])

    xml_str = SaftReportService().generate_saft_gl("tenant-a", 2024, session)
    root = _root(xml_str)

    assert root.findtext(f".//{{{_SAFT_NS}}}AccountID") == "1000"
    assert root.findtext(f".//{{{_SAFT_NS}}}AccountDescription") == "Cash"
    assert root.findtext(f".//{{{_SAFT_NS}}}AccountType") == "ASSET"
    assert root.findtext(f".//{{{_SAFT_NS}}}JournalID") == "entry-1"
    assert root.findtext(f".//{{{_SAFT_NS}}}Description") == "Opening balance"
    assert len(session.executed) == 2
