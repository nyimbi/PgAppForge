"""
PgForge Theming Package

Global application theming system: CSS custom-property themes, responsive
overrides for FAB/Bootstrap 3, session-backed theme switching, and a
ThemeView picker UI.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import (
	Blueprint,
	make_response,
	redirect,
	render_template_string,
	request,
	session,
	url_for,
)

from .wizard_themes import (
	WizardAnimationSettings,
	WizardAnimationType,
	WizardColorPalette,
	WizardColorScheme,
	WizardLayoutStyle,
	WizardSpacing,
	WizardTheme,
	WizardThemeManager,
	WizardTypography,
	wizard_theme_manager,
)

log = logging.getLogger(__name__)

_SESSION_KEY = "pgforge_theme"
_COOKIE_KEY = "pgforge_theme"
_DEFAULT_THEME = "default"

# ---------------------------------------------------------------------------
# 1. BUILT_IN_THEMES
# ---------------------------------------------------------------------------

BUILT_IN_THEMES: dict[str, dict[str, str]] = {
	"default": {
		"--primary":       "#007bff",
		"--secondary":     "#6c757d",
		"--bg":            "#ffffff",
		"--text":          "#212529",
		"--navbar-bg":     "#343a40",
		"--sidebar-bg":    "#f8f9fa",
		"--card-bg":       "#ffffff",
		"--border":        "#dee2e6",
		"--font-family":   '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
		"--font-size-base":"14px",
		"--border-radius": "4px",
		"label":           "Default",
		"description":     "Clean Bootstrap 3 default palette",
	},
	"dark": {
		"--primary":       "#375a7f",
		"--secondary":     "#444444",
		"--bg":            "#222222",
		"--text":          "#dddddd",
		"--navbar-bg":     "#1a1a1a",
		"--sidebar-bg":    "#2b2b2b",
		"--card-bg":       "#2d2d2d",
		"--border":        "#444444",
		"--font-family":   '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
		"--font-size-base":"14px",
		"--border-radius": "4px",
		"label":           "Dark",
		"description":     "Dark theme for low-light environments",
	},
	"high-contrast": {
		"--primary":       "#0000cc",
		"--secondary":     "#006600",
		"--bg":            "#ffffff",
		"--text":          "#000000",
		"--navbar-bg":     "#000000",
		"--sidebar-bg":    "#eeeeee",
		"--card-bg":       "#ffffff",
		"--border":        "#000000",
		"--font-family":   'Arial, Helvetica, sans-serif',
		"--font-size-base":"16px",
		"--border-radius": "0px",
		"label":           "High Contrast",
		"description":     "WCAG AA/AAA accessibility theme",
	},
	"government": {
		"--primary":       "#003366",
		"--secondary":     "#336699",
		"--bg":            "#f5f5f5",
		"--text":          "#1a1a1a",
		"--navbar-bg":     "#003366",
		"--sidebar-bg":    "#e8edf2",
		"--card-bg":       "#ffffff",
		"--border":        "#c0c8d0",
		"--font-family":   '"Open Sans", Arial, sans-serif',
		"--font-size-base":"14px",
		"--border-radius": "2px",
		"label":           "Government",
		"description":     "Formal blue palette for public-sector deployments",
	},
	"minimal": {
		"--primary":       "#333333",
		"--secondary":     "#999999",
		"--bg":            "#ffffff",
		"--text":          "#333333",
		"--navbar-bg":     "#ffffff",
		"--sidebar-bg":    "#fafafa",
		"--card-bg":       "#ffffff",
		"--border":        "#e0e0e0",
		"--font-family":   '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
		"--font-size-base":"13px",
		"--border-radius": "2px",
		"label":           "Minimal",
		"description":     "Near-invisible chrome, content first",
	},
	"corporate": {
		"--primary":       "#c0392b",
		"--secondary":     "#2c3e50",
		"--bg":            "#f9f9f9",
		"--text":          "#2c3e50",
		"--navbar-bg":     "#2c3e50",
		"--sidebar-bg":    "#ecf0f1",
		"--card-bg":       "#ffffff",
		"--border":        "#bdc3c7",
		"--font-family":   '"Helvetica Neue", Helvetica, Arial, sans-serif',
		"--font-size-base":"14px",
		"--border-radius": "3px",
		"label":           "Corporate",
		"description":     "Bold red-and-slate enterprise branding",
	},
}

# ---------------------------------------------------------------------------
# 2. RESPONSIVE_CSS
# ---------------------------------------------------------------------------

RESPONSIVE_CSS: str = """
/* ── PgForge responsive overrides for FAB / Bootstrap 3 ── */

/* Sidebar collapse on narrow viewports */
@media (max-width: 767px) {
	/* FAB sidebar */
	.side-nav,
	#sidebar-wrapper,
	.sidebar-wrapper {
		position: fixed;
		top: 50px;
		left: -240px;
		width: 240px;
		height: calc(100vh - 50px);
		overflow-y: auto;
		transition: left 0.25s ease;
		z-index: 1040;
		background: var(--sidebar-bg, #f8f9fa);
	}
	.sidebar-open .side-nav,
	.sidebar-open #sidebar-wrapper,
	.sidebar-open .sidebar-wrapper {
		left: 0;
	}
	/* Hamburger toggle button */
	.sidebar-toggle {
		display: block !important;
	}
	/* Push main content flush left */
	#page-wrapper,
	.page-wrapper,
	.container-fluid.main {
		margin-left: 0 !important;
		padding-left: 10px;
		padding-right: 10px;
	}
}

/* Hamburger button hidden by default on wide screens */
.sidebar-toggle {
	display: none;
	background: transparent;
	border: none;
	font-size: 20px;
	line-height: 50px;
	padding: 0 15px;
	cursor: pointer;
	color: #fff;
}

/* Tables horizontally scrollable on small screens */
@media (max-width: 767px) {
	.table-responsive {
		display: block;
		width: 100%;
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
	/* Wrap plain tables that aren't already in .table-responsive */
	table.table:not(.table-responsive table) {
		display: block;
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}
}

/* 44 px minimum touch target for buttons and links */
@media (max-width: 767px) {
	.btn,
	a.btn,
	button,
	input[type="button"],
	input[type="submit"],
	input[type="reset"],
	.nav > li > a,
	.pagination > li > a,
	.pagination > li > span {
		min-height: 44px;
		min-width: 44px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding-left: 12px;
		padding-right: 12px;
	}
}

/* Readable font sizes on mobile — prevent iOS auto-zoom on focus */
@media (max-width: 767px) {
	body {
		font-size: 16px;
	}
	input,
	select,
	textarea {
		font-size: 16px !important; /* prevents iOS zoom */
	}
	h1 { font-size: 1.6rem; }
	h2 { font-size: 1.4rem; }
	h3 { font-size: 1.2rem; }
	.navbar-brand {
		font-size: 1rem;
	}
}
"""

# ---------------------------------------------------------------------------
# 3. ThemeManager
# ---------------------------------------------------------------------------

class ThemeManager:
	"""
	Registers CSS endpoints, injects theme <link> tags via after_request,
	and manages the active theme per-session / per-cookie.

	Usage::

		from pgappforge.theming import theme_manager
		theme_manager.init_app(app, appbuilder)
	"""

	def __init__(self) -> None:
		self._app: Any = None
		self._appbuilder: Any = None

	# ── lifecycle ──────────────────────────────────────────────────────────

	def init_app(self, app: Any, appbuilder: Any | None = None) -> None:
		"""
		Attach to a Flask *app* (and optionally an AppBuilder instance).

		Registers:
		  - A ``/themes/<name>.css`` route serving generated CSS.
		  - An after_request hook that injects ``<link>`` and
		    ``<meta name=theme-color>`` into HTML responses.
		"""
		self._app = app
		self._appbuilder = appbuilder

		bp = Blueprint(
			"pgforge_themes",
			__name__,
			url_prefix="/themes",
		)

		@bp.route("/<name>.css")
		def theme_css(name: str):
			css = self.generate_css(name)
			resp = make_response(css, 200)
			resp.headers["Content-Type"] = "text/css; charset=utf-8"
			resp.headers["Cache-Control"] = "public, max-age=86400"
			return resp

		app.register_blueprint(bp)

		# Inject <link> tag into every HTML response
		app.after_request(self._inject_theme_link)

		log.debug("ThemeManager initialised")

	def _inject_theme_link(self, response: Any) -> Any:
		"""after_request: splice theme <link> + meta into <head>."""
		ct = response.content_type or ""
		if "text/html" not in ct:
			return response

		try:
			active = self.get_active_theme(request)
			theme_data = BUILT_IN_THEMES.get(active, BUILT_IN_THEMES[_DEFAULT_THEME])
			primary = theme_data.get("--primary", "#007bff")

			css_url = f"/themes/{active}.css"
			link_tag = (
				f'<link rel="stylesheet" href="{css_url}">'
				f'<meta name="theme-color" content="{primary}">'
			)

			data = response.get_data(as_text=True)
			if "<head>" in data:
				data = data.replace("<head>", f"<head>\n    {link_tag}", 1)
				response.set_data(data)
		except Exception:
			log.exception("ThemeManager._inject_theme_link failed")

		return response

	# ── CSS generation ─────────────────────────────────────────────────────

	def generate_css(self, theme_name: str) -> str:
		"""
		Return a complete CSS string for *theme_name*.

		Includes:
		  - ``:root { --primary: …; … }`` from BUILT_IN_THEMES
		  - Concrete selector overrides mapping vars onto FAB/Bootstrap elements
		  - RESPONSIVE_CSS appended at the end
		"""
		theme_data = BUILT_IN_THEMES.get(theme_name)
		if theme_data is None:
			log.warning("Unknown theme %r, falling back to default", theme_name)
			theme_data = BUILT_IN_THEMES[_DEFAULT_THEME]

		# Build :root block — skip non-CSS metadata keys
		css_props = {k: v for k, v in theme_data.items() if k.startswith("--")}
		root_lines = "\n".join(f"\t{k}: {v};" for k, v in css_props.items())

		concrete = """
/* ── Concrete FAB / Bootstrap 3 overrides using CSS vars ── */

body {
	background-color: var(--bg);
	color: var(--text);
	font-family: var(--font-family);
	font-size: var(--font-size-base);
}

/* Navbar */
.navbar-inverse,
.navbar-default,
.navbar {
	background-color: var(--navbar-bg) !important;
	border-color: var(--border);
}
.navbar-inverse .navbar-brand,
.navbar-inverse .navbar-nav > li > a {
	color: #ffffff !important;
}

/* Sidebar */
.side-nav,
#sidebar-wrapper,
.sidebar-wrapper {
	background-color: var(--sidebar-bg);
	border-right: 1px solid var(--border);
}

/* Cards / panels */
.panel,
.card,
.well {
	background-color: var(--card-bg);
	border: 1px solid var(--border);
	border-radius: var(--border-radius);
}
.panel-heading,
.card-header {
	background-color: var(--primary);
	color: #ffffff;
	border-radius: calc(var(--border-radius) - 1px) calc(var(--border-radius) - 1px) 0 0;
}

/* Buttons */
.btn-primary {
	background-color: var(--primary);
	border-color: var(--primary);
	color: #ffffff;
	border-radius: var(--border-radius);
}
.btn-primary:hover,
.btn-primary:focus {
	background-color: color-mix(in srgb, var(--primary) 85%, #000);
	border-color: color-mix(in srgb, var(--primary) 80%, #000);
	color: #ffffff;
}
.btn-default {
	background-color: var(--card-bg);
	border-color: var(--border);
	color: var(--text);
	border-radius: var(--border-radius);
}
.btn-secondary {
	background-color: var(--secondary);
	border-color: var(--secondary);
	color: #ffffff;
	border-radius: var(--border-radius);
}

/* Tables */
.table > thead > tr > th {
	background-color: var(--sidebar-bg);
	border-bottom: 2px solid var(--border);
	color: var(--text);
}
.table > tbody > tr > td,
.table > tbody > tr > th {
	border-top: 1px solid var(--border);
}
.table-striped > tbody > tr:nth-of-type(odd) {
	background-color: color-mix(in srgb, var(--sidebar-bg) 60%, var(--bg));
}
.table-hover > tbody > tr:hover {
	background-color: color-mix(in srgb, var(--primary) 10%, var(--bg));
}

/* Form controls */
.form-control {
	background-color: var(--bg);
	border: 1px solid var(--border);
	border-radius: var(--border-radius);
	color: var(--text);
}
.form-control:focus {
	border-color: var(--primary);
	outline: 0;
	box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent);
}

/* Links */
a {
	color: var(--primary);
}
a:hover {
	color: color-mix(in srgb, var(--primary) 75%, #000);
}

/* Pagination */
.pagination > li > a,
.pagination > li > span {
	color: var(--primary);
	border-color: var(--border);
	background-color: var(--card-bg);
}
.pagination > .active > a,
.pagination > .active > span {
	background-color: var(--primary);
	border-color: var(--primary);
	color: #ffffff;
}

/* Breadcrumbs */
.breadcrumb {
	background-color: var(--sidebar-bg);
	border: 1px solid var(--border);
	border-radius: var(--border-radius);
}
"""

		return f":root {{\n{root_lines}\n}}\n{concrete}\n{RESPONSIVE_CSS}"

	# ── theme accessors ────────────────────────────────────────────────────

	def get_theme(self, name: str) -> dict[str, str]:
		"""Return the theme dict for *name*, falling back to default."""
		return dict(BUILT_IN_THEMES.get(name, BUILT_IN_THEMES[_DEFAULT_THEME]))

	def list_themes(self) -> list[dict[str, str]]:
		"""
		Return a list of theme summary dicts suitable for UI rendering.

		Each dict has keys: ``name``, ``label``, ``description``,
		``primary``, ``bg``, ``text``.
		"""
		out: list[dict[str, str]] = []
		for name, data in BUILT_IN_THEMES.items():
			out.append({
				"name":        name,
				"label":       data.get("label", name),
				"description": data.get("description", ""),
				"primary":     data.get("--primary", "#007bff"),
				"bg":          data.get("--bg", "#ffffff"),
				"text":        data.get("--text", "#212529"),
				"navbar_bg":   data.get("--navbar-bg", "#343a40"),
			})
		return out

	def set_active_theme(self, name: str, use_session: bool = True) -> None:
		"""
		Persist *name* as the active theme.

		If *use_session* is True (default) the value is stored in the
		Flask session.  The caller is responsible for also setting the
		response cookie when needed (ThemeView does this).
		"""
		if name not in BUILT_IN_THEMES:
			log.warning("set_active_theme: unknown theme %r ignored", name)
			return
		if use_session:
			session[_SESSION_KEY] = name

	def get_active_theme(self, req: Any | None = None) -> str:
		"""
		Resolve active theme name from (in priority order):

		1. Flask session
		2. Cookie on the incoming request
		3. ``_DEFAULT_THEME``
		"""
		# session (highest priority — already authenticated user preference)
		name = session.get(_SESSION_KEY)
		if name and name in BUILT_IN_THEMES:
			return name

		# cookie fallback (unauthenticated / cross-session)
		if req is not None:
			name = req.cookies.get(_COOKIE_KEY)
			if name and name in BUILT_IN_THEMES:
				return name

		return _DEFAULT_THEME


# Module-level singleton
theme_manager = ThemeManager()

# ---------------------------------------------------------------------------
# 4. ThemeView
# ---------------------------------------------------------------------------

# Inline template — avoids needing a templates/ folder inside this package
_PICKER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Choose Theme</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; padding: 2rem; background: var(--bg, #fff); color: var(--text, #222); }
        h1   { margin-bottom: 1.5rem; }
        .swatches { display: flex; flex-wrap: wrap; gap: 1.25rem; }
        .swatch {
            width: 180px;
            border: 2px solid #ccc;
            border-radius: 6px;
            overflow: hidden;
            cursor: pointer;
            transition: box-shadow .15s;
        }
        .swatch:hover { box-shadow: 0 4px 16px rgba(0,0,0,.18); }
        .swatch.active { border-color: #007bff; box-shadow: 0 0 0 3px rgba(0,123,255,.35); }
        .swatch-preview {
            height: 56px;
        }
        .swatch-info { padding: .6rem .75rem; background: #fff; }
        .swatch-name { font-weight: 600; font-size: .95rem; }
        .swatch-desc { font-size: .78rem; color: #666; margin-top: .15rem; }
        form { margin: 0; }
        button.apply {
            margin-top: .5rem;
            width: 100%;
            padding: .4rem;
            border: none;
            border-radius: 4px;
            background: {{ theme.primary }};
            color: #fff;
            cursor: pointer;
            font-size: .85rem;
        }
    </style>
</head>
<body>
<h1>Choose Application Theme</h1>
<p>Active theme: <strong>{{ active }}</strong></p>
<div class="swatches">
{% for t in themes %}
    <div class="swatch {% if t.name == active %}active{% endif %}">
        <div class="swatch-preview"
             style="background: linear-gradient(135deg, {{ t.primary }} 50%, {{ t.navbar_bg }} 50%);"></div>
        <div class="swatch-info">
            <div class="swatch-name">{{ t.label }}</div>
            <div class="swatch-desc">{{ t.description }}</div>
            <form action="{{ set_url }}" method="POST">
                <input type="hidden" name="theme" value="{{ t.name }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                <button class="apply" type="submit"
                        style="background:{{ t.primary }}">Apply</button>
            </form>
        </div>
    </div>
{% endfor %}
</div>
</body>
</html>
"""


def _get_csrf_token() -> str:
	"""Return the WTF csrf token if flask-wtf is present, else empty string."""
	try:
		from flask_wtf.csrf import generate_csrf  # type: ignore[import-untyped]
		return generate_csrf()
	except Exception:
		return ""


def _build_theme_view_class() -> type:
	"""
	Build ThemeView dynamically so the import of BaseView / has_access /
	expose is deferred — those live in pgappforge, which imports us.
	"""
	from pgappforge.baseviews import BaseView, expose
	from pgappforge.security.decorators import has_access

	class ThemeView(BaseView):
		"""
		Theme picker UI mounted at /theme/.

		GET  /theme/     — render swatch picker
		POST /theme/set  — persist chosen theme in session + cookie, redirect back
		"""

		route_base = "/theme"
		default_view = "index"

		@expose("/")
		@has_access
		def index(self):
			active = theme_manager.get_active_theme(request)
			themes = theme_manager.list_themes()
			# Resolve set URL without needing the blueprint to be registered yet
			try:
				set_url = url_for("ThemeView.set_theme")
			except Exception:
				set_url = "/theme/set"

			html = render_template_string(
				_PICKER_TEMPLATE,
				active=active,
				themes=themes,
				theme=theme_manager.get_theme(active),
				set_url=set_url,
				csrf_token=_get_csrf_token(),
			)
			return html

		@expose("/set", methods=["POST"])
		@has_access
		def set_theme(self):
			name = request.form.get("theme", _DEFAULT_THEME)
			theme_manager.set_active_theme(name, use_session=True)

			# Determine redirect target — honour Referer, else go to /
			referrer = request.referrer or "/"
			resp = redirect(referrer)
			# Also persist in a long-lived cookie so the choice survives logout
			resp.set_cookie(
				_COOKIE_KEY,
				name,
				max_age=60 * 60 * 24 * 365,
				samesite="Lax",
				httponly=False,  # JS may read it for preview purposes
			)
			return resp

	return ThemeView


# Lazy class — instantiated on first attribute access so circular imports
# between pgappforge.theming and pgappforge.baseviews are avoided.
class _LazyThemeView:
	_cls: type | None = None

	def __getattr__(self, name: str):
		if _LazyThemeView._cls is None:
			_LazyThemeView._cls = _build_theme_view_class()
		return getattr(_LazyThemeView._cls, name)

	def __call__(self, *args, **kwargs):
		if _LazyThemeView._cls is None:
			_LazyThemeView._cls = _build_theme_view_class()
		return _LazyThemeView._cls(*args, **kwargs)


ThemeView = _LazyThemeView()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	# Global theming
	"BUILT_IN_THEMES",
	"RESPONSIVE_CSS",
	"ThemeManager",
	"ThemeView",
	"theme_manager",
	# Wizard theming (re-exported for backwards compat)
	"WizardTheme",
	"WizardThemeManager",
	"WizardColorScheme",
	"WizardLayoutStyle",
	"WizardAnimationType",
	"WizardColorPalette",
	"WizardTypography",
	"WizardSpacing",
	"WizardAnimationSettings",
	"wizard_theme_manager",
]
