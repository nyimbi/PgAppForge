"""
pgappforge/semantic.py

Semantic layer — maps business terms and metric names to SQL expressions.

The SemanticRegistry is a process-level singleton.  Domain modules register
their SemanticModel objects at startup; the NL analytics service reads from
the registry to enrich LLM prompts with domain vocabulary.

Quick-start::

    from pgappforge.semantic import SemanticRegistry, register_default_semantics

    # At app startup
    register_default_semantics()

    # In NL analytics service
    registry = SemanticRegistry.get()
    context  = registry.build_llm_context()

    # Find a named metric
    metric = registry.find_metric("par30")
    # → SemanticMetric(name="par30", sql="SELECT ROUND(100.0 * ...", ...)

YAML auto-loading
-----------------
``SemanticRegistry.get()`` automatically scans all
``pgappforge/plugins/**/semantic.yaml`` files on first access.

YAML schema::

    domain:  fintech
    module:  sacco
    glossary:
      par30: "Portfolio at Risk 30 days — % overdue"
    metrics:
      - name:        par30
        label:       PAR 30
        description: Portfolio at risk — loans 30+ days overdue as % of book
        sql:         "SELECT ROUND(100.0 * ...) FROM pgaf_loan"
        unit:        "%"
        aggregation: CUSTOM
    dimensions:
      - name:         branch
        label:        Branch
        table:        pgaf_branch
        key_column:   code
        label_column: name
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SemanticMetric:
	"""A named business metric with its SQL definition.

	Attributes:
		name:        Unique snake_case identifier (e.g. ``par30``).
		label:       Human-readable display name (e.g. ``PAR 30``).
		description: One-line description for the LLM context.
		sql:         SQL expression or full SELECT query that computes the metric.
		unit:        Display unit, e.g. ``"KES"``, ``"%"``, ``"count"``.
		table:       Primary table this metric reads from.
		aggregation: Aggregation function: SUM | COUNT | AVG | MAX | MIN | CUSTOM.
		filters:     Default WHERE conditions (list of SQL fragment strings).
	"""
	name:        str
	label:       str
	description: str
	sql:         str
	unit:        str       = ""
	table:       str       = ""
	aggregation: str       = "SUM"
	filters:     list[str] = field(default_factory=list)


@dataclass
class SemanticDimension:
	"""A named dimension for grouping/filtering queries.

	Attributes:
		name:             Unique snake_case identifier.
		label:            Human-readable display name.
		table:            DB table that holds this dimension.
		key_column:       PK / join column (e.g. ``"code"`` or ``"id"``).
		label_column:     Display column (e.g. ``"name"``).
		description:      Optional description for LLM context.
		related_metrics:  List of metric names that can be sliced by this dimension.
	"""
	name:             str
	label:            str
	table:            str
	key_column:       str
	label_column:     str
	description:      str       = ""
	related_metrics:  list[str] = field(default_factory=list)


@dataclass
class SemanticModel:
	"""Complete semantic model for a business domain module.

	Attributes:
		domain:           Domain identifier (e.g. ``"fintech"``).
		module:           Module identifier (e.g. ``"sacco"``).
		metrics:          List of SemanticMetric objects.
		dimensions:       List of SemanticDimension objects.
		business_glossary: Dict mapping business term → plain-English definition.
	"""
	domain:            str
	module:            str
	metrics:           list[SemanticMetric]    = field(default_factory=list)
	dimensions:        list[SemanticDimension] = field(default_factory=list)
	business_glossary: dict[str, str]          = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class SemanticRegistry:
	"""Process-level singleton registry of semantic models.

	Modules register SemanticModel objects at startup via ``register()``.
	The NL analytics service calls ``build_llm_context()`` to get a single
	string suitable for injection into LLM prompts.

	Thread safety: Python's GIL protects the dict mutations; the singleton
	pattern is safe for WSGI workers (each worker process gets its own copy).
	"""

	_instance: SemanticRegistry | None = None
	_models:   dict[str, SemanticModel]
	_glossary: dict[str, str]

	def __init__(self) -> None:
		self._models   = {}
		self._glossary = {}

	@classmethod
	def get(cls) -> SemanticRegistry:
		"""Return the process-level singleton, auto-loading YAML files on first call."""
		if cls._instance is None:
			cls._instance = cls()
			cls._instance._load_from_yaml_files()
		return cls._instance

	@classmethod
	def reset(cls) -> None:
		"""Reset the singleton (useful in tests)."""
		cls._instance = None

	# ------------------------------------------------------------------
	# Registration
	# ------------------------------------------------------------------

	def register(self, model: SemanticModel) -> None:
		"""Register a SemanticModel. Overwrites any previous model for the same key."""
		key = f"{model.domain}.{model.module}"
		self._models[key] = model
		self._glossary.update(model.business_glossary)
		log.info(
			"Semantic: registered %s — %d metrics, %d dimensions, %d glossary terms",
			key,
			len(model.metrics),
			len(model.dimensions),
			len(model.business_glossary),
		)

	# ------------------------------------------------------------------
	# Lookup
	# ------------------------------------------------------------------

	def find_metric(self, name_or_label: str) -> SemanticMetric | None:
		"""Find a metric by name or label (case-insensitive exact match)."""
		search = name_or_label.lower().strip()
		for model in self._models.values():
			for metric in model.metrics:
				if metric.name.lower() == search or metric.label.lower() == search:
					return metric
		return None

	def find_dimension(self, name_or_label: str) -> SemanticDimension | None:
		"""Find a dimension by name or label (case-insensitive exact match)."""
		search = name_or_label.lower().strip()
		for model in self._models.values():
			for dim in model.dimensions:
				if dim.name.lower() == search or dim.label.lower() == search:
					return dim
		return None

	def get_glossary(self) -> dict[str, str]:
		"""Return all business term definitions across all registered models."""
		return dict(self._glossary)

	def get_all_metrics(self) -> list[SemanticMetric]:
		"""Return all registered metrics across all modules."""
		result: list[SemanticMetric] = []
		for model in self._models.values():
			result.extend(model.metrics)
		return result

	def get_all_dimensions(self) -> list[SemanticDimension]:
		"""Return all registered dimensions across all modules."""
		result: list[SemanticDimension] = []
		for model in self._models.values():
			result.extend(model.dimensions)
		return result

	def get_model(self, domain: str, module: str) -> SemanticModel | None:
		"""Return a specific SemanticModel by domain + module."""
		return self._models.get(f"{domain}.{module}")

	def list_models(self) -> list[tuple[str, str]]:
		"""Return list of (domain, module) tuples for all registered models."""
		return [(m.domain, m.module) for m in self._models.values()]

	# ------------------------------------------------------------------
	# LLM context building
	# ------------------------------------------------------------------

	def build_llm_context(self, max_metrics: int = 30) -> str:
		"""Build a compact context string for LLM NL-to-SQL prompting.

		The string is injected into the system prompt alongside the DB schema.
		Caps at *max_metrics* entries to avoid blowing the context window.

		Returns an empty string if nothing is registered.
		"""
		if not self._models:
			return ""

		lines: list[str] = []

		# Glossary terms
		if self._glossary:
			lines.append("# Business Terms")
			for term, defn in list(self._glossary.items())[:40]:
				lines.append(f"  '{term}': {defn}")

		# Metrics
		metrics = self.get_all_metrics()[:max_metrics]
		if metrics:
			lines.append("\n# Available Metrics")
			for m in metrics:
				unit_str = f" [{m.unit}]" if m.unit else ""
				sql_hint = m.sql[:120].replace("\n", " ")
				lines.append(f"  - {m.label}{unit_str}: {m.description} | SQL hint: {sql_hint}")

		# Dimensions
		dims = self.get_all_dimensions()[:20]
		if dims:
			lines.append("\n# Available Dimensions (for GROUP BY / filtering)")
			for d in dims:
				lines.append(f"  - {d.label}: table={d.table}, key={d.key_column}, label={d.label_column}")

		return "\n".join(lines)

	# ------------------------------------------------------------------
	# YAML auto-loading
	# ------------------------------------------------------------------

	def _load_from_yaml_files(self) -> None:
		"""Auto-load semantic.yaml files from all plugin directories.

		Scans ``pgappforge/plugins/**/semantic.yaml`` (relative to cwd).
		Non-fatal — any invalid YAML or missing field is logged at DEBUG.
		"""
		import glob

		# Support both installed-package and editable/source-tree layouts
		search_paths = [
			"pgappforge/plugins/**/semantic.yaml",
			str(Path(__file__).parent / "plugins" / "**" / "semantic.yaml"),
		]

		seen: set[str] = set()
		for pattern in search_paths:
			for yaml_path_str in glob.glob(pattern, recursive=True):
				abs_path = str(Path(yaml_path_str).resolve())
				if abs_path in seen:
					continue
				seen.add(abs_path)
				self._load_yaml_file(Path(yaml_path_str))

	def _load_yaml_file(self, path: Path) -> None:
		try:
			import yaml
		except ImportError:
			log.debug("Semantic: PyYAML not installed — skipping %s", path)
			return

		try:
			data = yaml.safe_load(path.read_text())
			if not isinstance(data, dict):
				return

			_METRIC_FIELDS  = set(SemanticMetric.__dataclass_fields__)
			_DIM_FIELDS     = set(SemanticDimension.__dataclass_fields__)

			metrics = [
				SemanticMetric(**{k: v for k, v in m.items() if k in _METRIC_FIELDS})
				for m in data.get("metrics", [])
				if isinstance(m, dict)
			]
			dimensions = [
				SemanticDimension(**{k: v for k, v in d.items() if k in _DIM_FIELDS})
				for d in data.get("dimensions", [])
				if isinstance(d, dict)
			]
			model = SemanticModel(
				domain=data.get("domain", "unknown"),
				module=data.get("module", path.parent.name),
				metrics=metrics,
				dimensions=dimensions,
				business_glossary=data.get("glossary", {}),
			)
			self.register(model)
		except Exception as exc:
			log.debug("Semantic: failed to load %s — %s", path, exc)


# ---------------------------------------------------------------------------
# Default built-in semantic models
# ---------------------------------------------------------------------------

def register_default_semantics() -> None:
	"""Register built-in SemanticModels for all core ERP domains.

	Called once at app startup.  Safe to call multiple times (idempotent
	because register() overwrites by key).
	"""
	registry = SemanticRegistry.get()

	# ── SACCO / fintech ──────────────────────────────────────────────
	registry.register(SemanticModel(
		domain="fintech",
		module="sacco",
		metrics=[
			SemanticMetric(
				name="total_loan_book",
				label="Total Loan Book",
				description="Sum of all outstanding loan balances in KES",
				sql=(
					"SELECT SUM(outstanding_balance_cents) / 100.0 AS total_loan_book_kes "
					"FROM pgaf_loan "
					"WHERE status IN ('ACTIVE', 'ARREARS')"
				),
				unit="KES",
				table="pgaf_loan",
				aggregation="SUM",
			),
			SemanticMetric(
				name="active_members",
				label="Active Members",
				description="Count of SACCO members with ACTIVE status",
				sql=(
					"SELECT COUNT(*) AS active_members "
					"FROM pgaf_sacco_member "
					"WHERE status = 'ACTIVE'"
				),
				unit="count",
				table="pgaf_sacco_member",
				aggregation="COUNT",
			),
			SemanticMetric(
				name="par30",
				label="PAR 30",
				description="Portfolio at risk: % of loan book 30+ days past due (SASRA limit 10%)",
				sql=(
					"SELECT ROUND(100.0 * "
					"  SUM(CASE WHEN days_past_due >= 30 THEN outstanding_balance_cents ELSE 0 END) "
					"  / NULLIF(SUM(outstanding_balance_cents), 0), 2) AS par30_pct "
					"FROM pgaf_loan "
					"WHERE status IN ('ACTIVE', 'ARREARS', 'NPA')"
				),
				unit="%",
				table="pgaf_loan",
				aggregation="CUSTOM",
			),
			SemanticMetric(
				name="monthly_deposits",
				label="Monthly Deposits",
				description="Total member deposits received in the current calendar month",
				sql=(
					"SELECT SUM(amount_cents) / 100.0 AS monthly_deposits_kes "
					"FROM pgaf_sacco_transaction "
					"WHERE transaction_type = 'DEPOSIT' "
					"  AND DATE_TRUNC('month', transaction_date) = DATE_TRUNC('month', CURRENT_DATE)"
				),
				unit="KES",
				table="pgaf_sacco_transaction",
				aggregation="SUM",
			),
		],
		dimensions=[
			SemanticDimension(
				name="branch",
				label="Branch",
				table="pgaf_branch",
				key_column="code",
				label_column="name",
				related_metrics=["total_loan_book", "active_members", "par30"],
			),
			SemanticDimension(
				name="loan_product",
				label="Loan Product",
				table="pgaf_sacco_loan_product",
				key_column="id",
				label_column="name",
				related_metrics=["total_loan_book", "par30"],
			),
		],
		business_glossary={
			"par30":  "Portfolio at Risk 30 days — % of loan book 30+ days overdue. SASRA limit: 10%",
			"fosa":   "Front Office Service Activity — deposit-taking arm of a SACCO",
			"bosa":   "Back Office Service Activity — core savings and credit arm of a SACCO",
			"sasra":  "Sacco Societies Regulatory Authority — Kenya regulator for SACCOs",
			"shares": "Member equity (share capital) in a SACCO, distinct from savings deposits",
		},
	))

	# ── GL / Finance ─────────────────────────────────────────────────
	registry.register(SemanticModel(
		domain="erp",
		module="gl",
		metrics=[
			SemanticMetric(
				name="total_revenue",
				label="Total Revenue",
				description="Sum of all revenue account credits for the current fiscal period",
				sql=(
					"SELECT SUM(jl.amount_cents) / 100.0 AS total_revenue_kes "
					"FROM pgaf_gl_journal_line jl "
					"JOIN pgaf_gl_account a ON a.account_code = jl.account_code "
					"WHERE a.account_type = 'REVENUE' "
					"  AND jl.entry_type = 'CREDIT' "
					"  AND jl.posted_at >= DATE_TRUNC('year', CURRENT_DATE)"
				),
				unit="KES",
				table="pgaf_gl_journal_line",
				aggregation="SUM",
			),
			SemanticMetric(
				name="total_expenses",
				label="Total Expenses",
				description="Sum of all expense account debits for the current fiscal period",
				sql=(
					"SELECT SUM(jl.amount_cents) / 100.0 AS total_expenses_kes "
					"FROM pgaf_gl_journal_line jl "
					"JOIN pgaf_gl_account a ON a.account_code = jl.account_code "
					"WHERE a.account_type = 'EXPENSE' "
					"  AND jl.entry_type = 'DEBIT' "
					"  AND jl.posted_at >= DATE_TRUNC('year', CURRENT_DATE)"
				),
				unit="KES",
				table="pgaf_gl_journal_line",
				aggregation="SUM",
			),
			SemanticMetric(
				name="net_income",
				label="Net Income",
				description="Revenue minus expenses for the current fiscal period",
				sql=(
					"SELECT "
					"  (SUM(CASE WHEN a.account_type='REVENUE' AND jl.entry_type='CREDIT' THEN jl.amount_cents ELSE 0 END) "
					"  -SUM(CASE WHEN a.account_type='EXPENSE' AND jl.entry_type='DEBIT'  THEN jl.amount_cents ELSE 0 END)) "
					"  / 100.0 AS net_income_kes "
					"FROM pgaf_gl_journal_line jl "
					"JOIN pgaf_gl_account a ON a.account_code = jl.account_code "
					"WHERE jl.posted_at >= DATE_TRUNC('year', CURRENT_DATE)"
				),
				unit="KES",
				table="pgaf_gl_journal_line",
				aggregation="CUSTOM",
			),
		],
		dimensions=[
			SemanticDimension(
				name="cost_center",
				label="Cost Center",
				table="pgaf_gl_cost_center",
				key_column="code",
				label_column="name",
				related_metrics=["total_revenue", "total_expenses", "net_income"],
			),
			SemanticDimension(
				name="period",
				label="Accounting Period",
				table="pgaf_gl_period",
				key_column="id",
				label_column="name",
				related_metrics=["total_revenue", "total_expenses", "net_income"],
			),
		],
		business_glossary={
			"chart of accounts": "Hierarchical list of GL accounts used to classify all transactions",
			"journal entry":     "A balanced double-entry record: total debits = total credits",
			"cost center":       "Organisational unit used to track departmental P&L",
			"fiscal year":       "12-month accounting period defined per organisation",
			"period close":      "Month-end process locking a GL period against further posting",
		},
	))

	# ── HCM Payroll ──────────────────────────────────────────────────
	registry.register(SemanticModel(
		domain="erp",
		module="payroll",
		metrics=[
			SemanticMetric(
				name="headcount",
				label="Headcount",
				description="Active employee count",
				sql=(
					"SELECT COUNT(*) AS headcount "
					"FROM pgaf_employee "
					"WHERE employment_status = 'ACTIVE'"
				),
				unit="count",
				table="pgaf_employee",
				aggregation="COUNT",
			),
			SemanticMetric(
				name="total_payroll_cost",
				label="Total Payroll Cost",
				description="Total gross payroll disbursed in the last completed payroll run",
				sql=(
					"SELECT SUM(gross_pay_cents) / 100.0 AS total_payroll_cost_kes "
					"FROM pgaf_payslip ps "
					"JOIN pgaf_payroll_run pr ON pr.id = ps.payroll_run_id "
					"WHERE pr.status = 'PAID' "
					"  AND pr.period_end = ("
					"    SELECT MAX(period_end) FROM pgaf_payroll_run WHERE status = 'PAID'"
					"  )"
				),
				unit="KES",
				table="pgaf_payslip",
				aggregation="SUM",
			),
			SemanticMetric(
				name="avg_gross_pay",
				label="Average Gross Pay",
				description="Average employee gross pay in the last completed payroll run",
				sql=(
					"SELECT AVG(gross_pay_cents) / 100.0 AS avg_gross_pay_kes "
					"FROM pgaf_payslip ps "
					"JOIN pgaf_payroll_run pr ON pr.id = ps.payroll_run_id "
					"WHERE pr.status = 'PAID' "
					"  AND pr.period_end = ("
					"    SELECT MAX(period_end) FROM pgaf_payroll_run WHERE status = 'PAID'"
					"  )"
				),
				unit="KES",
				table="pgaf_payslip",
				aggregation="AVG",
			),
			SemanticMetric(
				name="total_statutory_deductions",
				label="Total Statutory Deductions",
				description="Sum of PAYE + NHIF + NSSF in the last completed payroll run",
				sql=(
					"SELECT SUM(paye_cents + nhif_cents + nssf_cents) / 100.0 "
					"  AS total_statutory_kes "
					"FROM pgaf_payslip ps "
					"JOIN pgaf_payroll_run pr ON pr.id = ps.payroll_run_id "
					"WHERE pr.status = 'PAID' "
					"  AND pr.period_end = ("
					"    SELECT MAX(period_end) FROM pgaf_payroll_run WHERE status = 'PAID'"
					"  )"
				),
				unit="KES",
				table="pgaf_payslip",
				aggregation="SUM",
			),
		],
		dimensions=[
			SemanticDimension(
				name="department",
				label="Department",
				table="pgaf_department",
				key_column="id",
				label_column="name",
				related_metrics=["headcount", "total_payroll_cost", "avg_gross_pay"],
			),
			SemanticDimension(
				name="pay_grade",
				label="Pay Grade",
				table="pgaf_pay_grade",
				key_column="code",
				label_column="name",
				related_metrics=["headcount", "avg_gross_pay"],
			),
		],
		business_glossary={
			"gross pay":          "Total pay before any deductions (statutory or voluntary)",
			"net pay":            "Take-home pay after all deductions",
			"paye":               "Pay As You Earn — Kenya income tax withheld at source",
			"nhif":               "National Hospital Insurance Fund — Kenya health deduction",
			"nssf":               "National Social Security Fund — Kenya pension deduction",
			"payroll run":        "A batch calculation covering all employees for one pay period",
			"payslip":            "Individual employee pay statement for one payroll run",
		},
	))

	log.info("Semantic: default models registered (sacco, gl, payroll)")


__all__ = [
	"SemanticRegistry",
	"SemanticModel",
	"SemanticMetric",
	"SemanticDimension",
	"register_default_semantics",
]
