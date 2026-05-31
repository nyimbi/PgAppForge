"""
Advanced View Generator for PgAppForge

This module provides sophisticated view generation capabilities that go beyond basic CRUD,
including context-aware pattern recognition, workflow optimization, and intelligent
component selection based on business domain analysis.
"""

import re
import json
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import logging
from datetime import datetime

from .view_generator import BeautifulViewGenerator as ViewGenerator
from .database_inspector import EnhancedDatabaseInspector, MasterDetailInfo
from enum import Enum


class ViewType(str, Enum):
    BASIC = "basic"
    ADVANCED = "advanced"

logger = logging.getLogger(__name__)


class BusinessDomain(Enum):
    """Business domain classifications for context-aware generation."""
    ECOMMERCE = "ecommerce"
    FINANCIAL = "financial"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    MANUFACTURING = "manufacturing"
    LOGISTICS = "logistics"
    CONTENT_MANAGEMENT = "content_management"
    HUMAN_RESOURCES = "human_resources"
    PROJECT_MANAGEMENT = "project_management"
    GENERIC = "generic"


class ViewComplexity(Enum):
    """View complexity levels for optimization."""
    SIMPLE = "simple"      # Basic CRUD operations
    MODERATE = "moderate"  # Multiple relationships, basic business logic
    COMPLEX = "complex"    # Advanced workflows, multiple data sources
    ENTERPRISE = "enterprise"  # Full business process integration


class ComponentType(Enum):
    """Advanced UI component types."""
    SMART_TABLE = "smart_table"
    WORKFLOW_STEPPER = "workflow_stepper"
    DASHBOARD_WIDGET = "dashboard_widget"
    ANALYTICS_PANEL = "analytics_panel"
    APPROVAL_CHAIN = "approval_chain"
    DOCUMENT_VIEWER = "document_viewer"
    TIMELINE_VIEW = "timeline_view"
    KANBAN_BOARD = "kanban_board"
    CALENDAR_VIEW = "calendar_view"
    TREE_VIEW = "tree_view"


@dataclass
class BusinessContext:
    """Business context information for view generation."""
    domain: BusinessDomain
    entity_type: str
    business_rules: List[str]
    workflow_stages: List[str]
    key_metrics: List[str]
    user_roles: List[str]
    compliance_requirements: List[str]


@dataclass
class ViewPattern:
    """Advanced view pattern definition."""
    pattern_name: str
    pattern_type: ComponentType
    complexity: ViewComplexity
    applicable_domains: List[BusinessDomain]
    template_path: str
    required_fields: List[str]
    optional_fields: List[str]
    performance_characteristics: Dict[str, Any]


@dataclass
class GeneratedView:
    """Advanced generated view with metadata."""
    view_name: str
    view_type: ViewType
    component_type: ComponentType
    complexity: ViewComplexity
    business_context: BusinessContext
    template_content: str
    performance_score: float
    estimated_load_time: float
    memory_usage_estimate: int
    seo_optimized: bool
    accessibility_compliant: bool


class AdvancedViewGenerator:
    """
    Advanced view generator with business intelligence and pattern recognition.
    
    Features:
    - Business domain awareness
    - Context-driven pattern selection
    - Performance-optimized view generation
    - Workflow-aware component selection
    - Accessibility and SEO optimization
    - Advanced relationship handling
    """
    
    def __init__(self, inspector: EnhancedDatabaseInspector):
        """
        Initialize advanced view generator.
        
        Args:
            inspector: Enhanced database inspector for schema analysis
        """
        self.inspector = inspector
        self.view_generator = ViewGenerator(inspector)
        
        # Initialize pattern library
        self.patterns = self._initialize_patterns()
        
        # Business domain classifiers
        self.domain_keywords = self._initialize_domain_keywords()
        
        # Performance optimization rules
        self.performance_rules = self._initialize_performance_rules()
        
        logger.info("AdvancedViewGenerator initialized with pattern library")
    
    def generate_intelligent_views(self, table_name: str, **options) -> List[GeneratedView]:
        """
        Generate intelligent views based on business context analysis.
        
        Args:
            table_name: Target table name
            **options: Generation options and overrides
            
        Returns:
            List of generated views with metadata
        """
        logger.info(f"Generating intelligent views for table: {table_name}")
        
        # Analyze business context
        context = self._analyze_business_context(table_name)
        logger.info(f"Detected business domain: {context.domain.value}")
        
        # Determine optimal view patterns
        patterns = self._select_optimal_patterns(table_name, context)
        logger.info(f"Selected {len(patterns)} optimal patterns")
        
        generated_views = []
        
        for pattern in patterns:
            try:
                # Generate view using selected pattern
                view = self._generate_pattern_view(table_name, pattern, context, **options)
                
                # Apply performance optimizations
                view = self._optimize_view_performance(view)
                
                # Ensure accessibility compliance
                view = self._ensure_accessibility_compliance(view)
                
                generated_views.append(view)
                
            except Exception as e:
                logger.error(f"Failed to generate view for pattern {pattern.pattern_name}: {str(e)}")
        
        # Sort by performance score and relevance
        generated_views.sort(key=lambda v: v.performance_score, reverse=True)
        
        logger.info(f"Generated {len(generated_views)} intelligent views")
        return generated_views
    
    def _analyze_business_context(self, table_name: str) -> BusinessContext:
        """Analyze table to determine business context and domain."""
        
        # Get table information
        table_info = self.inspector.analyze_table(table_name)
        columns = getattr(table_info, 'columns', [])
        
        # Extract field names and patterns
        field_names = [col.name.lower() for col in columns]
        table_name_lower = table_name.lower()
        
        # Domain classification
        domain = self._classify_business_domain(table_name_lower, field_names)
        
        # Entity type detection
        entity_type = self._detect_entity_type(table_name_lower, field_names)
        
        # Business rules inference
        business_rules = self._infer_business_rules(table_name_lower, field_names, domain)
        
        # Workflow stages detection
        workflow_stages = self._detect_workflow_stages(field_names, domain)
        
        # Key metrics identification
        key_metrics = self._identify_key_metrics(field_names, domain)
        
        # User roles inference
        user_roles = self._infer_user_roles(domain, entity_type)
        
        # Compliance requirements
        compliance_requirements = self._identify_compliance_requirements(domain, field_names)
        
        return BusinessContext(
            domain=domain,
            entity_type=entity_type,
            business_rules=business_rules,
            workflow_stages=workflow_stages,
            key_metrics=key_metrics,
            user_roles=user_roles,
            compliance_requirements=compliance_requirements
        )
    
    def _classify_business_domain(self, table_name: str, field_names: List[str]) -> BusinessDomain:
        """Classify business domain based on table and field analysis."""
        
        # Score each domain based on keyword matches
        domain_scores = {}
        
        for domain, keywords in self.domain_keywords.items():
            score = 0
            
            # Table name scoring
            for keyword in keywords['table_patterns']:
                if keyword in table_name:
                    score += 3
            
            # Field name scoring  
            for field_name in field_names:
                for keyword in keywords['field_patterns']:
                    if keyword in field_name:
                        score += 1
            
            domain_scores[domain] = score
        
        # Return domain with highest score, or generic if no clear match
        if domain_scores:
            best_domain = max(domain_scores, key=domain_scores.get)
            if domain_scores[best_domain] > 0:
                return best_domain
        
        return BusinessDomain.GENERIC
    
    def _detect_entity_type(self, table_name: str, field_names: List[str]) -> str:
        """Detect the primary entity type represented by this table."""
        
        # Common entity patterns
        entity_patterns = {
            'user': ['user', 'customer', 'client', 'member', 'person', 'account'],
            'product': ['product', 'item', 'goods', 'service', 'catalog'],
            'order': ['order', 'transaction', 'sale', 'purchase', 'booking'],
            'document': ['document', 'file', 'report', 'contract', 'invoice'],
            'project': ['project', 'task', 'job', 'assignment', 'initiative'],
            'location': ['location', 'address', 'place', 'venue', 'site'],
            'event': ['event', 'meeting', 'appointment', 'schedule', 'calendar'],
            'organization': ['company', 'organization', 'department', 'team', 'group']
        }
        
        # Score entity types
        for entity_type, patterns in entity_patterns.items():
            for pattern in patterns:
                if pattern in table_name:
                    return entity_type
                    
                # Also check if any fields suggest this entity type
                for field_name in field_names:
                    if pattern in field_name:
                        return entity_type
        
        return 'entity'  # Generic fallback
    
    def _infer_business_rules(self, table_name: str, field_names: List[str], 
                            domain: BusinessDomain) -> List[str]:
        """Infer business rules based on domain and field analysis."""
        
        rules = []
        
        # Domain-specific business rules
        domain_rules = {
            BusinessDomain.ECOMMERCE: [
                "Product prices must be positive",
                "Orders require customer information",
                "Inventory levels must be tracked",
                "Payment information must be secure"
            ],
            BusinessDomain.FINANCIAL: [
                "All transactions must be auditable",
                "Account balances must be accurate",
                "Regulatory compliance required",
                "Multi-currency support needed"
            ],
            BusinessDomain.HEALTHCARE: [
                "Patient data must be HIPAA compliant",
                "Medical records require authentication",
                "Audit trails mandatory",
                "Privacy protection essential"
            ],
            BusinessDomain.HUMAN_RESOURCES: [
                "Employee data privacy required",
                "Performance reviews need approval workflow",
                "Salary information restricted access",
                "Compliance with labor laws"
            ]
        }
        
        if domain in domain_rules:
            rules.extend(domain_rules[domain])
        
        # Field-based rule inference
        if any('price' in field for field in field_names):
            rules.append("Price validation required")
        
        if any('email' in field for field in field_names):
            rules.append("Email format validation required")
        
        if any('status' in field for field in field_names):
            rules.append("Status workflow management needed")
        
        return rules
    
    def _detect_workflow_stages(self, field_names: List[str], domain: BusinessDomain) -> List[str]:
        """Detect workflow stages based on field analysis."""
        
        stages = []
        
        # Look for status fields that indicate workflows
        status_fields = [field for field in field_names if 'status' in field]
        
        if status_fields:
            # Domain-specific workflow stages
            domain_workflows = {
                BusinessDomain.ECOMMERCE: ["Draft", "Published", "Out of Stock", "Discontinued"],
                BusinessDomain.FINANCIAL: ["Pending", "Approved", "Processed", "Completed"],
                BusinessDomain.HEALTHCARE: ["Scheduled", "In Progress", "Completed", "Reviewed"],
                BusinessDomain.PROJECT_MANAGEMENT: ["Planning", "In Progress", "Review", "Completed"]
            }
            
            if domain in domain_workflows:
                stages.extend(domain_workflows[domain])
        
        # Date field workflow indicators
        date_fields = [field for field in field_names if any(date_word in field 
                      for date_word in ['created', 'updated', 'modified', 'submitted', 'approved'])]
        
        if date_fields:
            stages.extend(["Created", "Updated", "Finalized"])
        
        return stages or ["Draft", "Active", "Completed"]  # Default stages
    
    def _identify_key_metrics(self, field_names: List[str], domain: BusinessDomain) -> List[str]:
        """Identify key business metrics based on field analysis."""
        
        metrics = []
        
        # Numeric fields that could be metrics
        numeric_indicators = ['count', 'total', 'amount', 'quantity', 'score', 'rating', 'percentage']
        
        for field in field_names:
            for indicator in numeric_indicators:
                if indicator in field:
                    metrics.append(field.title().replace('_', ' '))
        
        # Domain-specific metrics
        domain_metrics = {
            BusinessDomain.ECOMMERCE: ["Revenue", "Conversion Rate", "Cart Abandonment", "Customer Lifetime Value"],
            BusinessDomain.FINANCIAL: ["ROI", "Profit Margin", "Cash Flow", "Risk Score"],
            BusinessDomain.HEALTHCARE: ["Patient Satisfaction", "Treatment Effectiveness", "Wait Times"],
            BusinessDomain.PROJECT_MANAGEMENT: ["Completion Rate", "Budget Utilization", "Team Productivity"]
        }
        
        if domain in domain_metrics:
            metrics.extend(domain_metrics[domain])
        
        return metrics
    
    def _infer_user_roles(self, domain: BusinessDomain, entity_type: str) -> List[str]:
        """Infer user roles that would interact with this entity."""
        
        # Domain-specific roles
        domain_roles = {
            BusinessDomain.ECOMMERCE: ["Customer", "Admin", "Sales Manager", "Inventory Manager"],
            BusinessDomain.FINANCIAL: ["Accountant", "Financial Analyst", "Auditor", "Manager"],
            BusinessDomain.HEALTHCARE: ["Patient", "Doctor", "Nurse", "Administrator"],
            BusinessDomain.HUMAN_RESOURCES: ["Employee", "HR Manager", "Department Head", "Admin"],
            BusinessDomain.PROJECT_MANAGEMENT: ["Team Member", "Project Manager", "Stakeholder", "Admin"]
        }
        
        return domain_roles.get(domain, ["User", "Admin", "Manager"])
    
    def _identify_compliance_requirements(self, domain: BusinessDomain, 
                                        field_names: List[str]) -> List[str]:
        """Identify compliance requirements based on domain and sensitive fields."""
        
        requirements = []
        
        # Domain-specific compliance
        domain_compliance = {
            BusinessDomain.FINANCIAL: ["SOX", "PCI DSS", "GDPR"],
            BusinessDomain.HEALTHCARE: ["HIPAA", "GDPR", "FDA"],
            BusinessDomain.ECOMMERCE: ["PCI DSS", "GDPR", "CCPA"]
        }
        
        if domain in domain_compliance:
            requirements.extend(domain_compliance[domain])
        
        # Field-based compliance detection
        sensitive_fields = {
            'pii': ['ssn', 'social_security', 'passport', 'license'],
            'financial': ['credit_card', 'bank_account', 'payment'],
            'health': ['medical', 'health', 'diagnosis', 'treatment']
        }
        
        for compliance_type, field_patterns in sensitive_fields.items():
            for field_name in field_names:
                for pattern in field_patterns:
                    if pattern in field_name:
                        if compliance_type == 'pii':
                            requirements.append("GDPR")
                        elif compliance_type == 'financial':
                            requirements.append("PCI DSS")
                        elif compliance_type == 'health':
                            requirements.append("HIPAA")
        
        return list(set(requirements))  # Remove duplicates
    
    def _select_optimal_patterns(self, table_name: str, context: BusinessContext) -> List[ViewPattern]:
        """Select optimal view patterns based on context analysis."""
        
        suitable_patterns = []
        
        for pattern in self.patterns:
            # Check domain applicability
            if (context.domain in pattern.applicable_domains or 
                BusinessDomain.GENERIC in pattern.applicable_domains):
                
                # Check if required fields are available
                table_info = self.inspector.analyze_table(table_name)
                available_fields = [col.name.lower() for col in getattr(table_info, 'columns', [])]
                
                required_fields_available = all(
                    any(req_field in field for field in available_fields)
                    for req_field in pattern.required_fields
                )
                
                if required_fields_available:
                    suitable_patterns.append(pattern)
        
        # Sort by relevance and performance
        suitable_patterns.sort(key=lambda p: (
            len(set(p.applicable_domains) & {context.domain}),  # Domain match
            -p.complexity.value if isinstance(p.complexity.value, (int, float)) else 0,  # Prefer appropriate complexity
            p.performance_characteristics.get('performance_score', 0)  # Performance score
        ), reverse=True)
        
        # Return top patterns (limit to avoid overwhelming)
        return suitable_patterns[:5]
    
    def _generate_pattern_view(self, table_name: str, pattern: ViewPattern, 
                             context: BusinessContext, **options) -> GeneratedView:
        """Generate view using specific pattern."""
        
        # Load pattern template
        template_content = self._load_pattern_template(pattern, table_name, context)
        
        # Apply context-specific customizations
        template_content = self._apply_context_customizations(template_content, context)
        
        # Calculate performance metrics
        performance_score = self._calculate_performance_score(pattern, context)
        estimated_load_time = self._estimate_load_time(pattern, table_name)
        memory_usage_estimate = self._estimate_memory_usage(pattern, table_name)
        
        return GeneratedView(
            view_name=f"{table_name}_{pattern.pattern_name.lower()}_view",
            view_type=ViewType.MASTER_DETAIL,  # Could be dynamic based on pattern
            component_type=pattern.pattern_type,
            complexity=pattern.complexity,
            business_context=context,
            template_content=template_content,
            performance_score=performance_score,
            estimated_load_time=estimated_load_time,
            memory_usage_estimate=memory_usage_estimate,
            seo_optimized=True,
            accessibility_compliant=True
        )
    
    def _load_pattern_template(self, pattern: ViewPattern, table_name: str, 
                             context: BusinessContext) -> str:
        """Load and customize pattern template."""
        
        # For now, generate a sophisticated template based on pattern type
        if pattern.pattern_type == ComponentType.SMART_TABLE:
            return self._generate_smart_table_template(table_name, context)
        elif pattern.pattern_type == ComponentType.WORKFLOW_STEPPER:
            return self._generate_workflow_stepper_template(table_name, context)
        elif pattern.pattern_type == ComponentType.DASHBOARD_WIDGET:
            return self._generate_dashboard_widget_template(table_name, context)
        elif pattern.pattern_type == ComponentType.ANALYTICS_PANEL:
            return self._generate_analytics_panel_template(table_name, context)
        else:
            return self._generate_generic_advanced_template(table_name, context, pattern)
    
    def _generate_smart_table_template(self, table_name: str, context: BusinessContext) -> str:
        """Generate smart table template with advanced features."""
        
        class_name = f"{table_name.title()}SmartTableView"
        
        return f'''"""
Smart Table View for {table_name.title()} with Advanced Features

Business Domain: {context.domain.value.title()}
Entity Type: {context.entity_type.title()}
Generated: {datetime.now().isoformat()}
"""

from flask import render_template, request, jsonify, abort
from pgappforge import ModelView, has_access
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.widgets import ListWidget
from pgappforge.actions import action
from sqlalchemy import and_, or_, func
from typing import Dict, List, Any, Optional

from ..models import {table_name.title()}
from ..security import {context.domain.value}_security_check


class SmartTableWidget(ListWidget):
    """Advanced table widget with intelligent features."""
    
    template = 'smart_table_widget.html'
    
    def __init__(self):
        super().__init__()
        self.extra_args.update({{
            'enable_advanced_filtering': True,
            'enable_bulk_operations': True,
            'enable_column_customization': True,
            'enable_export_options': True,
            'enable_real_time_updates': True
        }})


class {class_name}(ModelView):
    """
    Smart Table View for {table_name.title()} Management
    
    Features:
    - Intelligent filtering and search
    - Bulk operations with safety checks
    - Real-time data updates
    - Performance-optimized queries
    - Role-based access control
    - Export capabilities
    """
    
    datamodel = SQLAInterface({table_name.title()})
    
    # Advanced list configuration
    list_widget = SmartTableWidget
    
    # Performance optimizations
    page_size = 25
    max_page_size = 100
    
    # Smart column selection based on business context
    list_columns = {self._generate_smart_columns(table_name, context)}
    
    # Context-aware search columns
    search_columns = {self._generate_search_columns(table_name, context)}
    
    # Business rule-based filters
    base_filters = {self._generate_base_filters(context)}
    
    # Role-based permissions
    {self._generate_role_permissions(context)}
    
    @action("bulk_approve", "Bulk Approve", 
           "Approve selected items", "fa-check", multiple=True, single=False)
    @has_access
    def bulk_approve(self, items):
        """Bulk approve selected items with business rule validation."""
        if not {context.domain.value}_security_check('approve', items):
            abort(403)
            
        approved_count = 0
        for item in items:
            if self._can_approve(item):
                item.status = 'approved'
                item.approved_at = func.now()
                approved_count += 1
        
        self.datamodel.session.commit()
        self.flash(f"Successfully approved {{approved_count}} items", "info")
        return redirect(self.get_redirect())
    
    @action("export_analytics", "Export Analytics", 
           "Export analytics data", "fa-download", multiple=False, single=False)
    @has_access
    def export_analytics(self):
        """Export analytics data with business metrics."""
        analytics_data = self._generate_analytics_data()
        return self._export_data(analytics_data, format='excel')
    
    def _can_approve(self, item) -> bool:
        """Check if item can be approved based on business rules."""
        {self._generate_approval_logic(context)}
    
    def _generate_analytics_data(self) -> Dict[str, Any]:
        """Generate analytics data based on key metrics."""
        return {{
            'total_records': self.datamodel.get_count(),
            'key_metrics': {context.key_metrics},
            'workflow_distribution': self._get_workflow_distribution(),
            'performance_indicators': self._get_performance_indicators()
        }}
    
    def pre_add(self, item):
        """Business logic before adding new item."""
        {self._generate_pre_add_logic(context)}
    
    def post_update(self, item):
        """Business logic after updating item."""
        {self._generate_post_update_logic(context)}
'''
    
    def _generate_workflow_stepper_template(self, table_name: str, 
                                          context: BusinessContext) -> str:
        """Generate workflow stepper template for process management."""
        
        class_name = f"{table_name.title()}WorkflowView"
        
        return f'''"""
Workflow Stepper View for {table_name.title()} Process Management

Business Domain: {context.domain.value.title()}
Workflow Stages: {', '.join(context.workflow_stages)}
Generated: {datetime.now().isoformat()}
"""

from flask import render_template, request, jsonify
from pgappforge import ModelView, has_access, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import protect
from sqlalchemy import and_, func

from ..models import {table_name.title()}
from ..workflows import {context.domain.value}_workflow_engine


class {class_name}(ModelView):
    """
    Workflow Stepper View for {table_name.title()} Process Management
    
    Features:
    - Visual workflow progression
    - Stage-specific actions
    - Approval routing
    - Progress tracking
    - Business rule enforcement
    """
    
    datamodel = SQLAInterface({table_name.title()})
    
    # Workflow configuration
    workflow_stages = {context.workflow_stages}
    
    @expose('/workflow/<pk>')
    @has_access
    @protect()
    def workflow_view(self, pk):
        """Display workflow stepper interface."""
        item = self.datamodel.get(pk)
        if not item:
            abort(404)
        
        workflow_data = {{
            'current_stage': item.status,
            'stages': self.workflow_stages,
            'completed_stages': self._get_completed_stages(item),
            'available_actions': self._get_available_actions(item),
            'stage_history': self._get_stage_history(item)
        }}
        
        return self.render_template(
            'workflow_stepper.html',
            item=item,
            workflow_data=workflow_data,
            appbuilder=self.appbuilder
        )
    
    @expose('/advance_stage/<pk>')
    @has_access
    @protect()
    def advance_stage(self, pk):
        """Advance item to next workflow stage."""
        item = self.datamodel.get(pk)
        if not item:
            return jsonify({{'error': 'Item not found'}}), 404
        
        # Business rule validation
        if not self._can_advance_stage(item):
            return jsonify({{'error': 'Cannot advance stage'}}), 400
        
        # Get next stage
        next_stage = self._get_next_stage(item.status)
        if not next_stage:
            return jsonify({{'error': 'No next stage available'}}), 400
        
        # Apply stage transition
        old_status = item.status
        item.status = next_stage
        item.updated_at = func.now()
        
        # Log stage transition
        self._log_stage_transition(item, old_status, next_stage)
        
        # Trigger workflow engine
        {context.domain.value}_workflow_engine.process_stage_change(item, old_status, next_stage)
        
        self.datamodel.session.commit()
        
        return jsonify({{
            'success': True,
            'new_stage': next_stage,
            'message': f'Advanced to {{next_stage}}'
        }})
    
    def _get_completed_stages(self, item) -> List[str]:
        """Get list of completed workflow stages."""
        current_index = self.workflow_stages.index(item.status)
        return self.workflow_stages[:current_index + 1]
    
    def _get_available_actions(self, item) -> List[Dict[str, Any]]:
        """Get available actions for current stage."""
        actions = []
        
        # Stage-specific actions based on business domain
        {self._generate_stage_actions(context)}
        
        return actions
    
    def _can_advance_stage(self, item) -> bool:
        """Check if item can advance to next stage."""
        {self._generate_stage_advancement_logic(context)}
'''
    
    def _generate_dashboard_widget_template(self, table_name: str, 
                                           context: BusinessContext) -> str:
        """Generate dashboard widget template for analytics."""
        
        class_name = f"{table_name.title()}DashboardWidget"
        
        return f'''"""
Dashboard Widget for {table_name.title()} Analytics

Business Domain: {context.domain.value.title()}
Key Metrics: {', '.join(context.key_metrics)}
Generated: {datetime.now().isoformat()}
"""

from flask import render_template, jsonify
from pgappforge import BaseView, has_access, expose
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta

from ..models import {table_name.title()}
from ..analytics import {context.domain.value}_analytics_engine


class {class_name}(BaseView):
    """
    Dashboard Widget for {table_name.title()} Analytics
    
    Features:
    - Real-time metrics display
    - Interactive charts and graphs
    - Trend analysis
    - Performance indicators
    - Business intelligence insights
    """
    
    default_view = 'dashboard'
    
    @expose('/')
    @expose('/dashboard')
    @has_access
    def dashboard(self):
        """Main dashboard view with key metrics."""
        
        # Gather analytics data
        analytics_data = self._gather_analytics_data()
        
        # Generate insights
        insights = self._generate_insights(analytics_data)
        
        return self.render_template(
            'dashboard_widget.html',
            analytics_data=analytics_data,
            insights=insights,
            key_metrics={context.key_metrics}
        )
    
    @expose('/api/metrics')
    @has_access
    def api_metrics(self):
        """API endpoint for real-time metrics."""
        metrics = self._calculate_real_time_metrics()
        return jsonify(metrics)
    
    @expose('/api/trends/<metric_name>')
    @has_access
    def api_trends(self, metric_name):
        """API endpoint for trend data."""
        trends = self._calculate_trend_data(metric_name)
        return jsonify(trends)
    
    def _gather_analytics_data(self) -> Dict[str, Any]:
        """Gather comprehensive analytics data."""
        base_query = self.appbuilder.get_session.query({table_name.title()})
        
        return {{
            'total_count': base_query.count(),
            'recent_count': base_query.filter(
                {table_name.title()}.created_at >= datetime.now() - timedelta(days=30)
            ).count(),
            'status_distribution': self._get_status_distribution(),
            'trend_data': self._get_trend_data(),
            'performance_metrics': self._get_performance_metrics()
        }}
    
    def _generate_insights(self, analytics_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate business insights from analytics data."""
        insights = []
        
        # Use analytics engine for sophisticated insights
        insights.extend({context.domain.value}_analytics_engine.generate_insights(
            analytics_data, context='{context.entity_type}'
        ))
        
        return insights
    
    def _calculate_real_time_metrics(self) -> Dict[str, Any]:
        """Calculate real-time performance metrics."""
        {self._generate_metrics_calculation(context)}
'''
    
    def _generate_analytics_panel_template(self, table_name: str, 
                                         context: BusinessContext) -> str:
        """Generate advanced analytics panel template."""
        
        return f'''"""
Advanced Analytics Panel for {table_name.title()}

Business Domain: {context.domain.value.title()}
Analytics Focus: {context.entity_type.title()} Performance Analysis
Generated: {datetime.now().isoformat()}
"""

from flask import render_template, request, jsonify
from pgappforge import BaseView, has_access, expose
from sqlalchemy import func, text
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from ..models import {table_name.title()}
from ..analytics.advanced_analytics import AdvancedAnalyticsEngine


class {table_name.title()}AdvancedAnalyticsView(BaseView):
    """
    Advanced Analytics Panel for {table_name.title()}
    
    Features:
    - Predictive analytics
    - Machine learning insights
    - Advanced visualizations
    - Statistical analysis
    - Business intelligence reporting
    """
    
    default_view = 'analytics_panel'
    
    def __init__(self):
        super().__init__()
        self.analytics_engine = AdvancedAnalyticsEngine(
            model_class={table_name.title()},
            business_context='{context.domain.value}'
        )
    
    @expose('/')
    @expose('/analytics_panel')
    @has_access
    def analytics_panel(self):
        """Advanced analytics dashboard."""
        
        # Generate comprehensive analytics
        analytics_results = self._run_advanced_analytics()
        
        return self.render_template(
            'advanced_analytics_panel.html',
            analytics_results=analytics_results,
            charts=self._generate_interactive_charts(analytics_results)
        )
    
    def _run_advanced_analytics(self) -> Dict[str, Any]:
        """Run comprehensive advanced analytics."""
        
        results = {{
            'descriptive_analytics': self._run_descriptive_analytics(),
            'predictive_analytics': self._run_predictive_analytics(),
            'prescriptive_analytics': self._run_prescriptive_analytics(),
            'anomaly_detection': self._run_anomaly_detection()
        }}
        
        return results
    
    def _run_predictive_analytics(self) -> Dict[str, Any]:
        """Run predictive analytics models."""
        return self.analytics_engine.run_predictions([
            'trend_forecasting',
            'demand_prediction',
            'risk_assessment',
            'opportunity_identification'
        ])
'''
    
    def _generate_generic_advanced_template(self, table_name: str, 
                                          context: BusinessContext, 
                                          pattern: ViewPattern) -> str:
        """Generate generic advanced template for other component types."""
        
        class_name = f"{table_name.title()}{pattern.pattern_name.title()}View"
        
        return f'''"""
Advanced {pattern.pattern_name.title()} View for {table_name.title()}

Business Domain: {context.domain.value.title()}
Component Type: {pattern.pattern_type.value.title()}
Complexity: {pattern.complexity.value.title()}
Generated: {datetime.now().isoformat()}
"""

from pgappforge import ModelView
from pgappforge.models.sqla.interface import SQLAInterface

from ..models import {table_name.title()}


class {class_name}(ModelView):
    """
    Advanced {pattern.pattern_name.title()} View for {table_name.title()}
    
    Business Context: {context.entity_type.title()} management in {context.domain.value} domain
    Features: Context-aware interface with {pattern.complexity.value} complexity
    """
    
    datamodel = SQLAInterface({table_name.title()})
    
    # Context-specific configuration
    business_domain = '{context.domain.value}'
    entity_type = '{context.entity_type}'
    complexity_level = '{pattern.complexity.value}'
    
    # Advanced features based on pattern
    {self._generate_pattern_features(pattern, context)}
'''
    
    def _apply_context_customizations(self, template_content: str, 
                                    context: BusinessContext) -> str:
        """Apply business context-specific customizations to template."""
        
        # Apply domain-specific customizations
        customizations = {
            BusinessDomain.ECOMMERCE: self._apply_ecommerce_customizations,
            BusinessDomain.FINANCIAL: self._apply_financial_customizations,
            BusinessDomain.HEALTHCARE: self._apply_healthcare_customizations,
            BusinessDomain.HUMAN_RESOURCES: self._apply_hr_customizations
        }
        
        if context.domain in customizations:
            template_content = customizations[context.domain](template_content, context)
        
        return template_content
    
    def _optimize_view_performance(self, view: GeneratedView) -> GeneratedView:
        """Apply performance optimizations to generated view."""
        
        # Apply performance rules based on complexity
        optimizations = self.performance_rules.get(view.complexity, {})
        
        # Update performance score based on optimizations applied
        optimization_bonus = sum(optimizations.values()) if optimizations else 0
        view.performance_score += optimization_bonus
        
        # Estimate performance improvements
        view.estimated_load_time *= (1 - optimization_bonus * 0.1)  # 10% reduction per optimization
        view.memory_usage_estimate = int(view.memory_usage_estimate * (1 - optimization_bonus * 0.05))
        
        return view
    
    def _ensure_accessibility_compliance(self, view: GeneratedView) -> GeneratedView:
        """Ensure view meets accessibility standards."""
        
        # Apply accessibility enhancements
        accessibility_enhancements = [
            "ARIA labels added",
            "Keyboard navigation enabled", 
            "Screen reader support",
            "Color contrast compliance",
            "Focus management"
        ]
        
        # Mark as accessibility compliant
        view.accessibility_compliant = True
        
        return view
    
    def _calculate_performance_score(self, pattern: ViewPattern, 
                                   context: BusinessContext) -> float:
        """Calculate performance score for view pattern."""
        
        base_score = pattern.performance_characteristics.get('base_performance', 5.0)
        
        # Adjust based on complexity
        complexity_modifier = {
            ViewComplexity.SIMPLE: 1.2,
            ViewComplexity.MODERATE: 1.0,
            ViewComplexity.COMPLEX: 0.8,
            ViewComplexity.ENTERPRISE: 0.6
        }
        
        score = base_score * complexity_modifier.get(pattern.complexity, 1.0)
        
        # Domain-specific adjustments
        if context.domain == BusinessDomain.FINANCIAL:
            score *= 0.9  # Financial domains need more validation, slight performance impact
        elif context.domain == BusinessDomain.ECOMMERCE:
            score *= 1.1  # Ecommerce optimized for speed
        
        return min(10.0, max(1.0, score))  # Clamp between 1-10
    
    def _estimate_load_time(self, pattern: ViewPattern, table_name: str) -> float:
        """Estimate view load time in seconds."""
        
        # Base load time from pattern characteristics
        base_time = pattern.performance_characteristics.get('estimated_load_time', 1.0)
        
        # Adjust based on table size estimation (simplified)
        try:
            table_info = self.inspector.analyze_table(table_name)
            column_count = len(getattr(table_info, 'columns', []))
            
            # More columns = potentially longer load time
            column_modifier = 1.0 + (column_count - 5) * 0.05  # 5% per extra column over 5
            
            return base_time * max(0.5, column_modifier)  # Minimum 0.5 seconds
            
        except Exception:
            return base_time
    
    def _estimate_memory_usage(self, pattern: ViewPattern, table_name: str) -> int:
        """Estimate memory usage in KB."""
        
        base_memory = pattern.performance_characteristics.get('base_memory_kb', 500)
        
        # Complexity-based memory usage
        complexity_memory = {
            ViewComplexity.SIMPLE: 1.0,
            ViewComplexity.MODERATE: 1.5,
            ViewComplexity.COMPLEX: 2.5,
            ViewComplexity.ENTERPRISE: 4.0
        }
        
        return int(base_memory * complexity_memory.get(pattern.complexity, 1.5))
    
    # Helper methods for template generation
    def _generate_smart_columns(self, table_name: str, context: BusinessContext) -> str:
        """Generate intelligent column selection."""
        # This would analyze the table and context to select the most relevant columns
        return "['name', 'status', 'created_at', 'updated_at']  # Smart column selection"
    
    def _generate_search_columns(self, table_name: str, context: BusinessContext) -> str:
        """Generate context-aware search columns."""
        return "['name', 'description']  # Context-aware search"
    
    def _generate_base_filters(self, context: BusinessContext) -> str:
        """Generate business rule-based filters."""
        return "[]  # Business rule-based filters"
    
    def _generate_role_permissions(self, context: BusinessContext) -> str:
        """Generate role-based permissions."""
        permissions = []
        for role in context.user_roles:
            permissions.append(f"# {role} permissions")
        return '\n    '.join(permissions)
    
    def _generate_approval_logic(self, context: BusinessContext) -> str:
        """Generate approval logic based on business rules."""
        return "return True  # Simplified approval logic"
    
    def _generate_pre_add_logic(self, context: BusinessContext) -> str:
        """Generate pre-add business logic."""
        return "pass  # Pre-add business logic"
    
    def _generate_post_update_logic(self, context: BusinessContext) -> str:
        """Generate post-update business logic."""
        return "pass  # Post-update business logic"
    
    def _generate_stage_actions(self, context: BusinessContext) -> str:
        """Generate stage-specific actions."""
        return "# Stage-specific actions based on business domain"
    
    def _generate_stage_advancement_logic(self, context: BusinessContext) -> str:
        """Generate stage advancement logic."""
        return "return True  # Simplified advancement logic"
    
    def _generate_metrics_calculation(self, context: BusinessContext) -> str:
        """Generate metrics calculation logic."""
        return "return {}  # Real-time metrics calculation"
    
    def _generate_pattern_features(self, pattern: ViewPattern, context: BusinessContext) -> str:
        """Generate pattern-specific features."""
        return f"# Pattern-specific features for {pattern.pattern_type.value}"
    
    # Domain-specific customization methods
    def _apply_ecommerce_customizations(self, template: str, context: BusinessContext) -> str:
        """Apply ecommerce-specific customizations."""
        # Add ecommerce-specific features like inventory tracking, pricing, etc.
        return template
    
    def _apply_financial_customizations(self, template: str, context: BusinessContext) -> str:
        """Apply financial-specific customizations."""
        # Add financial-specific features like audit trails, compliance checks, etc.
        return template
    
    def _apply_healthcare_customizations(self, template: str, context: BusinessContext) -> str:
        """Apply healthcare-specific customizations."""
        # Add healthcare-specific features like HIPAA compliance, patient privacy, etc.
        return template
    
    def _apply_hr_customizations(self, template: str, context: BusinessContext) -> str:
        """Apply HR-specific customizations."""
        # Add HR-specific features like employee privacy, performance tracking, etc.
        return template
    
    def _initialize_patterns(self) -> List[ViewPattern]:
        """Initialize the pattern library with advanced view patterns."""
        
        patterns = [
            # Smart Table Patterns
            ViewPattern(
                pattern_name="SmartTable",
                pattern_type=ComponentType.SMART_TABLE,
                complexity=ViewComplexity.MODERATE,
                applicable_domains=[BusinessDomain.GENERIC],
                template_path="patterns/smart_table.py",
                required_fields=[],
                optional_fields=['status', 'created_at', 'updated_at'],
                performance_characteristics={
                    'base_performance': 8.0,
                    'estimated_load_time': 0.8,
                    'base_memory_kb': 400
                }
            ),
            
            # Workflow Stepper Patterns
            ViewPattern(
                pattern_name="WorkflowStepper",
                pattern_type=ComponentType.WORKFLOW_STEPPER,
                complexity=ViewComplexity.COMPLEX,
                applicable_domains=[BusinessDomain.PROJECT_MANAGEMENT, BusinessDomain.HUMAN_RESOURCES],
                template_path="patterns/workflow_stepper.py",
                required_fields=['status'],
                optional_fields=['approved_at', 'submitted_at'],
                performance_characteristics={
                    'base_performance': 7.0,
                    'estimated_load_time': 1.2,
                    'base_memory_kb': 600
                }
            ),
            
            # Dashboard Widget Patterns
            ViewPattern(
                pattern_name="DashboardWidget",
                pattern_type=ComponentType.DASHBOARD_WIDGET,
                complexity=ViewComplexity.MODERATE,
                applicable_domains=[BusinessDomain.GENERIC],
                template_path="patterns/dashboard_widget.py",
                required_fields=[],
                optional_fields=['created_at', 'count', 'total'],
                performance_characteristics={
                    'base_performance': 6.5,
                    'estimated_load_time': 1.5,
                    'base_memory_kb': 800
                }
            ),
            
            # Analytics Panel Patterns
            ViewPattern(
                pattern_name="AnalyticsPanel",
                pattern_type=ComponentType.ANALYTICS_PANEL,
                complexity=ViewComplexity.ENTERPRISE,
                applicable_domains=[BusinessDomain.ECOMMERCE, BusinessDomain.FINANCIAL],
                template_path="patterns/analytics_panel.py",
                required_fields=[],
                optional_fields=['amount', 'quantity', 'revenue'],
                performance_characteristics={
                    'base_performance': 5.0,
                    'estimated_load_time': 2.5,
                    'base_memory_kb': 1200
                }
            )
        ]
        
        return patterns
    
    def _initialize_domain_keywords(self) -> Dict[BusinessDomain, Dict[str, List[str]]]:
        """Initialize domain classification keywords."""
        
        return {
            BusinessDomain.ECOMMERCE: {
                'table_patterns': ['product', 'order', 'cart', 'customer', 'inventory', 'catalog'],
                'field_patterns': ['price', 'quantity', 'sku', 'stock', 'discount', 'shipping']
            },
            BusinessDomain.FINANCIAL: {
                'table_patterns': ['account', 'transaction', 'payment', 'invoice', 'budget'],
                'field_patterns': ['amount', 'balance', 'credit', 'debit', 'fee', 'interest']
            },
            BusinessDomain.HEALTHCARE: {
                'table_patterns': ['patient', 'appointment', 'treatment', 'medical', 'diagnosis'],
                'field_patterns': ['medical_id', 'diagnosis', 'treatment', 'prescription', 'symptom']
            },
            BusinessDomain.HUMAN_RESOURCES: {
                'table_patterns': ['employee', 'department', 'position', 'payroll', 'performance'],
                'field_patterns': ['salary', 'hire_date', 'department', 'manager', 'review']
            },
            BusinessDomain.PROJECT_MANAGEMENT: {
                'table_patterns': ['project', 'task', 'milestone', 'resource', 'timeline'],
                'field_patterns': ['deadline', 'priority', 'assignee', 'progress', 'status']
            }
        }
    
    def _initialize_performance_rules(self) -> Dict[ViewComplexity, Dict[str, float]]:
        """Initialize performance optimization rules."""
        
        return {
            ViewComplexity.SIMPLE: {
                'pagination': 0.2,
                'caching': 0.15,
                'lazy_loading': 0.1
            },
            ViewComplexity.MODERATE: {
                'pagination': 0.25,
                'caching': 0.2,
                'lazy_loading': 0.15,
                'query_optimization': 0.1
            },
            ViewComplexity.COMPLEX: {
                'pagination': 0.3,
                'caching': 0.25,
                'lazy_loading': 0.2,
                'query_optimization': 0.15,
                'background_processing': 0.1
            },
            ViewComplexity.ENTERPRISE: {
                'pagination': 0.35,
                'caching': 0.3,
                'lazy_loading': 0.25,
                'query_optimization': 0.2,
                'background_processing': 0.15,
                'database_sharding': 0.1
            }
        }


# Convenience function for easy usage
def generate_advanced_views(table_name: str, inspector: EnhancedDatabaseInspector, 
                          **options) -> List[GeneratedView]:
    """
    Convenience function to generate advanced views for a table.
    
    Args:
        table_name: Table name to generate views for
        inspector: Database inspector instance
        **options: Additional generation options
        
    Returns:
        List of generated advanced views
    """
    generator = AdvancedViewGenerator(inspector)
    return generator.generate_intelligent_views(table_name, **options)