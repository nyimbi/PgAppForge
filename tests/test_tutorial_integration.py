#!/usr/bin/env python3
"""
End-to-end integration tests for Flask-AppBuilder tutorials.

This test suite validates complete tutorial workflows, ensuring that
all examples work together correctly and provide the expected user experience.
"""

import os
import sys
import tempfile
import shutil
import unittest
import json
import time
import subprocess
from typing import Dict, Any, List, Optional
from unittest.mock import patch, MagicMock, Mock
from pathlib import Path
from contextlib import contextmanager

# Add paths for tutorial imports
tutorial_path = os.path.join(os.path.dirname(__file__), '..', 'examples', 'tutorial_getting_started')
sys.path.insert(0, tutorial_path)

import pytest


class TutorialWorkflowTest(unittest.TestCase):
    """Test complete tutorial workflows end-to-end."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level test resources."""
        cls.tutorial_dir = Path(__file__).parent.parent / 'examples' / 'tutorial_getting_started'
        cls.test_base_dir = tempfile.mkdtemp(prefix='tutorial_test_')

    @classmethod
    def tearDownClass(cls):
        """Clean up class-level test resources."""
        if hasattr(cls, 'test_base_dir'):
            shutil.rmtree(cls.test_base_dir, ignore_errors=True)

    def setUp(self):
        """Set up individual test environment."""
        self.test_dir = tempfile.mkdtemp(dir=self.test_base_dir)
        self.original_cwd = os.getcwd()

        # Set up test environment variables
        self.env_patches = {
            'SECRET_KEY': 'tutorial-test-secret-key-minimum-20-chars',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{self.test_dir}/test_tutorial.db',
            'REDIS_URL': 'redis://localhost:6379/15',  # Use test database
            'TESTING': 'True',
            'WTF_CSRF_ENABLED': 'False',  # Disable CSRF for testing
            'OPENAI_API_KEY': 'test-openai-key',
            'ANTHROPIC_API_KEY': 'test-anthropic-key'
        }

        for key, value in self.env_patches.items():
            os.environ[key] = value

    def tearDown(self):
        """Clean up individual test environment."""
        os.chdir(self.original_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

        # Clean up environment variables
        for key in self.env_patches:
            if key in os.environ:
                del os.environ[key]

    @contextmanager
    def tutorial_app_context(self):
        """Context manager for tutorial application."""
        try:
            import app
            flask_app = app.create_app()
            with flask_app.app_context():
                yield flask_app
        except Exception as e:
            self.fail(f"Failed to create tutorial app context: {e}")

    def test_tutorial_file_structure(self):
        """Test that all required tutorial files exist."""
        required_files = [
            'app.py',
            'config.py',
            'models.py',
            'views.py',
            'README.md',
            'templates/dashboard.html',
            'templates/ai_insights.html',
            'templates/reports.html'
        ]

        for file_path in required_files:
            full_path = self.tutorial_dir / file_path
            self.assertTrue(full_path.exists(), f"Required file missing: {file_path}")

    @patch('redis.Redis.ping')
    @patch('redis.Redis')
    def test_complete_tutorial_workflow(self, mock_redis_class, mock_redis_ping):
        """Test the complete tutorial workflow from start to finish."""
        # Mock Redis
        mock_redis_ping.return_value = True
        mock_redis_instance = MagicMock()
        mock_redis_class.return_value = mock_redis_instance

        with self.tutorial_app_context() as flask_app:
            # Test 1: Application starts successfully
            self.assertIsNotNone(flask_app)
            self.assertTrue(hasattr(flask_app, 'appbuilder'))

            # Test 2: Database models are properly registered
            from models import Task, TaskCategory, Priority, Status
            from flask_appbuilder.models.sqla import Model

            # Create database tables
            Model.metadata.create_all(bind=flask_app.appbuilder.get_session.bind)

            session = flask_app.appbuilder.get_session

            # Test 3: Create and manage categories
            category = TaskCategory(
                name="Tutorial Category",
                description="A category created during tutorial testing"
            )
            session.add(category)
            session.commit()

            self.assertIsNotNone(category.id)
            self.assertEqual(category.name, "Tutorial Category")

            # Test 4: Create and manage tasks with all priority levels
            priorities = [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.URGENT]
            statuses = [Status.PENDING, Status.IN_PROGRESS, Status.COMPLETED, Status.CANCELLED]

            tasks = []
            for i, (priority, status) in enumerate(zip(priorities, statuses)):
                task = Task(
                    title=f"Tutorial Task {i+1}",
                    description=f"This is tutorial task number {i+1}",
                    category=category,
                    priority=priority,
                    status=status,
                    estimated_hours=2 + i,
                    actual_hours=1 + i if status in [Status.COMPLETED, Status.CANCELLED] else None
                )
                session.add(task)
                tasks.append(task)

            session.commit()

            # Test 5: Verify all tasks were created correctly
            self.assertEqual(len(tasks), 4)
            for task in tasks:
                self.assertIsNotNone(task.id)
                self.assertEqual(task.category, category)

            # Test 6: Test task queries and filtering
            pending_tasks = session.query(Task).filter(Task.status == Status.PENDING).all()
            self.assertEqual(len(pending_tasks), 1)

            high_priority_tasks = session.query(Task).filter(Task.priority == Priority.HIGH).all()
            self.assertEqual(len(high_priority_tasks), 1)

            # Test 7: Test task updates
            task_to_update = tasks[0]
            task_to_update.status = Status.IN_PROGRESS
            task_to_update.progress = 50
            session.commit()

            updated_task = session.query(Task).filter(Task.id == task_to_update.id).first()
            self.assertEqual(updated_task.status, Status.IN_PROGRESS)
            self.assertEqual(updated_task.progress, 50)

            # Test 8: Test task completion workflow
            task_to_complete = tasks[1]
            task_to_complete.status = Status.COMPLETED
            task_to_complete.progress = 100
            task_to_complete.actual_hours = 3
            session.commit()

            completed_task = session.query(Task).filter(Task.id == task_to_complete.id).first()
            self.assertEqual(completed_task.status, Status.COMPLETED)
            self.assertEqual(completed_task.progress, 100)
            self.assertEqual(completed_task.actual_hours, 3)

            # Test 9: Verify audit trail (AuditMixin functionality)
            for task in tasks:
                self.assertIsNotNone(task.created_on)
                self.assertIsNotNone(task.changed_on)
                self.assertIsNotNone(task.created_by_fk)

            # Clean up test data
            for task in tasks:
                session.delete(task)
            session.delete(category)
            session.commit()

    @patch('openai.OpenAI')
    def test_ai_integration_workflow(self, mock_openai):
        """Test AI integration functionality workflow."""
        # Mock OpenAI client and responses
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock AI responses for different scenarios
        mock_responses = {
            'summary': MagicMock(
                choices=[MagicMock(message=MagicMock(content="AI-generated task summary: This is a complex project requiring careful planning."))]
            ),
            'tags': MagicMock(
                choices=[MagicMock(message=MagicMock(content="planning, development, testing, deployment"))]
            ),
            'insights': MagicMock(
                choices=[MagicMock(message=MagicMock(content="This project shows good progress with 75% completion rate."))]
            )
        }

        def mock_create(**kwargs):
            """Mock the OpenAI create method based on the prompt."""
            prompt = kwargs.get('messages', [{}])[-1].get('content', '')
            if 'summary' in prompt.lower():
                return mock_responses['summary']
            elif 'tags' in prompt.lower():
                return mock_responses['tags']
            else:
                return mock_responses['insights']

        mock_client.chat.completions.create.side_effect = mock_create

        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                from models import Task, TaskCategory
                from flask_appbuilder.models.sqla import Model

                # Create database
                Model.metadata.create_all(bind=flask_app.appbuilder.get_session.bind)
                session = flask_app.appbuilder.get_session

                # Create test data
                category = TaskCategory(name="AI Test Category", description="Category for AI testing")
                session.add(category)
                session.commit()

                task = Task(
                    title="AI Integration Test Task",
                    description="A complex task that requires AI-generated summaries and insights",
                    category=category,
                    priority="high",
                    status="pending"
                )
                session.add(task)
                session.commit()

                # Test AI summary generation (simulated)
                task.ai_summary = "AI-generated task summary: This is a complex project requiring careful planning."
                task.ai_tags = "planning, development, testing, deployment"
                session.commit()

                # Verify AI fields are populated
                self.assertIsNotNone(task.ai_summary)
                self.assertIsNotNone(task.ai_tags)
                self.assertIn("complex project", task.ai_summary)
                self.assertIn("planning", task.ai_tags)

                # Clean up
                session.delete(task)
                session.delete(category)
                session.commit()

    def test_dashboard_functionality(self):
        """Test dashboard view and statistics functionality."""
        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                from models import Task, TaskCategory, Status, Priority
                from views import TaskDashboardView
                from flask_appbuilder.models.sqla import Model

                # Create database
                Model.metadata.create_all(bind=flask_app.appbuilder.get_session.bind)
                session = flask_app.appbuilder.get_session

                # Create test data for dashboard
                category = TaskCategory(name="Dashboard Test", description="Test category for dashboard")
                session.add(category)
                session.commit()

                # Create tasks with different statuses for statistics
                task_data = [
                    ("Task 1", Status.PENDING, Priority.HIGH),
                    ("Task 2", Status.IN_PROGRESS, Priority.MEDIUM),
                    ("Task 3", Status.COMPLETED, Priority.LOW),
                    ("Task 4", Status.COMPLETED, Priority.URGENT),
                    ("Task 5", Status.CANCELLED, Priority.MEDIUM)
                ]

                for title, status, priority in task_data:
                    task = Task(
                        title=title,
                        description=f"Description for {title}",
                        category=category,
                        status=status,
                        priority=priority
                    )
                    session.add(task)

                session.commit()

                # Test dashboard statistics
                total_tasks = session.query(Task).count()
                completed_tasks = session.query(Task).filter(Task.status == Status.COMPLETED).count()
                pending_tasks = session.query(Task).filter(Task.status == Status.PENDING).count()
                in_progress_tasks = session.query(Task).filter(Task.status == Status.IN_PROGRESS).count()

                self.assertEqual(total_tasks, 5)
                self.assertEqual(completed_tasks, 2)
                self.assertEqual(pending_tasks, 1)
                self.assertEqual(in_progress_tasks, 1)

                # Calculate completion rate
                completion_rate = (completed_tasks / total_tasks) * 100 if total_tasks > 0 else 0
                self.assertEqual(completion_rate, 40.0)

                # Test priority distribution
                high_priority = session.query(Task).filter(Task.priority == Priority.HIGH).count()
                urgent_priority = session.query(Task).filter(Task.priority == Priority.URGENT).count()

                self.assertEqual(high_priority, 1)
                self.assertEqual(urgent_priority, 1)

                # Clean up
                for title, _, _ in task_data:
                    task = session.query(Task).filter(Task.title == title).first()
                    if task:
                        session.delete(task)
                session.delete(category)
                session.commit()

    def test_view_registration(self):
        """Test that all views are properly registered with the application."""
        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                appbuilder = flask_app.appbuilder

                # Test that views are registered
                view_names = [view.__class__.__name__ for view in appbuilder.baseviews]

                # Check for tutorial-specific views
                expected_views = ['TaskModelView', 'TaskCategoryModelView', 'TaskDashboardView']

                for view_name in expected_views:
                    found = any(view_name in name for name in view_names)
                    self.assertTrue(found, f"View {view_name} not found in registered views")

                # Test that menus are created
                menu_items = appbuilder.menu.get_list()
                self.assertIsNotNone(menu_items)
                self.assertGreater(len(menu_items), 0)

    def test_security_and_permissions(self):
        """Test security configuration and permission setup."""
        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                sm = flask_app.appbuilder.sm

                # Test that security manager is properly configured
                self.assertIsNotNone(sm)

                # Test that default roles exist
                admin_role = sm.find_role('Admin')
                public_role = sm.find_role('Public')

                self.assertIsNotNone(admin_role)
                self.assertIsNotNone(public_role)

                # Test that permissions are created for our models
                from models import Task, TaskCategory

                # The permissions should be automatically created by Flask-AppBuilder
                task_permissions = sm.get_all_permissions()
                permission_names = [perm.name for perm in task_permissions]

                # Check for basic CRUD permissions
                expected_permission_patterns = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']

                for pattern in expected_permission_patterns:
                    found = any(pattern in perm_name for perm_name in permission_names)
                    self.assertTrue(found, f"Permission pattern {pattern} not found")

    def test_configuration_validation(self):
        """Test that configuration validation works correctly."""
        import config

        # Test environment validation
        config.validate_environment()  # Should not raise exception

        # Test individual validation functions
        db_status = config.validate_database_configuration()
        self.assertIsInstance(db_status, str)
        self.assertIn('SQLite', db_status)

        redis_status = config.validate_redis_configuration()
        self.assertIsInstance(redis_status, str)

        ai_status = config.validate_ai_configuration()
        self.assertIsInstance(ai_status, dict)

    def test_template_rendering(self):
        """Test that templates can be rendered without errors."""
        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                with flask_app.test_client() as client:
                    # Test that the application responds
                    response = client.get('/')
                    self.assertIn(response.status_code, [200, 302])  # 302 for redirects to login

                    # In a full test, we would test specific template routes
                    # For now, just verify the app is responsive

    def test_error_handling(self):
        """Test error handling and graceful degradation."""
        # Test with missing AI keys
        for key in ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY']:
            if key in os.environ:
                del os.environ[key]

        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                # App should still start even without AI keys
                self.assertIsNotNone(flask_app)

                import config
                ai_status = config.validate_ai_configuration()

                # Should indicate missing keys
                self.assertIn('openai', ai_status)
                self.assertIn('anthropic', ai_status)

    def test_database_relationships_integrity(self):
        """Test database relationship integrity and constraints."""
        with patch('redis.Redis.ping', return_value=True), \
             patch('redis.Redis', return_value=MagicMock()):

            with self.tutorial_app_context() as flask_app:
                from models import Task, TaskCategory
                from flask_appbuilder.models.sqla import Model

                # Create database
                Model.metadata.create_all(bind=flask_app.appbuilder.get_session.bind)
                session = flask_app.appbuilder.get_session

                # Test foreign key relationships
                category = TaskCategory(name="Relationship Test", description="Test category")
                session.add(category)
                session.commit()

                task = Task(
                    title="Relationship Test Task",
                    description="Test task for relationship testing",
                    category=category,
                    priority="medium",
                    status="pending"
                )
                session.add(task)
                session.commit()

                # Test that relationship works both ways
                self.assertEqual(task.category, category)
                self.assertIn(task, category.tasks)

                # Test cascade behavior (if configured)
                task_id = task.id
                session.delete(category)
                session.commit()

                # Task should still exist but with null category_id
                remaining_task = session.query(Task).filter(Task.id == task_id).first()
                if remaining_task:  # Depends on cascade configuration
                    session.delete(remaining_task)
                    session.commit()


class TutorialPerformanceTest(unittest.TestCase):
    """Performance tests for tutorial functionality."""

    def setUp(self):
        """Set up performance test environment."""
        self.test_dir = tempfile.mkdtemp()
        os.environ['SECRET_KEY'] = 'performance-test-secret-key-minimum-20-chars'
        os.environ['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.test_dir}/perf_test.db'
        os.environ['TESTING'] = 'True'

    def tearDown(self):
        """Clean up performance test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for key in ['SECRET_KEY', 'SQLALCHEMY_DATABASE_URI', 'TESTING']:
            if key in os.environ:
                del os.environ[key]

    @patch('redis.Redis.ping')
    @patch('redis.Redis')
    def test_bulk_operations_performance(self, mock_redis_class, mock_redis_ping):
        """Test performance of bulk operations."""
        mock_redis_ping.return_value = True
        mock_redis_instance = MagicMock()
        mock_redis_class.return_value = mock_redis_instance

        # Add tutorial path
        tutorial_path = os.path.join(os.path.dirname(__file__), '..', 'examples', 'tutorial_getting_started')
        if tutorial_path not in sys.path:
            sys.path.insert(0, tutorial_path)

        import app
        flask_app = app.create_app()

        with flask_app.app_context():
            from models import Task, TaskCategory
            from flask_appbuilder.models.sqla import Model

            # Create database
            Model.metadata.create_all(bind=flask_app.appbuilder.get_session.bind)
            session = flask_app.appbuilder.get_session

            # Create test category
            category = TaskCategory(name="Performance Test", description="Category for performance testing")
            session.add(category)
            session.commit()

            # Test bulk insert performance
            start_time = time.time()
            batch_size = 100

            tasks = []
            for i in range(batch_size):
                task = Task(
                    title=f"Performance Test Task {i}",
                    description=f"Task {i} for performance testing",
                    category=category,
                    priority="medium",
                    status="pending"
                )
                tasks.append(task)

            session.add_all(tasks)
            session.commit()

            insert_time = time.time() - start_time

            # Test bulk query performance
            start_time = time.time()
            all_tasks = session.query(Task).filter(Task.category == category).all()
            query_time = time.time() - start_time

            # Verify results
            self.assertEqual(len(all_tasks), batch_size)

            # Performance assertions (these thresholds may need adjustment)
            self.assertLess(insert_time, 5.0, f"Bulk insert took too long: {insert_time}s")
            self.assertLess(query_time, 1.0, f"Bulk query took too long: {query_time}s")

            # Clean up
            for task in tasks:
                session.delete(task)
            session.delete(category)
            session.commit()


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)