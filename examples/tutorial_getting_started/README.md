# Flask-AppBuilder Getting Started Tutorial

![Status](https://img.shields.io/badge/Status-✅%20Working-brightgreen)
![Dependencies](https://img.shields.io/badge/Dependencies-✅%20Validated-brightgreen)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue)

This is a complete, working implementation of the Flask-AppBuilder Getting Started tutorial.

## Features

✅ **Task Management System**
- Create, edit, delete tasks
- Task categories with color coding
- Priority and status management
- AI-generated summaries and tags
- Interactive dashboard with statistics

✅ **AI Integration**
- OpenAI GPT integration
- Anthropic Claude support
- AI-powered content generation
- Automatic summarization

✅ **Modern UI**
- Bootstrap-based responsive design
- Interactive dashboard
- Real-time statistics

## Quick Start

### 1. Install Dependencies

```bash
# Install Flask-AppBuilder with AI features
pip install flask-appbuilder[mfa,export,analytics]

# Install additional tutorial dependencies
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
# Optional: Add AI API keys for full functionality
export OPENAI_API_KEY="your-openai-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# Optional: Configure Redis for collaborative features
export REDIS_URL="redis://localhost:6379/0"
```

### 3. Start Supporting Services

```bash
# Start Redis (optional, for collaborative features)
redis-server

# Verify Redis is running
redis-cli ping  # Should return: PONG
```

### 4. Run the Application

```bash
# Run the application
python app.py
```

### 5. Access the Application

Open your browser to `http://localhost:8080`

**Default Credentials:**
- Username: `admin`
- Password: `admin`

## Application Structure

```
tutorial_getting_started/
├── app.py              # Main application entry point
├── config.py           # Configuration settings
├── models.py           # Database models (Task, TaskCategory)
├── views.py            # View classes and dashboard
├── requirements.txt    # Python dependencies
├── README.md          # This file
└── templates/         # Custom templates
    ├── dashboard.html
    └── ai_insights.html
```

## Usage Guide

### 1. Create Task Categories

1. Navigate to "Task Categories" in the menu
2. Add categories like:
   - **Work** (color: #007bff)
   - **Personal** (color: #28a745)
   - **Urgent** (color: #dc3545)

### 2. Create Tasks with AI

1. Go to "Tasks" → "Add"
2. Fill in:
   - **Title**: "Complete project proposal"
   - **Description**: "Create a comprehensive project proposal for the new client including budget, timeline, and deliverables"
   - **Category**: Work
   - **Priority**: High
   - **AI Generation**: "Generate Summary & Tags"
3. Save and see AI-generated content

### 3. Use Dashboard

1. Navigate to "Dashboard"
2. View task statistics and completion rates
3. Click "AI Insights" for analysis of your tasks

### 4. Bulk AI Operations

1. In task list, select multiple tasks
2. Use "Actions" → "Generate AI Summary"
3. Watch AI generate summaries for all selected tasks

## API Examples

### Add Task via API

```python
import requests

# Add a new task
task_data = {
    "title": "Review documentation",
    "description": "Review and update project documentation",
    "priority": "medium",
    "status": "pending"
}

response = requests.post(
    "http://localhost:8080/api/v1/task/",
    json=task_data,
    auth=('admin', 'admin')
)
```

### Get Task Statistics

```python
import requests

# Get all tasks
response = requests.get(
    "http://localhost:8080/api/v1/task/",
    auth=('admin', 'admin')
)

tasks = response.json()
print(f"Total tasks: {tasks['count']}")
```

## Configuration Options

### AI Providers

The application supports multiple AI providers:

```python
# config.py
AI_DEFAULT_PROVIDER = 'openai'  # or 'anthropic', 'groq'
AI_FALLBACK_PROVIDERS = ['anthropic', 'groq']

# Provider-specific settings
OPENAI_MODEL = 'gpt-4'
ANTHROPIC_MODEL = 'claude-3-sonnet-20240229'
```

### Database Configuration

```python
# SQLite (development)
SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'

# PostgreSQL (production)
SQLALCHEMY_DATABASE_URI = 'postgresql://user:pass@localhost/myapp'
```

## Troubleshooting

### Common Issues

**Redis Connection Error:**
```bash
# Make sure Redis is running
redis-cli ping
# Should return: PONG

# If not installed:
# macOS: brew install redis
# Ubuntu: sudo apt install redis-server
```

**AI Features Not Working:**
- Verify API keys are set correctly
- Check console logs for detailed error messages
- Ensure internet connectivity for AI provider APIs

**Database Issues:**
```bash
# Reset database
rm app.db
python -c "from app import db; db.create_all()"
```

**Import Errors:**
```bash
# Reinstall with all features
pip uninstall flask-appbuilder
pip install flask-appbuilder[mfa,export,analytics]
```

### Performance Optimization

**For Production:**

1. **Use PostgreSQL:**
   ```python
   SQLALCHEMY_DATABASE_URI = 'postgresql://user:pass@localhost/myapp'
   ```

2. **Enable Caching:**
   ```python
   CACHE_TYPE = 'RedisCache'
   CACHE_REDIS_URL = 'redis://localhost:6379/1'
   ```

3. **Configure Logging:**
   ```python
   import logging
   logging.basicConfig(level=logging.INFO)
   ```

## Extending the Application

### Add Custom Fields

```python
# models.py
class Task(Model, AuditMixin):
    # Add custom fields
    estimated_hours = Column(Integer)
    actual_hours = Column(Integer)
    tags = Column(String(500))
```

### Add Custom Views

```python
# views.py
class CustomTaskView(ModelView):
    # Override default behavior
    def pre_add(self, item):
        # Custom logic before adding
        item.created_by_id = g.user.id
```

### Add API Endpoints

```python
# api.py
from flask_appbuilder.api import ModelRestApi

class TaskApi(ModelRestApi):
    datamodel = SQLAInterface(Task)
    allow_browser_login = True
```

## Next Steps

After completing this tutorial:

1. **[Collaborative Features Tutorial](../tutorial_collaborative/)** - Add real-time collaboration
2. **[AI Integration Tutorial](../tutorial_ai/)** - Advanced AI capabilities
3. **[Process Workflows](../process_workflows/)** - Add approval workflows

## Contributing

Found an issue or want to improve this tutorial?

1. Check existing issues
2. Submit bug reports with detailed reproduction steps
3. Contribute improvements via pull requests

## License

This tutorial is part of Flask-AppBuilder and follows the same BSD license.