"""
Form Sequencing Engine and Orchestrator for Workflow-Aware Forms

Provides intelligent form sequencing, dynamic field management,
and orchestration capabilities for Flask-AppBuilder workflows.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass
from collections import OrderedDict
import json

from flask import session, request, current_app
from flask_login import current_user
from wtforms import Form, StringField, TextAreaField, SelectField, BooleanField, IntegerField
from wtforms import DateField, DateTimeField, FloatField, FileField
from wtforms.validators import DataRequired, Optional as OptionalValidator, Length, Email, NumberRange
from wtforms.widgets import TextInput, TextArea, Select, CheckboxInput, NumberInput, DateInput

from flask_appbuilder.forms import DynamicForm
from flask_appbuilder.fieldwidgets import BS3TextFieldWidget, BS3TextAreaFieldWidget
from flask_appbuilder.widgets import FormWidget

if TYPE_CHECKING:
    from .core import WorkflowState, WorkflowStepDefinition

log = logging.getLogger(__name__)


@dataclass
class FieldDefinition:
    """Definition of a form field."""
    name: str
    field_type: str
    label: Optional[str] = None
    required: bool = False
    validators: Optional[List[str]] = None
    choices: Optional[List[tuple]] = None
    default_value: Any = None
    placeholder: Optional[str] = None
    description: Optional[str] = None
    widget: Optional[str] = None
    conditions: Optional[Dict[str, Any]] = None


@dataclass
class FormStepDefinition:
    """Definition of a form step in a sequence."""
    id: str
    name: str
    description: Optional[str] = None
    fields: List[FieldDefinition] = None
    template: Optional[str] = None
    validation_rules: Optional[Dict[str, Any]] = None
    conditional_logic: Optional[Dict[str, Any]] = None
    required_role: Optional[str] = None
    timeout_minutes: Optional[int] = None


class WorkflowFormSequence:
    """
    Manages a sequence of forms in a workflow.

    Provides intelligent form sequencing with conditional logic,
    dynamic field management, and state persistence.
    """

    def __init__(self, sequence_name: str, steps: List[FormStepDefinition]):
        self.sequence_name = sequence_name
        self.steps = OrderedDict((step.id, step) for step in steps)
        self._field_cache = {}
        self._validator_cache = {}

    def get_step(self, step_id: str) -> Optional[FormStepDefinition]:
        """Get step definition by ID."""
        return self.steps.get(step_id)

    def get_step_ids(self) -> List[str]:
        """Get all step IDs in order."""
        return list(self.steps.keys())

    def get_next_step_id(self, current_step_id: str, form_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Get next step ID based on conditional logic."""
        step_ids = self.get_step_ids()

        try:
            current_index = step_ids.index(current_step_id)
        except ValueError:
            return None

        if current_index >= len(step_ids) - 1:
            return None

        # Check conditional logic for next step
        current_step = self.steps[current_step_id]
        if current_step.conditional_logic and form_data:
            next_step_id = self._evaluate_conditional_logic(
                current_step.conditional_logic,
                form_data,
                step_ids[current_index + 1:]
            )
            if next_step_id:
                return next_step_id

        # Default: return next step in sequence
        return step_ids[current_index + 1]

    def get_previous_step_id(self, current_step_id: str) -> Optional[str]:
        """Get previous step ID."""
        step_ids = self.get_step_ids()

        try:
            current_index = step_ids.index(current_step_id)
        except ValueError:
            return None

        if current_index <= 0:
            return None

        return step_ids[current_index - 1]

    def create_form_for_step(self, step_id: str, data: Optional[Dict[str, Any]] = None) -> Form:
        """Create WTForms form for a specific step."""
        step = self.get_step(step_id)
        if not step:
            raise ValueError(f"Step not found: {step_id}")

        return self._build_dynamic_form(step, data)

    def _build_dynamic_form(self, step: FormStepDefinition, data: Optional[Dict[str, Any]] = None) -> Form:
        """Build dynamic WTForms form from step definition."""

        class DynamicStepForm(DynamicForm):
            pass

        # Add fields to form class
        for field_def in step.fields or []:
            field_obj = self._create_field_from_definition(field_def)
            setattr(DynamicStepForm, field_def.name, field_obj)

        # Create form instance
        form = DynamicStepForm(data=data)

        # Set field data if provided
        if data:
            for field_name, value in data.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).data = value

        return form

    def _create_field_from_definition(self, field_def: FieldDefinition):
        """Create WTForms field from field definition."""
        cache_key = f"{field_def.name}_{field_def.field_type}"

        if cache_key in self._field_cache:
            return self._field_cache[cache_key]

        # Build validators
        validators = self._build_validators(field_def)

        # Field type mapping
        field_classes = {
            'string': StringField,
            'text': TextAreaField,
            'select': SelectField,
            'boolean': BooleanField,
            'integer': IntegerField,
            'float': FloatField,
            'date': DateField,
            'datetime': DateTimeField,
            'email': StringField,
            'file': FileField
        }

        field_class = field_classes.get(field_def.field_type, StringField)

        # Field arguments
        field_args = {
            'label': field_def.label or field_def.name.title(),
            'validators': validators,
            'description': field_def.description
        }

        # Add field-specific arguments
        if field_def.field_type == 'select' and field_def.choices:
            field_args['choices'] = field_def.choices

        if field_def.default_value is not None:
            field_args['default'] = field_def.default_value

        # Create field
        field = field_class(**field_args)

        # Cache field
        self._field_cache[cache_key] = field

        return field

    def _build_validators(self, field_def: FieldDefinition) -> List:
        """Build validators for a field."""
        validators = []

        # Required validator
        if field_def.required:
            validators.append(DataRequired())
        else:
            validators.append(OptionalValidator())

        # Custom validators
        if field_def.validators:
            for validator_name in field_def.validators:
                validator = self._get_validator(validator_name, field_def)
                if validator:
                    validators.append(validator)

        return validators

    def _get_validator(self, validator_name: str, field_def: FieldDefinition):
        """Get validator instance by name."""
        validator_map = {
            'email': Email(),
            'length': Length(min=1, max=255),  # Default length
            'number_range': NumberRange(min=0)  # Default range
        }

        return validator_map.get(validator_name)

    def _evaluate_conditional_logic(self, logic: Dict[str, Any], form_data: Dict[str, Any],
                                  available_steps: List[str]) -> Optional[str]:
        """Evaluate conditional logic to determine next step."""

        logic_type = logic.get('type', 'simple')

        if logic_type == 'simple':
            # Simple field-based conditions
            conditions = logic.get('conditions', [])

            for condition in conditions:
                field_name = condition.get('field')
                operator = condition.get('operator', 'equals')
                expected_value = condition.get('value')
                next_step = condition.get('next_step')

                if field_name not in form_data:
                    continue

                actual_value = form_data[field_name]

                if self._evaluate_condition(actual_value, operator, expected_value):
                    if next_step in available_steps:
                        return next_step

        elif logic_type == 'expression':
            # JavaScript-like expression evaluation (simplified)
            expression = logic.get('expression')
            return self._evaluate_expression(expression, form_data, available_steps)

        return None

    def _evaluate_condition(self, actual_value: Any, operator: str, expected_value: Any) -> bool:
        """Evaluate a single condition."""
        if operator == 'equals':
            return actual_value == expected_value
        elif operator == 'not_equals':
            return actual_value != expected_value
        elif operator == 'greater_than':
            return actual_value > expected_value
        elif operator == 'less_than':
            return actual_value < expected_value
        elif operator == 'contains':
            return expected_value in str(actual_value)
        elif operator == 'not_empty':
            return actual_value is not None and str(actual_value).strip() != ''
        elif operator == 'empty':
            return actual_value is None or str(actual_value).strip() == ''

        return False

    def _evaluate_expression(self, expression: str, form_data: Dict[str, Any],
                           available_steps: List[str]) -> Optional[str]:
        """Evaluate expression for conditional logic using safe AST evaluation."""
        import ast
        import operator

        # Safe operators for expression evaluation
        safe_operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
            ast.And: operator.and_,
            ast.Or: operator.or_,
            ast.Not: operator.not_,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def safe_eval(node, variables):
            """Safely evaluate AST node with limited operations."""
            if isinstance(node, ast.Constant):  # Python 3.8+
                return node.value
            elif isinstance(node, ast.Str):  # Python < 3.8
                return node.s
            elif isinstance(node, ast.Num):  # Python < 3.8
                return node.n
            elif isinstance(node, ast.Name):
                if node.id in variables:
                    return variables[node.id]
                else:
                    raise ValueError(f"Undefined variable: {node.id}")
            elif isinstance(node, ast.BinOp):
                left = safe_eval(node.left, variables)
                right = safe_eval(node.right, variables)
                if type(node.op) in safe_operators:
                    return safe_operators[type(node.op)](left, right)
                else:
                    raise ValueError(f"Unsupported binary operator: {type(node.op)}")
            elif isinstance(node, ast.UnaryOp):
                operand = safe_eval(node.operand, variables)
                if type(node.op) in safe_operators:
                    return safe_operators[type(node.op)](operand)
                else:
                    raise ValueError(f"Unsupported unary operator: {type(node.op)}")
            elif isinstance(node, ast.Compare):
                left = safe_eval(node.left, variables)
                for op, right_node in zip(node.ops, node.comparators):
                    right = safe_eval(right_node, variables)
                    if type(op) in safe_operators:
                        result = safe_operators[type(op)](left, right)
                        if not result:
                            return False
                        left = right  # For chained comparisons
                    else:
                        raise ValueError(f"Unsupported comparison operator: {type(op)}")
                return True
            elif isinstance(node, ast.BoolOp):
                values = [safe_eval(value, variables) for value in node.values]
                if isinstance(node.op, ast.And):
                    return all(values)
                elif isinstance(node.op, ast.Or):
                    return any(values)
                else:
                    raise ValueError(f"Unsupported boolean operator: {type(node.op)}")
            else:
                raise ValueError(f"Unsupported AST node type: {type(node)}")

        try:
            # Parse the expression into AST
            tree = ast.parse(expression, mode='eval')

            # Create safe variable context
            variables = {}
            for field_name, value in form_data.items():
                # Sanitize variable names (only alphanumeric and underscore)
                safe_name = ''.join(c for c in field_name if c.isalnum() or c == '_')
                if safe_name and safe_name[0].isalpha():
                    variables[safe_name] = value

            # Evaluate the expression safely
            result = safe_eval(tree.body, variables)

            # Return result if it's a valid step
            if isinstance(result, str) and result in available_steps:
                return result

        except (SyntaxError, ValueError, TypeError) as e:
            log.warning(f"Failed to evaluate expression '{expression}': {e}")
        except Exception as e:
            log.error(f"Unexpected error evaluating expression '{expression}': {e}")

        return None


class FormOrchestrator:
    """
    Orchestrates multiple form sequences and manages workflow state.

    Provides high-level workflow management capabilities including
    form sequence selection, state persistence, and progress tracking.
    """

    def __init__(self):
        self.sequences: Dict[str, WorkflowFormSequence] = {}
        self.state_handlers: Dict[str, Callable] = {}

    def register_sequence(self, sequence: WorkflowFormSequence):
        """Register a form sequence."""
        self.sequences[sequence.sequence_name] = sequence
        log.info(f"Registered form sequence: {sequence.sequence_name}")

    def register_state_handler(self, handler_name: str, handler: Callable):
        """Register a state change handler."""
        self.state_handlers[handler_name] = handler

    def get_sequence(self, sequence_name: str) -> Optional[WorkflowFormSequence]:
        """Get form sequence by name."""
        return self.sequences.get(sequence_name)

    def create_form_for_workflow_step(self, workflow_state: 'WorkflowState') -> Optional[Form]:
        """Create form for current workflow step."""
        sequence = self.get_sequence(workflow_state.workflow_name)
        if not sequence:
            return None

        current_step_data = workflow_state.get_form_data_for_step(workflow_state.current_step)
        return sequence.create_form_for_step(workflow_state.current_step, current_step_data)

    def advance_workflow_form(self, workflow_state: 'WorkflowState',
                            form_data: Dict[str, Any]) -> Optional[str]:
        """Advance workflow to next form step."""
        sequence = self.get_sequence(workflow_state.workflow_name)
        if not sequence:
            return None

        # Save current step data
        workflow_state.set_form_data_for_step(workflow_state.current_step, form_data)

        # Get next step
        next_step_id = sequence.get_next_step_id(workflow_state.current_step, form_data)

        if next_step_id:
            # Update workflow state
            workflow_state.current_step = next_step_id
            workflow_state.last_activity_at = datetime.now(tz=timezone.utc)

            # Add to completed steps
            if workflow_state.current_step not in workflow_state.completed_steps:
                completed = list(workflow_state.completed_steps) if workflow_state.completed_steps else []
                completed.append(workflow_state.current_step)
                workflow_state.completed_steps = completed

            # Call state handlers
            for handler in self.state_handlers.values():
                try:
                    handler(workflow_state, 'step_advanced', {
                        'previous_step': workflow_state.current_step,
                        'next_step': next_step_id,
                        'form_data': form_data
                    })
                except Exception as e:
                    log.error(f"Error in state handler: {e}")

        return next_step_id

    def validate_step_data(self, sequence_name: str, step_id: str,
                          form_data: Dict[str, Any]) -> Dict[str, List[str]]:
        """Validate form data for a specific step."""
        sequence = self.get_sequence(sequence_name)
        if not sequence:
            return {'general': ['Sequence not found']}

        step = sequence.get_step(step_id)
        if not step:
            return {'general': ['Step not found']}

        errors = {}

        # Create form and validate
        form = sequence.create_form_for_step(step_id, form_data)
        if not form.validate():
            for field_name, field_errors in form.errors.items():
                errors[field_name] = field_errors

        # Custom validation rules
        if step.validation_rules:
            custom_errors = self._apply_custom_validation(step.validation_rules, form_data)
            errors.update(custom_errors)

        return errors

    def _apply_custom_validation(self, rules: Dict[str, Any],
                               form_data: Dict[str, Any]) -> Dict[str, List[str]]:
        """Apply custom validation rules."""
        errors = {}

        for rule_name, rule_config in rules.items():
            if rule_name == 'unique_combination':
                # Validate unique field combinations
                fields = rule_config.get('fields', [])
                error_message = rule_config.get('message', 'Combination must be unique')

                # This would typically check against database
                # Simplified implementation for demo
                pass

            elif rule_name == 'conditional_required':
                # Conditionally required fields
                condition_field = rule_config.get('condition_field')
                condition_value = rule_config.get('condition_value')
                required_fields = rule_config.get('required_fields', [])
                error_message = rule_config.get('message', 'Field is required')

                if form_data.get(condition_field) == condition_value:
                    for field in required_fields:
                        if not form_data.get(field):
                            if field not in errors:
                                errors[field] = []
                            errors[field].append(error_message)

        return errors

    def get_form_progress(self, workflow_state: 'WorkflowState') -> Dict[str, Any]:
        """Get form completion progress."""
        sequence = self.get_sequence(workflow_state.workflow_name)
        if not sequence:
            return {}

        step_ids = sequence.get_step_ids()
        completed_steps = workflow_state.completed_steps or []
        current_step_index = step_ids.index(workflow_state.current_step) if workflow_state.current_step in step_ids else 0

        return {
            'total_steps': len(step_ids),
            'completed_steps': len(completed_steps),
            'current_step_index': current_step_index,
            'progress_percentage': int((len(completed_steps) / len(step_ids)) * 100) if step_ids else 0,
            'step_names': [sequence.get_step(step_id).name for step_id in step_ids],
            'current_step_name': sequence.get_step(workflow_state.current_step).name if workflow_state.current_step else None
        }


# Global orchestrator instance
form_orchestrator = FormOrchestrator()


def get_form_orchestrator() -> FormOrchestrator:
    """Get the global form orchestrator instance."""
    return form_orchestrator


# Helper functions for easy sequence creation
def create_simple_sequence(name: str, step_configs: List[Dict[str, Any]]) -> WorkflowFormSequence:
    """Create a simple form sequence from configuration."""
    steps = []

    for i, config in enumerate(step_configs):
        fields = []

        for field_config in config.get('fields', []):
            if isinstance(field_config, str):
                # Simple field name
                field_def = FieldDefinition(
                    name=field_config,
                    field_type='string',
                    required=True
                )
            else:
                # Full field configuration
                field_def = FieldDefinition(
                    name=field_config['name'],
                    field_type=field_config.get('type', 'string'),
                    label=field_config.get('label'),
                    required=field_config.get('required', False),
                    validators=field_config.get('validators'),
                    choices=field_config.get('choices'),
                    default_value=field_config.get('default'),
                    placeholder=field_config.get('placeholder'),
                    description=field_config.get('description')
                )

            fields.append(field_def)

        step = FormStepDefinition(
            id=config.get('id', f'step_{i+1}'),
            name=config.get('name', f'Step {i+1}'),
            description=config.get('description'),
            fields=fields,
            validation_rules=config.get('validation_rules'),
            conditional_logic=config.get('conditional_logic'),
            required_role=config.get('required_role')
        )

        steps.append(step)

    return WorkflowFormSequence(name, steps)