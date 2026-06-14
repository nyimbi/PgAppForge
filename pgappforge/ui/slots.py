"""View slot injection — Odoo <xpath>-style plugin content injection.

Problem
-------
Plugin A's customer detail view cannot embed Plugin B's loyalty balance
widget without hardcoding an import. No slot mechanism exists.

Solution
--------
A SlotRegistry where plugins declare named slots and providers register
content to fill them. Views include slot hooks; plugins inject content.

Usage — Provider (Plugin B registers content for a slot):
    from pgappforge.ui.slots import slot_provider

    @slot_provider('customer.detail.sidebar')
    def loyalty_sidebar(context: dict) -> str:
        customer_id = context.get('customer_id', '')
        return f'<div class="loyalty-widget">Points: {get_points(customer_id)}</div>'

Usage — Consumer (view template includes the slot):
    {{ render_slot('customer.detail.sidebar', {'customer_id': customer.id}) }}

Usage — Jinja2 extension registration:
    from pgappforge.ui.slots import register_slot_extension
    register_slot_extension(app.jinja_env)

Well-known slot names (plugins should use these for consistency):
    'customer.detail.sidebar'    — sidebar on customer detail view
    'customer.list.actions'      — action buttons in customer list
    'invoice.detail.footer'      — footer area on invoice detail
    'dashboard.kpi.row'          — additional KPI cards on home dashboard
    'nav.top.right'              — top-right navigation items
    '{domain}.{model}.detail.tab'  — additional tab in any detail view
"""
from __future__ import annotations

import logging
from collections import defaultdict
from markupsafe import Markup
from typing import Any, Callable

log = logging.getLogger(__name__)


class SlotRegistry:
	"""Registry of named slot providers.

	Slots are rendered in registration order; priority controls ordering.
	"""

	def __init__(self) -> None:
		# slot_name → list[(priority, provider_fn)]
		self._providers: dict[str, list[tuple[int, Callable]]] = defaultdict(list)

	def register_provider(self, slot_name: str, provider_fn: Callable, priority: int = 50) -> None:
		"""Register *provider_fn* to fill *slot_name*.

		provider_fn(context: dict) -> str — returns HTML string.
		Lower priority value = rendered first.
		"""
		self._providers[slot_name].append((priority, provider_fn))
		self._providers[slot_name].sort(key=lambda t: t[0])
		log.debug("SlotRegistry: registered provider for slot %r (priority=%d)", slot_name, priority)

	def render(self, slot_name: str, context: dict[str, Any] | None = None) -> Markup:
		"""Render all providers for *slot_name* and return combined HTML.

		Returns a Markup (safe string) — providers may return plain str or Markup.
		Exceptions in individual providers are caught and logged; other providers
		still render.
		"""
		ctx = context or {}
		parts: list[str] = []
		for priority, provider in self._providers.get(slot_name, []):
			try:
				result = provider(ctx)
				if result:
					parts.append(str(result))
			except Exception:
				log.exception(
					"SlotRegistry: provider %s for slot %r raised",
					getattr(provider, '__qualname__', repr(provider)), slot_name,
				)
		return Markup('\n'.join(parts))

	def list_slots(self) -> list[str]:
		"""Return all registered slot names."""
		return list(self._providers.keys())

	def provider_count(self, slot_name: str) -> int:
		return len(self._providers.get(slot_name, []))


# Module singleton
_registry: SlotRegistry | None = None


def get_slot_registry() -> SlotRegistry:
	global _registry
	if _registry is None:
		_registry = SlotRegistry()
	return _registry


def slot_provider(slot_name: str, priority: int = 50) -> Callable:
	"""Decorator: register a function as a provider for *slot_name*.

	Example::

		@slot_provider('customer.detail.sidebar')
		def my_widget(context: dict) -> str:
			return '<div>Hello from Plugin B</div>'
	"""
	def decorator(fn: Callable) -> Callable:
		get_slot_registry().register_provider(slot_name, fn, priority)
		fn._slot_name = slot_name
		fn._slot_priority = priority
		return fn
	return decorator


def render_slot(slot_name: str, context: dict[str, Any] | None = None) -> Markup:
	"""Render a named slot — callable from Python code or Jinja2 via extension."""
	return get_slot_registry().render(slot_name, context)


def register_slot_extension(jinja_env: Any) -> None:
	"""Add render_slot() as a Jinja2 global function.

	Call once in the app factory::

		from pgappforge.ui.slots import register_slot_extension
		register_slot_extension(app.jinja_env)
	"""
	jinja_env.globals['render_slot'] = render_slot
	log.debug("SlotRegistry: registered render_slot() in Jinja2 environment")


# Well-known slot name constants (use these for consistency)
SLOT_CUSTOMER_DETAIL_SIDEBAR = 'customer.detail.sidebar'
SLOT_CUSTOMER_LIST_ACTIONS   = 'customer.list.actions'
SLOT_INVOICE_DETAIL_FOOTER   = 'invoice.detail.footer'
SLOT_DASHBOARD_KPI_ROW       = 'dashboard.kpi.row'
SLOT_NAV_TOP_RIGHT           = 'nav.top.right'


__all__ = [
	'SlotRegistry', 'get_slot_registry', 'slot_provider', 'render_slot',
	'register_slot_extension',
	'SLOT_CUSTOMER_DETAIL_SIDEBAR', 'SLOT_CUSTOMER_LIST_ACTIONS',
	'SLOT_INVOICE_DETAIL_FOOTER', 'SLOT_DASHBOARD_KPI_ROW', 'SLOT_NAV_TOP_RIGHT',
]
