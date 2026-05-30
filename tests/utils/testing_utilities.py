#!/usr/bin/env python3
"""
Testing utilities and helpers for PgAppForge tutorial tests.

This module provides reusable utilities for setting up test environments,
generating test data, and managing test resources.
"""

import os
import sys
import tempfile
import shutil
import json
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Union
from contextlib import contextmanager
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

# Configure logging for test utilities
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestEnvironmentManager:
    """Advanced test environment management with resource tracking."""

    def __init__(self, config_name: str = 'default'):
        self.config_name = config_name
        self.temp_dirs = []
        self.patches = []
        self.processes = []
        self.cleanup_functions = []
        self.start_time = time.time()

    def create_temp_directory(self, prefix: str = 'test_') -> Path:
        """Create a temporary directory and track it for cleanup."""
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        self.temp_dirs.append(temp_dir)
        logger.debug(f"Created temporary directory: {temp_dir}")
        return temp_dir

    def patch_module(self, target: str, **kwargs) -> Mock:
        """Create and track a patch for automatic cleanup."""
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.patches.append(patcher)
        logger.debug(f"Applied patch to: {target}")
        return mock

    def start_process(self, cmd: List[str], **kwargs) -> subprocess.Popen:
        """Start a process and track it for cleanup."""
        process = subprocess.Popen(cmd, **kwargs)
        self.processes.append(process)
        logger.debug(f"Started process: {' '.join(cmd)}")
        return process

    def add_cleanup_function(self, func: Callable, *args, **kwargs):
        """Add a custom cleanup function."""
        self.cleanup_functions.append((func, args, kwargs))

    def cleanup(self):
        """Clean up all tracked resources."""
        cleanup_start = time.time()

        # Run custom cleanup functions
        for func, args, kwargs in reversed(self.cleanup_functions):
            try:
                func(*args, **kwargs)
                logger.debug(f"Executed cleanup function: {func.__name__}")
            except Exception as e:
                logger.warning(f"Cleanup function {func.__name__} failed: {e}")

        # Terminate processes
        for process in self.processes:
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                logger.debug(f"Terminated process: {process.pid}")
            except Exception as e:
                logger.warning(f"Failed to terminate process {process.pid}: {e}")

        # Stop patches
        for patcher in reversed(self.patches):
            try:
                patcher.stop()
            except Exception as e:
                logger.warning(f"Failed to stop patch: {e}")

        # Remove temporary directories
        for temp_dir in self.temp_dirs:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug(f"Removed temporary directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to remove directory {temp_dir}: {e}")

        cleanup_time = time.time() - cleanup_start
        total_time = time.time() - self.start_time
        logger.info(f"Cleanup completed in {cleanup_time:.2f}s (total session: {total_time:.2f}s)")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


class MockServiceFactory:
    """Factory for creating mock services used in testing."""

    @staticmethod
    def create_redis_mock(connected: bool = True, data: Optional[Dict] = None) -> Mock:
        """Create a mock Redis client."""
        mock_redis = Mock()
        mock_redis.ping.return_value = connected
        mock_redis.connected = connected

        # Set up data store
        store = data or {}
        mock_redis.get.side_effect = lambda key: store.get(key)
        mock_redis.set.side_effect = lambda key, value, **kwargs: store.update({key: value})
        mock_redis.delete.side_effect = lambda key: store.pop(key, None)
        mock_redis.exists.side_effect = lambda key: key in store
        mock_redis.flushdb.side_effect = lambda: store.clear()

        return mock_redis

    @staticmethod
    def create_ai_mock(provider: str = 'openai') -> Mock:
        """Create a mock AI client for various providers."""
        mock_client = Mock()

        if provider == 'openai':
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "Mock AI response from OpenAI"
            mock_client.chat.completions.create.return_value = mock_response

        elif provider == 'anthropic':
            mock_response = Mock()
            mock_response.completion = "Mock AI response from Anthropic"
            mock_client.completions.create.return_value = mock_response

        elif provider == 'google':
            mock_response = Mock()
            mock_response.text = "Mock AI response from Google"
            mock_client.generate_text.return_value = mock_response

        return mock_client

    @staticmethod
    def create_database_mock() -> Mock:
        """Create a mock database session."""
        mock_session = Mock()
        mock_session.query.return_value = mock_session
        mock_session.filter.return_value = mock_session
        mock_session.all.return_value = []
        mock_session.first.return_value = None
        mock_session.count.return_value = 0
        mock_session.add.return_value = None
        mock_session.commit.return_value = None
        mock_session.rollback.return_value = None
        return mock_session


class TestDataGenerator:
    """Generator for realistic test data."""

    @staticmethod
    def generate_tasks(count: int = 10, category_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Generate realistic task data for testing."""
        import random

        if category_names is None:
            category_names = ['Development', 'Testing', 'Documentation', 'DevOps']

        priorities = ['low', 'medium', 'high', 'urgent']
        statuses = ['pending', 'in_progress', 'completed', 'cancelled']

        task_templates = [
            "Implement {feature} functionality",
            "Fix {issue} in {component}",
            "Add {feature} to {component}",
            "Optimize {component} performance",
            "Update {component} documentation",
            "Test {feature} integration",
            "Deploy {feature} to production",
            "Research {technology} implementation"
        ]

        features = ['authentication', 'payment', 'notification', 'search', 'reporting', 'dashboard']
        components = ['API', 'frontend', 'database', 'cache', 'queue', 'middleware']
        issues = ['bug', 'memory leak', 'performance issue', 'security vulnerability']
        technologies = ['GraphQL', 'Redis', 'Docker', 'Kubernetes', 'microservices']

        tasks = []
        for i in range(count):
            template = random.choice(task_templates)
            title = template.format(
                feature=random.choice(features),
                component=random.choice(components),
                issue=random.choice(issues),
                technology=random.choice(technologies)
            )

            status = random.choice(statuses)
            estimated_hours = random.randint(1, 40)
            actual_hours = None
            progress = 0

            if status == 'in_progress':
                progress = random.randint(10, 90)
                actual_hours = int(estimated_hours * (progress / 100))
            elif status == 'completed':
                progress = 100
                actual_hours = random.randint(estimated_hours - 5, estimated_hours + 10)
            elif status == 'cancelled':
                progress = random.randint(0, 50)
                actual_hours = int(estimated_hours * (progress / 100)) if progress > 0 else None

            task = {
                'title': title,
                'description': f"Detailed description for: {title}. This task involves multiple steps and requires careful coordination.",
                'priority': random.choice(priorities),
                'status': status,
                'category': random.choice(category_names),
                'estimated_hours': estimated_hours,
                'actual_hours': actual_hours,
                'progress': progress,
                'created_on': datetime.now() - timedelta(days=random.randint(0, 30)),
                'due_date': datetime.now() + timedelta(days=random.randint(1, 60))
            }
            tasks.append(task)

        return tasks

    @staticmethod
    def generate_categories(count: int = 5) -> List[Dict[str, Any]]:
        """Generate realistic category data for testing."""
        category_data = [
            {'name': 'Development', 'description': 'Software development and programming tasks', 'color': '#007bff'},
            {'name': 'Testing', 'description': 'Quality assurance and testing activities', 'color': '#28a745'},
            {'name': 'Documentation', 'description': 'Documentation and knowledge sharing', 'color': '#ffc107'},
            {'name': 'DevOps', 'description': 'Infrastructure and deployment tasks', 'color': '#dc3545'},
            {'name': 'Research', 'description': 'Research and analysis activities', 'color': '#6f42c1'},
            {'name': 'Support', 'description': 'Customer support and maintenance', 'color': '#fd7e14'},
            {'name': 'Planning', 'description': 'Project planning and management', 'color': '#20c997'},
            {'name': 'Security', 'description': 'Security and compliance tasks', 'color': '#e83e8c'}
        ]

        return category_data[:count]

    @staticmethod
    def generate_user_data(count: int = 5) -> List[Dict[str, Any]]:
        """Generate realistic user data for testing."""
        import random

        first_names = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve', 'Frank', 'Grace', 'Henry']
        last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis']
        roles = ['Admin', 'User', 'Manager', 'Developer', 'Tester']

        users = []
        for i in range(count):
            first_name = random.choice(first_names)
            last_name = random.choice(last_names)
            username = f"{first_name.lower()}.{last_name.lower()}"
            email = f"{username}@example.com"

            user = {
                'username': username,
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
                'active': random.choice([True, True, True, False]),  # 75% active
                'role': random.choice(roles)
            }
            users.append(user)

        return users


class PerformanceTracker:
    """Track and analyze test performance metrics."""

    def __init__(self):
        self.metrics = {}
        self.start_times = {}

    def start_timing(self, operation: str):
        """Start timing an operation."""
        self.start_times[operation] = time.time()

    def end_timing(self, operation: str) -> float:
        """End timing an operation and return duration."""
        if operation not in self.start_times:
            logger.warning(f"No start time found for operation: {operation}")
            return 0.0

        duration = time.time() - self.start_times[operation]
        if operation not in self.metrics:
            self.metrics[operation] = []
        self.metrics[operation].append(duration)

        del self.start_times[operation]
        return duration

    @contextmanager
    def time_operation(self, operation: str):
        """Context manager for timing operations."""
        self.start_timing(operation)
        try:
            yield
        finally:
            self.end_timing(operation)

    def get_stats(self, operation: str) -> Dict[str, float]:
        """Get statistics for an operation."""
        if operation not in self.metrics:
            return {}

        times = self.metrics[operation]
        return {
            'count': len(times),
            'total': sum(times),
            'average': sum(times) / len(times),
            'min': min(times),
            'max': max(times)
        }

    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get statistics for all operations."""
        return {op: self.get_stats(op) for op in self.metrics.keys()}

    def reset(self):
        """Reset all metrics."""
        self.metrics.clear()
        self.start_times.clear()


class ResourceMonitor:
    """Monitor system resources during tests."""

    def __init__(self):
        self.enabled = self._check_psutil()
        if self.enabled:
            import psutil
            self.process = psutil.Process()
            self.snapshots = []

    def _check_psutil(self) -> bool:
        """Check if psutil is available."""
        try:
            import psutil
            return True
        except ImportError:
            logger.warning("psutil not available - resource monitoring disabled")
            return False

    def take_snapshot(self, label: str = None):
        """Take a snapshot of current resource usage."""
        if not self.enabled:
            return

        import psutil

        snapshot = {
            'timestamp': time.time(),
            'label': label,
            'memory_percent': self.process.memory_percent(),
            'memory_info': self.process.memory_info()._asdict(),
            'cpu_percent': self.process.cpu_percent(),
            'open_files': len(self.process.open_files()),
            'threads': self.process.num_threads(),
        }

        try:
            snapshot['system_memory'] = psutil.virtual_memory()._asdict()
            snapshot['system_cpu'] = psutil.cpu_percent(interval=None)
        except Exception as e:
            logger.debug(f"Failed to get system metrics: {e}")

        self.snapshots.append(snapshot)

    def get_peak_usage(self) -> Dict[str, Any]:
        """Get peak resource usage from snapshots."""
        if not self.snapshots:
            return {}

        peak_memory = max(self.snapshots, key=lambda x: x['memory_percent'])
        peak_cpu = max(self.snapshots, key=lambda x: x['cpu_percent'])

        return {
            'peak_memory_percent': peak_memory['memory_percent'],
            'peak_memory_mb': peak_memory['memory_info']['rss'] / 1024 / 1024,
            'peak_cpu_percent': peak_cpu['cpu_percent'],
            'max_open_files': max(s['open_files'] for s in self.snapshots),
            'max_threads': max(s['threads'] for s in self.snapshots),
            'snapshot_count': len(self.snapshots)
        }

    def reset(self):
        """Reset all snapshots."""
        self.snapshots.clear()


class TutorialTestValidator:
    """Validator for tutorial test requirements and environment."""

    @staticmethod
    def validate_python_version() -> bool:
        """Validate Python version meets requirements."""
        min_version = (3, 9)
        current_version = sys.version_info[:2]
        return current_version >= min_version

    @staticmethod
    def validate_dependencies() -> Dict[str, bool]:
        """Validate that required dependencies are available."""
        required_modules = [
            'flask', 'pgappforge', 'sqlalchemy', 'wtforms',
            'unittest', 'tempfile', 'pathlib', 'json'
        ]

        optional_modules = [
            'redis', 'openai', 'anthropic', 'psutil', 'pytest'
        ]

        results = {'required': {}, 'optional': {}}

        for module in required_modules:
            try:
                __import__(module)
                results['required'][module] = True
            except ImportError:
                results['required'][module] = False

        for module in optional_modules:
            try:
                __import__(module)
                results['optional'][module] = True
            except ImportError:
                results['optional'][module] = False

        return results

    @staticmethod
    def validate_tutorial_structure() -> Dict[str, bool]:
        """Validate tutorial directory structure."""
        project_root = Path(__file__).parent.parent.parent
        tutorial_dir = project_root / 'examples' / 'tutorial_getting_started'

        required_files = [
            'app.py', 'config.py', 'models.py', 'views.py', 'README.md'
        ]

        required_dirs = [
            'templates'
        ]

        results = {}

        for file_name in required_files:
            file_path = tutorial_dir / file_name
            results[f"file_{file_name}"] = file_path.exists()

        for dir_name in required_dirs:
            dir_path = tutorial_dir / dir_name
            results[f"dir_{dir_name}"] = dir_path.exists() and dir_path.is_dir()

        return results

    @staticmethod
    def validate_environment_variables() -> Dict[str, bool]:
        """Validate required environment variables."""
        required_vars = ['SECRET_KEY']
        optional_vars = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'REDIS_URL']

        results = {'required': {}, 'optional': {}}

        for var in required_vars:
            results['required'][var] = bool(os.environ.get(var))

        for var in optional_vars:
            results['optional'][var] = bool(os.environ.get(var))

        return results

    @classmethod
    def run_full_validation(cls) -> Dict[str, Any]:
        """Run complete validation and return results."""
        return {
            'python_version': cls.validate_python_version(),
            'dependencies': cls.validate_dependencies(),
            'tutorial_structure': cls.validate_tutorial_structure(),
            'environment_variables': cls.validate_environment_variables(),
            'timestamp': datetime.now().isoformat()
        }


def setup_test_logging(level: str = 'INFO', file_path: Optional[str] = None):
    """Set up logging for tests."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=[]
    )

    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(console_handler)

    # Add file handler if specified
    if file_path:
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(logging.Formatter(log_format))
        logging.getLogger().addHandler(file_handler)

    logger.info(f"Test logging configured - level: {level}")


def create_test_config(config_type: str = 'minimal') -> Dict[str, Any]:
    """Create test configuration based on type."""
    base_config = {
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret-key-for-utilities',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    }

    if config_type == 'minimal':
        return base_config

    elif config_type == 'full':
        base_config.update({
            'REDIS_URL': 'redis://localhost:6379/15',
            'OPENAI_API_KEY': 'test-openai-key',
            'ANTHROPIC_API_KEY': 'test-anthropic-key',
            'AUTH_TYPE': 1,
            'AUTH_ROLE_ADMIN': 'Admin',
            'AUTH_ROLE_PUBLIC': 'Public'
        })

    elif config_type == 'performance':
        base_config.update({
            'SQLALCHEMY_ENGINE_OPTIONS': {
                'pool_size': 5,
                'max_overflow': 10,
                'pool_pre_ping': True
            }
        })

    return base_config


# Global instances for convenience
performance_tracker = PerformanceTracker()
resource_monitor = ResourceMonitor()


# Export commonly used utilities
__all__ = [
    'TestEnvironmentManager',
    'MockServiceFactory',
    'TestDataGenerator',
    'PerformanceTracker',
    'ResourceMonitor',
    'TutorialTestValidator',
    'setup_test_logging',
    'create_test_config',
    'performance_tracker',
    'resource_monitor'
]