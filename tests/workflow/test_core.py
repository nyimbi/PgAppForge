"""
Tests for PgAppForge Workflow Core System

Tests the core workflow engine, state management, and form sequencing functionality.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest
from flask import Flask
from pgappforge import AppBuilder
from flask_sqlalchemy import SQLAlchemy

from pgappforge.workflow.core import (
    WorkflowEngine, WorkflowDefinition, WorkflowStepDefinition, WorkflowStepType,
    WorkflowState, get_workflow_engine
)
from pgappforge.workflow.forms import WorkflowFormSequence, FormOrchestrator
from pgappforge.workflow.mixins import WorkflowMixin


class TestWorkflowDefinition(unittest.TestCase):
    """Test WorkflowDefinition class."""

    def setUp(self):
        self.step1 = WorkflowStepDefinition(
            id="step_1",
            name="Personal Info",
            step_type=WorkflowStepType.FORM,
            form_fields=["name", "email"]
        )
        self.step2 = WorkflowStepDefinition(
            id="step_2",
            name="Employment",
            step_type=WorkflowStepType.FORM,
            form_fields=["position", "department"]
        )

    def test_workflow_definition_creation(self):
        """Test WorkflowDefinition creation."""
        workflow = WorkflowDefinition(
            name="test_workflow",
            description="Test workflow",
            version="1.0",
            steps=[self.step1, self.step2]
        )
        
        self.assertEqual(workflow.name, "test_workflow")
        self.assertEqual(len(workflow.steps), 2)
        self.assertEqual(workflow.steps[0].id, "step_1")

    def test_get_step_by_id(self):
        """Test getting step by ID."""
        workflow = WorkflowDefinition(
            name="test_workflow",
            steps=[self.step1, self.step2]
        )
        
        step = workflow.get_step_by_id("step_1")
        self.assertIsNotNone(step)
        self.assertEqual(step.name, "Personal Info")
        
        # Test non-existent step
        step = workflow.get_step_by_id("nonexistent")
        self.assertIsNone(step)

    def test_get_next_steps(self):
        """Test getting next steps."""
        self.step1.next_steps = ["step_2"]
        workflow = WorkflowDefinition(
            name="test_workflow",
            steps=[self.step1, self.step2]
        )
        
        next_steps = workflow.get_next_steps("step_1")
        self.assertEqual(len(next_steps), 1)
        self.assertEqual(next_steps[0], "step_2")


class TestWorkflowState(unittest.TestCase):
    """Test WorkflowState class."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_workflow_state_creation(self):
        """Test WorkflowState creation."""
        with self.app.app_context():
            state = WorkflowState(
                workflow_name="test_workflow",
                current_step="step_1",
                entity_type="TestEntity",
                entity_id=1
            )
            
            self.assertEqual(state.workflow_name, "test_workflow")
            self.assertEqual(state.current_step, "step_1")
            self.assertEqual(state.status, "not_started")

    def test_form_data_management(self):
        """Test form data management."""
        with self.app.app_context():
            state = WorkflowState(
                workflow_name="test_workflow",
                current_step="step_1"
            )
            
            # Test setting form data
            form_data = {"name": "John Doe", "email": "john@example.com"}
            state.set_form_data_for_step("step_1", form_data)
            
            # Test getting form data
            retrieved_data = state.get_form_data_for_step("step_1")
            self.assertEqual(retrieved_data, form_data)
            
            # Test non-existent step
            empty_data = state.get_form_data_for_step("nonexistent")
            self.assertEqual(empty_data, {})

    def test_progress_percentage(self):
        """Test progress percentage calculation."""
        with self.app.app_context():
            state = WorkflowState(
                workflow_name="test_workflow",
                current_step="step_2",
                completed_steps=["step_1"]
            )
            
            # Mock workflow definition with 3 steps
            with patch('pgappforge.workflow.core.get_workflow_engine') as mock_engine:
                mock_workflow = Mock()
                mock_workflow.steps = [Mock(id=f"step_{i}") for i in range(1, 4)]
                mock_engine.return_value.workflow_definitions = {"test_workflow": mock_workflow}
                
                progress = state.progress_percentage
                # 1 completed step out of 3 = 33%
                self.assertEqual(progress, 33)

    def test_history_management(self):
        """Test workflow history management."""
        with self.app.app_context():
            state = WorkflowState(
                workflow_name="test_workflow",
                current_step="step_1"
            )
            
            # Add history entry
            state.add_to_history("step_1", "started", {"user": "test_user"})
            
            self.assertIsNotNone(state.history)
            self.assertEqual(len(state.history), 1)
            self.assertEqual(state.history[0]["step_id"], "step_1")
            self.assertEqual(state.history[0]["action"], "started")


class TestWorkflowEngine(unittest.TestCase):
    """Test WorkflowEngine class."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)
            self.engine = WorkflowEngine()

    def test_register_workflow(self):
        """Test workflow registration."""
        with self.app.app_context():
            step = WorkflowStepDefinition(
                id="step_1",
                name="Test Step",
                step_type=WorkflowStepType.FORM
            )
            workflow = WorkflowDefinition(
                name="test_workflow",
                steps=[step]
            )
            
            self.engine.register_workflow(workflow)
            
            self.assertIn("test_workflow", self.engine.workflow_definitions)
            retrieved = self.engine.workflow_definitions["test_workflow"]
            self.assertEqual(retrieved.name, "test_workflow")

    def test_create_workflow_state(self):
        """Test workflow state creation."""
        with self.app.app_context():
            # Setup database tables
            self.db.create_all()
            
            step = WorkflowStepDefinition(
                id="step_1",
                name="Test Step",
                step_type=WorkflowStepType.FORM
            )
            workflow = WorkflowDefinition(
                name="test_workflow",
                steps=[step]
            )
            self.engine.register_workflow(workflow)
            
            # Create workflow state
            state = self.engine.create_workflow_state(
                workflow_name="test_workflow",
                entity_type="TestEntity",
                entity_id=1
            )
            
            self.assertIsNotNone(state)
            self.assertEqual(state.workflow_name, "test_workflow")
            self.assertEqual(state.current_step, "step_1")

    def test_advance_workflow(self):
        """Test workflow advancement."""
        with self.app.app_context():
            self.db.create_all()
            
            # Create workflow with two steps
            step1 = WorkflowStepDefinition(
                id="step_1",
                name="Step 1",
                step_type=WorkflowStepType.FORM,
                next_steps=["step_2"]
            )
            step2 = WorkflowStepDefinition(
                id="step_2",
                name="Step 2",
                step_type=WorkflowStepType.FORM
            )
            workflow = WorkflowDefinition(
                name="test_workflow",
                steps=[step1, step2]
            )
            self.engine.register_workflow(workflow)
            
            # Create and advance workflow state
            state = self.engine.create_workflow_state(
                workflow_name="test_workflow",
                entity_type="TestEntity"
            )
            
            success = self.engine.advance_workflow(state, "step_2")
            
            self.assertTrue(success)
            self.assertEqual(state.current_step, "step_2")
            self.assertIn("step_1", state.completed_steps)

    def test_validate_step_transition(self):
        """Test step transition validation."""
        with self.app.app_context():
            step1 = WorkflowStepDefinition(
                id="step_1",
                name="Step 1",
                next_steps=["step_2"]
            )
            step2 = WorkflowStepDefinition(
                id="step_2",
                name="Step 2"
            )
            
            state = WorkflowState(
                workflow_name="test_workflow",
                current_step="step_1"
            )
            
            # Valid transition
            valid = self.engine._validate_step_transition(state, step1, step2)
            self.assertTrue(valid)
            
            # Test with conditions
            step1.conditions = {"field": "approved", "value": True}
            form_data = {"approved": True}
            
            valid = self.engine._validate_step_transition(state, step1, step2, form_data)
            self.assertTrue(valid)
            
            # Invalid condition
            form_data = {"approved": False}
            valid = self.engine._validate_step_transition(state, step1, step2, form_data)
            self.assertFalse(valid)


class TestWorkflowFormSequence(unittest.TestCase):
    """Test WorkflowFormSequence class."""

    def setUp(self):
        from pgappforge.workflow.forms import FieldDefinition, FormStepDefinition
        
        self.field1 = FieldDefinition(
            name="name",
            field_type="string",
            required=True
        )
        self.field2 = FieldDefinition(
            name="email",
            field_type="string",
            validators=["email"]
        )
        
        self.step1 = FormStepDefinition(
            id="step_1",
            name="Personal Info",
            fields=[self.field1, self.field2]
        )
        
        self.sequence = WorkflowFormSequence(
            sequence_name="test_sequence",
            steps=[self.step1]
        )

    def test_form_sequence_creation(self):
        """Test form sequence creation."""
        self.assertEqual(self.sequence.sequence_name, "test_sequence")
        self.assertEqual(len(self.sequence.steps), 1)
        self.assertIn("step_1", self.sequence.steps)

    def test_get_step(self):
        """Test getting step from sequence."""
        step = self.sequence.get_step("step_1")
        self.assertIsNotNone(step)
        self.assertEqual(step.name, "Personal Info")
        
        # Test non-existent step
        step = self.sequence.get_step("nonexistent")
        self.assertIsNone(step)

    def test_get_step_ids(self):
        """Test getting step IDs."""
        step_ids = self.sequence.get_step_ids()
        self.assertEqual(step_ids, ["step_1"])

    def test_form_creation(self):
        """Test dynamic form creation."""
        form = self.sequence.create_form_for_step("step_1")
        self.assertIsNotNone(form)
        
        # Check form fields
        self.assertTrue(hasattr(form, "name"))
        self.assertTrue(hasattr(form, "email"))


class TestWorkflowMixin(unittest.TestCase):
    """Test WorkflowMixin functionality."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_workflow_mixin_properties(self):
        """Test WorkflowMixin properties."""
        with self.app.app_context():
            # Create test model
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))
                
                workflow_enabled = True
                workflow_name = 'test_workflow'
            
            self.db.create_all()
            
            model = TestModel(name="Test")
            
            # Test properties
            self.assertFalse(model.is_workflow_active)
            self.assertEqual(model.workflow_progress_percentage, 0)

    def test_start_workflow(self):
        """Test starting workflow from mixin."""
        with self.app.app_context():
            class TestModel(WorkflowMixin, self.db.Model):
                __tablename__ = 'test_model'
                id = self.db.Column(self.db.Integer, primary_key=True)
                name = self.db.Column(self.db.String(100))
                
                workflow_enabled = True
                workflow_name = 'test_workflow'
            
            self.db.create_all()
            
            # Mock workflow engine
            with patch('pgappforge.workflow.mixins.get_workflow_engine') as mock_engine:
                mock_state = Mock()
                mock_state.id = "test_state_id"
                mock_engine.return_value.create_workflow_state.return_value = mock_state
                
                model = TestModel(name="Test", id=1)
                
                # Start workflow
                workflow_state = model.start_workflow()
                
                self.assertIsNotNone(workflow_state)
                self.assertEqual(model.workflow_state_id, "test_state_id")
                self.assertEqual(model.workflow_status, "in_progress")


class TestIntegration(unittest.TestCase):
    """Integration tests for workflow system."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        
        with self.app.app_context():
            self.db = SQLAlchemy(self.app)
            self.appbuilder = AppBuilder(self.app, self.db.session)

    def test_complete_workflow_lifecycle(self):
        """Test complete workflow lifecycle."""
        with self.app.app_context():
            self.db.create_all()
            
            # Create workflow definition
            step1 = WorkflowStepDefinition(
                id="personal_info",
                name="Personal Information",
                step_type=WorkflowStepType.FORM,
                form_fields=["name", "email"],
                next_steps=["employment_info"]
            )
            step2 = WorkflowStepDefinition(
                id="employment_info",
                name="Employment Information", 
                step_type=WorkflowStepType.FORM,
                form_fields=["position", "department"]
            )
            
            workflow = WorkflowDefinition(
                name="employee_onboarding",
                description="Employee onboarding workflow",
                steps=[step1, step2]
            )
            
            # Register workflow
            engine = get_workflow_engine()
            engine.register_workflow(workflow)
            
            # Create workflow state
            state = engine.create_workflow_state(
                workflow_name="employee_onboarding",
                entity_type="Employee",
                entity_id=1
            )
            
            self.assertEqual(state.current_step, "personal_info")
            self.assertEqual(state.status, "in_progress")
            
            # Add form data and advance
            form_data = {"name": "John Doe", "email": "john@example.com"}
            state.set_form_data_for_step("personal_info", form_data)
            
            success = engine.advance_workflow(state, "employment_info", form_data)
            
            self.assertTrue(success)
            self.assertEqual(state.current_step, "employment_info")
            self.assertIn("personal_info", state.completed_steps)
            
            # Complete workflow
            employment_data = {"position": "Developer", "department": "IT"}
            state.set_form_data_for_step("employment_info", employment_data)
            
            # Mark as completed
            state.status = "completed"
            state.completed_at = datetime.utcnow()
            
            self.assertEqual(state.status, "completed")
            self.assertIsNotNone(state.completed_at)

    def test_form_orchestrator_integration(self):
        """Test form orchestrator integration."""
        with self.app.app_context():
            self.db.create_all()
            
            from pgappforge.workflow.forms import (
                FieldDefinition, FormStepDefinition, FormOrchestrator
            )
            
            # Create form sequence
            field1 = FieldDefinition(name="name", field_type="string", required=True)
            field2 = FieldDefinition(name="email", field_type="string", validators=["email"])
            
            step = FormStepDefinition(
                id="info_step",
                name="Information",
                fields=[field1, field2]
            )
            
            sequence = WorkflowFormSequence("test_sequence", [step])
            
            # Test orchestrator
            orchestrator = FormOrchestrator()
            orchestrator.register_sequence(sequence)
            
            # Create workflow state
            state = WorkflowState(
                workflow_name="test_sequence",
                current_step="info_step"
            )
            
            # Create form
            form = orchestrator.create_form_for_workflow_step(state)
            self.assertIsNotNone(form)


if __name__ == '__main__':
    unittest.main()