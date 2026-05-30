"""
Example PgAppForge configuration with ProcessManager.

Shows how to properly integrate the Intelligent Business Process Engine
with PgAppForge using the addon manager pattern.
"""

import os
from flask import Flask
from pgappforge import AppBuilder, SQLA

# Import the ProcessManager
from pgappforge.process import ProcessManager

# PgAppForge configuration
class Config(object):
    """Base PgAppForge configuration."""
    
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here-change-in-production'
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.dirname(__file__), 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Process Engine Configuration
    PROCESS_REDIS_URL = os.environ.get('PROCESS_REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0') 
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    
    # Process Engine Settings
    PROCESS_MAX_CONCURRENT = 100
    PROCESS_DEFAULT_TIMEOUT = 3600  # 1 hour
    PROCESS_RETENTION_DAYS = 90
    STUCK_PROCESS_HOURS = 24
    PROCESS_ENABLE_ML = False  # Set to True if you have ML dependencies
    PROCESS_ENABLE_AUDIT = True
    
    # Security settings
    AUTH_TYPE = 1  # Database authentication
    AUTH_ROLE_ADMIN = 'Admin'
    AUTH_ROLE_PUBLIC = 'Public'
    
    # Register ProcessManager as an addon
    ADDON_MANAGERS = [
        'pgappforge.process.manager.ProcessManager'
    ]


def create_app():
    """Create Flask application with ProcessManager."""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize SQLAlchemy
    db = SQLA(app)
    
    # Initialize PgAppForge
    appbuilder = AppBuilder(app, db.session)
    
    # The ProcessManager will be automatically initialized due to ADDON_MANAGERS
    # You can access it via: appbuilder.process_manager
    
    return app


if __name__ == '__main__':
    """Run the application."""
    app = create_app()
    
    # Optional: Create admin user if it doesn't exist
    with app.app_context():
        from pgappforge.security.sqla.models import User
        
        if not app.appbuilder.sm.find_user('admin'):
            app.appbuilder.sm.add_user(
                username='admin',
                first_name='Admin',
                last_name='User',
                email='admin@example.com',
                role=app.appbuilder.sm.find_role('Admin'),
                password='admin'  # Change in production!
            )
            print("Created admin user (username: admin, password: admin)")
    
    # Run the app
    app.run(host='0.0.0.0', port=8080, debug=True)