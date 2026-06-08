from __future__ import annotations

import logging

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority
from pgappforge.plugins.erp.hcm.lunch.events import (
	LunchOrderCancelledEvent,
	LunchOrderPlacedEvent,
	LunchSubsidyAppliedEvent,
	LunchSupplierDeliveredEvent,
)
from pgappforge.plugins.erp.hcm.lunch.models import (
	LunchMenu,
	LunchOrder,
	LunchSubsidyPolicy,
	LunchSupplier,
)
from pgappforge.plugins.erp.hcm.lunch.services import (
	LunchNotFoundError,
	LunchService,
	LunchServiceError,
	LunchStateError,
)

__all__ = [
	# Plugin entry point
	"LunchPlugin",
	"create_plugin",
	# Models
	"LunchSupplier",
	"LunchMenu",
	"LunchOrder",
	"LunchSubsidyPolicy",
	# Events
	"LunchOrderPlacedEvent",
	"LunchOrderCancelledEvent",
	"LunchSubsidyAppliedEvent",
	"LunchSupplierDeliveredEvent",
	# Service layer
	"LunchService",
	"LunchServiceError",
	"LunchNotFoundError",
	"LunchStateError",
]

_log = logging.getLogger(__name__)


class LunchPlugin(BasePlugin):
	"""HCM Lunch Management plugin.

	Covers supplier management, daily menus, employee ordering,
	subsidy policies, and delivery tracking.
	"""

	name = "lunch"
	domain = "hcm"
	depends_on = ["foundation"]

	metadata = {
		"version": "1.0.0",
		"description": (
			"HCM Lunch Management — supplier catalogues, daily menus, "
			"employee ordering, subsidy policies, catering delivery tracking"
		),
		"tags": ["erp", "hcm", "lunch", "catering"],
	}

	permissions = [
		"can_list_lunch_suppliers",
		"can_write_lunch_suppliers",
		"can_list_lunch_menus",
		"can_write_lunch_menus",
		"can_publish_lunch_menus",
		"can_list_lunch_orders",
		"can_write_lunch_orders",
		"can_cancel_lunch_orders",
		"can_list_lunch_subsidy_policies",
		"can_write_lunch_subsidy_policies",
		"can_view_lunch_reports",
	]

	def get_events(self) -> list[str]:
		return [
			"hcm.lunch.order.placed",
			"hcm.lunch.order.cancelled",
			"hcm.lunch.subsidy.applied",
			"hcm.lunch.supplier.delivered",
		]

	def subscribe_to(self) -> list[str]:
		return [
			"hcm.employee.terminated",
		]

	def initialize(self) -> None:
		"""Set config defaults and wire event subscriptions."""
		defaults = {
			"LUNCH_MENU_CATEGORY": "Lunch",
			"LUNCH_DEFAULT_CURRENCY": "KES",
			"LUNCH_ORDER_CUTOFF_MINUTES": 30,
		}
		if self.appbuilder is not None:
			app = self.appbuilder.get_app()
			for key, value in defaults.items():
				app.config.setdefault(key, value)

		try:
			subscribe("hcm.employee.terminated", self._on_employee_terminated)
			_log.info("LunchPlugin: event subscriptions registered")
		except Exception:  # noqa: BLE001
			_log.debug("LunchPlugin: event bus not available; subscriptions skipped")

		_log.info("LunchPlugin initialized")

	def register_models(self) -> list:
		return [
			LunchSupplier,
			LunchMenu,
			LunchOrder,
			LunchSubsidyPolicy,
		]

	def register_views(self) -> None:
		from pgappforge.plugins.erp.hcm.lunch.views import (
			LunchMenuView,
			LunchOrderView,
			LunchSupplierView,
		)
		cat = self.appbuilder.get_app().config.get("LUNCH_MENU_CATEGORY", "Lunch") \
			if self.appbuilder is not None else "Lunch"
		self.add_view(LunchSupplierView, "Suppliers", icon="fa-store", category=cat)
		self.add_view(LunchMenuView, "Menus", icon="fa-utensils", category=cat)
		self.add_view(LunchOrderView, "Orders", icon="fa-shopping-cart", category=cat)
		_log.info("LunchPlugin: views registered under %r", cat)

	def setup_rules(self, session: object) -> None:  # type: ignore[override]
		"""Install domain-level validation rulesets via the Rules Engine.

		Three rulesets are registered:
		1. lunch.menu.published_required_for_orders — orders require PUBLISHED menu.
		2. lunch.order.no_duplicate_employee_menu — one order per employee per menu.
		3. lunch.order.immutable_after_delivered — DELIVERED orders cannot be mutated.
		"""
		try:
			from pgappforge.plugins.rules.engine import RulesEngine

			engine = RulesEngine(session=session)

			engine.register_ruleset(
				name="lunch.menu.published_required_for_orders",
				model="LunchOrder",
				rules=[
					{
						"field": "menu.status",
						"op": "neq",
						"value": "PUBLISHED",
					}
				],
				action="raise_error",
				message=(
					"Orders can only be placed against a PUBLISHED menu."
				),
			)

			engine.register_ruleset(
				name="lunch.order.no_duplicate_employee_menu",
				model="LunchOrder",
				rules=[
					{
						"field": "status",
						"op": "notin",
						"value": ["CANCELLED"],
					}
				],
				action="raise_error",
				message=(
					"An active order already exists for this employee and menu. "
					"Cancel the existing order before placing a new one."
				),
			)

			engine.register_ruleset(
				name="lunch.order.immutable_after_delivered",
				model="LunchOrder",
				rules=[
					{
						"field": "status",
						"op": "eq",
						"value": "DELIVERED",
					}
				],
				action="raise_error",
				message=(
					"DELIVERED orders cannot be modified."
				),
			)

			_log.info("LunchPlugin: 3 rulesets registered via RulesEngine")

		except Exception as exc:  # noqa: BLE001
			_log.warning("LunchPlugin.setup_rules: RulesEngine unavailable — %s", exc)

	# ------------------------------------------------------------------
	# Internal event handlers
	# ------------------------------------------------------------------

	def _on_employee_terminated(self, event: object) -> None:
		"""Cancel any PLACED orders for a terminated employee."""
		try:
			from sqlalchemy import select

			from pgappforge.extensions import db

			employee_id: str = getattr(event, "employee_id", "")
			tenant_id: str = getattr(event, "tenant_id", "")

			if not (employee_id and tenant_id):
				_log.warning("_on_employee_terminated: missing employee_id or tenant_id")
				return

			svc = LunchService()
			with db.session() as session:
				placed = session.execute(
					select(LunchOrder).where(
						LunchOrder.tenant_id == tenant_id,
						LunchOrder.employee_id == employee_id,
						LunchOrder.status.in_(["DRAFT", "PLACED"]),
					)
				).scalars().all()

				for order in placed:
					svc.cancel_order(
						order.id,
						employee_id,
						session,
						reason="employee_terminated",
					)
				session.commit()
				_log.info(
					"Auto-cancelled %d lunch orders for employee=%s",
					len(placed), employee_id,
				)
		except Exception as exc:  # noqa: BLE001
			_log.error("_on_employee_terminated handler failed: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_plugin(appbuilder: object, config: dict | None = None) -> LunchPlugin:
	"""Instantiate and return the LunchPlugin."""
	plugin = LunchPlugin(appbuilder=appbuilder)

	if config and appbuilder is not None:
		app = appbuilder.get_app()  # type: ignore[union-attr]
		for key, value in config.items():
			app.config[key] = value

	plugin.initialize()
	return plugin
