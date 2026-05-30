#!/usr/bin/env python3
"""
Test configuration for PgForge tutorial tests.

This module provides standardized configuration for all tutorial tests,
ensuring consistent test environments and reliable test execution.
"""

import os
import tempfile
import unittest
from typing import Dict, Any, Optional
from pathlib import Path
from unittest.mock import patch, MagicMock


class TutorialTestConfig:
    """Configuration class for tutorial tests."""

    # Test environment configuration
    TEST_DATABASE_URI = 'sqlite:///:memory:'
    TEST_REDIS_URL = 'redis://localhost:6379/15'
    TEST_SECRET_KEY = 'tutorial-test-secret-key-for-comprehensive-testing'

    # AI provider test keys
    TEST_OPENAI_KEY = 'test-openai-key-for-tutorial-testing'
    TEST_ANTHROPIC_KEY = 'test-anthropic-key-for-tutorial-testing'
    TEST_GOOGLE_KEY = 'test-google-key-for-tutorial-testing'
    TEST_GROQ_KEY = 'test-groq-key-for-tutorial-testing'

    # Test performance thresholds
    MAX_APP_STARTUP_TIME = 10.0  # seconds
    MAX_DATABASE_OPERATION_TIME = 5.0  # seconds
    MAX_VIEW_RENDER_TIME = 2.0  # seconds
    BULK_OPERATION_THRESHOLD = 100  # records

    # Test data limits
    MAX_TEST_TASKS = 1000
    MAX_TEST_CATEGORIES = 50
    DEFAULT_TEST_BATCH_SIZE = 10

    @classmethod
    def get_base_config(cls) -> Dict[str, Any]:
        """Get base test configuration."""
        return {
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SECRET_KEY': cls.TEST_SECRET_KEY,
            'SQLALCHEMY_DATABASE_URI': cls.TEST_DATABASE_URI,
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'SQLALCHEMY_ENGINE_OPTIONS': {
                'pool_pre_ping': True,
                'pool_recycle': 300,
            },
            'REDIS_URL': cls.TEST_REDIS_URL,
            'CACHE_TYPE': 'simple',
            'LANGUAGES': {
                'en': {'flag': 'us', 'name': 'English'},
            },
            'AUTH_TYPE': 1,  # Database authentication
            'AUTH_ROLE_ADMIN': 'Admin',
            'AUTH_ROLE_PUBLIC': 'Public',
            'AUTH_USER_REGISTRATION': True,
            'AUTH_USER_REGISTRATION_ROLE': 'Public',
            'UPLOAD_FOLDER': tempfile.gettempdir(),
            'IMG_UPLOAD_FOLDER': tempfile.gettempdir(),
            'IMG_UPLOAD_URL': '/static/uploads/',
            'OPENAI_API_KEY': cls.TEST_OPENAI_KEY,
            'ANTHROPIC_API_KEY': cls.TEST_ANTHROPIC_KEY,
            'GOOGLE_API_KEY': cls.TEST_GOOGLE_KEY,
            'GROQ_API_KEY': cls.TEST_GROQ_KEY,
        }

    @classmethod
    def get_ai_disabled_config(cls) -> Dict[str, Any]:
        """Get configuration with AI features disabled."""
        config = cls.get_base_config()
        # Remove AI keys to test graceful degradation
        for key in ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY', 'GROQ_API_KEY']:
            config.pop(key, None)
        return config

    @classmethod
    def get_redis_disabled_config(cls) -> Dict[str, Any]:
        """Get configuration with Redis disabled."""
        config = cls.get_base_config()
        config['REDIS_URL'] = None
        config['CACHE_TYPE'] = 'null'
        return config

    @classmethod
    def get_performance_config(cls) -> Dict[str, Any]:
        """Get configuration optimized for performance testing."""
        config = cls.get_base_config()
        config.update({
            'SQLALCHEMY_ENGINE_OPTIONS': {
                'pool_size': 10,
                'max_overflow': 20,
                'pool_pre_ping': True,
                'pool_recycle': 300,
            },
            'SQLALCHEMY_ECHO': False,  # Disable SQL logging for performance
        })
        return config

    @classmethod
    def get_file_config(cls, test_dir: str) -> Dict[str, Any]:
        """Get configuration with file-based database."""
        config = cls.get_base_config()
        config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{test_dir}/tutorial_test.db'
        return config


class TestEnvironmentManager:
    """Manager for test environment setup and teardown."""

    def __init__(self, config_type: str = 'base'):
        self.config_type = config_type
        self.test_dir = None
        self.original_env = {}
        self.patches = []

    def __enter__(self):
        """Enter test environment context."""
        return self.setup()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit test environment context."""
        self.cleanup()

    def setup(self) -> Dict[str, Any]:
        """Set up test environment."""
        # Create temporary directory
        self.test_dir = tempfile.mkdtemp(prefix='tutorial_test_')

        # Get configuration
        if self.config_type == 'base':
            config = TutorialTestConfig.get_base_config()
        elif self.config_type == 'ai_disabled':
            config = TutorialTestConfig.get_ai_disabled_config()
        elif self.config_type == 'redis_disabled':
            config = TutorialTestConfig.get_redis_disabled_config()
        elif self.config_type == 'performance':
            config = TutorialTestConfig.get_performance_config()
        elif self.config_type == 'file':
            config = TutorialTestConfig.get_file_config(self.test_dir)
        else:
            config = TutorialTestConfig.get_base_config()

        # Set environment variables
        for key, value in config.items():
            if isinstance(value, (str, int, bool)):
                self.original_env[key] = os.environ.get(key)
                os.environ[key] = str(value)

        # Set up common patches
        self.setup_patches()

        return config

    def setup_patches(self):
        """Set up common mock patches."""
        # Mock Redis by default
        redis_patch = patch('redis.Redis')
        mock_redis = redis_patch.start()
        mock_redis.return_value.ping.return_value = True
        self.patches.append(redis_patch)

        # Mock AI providers
        openai_patch = patch('openai.OpenAI')
        mock_openai = openai_patch.start()
        mock_openai.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Test AI response"))]
        )
        self.patches.append(openai_patch)

    def cleanup(self):
        """Clean up test environment."""
        # Stop patches
        for patch_obj in self.patches:
            patch_obj.stop()
        self.patches.clear()

        # Restore environment variables
        for key, original_value in self.original_env.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
        self.original_env.clear()

        # Clean up temporary directory
        if self.test_dir:
            import shutil
            shutil.rmtree(self.test_dir, ignore_errors=True)
            self.test_dir = None


class BaseTutorialTestCase(unittest.TestCase):
    """Base test case class for tutorial tests."""

    @classmethod
    def setUpClass(cls):
        """Set up class-level test resources."""
        # Add tutorial path to sys.path
        import sys
        cls.tutorial_path = Path(__file__).parent.parent / 'examples' / 'tutorial_getting_started'
        if str(cls.tutorial_path) not in sys.path:
            sys.path.insert(0, str(cls.tutorial_path))

    def setUp(self):
        """Set up individual test."""
        self.env_manager = TestEnvironmentManager('base')
        self.config = self.env_manager.setup()

    def tearDown(self):
        """Clean up individual test."""
        self.env_manager.cleanup()

    def create_test_app(self):
        """Create a test Flask application."""
        try:
            import app
            flask_app = app.create_app()
            flask_app.config.update(self.config)
            return flask_app
        except Exception as e:
            self.fail(f"Failed to create test app: {e}")

    def assertResponseTime(self, func, max_time: float, *args, **kwargs):
        """Assert that a function completes within the specified time."""
        import time
        start_time = time.time()
        result = func(*args, **kwargs)
        execution_time = time.time() - start_time

        self.assertLess(
            execution_time, max_time,
            f"Function {func.__name__} took {execution_time:.4f}s, "
            f"expected less than {max_time}s"
        )
        return result

    def assertDatabaseOperationTime(self, func, *args, **kwargs):
        """Assert that a database operation completes within threshold."""
        return self.assertResponseTime(
            func, TutorialTestConfig.MAX_DATABASE_OPERATION_TIME, *args, **kwargs
        )

    def assertViewRenderTime(self, func, *args, **kwargs):
        """Assert that a view renders within threshold."""
        return self.assertResponseTime(
            func, TutorialTestConfig.MAX_VIEW_RENDER_TIME, *args, **kwargs
        )


class TutorialTestSuite:
    """Test suite manager for tutorial tests."""

    @staticmethod
    def discover_tests(start_dir: Optional[str] = None) -> unittest.TestSuite:
        """Discover all tutorial tests."""
        if start_dir is None:
            start_dir = str(Path(__file__).parent)

        loader = unittest.TestLoader()
        suite = loader.discover(
            start_dir,
            pattern='test_tutorial*.py',
            top_level_dir=str(Path(__file__).parent.parent)
        )
        return suite

    @staticmethod
    def run_tests(verbosity: int = 2) -> unittest.TestResult:
        """Run all tutorial tests."""
        suite = TutorialTestSuite.discover_tests()
        runner = unittest.TextTestRunner(verbosity=verbosity)
        return runner.run(suite)

    @staticmethod
    def run_performance_tests() -> unittest.TestResult:
        """Run performance-specific tests."""
        loader = unittest.TestLoader()
        suite = loader.discover(
            str(Path(__file__).parent),
            pattern='*performance*.py'
        )
        runner = unittest.TextTestRunner(verbosity=2)
        return runner.run(suite)

    @staticmethod
    def generate_test_report(result: unittest.TestResult) -> Dict[str, Any]:
        """Generate a test report from test results."""
        return {
            'total_tests': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
            'success_rate': ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0,
            'failure_details': [str(failure[1]) for failure in result.failures],
            'error_details': [str(error[1]) for error in result.errors],
        }


class MockServiceManager:
    """Manager for mock services used in testing."""

    def __init__(self):
        self.redis_mock = None
        self.ai_mocks = {}
        self.patches = []

    def setup_redis_mock(self, connected: bool = True):
        """Set up Redis mock."""
        from tests.fixtures.tutorial_test_data import MockRedisClient
        self.redis_mock = MockRedisClient()
        if not connected:
            self.redis_mock.disconnect()

        redis_patch = patch('redis.Redis', return_value=self.redis_mock)
        redis_patch.start()
        self.patches.append(redis_patch)

    def setup_ai_mocks(self):
        """Set up AI provider mocks."""
        from tests.fixtures.tutorial_test_data import MockAIResponses

        # OpenAI mock
        openai_patch = patch('openai.OpenAI')
        mock_openai = openai_patch.start()
        mock_openai.return_value = MockAIResponses.get_mock_openai_client()
        self.ai_mocks['openai'] = mock_openai
        self.patches.append(openai_patch)

        # Anthropic mock
        anthropic_patch = patch('anthropic.Anthropic')
        mock_anthropic = anthropic_patch.start()
        mock_anthropic.return_value = MockAIResponses.get_mock_anthropic_client()
        self.ai_mocks['anthropic'] = mock_anthropic
        self.patches.append(anthropic_patch)

    def cleanup(self):
        """Clean up all mocks."""
        for patch_obj in self.patches:
            patch_obj.stop()
        self.patches.clear()
        self.redis_mock = None
        self.ai_mocks.clear()

    def __enter__(self):
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        self.cleanup()


# Test configuration presets
TEST_CONFIGS = {
    'minimal': TutorialTestConfig.get_base_config(),
    'ai_disabled': TutorialTestConfig.get_ai_disabled_config(),
    'redis_disabled': TutorialTestConfig.get_redis_disabled_config(),
    'performance': TutorialTestConfig.get_performance_config(),
}


def run_tutorial_validation():
    """Run complete tutorial validation."""
    print("🔍 Running Tutorial Validation Tests...")

    # Run test suite
    result = TutorialTestSuite.run_tests()

    # Generate report
    report = TutorialTestSuite.generate_test_report(result)

    # Print summary
    print(f"\n📊 Test Results Summary:")
    print(f"Total Tests: {report['total_tests']}")
    print(f"Failures: {report['failures']}")
    print(f"Errors: {report['errors']}")
    print(f"Success Rate: {report['success_rate']:.1f}%")

    if report['failures'] > 0:
        print(f"\n❌ Failures:")
        for failure in report['failure_details'][:3]:  # Show first 3 failures
            print(f"  - {failure}")

    if report['errors'] > 0:
        print(f"\n🚨 Errors:")
        for error in report['error_details'][:3]:  # Show first 3 errors
            print(f"  - {error}")

    return result.wasSuccessful()


if __name__ == '__main__':
    # Run validation when script is executed directly
    success = run_tutorial_validation()
    exit(0 if success else 1)