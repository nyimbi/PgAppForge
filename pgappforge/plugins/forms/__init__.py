"""Visual Form Builder for pgappforge.

Build multi-step forms with conditional logic, public embed, analytics,
and scoring without writing code.

Usage:
	appbuilder.add_view(FormBuilderView, "Form Builder", ...)
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)
__all__ = ["FormsPlugin"]


class FormsPlugin:
	name = "forms"

	def initialize(self, app, appbuilder) -> None:
		log.info("FormsPlugin initialized")

	def register_views(self, appbuilder) -> None:
		from pgappforge.plugins.forms.views import FormBuilderView, PublicFormView
		appbuilder.add_view(FormBuilderView, "Form Builder", icon="fa-wpforms", category="Tools")
		appbuilder.add_view_no_menu(PublicFormView)
