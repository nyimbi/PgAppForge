# PgAppForge

**PostgreSQL-native application platform for Python/Flask.**  
Build complete, production-ready web applications from your database schema — with graph analytics, AI integration, security, and deployment tooling included.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.x-green.svg)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-14%2B-blue.svg)](https://www.postgresql.org/)
[![Apache AGE](https://img.shields.io/badge/apache%20age-1.5%2B-red.svg)](https://age.apache.org/)
[![License](https://img.shields.io/badge/license-BSD-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.90.0-brightgreen.svg)]()

---

## What it does

PgAppForge introspects a PostgreSQL database and generates a complete web application — models, views, REST API, authentication, deployment config, and tests — in seconds. The generated app uses Flask + SQLAlchemy and is fully customisable.

```bash
# Generate a complete app from any PostgreSQL database
flask forge gen all postgresql://user:pass@localhost/mydb \
  --name MyApp --output-dir ./myapp/

# Deploy it
flask forge deploy docker run
```

---

## Quick start

```bash
pip install pgappforge
# or with optional extras:
pip install "pgappforge[speech,analytics,realtime]"
```

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:pass@localhost/mydb'
app.config['SECRET_KEY'] = 'your-secret-key'

db = SQLA(app)
appbuilder = AppBuilder(app, db.session)
```

---

## Core features

### Database → Application codegen

```bash
flask forge gen all  postgresql://...  --name MyApp --output-dir ./app/
flask forge gen model postgresql://...  --output models.py
flask forge gen view  postgresql://...  --output-dir views/
```

- Introspects all tables, relationships, constraints
- Generates SQLAlchemy 2.x models with proper types
- Generates Flask-AppBuilder views (CRUD, API, master-detail, charts)
- Generates Docker/CI/CD configuration, Alembic migrations, tests
- Detects and maps all PostgreSQL-native column types to appropriate widgets

### Complete PostgreSQL type support

Every PostgreSQL column type maps to a CRUD widget:

| Type | Widget |
|------|--------|
| JSONB | `JSONEditorWidget` — live JSON editor |
| HSTORE | `HStoreEditorWidget` — key/value table |
| LTREE | `TreeHierarchyWidget` — breadcrumb path |
| INET / CIDR | `NetworkAddressWidget` |
| UUID | `UUIDFieldWidget` — with generate button |
| TSVECTOR | `FullTextSearchWidget` (read-only) |
| INT4RANGE/INT8RANGE/NUMRANGE | `NumericRangeWidget` — dual inputs |
| TSRANGE/TSTZRANGE | `TimestampRangeWidget` |
| DATERANGE | `DateRangeWidget` |
| GEOMETRY (PostGIS) | `PostGISWidget` — Leaflet.Draw, WKT/EWKT |
| GEOGRAPHY | `PostGISGeographyWidget` |
| VECTOR (pgvector) | `EmbeddingWidget` — dim count + norm |
| H3INDEX (Uber H3) | `H3IndexWidget` — hex cell map |

### Apache AGE graph database

```python
from pgappforge.database.age import AGEManager

mgr = AGEManager(engine)
mgr.setup()                           # load AGE extension

graph = mgr.create_graph('social')   # CREATE GRAPH

# OpenCypher queries
rows = graph.cypher(
    'MATCH (a:Person)-[:KNOWS]->(b:Person) '
    'WHERE a.name = $name RETURN b',
    params={'name': 'Alice'}
)

# Create vertices and edges
graph.create_vertex('Person', {'name': 'Bob', 'age': 30})
graph.create_edge('Person', {'name': 'Alice'}, 'KNOWS',
                  'Person', {'name': 'Bob'})

# Schema introspection
schema = graph.schema()  # {label: [property_keys]}

# Management
graphs = mgr.list_graphs()
stats  = mgr.graph_stats('social')  # {'vertices': N, 'edges': M}
mgr.drop_graph('old_graph')
```

### 80+ UI widgets

Beyond the PostgreSQL type widgets, the widget library includes:

- `RangeSliderWidget`, `TagInputWidget`, `CurrencyInputWidget`
- `JSONEditorWidget`, `MarkdownEditorWidget`, `CodeEditorWidget`
- `SignaturePadWidget`, `ImageCropWidget`, `FileUploadFieldWidget`
- `KanbanBoardWidget`, `GanttChartWidget`, `TreeViewWidget`
- `ColorPickerWidget`, `RatingWidget`, `StarRatingWidget`
- `AddressSearchWidget` — Nominatim geocoding + Leaflet map
- `RouteWidget` — multi-waypoint route editor
- `H3IndexWidget`, `H3ArrayWidget` — Uber H3 hex cell maps
- `EmbeddingWidget`, `VectorDisplayWidget` — pgvector visualisation

### Project management widgets

| Widget | What it renders | JS library |
|--------|-----------------|-----------|
| `GanttWidget` | Gantt chart with dependencies, drag-reschedule, progress bars | Frappe Gantt (MIT) |
| `KanbanWidget` | Drag-to-column Kanban with WIP limits, swimlanes | Vanilla JS |
| `ResourceCalendarWidget` | Who-is-doing-what resource timeline | FullCalendar.js |
| `SprintBurndownWidget` | Sprint burndown/burnup with ideal line | Chart.js |
| `MilestoneTimelineWidget` | Horizontal milestone timeline, overdue detection | D3.js |
| `WBSWidget` | Collapsible work breakdown tree, progress + effort | Vanilla JS |

### Markdown editor and display

```python
from pgappforge.widgets.markdown_widget import MarkdownEditorWidget, MarkdownDisplayWidget

class ArticleView(ModelView):
    edit_form_extra_fields = {
        'body': TextAreaField(widget=MarkdownEditorWidget())
    }
    show_form_extra_fields = {
        'body': StringField(widget=MarkdownDisplayWidget())
    }
```

### AI integration (14 providers)

```python
from pgappforge.collaborative.ai.ai_models import ModelManager, ModelConfig, ModelProvider

config = ModelConfig(
    provider=ModelProvider.ANTHROPIC,
    api_key='...',
    model='claude-opus-4-8',
)
manager = ModelManager(config)
response = await manager.generate_response(messages)
```

Supported providers: OpenAI, Anthropic, Google Gemini, Azure OpenAI,
Ollama (local), OpenRouter, Mistral, Groq, Grok, Deepseek, Kimi, Qwen,
HuggingFace, local Whisper + TTS.

### Speech: faster-whisper STT + Supertonic TTS

```python
from pgappforge.collaborative.ai.speech_backends import (
    FasterWhisperSTT, SupertonicTTS, SpeechProcessor, create_speech_blueprint
)

processor = SpeechProcessor(
    stt=FasterWhisperSTT(model_size='small', device='auto'),
    tts=SupertonicTTS(language='en'),
)
processor.init_app(app)
app.register_blueprint(create_speech_blueprint(processor), url_prefix='/voice')
# POST /voice/stt  — audio → text
# POST /voice/tts  — text  → audio
```

### Voice input/output plugin

```python
from pgappforge.plugins.voice import FABVoicePlugin

plugin = FABVoicePlugin()
plugin.init_app(app, appbuilder)
# Activates with: app.config['FAB_VOICE_ENABLED'] = True

# Per-view:
@FABVoicePlugin.enable_view
class MyView(ModelView): ...
```

### 33 model mixins

```python
from pgappforge.mixins import (
    CacheMixin, FullTextSearchMixin, GeoLocationMixin,
    StateMachineMixin, WorkflowMixin, MetadataMixin,
    ApprovalWorkflowMixin, MultiTenancyMixin, ...
)

class Employee(Model, FullTextSearchMixin, GeoLocationMixin):
    __tablename__ = 'employees'
    # full-text search on all text columns + PostGIS location column
```

### Plugin system

```python
# Enable plugins via config
app.config['PGAPPFORGE_PLUGINS'] = ['analytics', 'workflow', 'tenancy', 'realtime']

# Or install + auto-discover
# pip install "pgappforge[analytics]"
# app.config['PGAPPFORGE_AUTOLOAD_PLUGINS'] = True
```

Available plugins:

| Plugin | What | Install |
|--------|------|---------|
| `analytics` | Self-service BI dashboards, predictive analytics, KPI tracking | `pgappforge[analytics]` |
| `workflow` | Visual process designer, approval chains, state machines | `pgappforge[workflow]` |
| `tenancy` | Multi-tenant SaaS: data isolation, Stripe billing, white-label | `pgappforge[tenancy]` |
| `realtime` | WebSocket collaboration, live cursors, conflict resolution | `pgappforge[realtime]` |
| `offline` | PWA offline mode, IndexedDB sync, conflict resolution | `pgappforge[offline]` |
| `classify` | 8-level data classification (Unclassified → SAP) | `pgappforge[classify]` |

### HTTP access logging + analytics

```python
from pgappforge.access_log import AccessLogMiddleware, AccessLogAnalytics

middleware = AccessLogMiddleware()
middleware.init_app(app, db.session)
# Logs every request to fab_access_log PostgreSQL table

analytics = AccessLogAnalytics(db.session)
top = analytics.top_endpoints(hours=24)     # with p95 latency
users = analytics.top_users(limit=20)
errors = analytics.error_summary(hours=1)
```

### App-wide unified search

```python
from pgappforge.search import GlobalSearchManager

search = GlobalSearchManager()
search.init_app(app, db.session)
search.register(Employee, fields=['first_name', 'last_name', 'email'],
                label='Employees')
search.register(Department, fields=['name', 'code'], label='Departments')

# Uses PostgreSQL plainto_tsquery — all models in one UNION query
results = search.search('engineering', limit=30)
```

### Deploy CLI

```bash
# Docker
flask forge deploy init
flask forge deploy docker build
flask forge deploy docker run
flask forge deploy docker logs --follow
flask forge deploy docker restart

# Remote server (rsync + SSH)
flask forge deploy server push
flask forge deploy server start
flask forge deploy server logs -f -n 200
flask forge deploy server migrate
```

### Screenshot testing (Playwright)

```bash
flask forge screenshot all --output-dir screenshots/
flask forge screenshot view EmployeeView
flask forge screenshot diff screenshots/before/ screenshots/after/
```

### Mobile app generation (React Native / Expo)

```bash
flask forge gen mobile postgresql://... --name MyMobileApp --output-dir ./mobile/
```

Generates a complete Expo/React Native app with:
- List, detail, and form screens per model
- JWT authentication
- TypeScript API client for your pgappforge REST API

### Help and training

```bash
flask forge help topics
flask forge help search "deployment"
flask forge help topic authentication
flask forge training list
flask forge training start getting-started
```

---

## Security

### Role-based access control

The existing FAB RBAC system enhanced with:

- **Visual RBAC matrix** — drag-and-drop permission grid at `/security/rbac/matrix`
- **Impact assessment** — "what changes if I delete this role?" at `/security/rbac/impact/<id>`
- **Role hierarchy graph** — D3.js visualisation at `/security/rbac/hierarchy`
- **Export** — Keycloak realm JSON, SpiceDB schema, CSV

```python
from pgappforge.security.integrations import KeycloakIntegration, SpiceDBIntegration

# Export to Keycloak
kc = KeycloakIntegration()
realm_json = kc.export_realm(appbuilder)

# Export to SpiceDB
sd = SpiceDBIntegration()
schema = sd.export_schema(appbuilder)
```

### 8-level data classification

```python
from pgappforge.plugins.classify import ClassificationPlugin, ClassificationMixin

class Document(Model, ClassificationMixin):
    # Adds classification_level column (0=Unclassified … 7=SAP)
    # Automatically enforces read access via PostgreSQL RLS
    __tablename__ = 'documents'
```

Levels: `UNCLASSIFIED` → `CUI` → `PUBLIC_TRUST` → `CONFIDENTIAL` →
`SECRET` → `TOP_SECRET` → `SCI` → `SAP`

### MFA support

TOTP, SMS, Email, WebAuthn/Passkeys, backup codes — see `pgappforge/security/mfa/`.

---

## Configuration

### Required

```python
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:pass@host/db'
app.config['SECRET_KEY'] = 'at-least-20-characters'
```

### Key options

```python
# Plugins
app.config['PGAPPFORGE_PLUGINS'] = ['analytics', 'workflow']

# Speech
app.config['FAB_SPEECH_STT_BACKEND'] = 'faster-whisper'
app.config['FAB_SPEECH_TTS_BACKEND'] = 'supertonic'
app.config['FAB_SPEECH_WHISPER_MODEL'] = 'base'   # tiny|base|small|medium|large-v3

# Voice UI
app.config['FAB_VOICE_ENABLED'] = True

# Access logging
app.config['FAB_ACCESS_LOG_ENABLED'] = True
app.config['FAB_ACCESS_LOG_EXCLUDE_PATHS'] = ['/static/']

# Offline mode (PWA)
app.config['PGAPPFORGE_OFFLINE_ENABLED'] = True
app.config['PGAPPFORGE_OFFLINE_CONFLICT_STRATEGY'] = 'server_wins'

# Classification
app.config['PGAPPFORGE_MULTI_TENANT'] = False
```

---

## Installation

```bash
# Core
pip install pgappforge

# PostgreSQL extras
pip install "pgappforge[speech]"     # faster-whisper + Supertonic TTS
pip install "pgappforge[analytics]"  # Plotly + Pandas + DuckDB
pip install "pgappforge[workflow]"   # Celery + Redis
pip install "pgappforge[tenancy]"    # Stripe + boto3
pip install "pgappforge[realtime]"   # Flask-SocketIO + Redis
pip install "pgappforge[offline]"    # PWA + IndexedDB sync

# Everything
pip install "pgappforge[all]"
```

### Apache AGE (graph database)

```bash
# Install AGE PostgreSQL extension (requires PostgreSQL 13+)
# Debian/Ubuntu:
sudo apt install postgresql-15-age
# macOS (Homebrew):
brew install apache-age

# Python: no extra deps — AGE uses psycopg2 (already installed)
```

---

## CLI reference

```
flask forge --help

Commands:
  gen         Generate apps/models/views from database schema
    gen all   Complete app generation
    gen model SQLAlchemy models only
    gen view  Views + API only
    gen mobile React Native (Expo) mobile app

  deploy      Manage application deployment
    deploy init          Generate .fab-deploy.yml config
    deploy docker [...]  Docker lifecycle commands
    deploy server [...]  SSH server lifecycle commands

  screenshot  Capture UI screenshots (requires Playwright)
  help        Browse help topics
  training    Interactive training modules
  create-app  Create a new app from skeleton template
  create-admin Create admin user
  reset-password Reset a user's password
```

---

## Repository structure

```
pgappforge/
├── __init__.py              # AppBuilder, ModelView, SQLA, Model
├── base.py                  # AppBuilder class
├── baseviews.py             # BaseView, ModelView
├── api/                     # REST API (ModelRestApi, OpenAPI)
├── security/                # RBAC, MFA, SecurityManager
│   ├── mfa/                 # TOTP, WebAuthn, SMS, Email
│   ├── integrations/        # Keycloak, SpiceDB export
│   └── visual_rbac.py       # Drag-drop RBAC UI
├── cli/                     # forge CLI commands
│   ├── generators/          # codegen pipeline
│   │   ├── database_inspector.py
│   │   ├── model_generator.py
│   │   ├── view_generator.py
│   │   ├── app_generator.py
│   │   ├── mobile_generator.py
│   │   └── code_headers.py  # 17k line import template library
│   ├── deploy/              # deploy CLI
│   ├── help_commands.py     # help + training CLI
│   └── screenshot_commands.py
├── database/
│   └── age/                 # Apache AGE graph support
│       ├── manager.py       # AGEManager
│       ├── graph.py         # AGEGraph (OpenCypher execution)
│       └── types.py         # Vertex, Edge, Path
├── widgets/                 # UI widget library (80+ widgets)
│   ├── nx_widgets.py        # 82 widget classes
│   └── markdown_widget.py   # MarkdownEditorWidget + display
├── widgets_postgresql/      # PostgreSQL-specific widgets
│   ├── _cdn.py              # Canonical CDN URLs
│   ├── pg_type_widgets.py   # HSTORE, LTREE, ranges, UUID, vector
│   ├── postgis_h3_widgets.py# PostGIS + Uber H3 + SQLAlchemy types
│   └── pgvector_widgets.py  # pgvector EmbeddingWidget + VectorType
├── mixins/                  # 33 SQLAlchemy model mixins
├── plugins/                 # Plugin system
│   ├── hooks.py             # HookRegistry (12 event signals)
│   ├── base_plugin.py       # BasePlugin protocol
│   ├── plugin_manager.py    # Config loading + entry_point discovery
│   ├── analytics/           # BI plugin skeleton
│   ├── workflow/            # BPM plugin skeleton
│   ├── tenancy/             # Multi-tenant SaaS plugin skeleton
│   ├── realtime/            # Collaboration plugin skeleton
│   ├── offline/             # PWA offline plugin
│   ├── classify/            # 8-level classification plugin
│   └── voice/               # Voice input/output plugin
├── collaborative/           # AI + real-time collaboration
│   └── ai/
│       ├── ai_models.py     # 14 LLM provider adapters
│       └── speech_backends.py # faster-whisper + Supertonic TTS
├── access_log/              # HTTP request logging
├── search/                  # Global FTS search
├── theming/                 # Theme manager
├── config/                  # Runtime app configuration
└── help/                    # In-app help + training views
```

---

## Comparison with Flask-AppBuilder

PgAppForge started as a fork of [Flask-AppBuilder](https://github.com/dpgaspar/Flask-AppBuilder) by Daniel Vaz Gaspar and has expanded significantly in scope:

| | Flask-AppBuilder | PgAppForge |
|---|---|---|
| Database | SQLite / MySQL / PostgreSQL / MSSQL / Oracle | **PostgreSQL only** |
| Code generation | Manual | **DB → complete app in seconds** |
| Graph database | ❌ | **Apache AGE + OpenCypher** |
| Widget library | ~15 widgets | **80+ including PostGIS, H3, pgvector** |
| AI integration | ❌ | **14 LLM providers + RAG + STT/TTS** |
| Plugin system | Addon managers | **Formal plugin protocol + hooks** |
| Deploy tooling | ❌ | **Docker + SSH deploy CLI** |
| Classification | ❌ | **8-level (Unclassified → SAP)** |
| Mobile generation | ❌ | **React Native (Expo)** |
| Voice interface | ❌ | **Web Speech API + faster-whisper** |
| Python | 3.8+ | **3.12+ (3.14.5 tested)** |
| Flask | 2.x | **3.x** |

---

## Roadmap

The following from the original README represent real intent (not marketing copy):

- [ ] **ERD visual designer** — drag-and-drop schema editor with auto-generation from live database
- [ ] **Knowledge graph construction** — extract entities + relationships from text using spaCy/NER
- [ ] **Graph import/export** — GraphML, GEXF, Pajek, GML formats
- [ ] **Community detection** — Louvain, Label Propagation on AGE graphs
- [ ] **Visual RBAC** — complete implementation (matrix + impact assessment + D3 hierarchy)
- [ ] **Offline sync** — complete PWA implementation with IndexedDB
- [ ] **Full responsive/theming** — Bootstrap 5 migration, CSS variables, theme switcher
- [ ] **App configuration page** — database-backed runtime settings UI

---

## Contributing

Issues and PRs welcome at [github.com/nyimbi/PgAppForge](https://github.com/nyimbi/PgAppForge).

```bash
git clone https://github.com/nyimbi/PgAppForge.git
cd PgAppForge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ci/test_codegen_pipeline.py -v
```

---

## Acknowledgements

**PgAppForge would not exist without [Flask-AppBuilder](https://github.com/dpgaspar/Flask-AppBuilder)** by [Daniel Vaz Gaspar](https://github.com/dpgaspar).

Flask-AppBuilder is the foundation on which this project was built. Its core abstractions — `AppBuilder`, `ModelView`, `BaseSecurityManager`, the RBAC permission system, the REST API layer, and the Jinja2/Bootstrap rendering pipeline — are the skeleton of pgappforge. Daniel's decade of work making Flask applications simple to build is the direct inspiration for everything here.

If Flask-AppBuilder meets your needs, use it:
- PyPI: `pip install flask-appbuilder`
- Docs: [flask-appbuilder.readthedocs.org](https://flask-appbuilder.readthedocs.org)
- Repo: [github.com/dpgaspar/Flask-AppBuilder](https://github.com/dpgaspar/Flask-AppBuilder)

PgAppForge diverges from Flask-AppBuilder in scope (PostgreSQL-only, graph database, codegen pipeline, AI/voice, plugin system) but builds on its excellent foundation rather than replacing it.

---

## License

BSD License — same as Flask-AppBuilder. See [LICENSE](LICENSE).
