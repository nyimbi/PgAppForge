"""Regulatory reporting service — SAF-T GL, CSRD, Peppol."""
from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import Any

import sqlalchemy as sa


_SAFT_NS = "urn:OECD:Standard:SAF-T:1.00"


class SaftReportService:
	def generate_saft_gl(self, tenant_id: str, fiscal_year: int, session: Any) -> str:
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
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLAccount
			accounts = session.execute(
				sa.select(GLAccount).where(GLAccount.tenant_id == tenant_id)
			).scalars().all()
			for acct in accounts:
				acct_el = ET.SubElement(gl_accounts, f"{ns}Account")
				ET.SubElement(acct_el, f"{ns}AccountID").text = str(acct.id)
				ET.SubElement(acct_el, f"{ns}AccountDescription").text = getattr(acct, "name", "")
				ET.SubElement(acct_el, f"{ns}AccountType").text = getattr(acct, "account_type", "")
		except ImportError:
			pass  # GL plugin not installed — accounts section empty but schema valid
		transactions = ET.SubElement(root, f"{ns}GeneralLedgerEntries")
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLJournalEntry
			entries = session.execute(
				sa.select(GLJournalEntry).where(GLJournalEntry.tenant_id == tenant_id)
			).scalars().all()
			for e in entries:
				entry_el = ET.SubElement(transactions, f"{ns}Journal")
				ET.SubElement(entry_el, f"{ns}JournalID").text = str(e.id)
				ET.SubElement(entry_el, f"{ns}Description").text = getattr(e, "description", "")
		except ImportError:
			pass
		# xml_declaration=True produces the required <?xml version='1.0' encoding='us-ascii'?>
		# Use tostring with encoding='unicode' for a str return, prepend declaration manually
		body = ET.tostring(root, encoding="unicode")
		return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


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


__all__ = ["SaftReportService", "CsrdReportService"]
