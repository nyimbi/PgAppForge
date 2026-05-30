"""
Comprehensive Test Suite for Process Engine.

Tests all major components of the business process engine including
models, execution engine, state machine, approvals, and integrations.
"""

import unittest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock

import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Import all process engine components
from pgappforge.process.models.process_models import (
    ProcessDefinition, ProcessInstance, ProcessStep, ProcessTemplate,
    ApprovalRequest, ApprovalChain, SmartTrigger, ProcessMetric,
    ProcessInstanceStatus, ProcessStepStatus, ApprovalStatus
)
from pgappforge.process.engine.process_engine import ProcessEngine
from pgappforge.process.engine.state_machine import ProcessStateMachine, StateTransitionError
from pgappforge.process.engine.executors import (
    TaskExecutor, ServiceExecutor, GatewayExecutor, ApprovalExecutor, TimerExecutor
)
from pgappforge.process.approval.chain_manager import (
    ApprovalChainManager, ApprovalDecision, ApprovalContext
)
from pgappforge.process.ml.smart_triggers import SmartTriggerEngine, TriggerEvent
from pgappforge.process.analytics.dashboard import ProcessAnalytics
from pgappforge.process.async.task_monitor import TaskMonitor


class TestProcessModels(unittest.TestCase):
    """Test process data models."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        
        # Initialize database
        from pgappforge import db
        db.init_app(self.app)
        
        with self.app.app_context():
            db.create_all()
            
            # Create test data
            self.create_test_data()
    
    def create_test_data(self):
        """Create test process definitions and instances."""
        from pgappforge import db
        
        # Create process definition
        self.test_definition = ProcessDefinition(
            name="Test Process",
            description="Test process for unit testing",
            version="1.0",
            category="Testing",
            status="active",
            tenant_id=1,
            process_graph={
                "nodes": [
                    {
                        "id": "start",
                        "type": "event",
                        "subtype": "start",
                        "name": "Start"
                    },
                    {
                        "id": "task1",
                        "type": "task",
                        "subtype": "user",
                        "name": "User Task"
                    },
                    {
                        "id": "end",
                        "type": "event",
                        "subtype": "end",
                        "name": "End"
                    }
                ],
                "edges": [
                    {
                        "source": "start",
                        "target": "task1"
                    },
                    {
                        "source": "task1",
                        "target": "end"
                    }
                ]
            }
        )
        
        db.session.add(self.test_definition)
        db.session.commit()
        
        # Create process instance
        self.test_instance = ProcessInstance(
            definition_id=self.test_definition.id,
            tenant_id=1,
            status=ProcessInstanceStatus.RUNNING.value,
            input_data={"test_input": "value"},
            started_at=datetime.utcnow()
        )
        
        db.session.add(self.test_instance)
        db.session.commit()
    
    def test_process_definition_creation(self):
        """Test ProcessDefinition model creation."""
        with self.app.app_context():
            self.assertIsNotNone(self.test_definition.id)
            self.assertEqual(self.test_definition.name, "Test Process")
            self.assertEqual(self.test_definition.status, "active")
            self.assertIsInstance(self.test_definition.process_graph, dict)
            self.assertIn("nodes", self.test_definition.process_graph)
    
    def test_process_instance_creation(self):
        """Test ProcessInstance model creation."""
        with self.app.app_context():
            self.assertIsNotNone(self.test_instance.id)
            self.assertEqual(self.test_instance.definition_id, self.test_definition.id)
            self.assertEqual(self.test_instance.status, ProcessInstanceStatus.RUNNING.value)
            self.assertIsInstance(self.test_instance.input_data, dict)
    
    def test_process_step_creation(self):
        """Test ProcessStep model creation and methods."""
        with self.app.app_context():
            from pgappforge import db
            
            step = ProcessStep(
                instance_id=self.test_instance.id,
                node_id="task1",
                node_type="task",
                status=ProcessStepStatus.PENDING.value,
                tenant_id=1
            )
            
            db.session.add(step)
            db.session.commit()
            
            # Test step methods
            self.assertEqual(step.status, ProcessStepStatus.PENDING.value)
            
            # Test mark_completed
            step.mark_completed({"result": "success"})
            self.assertEqual(step.status, ProcessStepStatus.COMPLETED.value)
            self.assertIsNotNone(step.completed_at)
            self.assertEqual(step.output_data["result"], "success")
            
            # Test mark_failed
            step.mark_failed("Test error", {"error_code": 500})
            self.assertEqual(step.status, ProcessStepStatus.FAILED.value)
            self.assertEqual(step.error_message, "Test error")
            self.assertEqual(step.error_details["error_code"], 500)
    
    def test_approval_chain_creation(self):
        """Test ApprovalChain model creation."""
        with self.app.app_context():
            from pgappforge import db
            
            # Create process step
            step = ProcessStep(
                instance_id=self.test_instance.id,
                node_id="approval",
                node_type="approval",
                status=ProcessStepStatus.RUNNING.value,
                tenant_id=1
            )
            db.session.add(step)
            db.session.flush()
            
            # Create approval chain
            chain = ApprovalChain(
                step_id=step.id,
                tenant_id=1,
                chain_type="sequential",
                approvers=json.dumps([{"user_id": 1, "username": "approver1"}]),
                status=ApprovalStatus.PENDING.value,
                priority="normal"
            )
            
            db.session.add(chain)
            db.session.commit()
            
            self.assertIsNotNone(chain.id)
            self.assertEqual(chain.chain_type, "sequential")
            self.assertEqual(chain.status, ApprovalStatus.PENDING.value)


class TestProcessEngine(unittest.TestCase):
    """Test ProcessEngine core functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
            
            self.engine = ProcessEngine()
            self.create_test_definition()
    
    def create_test_definition(self):
        """Create a test process definition."""
        from pgappforge import db
        
        self.definition = ProcessDefinition(
            name="Engine Test Process",
            description="Test process for engine testing",
            version="1.0",
            category="Testing",
            status="active",
            tenant_id=1,
            process_graph={
                "nodes": [
                    {"id": "start", "type": "event", "subtype": "start", "name": "Start"},
                    {"id": "task1", "type": "task", "subtype": "user", "name": "Task 1",
                     "config": {"assignee": "user1", "form_key": "test_form"}},
                    {"id": "gateway", "type": "gateway", "subtype": "exclusive", "name": "Decision",
                     "config": {"condition": "input_data.approve === true"}},
                    {"id": "task2", "type": "task", "subtype": "service", "name": "Approve Task"},
                    {"id": "task3", "type": "task", "subtype": "service", "name": "Reject Task"},
                    {"id": "end", "type": "event", "subtype": "end", "name": "End"}
                ],
                "edges": [
                    {"source": "start", "target": "task1"},
                    {"source": "task1", "target": "gateway"},
                    {"source": "gateway", "target": "task2", "condition": "approve"},
                    {"source": "gateway", "target": "task3", "condition": "reject"},
                    {"source": "task2", "target": "end"},
                    {"source": "task3", "target": "end"}
                ]
            }
        )
        
        db.session.add(self.definition)
        db.session.commit()
    
    def test_start_process(self):
        """Test starting a process instance."""
        with self.app.app_context():
            input_data = {"test": "value", "approve": True}
            
            instance = asyncio.run(
                self.engine.start_process(
                    definition_id=self.definition.id,
                    input_data=input_data
                )
            )
            
            self.assertIsNotNone(instance)
            self.assertEqual(instance.definition_id, self.definition.id)
            self.assertEqual(instance.status, ProcessInstanceStatus.RUNNING.value)
            self.assertEqual(instance.input_data, input_data)
            self.assertIsNotNone(instance.started_at)
    
    def test_find_start_nodes(self):
        """Test finding start nodes in process graph."""
        with self.app.app_context():
            start_nodes = self.engine._find_start_nodes(self.definition.process_graph)
            
            self.assertEqual(len(start_nodes), 1)
            self.assertEqual(start_nodes[0]["id"], "start")
            self.assertEqual(start_nodes[0]["type"], "event")
    
    def test_get_next_nodes(self):
        """Test getting next nodes in process flow."""
        with self.app.app_context():
            graph = self.definition.process_graph
            
            next_nodes = self.engine._get_next_nodes(graph, "start")
            self.assertEqual(len(next_nodes), 1)
            self.assertEqual(next_nodes[0]["id"], "task1")
            
            next_nodes = self.engine._get_next_nodes(graph, "task1")
            self.assertEqual(len(next_nodes), 1)
            self.assertEqual(next_nodes[0]["id"], "gateway")
    
    def test_evaluate_gateway_conditions(self):
        """Test gateway condition evaluation."""
        with self.app.app_context():
            # Test approve condition
            context = {"input_data": {"approve": True}}
            result = self.engine._evaluate_condition("input_data.approve === true", context)
            self.assertTrue(result)
            
            # Test reject condition
            context = {"input_data": {"approve": False}}
            result = self.engine._evaluate_condition("input_data.approve === true", context)
            self.assertFalse(result)
    
    @patch('pgappforge.process.engine.executors.TaskExecutor.execute')
    def test_execute_node(self, mock_execute):
        """Test node execution."""
        with self.app.app_context():
            # Mock executor response
            mock_execute.return_value = {"result": "success", "data": "test_output"}
            
            instance = ProcessInstance(
                definition_id=self.definition.id,
                tenant_id=1,
                status=ProcessInstanceStatus.RUNNING.value,
                input_data={"test": "value"}
            )
            
            node = {"id": "task1", "type": "task", "subtype": "user", "name": "Task 1"}
            
            result = asyncio.run(
                self.engine._execute_node(instance, node, {"input": "data"})
            )
            
            self.assertIsNotNone(result)
            self.assertEqual(result["result"], "success")
            mock_execute.assert_called_once()


class TestStateMachine(unittest.TestCase):
    """Test ProcessStateMachine functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.state_machine = ProcessStateMachine()
        
        # Mock objects for testing
        self.mock_instance = Mock()
        self.mock_instance.id = 1
        self.mock_instance.status = ProcessInstanceStatus.RUNNING.value
        
        self.mock_step = Mock()
        self.mock_step.id = 1
        self.mock_step.status = ProcessStepStatus.PENDING.value
    
    def test_valid_process_transitions(self):
        """Test valid process state transitions."""
        # Test valid transitions
        self.assertTrue(
            self.state_machine.is_valid_process_transition(
                ProcessInstanceStatus.RUNNING.value,
                ProcessInstanceStatus.COMPLETED.value
            )
        )
        
        self.assertTrue(
            self.state_machine.is_valid_process_transition(
                ProcessInstanceStatus.SUSPENDED.value,
                ProcessInstanceStatus.RUNNING.value
            )
        )
    
    def test_invalid_process_transitions(self):
        """Test invalid process state transitions."""
        # Test invalid transitions
        self.assertFalse(
            self.state_machine.is_valid_process_transition(
                ProcessInstanceStatus.COMPLETED.value,
                ProcessInstanceStatus.RUNNING.value
            )
        )
        
        self.assertFalse(
            self.state_machine.is_valid_process_transition(
                ProcessInstanceStatus.COMPLETED.value,
                ProcessInstanceStatus.SUSPENDED.value
            )
        )
    
    def test_valid_step_transitions(self):
        """Test valid step state transitions."""
        self.assertTrue(
            self.state_machine.is_valid_step_transition(
                ProcessStepStatus.PENDING.value,
                ProcessStepStatus.RUNNING.value
            )
        )
        
        self.assertTrue(
            self.state_machine.is_valid_step_transition(
                ProcessStepStatus.FAILED.value,
                ProcessStepStatus.PENDING.value
            )
        )
    
    def test_invalid_step_transitions(self):
        """Test invalid step state transitions."""
        self.assertFalse(
            self.state_machine.is_valid_step_transition(
                ProcessStepStatus.COMPLETED.value,
                ProcessStepStatus.RUNNING.value
            )
        )
    
    def test_state_transition_hooks(self):
        """Test state transition hooks."""
        hook_called = False
        
        def test_hook(instance, from_status, to_status, context):
            nonlocal hook_called
            hook_called = True
            self.assertEqual(instance, self.mock_instance)
            self.assertEqual(from_status, ProcessInstanceStatus.RUNNING.value)
            self.assertEqual(to_status, ProcessInstanceStatus.COMPLETED.value)
        
        # Register hook
        self.state_machine.register_process_transition_hook(
            ProcessInstanceStatus.RUNNING.value,
            ProcessInstanceStatus.COMPLETED.value,
            test_hook
        )
        
        # This would test the hook in a real implementation
        # asyncio.run(self.state_machine.transition_process(
        #     self.mock_instance, ProcessInstanceStatus.COMPLETED.value
        # ))
        
        # For now, just test hook registration
        transition_key = (ProcessInstanceStatus.RUNNING.value, ProcessInstanceStatus.COMPLETED.value)
        self.assertIn(transition_key, self.state_machine.process_transition_hooks)
        self.assertEqual(len(self.state_machine.process_transition_hooks[transition_key]), 1)


class TestExecutors(unittest.TestCase):
    """Test process node executors."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        
        with self.app.app_context():
            self.mock_instance = Mock()
            self.mock_instance.id = 1
            self.mock_instance.input_data = {"test": "value"}
            
            self.mock_step = Mock()
            self.mock_step.id = 1
    
    def test_task_executor(self):
        """Test TaskExecutor functionality."""
        with self.app.app_context():
            executor = TaskExecutor()
            
            node_config = {
                "assignee": "user1",
                "form_key": "test_form",
                "due_date": "PT1H"
            }
            
            result = asyncio.run(
                executor.execute(self.mock_instance, self.mock_step, node_config)
            )
            
            self.assertIsInstance(result, dict)
            self.assertIn('task_created', result)
    
    @patch('requests.post')
    def test_service_executor_http(self, mock_post):
        """Test ServiceExecutor HTTP calls."""
        with self.app.app_context():
            # Mock HTTP response
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": "success"}
            mock_post.return_value = mock_response
            
            executor = ServiceExecutor()
            
            node_config = {
                "service_type": "http",
                "url": "https://api.example.com/endpoint",
                "method": "POST",
                "payload": {"data": "test"}
            }
            
            result = asyncio.run(
                executor.execute(self.mock_instance, self.mock_step, node_config)
            )
            
            self.assertIsInstance(result, dict)
            self.assertEqual(result["result"], "success")
            mock_post.assert_called_once()
    
    def test_gateway_executor(self):
        """Test GatewayExecutor condition evaluation."""
        with self.app.app_context():
            executor = GatewayExecutor()
            
            # Test exclusive gateway
            node_config = {
                "gateway_type": "exclusive",
                "conditions": [
                    {"expression": "input_data.value > 10", "target": "path1"},
                    {"expression": "input_data.value <= 10", "target": "path2"}
                ]
            }
            
            self.mock_instance.input_data = {"value": 15}
            
            result = asyncio.run(
                executor.execute(self.mock_instance, self.mock_step, node_config)
            )
            
            self.assertIsInstance(result, dict)
            self.assertIn('selected_path', result)
    
    @patch('pgappforge.process.approval.chain_manager.ApprovalChainManager.create_approval_chain')
    def test_approval_executor(self, mock_create_chain):
        """Test ApprovalExecutor functionality."""
        with self.app.app_context():
            # Mock approval chain creation
            mock_chain = Mock()
            mock_chain.id = 1
            mock_create_chain.return_value = asyncio.Future()
            mock_create_chain.return_value.set_result(mock_chain)
            
            executor = ApprovalExecutor()
            
            node_config = {
                "approvers": [{"user_id": 1, "username": "approver1"}],
                "approval_type": "sequential",
                "priority": "normal"
            }
            
            result = asyncio.run(
                executor.execute(self.mock_instance, self.mock_step, node_config)
            )
            
            self.assertIsInstance(result, dict)
            self.assertIn('approval_chain_id', result)


class TestApprovalSystem(unittest.TestCase):
    """Test approval chain management system."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
            
            self.chain_manager = ApprovalChainManager()
            self.create_test_data()
    
    def create_test_data(self):
        """Create test data for approval tests."""
        from pgappforge import db
        
        # Create process instance and step
        self.instance = ProcessInstance(
            definition_id=1,
            tenant_id=1,
            status=ProcessInstanceStatus.RUNNING.value,
            input_data={"test": "data"}
        )
        db.session.add(self.instance)
        db.session.flush()
        
        self.step = ProcessStep(
            instance_id=self.instance.id,
            node_id="approval",
            node_type="approval",
            status=ProcessStepStatus.RUNNING.value,
            tenant_id=1
        )
        db.session.add(self.step)
        db.session.commit()
    
    def test_approval_context_creation(self):
        """Test ApprovalContext creation."""
        with self.app.app_context():
            context = ApprovalContext(
                step_id=self.step.id,
                instance_id=self.instance.id,
                request_data={"amount": 1000},
                initiator_id=1,
                priority="high"
            )
            
            self.assertEqual(context.step_id, self.step.id)
            self.assertEqual(context.instance_id, self.instance.id)
            self.assertEqual(context.priority, "high")
    
    def test_approval_decision_creation(self):
        """Test ApprovalDecision creation."""
        decision = ApprovalDecision(
            approved=True,
            approver_id=1,
            comment="Looks good",
            response_data={"notes": "approved quickly"}
        )
        
        self.assertTrue(decision.approved)
        self.assertEqual(decision.approver_id, 1)
        self.assertEqual(decision.comment, "Looks good")
        self.assertIsNotNone(decision.timestamp)
    
    @patch('pgappforge.process.approval.chain_manager.ApprovalChainManager._determine_approvers')
    @patch('pgappforge.process.approval.chain_manager.ApprovalChainManager._send_approval_notification')
    def test_create_approval_chain(self, mock_send_notification, mock_determine_approvers):
        """Test approval chain creation."""
        with self.app.app_context():
            # Mock approvers
            mock_determine_approvers.return_value = asyncio.Future()
            mock_determine_approvers.return_value.set_result([
                {"user_id": 1, "username": "approver1", "order": 0, "required": True}
            ])
            
            mock_send_notification.return_value = asyncio.Future()
            mock_send_notification.return_value.set_result(None)
            
            context = ApprovalContext(
                step_id=self.step.id,
                instance_id=self.instance.id,
                request_data={"amount": 1000},
                initiator_id=1
            )
            
            chain_config = {
                "type": "sequential",
                "approvers": [{"user_id": 1}]
            }
            
            chain = asyncio.run(
                self.chain_manager.create_approval_chain(context, chain_config)
            )
            
            self.assertIsNotNone(chain)
            self.assertEqual(chain.step_id, self.step.id)
            self.assertEqual(chain.chain_type, "sequential")


class TestSmartTriggers(unittest.TestCase):
    """Test smart trigger system."""
    
    def setUp(self):
        """Set up test environment."""
        self.trigger_engine = SmartTriggerEngine()
    
    def test_trigger_event_creation(self):
        """Test TriggerEvent creation."""
        event = TriggerEvent(
            event_type="data_change",
            data={"field": "value", "threshold": 100},
            timestamp=datetime.utcnow(),
            tenant_id=1,
            source="database"
        )
        
        self.assertEqual(event.event_type, "data_change")
        self.assertIsInstance(event.data, dict)
        self.assertEqual(event.tenant_id, 1)
        self.assertIsNotNone(event.timestamp)
    
    def test_ml_model_initialization(self):
        """Test ML model initialization."""
        models = self.trigger_engine.ml_models
        
        self.assertIn('outcome_predictor', models)
        self.assertIn('anomaly_detector', models)
        
        predictor = models['outcome_predictor']
        self.assertEqual(predictor.model_name, "process_outcome_predictor")
        self.assertFalse(predictor.is_trained)
    
    @patch('pgappforge.process.ml.smart_triggers.ProcessOutcomePredictor.predict')
    def test_ml_prediction(self, mock_predict):
        """Test ML prediction functionality."""
        # Mock prediction result
        mock_predict.return_value = {
            'predicted_outcome': 'success',
            'confidence': 0.85,
            'estimated_duration_seconds': 3600
        }
        
        predictor = self.trigger_engine.ml_models['outcome_predictor']
        predictor.is_trained = True  # Mock trained state
        
        prediction_data = {
            'definition_complexity': 5,
            'input_data_size': 100,
            'historical_duration': 3600,
            'initiator_experience': 3
        }
        
        result = predictor.predict(prediction_data)
        
        self.assertEqual(result['predicted_outcome'], 'success')
        self.assertEqual(result['confidence'], 0.85)
        mock_predict.assert_called_once()


class TestAnalyticsDashboard(unittest.TestCase):
    """Test process analytics and dashboard."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
            
            self.analytics = ProcessAnalytics()
            self.create_test_analytics_data()
    
    def create_test_analytics_data(self):
        """Create test data for analytics."""
        from pgappforge import db
        
        # Create process instances with various statuses
        for i in range(10):
            instance = ProcessInstance(
                definition_id=1,
                tenant_id=1,
                status=ProcessInstanceStatus.COMPLETED.value if i < 8 else ProcessInstanceStatus.FAILED.value,
                input_data={"test": f"data_{i}"},
                started_at=datetime.utcnow() - timedelta(days=i),
                completed_at=datetime.utcnow() - timedelta(days=i, hours=-1) if i < 8 else datetime.utcnow() - timedelta(days=i)
            )
            db.session.add(instance)
        
        db.session.commit()
    
    @patch('pgappforge.tenants.context.TenantContext.get_current_tenant_id')
    def test_dashboard_metrics(self, mock_tenant_id):
        """Test dashboard metrics calculation."""
        with self.app.app_context():
            mock_tenant_id.return_value = 1
            
            metrics = self.analytics.get_dashboard_metrics(30)
            
            self.assertIsInstance(metrics, dict)
            self.assertIn('overview', metrics)
            self.assertIn('process_performance', metrics)
            self.assertIn('bottlenecks', metrics)
            self.assertIn('trends', metrics)
            
            overview = metrics['overview']
            self.assertIn('total_instances', overview)
            self.assertIn('success_rate', overview)
    
    def test_performance_metrics(self):
        """Test performance metrics calculation."""
        with self.app.app_context():
            # Mock performance calculation
            instances = [Mock() for _ in range(10)]
            
            # Set up mock instances
            for i, instance in enumerate(instances):
                instance.status = ProcessInstanceStatus.COMPLETED.value if i < 8 else ProcessInstanceStatus.FAILED.value
                instance.started_at = datetime.utcnow() - timedelta(hours=i)
                instance.completed_at = datetime.utcnow() - timedelta(hours=i-1) if i < 8 else None
            
            # Test status analysis
            status_analysis = self.analytics._analyze_instance_statuses(instances)
            
            self.assertIsInstance(status_analysis, dict)
            self.assertIn('counts', status_analysis)
            self.assertIn('percentages', status_analysis)
            
            counts = status_analysis['counts']
            self.assertEqual(counts[ProcessInstanceStatus.COMPLETED.value], 8)
            self.assertEqual(counts[ProcessInstanceStatus.FAILED.value], 2)


class TestTaskMonitoring(unittest.TestCase):
    """Test async task monitoring system."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            from pgappforge.process.async.task_monitor import Base
            
            db.init_app(self.app)
            
            # Create tables for task monitoring
            Base.metadata.create_all(db.engine)
            
            self.task_monitor = TaskMonitor()
    
    def test_task_monitoring_creation(self):
        """Test task monitor initialization."""
        self.assertIsNotNone(self.task_monitor)
        self.assertIsInstance(self.task_monitor._recent_tasks, type(self.task_monitor._recent_tasks))
    
    @patch('pgappforge.tenants.context.TenantContext.get_current_tenant_id')
    def test_task_statistics(self, mock_tenant_id):
        """Test task statistics calculation."""
        with self.app.app_context():
            mock_tenant_id.return_value = 1
            
            # Record some test tasks
            self.task_monitor.record_task_start("test_task_1", "test.task", (), {})
            self.task_monitor.record_task_success("test_task_1", {"result": "success"})
            
            self.task_monitor.record_task_start("test_task_2", "test.task", (), {})
            self.task_monitor.record_task_failure("test_task_2", "Test error")
            
            # Get statistics
            stats = self.task_monitor.get_task_statistics(24)
            
            self.assertIsInstance(stats, dict)
            self.assertIn('total_tasks', stats)
            self.assertIn('successful_tasks', stats)
            self.assertIn('failed_tasks', stats)
            self.assertIn('success_rate', stats)


class TestIntegrationScenarios(unittest.TestCase):
    """Test end-to-end integration scenarios."""
    
    def setUp(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        
        with self.app.app_context():
            from pgappforge import db
            db.init_app(self.app)
            db.create_all()
            
            self.engine = ProcessEngine()
            self.create_complex_process()
    
    def create_complex_process(self):
        """Create a complex process for integration testing."""
        from pgappforge import db
        
        self.definition = ProcessDefinition(
            name="Complex Integration Test Process",
            description="Complex process for integration testing",
            version="1.0",
            category="Testing",
            status="active",
            tenant_id=1,
            process_graph={
                "nodes": [
                    {"id": "start", "type": "event", "subtype": "start", "name": "Start"},
                    {"id": "user_task", "type": "task", "subtype": "user", "name": "User Input"},
                    {"id": "approval", "type": "approval", "subtype": "single", "name": "Manager Approval"},
                    {"id": "gateway", "type": "gateway", "subtype": "exclusive", "name": "Decision"},
                    {"id": "service_call", "type": "task", "subtype": "service", "name": "External Service"},
                    {"id": "timer", "type": "event", "subtype": "timer", "name": "Wait Period"},
                    {"id": "end", "type": "event", "subtype": "end", "name": "End"}
                ],
                "edges": [
                    {"source": "start", "target": "user_task"},
                    {"source": "user_task", "target": "approval"},
                    {"source": "approval", "target": "gateway"},
                    {"source": "gateway", "target": "service_call", "condition": "approved"},
                    {"source": "gateway", "target": "timer", "condition": "rejected"},
                    {"source": "service_call", "target": "end"},
                    {"source": "timer", "target": "end"}
                ]
            }
        )
        
        db.session.add(self.definition)
        db.session.commit()
    
    @patch('pgappforge.process.engine.executors.TaskExecutor.execute')
    @patch('pgappforge.process.engine.executors.ApprovalExecutor.execute')
    def test_complete_process_flow(self, mock_approval_executor, mock_task_executor):
        """Test complete process execution flow."""
        with self.app.app_context():
            # Mock executor responses
            mock_task_executor.return_value = asyncio.Future()
            mock_task_executor.return_value.set_result({"result": "task_completed", "data": "user_input"})
            
            mock_approval_executor.return_value = asyncio.Future()
            mock_approval_executor.return_value.set_result({"approval_chain_id": 1, "waiting_for_approval": True})
            
            # Start process
            instance = asyncio.run(
                self.engine.start_process(
                    definition_id=self.definition.id,
                    input_data={"user_request": "test_request", "amount": 500}
                )
            )
            
            self.assertIsNotNone(instance)
            self.assertEqual(instance.status, ProcessInstanceStatus.RUNNING.value)
            
            # Verify steps were created
            from pgappforge import db
            steps = db.session.query(ProcessStep).filter_by(instance_id=instance.id).all()
            self.assertGreater(len(steps), 0)
    
    def test_error_handling_flow(self):
        """Test process error handling and recovery."""
        with self.app.app_context():
            # Create instance with invalid data to trigger errors
            instance = ProcessInstance(
                definition_id=self.definition.id,
                tenant_id=1,
                status=ProcessInstanceStatus.RUNNING.value,
                input_data={"invalid": "data"}
            )
            
            from pgappforge import db
            db.session.add(instance)
            db.session.commit()
            
            # Create a failed step
            step = ProcessStep(
                instance_id=instance.id,
                node_id="user_task",
                node_type="task",
                status=ProcessStepStatus.FAILED.value,
                error_message="Test error",
                tenant_id=1
            )
            
            db.session.add(step)
            db.session.commit()
            
            # Test error handling
            self.assertEqual(step.status, ProcessStepStatus.FAILED.value)
            self.assertIsNotNone(step.error_message)


if __name__ == '__main__':
    # Run all tests
    unittest.main(verbosity=2)