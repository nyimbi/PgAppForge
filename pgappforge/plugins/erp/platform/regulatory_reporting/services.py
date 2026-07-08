"""Regulatory reporting service — SAF-T GL, CSRD, Peppol."""
from __future__ import annotations
from datetime import date
import logging
import xml.etree.ElementTree as ET
from typing import Any

import sqlalchemy as sa


_SAFT_NS = "urn:OECD:Standard:SAF-T:1.00"
log = logging.getLogger(__name__)


class RegulatoryReportingError(Exception):
	"""Base error for regulatory reporting input violations."""


class SaftReportService:
	def generate_saft_gl(self, tenant_id: str, fiscal_year: int, session: Any) -> str:
		tenant_id = self._validate_tenant_id(tenant_id)
		fiscal_year = self._validate_fiscal_year(fiscal_year)
		# Register namespace so ET produces proper xmlns declaration, not ns0: prefix
		ET.register_namespace("", _SAFT_NS)
		ns = f"{{{_SAFT_NS}}}"

		root = ET.Element(f"{ns}AuditFile")
		header = ET.SubElement(root, f"{ns}Header")
		ET.SubElement(header, f"{ns}AuditFileVersion").text = "1.00"
		ET.SubElement(header, f"{ns}CompanyID").text = tenant_id
		ET.SubElement(header, f"{ns}TaxRegistrationNumber").text = ""
		ET.SubElement(header, f"{ns}FiscalYear").text = str(fiscal_year)
		master = ET.SubElement(root, f"{ns}MasterFiles")
		gl_accounts = ET.SubElement(master, f"{ns}GeneralLedgerAccounts")
		for acct in self._load_gl_accounts(tenant_id, session):
			acct_el = ET.SubElement(gl_accounts, f"{ns}Account")
			ET.SubElement(acct_el, f"{ns}AccountID").text = self._text_value(
				acct,
				"account_code",
				"id",
			)
			ET.SubElement(acct_el, f"{ns}AccountDescription").text = self._text_value(
				acct,
				"account_name",
				"name",
			)
			ET.SubElement(acct_el, f"{ns}AccountType").text = self._text_value(
				acct,
				"account_type",
			)
		transactions = ET.SubElement(root, f"{ns}GeneralLedgerEntries")
		for entry in self._load_gl_entries(tenant_id, fiscal_year, session):
			entry_el = ET.SubElement(transactions, f"{ns}Journal")
			ET.SubElement(entry_el, f"{ns}JournalID").text = self._text_value(entry, "id")
			ET.SubElement(entry_el, f"{ns}Description").text = self._text_value(
				entry,
				"description",
			)
		# xml_declaration=True produces the required <?xml version='1.0' encoding='us-ascii'?>
		# Use tostring with encoding='unicode' for a str return, prepend declaration manually
		body = ET.tostring(root, encoding="unicode")
		return '<?xml version="1.0" encoding="UTF-8"?>\n' + body

	@staticmethod
	def _validate_tenant_id(value: str) -> str:
		if not isinstance(value, str) or not value.strip():
			raise RegulatoryReportingError("tenant_id is required")
		return value.strip()

	@staticmethod
	def _validate_fiscal_year(value: int) -> int:
		if isinstance(value, bool):
			raise RegulatoryReportingError("fiscal_year must be an integer year")
		try:
			year = int(value)
		except (TypeError, ValueError) as exc:
			raise RegulatoryReportingError("fiscal_year must be an integer year") from exc
		if year < 1900 or year > 2200:
			raise RegulatoryReportingError("fiscal_year must be between 1900 and 2200")
		return year

	def _load_gl_accounts(self, tenant_id: str, session: Any) -> list[Any]:
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLAccount
		except ImportError:
			return []
		stmt = (
			sa.select(GLAccount)
			.where(GLAccount.tenant_id == tenant_id)
			.order_by(GLAccount.account_code)
		)
		return self._safe_scalars(stmt, session, "SAF-T GL account query")

	def _load_gl_entries(self, tenant_id: str, fiscal_year: int, session: Any) -> list[Any]:
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLJournalEntry
		except ImportError:
			return []
		start = date(fiscal_year, 1, 1)
		end = date(fiscal_year, 12, 31)
		stmt = (
			sa.select(GLJournalEntry)
			.where(
				GLJournalEntry.tenant_id == tenant_id,
				GLJournalEntry.posting_date >= start,
				GLJournalEntry.posting_date <= end,
			)
			.order_by(GLJournalEntry.posting_date, GLJournalEntry.id)
		)
		return self._safe_scalars(stmt, session, "SAF-T GL journal query")

	@staticmethod
	def _safe_scalars(stmt: Any, session: Any, context: str) -> list[Any]:
		try:
			return list(session.execute(stmt).scalars().all())
		except Exception as exc:
			log.warning("%s unavailable: %s", context, exc)
			return []

	@staticmethod
	def _text_value(obj: Any, *field_names: str) -> str:
		for field_name in field_names:
			value = getattr(obj, field_name, None)
			if value is not None:
				return str(value)
		return ""


class CsrdReportService:
	def generate_csrd_report(self, tenant_id: str, fiscal_year: int, session: Any) -> dict[str, Any]:
		report: dict[str, Any] = {
			"standard": "CSRD",
			"fiscal_year": fiscal_year,
			"tenant_id": tenant_id,
			"ESRS_E1": self._esrs_e1(tenant_id, session),
			"ESRS_S1": self._esrs_s1(tenant_id, session),
			"ESRS_G1": self._esrs_g1(tenant_id, session),
		}
		return report

	def _esrs_e1(self, tenant_id: str, session: Any) -> dict[str, Any]:
		try:
			result = session.execute(
				sa.text("SELECT SUM(co2_kg) FROM platform_emission_record WHERE tenant_id = :tid"),
				{"tid": tenant_id},
			).scalar() or 0
		except Exception:
			result = 0
		return {"scope1_co2_kg": result, "scope2_co2_kg": 0, "scope3_co2_kg": 0}

	def _esrs_s1(self, tenant_id: str, session: Any) -> dict[str, Any]:
		try:
			count = session.execute(
				sa.text("SELECT COUNT(*) FROM hcm_employee WHERE tenant_id = :tid AND status = 'ACTIVE'"),
				{"tid": tenant_id},
			).scalar() or 0
			female = session.execute(
				sa.text("SELECT COUNT(*) FROM hcm_employee WHERE tenant_id = :tid AND status = 'ACTIVE' AND gender = 'F'"),
				{"tid": tenant_id},
			).scalar() or 0
			gender_ratio_f = round(female / count, 4) if count else None
		except Exception:
			count = 0
			gender_ratio_f = None
		return {
			"headcount": count,
			"gender_ratio_f": gender_ratio_f,
			"pay_gap_ratio": None,  # requires payroll integration — ESRS S1-16 not yet computable
		}

	def _esrs_g1(self, tenant_id: str, session: Any) -> dict[str, Any]:
		try:
			ethics_count = session.execute(
				sa.text("SELECT COUNT(*) FROM grc_ethics_report WHERE tenant_id = :tid"),
				{"tid": tenant_id},
			).scalar() or 0
		except Exception:
			ethics_count = 0
		return {"whistleblower_system": True, "ethics_reports_received": ethics_count}


__all__ = ["SaftReportService", "CsrdReportService", "RegulatoryReportingError"]
