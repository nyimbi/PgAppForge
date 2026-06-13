"""
pgappforge/ui/__init__.py

Higher-level UX components for PgAppForge.

Architecture note
-----------------
Two separate UI layers coexist in PgAppForge:

1. ``pgappforge/widgets/`` — **atomic rendering components**
   RenderTemplateWidget subclasses (StatCardWidget, DataGridWidget, etc.).
   Render via Jinja2 templates, integrated with FAB ModelView.
   Use for: KPI tiles, charts, data grids, approval buttons in views.

2. ``pgappforge/ui/`` (this package) — **page-level UX components**
   Multi-step wizards, guided workflow launchers, FK select widgets.
   Render via inline HTML/Markup (no template dependency).
   Use for: full-page wizard flows, dynamic FK dropdowns, workflow discovery.

The two layers are complementary: a wizard step (ui) might embed a
StatCardWidget (widgets) to show context while a user fills a form.

Sub-modules
-----------
  fk_widgets           — FK select dropdowns with Select2 search (inline HTML)
  wizard               — Multi-step wizard framework (WizardStep, WorkflowWizard)
  capability_workflows — Pre-built guided workflows for 8 ERP/fintech domains
"""
from __future__ import annotations

__all__ = ["fk_widgets", "wizard", "capability_workflows"]
