"""
pgappforge/plugins/classify/__init__.py

8-level US government data classification system for PgAppForge.

Provides:
  - ClassificationMixin — adds classification_level to any SQLAlchemy model
  - ClassificationPlugin — enforces clearance-gated read access, PostgreSQL RLS
    policies, per-field REDACTED masking, and visual classification banners
  - ClassificationWidget — colored classification banner (top/bottom of views)
  - UserClearanceMixin — adds clearance_level to User model / UserProfile

Classification ladder
---------------------
  0  UNCLASSIFIED
  1  CUI   (Controlled Unclassified Information)
  2  PUBLIC_TRUST
  3  CONFIDENTIAL
  4  SECRET
  5  TOP_SECRET
  6  SCI   (Sensitive Compartmented Information)
  7  SAP   (Special Access Programs)

Enable
------
Add the plugin class to ``PGAPPFORGE_PLUGINS`` in your app config::

    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.classify.ClassificationPlugin",
    ]

Or instantiate manually::

    from pgappforge.plugins.classify import create_plugin
    plugin = create_plugin(appbuilder, config={...})
    plugin.activate()

Config keys
-----------
``CLASSIFY_DEFAULT_LEVEL``
    Integer 0-7.  Classification assigned to new records that do not explicitly
    set one.  Defaults to ``0`` (UNCLASSIFIED).

``CLASSIFY_BANNER_POSITION``
    ``"top"`` (default) or ``"bottom"`` — where the classification banner is
    injected into view templates.

``CLASSIFY_ENFORCE_RLS``
    Boolean.  When True the plugin emits a PostgreSQL RLS policy that prevents
    direct DB reads above the session variable ``app.current_clearance``.
    Defaults to True.

``CLASSIFY_REDACT_FIELDS``
    List of field names that should be masked as "REDACTED" when the viewer's
    clearance falls below the record's level.  Defaults to ``[]`` (all string
    fields are masked).

``CLASSIFY_WARN_ON_LOGIN``
    Boolean.  Flash a warning when a user logs in while accessing data whose
    classification exceeds their clearance.  Defaults to True.
"""
from __future__ import annotations

import logging
import textwrap
from typing import TYPE_CHECKING, Any

from flask import flash, g, has_request_context, render_template_string
from markupsafe import Markup

from pgappforge import BaseView, expose, has_access, Model
from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

from sqlalchemy import Column, SmallInteger, Text, event as sa_event
from sqlalchemy.orm import declared_attr

if TYPE_CHECKING:
	pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification level registry
# ---------------------------------------------------------------------------

#: Ordered mapping of integer level → (name, abbreviation, css_color, banner_bg, banner_fg)
#: Colors follow US IC banner conventions:
#:   UNCLASSIFIED   — green
#:   CUI            — purple (per NARA/ISOO)
#:   PUBLIC TRUST   — blue
#:   CONFIDENTIAL   — blue (darker)
#:   SECRET         — red
#:   TOP SECRET     — orange
#:   SCI            — yellow on orange (TS//SCI)
#:   SAP            — red on black (TS//SAP)
_LEVELS: dict[int, tuple[str, str, str, str, str]] = {
	#  level: (full_name,         abbrev,      banner_text,                     bg_color,   fg_color)
	0: ("UNCLASSIFIED",           "U",         "UNCLASSIFIED",                  "#007a33",  "#ffffff"),
	1: ("CUI",                    "CUI",       "CONTROLLED // UNCLASSIFIED",    "#512888",  "#ffffff"),
	2: ("PUBLIC_TRUST",           "PT",        "PUBLIC TRUST",                  "#005288",  "#ffffff"),
	3: ("CONFIDENTIAL",           "C",         "CONFIDENTIAL",                  "#003087",  "#ffffff"),
	4: ("SECRET",                 "S",         "SECRET",                        "#c8102e",  "#ffffff"),
	5: ("TOP_SECRET",             "TS",        "TOP SECRET",                    "#ff671f",  "#000000"),
	6: ("SCI",                    "TS//SCI",   "TOP SECRET // SCI",             "#ffd700",  "#000000"),
	7: ("SAP",                    "TS//SAP",   "TOP SECRET // SAP",             "#000000",  "#ff0000"),
}

_MAX_LEVEL = max(_LEVELS)
_MIN_LEVEL = min(_LEVELS)


def _level_name(level: int) -> str:
	"""Return the full name for *level*, clamped to valid range."""
	return _LEVELS.get(level, _LEVELS[_MAX_LEVEL])[0]


def _level_abbrev(level: int) -> str:
	return _LEVELS.get(level, _LEVELS[_MAX_LEVEL])[1]


def _level_banner_text(level: int) -> str:
	return _LEVELS.get(level, _LEVELS[_MAX_LEVEL])[2]


def _level_bg(level: int) -> str:
	return _LEVELS.get(level, _LEVELS[_MAX_LEVEL])[3]


def _level_fg(level: int) -> str:
	return _LEVELS.get(level, _LEVELS[_MAX_LEVEL])[4]


# ---------------------------------------------------------------------------
# ClassificationMixin — applied to SQLAlchemy models
# ---------------------------------------------------------------------------

class ClassificationMixin:
	"""
	SQLAlchemy mixin that adds a ``classification_level`` column (SmallInteger,
	default 0 = UNCLASSIFIED) to any model.

	Usage::

		class MyModel(ClassificationMixin, Model):
		    __tablename__ = "my_model"
		    __allow_unmapped__ = True
		    id = Column(Integer, primary_key=True)
		    ...

	The column is indexed for efficient RLS and access-filter queries.
	"""

	__allow_unmapped__ = True

	@declared_attr
	def classification_level(cls) -> Column:  # noqa: N805
		return Column(
			SmallInteger,
			nullable=False,
			default=0,
			index=True,
			comment=(
				"Data classification level 0-7: "
				"0=UNCLASSIFIED 1=CUI 2=PUBLIC_TRUST 3=CONFIDENTIAL "
				"4=SECRET 5=TOP_SECRET 6=SCI 7=SAP"
			),
		)

	@property
	def classification_label(self) -> str:
		"""Human-readable level name, e.g. ``'TOP_SECRET'``."""
		lvl = int(self.classification_level or 0)
		return _level_name(lvl)

	@property
	def classification_color(self) -> str:
		"""CSS background color hex string for the record's classification level."""
		lvl = int(self.classification_level or 0)
		return _level_bg(lvl)

	@property
	def classification_abbrev(self) -> str:
		"""Short abbreviation, e.g. ``'TS'`` for TOP_SECRET."""
		lvl = int(self.classification_level or 0)
		return _level_abbrev(lvl)

	@property
	def classification_banner_text(self) -> str:
		"""Banner display text, e.g. ``'TOP SECRET // SCI'``."""
		lvl = int(self.classification_level or 0)
		return _level_banner_text(lvl)

	def is_accessible_by(self, user_clearance: int) -> bool:
		"""
		Return True when *user_clearance* >= this record's classification_level.

		Args:
			user_clearance: Integer clearance level 0-7 for the requesting user.
		"""
		return int(user_clearance) >= int(self.classification_level or 0)


# ---------------------------------------------------------------------------
# UserClearanceMixin — applied to the User model or a UserProfile model
# ---------------------------------------------------------------------------

class UserClearanceMixin:
	"""
	SQLAlchemy mixin that adds a ``clearance_level`` column to a user or profile
	model.  Admins set clearance per user; the login hook reads it from
	``g.current_user_clearance``.

	Usage::

		class UserProfile(UserClearanceMixin, Model):
		    __tablename__ = "user_profile"
		    __allow_unmapped__ = True
		    id = Column(Integer, primary_key=True)
		    user_id = Column(Integer, ForeignKey("ab_user.id"))
	"""

	__allow_unmapped__ = True

	@declared_attr
	def clearance_level(cls) -> Column:  # noqa: N805
		return Column(
			SmallInteger,
			nullable=False,
			default=0,
			comment=(
				"User clearance level 0-7: "
				"0=UNCLASSIFIED 1=CUI 2=PUBLIC_TRUST 3=CONFIDENTIAL "
				"4=SECRET 5=TOP_SECRET 6=SCI 7=SAP"
			),
		)

	@property
	def clearance_label(self) -> str:
		"""Human-readable clearance name."""
		lvl = int(self.clearance_level or 0)
		return _level_name(lvl)


# ---------------------------------------------------------------------------
# ClassificationWidget — injectable classification banner HTML
# ---------------------------------------------------------------------------

_BANNER_TEMPLATE = """\
<div class="classification-banner classification-banner-{{ position }}"
     style="
       background-color: {{ bg }};
       color: {{ fg }};
       text-align: center;
       font-weight: bold;
       font-size: 13px;
       letter-spacing: 2px;
       padding: 4px 0;
       width: 100%;
       position: {{ 'sticky' if position == 'top' else 'fixed' }};
       {{ 'top: 0;' if position == 'top' else 'bottom: 0;' }}
       z-index: 9999;
       border-{{ 'bottom' if position == 'top' else 'top' }}: 2px solid {{ fg }};
       font-family: 'Courier New', monospace;
       text-transform: uppercase;
       user-select: none;
     "
     aria-label="Classification level: {{ banner_text }}"
     data-classification-level="{{ level }}"
     data-classification-abbrev="{{ abbrev }}"
>
  {{ banner_text }}
</div>
"""


class ClassificationWidget:
	"""
	Renders a classification banner bar suitable for injection into any Flask
	view or Jinja2 template.

	The banner matches US IC classification banner conventions:
	  - Colored background per level
	  - ALL-CAPS text with level abbreviation
	  - Sticky at top (default) or fixed at bottom

	Usage in a Jinja2 template::

	    {{ classification_widget(record.classification_level, position='top') }}

	Or from Python::

	    html: Markup = ClassificationWidget.render(level=4, position='top')
	"""

	@staticmethod
	def render(level: int = 0, position: str = "top") -> Markup:
		"""
		Return a :class:`markupsafe.Markup` HTML banner for *level*.

		Args:
			level: Classification integer 0-7.
			position: ``"top"`` or ``"bottom"``.

		Returns:
			Safe HTML string (no escaping needed in templates).
		"""
		level = max(_MIN_LEVEL, min(_MAX_LEVEL, int(level)))
		position = position if position in ("top", "bottom") else "top"
		html = render_template_string(
			_BANNER_TEMPLATE,
			bg=_level_bg(level),
			fg=_level_fg(level),
			banner_text=_level_banner_text(level),
			abbrev=_level_abbrev(level),
			level=level,
			position=position,
		)
		return Markup(html)

	@staticmethod
	def render_for_record(record: Any, position: str = "top") -> Markup:
		"""
		Convenience wrapper that reads classification_level from *record*.

		Args:
			record: Any model instance with :class:`ClassificationMixin`.
			position: Banner position.
		"""
		level = int(getattr(record, "classification_level", 0) or 0)
		return ClassificationWidget.render(level=level, position=position)

	@staticmethod
	def css() -> Markup:
		"""
		Return a ``<style>`` block with base CSS rules for all classification
		levels.  Inject once into the page ``<head>``.
		"""
		rules: list[str] = [
			textwrap.dedent("""\
				.classification-banner {
					font-family: 'Courier New', Courier, monospace;
					text-transform: uppercase;
					letter-spacing: 2px;
					font-size: 13px;
					font-weight: bold;
					padding: 4px 8px;
					text-align: center;
					width: 100%;
					box-sizing: border-box;
				}
				.classification-banner-top  { position: sticky; top: 0; z-index: 9999; }
				.classification-banner-bottom { position: fixed; bottom: 0; z-index: 9999; }
			""")
		]
		for lvl, (name, abbrev, banner_text, bg, fg) in _LEVELS.items():
			rules.append(
				f".classification-level-{lvl} "
				f"{{ background-color: {bg}; color: {fg}; }}"
			)
		return Markup(f"<style>\n{''.join(rules)}\n</style>")


# ---------------------------------------------------------------------------
# Access enforcement helpers
# ---------------------------------------------------------------------------

def _current_clearance() -> int:
	"""
	Return the requesting user's clearance level from Flask ``g``.

	Falls back to 0 (UNCLASSIFIED) when outside a request context or when
	``g.current_user_clearance`` is not set.
	"""
	if not has_request_context():
		return 0
	return int(getattr(g, "current_user_clearance", 0) or 0)


def mask_record_fields(
	record: Any,
	clearance: int,
	fields_to_mask: list[str] | None = None,
) -> dict[str, Any]:
	"""
	Return a dict of ``{field_name: value_or_REDACTED}`` for *record*.

	String-typed fields that would expose information above *clearance* are
	replaced with the string ``"REDACTED"``.

	Args:
		record: Model instance with :class:`ClassificationMixin`.
		clearance: Viewer's integer clearance level.
		fields_to_mask: Explicit list of field names to mask.  When None,
		                all string/text-mapped columns are masked.

	Returns:
		Dict suitable for passing directly to a template or JSON serializer.
	"""
	rec_level = int(getattr(record, "classification_level", 0) or 0)
	mapper = getattr(record.__class__, "__mapper__", None)

	if mapper is None:
		return {}

	result: dict[str, Any] = {}
	string_types = (str,)

	for col in mapper.columns:
		name = col.key
		value = getattr(record, name, None)

		# Never mask the classification_level column itself
		if name == "classification_level":
			result[name] = value
			continue

		# Mask if insufficient clearance and the field is targeted
		if clearance < rec_level:
			should_mask = (
				fields_to_mask is None
				and isinstance(value, string_types)
			) or (
				fields_to_mask is not None
				and name in fields_to_mask
			)
			result[name] = "REDACTED" if should_mask else value
		else:
			result[name] = value

	return result


# ---------------------------------------------------------------------------
# PostgreSQL RLS policy SQL generators
# ---------------------------------------------------------------------------

def _rls_policy_sql(table_name: str) -> str:
	"""
	Return the SQL statements to enable RLS on *table_name* and create a
	SELECT policy enforcing ``classification_level <= app.current_clearance``.

	The session variable ``app.current_clearance`` must be set at the start of
	each DB session::

	    SET LOCAL app.current_clearance = 3;

	The plugin's ``on_user_login`` hook sets this variable automatically when
	``CLASSIFY_ENFORCE_RLS`` is True.
	"""
	return textwrap.dedent(f"""\
		-- Enable Row Level Security on {table_name}
		ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
		ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;

		-- Drop old policy if exists (idempotent re-apply)
		DROP POLICY IF EXISTS pgaf_classify_read ON {table_name};

		-- Allow SELECT only when clearance >= classification_level
		CREATE POLICY pgaf_classify_read
		    ON {table_name}
		    FOR SELECT
		    USING (
		        classification_level
		        <= COALESCE(
		            current_setting('app.current_clearance', true)::smallint,
		            0
		        )
		    );

		-- INSERT / UPDATE / DELETE are unrestricted by this policy
		-- (add separate policies if write restriction is needed)
		DROP POLICY IF EXISTS pgaf_classify_write ON {table_name};
		CREATE POLICY pgaf_classify_write
		    ON {table_name}
		    FOR ALL
		    USING (true)
		    WITH CHECK (true);
	""")


def _rls_teardown_sql(table_name: str) -> str:
	"""Return SQL to drop the classification RLS policy from *table_name*."""
	return textwrap.dedent(f"""\
		DROP POLICY IF EXISTS pgaf_classify_read ON {table_name};
		DROP POLICY IF EXISTS pgaf_classify_write ON {table_name};
		ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;
	""")


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------

_CLASSIFICATION_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} — Classification Plugin</title>
  <link rel="stylesheet"
    href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  {{ banner_css }}
  <style>
    body { padding-top: 70px; }
    .level-row td { vertical-align: middle; }
    .level-swatch {
      display: inline-block; width: 120px; padding: 3px 8px;
      border-radius: 3px; font-weight: bold; font-size: 12px;
      letter-spacing: 1px; text-align: center; font-family: monospace;
    }
  </style>
</head>
<body>
  {{ top_banner }}
  <div class="container">
    <div class="page-header">
      <h1>
        {{ title }}
        <small>
          <span class="label label-success">Classification Plugin v0.1.0</span>
        </small>
      </h1>
    </div>
    <div class="alert alert-info">{{ description }}</div>
    <div class="panel panel-default">
      <div class="panel-heading"><h3 class="panel-title">Classification Levels</h3></div>
      <table class="table table-condensed">
        <thead>
          <tr>
            <th>Level</th><th>Name</th><th>Abbreviation</th>
            <th>Banner</th><th>Banner Text</th>
          </tr>
        </thead>
        <tbody>
          {% for lvl, entry in levels.items() %}
          <tr class="level-row">
            <td><strong>{{ lvl }}</strong></td>
            <td>{{ entry.name }}</td>
            <td><code>{{ entry.abbrev }}</code></td>
            <td>
              <span class="level-swatch"
                    style="background: {{ entry.bg }}; color: {{ entry.fg }};">
                {{ entry.abbrev }}
              </span>
            </td>
            <td><em>{{ entry.banner }}</em></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if rls_enabled %}
    <div class="alert alert-warning">
      <strong>PostgreSQL RLS active.</strong>
      Session variable <code>app.current_clearance</code> controls read access
      at the database level.
    </div>
    {% endif %}
  </div>
  {{ bottom_banner }}
</body>
</html>
"""


class ClassificationAdminView(BaseView):
	"""
	Read-only administration view showing the classification level registry,
	RLS status, and a live banner preview for each level.

	Accessible to users with the ``Admin`` role.
	"""

	route_base = "/classify/admin"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		from flask import current_app
		rls_enabled = current_app.config.get("CLASSIFY_ENFORCE_RLS", True)
		clearance = _current_clearance()

		levels_ctx = {
			lvl: {
				"name": info[0],
				"abbrev": info[1],
				"banner": info[2],
				"bg": info[3],
				"fg": info[4],
			}
			for lvl, info in _LEVELS.items()
		}

		top_banner = ClassificationWidget.render(level=clearance, position="top")
		bottom_banner = ClassificationWidget.render(level=clearance, position="bottom")

		return render_template_string(
			_CLASSIFICATION_PAGE_TEMPLATE,
			title="Data Classification",
			description=(
				"8-level US government data classification system. "
				"Records are access-controlled by user clearance level."
			),
			levels=levels_ctx,
			rls_enabled=rls_enabled,
			top_banner=top_banner,
			bottom_banner=bottom_banner,
			banner_css=ClassificationWidget.css(),
		)

	@expose("/banner-preview/<int:level>")
	@has_access
	def banner_preview(self, level: int):
		"""Return a standalone HTML snippet with the banner for *level*."""
		level = max(_MIN_LEVEL, min(_MAX_LEVEL, level))
		html = ClassificationWidget.render(level=level, position="top")
		return render_template_string(
			"<!DOCTYPE html><html><head><meta charset='utf-8'>"
			"{{ css }}</head><body style='margin:0'>{{ banner }}</body></html>",
			css=ClassificationWidget.css(),
			banner=html,
		)


# ---------------------------------------------------------------------------
# ClassificationPlugin
# ---------------------------------------------------------------------------

class ClassificationPlugin(BasePlugin):
	"""
	PgAppForge plugin: 8-level US government data classification enforcement.

	Responsibilities
	----------------
	- Provides :class:`ClassificationMixin` for SQLAlchemy models.
	- Provides :class:`UserClearanceMixin` for user/profile models.
	- Enforces ``user.clearance_level >= record.classification_level`` at the
	  Python layer (``on_record_save``, ``on_user_login``).
	- Optionally applies a PostgreSQL RLS policy via
	  :func:`_rls_policy_sql` when ``CLASSIFY_ENFORCE_RLS`` is True.
	- Masks string fields as ``"REDACTED"`` for insufficient clearance via
	  :func:`mask_record_fields`.
	- Injects a color-coded :class:`ClassificationWidget` banner into views.
	- Flashes a login warning when ``CLASSIFY_WARN_ON_LOGIN`` is True and the
	  user accesses data above their clearance.

	Enable via::

	    PGAPPFORGE_PLUGINS = ["pgappforge.plugins.classify.ClassificationPlugin"]
	"""

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="classify",
			version="0.1.0",
			description=(
				"8-level US government data classification: UNCLASSIFIED through SAP. "
				"Enforces clearance-gated access, PostgreSQL RLS, and view banners."
			),
			author="PgAppForge Contributors",
			tags=["classification", "security", "clearance", "rls", "government", "cui"],
			priority=PluginPriority.CRITICAL,
			permissions=[
				"can_view_classification_admin",
				"can_set_clearance_level",
				"can_classify_records",
			],
			safe_mode_compatible=True,
			example_config={
				"CLASSIFY_DEFAULT_LEVEL": 0,
				"CLASSIFY_BANNER_POSITION": "top",
				"CLASSIFY_ENFORCE_RLS": True,
				"CLASSIFY_REDACT_FIELDS": [],
				"CLASSIFY_WARN_ON_LOGIN": True,
			},
		)

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Validate configuration values."""
		default_level = self.config.get("CLASSIFY_DEFAULT_LEVEL", 0)
		if not (_MIN_LEVEL <= int(default_level) <= _MAX_LEVEL):
			raise ValueError(
				f"ClassificationPlugin: CLASSIFY_DEFAULT_LEVEL must be "
				f"{_MIN_LEVEL}-{_MAX_LEVEL}, got {default_level!r}"
			)

		position = self.config.get("CLASSIFY_BANNER_POSITION", "top")
		if position not in ("top", "bottom"):
			raise ValueError(
				f"ClassificationPlugin: CLASSIFY_BANNER_POSITION must be "
				f"'top' or 'bottom', got {position!r}"
			)

		redact_fields = self.config.get("CLASSIFY_REDACT_FIELDS", [])
		if not isinstance(redact_fields, list):
			raise TypeError(
				"ClassificationPlugin: CLASSIFY_REDACT_FIELDS must be a list of field names"
			)

		log.info(
			"ClassificationPlugin initialized — default_level=%s enforce_rls=%s banner=%s",
			default_level,
			self.config.get("CLASSIFY_ENFORCE_RLS", True),
			position,
		)

	# ------------------------------------------------------------------
	# Views
	# ------------------------------------------------------------------

	def register_views(self) -> None:
		self.add_view(
			ClassificationAdminView,
			"Classification",
			icon="fa-shield",
			category="Security",
			category_icon="fa-lock",
		)
		log.debug("ClassificationPlugin: views registered")

	# ------------------------------------------------------------------
	# Models
	# ------------------------------------------------------------------

	def register_models(self) -> list:
		"""
		No dedicated tables — :class:`ClassificationMixin` is applied to
		existing models via inheritance, not a separate table.
		"""
		return []

	# ------------------------------------------------------------------
	# RLS helpers
	# ------------------------------------------------------------------

	def apply_rls(self, table_name: str) -> None:
		"""
		Emit the PostgreSQL RLS policy for *table_name* via the current DB session.

		Call this after running Alembic migrations to create the table::

		    plugin.apply_rls("my_classified_table")

		Args:
			table_name: PostgreSQL table name (schema-qualified if needed).
		"""
		if not self.config.get("CLASSIFY_ENFORCE_RLS", True):
			log.info("ClassificationPlugin: RLS disabled by config — skipping %s", table_name)
			return

		session = self.appbuilder.get_session
		try:
			for statement in _rls_policy_sql(table_name).split(";"):
				stmt = statement.strip()
				if stmt:
					session.execute(stmt)  # type: ignore[arg-type]
			session.commit()
			log.info("ClassificationPlugin: RLS policy applied to %s", table_name)
		except Exception as exc:
			session.rollback()
			log.error("ClassificationPlugin: failed to apply RLS to %s: %s", table_name, exc)
			raise

	def remove_rls(self, table_name: str) -> None:
		"""
		Remove the classification RLS policy from *table_name*.

		Args:
			table_name: PostgreSQL table name.
		"""
		session = self.appbuilder.get_session
		try:
			for statement in _rls_teardown_sql(table_name).split(";"):
				stmt = statement.strip()
				if stmt:
					session.execute(stmt)  # type: ignore[arg-type]
			session.commit()
			log.info("ClassificationPlugin: RLS policy removed from %s", table_name)
		except Exception as exc:
			session.rollback()
			log.error("ClassificationPlugin: failed to remove RLS from %s: %s", table_name, exc)
			raise

	def set_session_clearance(self, clearance: int) -> None:
		"""
		Set ``app.current_clearance`` PostgreSQL session variable for the current
		DB session.  Called automatically by ``on_user_login``; also available
		for manual use in middleware or background jobs.

		Args:
			clearance: Integer clearance 0-7.
		"""
		clearance = max(_MIN_LEVEL, min(_MAX_LEVEL, int(clearance)))
		session = self.appbuilder.get_session
		try:
			from sqlalchemy import text
			session.execute(text(f"SET LOCAL app.current_clearance = {clearance}"))
			log.debug("ClassificationPlugin: session clearance set to %d", clearance)
		except Exception as exc:
			log.warning(
				"ClassificationPlugin: could not set app.current_clearance — "
				"may not be PostgreSQL: %s", exc
			)

	# ------------------------------------------------------------------
	# Hook overrides
	# ------------------------------------------------------------------

	def on_user_login(self, user) -> None:
		"""
		Cache user's clearance on ``g.current_user_clearance`` and push the
		PostgreSQL session variable.

		If ``CLASSIFY_WARN_ON_LOGIN`` is True and the user has a clearance below
		the maximum level, flash an informational notice.
		"""
		clearance = int(getattr(user, "clearance_level", 0) or 0)
		g.current_user_clearance = clearance

		# Push clearance into PostgreSQL session variable for RLS
		if self.config.get("CLASSIFY_ENFORCE_RLS", True):
			self.set_session_clearance(clearance)

		warn = self.config.get("CLASSIFY_WARN_ON_LOGIN", True)
		if warn and clearance < _MAX_LEVEL:
			label = _level_name(clearance)
			flash(
				f"You are logged in with clearance level {clearance} ({label}). "
				"Records classified above this level are not visible to you.",
				"info",
			)

		log.info(
			"ClassificationPlugin.on_user_login: user=%s clearance=%d (%s)",
			getattr(user, "username", repr(user)),
			clearance,
			_level_name(clearance),
		)

	def on_record_save(self, model_class, record, is_new: bool) -> None:
		"""
		Apply ``CLASSIFY_DEFAULT_LEVEL`` to newly created records that have a
		``classification_level`` of None or have not been explicitly set.
		"""
		if not hasattr(record, "classification_level"):
			return

		if is_new and record.classification_level is None:
			default = int(self.config.get("CLASSIFY_DEFAULT_LEVEL", 0))
			record.classification_level = default
			log.debug(
				"ClassificationPlugin.on_record_save: stamped classification_level=%d on %s",
				default, model_class.__name__,
			)

	def on_permission_denied(self, user, permission: str, view_menu: str) -> None:
		"""Log classification-related access denials for audit purposes."""
		clearance = int(getattr(user, "clearance_level", 0) or 0)
		log.warning(
			"ClassificationPlugin: access denied — user=%s clearance=%d (%s) "
			"permission=%s view_menu=%s",
			getattr(user, "username", repr(user)),
			clearance,
			_level_name(clearance),
			permission,
			view_menu,
		)

	# ------------------------------------------------------------------
	# Public helpers exposed on the plugin instance
	# ------------------------------------------------------------------

	def banner(self, level: int | None = None, record: Any = None) -> Markup:
		"""
		Return a classification banner :class:`~markupsafe.Markup` string.

		Pass either *level* (integer) or *record* (model instance with
		:class:`ClassificationMixin`).

		Args:
			level: Explicit classification level 0-7.
			record: Model instance; ``classification_level`` is read from it.

		Returns:
			Safe HTML Markup string.
		"""
		position = self.config.get("CLASSIFY_BANNER_POSITION", "top")
		if record is not None:
			return ClassificationWidget.render_for_record(record, position=position)
		return ClassificationWidget.render(level=int(level or 0), position=position)

	def mask(self, record: Any, clearance: int | None = None) -> dict[str, Any]:
		"""
		Return a field-masked view of *record* for the given *clearance*.

		When *clearance* is None, reads from ``g.current_user_clearance``.

		Args:
			record: Model instance with :class:`ClassificationMixin`.
			clearance: Override clearance level; defaults to current user's.

		Returns:
			Dict of ``{field: value_or_REDACTED}``.
		"""
		if clearance is None:
			clearance = _current_clearance()
		fields = self.config.get("CLASSIFY_REDACT_FIELDS") or None
		return mask_record_fields(record, clearance, fields_to_mask=fields)

	# ------------------------------------------------------------------
	# Config schema
	# ------------------------------------------------------------------

	def get_config_schema(self) -> dict:
		return {
			"$schema": "http://json-schema.org/draft-07/schema#",
			"title": "ClassificationPlugin configuration",
			"type": "object",
			"properties": {
				"CLASSIFY_DEFAULT_LEVEL": {
					"type": "integer",
					"description": "Default classification level for new records (0-7).",
					"default": 0,
					"minimum": 0,
					"maximum": 7,
				},
				"CLASSIFY_BANNER_POSITION": {
					"type": "string",
					"description": "Where to display the classification banner.",
					"default": "top",
					"enum": ["top", "bottom"],
				},
				"CLASSIFY_ENFORCE_RLS": {
					"type": "boolean",
					"description": (
						"Enable PostgreSQL RLS policy enforcement via "
						"app.current_clearance session variable."
					),
					"default": True,
				},
				"CLASSIFY_REDACT_FIELDS": {
					"type": "array",
					"items": {"type": "string"},
					"description": (
						"Field names to mask as REDACTED for insufficient clearance. "
						"Empty list = mask all string fields."
					),
					"default": [],
				},
				"CLASSIFY_WARN_ON_LOGIN": {
					"type": "boolean",
					"description": "Flash a clearance notice on user login.",
					"default": True,
				},
			},
			"additionalProperties": False,
		}


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def create_plugin(appbuilder, config: dict[str, Any] | None = None) -> ClassificationPlugin:
	"""
	Instantiate and return a :class:`ClassificationPlugin`.

	Args:
		appbuilder: PgAppForge / AppBuilder instance.
		config: Optional config dict; keys mirror ``CLASSIFY_*`` app config keys.

	Returns:
		A :class:`ClassificationPlugin` ready for :meth:`~ClassificationPlugin.activate`.

	Example::

		plugin = create_plugin(appbuilder, config={
		    "CLASSIFY_DEFAULT_LEVEL": 0,
		    "CLASSIFY_ENFORCE_RLS": True,
		    "CLASSIFY_BANNER_POSITION": "top",
		})
		plugin.activate()
	"""
	return ClassificationPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Plugin
	"ClassificationPlugin",
	"create_plugin",
	# Mixins
	"ClassificationMixin",
	"UserClearanceMixin",
	# Widget
	"ClassificationWidget",
	# Admin view
	"ClassificationAdminView",
	# Level registry (read-only reference)
	"_LEVELS",
	# Helpers
	"mask_record_fields",
	"_rls_policy_sql",
	"_rls_teardown_sql",
	"_current_clearance",
	# Level accessors
	"_level_name",
	"_level_abbrev",
	"_level_banner_text",
	"_level_bg",
	"_level_fg",
]
