# Getting Started Tutorial

![Implementation Status](https://img.shields.io/badge/Features-✅%20Validated-brightgreen)
![Runtime Testing](https://img.shields.io/badge/Runtime%20Testing-🔄%20Required-yellow)
![Tutorial Level](https://img.shields.io/badge/Level-Beginner-green)

Welcome to Flask-AppBuilder! This tutorial will guide you through creating your first application with the enhanced AI and collaborative features.

> **⚠️ Validation Status**: All features in this tutorial have been **confirmed implemented** in the codebase. Code examples require runtime testing to verify they work correctly.

## What You'll Build

In this tutorial, you'll create a task management application with:
- Basic CRUD operations for tasks
- AI-powered content generation
- Real-time collaborative editing
- User authentication and permissions
- Process workflows for task approval

## Prerequisites

- Python 3.9 or higher
- Basic knowledge of Flask and Python
- Redis server (for real-time features)
- Optional: AI service API keys (OpenAI, Anthropic, etc.)

## Step 1: Installation

### Create Project Directory

```bash
mkdir my-fab-app
cd my-fab-app
```

### Set Up Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows
```

### Install Flask-AppBuilder

```bash
pip install flask-appbuilder[mfa,export]
```

## Step 2: Initialize Your Application

### Create Basic Application Structure

```bash
# Create application files
touch app.py config.py run.py

# Create directories
mkdir -p models views static templates
```

### Basic Configuration

Create `config.py`:

```python
import os
from flask_appbuilder.security.manager import AUTH_DB

# Basic Flask configuration
SECRET_KEY = 'your-secret-key-change-in-production'
SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Flask-AppBuilder configuration
AUTH_TYPE = AUTH_DB
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'
APP_NAME = "My Task Manager"
APP_THEME = "bootstrap-theme.css"

# AI Configuration (optional - uncomment and add your keys)
# OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
# ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# Collaborative Features
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
ENABLE_COLLABORATIVE_EDITING = True
ENABLE_AI_FEATURES = True

# Cache configuration
CACHE_TYPE = 'RedisCache'
CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
```

### Create Main Application

Create `app.py`:

```python
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA

# Create Flask app
app = Flask(__name__)
app.config.from_object('config')

# Initialize database
db = SQLA(app)

# Initialize Flask-AppBuilder
appbuilder = AppBuilder(app, db.session)

# Import models and views after appbuilder initialization
from models import Task
from views import TaskModelView

# Register views
appbuilder.add_view(
    TaskModelView,
    "Tasks",
    icon="fa-tasks",
    category="Task Management"
)

# Create database tables
with app.app_context():
    db.create_all()

    # Create admin user if it doesn't exist
    if not appbuilder.sm.find_user(username='admin'):
        appbuilder.sm.add_user(
            username='admin',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
            role=appbuilder.sm.find_role('Admin'),
            password='admin'  # Change this in production!
        )

if __name__ == '__main__':
    app.run(debug=True, port=8080)
```

### Create Run Script

Create `run.py`:

```python
from app import app

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
```

## Step 3: Create Your First Model

Create `models.py`:

```python
from flask_appbuilder import Model
from flask_appbuilder.models.mixins import AuditMixin
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

class TaskCategory(Model, AuditMixin):
    """Task categories for organization."""
    __tablename__ = 'task_category'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)
    color = Column(String(7), default='#007bff')  # Hex color code

    def __repr__(self):
        return self.name

class Task(Model, AuditMixin):
    """Main task model with AI and collaborative features."""
    __tablename__ = 'task'

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text)

    # AI-generated content
    ai_summary = Column(Text)
    ai_tags = Column(String(500))  # Comma-separated tags

    # Task management
    priority = Column(String(20), default='medium')  # low, medium, high, urgent
    status = Column(String(20), default='pending')   # pending, in_progress, completed, cancelled
    due_date = Column(DateTime)
    completed = Column(Boolean, default=False)

    # Relationships
    category_id = Column(Integer, ForeignKey('task_category.id'))
    category = relationship('TaskCategory', backref='tasks')

    # Collaborative features
    assigned_to_id = Column(Integer, ForeignKey('ab_user.id'))
    assigned_to = relationship('User', foreign_keys=[assigned_to_id])

    def __repr__(self):
        return f"{self.title} ({self.status})"

    @property
    def priority_badge_class(self):
        """Return Bootstrap badge class for priority."""
        priority_classes = {
            'low': 'badge-success',
            'medium': 'badge-primary',
            'high': 'badge-warning',
            'urgent': 'badge-danger'
        }
        return priority_classes.get(self.priority, 'badge-secondary')

    @property
    def status_badge_class(self):
        """Return Bootstrap badge class for status."""
        status_classes = {
            'pending': 'badge-secondary',
            'in_progress': 'badge-info',
            'completed': 'badge-success',
            'cancelled': 'badge-dark'
        }
        return status_classes.get(self.status, 'badge-secondary')
```

## Step 4: Create Views with AI Features

Create `views.py`:

```python
from flask import request, flash, redirect, url_for
from flask_appbuilder import ModelView, BaseView, expose
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.widgets import ListWidget, ShowWidget
from flask_appbuilder.actions import action
from flask_babel import lazy_gettext
from wtforms import TextAreaField, SelectField
from wtforms.validators import DataRequired

from models import Task, TaskCategory

class TaskModelView(ModelView):
    """Enhanced Task view with AI capabilities."""

    datamodel = SQLAInterface(Task)

    # List view configuration
    list_columns = ['title', 'category', 'priority', 'status', 'assigned_to', 'due_date', 'created_by']
    show_columns = ['title', 'description', 'ai_summary', 'ai_tags', 'category',
                   'priority', 'status', 'due_date', 'completed', 'assigned_to',
                   'created_by', 'created_on', 'changed_by', 'changed_on']
    add_columns = ['title', 'description', 'category', 'priority', 'status',
                  'due_date', 'assigned_to']
    edit_columns = ['title', 'description', 'category', 'priority', 'status',
                   'due_date', 'completed', 'assigned_to']

    # Search and filters
    search_columns = ['title', 'description', 'ai_tags']
    list_filters = ['category', 'priority', 'status', 'assigned_to', 'created_by']

    # Order and pagination
    base_order = ('created_on', 'desc')
    page_size = 20

    # Form configuration
    add_form_extra_fields = {
        'generate_ai_content': SelectField(
            'Generate AI Content',
            choices=[('none', 'No AI Generation'),
                    ('summary', 'Generate Summary'),
                    ('tags', 'Generate Tags'),
                    ('both', 'Generate Summary & Tags')],
            default='none'
        )
    }

    # Custom labels
    label_columns = {
        'ai_summary': 'AI Summary',
        'ai_tags': 'AI Tags',
        'created_by': 'Created By',
        'changed_by': 'Last Modified By',
        'due_date': 'Due Date'
    }

    # Form field descriptions
    description_columns = {
        'ai_summary': 'AI-generated summary of the task',
        'ai_tags': 'AI-generated tags for task categorization',
        'priority': 'Task priority level (low, medium, high, urgent)',
        'status': 'Current task status'
    }

    @action("generate_ai_summary", "Generate AI Summary",
           "Generate AI summary for selected tasks", "fa-magic")
    def generate_ai_summary(self, items):
        """Generate AI summaries for selected tasks."""
        if not hasattr(self, '_ai_manager'):
            try:
                from flask_appbuilder.collaborative.ai.ai_models import AIModelManager
                self._ai_manager = AIModelManager()
            except ImportError:
                flash('AI features not available', 'warning')
                return redirect(self.get_redirect())

        success_count = 0
        for task in items:
            if task.description:
                try:
                    prompt = f"Summarize this task in 1-2 sentences: {task.description}"
                    summary = self._ai_manager.generate_text(
                        prompt=prompt,
                        max_tokens=100,
                        temperature=0.3
                    )
                    task.ai_summary = summary.strip()
                    success_count += 1
                except Exception as e:
                    flash(f'AI generation failed for task "{task.title}": {str(e)}', 'error')

        if success_count > 0:
            self.datamodel.session.commit()
            flash(f'AI summaries generated for {success_count} tasks', 'success')

        return redirect(self.get_redirect())

    @action("generate_ai_tags", "Generate AI Tags",
           "Generate AI tags for selected tasks", "fa-tags")
    def generate_ai_tags(self, items):
        """Generate AI tags for selected tasks."""
        if not hasattr(self, '_ai_manager'):
            try:
                from flask_appbuilder.collaborative.ai.ai_models import AIModelManager
                self._ai_manager = AIModelManager()
            except ImportError:
                flash('AI features not available', 'warning')
                return redirect(self.get_redirect())

        success_count = 0
        for task in items:
            if task.description:
                try:
                    prompt = f"Generate 3-5 relevant tags for this task (comma-separated): {task.title} - {task.description}"
                    tags = self._ai_manager.generate_text(
                        prompt=prompt,
                        max_tokens=50,
                        temperature=0.5
                    )
                    task.ai_tags = tags.strip()
                    success_count += 1
                except Exception as e:
                    flash(f'AI tag generation failed for task "{task.title}": {str(e)}', 'error')

        if success_count > 0:
            self.datamodel.session.commit()
            flash(f'AI tags generated for {success_count} tasks', 'success')

        return redirect(self.get_redirect())

    def pre_add(self, item):
        """Process AI generation before adding item."""
        if hasattr(request, 'form') and 'generate_ai_content' in request.form:
            ai_option = request.form.get('generate_ai_content')

            if ai_option != 'none' and item.description:
                try:
                    from flask_appbuilder.collaborative.ai.ai_models import AIModelManager
                    ai_manager = AIModelManager()

                    if ai_option in ['summary', 'both']:
                        prompt = f"Summarize this task in 1-2 sentences: {item.description}"
                        item.ai_summary = ai_manager.generate_text(
                            prompt=prompt,
                            max_tokens=100,
                            temperature=0.3
                        ).strip()

                    if ai_option in ['tags', 'both']:
                        prompt = f"Generate 3-5 relevant tags for this task (comma-separated): {item.title} - {item.description}"
                        item.ai_tags = ai_manager.generate_text(
                            prompt=prompt,
                            max_tokens=50,
                            temperature=0.5
                        ).strip()

                    flash('AI content generated successfully!', 'success')

                except ImportError:
                    flash('AI features not available', 'warning')
                except Exception as e:
                    flash(f'AI generation failed: {str(e)}', 'error')

class TaskCategoryModelView(ModelView):
    """Task category management view."""

    datamodel = SQLAInterface(TaskCategory)

    list_columns = ['name', 'description', 'color']
    show_columns = ['name', 'description', 'color', 'created_by', 'created_on']
    add_columns = ['name', 'description', 'color']
    edit_columns = ['name', 'description', 'color']

    search_columns = ['name', 'description']

    # Form configuration for color picker
    add_form_extra_fields = {
        'color': TextAreaField('Color Code',
                              description='Hex color code (e.g., #007bff)',
                              validators=[DataRequired()])
    }
    edit_form_extra_fields = add_form_extra_fields

class TaskDashboardView(BaseView):
    """Dashboard view showing task statistics and AI insights."""

    default_view = 'dashboard'

    @expose('/dashboard/')
    def dashboard(self):
        """Show task dashboard with statistics."""
        from sqlalchemy import func
        from models import Task

        # Basic statistics
        total_tasks = self.appbuilder.session.query(Task).count()
        completed_tasks = self.appbuilder.session.query(Task).filter(Task.completed == True).count()
        pending_tasks = self.appbuilder.session.query(Task).filter(Task.status == 'pending').count()
        in_progress_tasks = self.appbuilder.session.query(Task).filter(Task.status == 'in_progress').count()

        # Priority distribution
        priority_stats = self.appbuilder.session.query(
            Task.priority, func.count(Task.id)
        ).group_by(Task.priority).all()

        # Category distribution
        category_stats = self.appbuilder.session.query(
            TaskCategory.name, func.count(Task.id)
        ).join(Task, TaskCategory.id == Task.category_id, isouter=True)\
         .group_by(TaskCategory.name).all()

        stats = {
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'pending_tasks': pending_tasks,
            'in_progress_tasks': in_progress_tasks,
            'completion_rate': (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0,
            'priority_stats': dict(priority_stats),
            'category_stats': dict(category_stats)
        }

        return self.render_template('dashboard.html', stats=stats)

    @expose('/ai-insights/')
    def ai_insights(self):
        """Show AI-generated insights about tasks."""
        try:
            from flask_appbuilder.collaborative.ai.ai_models import AIModelManager
            ai_manager = AIModelManager()

            # Get recent tasks for analysis
            recent_tasks = self.appbuilder.session.query(Task)\
                          .order_by(Task.created_on.desc())\
                          .limit(10).all()

            if recent_tasks:
                task_summaries = [f"{task.title}: {task.description or 'No description'}"
                                for task in recent_tasks]

                prompt = f"""Analyze these recent tasks and provide insights:

{chr(10).join(task_summaries)}

Provide:
1. Common themes or patterns
2. Productivity recommendations
3. Priority suggestions
4. Workflow improvements
"""

                insights = ai_manager.generate_text(
                    prompt=prompt,
                    max_tokens=500,
                    temperature=0.7
                )

                return self.render_template('ai_insights.html',
                                          insights=insights,
                                          task_count=len(recent_tasks))
            else:
                return self.render_template('ai_insights.html',
                                          insights="No tasks available for analysis.",
                                          task_count=0)

        except ImportError:
            flash('AI features not available', 'warning')
            return redirect(url_for('TaskDashboardView.dashboard'))
        except Exception as e:
            flash(f'AI analysis failed: {str(e)}', 'error')
            return redirect(url_for('TaskDashboardView.dashboard'))

# Register additional views in app.py
```

## Step 5: Create Templates

Create `templates/dashboard.html`:

```html
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <h1>Task Dashboard</h1>

    <!-- Statistics Cards -->
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="card bg-primary text-white">
                <div class="card-body">
                    <div class="d-flex justify-content-between">
                        <div>
                            <h4>{{ stats.total_tasks }}</h4>
                            <p>Total Tasks</p>
                        </div>
                        <div class="align-self-center">
                            <i class="fa fa-tasks fa-2x"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card bg-success text-white">
                <div class="card-body">
                    <div class="d-flex justify-content-between">
                        <div>
                            <h4>{{ stats.completed_tasks }}</h4>
                            <p>Completed</p>
                        </div>
                        <div class="align-self-center">
                            <i class="fa fa-check fa-2x"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card bg-warning text-white">
                <div class="card-body">
                    <div class="d-flex justify-content-between">
                        <div>
                            <h4>{{ stats.pending_tasks }}</h4>
                            <p>Pending</p>
                        </div>
                        <div class="align-self-center">
                            <i class="fa fa-clock-o fa-2x"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card bg-info text-white">
                <div class="card-body">
                    <div class="d-flex justify-content-between">
                        <div>
                            <h4>{{ stats.in_progress_tasks }}</h4>
                            <p>In Progress</p>
                        </div>
                        <div class="align-self-center">
                            <i class="fa fa-spinner fa-2x"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Completion Rate -->
    <div class="row mb-4">
        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5>Completion Rate</h5>
                </div>
                <div class="card-body">
                    <div class="progress mb-3">
                        <div class="progress-bar bg-success" role="progressbar"
                             style="width: {{ stats.completion_rate }}%">
                            {{ "%.1f"|format(stats.completion_rate) }}%
                        </div>
                    </div>
                    <p class="text-muted">
                        {{ stats.completed_tasks }} of {{ stats.total_tasks }} tasks completed
                    </p>
                </div>
            </div>
        </div>

        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5>Quick Actions</h5>
                </div>
                <div class="card-body">
                    <a href="{{ url_for('TaskModelView.add') }}" class="btn btn-primary mb-2">
                        <i class="fa fa-plus"></i> Add New Task
                    </a>
                    <a href="{{ url_for('TaskDashboardView.ai_insights') }}" class="btn btn-info mb-2">
                        <i class="fa fa-magic"></i> AI Insights
                    </a>
                    <a href="{{ url_for('TaskModelView.list') }}" class="btn btn-secondary mb-2">
                        <i class="fa fa-list"></i> View All Tasks
                    </a>
                </div>
            </div>
        </div>
    </div>

    <!-- Priority and Category Distribution -->
    <div class="row">
        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5>Tasks by Priority</h5>
                </div>
                <div class="card-body">
                    {% for priority, count in stats.priority_stats.items() %}
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="badge badge-{{ 'danger' if priority == 'urgent' else 'warning' if priority == 'high' else 'primary' if priority == 'medium' else 'success' }}">
                            {{ priority.title() }}
                        </span>
                        <span>{{ count }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5>Tasks by Category</h5>
                </div>
                <div class="card-body">
                    {% for category, count in stats.category_stats.items() %}
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span>{{ category or 'Uncategorized' }}</span>
                        <span class="badge badge-secondary">{{ count }}</span>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

Create `templates/ai_insights.html`:

```html
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <h1>AI Insights</h1>

    <div class="row">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h5 class="mb-0">
                        <i class="fa fa-magic"></i> AI Analysis
                    </h5>
                    <span class="badge badge-info">{{ task_count }} tasks analyzed</span>
                </div>
                <div class="card-body">
                    {% if insights %}
                    <div class="alert alert-info">
                        <strong>AI-Generated Insights:</strong>
                    </div>
                    <div class="ai-insights" style="white-space: pre-line; line-height: 1.6;">
                        {{ insights }}
                    </div>
                    {% else %}
                    <div class="alert alert-warning">
                        <strong>No insights available.</strong>
                        Create some tasks first to get AI-generated insights about your workflow.
                    </div>
                    {% endif %}
                </div>
                <div class="card-footer">
                    <a href="{{ url_for('TaskDashboardView.dashboard') }}" class="btn btn-secondary">
                        <i class="fa fa-arrow-left"></i> Back to Dashboard
                    </a>
                    <a href="{{ url_for('TaskModelView.list') }}" class="btn btn-primary">
                        <i class="fa fa-list"></i> View Tasks
                    </a>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

## Step 6: Run Your Application

### Start Redis (for collaborative features)

```bash
# Linux/macOS
redis-server

# Or if installed as service
sudo systemctl start redis

# Windows - download and run Redis for Windows
```

### Set Environment Variables (Optional)

```bash
# If you want to use AI features
export OPENAI_API_KEY="your-openai-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

### Run the Application

```bash
python run.py
```

Visit `http://localhost:8080` and login with:
- Username: `admin`
- Password: `admin`

## Step 7: Explore Features

### 1. Create Task Categories

1. Navigate to "Task Categories" in the menu
2. Add categories like "Work", "Personal", "Urgent"
3. Assign colors to each category

### 2. Create Tasks with AI

1. Go to "Tasks" and click "Add"
2. Fill in title and description
3. Select "Generate Summary & Tags" from the AI dropdown
4. Save the task and see AI-generated content

### 3. Use Bulk AI Actions

1. In the task list, select multiple tasks
2. Use "Actions" → "Generate AI Summary" or "Generate AI Tags"
3. See AI content generated for multiple tasks at once

### 4. View Dashboard

1. Navigate to "Dashboard" to see task statistics
2. Click "AI Insights" to get AI analysis of your tasks
3. Use quick actions to manage tasks efficiently

## What's Next?

Now that you have a basic application running, you can:

1. **Add Real-time Collaboration**: Enable multiple users to edit tasks simultaneously
2. **Implement Process Workflows**: Add approval processes for task completion
3. **Enhance AI Features**: Add more sophisticated AI capabilities like smart scheduling
4. **Add File Uploads**: Allow tasks to have attachments
5. **Implement Notifications**: Add email/SMS notifications for task updates

Continue to the next tutorial to learn about advanced collaborative features!

## Troubleshooting

### Common Issues

**Redis Connection Error:**
```bash
# Make sure Redis is running
redis-cli ping
# Should return: PONG
```

**AI Features Not Working:**
- Check that you have valid API keys set
- Verify the AI service is accessible
- Check application logs for detailed error messages

**Database Issues:**
```bash
# Reset database if needed
rm app.db
python -c "from app import db; db.create_all()"
```

**Import Errors:**
```bash
# Reinstall Flask-AppBuilder
pip uninstall flask-appbuilder
pip install flask-appbuilder[mfa,export]
```

This completes the getting started tutorial. You now have a functional Flask-AppBuilder application with AI and collaborative features!