"""
pgappforge/workflow — PgAppForge workflow subsystem.

Two engines coexist in this package:

1. **YAML/BPMN engine** (new, Phase 1) — ``PgAppForgeWorkflowEngine`` backed by
   sequential YAML definitions. Import from ``pgappforge.workflow.engine``:

       from pgappforge.workflow import yaml_engine, init_yaml_engine
       yaml_engine.load_all_from_directory("workflows/")
       instance = yaml_engine.start("sacco_loan_approval", data, tenant_id="t1")

2. **Form-sequencing engine** (original) — ``WorkflowEngine`` / ``WorkflowMixin``
   for ModelView form orchestration. Import as before:

       from pgappforge.workflow import WorkflowEngine, WorkflowMixin

Both engines are independent; they share only this package namespace.
"""

__version__ = "2.0.0"
__author__ = "PgAppForge Contributors"

import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Original form-sequencing engine (unchanged)
# Guarded: optional deps (redis, etc.) may not be installed in all envs.
# ---------------------------------------------------------------------------
try:
	from .core import WorkflowEngine, WorkflowState, WorkflowStepDefinition
	from .views import WorkflowModelView, WorkflowFormView
	from .mixins import WorkflowMixin, WorkflowStateMixin
	from .security import WorkflowPermission, DynamicRoleManager
	from .widgets import WorkflowFormWidget, WorkflowProgressWidget, ConditionalFieldWidget
	from .forms import WorkflowFormSequence, FormOrchestrator
except Exception as _legacy_exc:  # noqa: BLE001
	log.debug("Legacy workflow engine unavailable (missing optional deps): %s", _legacy_exc)
	WorkflowEngine = None  # type: ignore[assignment,misc]
	WorkflowState = None  # type: ignore[assignment,misc]
	WorkflowStepDefinition = None  # type: ignore[assignment,misc]
	WorkflowModelView = None  # type: ignore[assignment,misc]
	WorkflowFormView = None  # type: ignore[assignment,misc]
	WorkflowMixin = None  # type: ignore[assignment,misc]
	WorkflowStateMixin = None  # type: ignore[assignment,misc]
	WorkflowPermission = None  # type: ignore[assignment,misc]
	DynamicRoleManager = None  # type: ignore[assignment,misc]
	WorkflowFormWidget = None  # type: ignore[assignment,misc]
	WorkflowProgressWidget = None  # type: ignore[assignment,misc]
	ConditionalFieldWidget = None  # type: ignore[assignment,misc]
	WorkflowFormSequence = None  # type: ignore[assignment,misc]
	FormOrchestrator = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# New YAML/BPMN engine (Phase 1)
# ---------------------------------------------------------------------------
from .engine import (
	PgAppForgeWorkflowEngine,
	create_workflow_tables,
)
from .models import WorkflowDefinition, WorkflowInstance
from .triggers import WorkflowTriggerRegistry, get_trigger_registry
try:
	from .yaml_dsl import (
		WorkflowDSLError,
		parse_yaml_file,
		parse_yaml_string,
	)
except Exception as _yaml_exc:  # noqa: BLE001
	log.debug("yaml_dsl unavailable: %s", _yaml_exc)
	WorkflowDSLError = None  # type: ignore[assignment,misc]
	parse_yaml_file = None  # type: ignore[assignment,misc]
	parse_yaml_string = None  # type: ignore[assignment,misc]

# Module-level singleton — use directly or call init_yaml_engine() from app factory
yaml_engine = PgAppForgeWorkflowEngine()


def get_yaml_engine() -> "PgAppForgeWorkflowEngine":
	"""Return the process-wide YAML workflow engine singleton."""
	return yaml_engine


def init_yaml_engine(app, db=None) -> None:
	"""Integrate the YAML workflow engine with a Flask app.

	Call once from your application factory after ``appbuilder.init_app(app)``.

	- Creates ``pgaf_workflow_instance`` and ``pgaf_workflow_task`` tables.
	- Auto-loads all ``*.yaml`` definitions from ``WORKFLOW_DIRECTORY`` config
	  (defaults to ``"workflows/"`` relative to CWD).

	Args:
		app: Flask application instance.
		db:  Optional SQLAlchemy ``db`` object (Flask-SQLAlchemy) or raw Engine.
	"""
	from pathlib import Path
	with app.app_context():
		if db is not None:
			try:
				raw_engine = getattr(db, "engine", db)
				create_workflow_tables(raw_engine)
				log.info("Workflow YAML-engine tables ready")
			except Exception as exc:
				log.warning("Workflow table setup failed (non-fatal): %s", exc)

		workflow_dir = app.config.get("WORKFLOW_DIRECTORY", "workflows")
		wf_path = Path(workflow_dir)
		if wf_path.is_dir():
			count = yaml_engine.load_all_from_directory(wf_path)
			log.info("Loaded %d YAML workflow definition(s) from %s", count, wf_path)
		else:
			log.debug("WORKFLOW_DIRECTORY %r not found — no definitions auto-loaded", str(wf_path))


__all__ = [
	# ---- original form-sequencing engine ----
	"WorkflowEngine",
	"WorkflowState",
	"WorkflowStepDefinition",
	"WorkflowModelView",
	"WorkflowFormView",
	"WorkflowMixin",
	"WorkflowStateMixin",
	"WorkflowPermission",
	"DynamicRoleManager",
	"WorkflowFormWidget",
	"WorkflowProgressWidget",
	"ConditionalFieldWidget",
	"WorkflowFormSequence",
	"FormOrchestrator",
	# ---- new YAML/BPMN engine ----
	"yaml_engine",
	"get_yaml_engine",
	"init_yaml_engine",
	"PgAppForgeWorkflowEngine",
	"WorkflowDefinition",
	"WorkflowInstance",
	"WorkflowDSLError",
	"create_workflow_tables",
	"parse_yaml_file",
	"parse_yaml_string",
	# ---- event triggers ----
	"WorkflowTriggerRegistry",
	"get_trigger_registry",
]