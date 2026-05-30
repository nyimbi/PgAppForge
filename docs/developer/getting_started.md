# Developer Getting Started Guide

Complete guide for developers to get up and running with Flask-AppBuilder development, from basic setup to advanced customization.

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** (3.11+ recommended for best performance)
- **Virtual Environment** (venv, conda, or virtualenv)
- **Database** (SQLite for development, PostgreSQL/MySQL for production)
- **Node.js** (for frontend asset compilation)
- **Git** (for version control)

### Development Environment Setup

#### 1. Create Virtual Environment

```bash
# Using venv (recommended)
python -m venv fab-dev
source fab-dev/bin/activate  # On Windows: fab-dev\Scripts\activate

# Using conda
conda create -n fab-dev python=3.11
conda activate fab-dev
```

#### 2. Install Flask-AppBuilder

```bash
# Development installation with all features
pip install flask-appbuilder[mfa,export,analytics]

# Or from source for contributing
git clone https://github.com/dpgaspar/Flask-AppBuilder.git
cd Flask-AppBuilder
pip install -e .[mfa,export,analytics]
```

#### 3. Create Your First App

```bash
# Create new app
fab create-app MyDevApp
cd MyDevApp

# Initialize database
export FLASK_APP=app.py
export FLASK_ENV=development
flask fab create-admin
flask run
```

Visit `http://localhost:5000` to see your app!

## 🏗️ Project Structure

### Recommended Directory Layout

```
my-app/
├── app/                          # Main application package
│   ├── __init__.py              # App factory and configuration
│   ├── models.py                # Database models
│   ├── views.py                 # Views and controllers
│   ├── forms.py                 # WTForms definitions
│   ├── utils.py                 # Utility functions
│   └── templates/               # Custom templates
│       └── my_template.html
├── migrations/                   # Database migrations
├── tests/                       # Test suite
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_views.py
│   └── conftest.py
├── config.py                    # Configuration settings
├── app.py                       # Application entry point
├── requirements.txt             # Dependencies
├── requirements-dev.txt         # Development dependencies
├── .env                         # Environment variables (not in VCS)
├── .gitignore                   # Git ignore patterns
├── README.md                    # Project documentation
├── pytest.ini                  # Pytest configuration
└── setup.cfg                    # Tool configurations
```

### Core Files Explained

#### `app.py` - Application Entry Point

```python
"""Main application entry point."""
import os
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA

# Create Flask app
app = Flask(__name__)
app.config.from_object('config')

# Initialize database
db = SQLA(app)

# Initialize AppBuilder
appbuilder = AppBuilder(app, db.session)

# Import views (must be after appbuilder creation)
from app import views, models

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=app.config.get('DEBUG', False)
    )
```

#### `config.py` - Configuration Management

```python
"""Application configuration."""
import os
from flask_appbuilder.security.manager import AUTH_DB

# Base directory
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    """Base configuration."""

    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL') or
        f'sqlite:///{os.path.join(basedir, "app.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Flask-AppBuilder settings
    APP_NAME = "My Development App"
    APP_THEME = ""  # Default theme
    APP_ICON = "/static/img/logo.jpg"

    # Authentication
    AUTH_TYPE = AUTH_DB
    AUTH_ROLE_ADMIN = 'Admin'
    AUTH_ROLE_PUBLIC = 'Public'
    AUTH_USER_REGISTRATION = True
    AUTH_USER_REGISTRATION_ROLE = "Public"

    # Security
    CSRF_ENABLED = True
    WTF_CSRF_ENABLED = True

    # Upload settings
    UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads/')
    IMG_UPLOAD_FOLDER = os.path.join(basedir, 'app/static/uploads/')
    IMG_UPLOAD_URL = '/static/uploads/'
    IMG_SIZE = (300, 200, True)

    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False

    # Development database
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DEV_DATABASE_URL') or
        f'sqlite:///{os.path.join(basedir, "dev.db")}'
    )

    # Development features
    SQLALCHEMY_ECHO = False  # Set to True to see SQL queries

class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = True

    # Test database (in-memory)
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False

    # Production database (must be set via environment)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://user:password@localhost/myapp'

    # Production security settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
```

#### `app/__init__.py` - App Factory Pattern

```python
"""App factory for Flask-AppBuilder application."""
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA
from flask_migrate import Migrate

# Global variables
db = SQLA()
appbuilder = None
migrate = None

def create_app(config_name='default'):
    """Application factory."""
    from config import config

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)

    global appbuilder, migrate
    appbuilder = AppBuilder(app, db.session)
    migrate = Migrate(app, db)

    # Register blueprints and views
    register_views(appbuilder)

    # Error handlers
    register_error_handlers(app)

    # Shell context
    @app.shell_context_processor
    def make_shell_context():
        return {'db': db, 'app': app, 'appbuilder': appbuilder}

    return app

def register_views(appbuilder):
    """Register all views with AppBuilder."""
    from app.views import (
        MyModelView, MyBaseView, ApiView
    )

    # Register views
    appbuilder.add_view(
        MyModelView,
        "My Models",
        icon="fa-table",
        category="Models"
    )

    appbuilder.add_view(
        MyBaseView,
        "Custom View",
        icon="fa-cog",
        category="Tools"
    )

    # Register API views
    appbuilder.add_api(ApiView)

def register_error_handlers(app):
    """Register error handlers."""

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500
```

## 📊 Database Models

### Model Development Pattern

```python
"""Database models using SQLAlchemy."""
from flask_appbuilder import Model
from flask_appbuilder.models.mixins import (
    AuditMixin, BaseMixin, FileColumn, ImageColumn
)
from sqlalchemy import Column, Integer, String, Text, Date, Float, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

class Department(Model, AuditMixin):
    """Department model with audit trail."""
    __tablename__ = 'departments'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    budget = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)

    # Relationships
    employees = relationship('Employee', backref='department', lazy='dynamic')
    manager_id = Column(Integer, ForeignKey('employees.id'))
    manager = relationship('Employee', foreign_keys=[manager_id])

    def __repr__(self):
        return f'<Department {self.name}>'

    @property
    def employee_count(self):
        """Get number of employees in department."""
        return self.employees.filter_by(is_active=True).count()

class Employee(Model, AuditMixin):
    """Employee model with advanced features."""
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)

    # Personal Information
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    phone = Column(String(20))

    # Employment Information
    employee_id = Column(String(20), unique=True, nullable=False)
    hire_date = Column(Date, nullable=False)
    job_title = Column(String(100), nullable=False)
    salary = Column(Float)
    is_active = Column(Boolean, default=True)

    # Relationships
    department_id = Column(Integer, ForeignKey('departments.id'), nullable=False)
    manager_id = Column(Integer, ForeignKey('employees.id'))
    manager = relationship('Employee', remote_side=[id], backref='direct_reports')

    # File uploads
    photo = Column(ImageColumn(size=(300, 300, True), thumbnail_size=(50, 50, True)))
    resume = Column(FileColumn)

    def __repr__(self):
        return f'<Employee {self.full_name}>'

    @property
    def full_name(self):
        """Get full name."""
        return f'{self.first_name} {self.last_name}'

    @property
    def years_of_service(self):
        """Calculate years of service."""
        if self.hire_date:
            today = datetime.now().date()
            return (today - self.hire_date).days / 365.25
        return 0

    def get_subordinates(self):
        """Get all employees who report to this employee."""
        return Employee.query.filter_by(manager_id=self.id, is_active=True).all()

class Project(Model, AuditMixin):
    """Project model with many-to-many relationships."""
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    budget = Column(Float)
    status = Column(String(20), default='Planning')

    # Relationships
    department_id = Column(Integer, ForeignKey('departments.id'))
    project_manager_id = Column(Integer, ForeignKey('employees.id'))
    project_manager = relationship('Employee')

    # Many-to-many relationship with employees
    team_members = relationship(
        'Employee',
        secondary='project_assignments',
        backref='assigned_projects'
    )

    def __repr__(self):
        return f'<Project {self.name}>'

    @property
    def is_overdue(self):
        """Check if project is overdue."""
        if self.end_date and self.status not in ['Completed', 'Cancelled']:
            return datetime.now().date() > self.end_date
        return False

# Association table for many-to-many relationship
from sqlalchemy import Table
project_assignments = Table(
    'project_assignments',
    Model.metadata,
    Column('project_id', Integer, ForeignKey('projects.id'), primary_key=True),
    Column('employee_id', Integer, ForeignKey('employees.id'), primary_key=True),
    Column('role', String(50)),  # Role in the project
    Column('assigned_date', Date, default=datetime.now().date()),
    extend_existing=True
)
```

### Model Best Practices

```python
# Custom model mixins for common functionality
class TimestampMixin:
    """Add timestamp fields to models."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SoftDeleteMixin:
    """Add soft delete functionality."""
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime)
    deleted_by_id = Column(Integer, ForeignKey('ab_user.id'))

    @classmethod
    def active_only(cls):
        """Query filter for non-deleted records."""
        return cls.query.filter(cls.is_deleted == False)

class VersionedMixin:
    """Add version tracking to models."""
    version = Column(Integer, default=1, nullable=False)

    def increment_version(self):
        """Increment version number."""
        self.version += 1

# Advanced model with all mixins
class Document(Model, AuditMixin, TimestampMixin, SoftDeleteMixin, VersionedMixin):
    __tablename__ = 'documents'

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text)
    document_type = Column(String(50))
    file_path = Column(FileColumn)

    # Security and access control
    is_confidential = Column(Boolean, default=False)
    access_level = Column(String(20), default='public')  # public, internal, confidential

    # Relationships
    owner_id = Column(Integer, ForeignKey('ab_user.id'), nullable=False)
    owner = relationship('User')

    def can_access(self, user):
        """Check if user can access this document."""
        if self.owner_id == user.id:
            return True

        if user.has_role('Admin'):
            return True

        if self.access_level == 'public':
            return True

        if self.access_level == 'internal' and user.is_authenticated:
            return True

        if self.is_confidential and not user.has_permission('can_view_confidential'):
            return False

        return False
```

## 🎨 Views and Controllers

### ModelView Development

```python
"""Custom ModelViews for the application."""
from flask import flash, redirect, url_for, request, g
from flask_appbuilder import ModelView, BaseView, expose, has_access
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.widgets import ListWidget, ShowWidget
from flask_appbuilder.charts.views import GroupByChartView
from flask_appbuilder.actions import action
from wtforms import StringField, SelectField, validators
from wtforms.widgets import TextArea

from app import appbuilder, db
from app.models import Employee, Department, Project

class EmployeeModelView(ModelView):
    """Employee management view with advanced features."""

    datamodel = SQLAInterface(Employee)

    # List view configuration
    list_columns = ['photo_img', 'full_name', 'email', 'department', 'job_title', 'hire_date', 'is_active']
    list_title = "Employee Directory"

    # Search configuration
    search_columns = ['first_name', 'last_name', 'email', 'employee_id', 'job_title']
    search_exclude_columns = ['photo', 'resume']

    # Form configuration
    add_columns = [
        'first_name', 'last_name', 'email', 'phone', 'employee_id',
        'hire_date', 'job_title', 'salary', 'department', 'manager',
        'photo', 'resume'
    ]
    edit_columns = add_columns + ['is_active']
    show_columns = add_columns + ['years_of_service', 'created_by', 'created_on', 'changed_by', 'changed_on']

    # Field descriptions and validation
    description_columns = {
        'salary': 'Annual salary in USD',
        'photo': 'Upload employee photo (JPG, PNG)',
        'resume': 'Upload resume (PDF)',
        'employee_id': 'Unique employee identifier'
    }

    # Form field overrides
    add_form_extra_fields = {
        'bio': StringField(
            'Biography',
            widget=TextArea(),
            validators=[validators.Length(max=500)]
        )
    }

    # Ordering and pagination
    base_order = ('last_name', 'asc')
    page_size = 20

    # Permissions
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit']

    # Custom filters
    base_filters = [['is_active', FilterEqual, True]]

    def pre_add(self, item):
        """Custom logic before adding employee."""
        # Auto-generate employee ID if not provided
        if not item.employee_id:
            item.employee_id = self.generate_employee_id()

        # Validate salary range
        if item.salary and (item.salary < 30000 or item.salary > 500000):
            flash('Salary must be between $30,000 and $500,000', 'warning')
            return False

    def pre_update(self, item):
        """Custom logic before updating employee."""
        # Track salary changes
        if self.datamodel.is_changed(item, 'salary'):
            old_salary = self.datamodel.get_pk_value(item)
            # Log salary change for audit
            current_app.logger.info(f"Salary changed for employee {item.id}")

    def post_add(self, item):
        """Custom logic after adding employee."""
        flash(f'Employee {item.full_name} added successfully!', 'success')

        # Send welcome email (implement your email service)
        # self.send_welcome_email(item)

    def generate_employee_id(self):
        """Generate unique employee ID."""
        import random
        import string

        while True:
            emp_id = 'EMP' + ''.join(random.choices(string.digits, k=6))
            if not Employee.query.filter_by(employee_id=emp_id).first():
                return emp_id

    # Custom actions
    @action('deactivate', 'Deactivate', 'Deactivate selected employees?', 'fa-ban')
    def deactivate_employees(self, items):
        """Bulk deactivate employees."""
        count = 0
        for item in items:
            if item.is_active:
                item.is_active = False
                count += 1

        db.session.commit()
        flash(f'Deactivated {count} employees', 'success')
        return redirect(request.referrer)

    @action('export_csv', 'Export CSV', 'Export selected employees to CSV?', 'fa-download')
    def export_csv(self, items):
        """Export employees to CSV."""
        import csv
        from io import StringIO
        from flask import make_response

        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(['Name', 'Email', 'Department', 'Job Title', 'Hire Date'])

        # Write data
        for item in items:
            writer.writerow([
                item.full_name,
                item.email,
                item.department.name if item.department else '',
                item.job_title,
                item.hire_date
            ])

        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=employees.csv'

        return response

class DepartmentModelView(ModelView):
    """Department management view."""

    datamodel = SQLAInterface(Department)

    list_columns = ['name', 'manager', 'employee_count', 'budget', 'is_active']
    search_columns = ['name', 'description']
    add_columns = ['name', 'description', 'budget', 'manager']
    edit_columns = add_columns + ['is_active']

    # Custom formatters
    formatters_columns = {
        'budget': lambda x: f'${x:,.2f}' if x else '$0.00'
    }

    # Validators
    validators_columns = {
        'budget': [validators.NumberRange(min=0, message='Budget must be positive')]
    }

class ProjectModelView(ModelView):
    """Project management view with advanced widgets."""

    datamodel = SQLAInterface(Project)

    list_columns = ['name', 'project_manager', 'department', 'status', 'start_date', 'end_date', 'is_overdue']
    search_columns = ['name', 'description', 'status']

    # Custom list widget
    list_widget = ListWidget

    # Status choices
    add_form_extra_fields = {
        'status': SelectField(
            'Status',
            choices=[
                ('Planning', 'Planning'),
                ('In Progress', 'In Progress'),
                ('On Hold', 'On Hold'),
                ('Completed', 'Completed'),
                ('Cancelled', 'Cancelled')
            ]
        )
    }

    # Custom filters
    base_filters = [['status', FilterNotEqual, 'Cancelled']]

    # Color coding for status
    def list_formatter(self, item):
        """Custom list formatting."""
        if item.is_overdue:
            return f'<span class="label label-danger">{item.status}</span>'
        elif item.status == 'Completed':
            return f'<span class="label label-success">{item.status}</span>'
        else:
            return f'<span class="label label-info">{item.status}</span>'
```

### Custom BaseViews

```python
"""Custom BaseViews for special functionality."""
from flask import render_template, jsonify, request
from flask_appbuilder import BaseView, expose, has_access
from sqlalchemy import func

class DashboardView(BaseView):
    """Custom dashboard with metrics and charts."""

    default_view = 'dashboard'

    @expose('/')
    @has_access
    def dashboard(self):
        """Main dashboard page."""
        # Get dashboard metrics
        metrics = self.get_dashboard_metrics()

        return self.render_template(
            'dashboard.html',
            metrics=metrics,
            page_title='Dashboard'
        )

    @expose('/api/metrics')
    @has_access
    def api_metrics(self):
        """API endpoint for dashboard metrics."""
        metrics = self.get_dashboard_metrics()
        return jsonify(metrics)

    def get_dashboard_metrics(self):
        """Calculate dashboard metrics."""
        total_employees = db.session.query(Employee).filter_by(is_active=True).count()
        total_departments = db.session.query(Department).filter_by(is_active=True).count()
        total_projects = db.session.query(Project).count()
        active_projects = db.session.query(Project).filter(
            Project.status.in_(['Planning', 'In Progress'])
        ).count()

        # Department breakdown
        dept_breakdown = db.session.query(
            Department.name,
            func.count(Employee.id).label('count')
        ).join(Employee).filter(
            Employee.is_active == True
        ).group_by(Department.name).all()

        return {
            'total_employees': total_employees,
            'total_departments': total_departments,
            'total_projects': total_projects,
            'active_projects': active_projects,
            'department_breakdown': [
                {'name': dept.name, 'count': dept.count}
                for dept in dept_breakdown
            ]
        }

class ReportsView(BaseView):
    """Custom reports view."""

    @expose('/')
    @has_access
    def list(self):
        """List available reports."""
        reports = [
            {
                'name': 'Employee Report',
                'description': 'Detailed employee information',
                'url': url_for('ReportsView.employee_report')
            },
            {
                'name': 'Department Report',
                'description': 'Department statistics and metrics',
                'url': url_for('ReportsView.department_report')
            }
        ]

        return self.render_template('reports/list.html', reports=reports)

    @expose('/employee')
    @has_access
    def employee_report(self):
        """Employee report with filters."""
        # Get filter parameters
        department_id = request.args.get('department_id', type=int)
        active_only = request.args.get('active_only', default=True, type=bool)

        # Build query
        query = db.session.query(Employee)

        if department_id:
            query = query.filter(Employee.department_id == department_id)

        if active_only:
            query = query.filter(Employee.is_active == True)

        employees = query.order_by(Employee.last_name).all()
        departments = db.session.query(Department).filter_by(is_active=True).all()

        return self.render_template(
            'reports/employee_report.html',
            employees=employees,
            departments=departments,
            selected_department=department_id,
            active_only=active_only
        )

# Register views
appbuilder.add_view(
    EmployeeModelView,
    "Employees",
    icon="fa-users",
    category="HR"
)

appbuilder.add_view(
    DepartmentModelView,
    "Departments",
    icon="fa-building",
    category="HR"
)

appbuilder.add_view(
    ProjectModelView,
    "Projects",
    icon="fa-tasks",
    category="Projects"
)

appbuilder.add_view(
    DashboardView,
    "Dashboard",
    icon="fa-dashboard",
    category=""
)

appbuilder.add_view(
    ReportsView,
    "Reports",
    icon="fa-bar-chart",
    category="Reports"
)
```

## 🎨 Templates and UI Customization

### Custom Templates

```html
<!-- app/templates/dashboard.html -->
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <div class="row">
        <div class="col-lg-12">
            <h1 class="page-header">
                <i class="fa fa-dashboard"></i> Dashboard
            </h1>
        </div>
    </div>

    <!-- Metrics Cards -->
    <div class="row">
        <div class="col-lg-3 col-md-6">
            <div class="panel panel-primary">
                <div class="panel-heading">
                    <div class="row">
                        <div class="col-xs-3">
                            <i class="fa fa-users fa-5x"></i>
                        </div>
                        <div class="col-xs-9 text-right">
                            <div class="huge">{{ metrics.total_employees }}</div>
                            <div>Total Employees</div>
                        </div>
                    </div>
                </div>
                <a href="{{ url_for('EmployeeModelView.list') }}">
                    <div class="panel-footer">
                        <span class="pull-left">View Details</span>
                        <span class="pull-right"><i class="fa fa-arrow-circle-right"></i></span>
                        <div class="clearfix"></div>
                    </div>
                </a>
            </div>
        </div>

        <div class="col-lg-3 col-md-6">
            <div class="panel panel-green">
                <div class="panel-heading">
                    <div class="row">
                        <div class="col-xs-3">
                            <i class="fa fa-building fa-5x"></i>
                        </div>
                        <div class="col-xs-9 text-right">
                            <div class="huge">{{ metrics.total_departments }}</div>
                            <div>Departments</div>
                        </div>
                    </div>
                </div>
                <a href="{{ url_for('DepartmentModelView.list') }}">
                    <div class="panel-footer">
                        <span class="pull-left">View Details</span>
                        <span class="pull-right"><i class="fa fa-arrow-circle-right"></i></span>
                        <div class="clearfix"></div>
                    </div>
                </a>
            </div>
        </div>

        <div class="col-lg-3 col-md-6">
            <div class="panel panel-yellow">
                <div class="panel-heading">
                    <div class="row">
                        <div class="col-xs-3">
                            <i class="fa fa-tasks fa-5x"></i>
                        </div>
                        <div class="col-xs-9 text-right">
                            <div class="huge">{{ metrics.active_projects }}</div>
                            <div>Active Projects</div>
                        </div>
                    </div>
                </div>
                <a href="{{ url_for('ProjectModelView.list') }}">
                    <div class="panel-footer">
                        <span class="pull-left">View Details</span>
                        <span class="pull-right"><i class="fa fa-arrow-circle-right"></i></span>
                        <div class="clearfix"></div>
                    </div>
                </a>
            </div>
        </div>
    </div>

    <!-- Charts Section -->
    <div class="row">
        <div class="col-lg-6">
            <div class="panel panel-default">
                <div class="panel-heading">
                    <i class="fa fa-bar-chart-o"></i> Department Breakdown
                </div>
                <div class="panel-body">
                    <canvas id="departmentChart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>

        <div class="col-lg-6">
            <div class="panel panel-default">
                <div class="panel-heading">
                    <i class="fa fa-pie-chart"></i> Project Status
                </div>
                <div class="panel-body">
                    <canvas id="projectChart" width="400" height="200"></canvas>
                </div>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// Department breakdown chart
const deptCtx = document.getElementById('departmentChart').getContext('2d');
const departmentChart = new Chart(deptCtx, {
    type: 'bar',
    data: {
        labels: {{ metrics.department_breakdown | map(attribute='name') | list | tojson }},
        datasets: [{
            label: 'Employees',
            data: {{ metrics.department_breakdown | map(attribute='count') | list | tojson }},
            backgroundColor: [
                'rgba(54, 162, 235, 0.8)',
                'rgba(255, 99, 132, 0.8)',
                'rgba(255, 205, 86, 0.8)',
                'rgba(75, 192, 192, 0.8)',
                'rgba(153, 102, 255, 0.8)'
            ]
        }]
    },
    options: {
        responsive: true,
        scales: {
            y: {
                beginAtZero: true
            }
        }
    }
});
</script>
{% endblock %}
```

### Custom Widgets

```python
"""Custom widgets for enhanced UI."""
from flask_appbuilder.widgets import ListWidget
from flask import Markup

class EmployeeListWidget(ListWidget):
    """Custom list widget for employees with photo thumbnails."""

    template = 'widgets/employee_list.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.template = 'widgets/employee_list.html'

class DashboardCardWidget:
    """Custom widget for dashboard cards."""

    def __init__(self, title, value, icon, color='primary', url=None):
        self.title = title
        self.value = value
        self.icon = icon
        self.color = color
        self.url = url

    def render(self):
        """Render the dashboard card."""
        card_html = f'''
        <div class="col-lg-3 col-md-6">
            <div class="panel panel-{self.color}">
                <div class="panel-heading">
                    <div class="row">
                        <div class="col-xs-3">
                            <i class="fa {self.icon} fa-5x"></i>
                        </div>
                        <div class="col-xs-9 text-right">
                            <div class="huge">{self.value}</div>
                            <div>{self.title}</div>
                        </div>
                    </div>
                </div>
        '''

        if self.url:
            card_html += f'''
                <a href="{self.url}">
                    <div class="panel-footer">
                        <span class="pull-left">View Details</span>
                        <span class="pull-right"><i class="fa fa-arrow-circle-right"></i></span>
                        <div class="clearfix"></div>
                    </div>
                </a>
            '''

        card_html += '''
            </div>
        </div>
        '''

        return Markup(card_html)
```

## 🧪 Testing

### Test Configuration

```python
"""Test configuration and fixtures."""
# tests/conftest.py
import pytest
from app import create_app, db
from app.models import Employee, Department
from config import TestingConfig

@pytest.fixture(scope='session')
def app():
    """Create test app."""
    app = create_app('testing')

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture(scope='function')
def client(app):
    """Create test client."""
    with app.test_client() as client:
        with app.app_context():
            yield client

@pytest.fixture(scope='function')
def db_session(app):
    """Create database session for tests."""
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()

        # Configure session to use this connection
        session = db.create_scoped_session(
            options={"bind": connection, "binds": {}}
        )
        db.session = session

        yield session

        transaction.rollback()
        connection.close()

@pytest.fixture
def sample_department(db_session):
    """Create sample department."""
    dept = Department(
        name="Engineering",
        description="Software Engineering Department",
        budget=1000000.0
    )
    db_session.add(dept)
    db_session.commit()
    return dept

@pytest.fixture
def sample_employee(db_session, sample_department):
    """Create sample employee."""
    emp = Employee(
        first_name="John",
        last_name="Doe",
        email="john.doe@company.com",
        employee_id="EMP001",
        hire_date=date(2023, 1, 1),
        job_title="Software Engineer",
        salary=75000.0,
        department=sample_department
    )
    db_session.add(emp)
    db_session.commit()
    return emp
```

### Model Tests

```python
"""Test database models."""
# tests/test_models.py
from datetime import date, datetime
import pytest
from app.models import Employee, Department

def test_department_creation(db_session):
    """Test department model creation."""
    dept = Department(
        name="Marketing",
        description="Marketing Department",
        budget=500000.0
    )
    db_session.add(dept)
    db_session.commit()

    assert dept.id is not None
    assert dept.name == "Marketing"
    assert dept.budget == 500000.0
    assert dept.is_active is True

def test_employee_creation(db_session, sample_department):
    """Test employee model creation."""
    emp = Employee(
        first_name="Jane",
        last_name="Smith",
        email="jane.smith@company.com",
        employee_id="EMP002",
        hire_date=date(2023, 6, 1),
        job_title="Marketing Manager",
        salary=85000.0,
        department=sample_department
    )
    db_session.add(emp)
    db_session.commit()

    assert emp.id is not None
    assert emp.full_name == "Jane Smith"
    assert emp.years_of_service > 0

def test_employee_department_relationship(db_session, sample_employee, sample_department):
    """Test employee-department relationship."""
    assert sample_employee.department == sample_department
    assert sample_employee in sample_department.employees

def test_employee_manager_relationship(db_session, sample_department):
    """Test employee manager relationship."""
    manager = Employee(
        first_name="Bob",
        last_name="Manager",
        email="bob.manager@company.com",
        employee_id="EMP003",
        hire_date=date(2020, 1, 1),
        job_title="Engineering Manager",
        department=sample_department
    )
    db_session.add(manager)
    db_session.commit()

    subordinate = Employee(
        first_name="Alice",
        last_name="Developer",
        email="alice.dev@company.com",
        employee_id="EMP004",
        hire_date=date(2023, 1, 1),
        job_title="Software Developer",
        department=sample_department,
        manager=manager
    )
    db_session.add(subordinate)
    db_session.commit()

    assert subordinate.manager == manager
    assert subordinate in manager.direct_reports
```

### View Tests

```python
"""Test views and endpoints."""
# tests/test_views.py
import json
from unittest.mock import patch

def test_employee_list_view(client):
    """Test employee list view."""
    response = client.get('/employee/')
    assert response.status_code == 200
    assert b'Employee Directory' in response.data

def test_dashboard_view(client):
    """Test dashboard view."""
    response = client.get('/dashboard/')
    assert response.status_code == 200
    assert b'Dashboard' in response.data

def test_dashboard_api_metrics(client):
    """Test dashboard metrics API."""
    response = client.get('/dashboard/api/metrics')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'total_employees' in data
    assert 'total_departments' in data
    assert 'total_projects' in data

@patch('app.views.send_welcome_email')
def test_employee_creation(mock_email, client, sample_department):
    """Test employee creation via form."""
    employee_data = {
        'first_name': 'Test',
        'last_name': 'User',
        'email': 'test.user@company.com',
        'employee_id': 'EMP999',
        'hire_date': '2023-01-01',
        'job_title': 'Test Engineer',
        'salary': 70000,
        'department': sample_department.id
    }

    response = client.post('/employee/add', data=employee_data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Employee Test User added successfully!' in response.data

    # Verify email was sent
    mock_email.assert_called_once()

def test_employee_deactivation_action(client, sample_employee):
    """Test bulk employee deactivation."""
    action_data = {
        'action': 'deactivate',
        'rowid': [sample_employee.id]
    }

    response = client.post('/employee/action', data=action_data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Deactivated 1 employees' in response.data
```

### API Tests

```python
"""Test API endpoints."""
# tests/test_api.py
import json

def test_api_employee_list(client):
    """Test employee API list endpoint."""
    response = client.get('/api/v1/employee/')
    assert response.status_code == 200

    data = json.loads(response.data)
    assert 'result' in data
    assert isinstance(data['result'], list)

def test_api_employee_create(client, sample_department):
    """Test employee API creation."""
    employee_data = {
        'first_name': 'API',
        'last_name': 'Test',
        'email': 'api.test@company.com',
        'employee_id': 'EMPAPI001',
        'hire_date': '2023-01-01',
        'job_title': 'API Tester',
        'department_id': sample_department.id
    }

    response = client.post(
        '/api/v1/employee/',
        data=json.dumps(employee_data),
        content_type='application/json'
    )
    assert response.status_code == 201

    data = json.loads(response.data)
    assert data['result']['first_name'] == 'API'
    assert data['result']['last_name'] == 'Test'

def test_api_employee_update(client, sample_employee):
    """Test employee API update."""
    update_data = {
        'job_title': 'Senior Software Engineer'
    }

    response = client.put(
        f'/api/v1/employee/{sample_employee.id}',
        data=json.dumps(update_data),
        content_type='application/json'
    )
    assert response.status_code == 200

    data = json.loads(response.data)
    assert data['result']['job_title'] == 'Senior Software Engineer'
```

## 🚀 Development Workflow

### Environment Management

```bash
# Development commands
export FLASK_APP=app.py
export FLASK_ENV=development

# Run development server
flask run --host=0.0.0.0 --port=5000

# Run with auto-reload
flask run --reload

# Database operations
flask db init
flask db migrate -m "Description of changes"
flask db upgrade

# Create admin user
flask fab create-admin

# Reset database
flask fab reset-db

# Shell access
flask shell
```

### Code Quality Tools

```bash
# Install development tools
pip install black flake8 isort mypy pytest pytest-cov

# Code formatting
black app/ tests/
isort app/ tests/

# Linting
flake8 app/ tests/

# Type checking
mypy app/

# Testing
pytest
pytest --cov=app --cov-report=html
pytest -v --tb=short
```

### Git Workflow

```bash
# Feature development workflow
git checkout -b feature/new-employee-dashboard
git add .
git commit -m "Add employee dashboard with metrics"
git push origin feature/new-employee-dashboard

# Create pull request and merge
git checkout main
git pull origin main
git branch -d feature/new-employee-dashboard
```

For more advanced topics, see:
- [API Development Guide](api_development.md)
- [Security Implementation](../security/security_architecture.md)
- [Testing Best Practices](testing_guide.md)
- [Deployment Guide](../deployment/production_deployment.md)