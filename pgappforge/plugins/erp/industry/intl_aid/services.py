"""
pgappforge/plugins/erp/industry/intl_aid/services.py

IntlAidService — stateless business logic for the International Aid plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Callers own transaction boundaries (commit/rollback).

Key invariants:
  - ProjectTransactions are immutable (insert-only)
  - total_committed_cents and total_disbursed_cents are add-only
  - usd_value_cents is computed at recording time from exchange_rate
  - IATI XML output conforms to IATI Activity Standard 2.03
  - All monetary amounts are integer cents — never float
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree as ET

import sqlalchemy as sa
from sqlalchemy import func, select

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class IntlAidServiceError(Exception):
	"""Base error for International Aid domain violations."""


class ProjectNotFoundError(IntlAidServiceError):
	"""No AidProject with the given id."""


class OrganizationNotFoundError(IntlAidServiceError):
	"""No AidOrganization with the given id."""


class IndicatorNotFoundError(IntlAidServiceError):
	"""No ResultIndicator with the given id."""


class InvalidTransactionError(IntlAidServiceError):
	"""Transaction data is invalid."""


# ---------------------------------------------------------------------------
# IntlAidService
# ---------------------------------------------------------------------------

class IntlAidService:
	"""Stateless service for IATI-compliant international aid operations."""

	# ------------------------------------------------------------------
	# create_project
	# ------------------------------------------------------------------

	def create_project(
		self,
		*,
		tenant_id: str,
		iati_identifier: str,
		title: str,
		implementing_org_id: str,
		funding_org_id: str,
		recipient_country_code: str,
		total_budget_cents: int,
		funding_commitments: list[dict],
		description: str | None = None,
		recipient_region: str | None = None,
		sectors: list | None = None,
		sdg_targets: list[str] | None = None,
		start_date: date | None = None,
		end_date: date | None = None,
		humanitarian: bool = False,
		tied_status: str = "FREE",
		currency_code: str = "USD",
		session: Any,
	) -> Any:
		"""Create an AidProject and record initial funding commitments.

		Each item in funding_commitments must contain:
		  {amount_cents, currency_code, provider_id, receiver_id, transaction_date?}

		Side effects:
		  - Creates AidProject with status=PIPELINE
		  - Creates one ProjectTransaction(COMMITMENT) per funding_commitments entry
		  - Updates project.total_committed_cents
		  - Updates implementing_org.active_projects += 1
		  - Emits AidProjectCreatedEvent and CommitmentRecordedEvent per commitment

		Returns the created AidProject.
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization, AidProject, ProjectTransaction
		from pgappforge.plugins.erp.industry.intl_aid.events import AidProjectCreatedEvent, CommitmentRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		impl_org = session.get(AidOrganization, implementing_org_id)
		if impl_org is None:
			raise OrganizationNotFoundError(f"AidOrganization {implementing_org_id!r} not found")

		project = AidProject(
			tenant_id=tenant_id,
			iati_identifier=iati_identifier,
			title=title,
			description=description,
			implementing_org_id=implementing_org_id,
			funding_org_id=funding_org_id,
			recipient_country_code=recipient_country_code,
			recipient_region=recipient_region,
			sectors=sectors or [],
			sdg_targets=sdg_targets or [],
			start_date=start_date,
			end_date=end_date,
			status="PIPELINE",
			total_budget_cents=total_budget_cents,
			total_committed_cents=0,
			total_disbursed_cents=0,
			humanitarian=humanitarian,
			tied_status=tied_status,
		)
		session.add(project)
		session.flush()

		# Record funding commitments
		for fc in funding_commitments:
			amt = int(fc["amount_cents"])
			ccy = fc.get("currency_code", currency_code)
			rate = Decimal(str(fc.get("exchange_rate", 1)))
			usd_cents = int((Decimal(str(amt)) * rate).to_integral_value())
			txn_date = (
				date.fromisoformat(fc["transaction_date"])
				if fc.get("transaction_date")
				else date.today()
			)

			txn = ProjectTransaction(
				tenant_id=tenant_id,
				project_id=project.id,
				transaction_type="COMMITMENT",
				transaction_date=txn_date,
				value_cents=amt,
				currency_code=ccy,
				exchange_rate=rate,
				usd_value_cents=usd_cents,
				provider_id=fc["provider_id"],
				receiver_id=fc.get("receiver_id", implementing_org_id),
				description=fc.get("description"),
				reference=fc.get("reference"),
			)
			session.add(txn)
			session.flush()

			# Add-only invariant
			project.total_committed_cents = (project.total_committed_cents or 0) + amt

			emit_event(
				CommitmentRecordedEvent(
					aggregate_id=txn.id,
					aggregate_type="ProjectTransaction",
					tenant_id=tenant_id,
					transaction_id=txn.id,
					project_id=project.id,
					amount_cents=amt,
					currency_code=ccy,
					provider_id=fc["provider_id"],
					transaction_date=txn_date.isoformat(),
				),
				session,
			)

		# Increment implementing org active count
		impl_org.active_projects = (impl_org.active_projects or 0) + 1

		emit_event(
			AidProjectCreatedEvent(
				aggregate_id=project.id,
				aggregate_type="AidProject",
				tenant_id=tenant_id,
				project_id=project.id,
				iati_identifier=iati_identifier,
				implementing_org_id=implementing_org_id,
				funding_org_id=funding_org_id,
				recipient_country_code=recipient_country_code,
				total_budget_cents=total_budget_cents,
				currency_code=currency_code,
				humanitarian=humanitarian,
			),
			session,
		)

		log.info(
			"create_project: iati=%r project=%r commitments=%d",
			iati_identifier, project.id, len(funding_commitments),
		)
		return project

	# ------------------------------------------------------------------
	# record_disbursement
	# ------------------------------------------------------------------

	def record_disbursement(
		self,
		*,
		project_id: str,
		amount_cents: int,
		currency_code: str,
		receiver_id: str,
		provider_id: str | None = None,
		transaction_date: date | None = None,
		exchange_rate: Decimal | float = 1,
		description: str | None = None,
		reference: str | None = None,
		session: Any,
	) -> Any:
		"""Record an immutable disbursement transaction against a project.

		Side effects:
		  - Creates ProjectTransaction(DISBURSEMENT)
		  - Updates project.total_disbursed_cents (add-only)
		  - Updates implementing_org.total_disbursements_cents (add-only)
		  - Emits DisbursementRecordedEvent

		Returns the created ProjectTransaction.
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization, AidProject, ProjectTransaction
		from pgappforge.plugins.erp.industry.intl_aid.events import DisbursementRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		project = session.get(AidProject, project_id)
		if project is None:
			raise ProjectNotFoundError(f"AidProject {project_id!r} not found")

		rate = Decimal(str(exchange_rate))
		usd_cents = int((Decimal(str(amount_cents)) * rate).to_integral_value())
		txn_date = transaction_date or date.today()

		txn = ProjectTransaction(
			tenant_id=project.tenant_id,
			project_id=project_id,
			transaction_type="DISBURSEMENT",
			transaction_date=txn_date,
			value_cents=amount_cents,
			currency_code=currency_code,
			exchange_rate=rate,
			usd_value_cents=usd_cents,
			provider_id=provider_id or project.funding_org_id,
			receiver_id=receiver_id,
			description=description,
			reference=reference,
		)
		session.add(txn)
		session.flush()

		# Add-only invariants
		project.total_disbursed_cents = (project.total_disbursed_cents or 0) + amount_cents

		# Update org aggregate
		impl_org = session.get(AidOrganization, project.implementing_org_id)
		if impl_org is not None:
			impl_org.total_disbursements_cents = (impl_org.total_disbursements_cents or 0) + usd_cents

		emit_event(
			DisbursementRecordedEvent(
				aggregate_id=txn.id,
				aggregate_type="ProjectTransaction",
				tenant_id=project.tenant_id,
				transaction_id=txn.id,
				project_id=project_id,
				iati_identifier=project.iati_identifier,
				amount_cents=amount_cents,
				currency_code=currency_code,
				usd_value_cents=usd_cents,
				receiver_id=receiver_id,
				transaction_date=txn_date.isoformat(),
			),
			session,
		)

		log.info(
			"record_disbursement: project=%r amount=%d¢ %s usd=%d¢",
			project_id, amount_cents, currency_code, usd_cents,
		)
		return txn

	# ------------------------------------------------------------------
	# update_results
	# ------------------------------------------------------------------

	def update_results(
		self,
		*,
		project_id: str,
		indicator_updates: list[dict],
		session: Any,
	) -> list[Any]:
		"""Update current_value on result indicators.

		Each item in indicator_updates must contain:
		  {indicator_id, current_value, last_updated?}

		Side effects:
		  - Updates ResultIndicator.current_value and .last_updated
		  - Emits ResultsUpdatedEvent

		Returns list of updated ResultIndicator objects.
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidProject, ResultIndicator
		from pgappforge.plugins.erp.industry.intl_aid.events import ResultsUpdatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		project = session.get(AidProject, project_id)
		if project is None:
			raise ProjectNotFoundError(f"AidProject {project_id!r} not found")

		updated: list[Any] = []
		updated_ids: list[str] = []

		for upd in indicator_updates:
			indicator_id = upd.get("indicator_id")
			if not indicator_id:
				continue
			ind = session.get(ResultIndicator, indicator_id)
			if ind is None:
				raise IndicatorNotFoundError(f"ResultIndicator {indicator_id!r} not found")
			if ind.project_id != project_id:
				raise IntlAidServiceError(
					f"ResultIndicator {indicator_id!r} does not belong to project {project_id!r}"
				)

			ind.current_value = Decimal(str(upd["current_value"]))
			ind.last_updated = (
				date.fromisoformat(upd["last_updated"])
				if upd.get("last_updated")
				else date.today()
			)
			updated.append(ind)
			updated_ids.append(indicator_id)

		if updated:
			emit_event(
				ResultsUpdatedEvent(
					aggregate_id=project_id,
					aggregate_type="AidProject",
					tenant_id=project.tenant_id,
					project_id=project_id,
					iati_identifier=project.iati_identifier,
					indicators_updated=len(updated),
					updated_indicator_ids=updated_ids,
				),
				session,
			)

		log.info("update_results: project=%r updated=%d indicators", project_id, len(updated))
		return updated

	# ------------------------------------------------------------------
	# generate_iati_xml
	# ------------------------------------------------------------------

	def generate_iati_xml(self, project_id: str, session: Any) -> str:
		"""Generate IATI Activity Standard 2.03 XML for a project.

		Returns a well-formed XML string suitable for submission to the
		IATI Registry or d-portal.org.
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization, AidProject, ProjectTransaction, ResultIndicator

		project = session.get(AidProject, project_id)
		if project is None:
			raise ProjectNotFoundError(f"AidProject {project_id!r} not found")

		impl_org = session.get(AidOrganization, project.implementing_org_id)
		funding_org = session.get(AidOrganization, project.funding_org_id)

		transactions = session.execute(
			select(ProjectTransaction)
			.where(ProjectTransaction.project_id == project_id)
			.order_by(ProjectTransaction.transaction_date)
		).scalars().all()

		indicators = session.execute(
			select(ResultIndicator).where(ResultIndicator.project_id == project_id)
		).scalars().all()

		# Build XML tree
		activities = ET.Element("iati-activities", {
			"version": "2.03",
			"generated-datetime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
		})

		activity = ET.SubElement(activities, "iati-activity", {
			"last-updated-datetime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
			"default-currency": "USD",
			"humanitarian": "1" if project.humanitarian else "0",
		})

		# iati-identifier
		ET.SubElement(activity, "iati-identifier").text = project.iati_identifier

		# reporting-org
		if impl_org:
			ro = ET.SubElement(activity, "reporting-org", {
				"ref": impl_org.iati_identifier,
				"type": self._iati_org_type_code(impl_org.org_type),
			})
			ET.SubElement(ro, "narrative").text = impl_org.iati_identifier

		# title
		title_el = ET.SubElement(activity, "title")
		ET.SubElement(title_el, "narrative").text = project.title

		# description
		if project.description:
			desc_el = ET.SubElement(activity, "description", {"type": "1"})
			ET.SubElement(desc_el, "narrative").text = project.description

		# activity-status
		ET.SubElement(activity, "activity-status", {"code": self._iati_status_code(project.status)})

		# activity-date
		if project.start_date:
			ET.SubElement(activity, "activity-date", {
				"iso-date": project.start_date.isoformat(),
				"type": "2",  # actual start
			})
		if project.end_date:
			ET.SubElement(activity, "activity-date", {
				"iso-date": project.end_date.isoformat(),
				"type": "4",  # actual end / planned end
			})

		# participating-org
		if funding_org:
			po = ET.SubElement(activity, "participating-org", {
				"ref": funding_org.iati_identifier,
				"type": self._iati_org_type_code(funding_org.org_type),
				"role": "1",  # funding
			})
			ET.SubElement(po, "narrative").text = funding_org.iati_identifier

		# recipient-country
		ET.SubElement(activity, "recipient-country", {"code": project.recipient_country_code})

		# sector
		for sector in (project.sectors or []):
			ET.SubElement(activity, "sector", {
				"vocabulary": str(sector.get("vocabulary", "1")),
				"code": str(sector.get("code", "")),
				"percentage": str(sector.get("percentage", 100)),
			})

		# transaction
		_txn_type_map = {
			"COMMITMENT": "2",
			"DISBURSEMENT": "3",
			"EXPENDITURE": "4",
			"REPAYMENT": "7",
		}
		for t in transactions:
			txn_el = ET.SubElement(activity, "transaction")
			ET.SubElement(txn_el, "transaction-type", {"code": _txn_type_map.get(t.transaction_type, "3")})
			ET.SubElement(txn_el, "transaction-date", {"iso-date": t.transaction_date.isoformat()})
			ET.SubElement(txn_el, "value", {
				"currency": t.currency_code,
				"value-date": t.transaction_date.isoformat(),
			}).text = str(round(t.value_cents / 100, 2))
			if t.description:
				desc_txn = ET.SubElement(txn_el, "description")
				ET.SubElement(desc_txn, "narrative").text = t.description

		# budget (from total_budget_cents)
		if project.total_budget_cents:
			budget_el = ET.SubElement(activity, "budget", {"type": "1", "status": "2"})
			if project.start_date:
				ET.SubElement(budget_el, "period-start", {"iso-date": project.start_date.isoformat()})
			if project.end_date:
				ET.SubElement(budget_el, "period-end", {"iso-date": project.end_date.isoformat()})
			ET.SubElement(budget_el, "value", {
				"currency": "USD",
				"value-date": (project.start_date or date.today()).isoformat(),
			}).text = str(round(project.total_budget_cents / 100, 2))

		# result
		for ind in indicators:
			result_el = ET.SubElement(activity, "result", {
				"type": self._iati_result_type(ind.indicator_type),
				"aggregation-status": "1",
			})
			result_title = ET.SubElement(result_el, "title")
			ET.SubElement(result_title, "narrative").text = ind.indicator_name
			indicator_el = ET.SubElement(result_el, "indicator", {"measure": "1", "ascending": "1"})
			title_ind = ET.SubElement(indicator_el, "title")
			ET.SubElement(title_ind, "narrative").text = ind.indicator_name
			ET.SubElement(indicator_el, "baseline", {
				"year": str(ind.baseline_year),
				"value": str(ind.baseline_value),
			})
			period_el = ET.SubElement(indicator_el, "period")
			ET.SubElement(period_el, "period-start", {"iso-date": f"{ind.baseline_year}-01-01"})
			ET.SubElement(period_el, "period-end", {"iso-date": f"{ind.target_year}-12-31"})
			ET.SubElement(period_el, "target", {"value": str(ind.target_value)})
			ET.SubElement(period_el, "actual", {"value": str(ind.current_value)})

		# tied-status
		_tied_map = {"FREE": "5", "PARTIALLY_TIED": "3", "TIED": "4"}
		ET.SubElement(activity, "default-tied-status", {"code": _tied_map.get(project.tied_status, "5")})

		xml_str = ET.tostring(activities, encoding="unicode", xml_declaration=False)
		log.info("generate_iati_xml: project=%r iati=%r", project_id, project.iati_identifier)
		return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

	@staticmethod
	def _iati_org_type_code(org_type: str) -> str:
		return {
			"GOVERNMENT": "10",
			"NGO": "21",
			"MULTILATERAL": "40",
			"BILATERAL": "10",
			"PRIVATE": "70",
		}.get(org_type, "21")

	@staticmethod
	def _iati_status_code(status: str) -> str:
		return {
			"PIPELINE": "1",
			"IMPLEMENTATION": "2",
			"COMPLETION": "3",
			"CLOSED": "4",
		}.get(status, "2")

	@staticmethod
	def _iati_result_type(indicator_type: str) -> str:
		return {"OUTPUT": "1", "OUTCOME": "2", "IMPACT": "3"}.get(indicator_type, "1")

	# ------------------------------------------------------------------
	# calculate_aid_effectiveness
	# ------------------------------------------------------------------

	def calculate_aid_effectiveness(
		self,
		*,
		org_id: str,
		period_years: int = 5,
		session: Any,
	) -> dict:
		"""Measure aid effectiveness for an organisation over N years.

		Computes:
		  - disbursement_rate: total_disbursed / total_committed (%)
		  - results_achievement_rate: indicators at/above target / total indicators (%)
		  - avg_cost_per_beneficiary_usd_cents
		  - projects breakdown by status

		Returns a dict suitable for dashboard rendering.
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization, AidProject, BeneficiaryCount, ResultIndicator

		org = session.get(AidOrganization, org_id)
		if org is None:
			raise OrganizationNotFoundError(f"AidOrganization {org_id!r} not found")

		cutoff_year = date.today().year - period_years
		cutoff_date = date(cutoff_year, 1, 1)

		projects = session.execute(
			select(AidProject).where(
				AidProject.implementing_org_id == org_id,
				AidProject.start_date >= cutoff_date,
			)
		).scalars().all()

		project_ids = [p.id for p in projects]

		total_committed = sum(p.total_committed_cents or 0 for p in projects)
		total_disbursed = sum(p.total_disbursed_cents or 0 for p in projects)
		disbursement_rate = (
			round(total_disbursed / max(total_committed, 1) * 100, 1)
			if total_committed
			else 0.0
		)

		# Results achievement
		indicators: list[Any] = []
		if project_ids:
			indicators = session.execute(
				select(ResultIndicator).where(ResultIndicator.project_id.in_(project_ids))
			).scalars().all()

		achieved = sum(1 for i in indicators if i.current_value >= i.target_value)
		results_rate = (
			round(achieved / max(len(indicators), 1) * 100, 1)
			if indicators
			else None
		)

		# Beneficiaries
		total_bene = 0
		if project_ids:
			bene_rows = session.execute(
				select(
					func.max(BeneficiaryCount.total_beneficiaries).label("max_bene"),
					BeneficiaryCount.project_id,
				)
				.where(BeneficiaryCount.project_id.in_(project_ids))
				.group_by(BeneficiaryCount.project_id)
			).all()
			total_bene = sum(r.max_bene or 0 for r in bene_rows)

		avg_cost_per_bene = (
			total_disbursed // total_bene if total_bene else None
		)

		# Status breakdown
		by_status: dict[str, int] = {}
		for p in projects:
			by_status[p.status] = by_status.get(p.status, 0) + 1

		return {
			"org_id": org_id,
			"iati_identifier": org.iati_identifier,
			"period_years": period_years,
			"project_count": len(projects),
			"total_committed_cents": total_committed,
			"total_disbursed_cents": total_disbursed,
			"disbursement_rate_pct": disbursement_rate,
			"indicator_count": len(indicators),
			"indicators_achieved": achieved,
			"results_achievement_rate_pct": results_rate,
			"total_beneficiaries_reached": total_bene,
			"avg_cost_per_beneficiary_usd_cents": avg_cost_per_bene,
			"projects_by_status": by_status,
		}

	# ------------------------------------------------------------------
	# get_portfolio_dashboard
	# ------------------------------------------------------------------

	def get_portfolio_dashboard(self, org_id: str, session: Any) -> dict:
		"""Return portfolio KPI dashboard for an organisation.

		Returns::

		    {
		        "org_id": "...",
		        "iati_identifier": "...",
		        "active_projects": 12,
		        "total_budget_cents": 50000000,
		        "total_committed_cents": 45000000,
		        "total_disbursed_cents": 30000000,
		        "disbursement_gap_cents": 15000000,
		        "disbursement_rate_pct": 66.7,
		        "countries": ["KE", "UG", "TZ"],
		        "sdg_targets": ["1.1", "2.3"],
		        "humanitarian_projects": 2,
		        "results_summary": {
		            "indicators": 45,
		            "on_track": 30,
		            "off_track": 15,
		        },
		    }
		"""
		from pgappforge.plugins.erp.industry.intl_aid.models import AidOrganization, AidProject, ResultIndicator

		org = session.get(AidOrganization, org_id)
		if org is None:
			raise OrganizationNotFoundError(f"AidOrganization {org_id!r} not found")

		active_projects = session.execute(
			select(AidProject).where(
				AidProject.implementing_org_id == org_id,
				AidProject.status.in_(["PIPELINE", "IMPLEMENTATION"]),
			)
		).scalars().all()

		all_projects = session.execute(
			select(AidProject).where(AidProject.implementing_org_id == org_id)
		).scalars().all()

		project_ids = [p.id for p in all_projects]
		total_budget = sum(p.total_budget_cents or 0 for p in all_projects)
		total_committed = sum(p.total_committed_cents or 0 for p in all_projects)
		total_disbursed = sum(p.total_disbursed_cents or 0 for p in all_projects)
		disbursement_gap = max(0, total_committed - total_disbursed)
		disbursement_rate = (
			round(total_disbursed / max(total_committed, 1) * 100, 1)
			if total_committed
			else 0.0
		)

		countries = sorted({p.recipient_country_code for p in all_projects if p.recipient_country_code})
		sdg_targets_set: set[str] = set()
		for p in all_projects:
			for t in (p.sdg_targets or []):
				sdg_targets_set.add(t)
		humanitarian_count = sum(1 for p in all_projects if p.humanitarian)

		# Results summary
		indicators: list[Any] = []
		if project_ids:
			indicators = session.execute(
				select(ResultIndicator).where(ResultIndicator.project_id.in_(project_ids))
			).scalars().all()

		on_track = sum(1 for i in indicators if i.current_value >= i.target_value)

		return {
			"org_id": org_id,
			"iati_identifier": org.iati_identifier,
			"org_type": org.org_type,
			"active_projects": len(active_projects),
			"total_projects": len(all_projects),
			"total_budget_cents": total_budget,
			"total_committed_cents": total_committed,
			"total_disbursed_cents": total_disbursed,
			"disbursement_gap_cents": disbursement_gap,
			"disbursement_rate_pct": disbursement_rate,
			"countries": countries,
			"sdg_targets": sorted(sdg_targets_set),
			"humanitarian_projects": humanitarian_count,
			"results_summary": {
				"indicators": len(indicators),
				"on_track": on_track,
				"off_track": len(indicators) - on_track,
			},
		}


__all__ = [
	"IntlAidService",
	"IntlAidServiceError",
	"ProjectNotFoundError",
	"OrganizationNotFoundError",
	"IndicatorNotFoundError",
	"InvalidTransactionError",
]
