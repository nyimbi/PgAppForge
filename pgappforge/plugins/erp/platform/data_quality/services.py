"""
pgappforge/plugins/erp/platform/data_quality/services.py

Read-only data-quality checks across ERP domain models.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualityModelSpec:
	domain: str
	label: str
	model: type
	required_fields: tuple[str, ...]
	duplicate_keys: tuple[tuple[str, ...], ...] = ()
	stale_field: str = "updated_at"
	stale_after_days: int = 90
	tenant_field: str = "tenant_id"
	status_field: str | None = None
	active_statuses: tuple[Any, ...] = ()


class DataQualityService:
	"""Compute live completeness, duplicate, and stale-record metrics."""

	def __init__(self, specs: list[QualityModelSpec] | None = None) -> None:
		self._specs = specs

	def get_quality_summary(
		self,
		session: Session,
		tenant_id: str | None = None,
		*,
		as_of: datetime | None = None,
		duplicate_limit: int = 10,
		stale_limit: int = 25,
	) -> dict[str, Any]:
		"""Return a dashboard-ready data-quality snapshot."""
		as_of = as_of or datetime.now(timezone.utc)
		specs = self._specs or self._default_specs()
		completeness = self.check_completeness(session, tenant_id, specs=specs)
		duplicates = self.detect_duplicates(
			session,
			tenant_id,
			specs=specs,
			limit_per_key=duplicate_limit,
		)
		stale = self.find_stale_records(
			session,
			tenant_id,
			specs=specs,
			as_of=as_of,
			limit_per_model=stale_limit,
		)
		domain_scores = self._domain_scores(completeness["models"])
		total_records = sum(item["total_records"] for item in completeness["models"])
		weighted_completeness = self._weighted_score(completeness["models"])
		duplicate_records = duplicates["duplicate_records"]
		stale_records = stale["stale_records"]
		duplicate_score = self._inverse_rate_score(duplicate_records, total_records)
		stale_score = self._inverse_rate_score(stale_records, total_records)
		overall_score = round(
			(weighted_completeness * 0.70)
			+ (duplicate_score * 0.15)
			+ (stale_score * 0.15),
			1,
		)
		errors = [
			*completeness["errors"],
			*duplicates["errors"],
			*stale["errors"],
		]
		return {
			"generated_at": as_of.isoformat(),
			"tenant_id": tenant_id,
			"model_count": len(specs),
			"total_records": total_records,
			"overall_score": overall_score,
			"completeness_score": weighted_completeness,
			"duplicate_score": duplicate_score,
			"stale_score": stale_score,
			"domain_scores": domain_scores,
			"completeness": completeness["models"],
			"duplicates": duplicates["groups"],
			"duplicate_groups": duplicates["duplicate_groups"],
			"duplicate_records": duplicate_records,
			"stale": stale["records"],
			"stale_records": stale_records,
			"errors": errors,
		}

	def check_completeness(
		self,
		session: Session,
		tenant_id: str | None = None,
		*,
		specs: list[QualityModelSpec] | None = None,
	) -> dict[str, Any]:
		"""Score required-field completeness for each configured model."""
		rows: list[dict[str, Any]] = []
		errors: list[str] = []
		for spec in specs or self._default_specs():
			fields = self._existing_fields(spec.model, spec.required_fields)
			if not fields:
				rows.append(self._empty_completeness_row(spec, "No configured fields exist on model"))
				continue
			try:
				total_expr = sa.func.count().label("_total_records")
				present_exprs = [
					sa.func.coalesce(
						sa.func.sum(sa.case((self._present_condition(getattr(spec.model, field)), 1), else_=0)),
						0,
					).label(field)
					for field in fields
				]
				stmt = sa.select(total_expr, *present_exprs).select_from(spec.model)
				stmt = self._apply_scope(stmt, spec, tenant_id)
				result = session.execute(stmt).one()
				mapping = result._mapping
				total = int(mapping["_total_records"] or 0)
				field_scores = []
				for field in fields:
					present = int(mapping[field] or 0)
					missing = max(total - present, 0)
					score = 100.0 if total == 0 else round((present / total) * 100, 1)
					field_scores.append({
						"field": field,
						"present": present,
						"missing": missing,
						"score": score,
					})
				model_score = 100.0 if not field_scores else round(
					sum(item["score"] for item in field_scores) / len(field_scores),
					1,
				)
				rows.append({
					"domain": spec.domain,
					"model": spec.label,
					"total_records": total,
					"score": model_score,
					"fields": field_scores,
					"missing_fields": [
						item for item in field_scores if item["missing"] > 0
					],
				})
			except Exception as exc:
				log.debug("Data-quality completeness failed for %s", spec.label, exc_info=True)
				errors.append(f"{spec.label}: completeness check failed: {exc}")
				rows.append(self._empty_completeness_row(spec, "Completeness query failed"))
		return {"models": rows, "errors": errors}

	def detect_duplicates(
		self,
		session: Session,
		tenant_id: str | None = None,
		*,
		specs: list[QualityModelSpec] | None = None,
		limit_per_key: int = 10,
	) -> dict[str, Any]:
		"""Return duplicate key groups for configured models."""
		groups: list[dict[str, Any]] = []
		errors: list[str] = []
		for spec in specs or self._default_specs():
			for key_fields in spec.duplicate_keys:
				fields = self._existing_fields(spec.model, key_fields)
				if len(fields) != len(key_fields):
					continue
				try:
					columns = [getattr(spec.model, field) for field in fields]
					count_expr = sa.func.count().label("record_count")
					stmt = sa.select(
						*[col.label(field) for col, field in zip(columns, fields)],
						count_expr,
					).select_from(spec.model)
					stmt = self._apply_scope(stmt, spec, tenant_id)
					for col in columns:
						stmt = stmt.where(self._present_condition(col))
					stmt = (
						stmt.group_by(*columns)
						.having(sa.func.count() > 1)
						.order_by(sa.func.count().desc())
						.limit(limit_per_key)
					)
					for row in session.execute(stmt).all():
						mapping = row._mapping
						record_count = int(mapping["record_count"] or 0)
						groups.append({
							"domain": spec.domain,
							"model": spec.label,
							"key_fields": list(fields),
							"key": {
								field: self._stringify(mapping[field])
								for field in fields
							},
							"record_count": record_count,
						})
				except Exception as exc:
					log.debug("Data-quality duplicate check failed for %s", spec.label, exc_info=True)
					errors.append(f"{spec.label}: duplicate check failed: {exc}")
		return {
			"groups": groups,
			"duplicate_groups": len(groups),
			"duplicate_records": sum(item["record_count"] for item in groups),
			"errors": errors,
		}

	def find_stale_records(
		self,
		session: Session,
		tenant_id: str | None = None,
		*,
		specs: list[QualityModelSpec] | None = None,
		as_of: datetime | None = None,
		limit_per_model: int = 25,
	) -> dict[str, Any]:
		"""Return stale active records older than each model threshold."""
		as_of = as_of or datetime.now(timezone.utc)
		records: list[dict[str, Any]] = []
		errors: list[str] = []
		total_stale = 0
		for spec in specs or self._default_specs():
			if not hasattr(spec.model, spec.stale_field):
				continue
			try:
				stale_col = getattr(spec.model, spec.stale_field)
				threshold = as_of - timedelta(days=spec.stale_after_days)
				count_stmt = sa.select(sa.func.count()).select_from(spec.model).where(
					stale_col < threshold
				)
				count_stmt = self._apply_scope(count_stmt, spec, tenant_id)
				stale_count = int(session.execute(count_stmt).scalar_one() or 0)
				total_stale += stale_count
				if stale_count == 0:
					continue
				id_col = getattr(spec.model, "id", None)
				label_col = self._display_column(spec)
				selected = [id_col.label("record_id"), stale_col.label("stale_at")]
				if label_col is not None:
					selected.append(label_col.label("record_label"))
				stmt = sa.select(*selected).select_from(spec.model).where(stale_col < threshold)
				stmt = self._apply_scope(stmt, spec, tenant_id)
				stmt = stmt.order_by(stale_col.asc()).limit(limit_per_model)
				for row in session.execute(stmt).all():
					mapping = row._mapping
					records.append({
						"domain": spec.domain,
						"model": spec.label,
						"record_id": self._stringify(mapping["record_id"]),
						"label": self._stringify(mapping.get("record_label", "")),
						"stale_field": spec.stale_field,
						"stale_at": self._stringify(mapping["stale_at"]),
						"stale_after_days": spec.stale_after_days,
						"model_stale_count": stale_count,
					})
			except Exception as exc:
				log.debug("Data-quality stale check failed for %s", spec.label, exc_info=True)
				errors.append(f"{spec.label}: stale-record check failed: {exc}")
		return {"records": records, "stale_records": total_stale, "errors": errors}

	def _default_specs(self) -> list[QualityModelSpec]:
		specs: list[QualityModelSpec] = []
		try:
			from pgappforge.plugins.erp.foundation.models import Party
			specs.append(QualityModelSpec(
				"Foundation",
				"Parties",
				Party,
				("party_type", "name"),
				(("name", "tax_id"), ("name", "registration_number")),
				stale_after_days=180,
			))
		except Exception:
			log.debug("Foundation Party model unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice, APSupplier
			specs.extend([
				QualityModelSpec(
					"Finance",
					"AP Suppliers",
					APSupplier,
					("account_number", "name", "status", "currency_code"),
					(("account_number",), ("name", "tax_id")),
					stale_after_days=180,
					status_field="status",
					active_statuses=("active", "under_review", "blocked"),
				),
				QualityModelSpec(
					"Finance",
					"AP Invoices",
					APInvoice,
					("invoice_number_supplier", "supplier_id", "invoice_date", "due_date", "currency_code", "total_cents", "status"),
					(("supplier_id", "invoice_number_supplier"),),
					stale_after_days=60,
					status_field="status",
					active_statuses=("RECEIVED", "MATCHING", "APPROVED", "PAYMENT_SCHEDULED", "DISPUTED"),
				),
			])
		except Exception:
			log.debug("AP models unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.finance.ar.models import ARCustomer, ARInvoice
			specs.extend([
				QualityModelSpec(
					"Finance",
					"AR Customers",
					ARCustomer,
					("customer_number", "name", "status", "currency_code"),
					(("customer_number",), ("name", "tax_id")),
					stale_after_days=180,
					status_field="status",
					active_statuses=("ACTIVE", "CREDIT_HOLD"),
				),
				QualityModelSpec(
					"Finance",
					"AR Invoices",
					ARInvoice,
					("invoice_number", "customer_id", "invoice_date", "due_date", "currency_code", "total_cents", "status"),
					(("invoice_number",),),
					stale_after_days=60,
					status_field="status",
					active_statuses=("DRAFT", "ISSUED", "PARTIAL", "OVERDUE", "DISPUTED"),
				),
			])
		except Exception:
			log.debug("AR models unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLJournalEntry
			specs.append(QualityModelSpec(
				"Finance",
				"GL Journal Entries",
				GLJournalEntry,
				("batch_id", "entry_type", "posting_date", "status"),
				(("entry_number",),),
				stale_after_days=45,
				status_field="status",
				active_statuses=("DRAFT",),
			))
		except Exception:
			log.debug("GL models unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.crm.sales.models import Lead, Opportunity, SalesAccount, SalesContact
			specs.extend([
				QualityModelSpec(
					"CRM",
					"Accounts",
					SalesAccount,
					("name", "account_type", "status"),
					(("account_number",), ("name", "email")),
					stale_after_days=180,
					status_field="status",
					active_statuses=("ACTIVE",),
				),
				QualityModelSpec(
					"CRM",
					"Contacts",
					SalesContact,
					("first_name", "last_name", "account_id", "status"),
					(("email",), ("first_name", "last_name", "account_id")),
					stale_after_days=120,
					status_field="status",
					active_statuses=("ACTIVE",),
				),
				QualityModelSpec(
					"CRM",
					"Leads",
					Lead,
					("company", "email", "source", "status", "assigned_to"),
					(("email",), ("company", "phone")),
					stale_after_days=30,
					status_field="status",
					active_statuses=("NEW", "CONTACTED", "WORKING", "QUALIFIED"),
				),
				QualityModelSpec(
					"CRM",
					"Opportunities",
					Opportunity,
					("account_id", "opportunity_name", "stage", "amount_cents", "expected_close_date", "owner_id"),
					(("account_id", "opportunity_name"),),
					stale_after_days=45,
					status_field="stage",
					active_statuses=("PROSPECTING", "QUALIFICATION", "DEMO", "PROPOSAL", "NEGOTIATION"),
				),
			])
		except Exception:
			log.debug("CRM sales models unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.hcm.personnel.models import Employee
			specs.append(QualityModelSpec(
				"HCM",
				"Employees",
				Employee,
				("employee_number", "entity_id", "employment_type", "employment_status", "start_date", "manager_id"),
				(("employee_number",), ("party_id", "entity_id")),
				stale_after_days=180,
				status_field="employment_status",
				active_statuses=("ACTIVE", "ON_LEAVE"),
			))
		except Exception:
			log.debug("HCM employee model unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.operations.inventory.models import Product, Warehouse
			specs.extend([
				QualityModelSpec(
					"Operations",
					"Products",
					Product,
					("sku", "name", "uom", "currency_code", "valuation_method"),
					(("sku",), ("barcode",), ("name", "brand")),
					stale_after_days=180,
				),
				QualityModelSpec(
					"Operations",
					"Warehouses",
					Warehouse,
					("code", "name", "warehouse_type", "address"),
					(("code",),),
					stale_after_days=180,
				),
			])
		except Exception:
			log.debug("Inventory models unavailable for data-quality checks", exc_info=True)
		try:
			from pgappforge.plugins.erp.operations.scm.models import PurchaseOrder, Supplier
			specs.extend([
				QualityModelSpec(
					"Operations",
					"SCM Suppliers",
					Supplier,
					("supplier_code", "name", "supplier_type", "status", "currency_code"),
					(("supplier_code",), ("name", "country_code")),
					stale_after_days=180,
					status_field="status",
					active_statuses=("ACTIVE", "QUALIFIED", "SUSPENDED"),
				),
				QualityModelSpec(
					"Operations",
					"Purchase Orders",
					PurchaseOrder,
					("po_number", "supplier_id", "order_date", "expected_delivery_date", "status", "total_amount_cents"),
					(("po_number",),),
					stale_after_days=45,
					status_field="status",
					active_statuses=("DRAFT", "SENT", "ACKNOWLEDGED", "PARTIAL"),
				),
			])
		except Exception:
			log.debug("SCM models unavailable for data-quality checks", exc_info=True)
		return specs

	def _apply_scope(self, stmt: sa.Select, spec: QualityModelSpec, tenant_id: str | None) -> sa.Select:
		if tenant_id and hasattr(spec.model, spec.tenant_field):
			stmt = stmt.where(getattr(spec.model, spec.tenant_field) == tenant_id)
		if spec.status_field and spec.active_statuses and hasattr(spec.model, spec.status_field):
			stmt = stmt.where(getattr(spec.model, spec.status_field).in_(spec.active_statuses))
		return stmt

	def _existing_fields(self, model: type, fields: tuple[str, ...]) -> tuple[str, ...]:
		return tuple(field for field in fields if hasattr(model, field))

	def _present_condition(self, column: Any) -> Any:
		as_text = sa.func.trim(sa.cast(column, sa.String()))
		return sa.and_(column.isnot(None), as_text != "")

	def _display_column(self, spec: QualityModelSpec) -> Any:
		for field in (
			"name",
			"invoice_number",
			"invoice_number_supplier",
			"account_number",
			"employee_number",
			"sku",
			"po_number",
			"code",
			"entry_number",
			"opportunity_name",
		):
			if hasattr(spec.model, field):
				return getattr(spec.model, field)
		return None

	def _empty_completeness_row(self, spec: QualityModelSpec, error: str) -> dict[str, Any]:
		return {
			"domain": spec.domain,
			"model": spec.label,
			"total_records": 0,
			"score": 0.0,
			"fields": [],
			"missing_fields": [],
			"error": error,
		}

	def _domain_scores(self, model_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
		grouped: dict[str, dict[str, float]] = {}
		for row in model_rows:
			domain = row["domain"]
			bucket = grouped.setdefault(domain, {"records": 0.0, "weighted": 0.0, "models": 0.0})
			records = float(row["total_records"])
			bucket["records"] += records
			bucket["weighted"] += records * float(row["score"])
			bucket["models"] += 1
		scores: list[dict[str, Any]] = []
		for domain, bucket in grouped.items():
			if bucket["records"]:
				score = bucket["weighted"] / bucket["records"]
			else:
				domain_rows = [row for row in model_rows if row["domain"] == domain]
				score = sum(float(row["score"]) for row in domain_rows) / max(len(domain_rows), 1)
			scores.append({
				"domain": domain,
				"score": round(score, 1),
				"total_records": int(bucket["records"]),
				"models": int(bucket["models"]),
			})
		return sorted(scores, key=lambda item: item["domain"])

	def _weighted_score(self, model_rows: list[dict[str, Any]]) -> float:
		total_records = sum(float(row["total_records"]) for row in model_rows)
		if total_records == 0:
			if not model_rows:
				return 0.0
			return round(sum(float(row["score"]) for row in model_rows) / len(model_rows), 1)
		weighted = sum(float(row["score"]) * float(row["total_records"]) for row in model_rows)
		return round(weighted / total_records, 1)

	def _inverse_rate_score(self, findings: int, total_records: int) -> float:
		if total_records <= 0:
			return 100.0
		return round(max(0.0, 100.0 - ((findings / total_records) * 100.0)), 1)

	def _stringify(self, value: Any) -> str:
		if value is None:
			return ""
		if isinstance(value, datetime):
			return value.isoformat()
		return str(value)


__all__ = ["DataQualityService", "QualityModelSpec"]
