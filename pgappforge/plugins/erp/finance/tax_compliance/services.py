"""
pgappforge/plugins/erp/finance/tax_compliance/services.py

Automatic tax compliance submission for Africa-specific mandates.

Wires AR invoice approval → eTIMS (Kenya) / EFRIS (Uganda) / ZRA (Zambia).
The service detects the applicable mandate from COMPLIANCE_COUNTRY config.

Config:
	COMPLIANCE_COUNTRY = "KE"   # KE|UG|ZM|NG|GH — which mandate to enforce
	TAX_COMPLIANCE_ENABLED = True

	# Per-country configs (see individual connector docs):
	ETIMS_PIN = "..."            # for KE
	EFRIS_TIN = "..."            # for UG
	ZRA_TIN = "..."              # for ZM
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


class TaxComplianceService:
	"""Automatic tax invoice submission for Africa compliance mandates."""

	def submit_invoice(
		self,
		invoice_id: str,
		tenant_id: str,
		session,
		*,
		force_resubmit: bool = False,
	) -> dict[str, Any]:
		"""Submit an AR invoice to the applicable tax authority.

		Determines which authority to use from COMPLIANCE_COUNTRY config.
		Idempotent: skips already-submitted invoices unless force_resubmit=True.
		Non-fatal: logs errors but does not prevent invoice finalization.

		Returns: {submitted, authority, control_number, error}
		"""
		from flask import current_app
		country = current_app.config.get("COMPLIANCE_COUNTRY", "").upper()

		if not country:
			return {
				"submitted": False,
				"authority": None,
				"control_number": None,
				"error": "COMPLIANCE_COUNTRY not configured",
			}

		if not current_app.config.get("TAX_COMPLIANCE_ENABLED", False):
			return {
				"submitted": False,
				"authority": country,
				"control_number": None,
				"error": "TAX_COMPLIANCE_ENABLED=False",
			}

		# Check if already submitted
		if not force_resubmit:
			existing = self._get_submission_record(invoice_id, session)
			if existing and existing.get("status") == "SUCCESS":
				return {
					"submitted": True,
					"authority": country,
					"control_number": existing.get("control_number"),
					"error": None,
					"cached": True,
				}

		# Get invoice data
		invoice_data = self._load_invoice(invoice_id, tenant_id, session)
		if not invoice_data:
			return {
				"submitted": False,
				"authority": country,
				"control_number": None,
				"error": f"Invoice {invoice_id!r} not found",
			}

		# Route to appropriate authority
		try:
			if country == "KE":
				result = self._submit_to_etims(invoice_data)
			elif country == "UG":
				result = self._submit_to_efris(invoice_data)
			elif country == "ZM":
				result = self._submit_to_zra(invoice_data)
			elif country in ("NG", "GH"):
				result = {
					"submitted": True,
					"authority": country,
					"control_number": f"{country}-PENDING",
					"error": None,
					"note": "E-invoicing in progress for this country",
				}
			else:
				result = {
					"submitted": False,
					"authority": country,
					"control_number": None,
					"error": f"No compliance mandate configured for country {country}",
				}
		except Exception as exc:
			log.warning("Tax compliance submission failed for %s: %s", invoice_id, exc)
			result = {
				"submitted": False,
				"authority": country,
				"control_number": None,
				"error": str(exc),
			}

		# Persist submission record
		self._save_submission_record(invoice_id, tenant_id, country, result, session)

		# Update invoice with control number
		if result.get("submitted") and result.get("control_number"):
			self._update_invoice_control_number(invoice_id, result["control_number"], session)

		return result

	def _submit_to_etims(self, invoice: dict) -> dict:
		"""Submit to KRA eTIMS Kenya."""
		from pgappforge.plugins.connectors.etims.client import ETIMSClient
		client = ETIMSClient.from_config()
		return client.submit_invoice(
			invoice_number=invoice.get("invoice_number", ""),
			customer_pin=invoice.get("customer_pin", "000000000"),
			customer_name=invoice.get("customer_name", ""),
			items=invoice.get("line_items", []),
			invoice_date=invoice.get("invoice_date", ""),
		)

	def _submit_to_efris(self, invoice: dict) -> dict:
		"""Submit to URA EFRIS Uganda."""
		from pgappforge.plugins.connectors.efris.client import EFRISClient
		client = EFRISClient.from_config()
		return client.submit_invoice(
			invoice_number=invoice.get("invoice_number", ""),
			customer_tin=invoice.get("customer_tin", "0000000000"),
			customer_name=invoice.get("customer_name", ""),
			items=invoice.get("line_items", []),
			invoice_date=invoice.get("invoice_date", ""),
		)

	def _submit_to_zra(self, invoice: dict) -> dict:
		"""Submit to ZRA Smart Invoice Zambia."""
		from pgappforge.plugins.connectors.zra.client import ZRAClient
		client = ZRAClient.from_config()
		return client.submit_invoice(
			invoice_number=invoice.get("invoice_number", ""),
			customer_tpin=invoice.get("customer_tpin", "0000000000"),
			customer_name=invoice.get("customer_name", ""),
			items=invoice.get("line_items", []),
			invoice_date=invoice.get("invoice_date", ""),
		)

	def _load_invoice(self, invoice_id: str, tenant_id: str, session) -> dict | None:
		"""Load invoice data from ARInvoice model."""
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice
			invoice = session.execute(
				sa.select(ARInvoice).where(
					ARInvoice.id == invoice_id,
					ARInvoice.tenant_id == tenant_id,
				)
			).scalar_one_or_none()

			if invoice is None:
				return None

			return {
				"invoice_number": getattr(invoice, "invoice_number", str(invoice_id)[:8]),
				"customer_name": str(getattr(invoice, "customer_id", "") or ""),
				"customer_pin": getattr(invoice, "customer_pin", "") or "000000000",
				"customer_tin": getattr(invoice, "customer_tin", "") or "0000000000",
				"customer_tpin": getattr(invoice, "customer_tpin", "") or "0000000000",
				"invoice_date": str(getattr(invoice, "invoice_date", datetime.now(timezone.utc).date())),
				"total_amount_cents": getattr(invoice, "total_amount_cents", 0) or 0,
				"tax_amount_cents": getattr(invoice, "tax_amount_cents", 0) or 0,
				"line_items": getattr(invoice, "line_items", []) or [],
			}
		except Exception as exc:
			log.debug("_load_invoice failed: %s", exc)
			return None

	def _get_submission_record(self, invoice_id: str, session) -> dict | None:
		"""Check if invoice was already submitted."""
		try:
			row = session.execute(
				sa.text(
					"SELECT status, control_number FROM pgaf_tax_submission"
					" WHERE invoice_id = :id ORDER BY created_at DESC LIMIT 1"
				),
				{"id": invoice_id},
			).fetchone()
			return dict(zip(("status", "control_number"), row)) if row else None
		except Exception:
			return None

	def _save_submission_record(
		self,
		invoice_id: str,
		tenant_id: str,
		authority: str,
		result: dict,
		session,
	) -> None:
		"""Persist the submission attempt to pgaf_tax_submission."""
		try:
			from uuid6 import uuid7
			session.execute(
				sa.text("""
					INSERT INTO pgaf_tax_submission
					(id, tenant_id, invoice_id, authority, status, control_number, error_message, created_at)
					VALUES (:id, :tid, :inv_id, :auth, :status, :ctrl, :err, :ts)
				"""),
				{
					"id": str(uuid7()),
					"tid": tenant_id,
					"inv_id": invoice_id,
					"auth": authority,
					"status": "SUCCESS" if result.get("submitted") else "FAILED",
					"ctrl": result.get("control_number"),
					"err": result.get("error"),
					"ts": datetime.now(timezone.utc),
				},
			)
			session.flush()
		except Exception as exc:
			log.debug("_save_submission_record failed: %s", exc)

	def _update_invoice_control_number(
		self,
		invoice_id: str,
		control_number: str,
		session,
	) -> None:
		"""Write the tax authority control number back to the invoice."""
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice
			session.execute(
				sa.update(ARInvoice)
				.where(ARInvoice.id == invoice_id)
				.values(tax_control_number=control_number)
			)
		except Exception as exc:
			log.debug("_update_invoice_control_number failed: %s", exc)

	def create_compliance_tables(self, engine) -> None:
		"""Create pgaf_tax_submission audit table."""
		with engine.begin() as conn:
			conn.execute(sa.text("""
				CREATE TABLE IF NOT EXISTS pgaf_tax_submission (
					id              VARCHAR(36) PRIMARY KEY,
					tenant_id       VARCHAR(36) NOT NULL,
					invoice_id      VARCHAR(36) NOT NULL,
					authority       VARCHAR(10) NOT NULL,
					status          VARCHAR(10) NOT NULL,
					control_number  VARCHAR(100),
					error_message   TEXT,
					created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
				);
				CREATE INDEX IF NOT EXISTS ix_pgaf_tax_invoice
					ON pgaf_tax_submission(invoice_id);
			"""))

	def get_compliance_status(self, invoice_id: str, session) -> dict:
		"""Get tax compliance submission status for an invoice."""
		try:
			rows = session.execute(
				sa.text(
					"SELECT authority, status, control_number, error_message, created_at"
					" FROM pgaf_tax_submission WHERE invoice_id = :id ORDER BY created_at DESC"
				),
				{"id": invoice_id},
			).fetchall()
			return {
				"invoice_id": invoice_id,
				"submissions": [
					dict(zip(("authority", "status", "control_number", "error", "created_at"), r))
					for r in rows
				],
				"compliant": any(r[1] == "SUCCESS" for r in rows),
			}
		except Exception:
			return {"invoice_id": invoice_id, "submissions": [], "compliant": False}

	def subscribe_to_invoice_events(self) -> None:
		"""Subscribe to invoice approval events for automatic submission."""
		try:
			from pgappforge.plugins.erp.foundation.events import subscribe

			def _on_invoice_approved(event):
				invoice_id = str(
					getattr(event, "aggregate_id", "") or getattr(event, "invoice_id", "")
				)
				tenant_id = str(getattr(event, "tenant_id", ""))
				if not invoice_id or not tenant_id:
					return
				try:
					from flask import current_app
					session = current_app.appbuilder.get_session()
					result = self.submit_invoice(invoice_id, tenant_id, session)
					session.commit()
					if result.get("submitted"):
						log.info(
							"Tax compliance: invoice %s submitted to %s (%s)",
							invoice_id[:8],
							result.get("authority"),
							result.get("control_number"),
						)
				except Exception as exc:
					log.warning("Tax compliance auto-submit failed: %s", exc)

			subscribe("finance.ar.invoice.approved", _on_invoice_approved)
			subscribe("finance.ar.invoice.finalized", _on_invoice_approved)
			log.info("TaxComplianceService: subscribed to invoice approval events")
		except Exception as exc:
			log.debug("subscribe_to_invoice_events failed: %s", exc)


__all__ = ["TaxComplianceService"]
