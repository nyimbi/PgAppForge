# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PgAppForge (FAB) is a rapid application development framework built on top of Flask that provides automatic CRUD generation, detailed security, RESTful APIs, and extensive customization options. This is the main PgAppForge repository with version 4.8.0.

## Development Commands

### Testing
- **Run all tests**: `nose2 -c setup.cfg -F -v --with-coverage --coverage pgappforge -A '!mongo' tests`
- **Run MongoDB tests**: `nose2 -c setup.cfg -F -v --with-coverage --coverage pgappforge -A 'mongo' tests`
- **Run single test**: `nose2 tests.test_<module_name>`
- **Tox environments**: `tox -e api-sqlite`, `tox -e mysql`, `tox -e postgres`, `tox -e mongodb`

### Code Quality
- **Linting**: `flake8` (configured in setup.cfg with Google import order style, 90 char line limit)
- **Code formatting**: `black --check setup.py pgappforge tests` or `black setup.py pgappforge tests`
- **Type checking**: `mypy` (configured for specific modules in setup.cfg)

### SQLAlchemy 2.x Development
- **Dependencies**: Uses SQLAlchemy 2.0.42+ and Flask-SQLAlchemy 3.1.1+
- **Query patterns**: Framework uses modern `session.execute(select())` patterns internally
- **Compatibility**: Automatic detection of Flask-SQLAlchemy 2.x vs 3.x with compatibility layers

### Framework CLI
- **Modern CLI**: `flask fab <command>` (preferred over deprecated fabmanager)
- **Legacy CLI**: `fabmanager <command>` (being deprecated in 2.2.X)

### Documentation
- **Build docs**: `cd docs && make html`
- **Live docs**: Available at http://flask-appbuilder.readthedocs.org/

## Architecture

### Core Components

1. **AppBuilder (`pgappforge/base.py`)**: Central orchestrator that manages views, security, menus, and the Flask app lifecycle. Handles registration of views, permissions, and addon managers.

2. **Security System (`pgappforge/security/`)**: 
   - Supports multiple auth methods: OAuth, OpenID, Database, LDAP, REMOTE_USER
   - Role-based permissions with automatic permission generation
   - Separate implementations for SQLAlchemy (`sqla/`) and MongoEngine (`mongoengine/`)

3. **Views System (`pgappforge/views.py`, `pgappforge/baseviews.py`)**:
   - `ModelView`: Automatic CRUD for database models
   - `BaseView`: Foundation for custom views  
   - `CompactCRUDMixin`, `MasterDetailView`: Specialized view mixins
   - `RestCRUDView`: RESTful API endpoints

4. **API System (`pgappforge/api/`)**:
   - `ModelRestApi`: Automatic REST API generation
   - OpenAPI/Swagger integration
   - Schema validation and serialization

### Database Support
- **Primary**: SQLAlchemy 2.x with support for SQLite, MySQL, PostgreSQL, MSSQL, Oracle, DB2
- **Alternative**: MongoEngine for MongoDB (partial support)
- **Multi-DB**: Supports multiple database connections (vertical partitioning)
- **Modern Features**: Improved performance, better type checking, and enhanced debugging with SQLAlchemy 2.x

### Key Patterns
- **Factory Pattern**: Supports Flask app factory pattern via `init_app()`
- **Addon System**: Dynamic loading of addon managers from `ADDON_MANAGERS` config
- **Blueprint Registration**: All views are registered as Flask blueprints
- **Permission Auto-generation**: Automatic creation of permissions based on view methods

## Configuration

### Required Environment Variables
- `SQLALCHEMY_DATABASE_URI`: Database connection string
- `SECRET_KEY`: Flask secret key (minimum 20 characters)

### Key Config Options
- `APP_NAME`: Application name (default: "F.A.B.")
- `APP_THEME`: Bootstrap theme name
- `FAB_SECURITY_MANAGER_CLASS`: Custom security manager
- `FAB_UPDATE_PERMS`: Auto-update permissions (default: True)
- `ADDON_MANAGERS`: List of addon manager classes to load

## Testing Strategy

Tests use `nose2` with coverage reporting. Test structure:
- `tests/`: Main test directory
- `tests/fixtures/`: Test data and fixtures  
- `tests/sqla/`: SQLAlchemy-specific tests
- `tests/mongoengine/`: MongoDB-specific tests
- `tests/security/`: Authentication and authorization tests

Test databases configured via environment variables in tox.ini.

## Development Notes

- Framework follows semantic versioning
- Code style enforced by black and flake8
- Type hints used selectively with mypy checking on core modules
- Extensive example applications in `examples/` directory
- Internationalization support via Flask-Babel with translations in `pgappforge/translations/`
- Static assets (CSS, JS, images) in `pgappforge/static/appbuilder/`
- Jinja2 templates in `pgappforge/templates/appbuilder/`

## Dependencies

Core dependencies managed in `requirements/` with separate files for base, dev, testing, extras, and database-specific requirements. Uses pip-tools for dependency management.
- All testing, tests, and validation code must be written in a tests dieretory. All documentation must be written in a docs directory. Todo files should be written in a works directory. Avoid cluttering up the workspace with miscellaneous files.  Fully document all actions, decisions and findings.