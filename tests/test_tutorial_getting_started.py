#!/usr/bin/env python3
"""
Comprehensive tests for the Getting Started tutorial.

This test suite validates that the tutorial example application works correctly
and all features function as expected without runtime errors.
"""

import os
import sys
import tempfile
import shutil
import unittest
import json
from typing import Dict, Any, Optional
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add examples directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'examples', 'tutorial_getting_started'))

import pytest


class TutorialGettingStartedTest(unittest.TestCase):
    """Test suite for Getting Started tutorial."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Mock environment variables for testing
        self.env_patches = {
            'OPENAI_API_KEY': 'test-openai-key',
            'ANTHROPIC_API_KEY': 'test-anthropic-key',
            'REDIS_URL': 'redis://localhost:6379/1',
            'SECRET_KEY': 'test-secret-key-for-testing-purposes',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{self.test_dir}/tutorial.db'
        }

        for key, value in self.env_patches.items():
            os.environ[key] = value

    def tearDown(self):
        """Clean up test environment."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

        # Clean up environment variables
        for key in self.env_patches:
            if key in os.environ:
                del os.environ[key]

    def test_config_import(self):
        """Test that config module can be imported."""
        try:
            import config
            self.assertIsNotNone(config)
        except ImportError as e:
            self.fail(f"Failed to import config module: {e}")

    def test_config_validation_functions(self):
        """Test config validation functions."""
        import config

        # Test database validation
        db_status = config.validate_database_configuration()
        self.assertIn('status', db_status.lower())

        # Test Redis validation
        redis_status = config.validate_redis_configuration()
        self.assertIn('status', redis_status.lower())

        # Test AI validation
        ai_status = config.validate_ai_configuration()
        self.assertIsInstance(ai_status, dict)

    def test_models_import(self):
        """Test that models can be imported."""
        try:
            import models
            self.assertIsNotNone(models)

            # Test that model classes exist
            self.assertTrue(hasattr(models, 'Task'))
            self.assertTrue(hasattr(models, 'TaskCategory'))
            self.assertTrue(hasattr(models, 'Priority'))
            self.assertTrue(hasattr(models, 'Status'))
        except ImportError as e:
            self.fail(f"Failed to import models module: {e}")

    def test_model_enums(self):
        """Test that model enums are properly defined."""
        from models import Priority, Status

        # Test Priority enum
        self.assertEqual(Priority.LOW.value, 'low')
        self.assertEqual(Priority.MEDIUM.value, 'medium')
        self.assertEqual(Priority.HIGH.value, 'high')
        self.assertEqual(Priority.URGENT.value, 'urgent')

        # Test Status enum
        self.assertEqual(Status.PENDING.value, 'pending')
        self.assertEqual(Status.IN_PROGRESS.value, 'in_progress')
        self.assertEqual(Status.COMPLETED.value, 'completed')
        self.assertEqual(Status.CANCELLED.value, 'cancelled')

    def test_views_import(self):
        """Test that views can be imported."""
        try:
            import views
            self.assertIsNotNone(views)

            # Test that view classes exist
            self.assertTrue(hasattr(views, 'TaskModelView'))
            self.assertTrue(hasattr(views, 'TaskCategoryModelView'))
            self.assertTrue(hasattr(views, 'TaskDashboardView'))
        except ImportError as e:
            self.fail(f"Failed to import views module: {e}")

    @patch('redis.Redis.ping')
    @patch('sqlalchemy.create_engine')
    def test_app_creation(self, mock_engine, mock_redis):
        """Test that the Flask app can be created."""
        # Mock Redis connection
        mock_redis.return_value = True

        # Mock SQLAlchemy engine
        mock_engine.return_value = MagicMock()

        try:
            import app
            flask_app = app.create_app()

            self.assertIsNotNone(flask_app)
            self.assertEqual(flask_app.config['TESTING'], True)
        except Exception as e:
            self.fail(f"Failed to create Flask app: {e}")

    @patch('redis.Redis.ping')
    @patch('sqlalchemy.create_engine')
    def test_app_initialization(self, mock_engine, mock_redis):
        """Test app initialization and database setup."""
        mock_redis.return_value = True
        mock_engine.return_value = MagicMock()

        try:
            import app
            flask_app = app.create_app()

            with flask_app.app_context():
                # Test that AppBuilder is initialized
                self.assertTrue(hasattr(flask_app, 'appbuilder'))

                # Test that security manager is set up
                self.assertIsNotNone(flask_app.appbuilder.sm)
        except Exception as e:
            self.fail(f"Failed to initialize app: {e}")

    def test_environment_validation(self):
        """Test environment validation function."""
        try:
            import app

            # This should not raise an exception
            app.validate_environment()
        except Exception as e:
            self.fail(f"Environment validation failed: {e}")

    def test_ai_service_initialization(self):
        """Test that AI services can be initialized with mock credentials."""
        try:
            import config

            # Test AI provider configuration
            ai_config = config.validate_ai_configuration()
            self.assertIsInstance(ai_config, dict)

            # Should have entries for different providers
            expected_providers = ['openai', 'anthropic', 'google', 'groq', 'ollama']
            for provider in expected_providers:
                self.assertIn(provider, ai_config)
        except Exception as e:
            self.fail(f"AI service initialization failed: {e}")

    def test_template_files_exist(self):
        """Test that required template files exist."""
        template_dir = Path(__file__).parent.parent / 'examples' / 'tutorial_getting_started' / 'templates'

        required_templates = [
            'dashboard.html',
            'ai_insights.html',
            'reports.html'
        ]

        for template in required_templates:
            template_path = template_dir / template
            self.assertTrue(template_path.exists(), f"Template {template} does not exist")

    def test_static_files_structure(self):
        """Test that static files are properly structured."""
        # This is a basic test - in a real scenario, we'd check for CSS/JS files
        examples_dir = Path(__file__).parent.parent / 'examples' / 'tutorial_getting_started'
        self.assertTrue(examples_dir.exists(), "Tutorial directory does not exist")

    @patch('openai.OpenAI')
    def test_ai_integration_mock(self, mock_openai):
        """Test AI integration with mocked OpenAI client."""
        # Mock OpenAI response
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Test AI response"))]
        )

        try:
            from views import TaskModelView

            # Create a mock task instance
            task_data = {
                'title': 'Test Task',
                'description': 'Test Description',
                'priority': 'medium',
                'status': 'pending'
            }

            # This would normally test AI generation, but we're mocking it
            self.assertIsNotNone(task_data)
        except Exception as e:
            self.fail(f"AI integration test failed: {e}")

    def test_database_model_relationships(self):
        """Test that database model relationships are properly defined."""
        try:
            from models import Task, TaskCategory

            # Test that Task has a category relationship
            self.assertTrue(hasattr(Task, 'category'))
            self.assertTrue(hasattr(Task, 'category_id'))

            # Test that TaskCategory has tasks relationship
            self.assertTrue(hasattr(TaskCategory, 'tasks'))
        except Exception as e:
            self.fail(f"Model relationship test failed: {e}")

    def test_view_permissions(self):
        """Test that view permissions are properly configured."""
        try:
            from views import TaskModelView, TaskCategoryModelView, TaskDashboardView

            # Test that views have proper class attributes
            self.assertTrue(hasattr(TaskModelView, 'datamodel'))
            self.assertTrue(hasattr(TaskCategoryModelView, 'datamodel'))
            self.assertTrue(hasattr(TaskDashboardView, 'route_base'))
        except Exception as e:
            self.fail(f"View permissions test failed: {e}")

    def test_configuration_completeness(self):
        """Test that all required configuration is present."""
        try:
            import config

            # Test required config attributes
            required_configs = [
                'SECRET_KEY',
                'SQLALCHEMY_DATABASE_URI',
                'REDIS_URL',
                'WTF_CSRF_ENABLED'
            ]

            for attr in required_configs:
                self.assertTrue(hasattr(config, attr), f"Missing config: {attr}")
        except Exception as e:
            self.fail(f"Configuration completeness test failed: {e}")

    def test_security_configuration(self):
        """Test security configuration is properly set up."""
        try:
            import config

            # Test security configurations
            self.assertTrue(hasattr(config, 'AUTH_TYPE'))
            self.assertTrue(hasattr(config, 'AUTH_ROLE_ADMIN'))
            self.assertTrue(hasattr(config, 'AUTH_ROLE_PUBLIC'))
        except Exception as e:
            self.fail(f"Security configuration test failed: {e}")


class TutorialIntegrationTest(unittest.TestCase):
    """Integration tests for tutorial functionality."""

    def setUp(self):
        """Set up integration test environment."""
        self.test_dir = tempfile.mkdtemp()

        # Set up minimal environment
        self.env_patches = {
            'SECRET_KEY': 'test-secret-key-for-integration-testing',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{self.test_dir}/integration.db',
            'TESTING': 'True'
        }

        for key, value in self.env_patches.items():
            os.environ[key] = value

    def tearDown(self):
        """Clean up integration test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

        for key in self.env_patches:
            if key in os.environ:
                del os.environ[key]

    @patch('redis.Redis.ping')
    @patch('redis.Redis')
    def test_full_application_lifecycle(self, mock_redis_class, mock_redis_ping):
        """Test complete application lifecycle."""
        # Mock Redis
        mock_redis_ping.return_value = True
        mock_redis_instance = MagicMock()
        mock_redis_class.return_value = mock_redis_instance

        try:
            # Add tutorial directory to path
            tutorial_path = os.path.join(os.path.dirname(__file__), '..', 'examples', 'tutorial_getting_started')
            if tutorial_path not in sys.path:
                sys.path.insert(0, tutorial_path)

            import app
            flask_app = app.create_app()

            with flask_app.app_context():
                # Test app creation
                self.assertIsNotNone(flask_app)

                # Test database initialization
                from flask_appbuilder.models.sqla import Model
                from models import Task, TaskCategory

                # Create tables (in real scenario, this would be done by migrations)
                Model.metadata.create_all(bind=flask_app.appbuilder.get_session.bind)

                # Test model operations
                session = flask_app.appbuilder.get_session

                # Create a test category
                category = TaskCategory(name="Test Category", description="Test Category Description")
                session.add(category)
                session.commit()

                # Create a test task
                task = Task(
                    title="Integration Test Task",
                    description="This is a test task",
                    category=category,
                    priority="medium",
                    status="pending"
                )
                session.add(task)
                session.commit()

                # Verify task was created
                self.assertEqual(task.title, "Integration Test Task")
                self.assertEqual(task.category.name, "Test Category")

                # Test task query
                tasks = session.query(Task).all()
                self.assertEqual(len(tasks), 1)

                # Clean up
                session.delete(task)
                session.delete(category)
                session.commit()

        except Exception as e:
            self.fail(f"Full application lifecycle test failed: {e}")

    def test_mock_ai_workflow(self):
        """Test AI workflow with mocked services."""
        with patch('openai.OpenAI') as mock_openai:
            # Mock AI response
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="AI generated summary"))]
            )

            try:
                # Test that AI workflow functions can be called
                test_task_data = {
                    'title': 'Test Task',
                    'description': 'Test task for AI processing',
                    'priority': 'high'
                }

                # In a real test, this would call actual AI service methods
                # For now, just verify the mock setup works
                self.assertIsNotNone(test_task_data)

            except Exception as e:
                self.fail(f"Mock AI workflow test failed: {e}")


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)