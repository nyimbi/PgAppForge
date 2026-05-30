"""Help and training views for PgAppForge."""
from __future__ import annotations

from flask import request, render_template_string

from pgappforge.baseviews import BaseView, expose

# ---------------------------------------------------------------------------
# Shared topic content — single source of truth used by both views and CLI
# ---------------------------------------------------------------------------

TOPICS: dict[str, dict[str, str]] = {
	"getting-started": {
		"title": "Getting Started with PgAppForge",
		"keywords": "install setup quickstart scaffold skeleton",
		"content": """\
PgAppForge (FAB) is a rapid application development framework built on
Flask. It generates CRUD UIs, REST APIs, and a security system from your
SQLAlchemy models.

Quick start
-----------
1.  Install:  pip install flask-appbuilder
2.  Scaffold: flask fab create-app --name MyApp --engine SQLAlchemy
3.  Run:      flask run

The scaffold creates:
  app/            - application package
  app/__init__.py - AppBuilder initialisation
  app/models.py   - place your SQLAlchemy models here
  app/views.py    - register ModelView subclasses here
  config.py       - Flask & FAB configuration
  run.py          - development entry-point

Key config variables
  SQLALCHEMY_DATABASE_URI  - database connection string (required)
  SECRET_KEY               - Flask secret key, minimum 20 characters (required)
  APP_NAME                 - displayed in the navbar (default "F.A.B.")
  FAB_UPDATE_PERMS         - auto-sync permissions on startup (default True)
""",
	},
	"crud-operations": {
		"title": "CRUD Operations",
		"keywords": "crud create read update delete modelview list show add edit",
		"content": """\
ModelView auto-generates list, show, add, edit, and delete views from a
SQLAlchemy model.

Minimal example
---------------
  from pgappforge import ModelView
  from pgappforge.models.sqla.interface import SQLAInterface
  from .models import Contact

  class ContactView(ModelView):
      datamodel = SQLAInterface(Contact)
      list_columns = ['name', 'email', 'phone']
      show_columns = ['name', 'email', 'phone', 'address']
      add_columns  = ['name', 'email', 'phone']
      edit_columns = ['name', 'email', 'phone']

  appbuilder.add_view(ContactView, "Contacts", icon="fa-address-book",
                      category="Contacts")

Column control attributes
  list_columns      - columns shown on the list page
  show_columns      - columns shown on the detail page
  add_columns       - fields in the add form
  edit_columns      - fields in the edit form
  search_columns    - columns used in the search widget
  label_columns     - dict mapping column name → display label
  description_columns - dict mapping column name → help text

Validators
  Add / edit forms respect WTForms validators defined on the model or via
  add_form_extra_fields / edit_form_extra_fields.

Actions
  Bulk operations can be added with the @action decorator:

    @action("send_email", "Send Email", "Send email to all selected?", "fa-envelope")
    def send_email(self, items):
        ...
""",
	},
	"security-permissions": {
		"title": "Security and Permissions",
		"keywords": "security auth roles permissions rbac oauth ldap mfa login",
		"content": """\
FAB ships a full role-based access control (RBAC) system with automatic
permission generation.

Authentication backends
  AUTH_DB          - username/password stored in the FAB user table (default)
  AUTH_LDAP        - bind against an LDAP directory
  AUTH_OAUTH       - delegate to OAuth2 providers (GitHub, Google, Azure …)
  AUTH_OID         - OpenID 2.0 (legacy)
  AUTH_REMOTE_USER - trust REMOTE_USER header (reverse-proxy SSO)

Set the backend in config.py:
  AUTH_TYPE = AUTH_OAUTH

Roles
  FAB creates the Admin role automatically. Custom roles are created through
  the Security → Roles menu or programmatically:

    security_manager.add_role("Analyst")

Permissions
  Every view method (list, show, add, edit, delete) gets a permission tuple
  (can_<method>, <ViewClassName>) generated at startup when FAB_UPDATE_PERMS
  is True.

  Assigning permissions to roles is done through Security → Roles → Edit.

Decorators
  @has_access               - requires any authenticated session
  @permission_name("read")  - override the auto-generated permission name
  @protect                  - REST API equivalent of @has_access

Custom security manager
  Subclass SecurityManager and point FAB at it:

    FAB_SECURITY_MANAGER_CLASS = "app.security.MySecurityManager"
""",
	},
	"database-codegen": {
		"title": "Database Codegen (flask fab gen all)",
		"keywords": "codegen generate scaffold models views introspect sqlacodegen",
		"content": """\
FAB can introspect an existing database and generate models and views.

Commands
  flask fab gen all       - generate models + views for every table
  flask fab gen models    - generate SQLAlchemy model classes only
  flask fab gen views     - generate ModelView classes from existing models

Typical workflow
  1. Point SQLALCHEMY_DATABASE_URI at your existing database.
  2. Run:  flask fab gen all --output-dir app/
  3. Review the generated files and add them to app/__init__.py.
  4. Run the app and visit the auto-created CRUD views.

Options (flask fab gen all)
  --output-dir    destination directory (default: current working directory)
  --prefix        class name prefix (e.g. "Db" → DbUserView)
  --overwrite     overwrite existing files without prompting

Notes
  - Composite primary keys are detected and handled.
  - Foreign keys become RelatedField widgets automatically.
  - Generated code is a starting point; review and customise before production.
""",
	},
	"deploy-commands": {
		"title": "Deploy Commands (flask fab deploy)",
		"keywords": "deploy production gunicorn docker supervisor systemd",
		"content": """\
flask fab deploy automates production deployment scaffolding.

Subcommands
  flask fab deploy gunicorn    - write gunicorn config + systemd unit file
  flask fab deploy docker      - generate Dockerfile + docker-compose.yml
  flask fab deploy supervisor  - write a supervisor.conf entry
  flask fab deploy nginx       - generate an nginx site config

Common options
  --bind         gunicorn bind address (default 0.0.0.0:8000)
  --workers      number of worker processes (default: 2 × CPU + 1)
  --output-dir   where to write generated files (default: deploy/)

Minimal production checklist
  1. Set DEBUG = False and a strong SECRET_KEY in config.py.
  2. Use a production database (PostgreSQL recommended).
  3. Run database migrations: flask db upgrade.
  4. Collect / serve static files via a CDN or nginx alias.
  5. Set WTF_CSRF_ENABLED = True (default in FAB).
""",
	},
	"postgresql-types-widgets": {
		"title": "PostgreSQL Types and Widgets",
		"keywords": "postgresql postgres jsonb array hstore widget fieldwidget",
		"content": """\
FAB has first-class support for PostgreSQL-specific column types.

Supported types
  JSONB / JSON    - rendered as a JSON textarea with syntax validation
  ARRAY           - rendered as a comma-separated input (or multi-select)
  HSTORE          - rendered as key=value pairs widget
  UUID            - rendered as text, validated as UUID4
  CIDR / INET     - rendered as text with network-address validation
  TSVECTOR        - read-only display widget

Widget mapping in views.py
  from pgappforge.fieldwidgets import BS3TextAreaFieldWidget
  from pgappforge.forms import DynamicForm
  from wtforms import TextAreaField

  class MyView(ModelView):
      add_form_extra_fields = {
          "payload": TextAreaField("Payload",
                                  widget=BS3TextAreaFieldWidget())
      }

Custom widget for JSONB
  Subclass AJAXSelectWidget or write a Jinja2 macro and register it via
  fieldwidgets.py. The widgets_postgresql package (pgappforge/widgets_postgresql/)
  contains ready-made widgets for all PostgreSQL-specific types.

Gotchas
  - Always set server_default on JSONB columns to avoid NULL vs {} confusion.
  - ARRAY columns need postgresql_using="gin" on the index for fast searches.
  - Use func.jsonb_build_object() in SQLAlchemy for JSONB construction.
""",
	},
	"mixins": {
		"title": "Mixins Usage",
		"keywords": "mixin reuse multiple inheritance compactcrud auditlog timestamp",
		"content": """\
FAB provides mixins that add standard behaviours without boilerplate.

Built-in mixins (pgappforge/mixins/)
  AuditMixin        - created_by, changed_by, created_on, changed_on columns
  FileColumn        - file upload handling linked to a model column
  ImageColumn       - image upload with thumbnail generation
  CompactCRUDMixin  - merges the show / add / edit views into a single page

AuditMixin example
  from pgappforge.models.mixins import AuditMixin
  from pgappforge import Model
  from sqlalchemy import Column, Integer, String

  class Article(AuditMixin, Model):
      id      = Column(Integer, primary_key=True)
      title   = Column(String(200), nullable=False)
      body    = Column(Text)

  FAB populates created_by / changed_by automatically from the current user.

CompactCRUDMixin
  class ContactView(CompactCRUDMixin, ModelView):
      datamodel    = SQLAInterface(Contact)
      list_columns = ['name', 'email']

  This renders inline add/edit forms in the list page rather than separate routes.

Multi-tenant mixins (pgappforge/mixins/)
  TenantMixin       - adds tenant_id FK and filters all queries by current tenant
  Use alongside the multi-tenant security manager for SaaS applications.

Writing your own mixin
  Any SQLAlchemy mixin that declares columns can be used. Python's MRO handles
  column ordering — put mixins before Model in the class bases.
""",
	},
	"api-endpoints": {
		"title": "REST API Endpoints",
		"keywords": "api rest openapi swagger modelrestapi json endpoint",
		"content": """\
FAB auto-generates a JSON REST API alongside (or instead of) the HTML UI.

ModelRestApi
  from pgappforge.api import ModelRestApi
  from pgappforge.models.sqla.interface import SQLAInterface
  from .models import Contact

  class ContactApi(ModelRestApi):
      resource_name = "contact"
      datamodel      = SQLAInterface(Contact)

  appbuilder.add_api(ContactApi)

Generated endpoints (base URL: /api/v1/contact/)
  GET    /         - list (supports _filters, _order_column, _page, _page_size)
  POST   /         - create
  GET    /<pk>     - retrieve one record
  PUT    /<pk>     - full update
  PATCH  /<pk>     - partial update (FAB extension)
  DELETE /<pk>     - delete
  GET    /_info    - schema information (column types, validators)

OpenAPI / Swagger
  Auto-generated spec served at /swagger/v1 and interactive UI at /swaggerview/v1.

Authentication
  Use JWT (flask-jwt-extended):
    POST /api/v1/security/login  { "username": "…", "password": "…" }
    Response includes access_token — pass as Bearer token on subsequent requests.

Filtering syntax
  GET /api/v1/contact/?_filters=[{"col":"name","opr":"sw","value":"A"}]

  Operators: eq, neq, gt, gte, lt, lte, like, ilike, sw (starts-with), ew (ends-with)

Pagination
  _page=0&_page_size=25   (page numbers are zero-based)
""",
	},
}


# ---------------------------------------------------------------------------
# Templates (Bootstrap 3 compatible, no external files needed)
# ---------------------------------------------------------------------------

_BASE_LAYOUT = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ page_title }} — FAB Help</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <style>
    body { padding-top: 20px; }
    .help-sidebar { background: #f5f5f5; padding: 15px; border-radius: 4px; }
    .help-sidebar a { display: block; padding: 4px 0; }
    .topic-content pre { background: #f9f9f9; padding: 12px; border-radius: 4px;
                         white-space: pre-wrap; word-break: break-word; }
    .search-bar { margin-bottom: 20px; }
    .tutorial-step { border-left: 4px solid #337ab7; padding-left: 15px; margin-bottom: 20px; }
    .step-number { display: inline-block; background: #337ab7; color: #fff;
                   border-radius: 50%; width: 28px; height: 28px; line-height: 28px;
                   text-align: center; margin-right: 8px; font-weight: bold; }
  </style>
</head>
<body>
<div class="container-fluid">
  <div class="row">
    <div class="col-md-2 help-sidebar">
      <h4><a href="/help/">Help Topics</a></h4>
      {% for slug, topic in topics.items() %}
      <a href="/help/topic/{{ slug }}">{{ topic.title }}</a>
      {% endfor %}
      <hr>
      <h4><a href="/training/">Training</a></h4>
      <h4><a href="/admin-guide/">Admin Guide</a></h4>
    </div>
    <div class="col-md-10">
      {{ body | safe }}
    </div>
  </div>
</div>
</body>
</html>
"""

_HELP_INDEX = """\
<h2>PgAppForge Help</h2>
<form method="GET" action="/help/search" class="search-bar">
  <div class="input-group">
    <input type="text" name="q" class="form-control" placeholder="Search help…"
           value="{{ query | e }}">
    <span class="input-group-btn">
      <button class="btn btn-default" type="submit">Search</button>
    </span>
  </div>
</form>
<div class="row">
  {% for slug, topic in topics.items() %}
  <div class="col-md-6" style="margin-bottom:20px">
    <div class="panel panel-default">
      <div class="panel-heading">
        <h3 class="panel-title"><a href="/help/topic/{{ slug }}">{{ topic.title }}</a></h3>
      </div>
      <div class="panel-body">
        <small>{{ topic.keywords }}</small>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
"""

_HELP_SEARCH = """\
<h2>Search results for <em>{{ query | e }}</em></h2>
<a href="/help/" class="btn btn-default btn-sm" style="margin-bottom:15px">← All Topics</a>
{% if results %}
  {% for slug, topic in results %}
  <div class="panel panel-default">
    <div class="panel-heading">
      <h3 class="panel-title"><a href="/help/topic/{{ slug }}">{{ topic.title }}</a></h3>
    </div>
    <div class="panel-body"><small>{{ topic.keywords }}</small></div>
  </div>
  {% endfor %}
{% else %}
  <div class="alert alert-info">No topics found for <strong>{{ query | e }}</strong>.</div>
{% endif %}
"""

_HELP_TOPIC = """\
<h2>{{ topic.title }}</h2>
<a href="/help/" class="btn btn-default btn-sm" style="margin-bottom:15px">← All Topics</a>
<div class="panel panel-default">
  <div class="panel-body topic-content">
    <pre>{{ topic.content }}</pre>
  </div>
</div>
"""

_TRAINING_INDEX = """\
<h2>Interactive Training Modules</h2>
<p class="text-muted">Step-by-step guides to mastering PgAppForge.</p>
<div class="list-group">
  {% for mod in modules %}
  <a href="/training/module/{{ mod.slug }}" class="list-group-item">
    <h4 class="list-group-item-heading">{{ mod.title }}</h4>
    <p class="list-group-item-text">{{ mod.description }}</p>
    <span class="badge">{{ mod.steps | length }} steps</span>
  </a>
  {% endfor %}
</div>
"""

_TRAINING_MODULE = """\
<h2>{{ module.title }}</h2>
<p class="text-muted">{{ module.description }}</p>
<a href="/training/" class="btn btn-default btn-sm" style="margin-bottom:15px">← All Modules</a>
{% for step in module.steps %}
<div class="tutorial-step">
  <h4><span class="step-number">{{ loop.index }}</span>{{ step.title }}</h4>
  <pre style="background:#f9f9f9;padding:12px;border-radius:4px">{{ step.content }}</pre>
</div>
{% endfor %}
<div class="alert alert-success">
  <strong>Module complete!</strong> Return to <a href="/training/">all modules</a>
  or continue with <a href="/help/">help topics</a>.
</div>
"""

_ADMIN_GUIDE = """\
<h2>System Admin Reference</h2>
<div class="panel panel-default">
  <div class="panel-heading"><h3 class="panel-title">User Management</h3></div>
  <div class="panel-body">
    <p>Navigate to <strong>Security → List Users</strong> to create, edit, reset passwords
    or deactivate accounts. Users can belong to multiple roles.</p>
  </div>
</div>
<div class="panel panel-default">
  <div class="panel-heading"><h3 class="panel-title">Role & Permission Management</h3></div>
  <div class="panel-body">
    <p>Roles aggregate permission tuples (<em>can_list</em>, <em>MyView</em>).
    Go to <strong>Security → Roles</strong> to add/remove permissions from a role.
    Run <code>flask fab security-converge</code> after renaming views.</p>
  </div>
</div>
<div class="panel panel-default">
  <div class="panel-heading"><h3 class="panel-title">Database Migrations</h3></div>
  <div class="panel-body">
    <p>FAB integrates Alembic. Use <code>flask db init</code>,
    <code>flask db migrate -m "msg"</code>, and <code>flask db upgrade</code>.</p>
  </div>
</div>
<div class="panel panel-default">
  <div class="panel-heading"><h3 class="panel-title">Useful Admin CLI Commands</h3></div>
  <div class="panel-body">
<pre>flask fab create-admin          # create the first admin account
flask fab reset-password        # reset any user's password
flask fab security-converge     # sync permissions after view renames
flask fab list-users            # tabulate all users
flask fab list-views            # show registered views and their routes
flask fab gen all               # generate models + views from the DB schema
flask fab deploy gunicorn       # scaffold gunicorn / systemd config</pre>
  </div>
</div>
<div class="panel panel-default">
  <div class="panel-heading"><h3 class="panel-title">Configuration Quick Reference</h3></div>
  <div class="panel-body">
<pre>SQLALCHEMY_DATABASE_URI  = "postgresql+psycopg2://user:pass@host/dbname"
SECRET_KEY               = "at-least-20-random-characters"
AUTH_TYPE                = AUTH_OAUTH          # AUTH_DB | AUTH_LDAP | AUTH_OAUTH
WTF_CSRF_ENABLED         = True
FAB_UPDATE_PERMS         = True
FAB_SECURITY_MANAGER_CLASS = "app.security.MySecurityManager"
ADDON_MANAGERS           = ["app.addons.MyAddon"]
APP_NAME                 = "My Application"
APP_THEME                = "bootstrap-3.3.7.min.css"</pre>
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Training data — modules with sequential steps
# ---------------------------------------------------------------------------

TRAINING_MODULES: list[dict] = [
	{
		"slug": "getting-started",
		"title": "Getting Started",
		"description": "Install FAB and run your first application from scratch.",
		"steps": [
			{
				"title": "Install PgAppForge",
				"content": "pip install flask-appbuilder\n\n# Verify installation\nflask --version\npython -c 'import pgappforge; print(pgappforge.__version__)'",
			},
			{
				"title": "Scaffold a new project",
				"content": "flask fab create-app --name MyApp --engine SQLAlchemy\ncd MyApp",
			},
			{
				"title": "Configure the database URI",
				"content": "# In config.py:\nSQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'\nSECRET_KEY = 'your-secret-key-minimum-20-chars'",
			},
			{
				"title": "Create the admin user and run",
				"content": "flask fab create-admin\nflask run\n\n# Open http://localhost:5000 in your browser",
			},
		],
	},
	{
		"slug": "first-crud-view",
		"title": "Your First CRUD View",
		"description": "Define a SQLAlchemy model and expose it as a full CRUD UI.",
		"steps": [
			{
				"title": "Define the model",
				"content": "# app/models.py\nfrom pgappforge import Model\nfrom sqlalchemy import Column, Integer, String\n\nclass Contact(Model):\n    id    = Column(Integer, primary_key=True)\n    name  = Column(String(150), nullable=False)\n    email = Column(String(150))",
			},
			{
				"title": "Create the ModelView",
				"content": "# app/views.py\nfrom pgappforge import ModelView\nfrom pgappforge.models.sqla.interface import SQLAInterface\nfrom .models import Contact\n\nclass ContactView(ModelView):\n    datamodel    = SQLAInterface(Contact)\n    list_columns = ['name', 'email']",
			},
			{
				"title": "Register the view",
				"content": "# app/__init__.py  (inside create_app)\nfrom .views import ContactView\nappbuilder.add_view(ContactView, 'Contacts', icon='fa-users', category='People')",
			},
			{
				"title": "Create the table and verify",
				"content": "flask db init && flask db migrate -m 'add contact' && flask db upgrade\nflask run\n# Visit http://localhost:5000/contactview/list",
			},
		],
	},
	{
		"slug": "rest-api",
		"title": "Building a REST API",
		"description": "Expose your models as a JSON REST API with Swagger docs.",
		"steps": [
			{
				"title": "Define a ModelRestApi",
				"content": "# app/api.py\nfrom pgappforge.api import ModelRestApi\nfrom pgappforge.models.sqla.interface import SQLAInterface\nfrom .models import Contact\n\nclass ContactApi(ModelRestApi):\n    resource_name = 'contact'\n    datamodel      = SQLAInterface(Contact)",
			},
			{
				"title": "Register the API",
				"content": "# app/__init__.py\nfrom .api import ContactApi\nappbuilder.add_api(ContactApi)",
			},
			{
				"title": "Obtain a JWT token",
				"content": "curl -X POST http://localhost:5000/api/v1/security/login \\\n  -H 'Content-Type: application/json' \\\n  -d '{\"username\":\"admin\",\"password\":\"admin\",\"provider\":\"db\"}'",
			},
			{
				"title": "Query the API",
				"content": "TOKEN=<paste access_token here>\ncurl -H \"Authorization: Bearer $TOKEN\" \\\n     http://localhost:5000/api/v1/contact/\n\n# Swagger UI at: http://localhost:5000/swaggerview/v1",
			},
		],
	},
	{
		"slug": "security-setup",
		"title": "Security & Role Configuration",
		"description": "Configure authentication, create roles, and assign permissions.",
		"steps": [
			{
				"title": "Choose an auth backend",
				"content": "# config.py\nfrom pgappforge.const import AUTH_DB, AUTH_OAUTH\nAUTH_TYPE = AUTH_OAUTH\n\nOAUTH_PROVIDERS = [{\n    'name': 'github',\n    'token_key': 'access_token',\n    'icon': 'fa-github',\n    'remote_app': {\n        'client_id': 'YOUR_CLIENT_ID',\n        'client_secret': 'YOUR_SECRET',\n        'api_base_url': 'https://api.github.com/',\n        'access_token_url': 'https://github.com/login/oauth/access_token',\n        'authorize_url': 'https://github.com/login/oauth/authorize',\n    },\n}]",
			},
			{
				"title": "Create a custom role via CLI",
				"content": "flask fab create-db   # ensure tables exist\nflask fab list-views  # verify registered views\n\n# Then in Security → Roles → Create and assign permissions interactively",
			},
			{
				"title": "Restrict a view to a role",
				"content": "class ContactView(ModelView):\n    datamodel       = SQLAInterface(Contact)\n    base_permissions = ['can_list', 'can_show']   # read-only\n    # Users must have 'can_list ContactView' or 'can_show ContactView'",
			},
			{
				"title": "Sync permissions after renaming",
				"content": "# After renaming a view class, run:\nflask fab security-converge\n# This migrates old permission tuples to the new class name",
			},
		],
	},
]


# ---------------------------------------------------------------------------
# View classes
# ---------------------------------------------------------------------------

def _render(body: str, page_title: str, query: str = "", **ctx) -> str:
	"""Render a page using the shared base layout."""
	from jinja2 import Environment, Undefined

	env = Environment(autoescape=True)
	base_tpl = env.from_string(_BASE_LAYOUT)
	page_html = env.from_string(body).render(
		topics=TOPICS,
		modules=TRAINING_MODULES,
		query=query,
		**ctx,
	)
	return base_tpl.render(
		page_title=page_title,
		topics=TOPICS,
		body=page_html,
	)


class HelpView(BaseView):
	"""Searchable help topics browser."""

	route_base = "/help"
	default_view = "index"

	@expose("/")
	def index(self) -> str:
		body = _render(_HELP_INDEX, page_title="Help", query="")
		return render_template_string(body)

	@expose("/search")
	def search(self) -> str:
		query = (request.args.get("q") or "").strip().lower()
		results: list[tuple[str, dict]] = []
		if query:
			for slug, topic in TOPICS.items():
				haystack = (
					topic["title"].lower()
					+ " "
					+ topic["keywords"].lower()
					+ " "
					+ topic["content"].lower()
				)
				if query in haystack:
					results.append((slug, topic))
		body = _render(
			_HELP_SEARCH,
			page_title=f'Search: {query}',
			query=query,
			results=results,
		)
		return render_template_string(body)

	@expose("/topic/<string:slug>")
	def topic(self, slug: str) -> str:
		topic = TOPICS.get(slug)
		if topic is None:
			return render_template_string(
				_render(
					'<div class="alert alert-danger">Topic <strong>{{ slug | e }}</strong>'
					' not found. <a href="/help/">← Back</a></div>',
					page_title="Not Found",
					slug=slug,
				)
			), 404
		body = _render(_HELP_TOPIC, page_title=topic["title"], topic=topic)
		return render_template_string(body)


class TrainingView(BaseView):
	"""Interactive step-by-step tutorial browser."""

	route_base = "/training"
	default_view = "index"

	@expose("/")
	def index(self) -> str:
		body = _render(_TRAINING_INDEX, page_title="Training Modules")
		return render_template_string(body)

	@expose("/module/<string:slug>")
	def module(self, slug: str) -> str:
		module = next((m for m in TRAINING_MODULES if m["slug"] == slug), None)
		if module is None:
			return render_template_string(
				_render(
					'<div class="alert alert-danger">Module not found.'
					' <a href="/training/">← Back</a></div>',
					page_title="Not Found",
				)
			), 404
		body = _render(_TRAINING_MODULE, page_title=module["title"], module=module)
		return render_template_string(body)


class AdminGuideView(BaseView):
	"""System administrator reference guide."""

	route_base = "/admin-guide"
	default_view = "index"

	@expose("/")
	def index(self) -> str:
		body = _render(_ADMIN_GUIDE, page_title="Admin Guide")
		return render_template_string(body)
