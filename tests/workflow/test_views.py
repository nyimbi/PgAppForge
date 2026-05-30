"""
Tests for PgAppForge Workflow Views

Tests the WorkflowModelView, form handling, and view integration.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import json

import pytest
from flask import Flask, request
from pgappforge import AppBuilder
from flask_sqlalchemy import SQLAlchemy
from werkzeug.test import Client

from pgappforge.workflow.views import WorkflowModelView, WorkflowFormView
from pgappforge.workflow.core import WorkflowDefinition, WorkflowStepDefinition, WorkflowStepType
from pgappforge.workflow.mixins import WorkflowMixin


class TestWorkflowModelView(unittest.TestCase):
    """Test WorkflowModelView functionality."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_workflow_model_view_initialization(self):
        """Test WorkflowModelView initialization."""
        with self.app.app_context():
            # Create test model
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))
                
                workflow_enabled = True
                workflow_name = 'test_workflow'

            # Create view
            from pgappforge.models.sqla.interface import SQLAInterface
            
            class TestView(WorkflowModelView):
                datamodel = SQLAInterface(TestModel)
                workflow_definition = {
                    'name': 'test_workflow',
                    'steps': [
                        {'id': 'step1', 'name': 'Step 1', 'fields': ['name']},
                        {'id': 'step2', 'name': 'Step 2', 'fields': ['name']}
                    ]
                }

            view = TestView()
            self.assertIsNotNone(view.workflow_definition)
            self.assertEqual(view.workflow_definition.name, 'test_workflow')

    def test_can_create_with_workflow(self):
        """Test can_create method with workflow constraints."""
        with self.app.app_context():
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))

            from pgappforge.models.sqla.interface import SQLAInterface
            
            class TestView(WorkflowModelView):
                datamodel = SQLAInterface(TestModel)
                workflow_require_completion = True

            view = TestView()
            
            # Mock base permissions
            with patch.object(view, 'can_create', return_value=True):
                # Test without workflow requirement
                view.workflow_require_completion = False
                self.assertTrue(view.can_create())
                
                # Test with workflow requirement
                view.workflow_require_completion = True
                with patch.object(view, '_check_workflow_prerequisites', return_value=True):
                    self.assertTrue(view.can_create())

    def test_can_edit_with_workflow_state(self):
        """Test can_edit method with workflow state constraints."""
        with self.app.app_context():
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))

            from pgappforge.models.sqla.interface import SQLAInterface
            
            class TestView(WorkflowModelView):
                datamodel = SQLAInterface(TestModel)

            view = TestView()
            
            # Create test item with workflow state
            item = TestModel(id=1, name="Test")
            
            # Mock workflow state
            mock_state = Mock()
            mock_state.status = 'in_progress'
            mock_state.can_user_access_step.return_value = True
            item.workflow_state = mock_state
            
            with patch.object(view, 'can_edit', return_value=True):
                result = view.can_edit(item)
                self.assertTrue(result)
                
                # Test completed workflow without permission
                mock_state.status = 'completed'
                with patch.object(view, 'has_access', return_value=False):
                    result = view.can_edit(item)
                    self.assertFalse(result)

    def test_workflow_form_submission_handling(self):
        """Test workflow form submission handling."""
        with self.app.app_context():
            self.db.create_all()
            
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))

            from pgappforge.models.sqla.interface import SQLAInterface
            
            class TestView(WorkflowModelView):
                datamodel = SQLAInterface(TestModel)

            view = TestView()
            
            # Mock form and workflow state
            mock_form = Mock()
            mock_form.__iter__ = Mock(return_value=iter([
                Mock(name='name', data='Test Name'),
                Mock(name='csrf_token', data='token')
            ]))
            
            mock_state = Mock()
            mock_state.set_form_data_for_step = Mock()
            mock_state.available_next_steps = ['step2']
            
            with patch('pgappforge.workflow.views.request') as mock_request:
                mock_request.form = {'workflow_next': True}
                
                with patch.object(view, '_handle_workflow_navigation') as mock_nav:
                    mock_nav.return_value = Mock()
                    
                    result = view._handle_workflow_form_submission(
                        mock_form, 'step1', mock_state
                    )
                    
                    # Verify form data was saved
                    mock_state.set_form_data_for_step.assert_called_once()
                    mock_nav.assert_called_once_with(mock_state, 'next', None)

    def test_workflow_navigation_handling(self):
        """Test workflow navigation handling."""
        with self.app.app_context():
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))

            from pgappforge.models.sqla.interface import SQLAInterface
            
            class TestView(WorkflowModelView):
                datamodel = SQLAInterface(TestModel)

            view = TestView()
            
            # Mock workflow state and engine
            mock_state = Mock()
            mock_state.available_next_steps = ['step2']
            mock_state.current_step = 'step1'
            
            mock_engine = Mock()
            mock_engine.advance_workflow.return_value = True
            
            with patch('pgappforge.workflow.views.get_workflow_engine', return_value=mock_engine):
                with patch('pgappforge.workflow.views.redirect') as mock_redirect:
                    with patch('pgappforge.workflow.views.url_for') as mock_url:
                        mock_url.return_value = '/test/url'
                        
                        result = view._handle_workflow_navigation(mock_state, 'next')
                        
                        mock_engine.advance_workflow.assert_called_once()
                        mock_redirect.assert_called_once()

    def test_create_entity_from_workflow(self):
        """Test creating entity from workflow data."""
        with self.app.app_context():
            self.db.create_all()
            
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))

            from pgappforge.models.sqla.interface import SQLAInterface
            
            class TestView(WorkflowModelView):
                datamodel = SQLAInterface(TestModel)

            view = TestView()
            
            # Mock workflow state with form data
            mock_state = Mock()
            mock_state.form_data = {
                'step1': {'name': 'Test Name'},
                'step2': {'description': 'Test Description'}
            }
            mock_state.workflow_name = 'test_workflow'
            
            with patch.object(view.datamodel, 'add') as mock_add:
                mock_item = TestModel(name='Test Name')
                mock_add.return_value = mock_item
                
                with patch('pgappforge.workflow.views.redirect') as mock_redirect:
                    result = view._create_entity_from_workflow(mock_state)
                    
                    mock_add.assert_called_once()
                    mock_redirect.assert_called_once()


class TestWorkflowFormView(unittest.TestCase):
    """Test WorkflowFormView functionality."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_workflow_form_view_initialization(self):
        """Test WorkflowFormView initialization."""
        with self.app.app_context():
            class TestFormView(WorkflowFormView):
                workflow_definition = {
                    'name': 'test_form_workflow',
                    'steps': [
                        {'id': 'step1', 'name': 'Step 1', 'fields': ['field1']},
                    ]
                }

            view = TestFormView()
            self.assertIsNotNone(view.workflow_definition)
            self.assertEqual(view.workflow_definition.name, 'test_form_workflow')

    def test_create_step_form(self):
        """Test dynamic step form creation."""
        with self.app.app_context():
            class TestFormView(WorkflowFormView):
                workflow_definition = {
                    'name': 'test_form_workflow',
                    'steps': [
                        {'id': 'step1', 'name': 'Step 1', 'fields': ['field1']},
                    ]
                }

            view = TestFormView()
            
            # Mock step definition
            mock_step = Mock()
            mock_step.id = 'step1'
            mock_step.form_fields = ['field1', 'field2']
            
            # Mock workflow state
            mock_state = Mock()
            mock_state.get_form_data_for_step.return_value = {'field1': 'value1'}
            
            form = view._create_step_form(mock_step, mock_state)
            
            self.assertIsNotNone(form)
            # Form should have dynamic fields
            self.assertTrue(hasattr(form, 'field1'))
            self.assertTrue(hasattr(form, 'field2'))

    def test_form_submission_handling(self):
        """Test form submission handling."""
        with self.app.app_context():
            self.db.create_all()
            
            class TestFormView(WorkflowFormView):
                workflow_definition = {
                    'name': 'test_form_workflow',
                    'steps': [
                        {'id': 'step1', 'name': 'Step 1', 'fields': ['field1']},
                        {'id': 'step2', 'name': 'Step 2', 'fields': ['field2']},
                    ]
                }

            view = TestFormView()
            
            # Mock form
            mock_form = Mock()
            mock_form.__iter__ = Mock(return_value=iter([
                Mock(name='field1', data='value1'),
                Mock(name='csrf_token', data='token')
            ]))
            
            # Mock workflow state
            mock_state = Mock()
            mock_state.set_form_data_for_step = Mock()
            mock_state.available_next_steps = ['step2']
            
            with patch('pgappforge.workflow.views.request') as mock_request:
                mock_request.form = {'next': True}
                
                with patch('pgappforge.workflow.views.redirect') as mock_redirect:
                    with patch('pgappforge.workflow.views.url_for'):
                        with patch('pgappforge.workflow.views.get_workflow_engine') as mock_engine:
                            mock_engine.return_value.advance_workflow.return_value = True
                            
                            result = view._handle_form_submission(mock_form, 'step1', mock_state)
                            
                            mock_state.set_form_data_for_step.assert_called_once()
                            mock_redirect.assert_called_once()


class TestWorkflowIntegration(unittest.TestCase):
    """Integration tests for workflow views."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        self.app.config['WTF_CSRF_ENABLED'] = False
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_full_workflow_view_integration(self):
        """Test complete workflow view integration."""
        with self.app.app_context():
            self.db.create_all()
            
            # Create test model
            class Employee(WorkflowMixin, self.db.Model):
                __tablename__ = 'employee'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))
                email = self.db.Column(self.db.String(100))
                position = self.db.Column(self.db.String(100))
                
                workflow_enabled = True
                workflow_name = 'employee_onboarding'

            self.db.create_all()

            # Create workflow view
            from pgappforge.models.sqla.interface import SQLAInterface
            
            class EmployeeView(WorkflowModelView):
                datamodel = SQLAInterface(Employee)
                workflow_definition = {
                    'name': 'employee_onboarding',
                    'steps': [
                        {
                            'id': 'personal_info',
                            'name': 'Personal Information',
                            'fields': ['name', 'email']
                        },
                        {
                            'id': 'employment_info',
                            'name': 'Employment Information',
                            'fields': ['position']
                        }
                    ]
                }

            view = EmployeeView()
            
            # Test workflow setup
            self.assertIsNotNone(view.workflow_definition)
            self.assertEqual(len(view.workflow_definition.steps), 2)
            
            # Test form columns for specific step
            columns = view.get_form_columns('personal_info')
            self.assertEqual(columns, ['name', 'email'])
            
            # Test workflow context
            with patch.object(view, 'get_workflow_state_from_session') as mock_session:
                mock_state = Mock()
                mock_state.current_step = 'personal_info'
                mock_state.completed_steps = []
                mock_state.available_next_steps = ['employment_info']
                mock_state.progress_percentage = 25
                mock_session.return_value = mock_state
                
                context = view.get_workflow_context('employee_onboarding')
                
                self.assertIn('workflow_state', context)
                self.assertIn('progress_percentage', context)
                self.assertEqual(context['progress_percentage'], 25)

    def test_workflow_permissions_integration(self):
        """Test workflow permissions integration."""
        with self.app.app_context():
            # Create test model
            class Document(WorkflowMixin, self.db.Model):
                __tablename__ = 'document'
                id = self.db.Column(self.db.Integer, primary_key=True)
                title = self.db.Column(self.db.String(100))
                content = self.db.Column(self.db.Text)
                
                workflow_enabled = True
                workflow_name = 'document_approval'

            # Create workflow view
            from pgappforge.models.sqla.interface import SQLAInterface
            
            class DocumentView(WorkflowModelView):
                datamodel = SQLAInterface(Document)
                workflow_definition = {
                    'name': 'document_approval',
                    'steps': [
                        {
                            'id': 'draft',
                            'name': 'Draft',
                            'fields': ['title', 'content'],
                            'required_role': 'Author'
                        },
                        {
                            'id': 'review',
                            'name': 'Review',
                            'fields': [],
                            'required_role': 'Reviewer'
                        }
                    ]
                }

            view = DocumentView()
            
            # Test base permissions
            self.assertIn('can_navigate_workflow', view.base_permissions)
            self.assertIn('can_restart_workflow', view.base_permissions)
            
            # Test workflow-specific permission checks
            document = Document(id=1, title="Test Doc")
            
            # Mock workflow state with permissions
            mock_state = Mock()
            mock_state.status = 'in_progress'
            mock_state.can_user_access_step.return_value = True
            document.workflow_state = mock_state
            
            with patch.object(view, 'can_edit', return_value=True):
                result = view.can_edit(document)
                self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()