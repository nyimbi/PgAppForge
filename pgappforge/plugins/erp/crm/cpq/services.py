"""
pgappforge/plugins/erp/crm/cpq/services.py

CPQService — stateless business logic for the Configure-Price-Quote plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout. Float is never used.

Key methods
-----------
  generate_quote(opportunity_id, line_items, session) -> Quote
      Create a DRAFT quote from an opportunity + list of line items.
      Applies active pricing rules from the current catalog.

  price_line(product_id, quantity, config, catalog_id, session) -> dict
      Compute net_price_cents for a single line after applying pricing rules.

  configure_product(product_id, config, session) -> dict
      Validate a product configuration against config_rules.
      Returns validated config or raises CPQValidationError.

  send_quote(quote_id, session) -> Quote
      Transition DRAFT → SENT; sets valid_until from config.

  accept_quote(quote_id, session) -> Quote
      Customer accepts quote; emits QuoteAcceptedEvent.

  reject_quote(quote_id, reason, session) -> Quote
      Customer rejects quote; emits QuoteRejectedEvent.

  submit_for_approval(quote_id, session) -> Quote
      Submit a DRAFT/SENT quote for internal approval workflow.

  approve_quote(quote_id, approver_id, notes, session) -> Quote
      Approver approves quote.

  reject_approval(quote_id, approver_id, reason, session) -> Quote
      Approver rejects quote.

  expire_quotes(tenant_id, as_of_date, session) -> int
      Mark SENT quotes past valid_until as EXPIRED.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)

# Default quote validity in days (overridden by CPQ_QUOTE_VALIDITY_DAYS config)
_DEFAULT_VALIDITY_DAYS = 30

# Approval threshold: quotes with discount > this % require approval
_DEFAULT_APPROVAL_DISCOUNT_PCT = Decimal("20.00")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CPQServiceError(Exception):
	"""Base exception for CPQ service layer errors."""


class QuoteNotFoundError(CPQServiceError):
	pass


class ProductNotFoundError(CPQServiceError):
	pass


class CatalogNotFoundError(CPQServiceError):
	pass


class CPQValidationError(CPQServiceError):
	"""Business rule or configuration validation failure — HTTP 422."""


class ApprovalRequiredError(CPQServiceError):
	"""Quote exceeds discount threshold; must go through approval workflow."""


# ---------------------------------------------------------------------------
# CPQService
# ---------------------------------------------------------------------------

class CPQService:
	"""Stateless CPQ business logic.

	Instantiate per-request or as a singleton — no instance state.
	"""

	# ------------------------------------------------------------------
	# generate_quote
	# ------------------------------------------------------------------

	def generate_quote(
		self,
		opportunity_id: str | None,
		account_id: str,
		line_items: list[dict],
		session: Any,
		tenant_id: str = "",
		currency_code: str = "USD",
		owner_id: str | None = None,
		quote_number: str | None = None,
		valid_days: int = _DEFAULT_VALIDITY_DAYS,
	) -> Any:
		"""Create a DRAFT Quote from line items with pricing rule application.

		line_items: list of dicts::
		    [
		        {
		            "product_id": "<uuid>",        # optional
		            "description": "Widget Pro",
		            "quantity": 2,
		            "list_price_cents": 10000,     # per unit
		            "discount_pct": 0,             # optional override
		            "cost_cents": 5000,            # optional
		            "configuration": {},           # optional for configurable products
		        },
		        ...
		    ]

		Applies best active pricing rule per line from the current catalog.
		Computes subtotal, discount, total; creates Quote + QuoteLine rows.
		Emits QuoteCreatedEvent.

		Returns the created Quote.
		"""
		from pgappforge.plugins.erp.crm.cpq.models import Quote, QuoteLine
		from pgappforge.plugins.erp.crm.cpq.events import QuoteCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		if not line_items:
			raise CPQValidationError("Quote must have at least one line item")

		# Resolve active catalog for tenant/currency
		catalog_id = self._resolve_catalog_id(tenant_id, currency_code, session)

		# Generate quote number if not provided
		if not quote_number:
			quote_number = self._next_quote_number(tenant_id, session)

		valid_until = date.today() + timedelta(days=valid_days)

		quote = Quote(
			tenant_id=tenant_id,
			opportunity_id=opportunity_id,
			account_id=account_id,
			quote_number=quote_number,
			status="DRAFT",
			valid_until=valid_until,
			currency_code=currency_code,
			owner_id=owner_id,
			subtotal_cents=0,
			discount_cents=0,
			tax_cents=0,
			total_cents=0,
		)
		session.add(quote)
		session.flush()  # get quote.id

		subtotal = 0
		total_discount = 0

		for i, item in enumerate(line_items, start=1):
			product_id = item.get("product_id")
			description = item.get("description") or "Product"
			quantity = Decimal(str(item.get("quantity", 1)))
			list_price_cents = int(item.get("list_price_cents", 0))
			cost_cents = item.get("cost_cents")
			config = item.get("configuration") or {}

			# Apply pricing rules
			priced = self.price_line(
				product_id=product_id,
				quantity=quantity,
				list_price_cents=list_price_cents,
				override_discount_pct=item.get("discount_pct"),
				catalog_id=catalog_id,
				session=session,
			)
			net_price_cents = priced["net_price_cents"]
			discount_pct = priced["discount_pct"]

			# Margin
			margin_pct = None
			if cost_cents is not None and net_price_cents > 0:
				cost_total = int(cost_cents) * int(quantity.to_integral_value(ROUND_HALF_UP))
				margin_pct = Decimal(str(
					(net_price_cents - cost_total) / net_price_cents * 100
				)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

			line = QuoteLine(
				tenant_id=tenant_id,
				quote_id=quote.id,
				line_number=i,
				product_id=product_id,
				description=description,
				quantity=quantity,
				list_price_cents=list_price_cents,
				discount_pct=discount_pct,
				net_price_cents=net_price_cents,
				cost_cents=cost_cents,
				margin_pct=margin_pct,
				configuration=config,
			)
			session.add(line)

			line_subtotal = int(
				(quantity * list_price_cents).to_integral_value(ROUND_HALF_UP)
			)
			subtotal += line_subtotal
			total_discount += line_subtotal - net_price_cents

		quote.subtotal_cents = subtotal
		quote.discount_cents = max(0, total_discount)
		quote.total_cents = subtotal - quote.discount_cents + quote.tax_cents

		emit_event(
			QuoteCreatedEvent(
				aggregate_id=quote.id,
				aggregate_type="Quote",
				tenant_id=tenant_id,
				quote_id=quote.id,
				quote_number=quote.quote_number,
				account_id=account_id,
				opportunity_id=opportunity_id or "",
				owner_id=owner_id or "",
				total_cents=quote.total_cents,
				currency_code=currency_code,
			),
			session,
		)

		log.info(
			"CPQService.generate_quote: %r created, total=%d¢, lines=%d",
			quote.quote_number, quote.total_cents, len(line_items),
		)
		return quote

	# ------------------------------------------------------------------
	# price_line
	# ------------------------------------------------------------------

	def price_line(
		self,
		product_id: str | None,
		quantity: Decimal,
		list_price_cents: int,
		override_discount_pct: float | None = None,
		catalog_id: str | None = None,
		session: Any = None,
	) -> dict:
		"""Compute net_price_cents for a single line after applying pricing rules.

		Returns::
		    {
		        "list_price_cents": int,
		        "discount_pct": Decimal,
		        "net_price_cents": int,
		        "rule_applied": str | None,
		    }

		Rule application order:
		  1. Explicit override_discount_pct (from caller) takes lowest priority.
		  2. Active FIXED rules override price entirely.
		  3. Active PERCENT/VOLUME_DISCOUNT rules apply discount_pct.
		  4. TIERED rules apply per quantity tier from conditions JSONB.
		  Rules are sorted by priority ASC (lower = higher priority).
		"""
		from pgappforge.plugins.erp.crm.cpq.models import PricingRule

		best_discount = Decimal(str(override_discount_pct or 0))
		fixed_override: int | None = None
		rule_applied: str | None = None

		if catalog_id and session:
			rules = session.execute(
				sa.select(PricingRule)
				.where(PricingRule.catalog_id == catalog_id)
				.where(PricingRule.is_active.is_(True))
				.order_by(PricingRule.priority)
			).scalars().all()

			for rule in rules:
				if not self._evaluate_conditions(rule.conditions, {
					"product_id": product_id,
					"quantity": float(quantity),
					"list_price_cents": list_price_cents,
				}):
					continue

				if rule.rule_type == "FIXED" and rule.fixed_price_cents is not None:
					fixed_override = rule.fixed_price_cents
					rule_applied = rule.rule_name
					break  # FIXED takes immediate precedence
				elif rule.rule_type in ("PERCENT", "VOLUME_DISCOUNT"):
					if rule.discount_pct is not None:
						pct = Decimal(str(rule.discount_pct))
						if pct > best_discount:
							best_discount = pct
							rule_applied = rule.rule_name
				elif rule.rule_type == "TIERED":
					tier_discount = self._evaluate_tiered(rule.conditions, float(quantity))
					if tier_discount is not None and Decimal(str(tier_discount)) > best_discount:
						best_discount = Decimal(str(tier_discount))
						rule_applied = rule.rule_name

		if fixed_override is not None:
			net_price_cents = int(
				(quantity * fixed_override).to_integral_value(ROUND_HALF_UP)
			)
			# Back-calculate effective discount_pct for display
			gross = int((quantity * list_price_cents).to_integral_value(ROUND_HALF_UP))
			effective_pct = (
				Decimal(str((gross - net_price_cents) / gross * 100)).quantize(
					Decimal("0.01"), rounding=ROUND_HALF_UP
				)
				if gross > 0
				else Decimal("0.00")
			)
			return {
				"list_price_cents": list_price_cents,
				"discount_pct": effective_pct,
				"net_price_cents": net_price_cents,
				"rule_applied": rule_applied,
			}

		# Apply percentage discount
		multiplier = (Decimal("100") - best_discount) / Decimal("100")
		net_price_cents = int(
			(quantity * list_price_cents * multiplier).to_integral_value(ROUND_HALF_UP)
		)
		return {
			"list_price_cents": list_price_cents,
			"discount_pct": best_discount,
			"net_price_cents": net_price_cents,
			"rule_applied": rule_applied,
		}

	# ------------------------------------------------------------------
	# configure_product
	# ------------------------------------------------------------------

	def configure_product(
		self,
		product_id: str,
		config: dict,
		session: Any,
	) -> dict:
		"""Validate a product configuration against config_rules.

		Checks:
		  - Product must exist in cpq_configurable_product.
		  - is_configurable must be True.
		  - All required options must be present in config.
		  - Selected values must be in allowed values list.
		  - Constraints: if/then pairs in config_rules.constraints.

		Returns the validated config dict (possibly normalised).
		Raises CPQValidationError with details on first violation.
		"""
		from pgappforge.plugins.erp.crm.cpq.models import ConfigurableProduct

		cp = session.execute(
			sa.select(ConfigurableProduct)
			.where(ConfigurableProduct.product_id == product_id)
		).scalar_one_or_none()

		if cp is None:
			raise ProductNotFoundError(
				f"No CPQ configuration found for product {product_id!r}"
			)
		if not cp.is_configurable:
			raise CPQValidationError(f"Product {product_id!r} is not configurable")

		rules = cp.config_rules or {}
		options = rules.get("options", [])
		constraints = rules.get("constraints", [])

		# Validate options
		for opt in options:
			name = opt["name"]
			allowed = opt.get("values", [])
			required = opt.get("required", False)

			if required and name not in config:
				raise CPQValidationError(
					f"Required option {name!r} is missing from configuration"
				)
			if name in config and allowed and config[name] not in allowed:
				raise CPQValidationError(
					f"Option {name!r}={config[name]!r} is not in allowed values {allowed}"
				)

		# Validate constraints
		for constraint in constraints:
			if_clause = constraint.get("if", {})
			then_clause = constraint.get("then", {})

			# Check if IF condition is met
			if_met = all(
				config.get(k) == v for k, v in if_clause.items()
			)
			if not if_met:
				continue

			# Check THEN requirements
			for k, allowed_values in then_clause.items():
				if k in config and config[k] not in allowed_values:
					raise CPQValidationError(
						f"Constraint violation: when {if_clause}, "
						f"option {k!r} must be one of {allowed_values} "
						f"(got {config[k]!r})"
					)

		# Validate price bounds if set
		log.debug(
			"CPQService.configure_product: product=%r config validated",
			product_id,
		)
		return config

	# ------------------------------------------------------------------
	# send_quote
	# ------------------------------------------------------------------

	def send_quote(self, quote_id: str, session: Any) -> Any:
		"""Transition quote DRAFT → SENT.

		Validations:
		  - Quote must be DRAFT.
		  - Must have at least one line.
		  - If discount exceeds threshold, approval_status must be APPROVED.

		Emits QuoteSentEvent.
		"""
		from pgappforge.plugins.erp.crm.cpq.models import Quote, QuoteLine
		from pgappforge.plugins.erp.crm.cpq.events import QuoteSentEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		quote = session.get(Quote, quote_id)
		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found")
		if quote.status != "DRAFT":
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} is {quote.status!r}, not DRAFT"
			)

		line_count = session.execute(
			sa.select(sa.func.count(QuoteLine.id))
			.where(QuoteLine.quote_id == quote_id)
		).scalar() or 0
		if line_count == 0:
			raise CPQValidationError("Quote must have at least one line before sending")

		# Check if approval required
		if (
			quote.subtotal_cents > 0
			and quote.discount_cents > 0
			and quote.approval_status not in ("APPROVED",)
		):
			effective_discount_pct = Decimal(str(
				quote.discount_cents / quote.subtotal_cents * 100
			))
			if effective_discount_pct >= _DEFAULT_APPROVAL_DISCOUNT_PCT:
				raise ApprovalRequiredError(
					f"Quote discount {effective_discount_pct:.1f}% exceeds "
					f"approval threshold {_DEFAULT_APPROVAL_DISCOUNT_PCT}%; "
					"submit for approval first"
				)

		quote.status = "SENT"
		quote.updated_at = datetime.now(timezone.utc)

		emit_event(
			QuoteSentEvent(
				aggregate_id=quote_id,
				aggregate_type="Quote",
				tenant_id=quote.tenant_id,
				quote_id=quote_id,
				quote_number=quote.quote_number,
				account_id=quote.account_id,
				opportunity_id=quote.opportunity_id or "",
				total_cents=quote.total_cents,
				currency_code=quote.currency_code,
				valid_until=quote.valid_until.isoformat() if quote.valid_until else "",
			),
			session,
		)

		log.info("CPQService.send_quote: %r sent, total=%d¢", quote.quote_number, quote.total_cents)
		return quote

	# ------------------------------------------------------------------
	# accept_quote
	# ------------------------------------------------------------------

	def accept_quote(self, quote_id: str, session: Any) -> Any:
		"""Customer accepts quote (SENT → ACCEPTED). Emits QuoteAcceptedEvent."""
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		from pgappforge.plugins.erp.crm.cpq.events import QuoteAcceptedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		quote = session.get(Quote, quote_id)
		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found")
		if quote.status != "SENT":
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} is {quote.status!r}, not SENT"
			)

		now_utc = datetime.now(timezone.utc)
		quote.status = "ACCEPTED"
		quote.updated_at = now_utc

		emit_event(
			QuoteAcceptedEvent(
				aggregate_id=quote_id,
				aggregate_type="Quote",
				tenant_id=quote.tenant_id,
				quote_id=quote_id,
				quote_number=quote.quote_number,
				account_id=quote.account_id,
				opportunity_id=quote.opportunity_id or "",
				total_cents=quote.total_cents,
				currency_code=quote.currency_code,
				accepted_at=now_utc.isoformat(),
			),
			session,
		)

		log.info("CPQService.accept_quote: %r accepted", quote.quote_number)
		return quote

	# ------------------------------------------------------------------
	# reject_quote
	# ------------------------------------------------------------------

	def reject_quote(self, quote_id: str, reason: str, session: Any) -> Any:
		"""Customer rejects quote. Emits QuoteRejectedEvent."""
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		from pgappforge.plugins.erp.crm.cpq.events import QuoteRejectedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		quote = session.get(Quote, quote_id)
		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found")
		if quote.status != "SENT":
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} is {quote.status!r}, not SENT"
			)

		quote.status = "REJECTED"
		quote.updated_at = datetime.now(timezone.utc)

		emit_event(
			QuoteRejectedEvent(
				aggregate_id=quote_id,
				aggregate_type="Quote",
				tenant_id=quote.tenant_id,
				quote_id=quote_id,
				quote_number=quote.quote_number,
				account_id=quote.account_id,
				opportunity_id=quote.opportunity_id or "",
				total_cents=quote.total_cents,
				reason=reason,
			),
			session,
		)
		return quote

	# ------------------------------------------------------------------
	# submit_for_approval
	# ------------------------------------------------------------------

	def submit_for_approval(self, quote_id: str, session: Any) -> Any:
		"""Submit a quote for internal approval workflow.

		Sets approval_status = PENDING. Emits QuoteApprovalRequestedEvent.
		"""
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		from pgappforge.plugins.erp.crm.cpq.events import QuoteApprovalRequestedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		quote = session.get(Quote, quote_id)
		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found")
		if quote.status not in ("DRAFT", "SENT"):
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} cannot be submitted for approval "
				f"from status {quote.status!r}"
			)
		if quote.approval_status == "PENDING":
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} already has a pending approval"
			)

		quote.approval_status = "PENDING"
		quote.updated_at = datetime.now(timezone.utc)

		emit_event(
			QuoteApprovalRequestedEvent(
				aggregate_id=quote_id,
				aggregate_type="Quote",
				tenant_id=quote.tenant_id,
				quote_id=quote_id,
				quote_number=quote.quote_number,
				owner_id=quote.owner_id or "",
				total_cents=quote.total_cents,
				currency_code=quote.currency_code,
				discount_cents=quote.discount_cents,
			),
			session,
		)

		log.info("CPQService.submit_for_approval: %r submitted", quote.quote_number)
		return quote

	# ------------------------------------------------------------------
	# approve_quote / reject_approval
	# ------------------------------------------------------------------

	def approve_quote(
		self,
		quote_id: str,
		approver_id: str,
		notes: str,
		session: Any,
	) -> Any:
		"""Approver approves a PENDING quote."""
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		from pgappforge.plugins.erp.crm.cpq.events import QuoteApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		quote = session.get(Quote, quote_id)
		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found")
		if quote.approval_status != "PENDING":
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} approval_status is {quote.approval_status!r}"
			)

		now_utc = datetime.now(timezone.utc)
		quote.approval_status = "APPROVED"
		quote.approved_by = approver_id
		quote.approved_at = now_utc
		quote.approval_notes = notes
		quote.updated_at = now_utc

		emit_event(
			QuoteApprovedEvent(
				aggregate_id=quote_id,
				aggregate_type="Quote",
				tenant_id=quote.tenant_id,
				quote_id=quote_id,
				quote_number=quote.quote_number,
				approved_by=approver_id,
				approved_at=now_utc.isoformat(),
			),
			session,
		)
		return quote

	def reject_approval(
		self,
		quote_id: str,
		approver_id: str,
		reason: str,
		session: Any,
	) -> Any:
		"""Approver rejects a PENDING quote."""
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		from pgappforge.plugins.erp.crm.cpq.events import QuoteApprovalRejectedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		quote = session.get(Quote, quote_id)
		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found")
		if quote.approval_status != "PENDING":
			raise CPQValidationError(
				f"Quote {quote.quote_number!r} approval_status is {quote.approval_status!r}"
			)

		quote.approval_status = "REJECTED"
		quote.approval_notes = reason
		quote.updated_at = datetime.now(timezone.utc)

		emit_event(
			QuoteApprovalRejectedEvent(
				aggregate_id=quote_id,
				aggregate_type="Quote",
				tenant_id=quote.tenant_id,
				quote_id=quote_id,
				quote_number=quote.quote_number,
				rejected_by=approver_id,
				reason=reason,
			),
			session,
		)
		return quote

	# ------------------------------------------------------------------
	# expire_quotes
	# ------------------------------------------------------------------

	def expire_quotes(
		self,
		tenant_id: str,
		as_of_date: date,
		session: Any,
	) -> int:
		"""Mark SENT quotes past valid_until as EXPIRED.

		Typically called daily by a scheduler. Returns count updated.
		"""
		from pgappforge.plugins.erp.crm.cpq.models import Quote

		result = session.execute(
			sa.update(Quote)
			.where(Quote.tenant_id == tenant_id)
			.where(Quote.status == "SENT")
			.where(Quote.valid_until < as_of_date)
			.values(status="EXPIRED", updated_at=datetime.now(timezone.utc))
		)
		n = result.rowcount
		log.info("CPQService.expire_quotes: expired %d quotes as of %s", n, as_of_date)
		return n

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _resolve_catalog_id(
		self,
		tenant_id: str,
		currency_code: str,
		session: Any,
	) -> str | None:
		"""Return the active catalog ID for tenant/currency, or None."""
		from pgappforge.plugins.erp.crm.cpq.models import ProductCatalog
		today = date.today()
		catalog = session.execute(
			sa.select(ProductCatalog)
			.where(ProductCatalog.tenant_id == tenant_id)
			.where(ProductCatalog.currency_code == currency_code)
			.where(ProductCatalog.is_active.is_(True))
			.where(ProductCatalog.effective_from <= today)
			.where(
				sa.or_(
					ProductCatalog.effective_to.is_(None),
					ProductCatalog.effective_to >= today,
				)
			)
			.order_by(sa.desc(ProductCatalog.effective_from))
			.limit(1)
		).scalar_one_or_none()
		return catalog.id if catalog else None

	def _next_quote_number(self, tenant_id: str, session: Any) -> str:
		"""Generate next sequential quote number for tenant."""
		from pgappforge.plugins.erp.crm.cpq.models import Quote
		count = session.execute(
			sa.select(sa.func.count(Quote.id))
			.where(Quote.tenant_id == tenant_id)
		).scalar() or 0
		return f"QUO-{count + 1:06d}"

	def _evaluate_conditions(self, conditions: list, context: dict) -> bool:
		"""Evaluate a list of condition dicts against a context dict.

		Each condition: {"field": str, "op": str, "value": any}
		Supported ops: eq, neq, gt, gte, lt, lte, in, not_in, is_null
		All conditions must pass (AND logic).
		"""
		for cond in conditions:
			field = cond.get("field", "")
			op = cond.get("op", "eq")
			expected = cond.get("value")
			actual = context.get(field)

			try:
				if op == "eq" and actual != expected:
					return False
				elif op == "neq" and actual == expected:
					return False
				elif op == "gt" and not (actual is not None and actual > expected):
					return False
				elif op == "gte" and not (actual is not None and actual >= expected):
					return False
				elif op == "lt" and not (actual is not None and actual < expected):
					return False
				elif op == "lte" and not (actual is not None and actual <= expected):
					return False
				elif op == "in" and actual not in (expected or []):
					return False
				elif op == "not_in" and actual in (expected or []):
					return False
				elif op == "is_null" and (actual is None) != bool(expected):
					return False
			except (TypeError, ValueError):
				return False
		return True

	def _evaluate_tiered(self, conditions: list, quantity: float) -> float | None:
		"""Extract the applicable discount_pct from a TIERED rule's conditions.

		Conditions for tiered rules use format::
		    [
		        {"tier_min": 1,  "tier_max": 9,  "discount_pct": 0},
		        {"tier_min": 10, "tier_max": 49, "discount_pct": 5},
		        {"tier_min": 50, "tier_max": null, "discount_pct": 10},
		    ]

		Returns the matching discount_pct float, or None if no tier matches.
		"""
		for tier in conditions:
			if "tier_min" not in tier:
				continue
			tier_min = tier["tier_min"]
			tier_max = tier.get("tier_max")
			if quantity >= tier_min and (tier_max is None or quantity <= tier_max):
				return float(tier.get("discount_pct", 0))
		return None


__all__ = [
	"CPQService",
	"CPQServiceError",
	"QuoteNotFoundError",
	"ProductNotFoundError",
	"CatalogNotFoundError",
	"CPQValidationError",
	"ApprovalRequiredError",
]
