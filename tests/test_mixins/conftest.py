"""
Pytest configuration and fixtures for mixin tests.

Provides shared fixtures, test utilities, and configuration
for comprehensive mixin testing.
"""

import pytest
import json
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch

from flask import Flask
from pgappforge import AppBuilder
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def app():
    """Create Flask application for testing."""
    app = Flask(__name__)
    app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-for-mixins',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'WTF_CSRF_ENABLED': False,
        
        # Mixin-specific configuration
        'ENCRYPTION_KEY': b'test_encryption_key_32_chars_long',
        'MAPQUEST_API_KEY': 'test_mapquest_key',
        'GOOGLE_MAPS_API_KEY': 'test_google_key',
        'GEOCODING_USER_AGENT': 'TestSuite/1.0',
        
        # Cache configuration
        'CACHE_TYPE': 'simple',
        'CACHE_DEFAULT_TIMEOUT': 300,
    })
    
    return app


@pytest.fixture(scope="session")
def appbuilder(app):
    """Create AppBuilder instance for testing."""
    return AppBuilder(app, update_perms=False)


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = Mock()
    session.query.return_value = session
    session.filter.return_value = session
    session.first.return_value = None
    session.all.return_value = []
    session.add.return_value = None
    session.commit.return_value = None
    session.rollback.return_value = None
    session.delete.return_value = None
    return session


@pytest.fixture
def mock_current_user():
    """Mock current user for testing."""
    user = Mock()
    user.id = 123
    user.active = True
    user.email = 'test@example.com'
    user.first_name = 'Test'
    user.last_name = 'User'
    user.roles = [Mock(name='Admin')]
    user.has_permission.return_value = True
    return user


@pytest.fixture
def mock_cache():
    """Mock cache for testing."""
    cache = Mock()
    cache.get.return_value = None
    cache.set.return_value = None
    cache.delete.return_value = None
    return cache


@pytest.fixture
def sample_metadata():
    """Sample metadata for testing."""
    return {
        "category": "test",
        "priority": 5,
        "tags": ["important", "testing"],
        "settings": {
            "auto_approve": False,
            "notify_users": True
        }
    }


@pytest.fixture
def sample_approval_workflow():
    """Sample approval workflow configuration."""
    return {
        1: {
            'required_role': 'reviewer',
            'required_approvals': 1,
            'prevent_self_approval': True,
            'approval_window_hours': 24
        },
        2: {
            'required_role': 'manager', 
            'required_approvals': 2,
            'prevent_self_approval': True,
            'allowed_departments': ['finance', 'operations']
        }
    }


@pytest.fixture
def sample_exchange_rates():
    """Sample exchange rates for currency testing."""
    return {
        'EUR': 0.85,
        'GBP': 0.73,
        'JPY': 110.25,
        'CAD': 1.25,
        'AUD': 1.35
    }


@pytest.fixture
def sample_geocoding_response():
    """Sample geocoding API response."""
    return {
        'nominatim': [{
            'lat': '37.4419',
            'lon': '-122.1430',
            'class': 'place',
            'type': 'house',
            'address': {
                'city': 'Mountain View',
                'state': 'California', 
                'country': 'United States',
                'postcode': '94043'
            }
        }],
        'google': {
            'status': 'OK',
            'results': [{
                'geometry': {
                    'location': {'lat': 37.4419, 'lng': -122.1430},
                    'location_type': 'ROOFTOP'
                },
                'formatted_address': '1600 Amphitheatre Parkway, Mountain View, CA 94043, USA',
                'address_components': [
                    {'long_name': 'Mountain View', 'types': ['locality']},
                    {'long_name': 'California', 'types': ['administrative_area_level_1']},
                    {'long_name': 'United States', 'types': ['country']},
                    {'long_name': '94043', 'types': ['postal_code']}
                ]
            }]
        }
    }


class MockRequestsResponse:
    """Mock requests response for external API testing."""
    
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code
    
    def json(self):
        return self.json_data
    
    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import HTTPError
            raise HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for external API testing."""
    with patch('requests.get') as mock_get:
        yield mock_get


@pytest.fixture 
def mock_security_validator():
    """Mock SecurityValidator for testing."""
    with patch('pgappforge.mixins.security_framework.SecurityValidator') as mock_validator:
        # Setup default validation behavior
        mock_user = Mock()
        mock_user.id = 123
        mock_user.active = True
        mock_validator.validate_user_context.return_value = mock_user
        mock_validator.validate_permission.return_value = True
        yield mock_validator


@pytest.fixture
def mock_security_auditor():
    """Mock SecurityAuditor for testing.""" 
    with patch('pgappforge.mixins.security_framework.SecurityAuditor') as mock_auditor:
        yield mock_auditor


# Test utilities

class TestModelFactory:
    """Factory for creating test models with mixins."""
    
    @staticmethod
    def create_enhanced_soft_delete_model(**kwargs):
        """Create test model with EnhancedSoftDeleteMixin."""
        from pgappforge.mixins.enhanced_mixins import EnhancedSoftDeleteMixin
        from pgappforge import Model
        
        class TestModel(EnhancedSoftDeleteMixin, Model):
            __tablename__ = 'test_soft_delete'
            __soft_delete_cascade__ = kwargs.get('cascade_relations', [])
        
        model = TestModel()
        model.id = kwargs.get('id', 123)
        model.deleted = kwargs.get('deleted', False)
        model.deleted_on = kwargs.get('deleted_on', None)
        model.deleted_by_fk = kwargs.get('deleted_by_fk', None)
        return model
    
    @staticmethod  
    def create_currency_model(**kwargs):
        """Create test model with CurrencyMixin."""
        from pgappforge.mixins.specialized_mixins import CurrencyMixin
        from pgappforge import Model
        
        class TestModel(CurrencyMixin, Model):
            __tablename__ = 'test_currency'
            __default_currency__ = kwargs.get('default_currency', 'USD')
            __exchange_rate_api_url__ = 'https://api.test.com'
            __exchange_rate_api_key__ = 'test_key'
        
        model = TestModel()
        model.id = kwargs.get('id', 123)
        model.amount = kwargs.get('amount', Decimal('100.00'))
        model.currency = kwargs.get('currency', 'USD')
        return model
    
    @staticmethod
    def create_approval_workflow_model(**kwargs):
        """Create test model with ApprovalWorkflowMixin."""
        from pgappforge.mixins.business_mixins import ApprovalWorkflowMixin
        from pgappforge import Model
        
        workflow_config = kwargs.get('approval_workflow', {
            1: {'required_role': 'reviewer', 'required_approvals': 1},
            2: {'required_role': 'manager', 'required_approvals': 1}
        })
        
        class TestModel(ApprovalWorkflowMixin, Model):
            __tablename__ = 'test_approval'
            __approval_workflow__ = workflow_config
        
        model = TestModel()
        model.id = kwargs.get('id', 123)
        model.current_state = kwargs.get('current_state', 'draft')
        model.current_approval_step = kwargs.get('current_approval_step', 1)
        model.received_approvals = kwargs.get('received_approvals', 0)
        model.workflow_data = kwargs.get('workflow_data', '{}')
        return model


# Performance testing utilities

@pytest.fixture
def performance_timer():
    """Timer utility for performance testing."""
    import time
    
    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
        
        def start(self):
            self.start_time = time.time()
        
        def stop(self):
            self.end_time = time.time()
        
        @property
        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None
        
        def assert_under(self, max_seconds):
            assert self.elapsed is not None, "Timer not stopped"
            assert self.elapsed < max_seconds, f"Operation took {self.elapsed:.2f}s, expected < {max_seconds}s"
    
    return Timer()


# Custom pytest markers for test categorization

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "security: marks tests as security-focused"
    )
    config.addinivalue_line(
        "markers", "performance: marks tests as performance-focused"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "external_api: marks tests that use external APIs"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )


# Test data generators

def generate_test_documents(count=10):
    """Generate test documents for bulk testing."""
    documents = []
    for i in range(count):
        doc = {
            'id': i + 1,
            'title': f'Test Document {i + 1}',
            'content': f'This is the content of test document {i + 1}. ' * 10,
            'tags': f'tag{i},test,document',
            'metadata': {
                'category': f'category_{i % 3}',
                'priority': (i % 5) + 1,
                'created_batch': i // 10
            }
        }
        documents.append(doc)
    return documents


def generate_test_locations(count=10):
    """Generate test location data."""
    locations = []
    base_lat, base_lng = 37.4419, -122.1430  # Mountain View, CA
    
    for i in range(count):
        location = {
            'id': i + 1,
            'name': f'Test Location {i + 1}',
            'latitude': base_lat + (i * 0.01),  # Spread out locations
            'longitude': base_lng + (i * 0.01),
            'address': f'{100 + i} Test Street, Test City, TC',
            'amount': Decimal(str(100.00 + i * 10)),
            'currency': ['USD', 'EUR', 'GBP'][i % 3]
        }
        locations.append(location)
    return locations


# Error simulation utilities

class ErrorSimulator:
    """Utility for simulating various error conditions."""
    
    @staticmethod
    def database_error():
        """Simulate database connection error."""
        from sqlalchemy.exc import OperationalError
        raise OperationalError("Database connection failed", None, None)
    
    @staticmethod
    def network_error():
        """Simulate network/API error."""
        import requests
        raise requests.RequestException("Network unreachable")
    
    @staticmethod
    def validation_error():
        """Simulate validation error.""" 
        from pgappforge.mixins.security_framework import MixinValidationError
        raise MixinValidationError("Test validation error", field="test_field")
    
    @staticmethod
    def permission_error():
        """Simulate permission error."""
        from pgappforge.mixins.security_framework import MixinPermissionError
        raise MixinPermissionError("Access denied", user_id=123)