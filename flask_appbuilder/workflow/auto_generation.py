"""
Automatic Workflow Generation System for Flask-AppBuilder

Provides intelligent workflow generation capabilities including:
- Model-driven workflow generation from SQLAlchemy models
- Business rule-based workflow creation
- AI-powered workflow suggestion using Ollama
- Template-based workflow generation
- Workflow optimization and refinement
- Automatic step sequence generation
- Smart form field grouping and validation
"""

import logging
import json
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, TYPE_CHECKING
from dataclasses import dataclass, asdict
from enum import Enum
import inspect

from flask import current_app
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.inspection import inspect as sqla_inspect
from sqlalchemy.orm import relationship
from wtforms import validators

from ..models.mixins import AuditMixin
from .core import WorkflowDefinition, WorkflowStepDefinition, WorkflowStepType, get_workflow_engine
from .ai_optimization import get_ai_optimizer

if TYPE_CHECKING:
    from sqlalchemy.ext.declarative import DeclarativeMeta

log = logging.getLogger(__name__)


class GenerationType(Enum):
    """Types of workflow generation."""
    MODEL_DRIVEN = "model_driven"
    BUSINESS_RULES = "business_rules"
    AI_SUGGESTED = "ai_suggested"
    TEMPLATE_BASED = "template_based"
    HYBRID = "hybrid"


class FieldGroupingStrategy(Enum):
    """Strategies for grouping form fields into steps."""
    LOGICAL_GROUPS = "logical_groups"
    FIELD_COUNT = "field_count"
    COMPLEXITY_BASED = "complexity_based"
    RELATIONSHIP_BASED = "relationship_based"
    AI_OPTIMIZED = "ai_optimized"


@dataclass
class GenerationConfig:
    """Configuration for workflow generation."""
    generation_type: GenerationType
    grouping_strategy: FieldGroupingStrategy
    max_fields_per_step: int = 5
    enable_ai_optimization: bool = True
    include_validation_steps: bool = True
    include_approval_steps: bool = False
    auto_generate_navigation: bool = True
    business_rules: Optional[Dict[str, Any]] = None
    template_name: Optional[str] = None


@dataclass
class FieldAnalysis:
    """Analysis of a model field for workflow generation."""
    name: str
    field_type: str
    required: bool
    relationship_type: Optional[str]
    complexity_score: float
    grouping_hint: Optional[str]
    validation_rules: List[str]
    default_value: Any = None


@dataclass
class WorkflowTemplate:
    """Template for workflow generation."""
    name: str
    description: str
    steps: List[Dict[str, Any]]
    applicable_models: List[str]
    business_domain: str
    complexity_level: str  # simple, medium, complex


class WorkflowAutoGenerator:
    """
    Automatic workflow generation engine.
    """

    def __init__(self):
        self.templates: Dict[str, WorkflowTemplate] = {}
        self.field_analyzers: Dict[str, callable] = {}
        self.business_rules: Dict[str, callable] = {}
        self._setup_default_templates()
        self._setup_field_analyzers()

    def _setup_default_templates(self):
        """Setup default workflow templates."""
        
        # Employee Onboarding Template
        self.templates['employee_onboarding'] = WorkflowTemplate(
            name='Employee Onboarding',
            description='Standard employee onboarding workflow',
            steps=[
                {
                    'name': 'Personal Information',
                    'fields': ['first_name', 'last_name', 'email', 'phone', 'address'],
                    'grouping': 'personal_info'
                },
                {
                    'name': 'Employment Details',
                    'fields': ['position', 'department', 'start_date', 'salary', 'manager'],
                    'grouping': 'employment'
                },
                {
                    'name': 'Documentation',
                    'fields': ['documents', 'emergency_contact', 'tax_information'],
                    'grouping': 'documentation'
                },
                {
                    'name': 'Review and Approval',
                    'fields': ['review_comments', 'hr_approval'],
                    'grouping': 'approval',
                    'step_type': 'approval'
                }
            ],
            applicable_models=['Employee', 'Staff', 'Personnel'],
            business_domain='HR',
            complexity_level='medium'
        )

        # Customer Registration Template
        self.templates['customer_registration'] = WorkflowTemplate(
            name='Customer Registration',
            description='Customer registration and verification workflow',
            steps=[
                {
                    'name': 'Basic Information',
                    'fields': ['name', 'email', 'phone'],
                    'grouping': 'basic_info'
                },
                {
                    'name': 'Address Details',
                    'fields': ['address', 'city', 'state', 'zip_code', 'country'],
                    'grouping': 'address'
                },
                {
                    'name': 'Account Setup',
                    'fields': ['username', 'password', 'security_question'],
                    'grouping': 'account'
                },
                {
                    'name': 'Preferences',
                    'fields': ['newsletter', 'notifications', 'marketing_consent'],
                    'grouping': 'preferences'
                }
            ],
            applicable_models=['Customer', 'Client', 'User'],
            business_domain='Sales',
            complexity_level='simple'
        )

        # Product Development Template
        self.templates['product_development'] = WorkflowTemplate(
            name='Product Development',
            description='Product development lifecycle workflow',
            steps=[
                {
                    'name': 'Concept',
                    'fields': ['product_name', 'description', 'target_market'],
                    'grouping': 'concept'
                },
                {
                    'name': 'Requirements',
                    'fields': ['features', 'specifications', 'requirements'],
                    'grouping': 'requirements'
                },
                {
                    'name': 'Design',
                    'fields': ['design_docs', 'mockups', 'prototypes'],
                    'grouping': 'design'
                },
                {
                    'name': 'Development',
                    'fields': ['development_plan', 'milestones', 'resources'],
                    'grouping': 'development'
                },
                {
                    'name': 'Testing',
                    'fields': ['test_plan', 'quality_metrics', 'acceptance_criteria'],
                    'grouping': 'testing'
                },
                {
                    'name': 'Launch',
                    'fields': ['launch_plan', 'marketing_strategy', 'go_live_date'],
                    'grouping': 'launch'
                }
            ],
            applicable_models=['Product', 'Project', 'Development'],
            business_domain='Product',
            complexity_level='complex'
        )

    def _setup_field_analyzers(self):
        """Setup field analysis functions."""
        
        def analyze_string_field(column):
            complexity = 1.0
            grouping_hint = 'basic_info'
            validation_rules = []
            
            if hasattr(column.type, 'length') and column.type.length:
                if column.type.length > 255:
                    complexity += 0.5
                    grouping_hint = 'detailed_info'
                    
            if 'email' in column.name.lower():
                validation_rules.append('email')
                grouping_hint = 'contact_info'
            elif 'phone' in column.name.lower():
                validation_rules.append('phone')
                grouping_hint = 'contact_info'
            elif 'address' in column.name.lower():
                grouping_hint = 'address_info'
            elif any(word in column.name.lower() for word in ['password', 'secret', 'key']):
                complexity += 1.0
                grouping_hint = 'security_info'
                validation_rules.append('secure')
                
            return complexity, grouping_hint, validation_rules
            
        def analyze_integer_field(column):
            complexity = 0.5
            grouping_hint = 'basic_info'
            validation_rules = []
            
            if 'id' in column.name.lower() and column.name.lower().endswith('_id'):
                grouping_hint = 'relationships'
                complexity += 0.3
            elif any(word in column.name.lower() for word in ['salary', 'price', 'cost', 'amount']):
                grouping_hint = 'financial_info'
                validation_rules.append('positive')
                
            return complexity, grouping_hint, validation_rules
            
        def analyze_datetime_field(column):
            complexity = 0.7
            grouping_hint = 'basic_info'
            validation_rules = []
            
            if any(word in column.name.lower() for word in ['start', 'end', 'due', 'deadline']):
                grouping_hint = 'scheduling_info'
            elif any(word in column.name.lower() for word in ['created', 'updated', 'modified']):
                grouping_hint = 'audit_info'
                
            return complexity, grouping_hint, validation_rules
            
        def analyze_boolean_field(column):
            complexity = 0.3
            grouping_hint = 'preferences'
            validation_rules = []
            
            if any(word in column.name.lower() for word in ['active', 'enabled', 'approved']):
                grouping_hint = 'status_info'
            elif any(word in column.name.lower() for word in ['consent', 'agree', 'accept']):
                grouping_hint = 'legal_info'
                validation_rules.append('required')
                
            return complexity, grouping_hint, validation_rules

        self.field_analyzers = {
            'String': analyze_string_field,
            'Integer': analyze_integer_field,
            'DateTime': analyze_datetime_field,
            'Boolean': analyze_boolean_field,
            'Text': lambda col: (1.5, 'detailed_info', []),
            'Float': lambda col: (0.6, 'basic_info', []),
        }

    def generate_workflow_from_model(self, model_class: 'DeclarativeMeta', 
                                   config: GenerationConfig) -> WorkflowDefinition:
        """Generate workflow from SQLAlchemy model."""
        
        # Analyze model fields
        field_analyses = self._analyze_model_fields(model_class)
        
        # Group fields into steps
        if config.grouping_strategy == FieldGroupingStrategy.AI_OPTIMIZED and config.enable_ai_optimization:
            steps = self._ai_optimize_field_grouping(field_analyses, model_class.__name__)
        else:
            steps = self._group_fields_into_steps(field_analyses, config)
        
        # Create workflow definition
        workflow_name = f"{model_class.__name__.lower()}_workflow"
        workflow_def = WorkflowDefinition(
            name=workflow_name,
            description=f"Generated workflow for {model_class.__name__}",
            version="1.0",
            steps=steps,
            allow_navigation=config.auto_generate_navigation
        )
        
        # Apply AI optimization if enabled
        if config.enable_ai_optimization:
            workflow_def = self._ai_optimize_workflow(workflow_def)
            
        return workflow_def

    def _analyze_model_fields(self, model_class: 'DeclarativeMeta') -> List[FieldAnalysis]:
        """Analyze model fields for workflow generation."""
        
        inspector = sqla_inspect(model_class)
        field_analyses = []
        
        for column_name, column in inspector.columns.items():
            # Skip audit and system fields
            if column_name in ['id', 'created_on', 'changed_on', 'created_by_fk', 'changed_by_fk']:
                continue
                
            field_type = column.type.__class__.__name__
            required = not column.nullable and column.default is None
            
            # Analyze field complexity and grouping
            analyzer = self.field_analyzers.get(field_type, lambda col: (1.0, 'basic_info', []))
            complexity, grouping_hint, validation_rules = analyzer(column)
            
            # Check for relationships
            relationship_type = None
            for rel_name, rel in inspector.relationships.items():
                if hasattr(rel, 'local_columns') and column in rel.local_columns:
                    relationship_type = 'foreign_key'
                    complexity += 0.5
                    grouping_hint = 'relationships'
                    break
            
            field_analysis = FieldAnalysis(
                name=column_name,
                field_type=field_type,
                required=required,
                relationship_type=relationship_type,
                complexity_score=complexity,
                grouping_hint=grouping_hint,
                validation_rules=validation_rules,
                default_value=column.default.arg if column.default else None
            )
            
            field_analyses.append(field_analysis)
            
        return field_analyses

    def _group_fields_into_steps(self, field_analyses: List[FieldAnalysis], 
                               config: GenerationConfig) -> List[WorkflowStepDefinition]:
        """Group fields into workflow steps based on strategy."""
        
        if config.grouping_strategy == FieldGroupingStrategy.LOGICAL_GROUPS:
            return self._group_by_logical_groups(field_analyses, config)
        elif config.grouping_strategy == FieldGroupingStrategy.FIELD_COUNT:
            return self._group_by_field_count(field_analyses, config)
        elif config.grouping_strategy == FieldGroupingStrategy.COMPLEXITY_BASED:
            return self._group_by_complexity(field_analyses, config)
        elif config.grouping_strategy == FieldGroupingStrategy.RELATIONSHIP_BASED:
            return self._group_by_relationships(field_analyses, config)
        else:
            return self._group_by_logical_groups(field_analyses, config)

    def _group_by_logical_groups(self, field_analyses: List[FieldAnalysis], 
                               config: GenerationConfig) -> List[WorkflowStepDefinition]:
        """Group fields by logical groupings."""
        
        # Group fields by their grouping hints
        groups = {}
        for field in field_analyses:
            group_name = field.grouping_hint or 'basic_info'
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(field)
        
        steps = []
        step_id = 1
        
        # Define logical order for groups
        group_order = [
            'basic_info', 'contact_info', 'address_info', 'employment_info',
            'financial_info', 'preferences', 'relationships', 'detailed_info',
            'security_info', 'legal_info', 'audit_info'
        ]
        
        for group_name in group_order:
            if group_name in groups:
                fields = groups[group_name]
                
                # Split large groups
                while len(fields) > config.max_fields_per_step:
                    chunk = fields[:config.max_fields_per_step]
                    fields = fields[config.max_fields_per_step:]
                    
                    step = WorkflowStepDefinition(
                        id=f"step_{step_id}",
                        name=self._format_group_name(group_name) + (f" ({step_id})" if step_id > 1 else ""),
                        step_type=WorkflowStepType.FORM,
                        form_fields=[field.name for field in chunk],
                        required_role=None,
                        auto_save=True
                    )
                    steps.append(step)
                    step_id += 1
                
                if fields:  # Remaining fields
                    step = WorkflowStepDefinition(
                        id=f"step_{step_id}",
                        name=self._format_group_name(group_name),
                        step_type=WorkflowStepType.FORM,
                        form_fields=[field.name for field in fields],
                        required_role=None,
                        auto_save=True
                    )
                    steps.append(step)
                    step_id += 1
                
                del groups[group_name]
        
        # Handle remaining ungrouped fields
        remaining_fields = []
        for group_fields in groups.values():
            remaining_fields.extend(group_fields)
            
        if remaining_fields:
            step = WorkflowStepDefinition(
                id=f"step_{step_id}",
                name="Additional Information",
                step_type=WorkflowStepType.FORM,
                form_fields=[field.name for field in remaining_fields],
                required_role=None,
                auto_save=True
            )
            steps.append(step)
        
        # Add validation step if configured
        if config.include_validation_steps and len(steps) > 1:
            validation_step = WorkflowStepDefinition(
                id=f"step_{len(steps) + 1}",
                name="Review and Validate",
                step_type=WorkflowStepType.VALIDATION,
                form_fields=[],
                required_role=None,
                auto_save=False
            )
            steps.append(validation_step)
        
        return steps

    def _group_by_field_count(self, field_analyses: List[FieldAnalysis], 
                            config: GenerationConfig) -> List[WorkflowStepDefinition]:
        """Group fields by maximum count per step."""
        
        steps = []
        step_id = 1
        
        for i in range(0, len(field_analyses), config.max_fields_per_step):
            chunk = field_analyses[i:i + config.max_fields_per_step]
            
            step = WorkflowStepDefinition(
                id=f"step_{step_id}",
                name=f"Step {step_id}",
                step_type=WorkflowStepType.FORM,
                form_fields=[field.name for field in chunk],
                required_role=None,
                auto_save=True
            )
            steps.append(step)
            step_id += 1
            
        return steps

    def _group_by_complexity(self, field_analyses: List[FieldAnalysis], 
                           config: GenerationConfig) -> List[WorkflowStepDefinition]:
        """Group fields by complexity score."""
        
        # Sort fields by complexity
        sorted_fields = sorted(field_analyses, key=lambda f: f.complexity_score)
        
        steps = []
        step_id = 1
        current_step_fields = []
        current_complexity = 0.0
        max_complexity_per_step = 5.0
        
        for field in sorted_fields:
            if (len(current_step_fields) >= config.max_fields_per_step or 
                current_complexity + field.complexity_score > max_complexity_per_step):
                
                if current_step_fields:
                    step = WorkflowStepDefinition(
                        id=f"step_{step_id}",
                        name=f"Step {step_id}",
                        step_type=WorkflowStepType.FORM,
                        form_fields=[field.name for field in current_step_fields],
                        required_role=None,
                        auto_save=True
                    )
                    steps.append(step)
                    step_id += 1
                    current_step_fields = []
                    current_complexity = 0.0
            
            current_step_fields.append(field)
            current_complexity += field.complexity_score
        
        # Add remaining fields
        if current_step_fields:
            step = WorkflowStepDefinition(
                id=f"step_{step_id}",
                name=f"Step {step_id}",
                step_type=WorkflowStepType.FORM,
                form_fields=[field.name for field in current_step_fields],
                required_role=None,
                auto_save=True
            )
            steps.append(step)
            
        return steps

    def _group_by_relationships(self, field_analyses: List[FieldAnalysis], 
                              config: GenerationConfig) -> List[WorkflowStepDefinition]:
        """Group fields by relationship dependencies."""
        
        # Separate regular fields from relationship fields
        regular_fields = [f for f in field_analyses if not f.relationship_type]
        relationship_fields = [f for f in field_analyses if f.relationship_type]
        
        steps = []
        step_id = 1
        
        # Create steps for regular fields first
        if regular_fields:
            regular_steps = self._group_by_logical_groups(regular_fields, config)
            steps.extend(regular_steps)
            step_id = len(steps) + 1
        
        # Add relationship fields as separate step
        if relationship_fields:
            step = WorkflowStepDefinition(
                id=f"step_{step_id}",
                name="Relationships",
                step_type=WorkflowStepType.FORM,
                form_fields=[field.name for field in relationship_fields],
                required_role=None,
                auto_save=True
            )
            steps.append(step)
            
        return steps

    def _ai_optimize_field_grouping(self, field_analyses: List[FieldAnalysis], 
                                  model_name: str) -> List[WorkflowStepDefinition]:
        """Use AI to optimize field grouping."""
        
        try:
            import requests
            
            # Prepare context for AI
            fields_info = []
            for field in field_analyses:
                fields_info.append({
                    'name': field.name,
                    'type': field.field_type,
                    'required': field.required,
                    'complexity': field.complexity_score,
                    'grouping_hint': field.grouping_hint
                })
            
            ollama_config = current_app.config.get('OLLAMA_HOST', 'http://localhost:11434')
            model = current_app.config.get('OLLAMA_MODEL', 'gpt-oss')
            
            prompt = f"""
            You are a workflow design expert. Given the following model fields for {model_name}, 
            suggest an optimal grouping of fields into workflow steps that would provide the best user experience.

            Fields:
            {json.dumps(fields_info, indent=2)}

            Please suggest 3-6 logical steps with 3-5 fields each. Consider:
            - Logical flow and dependencies
            - User experience and cognitive load
            - Natural progression of information gathering
            - Related fields should be grouped together

            Return your response as a JSON array of steps with this format:
            [
              {{"name": "Step Name", "fields": ["field1", "field2"], "description": "Brief description"}},
              ...
            ]
            """

            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3}
            }

            response = requests.post(f"{ollama_config}/api/generate", json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '')
                
                # Try to extract JSON from response
                try:
                    # Find JSON in the response
                    json_match = re.search(r'\[.*\]', content, re.DOTALL)
                    if json_match:
                        ai_steps = json.loads(json_match.group())
                        
                        # Convert AI suggestions to WorkflowStepDefinition
                        steps = []
                        for i, ai_step in enumerate(ai_steps):
                            step = WorkflowStepDefinition(
                                id=f"step_{i+1}",
                                name=ai_step.get('name', f"Step {i+1}"),
                                step_type=WorkflowStepType.FORM,
                                form_fields=ai_step.get('fields', []),
                                description=ai_step.get('description'),
                                auto_save=True
                            )
                            steps.append(step)
                        
                        return steps
                        
                except (json.JSONDecodeError, KeyError):
                    log.warning("Failed to parse AI response for field grouping")
                    
        except Exception as e:
            log.error(f"Error in AI field grouping: {e}")
        
        # Fallback to logical grouping
        config = GenerationConfig(
            generation_type=GenerationType.MODEL_DRIVEN,
            grouping_strategy=FieldGroupingStrategy.LOGICAL_GROUPS
        )
        return self._group_by_logical_groups(field_analyses, config)

    def _ai_optimize_workflow(self, workflow_def: WorkflowDefinition) -> WorkflowDefinition:
        """Use AI to optimize the entire workflow."""
        
        try:
            import requests
            
            ollama_config = current_app.config.get('OLLAMA_HOST', 'http://localhost:11434')
            model = current_app.config.get('OLLAMA_MODEL', 'gpt-oss')
            
            # Prepare workflow context
            steps_info = []
            for step in workflow_def.steps:
                steps_info.append({
                    'name': step.name,
                    'fields': step.form_fields,
                    'type': step.step_type.value if step.step_type else 'form'
                })
            
            prompt = f"""
            Review this workflow definition and suggest improvements for better user experience:

            Workflow: {workflow_def.name}
            Steps: {json.dumps(steps_info, indent=2)}

            Please suggest:
            1. Better step names if needed
            2. Optimal step sequence
            3. Any missing validation or approval steps
            4. Improvements to user flow

            Return suggestions as a brief list of improvements.
            """

            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.5}
            }

            response = requests.post(f"{ollama_config}/api/generate", json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                suggestions = result.get('response', '')
                
                # Store AI suggestions in workflow description
                workflow_def.description += f"\n\nAI Optimization Suggestions:\n{suggestions}"
                
        except Exception as e:
            log.error(f"Error in AI workflow optimization: {e}")
        
        return workflow_def

    def _format_group_name(self, group_name: str) -> str:
        """Format group name for display."""
        return group_name.replace('_', ' ').title()

    def generate_from_template(self, template_name: str, model_class: 'DeclarativeMeta') -> WorkflowDefinition:
        """Generate workflow from template."""
        
        if template_name not in self.templates:
            raise ValueError(f"Template '{template_name}' not found")
        
        template = self.templates[template_name]
        
        # Check if template is applicable to model
        model_name = model_class.__name__
        if not any(applicable in model_name for applicable in template.applicable_models):
            log.warning(f"Template '{template_name}' may not be suitable for model '{model_name}'")
        
        # Get model field names
        inspector = sqla_inspect(model_class)
        model_fields = set(inspector.columns.keys())
        
        steps = []
        for i, template_step in enumerate(template.steps):
            # Filter template fields to only include those in the model
            available_fields = [field for field in template_step['fields'] if field in model_fields]
            
            if available_fields:  # Only create step if it has valid fields
                step = WorkflowStepDefinition(
                    id=f"step_{i+1}",
                    name=template_step['name'],
                    step_type=WorkflowStepType.APPROVAL if template_step.get('step_type') == 'approval' else WorkflowStepType.FORM,
                    form_fields=available_fields,
                    required_role=template_step.get('required_role'),
                    auto_save=template_step.get('auto_save', True)
                )
                steps.append(step)
        
        workflow_name = f"{model_name.lower()}_{template_name}"
        workflow_def = WorkflowDefinition(
            name=workflow_name,
            description=f"{template.description} for {model_name}",
            version="1.0",
            steps=steps,
            allow_navigation=True
        )
        
        return workflow_def

    def suggest_workflow_improvements(self, workflow_def: WorkflowDefinition) -> List[str]:
        """Suggest improvements for an existing workflow using AI."""
        
        try:
            import requests
            
            ollama_config = current_app.config.get('OLLAMA_HOST', 'http://localhost:11434')
            model = current_app.config.get('OLLAMA_MODEL', 'gpt-oss')
            
            # Analyze current workflow
            analysis = {
                'total_steps': len(workflow_def.steps),
                'total_fields': sum(len(step.form_fields or []) for step in workflow_def.steps),
                'avg_fields_per_step': sum(len(step.form_fields or []) for step in workflow_def.steps) / len(workflow_def.steps) if workflow_def.steps else 0,
                'step_names': [step.name for step in workflow_def.steps]
            }
            
            prompt = f"""
            Analyze this workflow and suggest specific improvements:

            Workflow: {workflow_def.name}
            Total Steps: {analysis['total_steps']}
            Total Fields: {analysis['total_fields']}
            Average Fields per Step: {analysis['avg_fields_per_step']:.1f}
            Step Names: {analysis['step_names']}

            Suggest 3-5 specific improvements for:
            - User experience
            - Workflow efficiency
            - Step organization
            - Navigation flow

            Format as numbered list.
            """

            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.6}
            }

            response = requests.post(f"{ollama_config}/api/generate", json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '')
                
                # Parse suggestions
                lines = content.split('\n')
                suggestions = []
                
                for line in lines:
                    line = line.strip()
                    if line and (line[0].isdigit() or line.startswith('-') or line.startswith('*')):
                        cleaned = line.lstrip('0123456789.-* ')
                        if cleaned:
                            suggestions.append(cleaned)
                
                return suggestions[:5]  # Return top 5 suggestions
                
        except Exception as e:
            log.error(f"Error generating workflow suggestions: {e}")
        
        return [
            "Consider adding progress indicators between steps",
            "Review field grouping for better logical flow",
            "Add validation steps for data quality",
            "Implement auto-save functionality",
            "Consider parallel processing for independent steps"
        ]

    def auto_generate_workflow(self, model_class: 'DeclarativeMeta', 
                             generation_type: GenerationType = GenerationType.HYBRID,
                             template_name: Optional[str] = None) -> WorkflowDefinition:
        """Auto-generate workflow with intelligent defaults."""
        
        model_name = model_class.__name__
        
        # Try template-based generation first if template specified
        if template_name and generation_type in [GenerationType.TEMPLATE_BASED, GenerationType.HYBRID]:
            try:
                return self.generate_from_template(template_name, model_class)
            except ValueError:
                log.warning(f"Template '{template_name}' not found, falling back to model-driven generation")
        
        # Try to find suitable template based on model name
        if generation_type in [GenerationType.AI_SUGGESTED, GenerationType.HYBRID]:
            for template_name, template in self.templates.items():
                if any(applicable.lower() in model_name.lower() for applicable in template.applicable_models):
                    log.info(f"Auto-selected template '{template_name}' for model '{model_name}'")
                    return self.generate_from_template(template_name, model_class)
        
        # Fall back to model-driven generation
        config = GenerationConfig(
            generation_type=GenerationType.MODEL_DRIVEN,
            grouping_strategy=FieldGroupingStrategy.AI_OPTIMIZED if generation_type == GenerationType.AI_SUGGESTED else FieldGroupingStrategy.LOGICAL_GROUPS,
            enable_ai_optimization=True
        )
        
        return self.generate_workflow_from_model(model_class, config)


# Global generator instance
_auto_generator = None


def get_auto_generator() -> WorkflowAutoGenerator:
    """Get the global auto generator instance."""
    global _auto_generator
    if _auto_generator is None:
        _auto_generator = WorkflowAutoGenerator()
    return _auto_generator


# Convenience functions
def generate_workflow_for_model(model_class: 'DeclarativeMeta', 
                               generation_type: GenerationType = GenerationType.HYBRID,
                               template_name: Optional[str] = None) -> WorkflowDefinition:
    """Generate workflow for a model class."""
    generator = get_auto_generator()
    return generator.auto_generate_workflow(model_class, generation_type, template_name)


def register_workflow_template(template: WorkflowTemplate):
    """Register a new workflow template."""
    generator = get_auto_generator()
    generator.templates[template.name] = template


def get_available_templates() -> List[str]:
    """Get list of available workflow templates."""
    generator = get_auto_generator()
    return list(generator.templates.keys())


# CLI command for generating workflows
def register_workflow_cli_commands(app):
    """Register CLI commands for workflow generation."""
    
    @app.cli.command('generate-workflow')
    @app.cli.argument('model_name')
    @app.cli.option('--template', help='Template name to use')
    @app.cli.option('--type', default='hybrid', help='Generation type')
    def generate_workflow_cli(model_name, template, type):
        """Generate workflow for a model via CLI."""
        from flask_appbuilder import Model
        
        # Find model class
        model_class = None
        for cls in Model.__subclasses__():
            if cls.__name__.lower() == model_name.lower():
                model_class = cls
                break
        
        if not model_class:
            print(f"Model '{model_name}' not found")
            return
        
        # Generate workflow
        try:
            generation_type = GenerationType(type)
        except ValueError:
            generation_type = GenerationType.HYBRID
        
        workflow_def = generate_workflow_for_model(model_class, generation_type, template)
        
        # Register with engine
        engine = get_workflow_engine()
        engine.register_workflow(workflow_def)
        
        print(f"Generated workflow '{workflow_def.name}' with {len(workflow_def.steps)} steps")
        for i, step in enumerate(workflow_def.steps, 1):
            print(f"  Step {i}: {step.name} ({len(step.form_fields or [])} fields)")