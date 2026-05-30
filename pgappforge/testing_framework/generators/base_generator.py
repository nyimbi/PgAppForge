"""
Base Test Generator

Abstract base class for all test generators providing common functionality
including template management, code generation utilities, and test patterns.
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, Template
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """Represents a single test case."""
    name: str
    description: str
    test_type: str
    method_name: str
    test_code: str
    setup_code: Optional[str] = None
    teardown_code: Optional[str] = None
    dependencies: List[str] = None
    tags: List[str] = None
    expected_execution_time: float = 1.0
    
    def __post_init__(self):
        """Initialize empty collections."""
        if self.dependencies is None:
            self.dependencies = []
        if self.tags is None:
            self.tags = []


class BaseTestGenerator(ABC):
    """
    Abstract base class for all test generators.
    
    Provides common functionality including:
    - Template management and rendering
    - Code generation utilities
    - Common test patterns
    - Test case organization
    - Import management
    """
    
    def __init__(self, config, inspector=None):
        """
        Initialize base test generator.
        
        Args:
            config: Test generation configuration
            inspector: Database inspector (optional)
        """
        self.config = config
        self.inspector = inspector
        
        # Template management
        self.template_dir = self._get_template_directory()
        self.jinja_env = self._setup_jinja_environment()
        
        # Test case tracking
        self.generated_tests: Dict[str, List[TestCase]] = {}
        self.imports: Set[str] = set()
        self.fixtures: Set[str] = set()
        
        logger.debug(f"Initialized {self.__class__.__name__}")
    
    def _get_template_directory(self) -> str:
        """Get template directory for this generator."""
        # Get the directory of the current generator class
        current_file = os.path.abspath(__file__)
        current_dir = os.path.dirname(current_file)
        
        # Go up to testing_framework directory and find templates
        testing_framework_dir = os.path.dirname(current_dir)
        template_dir = os.path.join(testing_framework_dir, 'templates', self.get_generator_type())
        
        if not os.path.exists(template_dir):
            # Create template directory if it doesn't exist
            os.makedirs(template_dir, exist_ok=True)
            logger.warning(f"Template directory created: {template_dir}")
        
        return template_dir
    
    def _setup_jinja_environment(self) -> Environment:
        """Set up Jinja2 template environment."""
        env = Environment(
            loader=FileSystemLoader(self.template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True
        )
        
        # Add custom filters
        env.filters['to_snake_case'] = self._to_snake_case
        env.filters['to_pascal_case'] = self._to_pascal_case
        env.filters['to_camel_case'] = self._to_camel_case
        env.filters['pluralize'] = self._pluralize
        env.filters['singularize'] = self._singularize
        
        return env
    
    @abstractmethod
    def get_generator_type(self) -> str:
        """Return the type of generator (e.g., 'unit', 'integration', 'e2e')."""
        pass
    
    @abstractmethod
    def generate_all_tests(self, schema) -> Dict[str, str]:
        """
        Generate all tests for the given schema.
        
        Args:
            schema: Database schema or table information
            
        Returns:
            Dictionary mapping test file names to test code
        """
        pass
    
    def generate_test_file(self, template_name: str, context: Dict[str, Any], 
                          filename: str = None) -> str:
        """
        Generate a test file from template with given context.
        
        Args:
            template_name: Name of the Jinja2 template file
            context: Template context variables
            filename: Optional filename for error reporting
            
        Returns:
            Generated test code as string
        """
        try:
            template = self.jinja_env.get_template(template_name)
            
            # Add common context variables
            context.update({
                'config': self.config,
                'imports': self._generate_imports(),
                'fixtures': self._generate_fixtures(),
                'timestamp': self._get_timestamp(),
                'generator_info': {
                    'type': self.get_generator_type(),
                    'version': '1.0.0',
                    'class_name': self.__class__.__name__
                }
            })
            
            return template.render(**context)
            
        except Exception as e:
            logger.error(f"Failed to generate test file from template {template_name}: {e}")
            if filename:
                logger.error(f"Target filename: {filename}")
            raise
    
    def add_import(self, import_statement: str):
        """Add import statement to the set of required imports."""
        self.imports.add(import_statement)
    
    def add_fixture(self, fixture_name: str):
        """Add fixture to the set of required fixtures."""
        self.fixtures.add(fixture_name)
    
    def _generate_imports(self) -> List[str]:
        """Generate list of import statements."""
        # Standard test imports
        standard_imports = [
            'import unittest',
            'import pytest',
            'from unittest.mock import Mock, patch, MagicMock',
            'from flask import Flask',
            'from flask_testing import TestCase as FlaskTestCase',
            'import tempfile',
            'import os',
            'import json'
        ]
        
        # Add configuration-specific imports
        if self.config.generate_performance_tests:
            standard_imports.extend([
                'import time',
                'from concurrent.futures import ThreadPoolExecutor'
            ])
        
        if self.config.generate_security_tests:
            standard_imports.extend([
                'import hashlib',
                'import secrets',
                'from werkzeug.security import check_password_hash'
            ])
        
        # Combine with custom imports
        all_imports = standard_imports + list(self.imports)
        return sorted(set(all_imports))
    
    def _generate_fixtures(self) -> List[str]:
        """Generate list of pytest fixtures."""
        # Standard fixtures
        standard_fixtures = [
            '@pytest.fixture\ndef app():\n    """Create test Flask application."""\n    pass',
            '@pytest.fixture\ndef client(app):\n    """Create test client."""\n    return app.test_client()',
            '@pytest.fixture\ndef db():\n    """Create test database."""\n    pass'
        ]
        
        # Add custom fixtures
        all_fixtures = standard_fixtures + list(self.fixtures)
        return all_fixtures
    
    def _get_timestamp(self) -> str:
        """Get current timestamp for generated files."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Utility methods for string manipulation
    def _to_snake_case(self, text: str) -> str:
        """Convert text to snake_case."""
        import re
        # Insert underscores before capitals
        text = re.sub(r'([a-z])([A-Z])', r'\1_\2', text)
        # Convert to lowercase and replace spaces/hyphens with underscores
        return re.sub(r'[\s\-]+', '_', text).lower()
    
    def _to_pascal_case(self, text: str) -> str:
        """Convert text to PascalCase."""
        # Split on underscores, spaces, and hyphens, then capitalize each word
        words = text.replace('_', ' ').replace('-', ' ').split()
        return ''.join(word.capitalize() for word in words)
    
    def _to_camel_case(self, text: str) -> str:
        """Convert text to camelCase."""
        pascal = self._to_pascal_case(text)
        return pascal[0].lower() + pascal[1:] if pascal else ""
    
    def _pluralize(self, word: str) -> str:
        """Simple pluralization (can be enhanced with inflect library)."""
        if word.endswith(('s', 'sh', 'ch', 'x', 'z')):
            return word + 'es'
        elif word.endswith('y') and word[-2] not in 'aeiou':
            return word[:-1] + 'ies'
        elif word.endswith('f'):
            return word[:-1] + 'ves'
        elif word.endswith('fe'):
            return word[:-2] + 'ves'
        else:
            return word + 's'
    
    def _singularize(self, word: str) -> str:
        """Simple singularization."""
        if word.endswith('ies'):
            return word[:-3] + 'y'
        elif word.endswith('ves'):
            if word.endswith('aves'):
                return word[:-3] + 'f'
            else:
                return word[:-3] + 'fe'
        elif word.endswith('ses'):
            return word[:-2]
        elif word.endswith('s') and not word.endswith('ss'):
            return word[:-1]
        else:
            return word
    
    def generate_test_data_setup(self, table_info) -> str:
        """Generate test data setup code for a table."""
        if not hasattr(table_info, 'columns'):
            return "# No table information available"
        
        setup_code = []
        setup_code.append(f"def create_{table_info.name}_test_data():")
        setup_code.append(f'    """Create test data for {table_info.name} table."""')
        
        # Generate sample data based on column types
        for column in table_info.columns:
            if column.primary_key:
                continue
            
            if hasattr(column, 'category'):
                sample_value = self._generate_sample_value_for_column(column)
                setup_code.append(f"    # {column.name}: {sample_value}")
        
        setup_code.append(f"    return test_data")
        
        return '\n'.join(setup_code)
    
    def _generate_sample_value_for_column(self, column) -> str:
        """Generate a sample value for a database column."""
        # This would integrate with the realistic data generator
        if hasattr(column, 'category'):
            if 'string' in str(column.category).lower():
                return f"'test_{column.name}'"
            elif 'integer' in str(column.category).lower():
                return "123"
            elif 'float' in str(column.category).lower():
                return "123.45"
            elif 'boolean' in str(column.category).lower():
                return "True"
            elif 'date' in str(column.category).lower():
                return "datetime.now()"
        
        return "'test_value'"
    
    def generate_assertion_helpers(self) -> str:
        """Generate helper methods for common assertions."""
        return '''
def assert_valid_response(response, expected_status=200):
    """Assert response is valid with expected status."""
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.data is not None

def assert_json_response(response, expected_keys=None):
    """Assert response is valid JSON with expected keys."""
    assert response.content_type == 'application/json'
    data = response.get_json()
    assert data is not None
    
    if expected_keys:
        for key in expected_keys:
            assert key in data

def assert_form_validation_error(response, field_name):
    """Assert form validation error for specific field."""
    assert response.status_code == 400
    # Add specific validation error checking logic
    
def assert_database_record_exists(model_class, **filters):
    """Assert database record exists with given filters."""
    record = model_class.query.filter_by(**filters).first()
    assert record is not None
    return record

def assert_database_record_count(model_class, expected_count, **filters):
    """Assert database record count matches expected."""
    if filters:
        actual_count = model_class.query.filter_by(**filters).count()
    else:
        actual_count = model_class.query.count()
    assert actual_count == expected_count
'''
    
    def generate_mock_helpers(self) -> str:
        """Generate helper methods for mocking."""
        return '''
class MockHelpers:
    """Helper methods for creating mocks and stubs."""
    
    @staticmethod
    def create_mock_user(username="testuser", email="test@example.com", roles=None):
        """Create a mock user object."""
        user = Mock()
        user.username = username
        user.email = email
        user.roles = roles or []
        return user
    
    @staticmethod
    def create_mock_request(method="GET", data=None, json_data=None):
        """Create a mock request object."""
        request = Mock()
        request.method = method
        request.form = data or {}
        request.json = json_data or {}
        return request
    
    @staticmethod
    def create_mock_database_session():
        """Create a mock database session."""
        session = Mock()
        session.query.return_value = session
        session.filter_by.return_value = session
        session.first.return_value = None
        session.all.return_value = []
        session.count.return_value = 0
        return session
'''
    
    def get_common_test_patterns(self) -> Dict[str, str]:
        """Get common test patterns used across different test types."""
        return {
            'crud_pattern': '''
def test_{operation}_{model}(self):
    """Test {operation} operation for {model}."""
    # Arrange
    # Act
    # Assert
    pass
''',
            'validation_pattern': '''
def test_{field}_validation(self):
    """Test validation for {field} field."""
    # Test valid input
    # Test invalid input
    # Assert validation errors
    pass
''',
            'relationship_pattern': '''
def test_{relationship}_relationship(self):
    """Test {relationship} relationship."""
    # Create parent record
    # Create child records
    # Assert relationship is established
    # Test cascade operations
    pass
''',
            'permission_pattern': '''
def test_{action}_permission_required(self):
    """Test that {action} requires proper permissions."""
    # Test without authentication
    # Test with insufficient permissions
    # Test with correct permissions
    pass
'''
        }
    
    def create_test_case(self, name: str, description: str, test_code: str, 
                        **kwargs) -> TestCase:
        """
        Create a TestCase object with the given parameters.
        
        Args:
            name: Test case name
            description: Test case description  
            test_code: Test implementation code
            **kwargs: Additional TestCase parameters
            
        Returns:
            TestCase object
        """
        return TestCase(
            name=name,
            description=description,
            test_type=self.get_generator_type(),
            method_name=f"test_{self._to_snake_case(name)}",
            test_code=test_code,
            **kwargs
        )
    
    def organize_test_cases_by_file(self, test_cases: List[TestCase]) -> Dict[str, List[TestCase]]:
        """
        Organize test cases into logical file groups.
        
        Args:
            test_cases: List of generated test cases
            
        Returns:
            Dictionary mapping file names to test cases
        """
        file_groups = {}
        
        for test_case in test_cases:
            # Group by test type and tags
            file_key = f"{test_case.test_type}_tests"
            
            if test_case.tags:
                # Use first tag as file grouping hint
                file_key = f"{test_case.test_type}_{test_case.tags[0]}_tests"
            
            if file_key not in file_groups:
                file_groups[file_key] = []
            
            file_groups[file_key].append(test_case)
        
        return file_groups