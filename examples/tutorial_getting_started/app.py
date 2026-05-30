"""
Flask-AppBuilder Getting Started Tutorial - Main Application

This is a complete, working Flask-AppBuilder application demonstrating:
- Task management with AI features
- Interactive dashboard with statistics
- Modern UI components
- Production-ready configuration

Run with: python app.py
"""

import os
import logging
from flask import Flask
from flask_appbuilder import AppBuilder, SQLA
from flask_appbuilder.menu import Menu

# Configure logging
logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
logging.getLogger().setLevel(logging.INFO)

def create_app(config_name='config'):
    """
    Application factory for creating Flask-AppBuilder application.
    
    Args:
        config_name: Configuration module name
        
    Returns:
        Tuple of (app, appbuilder) instances
    """
    # Create Flask application
    app = Flask(__name__)
    app.config.from_object(config_name)
    
    # Validate required configuration
    required_config = ['SECRET_KEY', 'SQLALCHEMY_DATABASE_URI']
    for key in required_config:
        if not app.config.get(key):
            raise ValueError(f"Missing required configuration: {key}")
    
    # Initialize SQLAlchemy
    db = SQLA(app)
    
    # Initialize Flask-AppBuilder
    appbuilder = AppBuilder(app, db.session)
    
    # Import models to ensure they're registered
    from models import Task, TaskCategory, TaskHistory
    
    # Import views and register them
    from views import (
        TaskModelView, TaskCategoryModelView, TaskDashboardView, 
        TaskHistoryModelView
    )
    
    # Register main views
    appbuilder.add_view(
        TaskModelView,
        "Tasks",
        icon="fa-tasks",
        category="Task Management",
        category_icon="fa-folder-open-o"
    )
    
    appbuilder.add_view(
        TaskCategoryModelView,
        "Categories",
        icon="fa-folder",
        category="Task Management"
    )
    
    # Register dashboard
    appbuilder.add_view(
        TaskDashboardView,
        "Dashboard",
        icon="fa-dashboard",
        category="Analytics",
        category_icon="fa-bar-chart"
    )
    
    # Register history view (admin only)
    appbuilder.add_view(
        TaskHistoryModelView,
        "Task History",
        icon="fa-history",
        category="Administration",
        category_icon="fa-cogs"
    )
    
    # Add custom menu items
    appbuilder.add_link(
        "AI Insights",
        href="/taskdashboardview/ai-insights/",
        icon="fa-magic",
        category="Analytics"
    )
    
    appbuilder.add_link(
        "Reports",
        href="/taskdashboardview/reports/",
        icon="fa-line-chart",
        category="Analytics"
    )
    
    # Add separator in menu
    appbuilder.add_separator("Analytics")
    
    # Add external links
    appbuilder.add_link(
        "Flask-AppBuilder Docs",
        href="https://flask-appbuilder.readthedocs.io/",
        icon="fa-external-link",
        category="Help"
    )
    
    return app, appbuilder


def validate_environment():
    """
    Validate the application environment and display status.
    
    Returns:
        Boolean indicating if environment is valid
    """
    print("🔍 Validating Application Environment...")
    print("=" * 50)
    
    # Check Python version
    import sys
    python_version = sys.version_info
    print(f"Python Version: {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # Import configuration for validation
    import config
    
    # Validate database
    db_status = config.validate_database_configuration()
    print(f"Database: {db_status}")
    
    # Validate Redis
    redis_status = config.validate_redis_configuration()
    print(f"Redis: {redis_status}")
    
    # Validate AI providers
    ai_providers = config.validate_ai_configuration()
    print("AI Providers:")
    for provider, status in ai_providers.items():
        print(f"  {provider}: {status}")
    
    # Check Flask-AppBuilder features
    print("\nFeature Availability:")
    
    # Check AI features
    try:
        from flask_appbuilder.collaborative.ai.ai_models import AIModelManager
        print("  AI Integration: ✅ Available")
    except ImportError:
        print("  AI Integration: ❌ Not Available")
    
    # Check collaborative features
    try:
        from flask_appbuilder.collaborative.realtime.websocket_manager import WebSocketManager
        print("  Collaborative Features: ✅ Available")
    except ImportError:
        print("  Collaborative Features: ❌ Not Available")
    
    # Check MFA features
    try:
        from flask_appbuilder.security.mfa.models import MFACredential
        print("  MFA Security: ✅ Available")
    except ImportError:
        print("  MFA Security: ❌ Not Available")
    
    print("=" * 50)
    
    # Determine if environment is valid
    has_errors = any('❌' in status for status in [db_status, redis_status] + list(ai_providers.values()))
    
    if has_errors:
        print("⚠️  Some services are not available. The application will still work with limited functionality.")
        print("💡 See README.md for setup instructions.")
        return False
    else:
        print("✅ All services validated successfully!")
        return True


def setup_database(app, appbuilder):
    """
    Set up database tables and initial data.
    
    Args:
        app: Flask application instance
        appbuilder: AppBuilder instance
    """
    with app.app_context():
        # Create all database tables
        try:
            appbuilder.get_session.get_bind().create_all()
            print("✅ Database tables created successfully")
        except Exception as e:
            print(f"❌ Database setup failed: {e}")
            return False
        
        # Create admin user if it doesn't exist
        admin_user = appbuilder.sm.find_user(username='admin')
        if not admin_user:
            try:
                admin_role = appbuilder.sm.find_role('Admin')
                appbuilder.sm.add_user(
                    username='admin',
                    first_name='Admin',
                    last_name='User',
                    email='admin@example.com',
                    role=admin_role,
                    password='admin'
                )
                print("✅ Admin user created: admin/admin")
                print("⚠️  Change the default password in production!")
            except Exception as e:
                print(f"❌ Failed to create admin user: {e}")
                return False
        else:
            print("ℹ️  Admin user already exists")
        
        # Create sample categories if none exist
        from models import TaskCategory
        if appbuilder.session.query(TaskCategory).count() == 0:
            sample_categories = [
                TaskCategory(name='Work', description='Work-related tasks', color='#007bff', sort_order=1),
                TaskCategory(name='Personal', description='Personal tasks', color='#28a745', sort_order=2),
                TaskCategory(name='Urgent', description='Urgent tasks requiring immediate attention', color='#dc3545', sort_order=3),
                TaskCategory(name='Planning', description='Planning and strategy tasks', color='#ffc107', sort_order=4)
            ]
            
            try:
                for category in sample_categories:
                    appbuilder.session.add(category)
                appbuilder.session.commit()
                print("✅ Sample task categories created")
            except Exception as e:
                print(f"❌ Failed to create sample categories: {e}")
                appbuilder.session.rollback()
        
        # Create sample task if none exist
        from models import Task, Priority, Status
        if appbuilder.session.query(Task).count() == 0:
            try:
                work_category = appbuilder.session.query(TaskCategory).filter_by(name='Work').first()
                sample_task = Task(
                    title='Welcome to Flask-AppBuilder!',
                    description='This is a sample task demonstrating the capabilities of your new task management system. You can edit this task, create new ones, and explore all the features including AI-powered content generation.',
                    category=work_category,
                    priority=Priority.MEDIUM,
                    status=Status.PENDING,
                    tags='sample, welcome, demo'
                )
                appbuilder.session.add(sample_task)
                appbuilder.session.commit()
                print("✅ Sample task created")
            except Exception as e:
                print(f"❌ Failed to create sample task: {e}")
                appbuilder.session.rollback()
        
        return True


def main():
    """
    Main application entry point.
    """
    print("🚀 Starting Flask-AppBuilder Tutorial Application")
    print("=" * 60)
    
    # Validate environment
    env_valid = validate_environment()
    
    # Create application
    try:
        app, appbuilder = create_app()
        print("✅ Application created successfully")
    except Exception as e:
        print(f"❌ Failed to create application: {e}")
        return 1
    
    # Setup database
    if not setup_database(app, appbuilder):
        print("❌ Database setup failed")
        return 1
    
    # Display startup information
    print("\n🌐 Application Information:")
    print("=" * 30)
    print(f"URL: http://localhost:8080")
    print(f"Admin Username: admin")
    print(f"Admin Password: admin")
    print(f"Environment: {app.config.get('FLASK_ENV', 'production')}")
    print(f"Debug Mode: {app.config.get('DEBUG', False)}")
    
    if not env_valid:
        print("\n⚠️  Warning: Some features may be limited due to missing dependencies.")
        print("📖 Check README.md for complete setup instructions.")
    
    print("\n🎯 Quick Start Guide:")
    print("1. Open http://localhost:8080 in your browser")
    print("2. Login with admin/admin")
    print("3. Navigate to 'Dashboard' to see task statistics")
    print("4. Go to 'Tasks' to create and manage tasks")
    print("5. Try 'AI Insights' for intelligent task analysis")
    
    print("\n" + "=" * 60)
    print("🚀 Starting Flask development server...")
    
    # Start the application
    try:
        app.run(
            debug=app.config.get('DEBUG', False),
            host='0.0.0.0',
            port=8080,
            use_reloader=app.config.get('DEBUG', False)
        )
    except KeyboardInterrupt:
        print("\n👋 Application stopped by user")
        return 0
    except Exception as e:
        print(f"\n❌ Application failed to start: {e}")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())