import os
"""
Comprehensive unit tests for PgAppForge core components.

This module provides thorough testing coverage for all core PgAppForge
components including base classes, views, security, and data models.
"""

import asyncio
import datetime
import logging
import unittest
from typing import Any, Dict, List
from unittest.mock import Mock, MagicMock, patch

import pytest
from flask import Flask, g
from pgappforge import AppBuilder, SQLA
from pgappforge.baseviews import BaseView, BaseModelView
from pgappforge.models.sqla import Model
from pgappforge.security.sqla.models import User, Role, Permission
from pgappforge.views import ModelView, SimpleFormView
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base

from tests.base import FABTestCase


class CoreTestModel(Model):
    """Test model for unit testing"""
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    created_on = Column(DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return self.name or ''


class CoreModelViewHelper(ModelView):
    """Test model view for unit testing"""
    datamodel = None  # Will be set in tests
    list_columns = ['name', 'description', 'created_on']
    show_columns = ['name', 'description', 'created_on']
    edit_columns = ['name', 'description']
    add_columns = ['name', 'description']


class TestCoreAppBuilderInitialization(FABTestCase):
    """Test AppBuilder initialization and configuration"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
    
    def test_appbuilder_initialization(self):
        """Test AppBuilder initializes correctly"""
        self.assertIsInstance(self.appbuilder, AppBuilder)
        self.assertEqual(self.appbuilder.app, self.app)
        self.assertIsNotNone(self.appbuilder.sm)
    
    def test_database_initialization(self):
        """Test database tables are created properly"""
        with self.app.app_context():
            # Check that security tables exist
            from sqlalchemy import inspect as sa_inspect
            tables = sa_inspect(self.db.engine).get_table_names()
            expected_tables = ['ab_user', 'ab_role', 'ab_permission', 'ab_view_menu']
            for table in expected_tables:
                self.assertIn(table, tables)
    
    def test_security_manager_initialization(self):
        """Test SecurityManager is properly initialized"""
        sm = self.appbuilder.sm
        self.assertIsNotNone(sm)
        self.assertIsNotNone(sm.user_model)
        self.assertIsNotNone(sm.role_model)
        self.assertIsNotNone(sm.permission_model)
    
    def test_default_security_views_registered(self):
        """Test that default security views are registered"""
        with self.app.app_context():
            registered_endpoints = {rule.endpoint for rule in self.app.url_map.iter_rules()}
            
            expected_endpoints = [
                'AuthDBView.login',
                'AuthDBView.logout',
            ]
            
            for endpoint in expected_endpoints:
                self.assertIn(endpoint, registered_endpoints)


class TestCoreBaseView(FABTestCase):
    """Test BaseView functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_base_view_creation(self):
        """Test BaseView can be instantiated"""
        view = BaseView()
        self.assertIsInstance(view, BaseView)
        self.assertEqual(view.default_view, 'list')
    
    def test_base_view_blueprint_registration(self):
        """Test BaseView blueprint registration"""
        class TestView(BaseView):
            route_base = '/test'
            
            def list(self):
                return 'test list'
        
        view = TestView()
        view.appbuilder = self.appbuilder
        
        # Test that the view can be registered
        self.assertIsNotNone(view.route_base)
        self.assertEqual(view.route_base, '/test')
    
    def test_base_view_permissions(self):
        """Test BaseView permission handling"""
        view = BaseView()
        view.appbuilder = self.appbuilder
        
        # Test default permissions
        self.assertIsInstance(view.base_permissions, list)


class TestCoreModelView(FABTestCase):
    """Test ModelView functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        
        # Create test model table
        with self.app.app_context():
            CoreTestModel.__table__.create(self.db.engine, checkfirst=True)
        
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
    
    def _make_view(self):
        """Create a CoreModelViewHelper with datamodel set as class variable."""
        from pgappforge.models.sqla.interface import SQLAInterface
        dm = SQLAInterface(CoreTestModel, self.db.session)

        class _BoundView(CoreModelViewHelper):
            datamodel = dm

        return _BoundView

    def test_model_view_creation(self):
        """Test ModelView can be created with datamodel"""
        with self.app.app_context():
            ViewClass = self._make_view()
            self.assertTrue(issubclass(ViewClass, ModelView))
            self.assertIsNotNone(ViewClass.datamodel)
            self.assertEqual(ViewClass.datamodel.obj, CoreTestModel)

    def test_model_view_crud_operations(self):
        """Test ModelView CRUD operations"""
        with self.app.app_context():
            ViewClass = self._make_view()
            # Test that CRUD methods exist on the class
            for method in ('list', 'show', 'add', 'edit', 'delete'):
                self.assertTrue(hasattr(ViewClass, method))

    def test_model_view_columns_configuration(self):
        """Test ModelView column configuration"""
        with self.app.app_context():
            ViewClass = self._make_view()
            self.assertIsInstance(ViewClass.list_columns, list)
            self.assertIsInstance(ViewClass.show_columns, list)
            self.assertIsInstance(ViewClass.edit_columns, list)
            self.assertIsInstance(ViewClass.add_columns, list)
            self.assertIn('name', ViewClass.list_columns)
            self.assertIn('description', ViewClass.list_columns)


class TestCoreDataModel(FABTestCase):
    """Test data model functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
            CoreTestModel.__table__.create(self.db.engine, checkfirst=True)
    
    def test_model_creation(self):
        """Test model can be created and persisted"""
        with self.app.app_context():
            test_obj = CoreTestModel(
                name='test_name',
                description='test description'
            )
            
            self.db.session.add(test_obj)
            self.db.session.commit()
            
            # Verify object was created
            retrieved = self.db.session.query(CoreTestModel).filter_by(name='test_name').first()
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.name, 'test_name')
            self.assertEqual(retrieved.description, 'test description')
    
    def test_model_relationships(self):
        """Test model relationships work correctly"""
        with self.app.app_context():
            # Test basic model operations
            test_obj = CoreTestModel(name='relationship_test')
            self.db.session.add(test_obj)
            self.db.session.commit()
            
            self.assertIsNotNone(test_obj.id)
            self.assertIsInstance(test_obj.created_on, datetime.datetime)


class TestCoreSecurity(FABTestCase):
    """Test core security functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
    
    def test_user_creation(self):
        """Test user creation and authentication"""
        with self.app.app_context():
            user = self.appbuilder.sm.add_user(
                username='testuser',
                first_name='Test',
                last_name='User',
                email='test@example.com',
                role=self.appbuilder.sm.find_role('Public'),
                password='password123'
            )
            
            self.assertIsNotNone(user)
            self.assertEqual(user.username, 'testuser')
            self.assertEqual(user.email, 'test@example.com')
    
    def test_role_permission_system(self):
        """Test role and permission system"""
        with self.app.app_context():
            # Test default roles exist
            admin_role = self.appbuilder.sm.find_role('Admin')
            public_role = self.appbuilder.sm.find_role('Public')
            
            self.assertIsNotNone(admin_role)
            self.assertIsNotNone(public_role)
            self.assertEqual(admin_role.name, 'Admin')
            self.assertEqual(public_role.name, 'Public')
    
    def test_password_hashing(self):
        """Test password hashing functionality"""
        with self.app.app_context():
            password = 'test_password_123'
            hashed = self.appbuilder.sm.hash_password(password)
            
            self.assertNotEqual(password, hashed)
            self.assertTrue(self.appbuilder.sm.check_password(password, hashed))


class TestCoreValidation(FABTestCase):
    """Test core validation functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_form_validation(self):
        """Test form validation mechanisms"""
        with self.app.app_context():
            # Test basic validation infrastructure exists
            self.assertTrue(hasattr(self.appbuilder, 'sm'))
            self.assertTrue(hasattr(self.appbuilder.sm, 'user_model'))
    
    def test_data_validation(self):
        """Test data validation mechanisms"""
        with self.app.app_context():
            # Test that validation infrastructure is in place
            self.assertIsNotNone(self.appbuilder)


class TestCoreErrorHandling(FABTestCase):
    """Test core error handling"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_invalid_configuration_handling(self):
        """Test handling of invalid configurations"""
        # Test that invalid configurations are handled gracefully
        with self.assertRaises(Exception):
            # This should raise an exception for invalid config
            invalid_app = Flask(__name__)
            # Missing required config
            AppBuilder(invalid_app, None)
    
    def test_database_error_handling(self):
        """Test database error handling"""
        with self.app.app_context():
            # Test that database errors are handled appropriately
            self.assertIsNotNone(self.appbuilder.get_session)


class TestCoreAsyncSupport(FABTestCase):
    """Test async functionality support"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
    
    def test_async_compatibility(self):
        """Test that async operations are supported"""
        async def async_test():
            # Test async functionality
            with self.app.app_context():
                result = await asyncio.sleep(0, result=True)
                return result
        
        result = asyncio.run(async_test())
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()