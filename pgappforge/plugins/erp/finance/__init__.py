"""
pgappforge/plugins/erp/finance/__init__.py

Finance domain namespace for ERP plugins.

Plugins in this domain:
  gl  — General Ledger (chart of accounts, journals, periods, budgets)
  ap  — Accounts Payable      (planned)
  ar  — Accounts Receivable   (planned)
  fa  — Fixed Assets          (planned)
  tx  — Tax Management        (planned)
"""
from __future__ import annotations

from markupsafe import Markup, escape

from pgappforge.plugins.erp.base_view import BaseERPView


def _finance_kpi_cards(self, kpis: list[dict]) -> Markup:
	import re as _re

	_COLOR_RE = _re.compile(r'^#[0-9a-fA-F]{6}$')
	_ICON_RE = _re.compile(r'^fa-[a-z0-9-]+$')

	from pgappforge.widgets.display_widgets import StatCardWidget

	parts: list[str] = [
		'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));'
		'gap:1rem;margin-bottom:1.5rem">'
	]
	for i, kpi in enumerate(kpis):
		color = kpi.get("color", "#1a56db")
		icon = kpi.get("icon", "fa-chart-line")
		if not _COLOR_RE.match(str(color)):
			color = "#1a56db"
		if not _ICON_RE.match(str(icon)):
			icon = "fa-chart-line"

		value = kpi.get("value", 0)
		label = str(kpi.get("label", ""))
		is_cent_value = (
			isinstance(value, int)
			and not isinstance(value, bool)
			and abs(value) > 100
			and ("cent" in label.lower() or kpi.get("format") == "currency")
		)
		if is_cent_value:
			prefix = str(kpi.get("currency_prefix") or kpi.get("currency") or "$")
			displayed = f"{prefix}{value // 100:,}"
			trend = kpi.get("trend")
			trend_html = f' <span style="font-size:0.8em">{escape(str(trend))}</span>' if trend else ""
			parts.append(f"""
<div style="background:#fff;border:1px solid #dee2e6;border-radius:6px;
            padding:16px 20px;display:flex;align-items:center;gap:16px;
            box-shadow:0 1px 3px rgba(0,0,0,0.08)">
  <div style="width:48px;height:48px;border-radius:50%;background:{color}22;
              display:flex;align-items:center;justify-content:center;flex-shrink:0">
    <i class="fa {icon}" style="font-size:1.4em;color:{color}"></i>
  </div>
  <div style="flex:1;min-width:0">
    <div style="font-size:1.6em;font-weight:700;color:#2c3e50;line-height:1">
      {escape(displayed)}{trend_html}
    </div>
    <div style="font-size:0.82em;color:#6c757d;margin-top:2px">{escape(label)}</div>
  </div>
</div>
""")
			continue

		widget = StatCardWidget(
			value_col="value",
			label=label,
			format=kpi.get("format", "integer"),
			color=color,
			icon=icon,
			trend_col="trend" if kpi.get("trend") is not None else None,
		)
		row = {"value": value, "trend": kpi.get("trend", "")}
		if kpi.get("compare") is not None:
			row["compare"] = kpi["compare"]
		cid = f"kpi_{i}"
		parts.append(str(widget.render([row], container_id=cid)))
	parts.append("</div>")
	return Markup("".join(parts))


_finance_kpi_cards._finance_cents_formatter = True  # type: ignore[attr-defined]
BaseERPView.kpi_cards = _finance_kpi_cards


def register_currency_views(appbuilder, category: str = "Currency Management") -> None:
	"""Register tenant-scoped currency views on an AppBuilder instance."""
	from pgappforge.plugins.erp.finance.currency.views import (
		CurrencyDashboardView,
		ExchangeRateView,
	)

	appbuilder.add_view(
		CurrencyDashboardView,
		"Currency Dashboard",
		icon="fa-dashboard",
		category=category,
	)
	appbuilder.add_view(
		ExchangeRateView,
		"Exchange Rates",
		icon="fa-exchange",
		category=category,
	)


__all__ = [
	"register_currency_views",
]
