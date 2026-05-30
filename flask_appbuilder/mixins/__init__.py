"""
Flask-AppBuilder Mixin Library — PostgreSQL-backed applications.

All imports are guarded so a broken individual mixin never prevents the
package from loading.  Use `from flask_appbuilder.mixins import XMixin`
to access any mixin directly.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


def _try_import(module_name: str, *names: str) -> dict:
	"""Relative import with graceful fallback on any error."""
	from importlib import import_module
	try:
		mod = import_module(f".{module_name}", package=__name__)
		return {n: getattr(mod, n) for n in names if hasattr(mod, n)}
	except Exception as exc:
		log.debug("Mixin skipped %s: %s", module_name, exc)
		return {}


_ns: dict = {}

# Core
_ns.update(_try_import("util_mixins", "VersionMixin", "LookupMixin", "HumanizeMixin"))
_ns.update(_try_import("archive_mixin", "ArchiveMixin", "ArchiveQuery"))
_ns.update(_try_import("version_control_mixin", "VersionControlMixin"))

# Data
_ns.update(_try_import("cache_mixin", "CacheMixin", "CachedQuery"))
_ns.update(_try_import("metadata_mixin", "MetadataMixin", "JSONBType"))
_ns.update(_try_import("full_text_search_mixin", "FullTextSearchMixin"))

# Business
_ns.update(_try_import("approval_workflow_mixin", "ApprovalWorkflowMixin", "ApprovalStatus"))
_ns.update(_try_import("business_rules_mixin", "BusinessRuleMixin"))
_ns.update(_try_import("statemachine_mixin", "StateMachineMixin", "State"))
_ns.update(_try_import("workflow_mixin", "WorkflowMixin"))
_ns.update(_try_import("scheduling_mixin", "SchedulingMixin"))
_ns.update(_try_import("project_mixin", "ProjectMixin"))
_ns.update(_try_import("rate_limit_mixin", "RateLimitMixin", "RateLimitConfig"))

# Content
_ns.update(_try_import("commentable_mixin", "CommentableMixin"))
_ns.update(_try_import("doc_mixin", "DocMixin"))
_ns.update(_try_import("import_export_mixin", "ImportExportMixin"))
_ns.update(_try_import("currency_mixin", "CurrencyMixin"))

# Integration
_ns.update(_try_import("geo_location_mixin", "GeoLocationMixin"))
_ns.update(_try_import("multi_tenancy_mixin", "MultiTenancyMixin"))
_ns.update(_try_import("polymorphic_mixin", "PolymorphicMixin"))
_ns.update(_try_import("replication_mixin", "ReplicationMixin"))
_ns.update(_try_import("internationalization_mixin", "InternationalizationMixin"))
_ns.update(_try_import("rls_mixin", "RLSFilterCache"))
_ns.update(_try_import("event_disptach_mixin", "EventDispatchMixin"))

# FAB integration
_ns.update(_try_import("fab_integration", "FABIntegratedModel", "FABMixinRegistry"))
_ns.update(_try_import("view_mixins", "EnhancedModelView"))

# Optional (requires alembic)
_ns.update(_try_import("migration_tools", "MigrationHelper"))

globals().update(_ns)
__all__ = list(_ns.keys())
