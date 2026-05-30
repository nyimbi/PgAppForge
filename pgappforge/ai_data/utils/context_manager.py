"""
Business Context Manager

Provides domain-specific context, knowledge, and understanding for intelligent
data generation. Manages business rules, domain vocabularies, and contextual
relationships between entities.
"""

import logging
import json
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import re

logger = logging.getLogger(__name__)


@dataclass
class DomainContext:
    """Context information for a business domain."""
    domain: str
    description: str
    key_entities: List[str]
    common_relationships: List[Dict[str, str]]
    business_rules: List[str]
    data_characteristics: Dict[str, Any]
    vocabulary: Dict[str, List[str]]
    compliance_requirements: List[str] = None
    industry_standards: List[str] = None


@dataclass
class EntityContext:
    """Context information for a specific entity within a domain."""
    entity_name: str
    domain: str
    description: str
    typical_attributes: List[str]
    required_attributes: List[str]
    optional_attributes: List[str]
    validation_rules: List[Dict[str, Any]]
    business_constraints: List[str]
    relationship_roles: List[str]  # parent, child, peer, etc.


class BusinessContextManager:
    """
    Manages business context and domain knowledge for data generation.
    
    Provides:
    - Domain-specific vocabularies and terminologies
    - Business rule contexts
    - Entity relationship contexts
    - Industry compliance contexts
    - Data generation guidelines by domain
    """
    
    def __init__(self):
        self.domain_contexts: Dict[str, DomainContext] = {}
        self.entity_contexts: Dict[str, Dict[str, EntityContext]] = {}
        self.industry_vocabularies: Dict[str, Dict[str, List[str]]] = {}
        self.compliance_frameworks: Dict[str, Dict[str, Any]] = {}
        
        # Initialize built-in contexts
        self._initialize_contexts()
    
    def _initialize_contexts(self):
        """Initialize built-in domain and entity contexts."""
        
        self._init_ecommerce_context()
        self._init_finance_context()
        self._init_healthcare_context()
        self._init_hr_context()
        self._init_education_context()
        self._init_crm_context()
        self._init_real_estate_context()
        self._init_manufacturing_context()
        
        # Initialize compliance frameworks
        self._init_compliance_frameworks()
    
    def _init_ecommerce_context(self):
        """Initialize e-commerce domain context."""
        
        domain = 'ecommerce'
        
        context = DomainContext(
            domain=domain,
            description="E-commerce and retail business operations",
            key_entities=['customer', 'product', 'order', 'payment', 'inventory', 'category', 'review'],
            common_relationships=[
                {'type': 'one_to_many', 'parent': 'customer', 'child': 'order'},
                {'type': 'one_to_many', 'parent': 'order', 'child': 'order_item'},
                {'type': 'many_to_one', 'parent': 'product', 'child': 'order_item'},
                {'type': 'many_to_many', 'parent': 'product', 'child': 'category'},
                {'type': 'one_to_many', 'parent': 'product', 'child': 'review'}
            ],
            business_rules=[
                "Order total must equal sum of line items plus tax and shipping",
                "Inventory quantity cannot be negative",
                "Customer must exist before placing order",
                "Payment amount must match order total",
                "Product reviews can only be left by customers who purchased the product"
            ],
            data_characteristics={
                'seasonal_patterns': True,
                'price_sensitivity': True,
                'geographical_distribution': True,
                'customer_segmentation': True
            },
            vocabulary={
                'order_statuses': ['pending', 'processing', 'shipped', 'delivered', 'cancelled', 'returned'],
                'payment_methods': ['credit_card', 'paypal', 'apple_pay', 'google_pay', 'bank_transfer'],
                'product_categories': ['electronics', 'clothing', 'books', 'home', 'sports', 'automotive'],
                'shipping_methods': ['standard', 'expedited', 'overnight', 'two_day', 'pickup'],
                'return_reasons': ['defective', 'wrong_size', 'not_as_described', 'changed_mind', 'damaged']
            },
            compliance_requirements=['PCI_DSS', 'GDPR', 'CCPA'],
            industry_standards=['ISO_27001', 'SOC_2']
        )
        
        entities = {
            'customer': EntityContext(
                entity_name='customer',
                domain=domain,
                description="E-commerce customer entity",
                typical_attributes=['customer_id', 'email', 'first_name', 'last_name', 'phone', 'address', 'city', 'state', 'zip_code', 'country', 'date_joined', 'total_orders', 'total_spent', 'customer_segment'],
                required_attributes=['customer_id', 'email', 'first_name', 'last_name', 'date_joined'],
                optional_attributes=['phone', 'address', 'customer_segment', 'marketing_opt_in'],
                validation_rules=[
                    {'field': 'email', 'type': 'format', 'pattern': r'^[^@]+@[^@]+\.[^@]+$'},
                    {'field': 'total_spent', 'type': 'range', 'min': 0},
                    {'field': 'total_orders', 'type': 'range', 'min': 0}
                ],
                business_constraints=['email must be unique', 'customer_id must be unique'],
                relationship_roles=['parent']
            ),
            
            'product': EntityContext(
                entity_name='product',
                domain=domain,
                description="E-commerce product entity",
                typical_attributes=['product_id', 'name', 'description', 'price', 'cost', 'sku', 'category', 'brand', 'weight', 'dimensions', 'in_stock', 'quantity_available', 'created_date'],
                required_attributes=['product_id', 'name', 'price', 'sku'],
                optional_attributes=['description', 'brand', 'weight', 'dimensions'],
                validation_rules=[
                    {'field': 'price', 'type': 'range', 'min': 0},
                    {'field': 'quantity_available', 'type': 'range', 'min': 0},
                    {'field': 'sku', 'type': 'unique', 'constraint': True}
                ],
                business_constraints=['SKU must be unique', 'price must be greater than cost'],
                relationship_roles=['parent', 'child']
            ),
            
            'order': EntityContext(
                entity_name='order',
                domain=domain,
                description="E-commerce order entity",
                typical_attributes=['order_id', 'customer_id', 'order_date', 'status', 'subtotal', 'tax', 'shipping_cost', 'total', 'payment_method', 'shipping_address', 'billing_address'],
                required_attributes=['order_id', 'customer_id', 'order_date', 'status', 'total'],
                optional_attributes=['tax', 'shipping_cost', 'payment_method'],
                validation_rules=[
                    {'field': 'total', 'type': 'calculated', 'formula': 'subtotal + tax + shipping_cost'},
                    {'field': 'order_date', 'type': 'date', 'constraint': 'not_future'},
                    {'field': 'status', 'type': 'enum', 'values': ['pending', 'processing', 'shipped', 'delivered', 'cancelled']}
                ],
                business_constraints=['customer_id must reference valid customer', 'total must equal subtotal + tax + shipping'],
                relationship_roles=['child', 'parent']
            )
        }
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = entities
    
    def _init_finance_context(self):
        """Initialize finance domain context."""
        
        domain = 'finance'
        
        context = DomainContext(
            domain=domain,
            description="Financial services and banking operations",
            key_entities=['account', 'customer', 'transaction', 'loan', 'investment', 'card'],
            common_relationships=[
                {'type': 'one_to_many', 'parent': 'customer', 'child': 'account'},
                {'type': 'one_to_many', 'parent': 'account', 'child': 'transaction'},
                {'type': 'one_to_many', 'parent': 'customer', 'child': 'loan'},
                {'type': 'one_to_many', 'parent': 'customer', 'child': 'card'}
            ],
            business_rules=[
                "Account balance must equal sum of all transactions",
                "Debit transactions decrease balance, credit transactions increase balance",
                "Loan payments must not exceed outstanding balance",
                "Large transactions above $10,000 must be reported (AML)",
                "Account cannot have negative balance unless overdraft is enabled"
            ],
            data_characteristics={
                'regulatory_compliance': True,
                'high_precision_required': True,
                'audit_trail_required': True,
                'security_sensitive': True
            },
            vocabulary={
                'account_types': ['checking', 'savings', 'credit', 'investment', 'mortgage', 'loan'],
                'transaction_types': ['deposit', 'withdrawal', 'transfer', 'payment', 'fee', 'interest'],
                'loan_types': ['personal', 'auto', 'mortgage', 'business', 'student'],
                'card_types': ['debit', 'credit', 'prepaid', 'business'],
                'transaction_statuses': ['pending', 'posted', 'reversed', 'failed']
            },
            compliance_requirements=['SOX', 'GDPR', 'PCI_DSS', 'AML', 'KYC'],
            industry_standards=['ISO_20022', 'SWIFT', 'ACH', 'NACHA']
        )
        
        entities = {
            'account': EntityContext(
                entity_name='account',
                domain=domain,
                description="Financial account entity",
                typical_attributes=['account_id', 'customer_id', 'account_number', 'account_type', 'balance', 'currency', 'status', 'opening_date', 'interest_rate', 'overdraft_limit'],
                required_attributes=['account_id', 'customer_id', 'account_number', 'account_type', 'balance', 'opening_date'],
                optional_attributes=['interest_rate', 'overdraft_limit', 'minimum_balance'],
                validation_rules=[
                    {'field': 'account_number', 'type': 'format', 'pattern': r'^\d{10,12}$'},
                    {'field': 'balance', 'type': 'precision', 'decimal_places': 2},
                    {'field': 'interest_rate', 'type': 'range', 'min': 0, 'max': 30}
                ],
                business_constraints=['account_number must be unique', 'balance precision must be 2 decimal places'],
                relationship_roles=['child', 'parent']
            ),
            
            'transaction': EntityContext(
                entity_name='transaction',
                domain=domain,
                description="Financial transaction entity",
                typical_attributes=['transaction_id', 'account_id', 'amount', 'transaction_type', 'description', 'transaction_date', 'posted_date', 'reference_number', 'balance_after'],
                required_attributes=['transaction_id', 'account_id', 'amount', 'transaction_type', 'transaction_date'],
                optional_attributes=['description', 'reference_number', 'merchant_name'],
                validation_rules=[
                    {'field': 'amount', 'type': 'precision', 'decimal_places': 2},
                    {'field': 'transaction_date', 'type': 'date', 'constraint': 'not_future'},
                    {'field': 'posted_date', 'type': 'date_range', 'after_field': 'transaction_date'}
                ],
                business_constraints=['transaction_id must be unique', 'posted_date >= transaction_date'],
                relationship_roles=['child']
            )
        }
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = entities
    
    def _init_healthcare_context(self):
        """Initialize healthcare domain context."""
        
        domain = 'healthcare'
        
        context = DomainContext(
            domain=domain,
            description="Healthcare and medical services",
            key_entities=['patient', 'provider', 'appointment', 'diagnosis', 'treatment', 'medication', 'insurance'],
            common_relationships=[
                {'type': 'one_to_many', 'parent': 'patient', 'child': 'appointment'},
                {'type': 'one_to_many', 'parent': 'provider', 'child': 'appointment'},
                {'type': 'one_to_many', 'parent': 'patient', 'child': 'diagnosis'},
                {'type': 'many_to_many', 'parent': 'patient', 'child': 'medication'}
            ],
            business_rules=[
                "Patient must be scheduled before appointment date",
                "Provider specialization must match appointment type",
                "Prescription must have valid DEA number",
                "Patient allergies must be checked before medication",
                "Insurance coverage must be verified before treatment"
            ],
            data_characteristics={
                'privacy_sensitive': True,
                'regulatory_compliance': True,
                'life_critical': True,
                'standardized_coding': True
            },
            vocabulary={
                'appointment_types': ['consultation', 'checkup', 'follow_up', 'procedure', 'surgery', 'emergency'],
                'specializations': ['cardiology', 'endocrinology', 'neurology', 'orthopedics', 'pediatrics', 'psychiatry'],
                'diagnosis_categories': ['infectious', 'chronic', 'acute', 'genetic', 'traumatic'],
                'medication_types': ['prescription', 'over_counter', 'controlled', 'generic', 'brand'],
                'insurance_types': ['private', 'medicare', 'medicaid', 'self_pay', 'workers_comp']
            },
            compliance_requirements=['HIPAA', 'FDA', 'CMS', 'HITECH'],
            industry_standards=['HL7_FHIR', 'ICD_10', 'CPT', 'SNOMED_CT', 'LOINC']
        )
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = {}  # Simplified for brevity
    
    def _init_hr_context(self):
        """Initialize HR domain context."""
        
        domain = 'hr'
        
        context = DomainContext(
            domain=domain,
            description="Human resources and workforce management",
            key_entities=['employee', 'department', 'position', 'payroll', 'performance', 'training'],
            common_relationships=[
                {'type': 'many_to_one', 'parent': 'department', 'child': 'employee'},
                {'type': 'many_to_one', 'parent': 'employee', 'child': 'manager'},
                {'type': 'one_to_many', 'parent': 'employee', 'child': 'performance'},
                {'type': 'many_to_many', 'parent': 'employee', 'child': 'training'}
            ],
            business_rules=[
                "Employee start date must be before end date",
                "Manager must be from same department or above",
                "Salary must be within position pay band",
                "Performance reviews required annually",
                "Training completion affects certification status"
            ],
            data_characteristics={
                'privacy_sensitive': True,
                'hierarchical_structure': True,
                'time_series_data': True,
                'compensation_sensitive': True
            },
            vocabulary={
                'departments': ['engineering', 'sales', 'marketing', 'finance', 'hr', 'operations'],
                'employment_types': ['full_time', 'part_time', 'contractor', 'intern', 'consultant'],
                'performance_ratings': ['excellent', 'exceeds', 'meets', 'below', 'unsatisfactory'],
                'training_types': ['onboarding', 'technical', 'compliance', 'leadership', 'safety'],
                'benefit_types': ['health', 'dental', 'vision', '401k', 'pto', 'life_insurance']
            },
            compliance_requirements=['FLSA', 'FMLA', 'ADA', 'EEOC', 'OSHA'],
            industry_standards=['ISO_30414', 'SHRM', 'HRCI']
        )
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = {}
    
    def _init_education_context(self):
        """Initialize education domain context."""
        
        domain = 'education'
        
        context = DomainContext(
            domain=domain,
            description="Educational institutions and learning management",
            key_entities=['student', 'instructor', 'course', 'enrollment', 'grade', 'assignment'],
            common_relationships=[
                {'type': 'many_to_many', 'parent': 'student', 'child': 'course'},
                {'type': 'one_to_many', 'parent': 'instructor', 'child': 'course'},
                {'type': 'one_to_many', 'parent': 'course', 'child': 'assignment'},
                {'type': 'many_to_one', 'parent': 'grade', 'child': 'student'}
            ],
            business_rules=[
                "Student must be enrolled before receiving grades",
                "Prerequisites must be completed before advanced courses",
                "GPA calculated from all completed courses",
                "Instructor must be qualified for course subject",
                "Assignment due dates must be during semester"
            ],
            data_characteristics={
                'academic_calendar_based': True,
                'grade_progression': True,
                'prerequisite_dependencies': True,
                'performance_tracking': True
            },
            vocabulary={
                'grade_levels': ['freshman', 'sophomore', 'junior', 'senior', 'graduate'],
                'course_types': ['lecture', 'lab', 'seminar', 'online', 'hybrid'],
                'grade_scales': ['A', 'B', 'C', 'D', 'F', 'pass', 'fail', 'incomplete'],
                'semesters': ['fall', 'spring', 'summer', 'winter'],
                'majors': ['computer_science', 'business', 'engineering', 'liberal_arts', 'sciences']
            },
            compliance_requirements=['FERPA', 'ADA', 'Title_IX'],
            industry_standards=['QTI', 'LTI', 'xAPI', 'SCORM']
        )
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = {}
    
    def _init_crm_context(self):
        """Initialize CRM domain context."""
        
        domain = 'crm'
        
        context = DomainContext(
            domain=domain,
            description="Customer relationship management and sales operations",
            key_entities=['lead', 'contact', 'account', 'opportunity', 'campaign', 'activity'],
            common_relationships=[
                {'type': 'one_to_many', 'parent': 'account', 'child': 'contact'},
                {'type': 'one_to_many', 'parent': 'contact', 'child': 'opportunity'},
                {'type': 'many_to_many', 'parent': 'contact', 'child': 'campaign'},
                {'type': 'one_to_many', 'parent': 'opportunity', 'child': 'activity'}
            ],
            business_rules=[
                "Lead must be qualified before converting to opportunity",
                "Opportunities must have valid close date",
                "Activities must be associated with contacts or opportunities",
                "Campaign responses tracked to measure ROI",
                "Sales stages follow defined progression"
            ],
            data_characteristics={
                'sales_funnel_tracking': True,
                'conversion_metrics': True,
                'relationship_mapping': True,
                'activity_timeline': True
            },
            vocabulary={
                'lead_sources': ['website', 'referral', 'trade_show', 'cold_call', 'social_media'],
                'opportunity_stages': ['prospecting', 'qualification', 'proposal', 'negotiation', 'closed_won', 'closed_lost'],
                'activity_types': ['call', 'email', 'meeting', 'demo', 'proposal', 'contract'],
                'campaign_types': ['email', 'webinar', 'trade_show', 'social_media', 'direct_mail'],
                'industry_segments': ['technology', 'healthcare', 'finance', 'manufacturing', 'retail']
            },
            compliance_requirements=['GDPR', 'CAN_SPAM', 'CCPA'],
            industry_standards=['BANT', 'MEDDIC', 'SPIN']
        )
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = {}
    
    def _init_real_estate_context(self):
        """Initialize real estate domain context."""
        
        domain = 'real_estate'
        
        context = DomainContext(
            domain=domain,
            description="Real estate transactions and property management",
            key_entities=['property', 'agent', 'client', 'listing', 'transaction', 'inspection'],
            common_relationships=[
                {'type': 'one_to_many', 'parent': 'agent', 'child': 'listing'},
                {'type': 'one_to_one', 'parent': 'property', 'child': 'listing'},
                {'type': 'one_to_many', 'parent': 'client', 'child': 'transaction'},
                {'type': 'one_to_many', 'parent': 'property', 'child': 'inspection'}
            ],
            business_rules=[
                "Property must have valid address and legal description",
                "Listing price should be based on comparable sales",
                "Agent must be licensed in property jurisdiction",
                "Inspection must be completed before closing",
                "Commission calculated on final sale price"
            ],
            data_characteristics={
                'location_dependent': True,
                'market_sensitive': True,
                'legal_documentation': True,
                'valuation_based': True
            },
            vocabulary={
                'property_types': ['single_family', 'condo', 'townhouse', 'multi_family', 'commercial', 'land'],
                'listing_types': ['for_sale', 'for_rent', 'sold', 'rented', 'off_market'],
                'transaction_types': ['purchase', 'sale', 'lease', 'rental', 'refinance'],
                'property_features': ['pool', 'garage', 'fireplace', 'hardwood', 'updated_kitchen', 'master_suite'],
                'market_conditions': ['hot', 'balanced', 'cold', 'seasonal', 'volatile']
            },
            compliance_requirements=['RESPA', 'TRID', 'Fair_Housing', 'MLS'],
            industry_standards=['RETS', 'IDX', 'VOW', 'RESO']
        )
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = {}
    
    def _init_manufacturing_context(self):
        """Initialize manufacturing domain context."""
        
        domain = 'manufacturing'
        
        context = DomainContext(
            domain=domain,
            description="Manufacturing operations and supply chain management",
            key_entities=['product', 'component', 'supplier', 'work_order', 'quality_control', 'inventory'],
            common_relationships=[
                {'type': 'one_to_many', 'parent': 'product', 'child': 'component'},
                {'type': 'many_to_one', 'parent': 'supplier', 'child': 'component'},
                {'type': 'one_to_many', 'parent': 'work_order', 'child': 'quality_control'},
                {'type': 'one_to_one', 'parent': 'component', 'child': 'inventory'}
            ],
            business_rules=[
                "Work orders must specify required components",
                "Quality control checks required before shipping",
                "Inventory levels must meet safety stock requirements",
                "Supplier lead times affect production scheduling",
                "Component specifications must match product requirements"
            ],
            data_characteristics={
                'process_optimization': True,
                'supply_chain_tracking': True,
                'quality_metrics': True,
                'operational_efficiency': True
            },
            vocabulary={
                'work_order_statuses': ['planned', 'released', 'in_progress', 'completed', 'cancelled'],
                'quality_levels': ['acceptable', 'marginal', 'rejected', 'rework_required'],
                'supplier_ratings': ['preferred', 'approved', 'conditional', 'restricted'],
                'inventory_types': ['raw_material', 'work_in_progress', 'finished_goods', 'spare_parts'],
                'production_methods': ['batch', 'continuous', 'job_shop', 'assembly_line']
            },
            compliance_requirements=['ISO_9001', 'AS9100', 'TS16949', 'FDA_GMP'],
            industry_standards=['MES', 'ERP', 'PLM', 'SCADA']
        )
        
        self.domain_contexts[domain] = context
        self.entity_contexts[domain] = {}
    
    def _init_compliance_frameworks(self):
        """Initialize compliance frameworks."""
        
        self.compliance_frameworks = {
            'GDPR': {
                'name': 'General Data Protection Regulation',
                'description': 'EU privacy regulation',
                'key_requirements': ['consent', 'right_to_erasure', 'data_portability', 'breach_notification'],
                'applicable_domains': ['all'],
                'data_fields': ['personal_data', 'sensitive_data', 'consent_status', 'data_source']
            },
            
            'HIPAA': {
                'name': 'Health Insurance Portability and Accountability Act',
                'description': 'US healthcare privacy regulation',
                'key_requirements': ['minimum_necessary', 'patient_consent', 'audit_logs', 'encryption'],
                'applicable_domains': ['healthcare'],
                'data_fields': ['phi', 'patient_id', 'covered_entity', 'business_associate']
            },
            
            'PCI_DSS': {
                'name': 'Payment Card Industry Data Security Standard',
                'description': 'Credit card security standard',
                'key_requirements': ['encryption', 'access_control', 'monitoring', 'testing'],
                'applicable_domains': ['ecommerce', 'finance'],
                'data_fields': ['card_number', 'cvv', 'cardholder_name', 'expiry_date']
            },
            
            'SOX': {
                'name': 'Sarbanes-Oxley Act',
                'description': 'Financial reporting compliance',
                'key_requirements': ['internal_controls', 'audit_trail', 'segregation_of_duties', 'documentation'],
                'applicable_domains': ['finance'],
                'data_fields': ['financial_data', 'audit_log', 'approval_chain', 'supporting_documents']
            }
        }
    
    # Public API methods
    def get_domain_context(self, domain: str) -> Dict[str, Any]:
        """Get comprehensive context for a domain."""
        
        if domain not in self.domain_contexts:
            # Return generic context
            return self._get_generic_context()
        
        domain_context = self.domain_contexts[domain]
        
        context = {
            'domain': domain_context.domain,
            'description': domain_context.description,
            'key_entities': domain_context.key_entities,
            'common_relationships': domain_context.common_relationships,
            'business_rules': domain_context.business_rules,
            'data_characteristics': domain_context.data_characteristics,
            'vocabulary': domain_context.vocabulary,
            'compliance_requirements': domain_context.compliance_requirements or [],
            'industry_standards': domain_context.industry_standards or [],
            
            # Additional computed context
            'suggested_field_names': self._get_suggested_field_names(domain),
            'typical_data_volumes': self._get_typical_data_volumes(domain),
            'common_constraints': self._get_common_constraints(domain),
            'generation_priorities': self._get_generation_priorities(domain)
        }
        
        return context
    
    def get_entity_context(self, domain: str, entity: str) -> Optional[Dict[str, Any]]:
        """Get context for specific entity within domain."""
        
        if domain not in self.entity_contexts or entity not in self.entity_contexts[domain]:
            return None
        
        entity_context = self.entity_contexts[domain][entity]
        
        return {
            'entity_name': entity_context.entity_name,
            'domain': entity_context.domain,
            'description': entity_context.description,
            'typical_attributes': entity_context.typical_attributes,
            'required_attributes': entity_context.required_attributes,
            'optional_attributes': entity_context.optional_attributes,
            'validation_rules': entity_context.validation_rules,
            'business_constraints': entity_context.business_constraints,
            'relationship_roles': entity_context.relationship_roles,
            
            # Additional computed context
            'suggested_data_types': self._infer_data_types(entity_context.typical_attributes),
            'field_relationships': self._get_field_relationships(domain, entity),
            'generation_strategies': self._get_generation_strategies(domain, entity)
        }
    
    def get_vocabulary_for_field(self, domain: str, field_name: str) -> List[str]:
        """Get domain-specific vocabulary suggestions for a field."""
        
        if domain not in self.domain_contexts:
            return []
        
        vocabulary = self.domain_contexts[domain].vocabulary
        field_lower = field_name.lower()
        
        # Direct vocabulary match
        if field_lower in vocabulary:
            return vocabulary[field_lower]
        
        # Pattern-based matching
        for vocab_key, values in vocabulary.items():
            if vocab_key in field_lower or any(part in field_lower for part in vocab_key.split('_')):
                return values
        
        # Semantic matching
        semantic_mappings = {
            'status': ['statuses', 'states', 'conditions'],
            'type': ['types', 'categories', 'kinds'],
            'method': ['methods', 'ways', 'approaches'],
            'reason': ['reasons', 'causes', 'explanations']
        }
        
        for field_concept, vocab_keys in semantic_mappings.items():
            if field_concept in field_lower:
                for vocab_key in vocab_keys:
                    if vocab_key in vocabulary:
                        return vocabulary[vocab_key]
        
        return []
    
    def get_business_rules_for_entity(self, domain: str, entity: str) -> List[Dict[str, Any]]:
        """Get business rules applicable to specific entity."""
        
        rules = []
        
        # Domain-level rules
        if domain in self.domain_contexts:
            domain_rules = self.domain_contexts[domain].business_rules
            for rule in domain_rules:
                if entity.lower() in rule.lower():
                    rules.append({
                        'type': 'domain_rule',
                        'description': rule,
                        'scope': 'domain',
                        'enforcement': 'validation'
                    })
        
        # Entity-level rules
        entity_context = self.get_entity_context(domain, entity)
        if entity_context:
            for constraint in entity_context['business_constraints']:
                rules.append({
                    'type': 'entity_constraint',
                    'description': constraint,
                    'scope': 'entity',
                    'enforcement': 'generation'
                })
        
        return rules
    
    def get_compliance_requirements(self, domain: str) -> List[Dict[str, Any]]:
        """Get compliance requirements for domain."""
        
        requirements = []
        
        if domain in self.domain_contexts:
            compliance_names = self.domain_contexts[domain].compliance_requirements or []
            
            for compliance_name in compliance_names:
                if compliance_name in self.compliance_frameworks:
                    framework = self.compliance_frameworks[compliance_name]
                    requirements.append({
                        'framework': compliance_name,
                        'name': framework['name'],
                        'description': framework['description'],
                        'key_requirements': framework['key_requirements'],
                        'data_fields': framework['data_fields']
                    })
        
        return requirements
    
    def suggest_relationships(self, domain: str, entities: List[str]) -> List[Dict[str, Any]]:
        """Suggest relationships between entities based on domain knowledge."""
        
        suggestions = []
        
        if domain not in self.domain_contexts:
            return suggestions
        
        common_relationships = self.domain_contexts[domain].common_relationships
        
        for relationship in common_relationships:
            parent = relationship['parent']
            child = relationship['child']
            
            if parent in entities and child in entities:
                suggestions.append({
                    'type': relationship['type'],
                    'parent': parent,
                    'child': child,
                    'confidence': 0.9,
                    'description': f"Common {relationship['type']} relationship in {domain} domain"
                })
        
        # Additional heuristic-based suggestions
        heuristic_suggestions = self._generate_heuristic_relationships(entities)
        suggestions.extend(heuristic_suggestions)
        
        return suggestions
    
    def validate_domain_consistency(self, domain: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate data consistency against domain knowledge."""
        
        validation_results = {
            'valid': True,
            'warnings': [],
            'errors': [],
            'suggestions': []
        }
        
        domain_context = self.get_domain_context(domain)
        
        # Check field naming conventions
        field_names = data.keys() if isinstance(data, dict) else []
        expected_fields = domain_context.get('suggested_field_names', {})
        
        for entity, expected in expected_fields.items():
            if entity in str(field_names).lower():
                missing_fields = set(expected) - set(field_names)
                if missing_fields:
                    validation_results['suggestions'].append({
                        'type': 'missing_fields',
                        'entity': entity,
                        'fields': list(missing_fields),
                        'message': f"Consider adding typical {entity} fields: {', '.join(missing_fields)}"
                    })
        
        # Check vocabulary usage
        vocabulary = domain_context.get('vocabulary', {})
        for field_name, field_value in data.items():
            if isinstance(field_value, str):
                vocab_suggestions = self.get_vocabulary_for_field(domain, field_name)
                if vocab_suggestions and field_value not in vocab_suggestions:
                    validation_results['warnings'].append({
                        'field': field_name,
                        'value': field_value,
                        'suggestion': f"Consider using domain vocabulary: {', '.join(vocab_suggestions[:5])}"
                    })
        
        return validation_results
    
    # Helper methods
    def _get_generic_context(self) -> Dict[str, Any]:
        """Get generic context for unknown domains."""
        
        return {
            'domain': 'generic',
            'description': 'Generic business context',
            'key_entities': ['entity', 'record', 'item'],
            'common_relationships': [
                {'type': 'one_to_many', 'parent': 'parent', 'child': 'child'}
            ],
            'business_rules': ['Data must be consistent', 'Required fields must be present'],
            'data_characteristics': {'generic_patterns': True},
            'vocabulary': {
                'statuses': ['active', 'inactive', 'pending'],
                'types': ['primary', 'secondary', 'other'],
                'priorities': ['high', 'medium', 'low']
            },
            'compliance_requirements': [],
            'industry_standards': [],
            'suggested_field_names': {},
            'typical_data_volumes': {'small': 100, 'medium': 10000, 'large': 1000000},
            'common_constraints': [],
            'generation_priorities': []
        }
    
    def _get_suggested_field_names(self, domain: str) -> Dict[str, List[str]]:
        """Get suggested field names for domain entities."""
        
        suggestions = {}
        
        if domain in self.entity_contexts:
            for entity_name, entity_context in self.entity_contexts[domain].items():
                suggestions[entity_name] = entity_context.typical_attributes
        
        return suggestions
    
    def _get_typical_data_volumes(self, domain: str) -> Dict[str, int]:
        """Get typical data volumes for domain."""
        
        # Domain-specific volume estimates
        volume_profiles = {
            'ecommerce': {'customers': 100000, 'products': 10000, 'orders': 500000},
            'finance': {'accounts': 50000, 'transactions': 10000000, 'customers': 25000},
            'healthcare': {'patients': 20000, 'appointments': 100000, 'providers': 500},
            'hr': {'employees': 1000, 'departments': 20, 'performance_reviews': 2000},
            'education': {'students': 5000, 'courses': 500, 'enrollments': 25000}
        }
        
        return volume_profiles.get(domain, {'entities': 1000, 'relationships': 5000})
    
    def _get_common_constraints(self, domain: str) -> List[str]:
        """Get common constraints for domain."""
        
        constraint_patterns = {
            'ecommerce': ['price >= 0', 'quantity >= 0', 'email unique'],
            'finance': ['balance precision 2 decimals', 'account_number unique', 'transaction_date <= today'],
            'healthcare': ['patient_id unique', 'appointment_date >= today', 'provider licensed'],
            'hr': ['employee_id unique', 'salary >= minimum_wage', 'start_date <= today'],
            'education': ['student_id unique', 'gpa between 0 and 4', 'credits >= 0']
        }
        
        return constraint_patterns.get(domain, ['id unique', 'created_date <= today'])
    
    def _get_generation_priorities(self, domain: str) -> List[str]:
        """Get generation priorities for domain."""
        
        priority_patterns = {
            'ecommerce': ['customers', 'products', 'orders', 'payments'],
            'finance': ['customers', 'accounts', 'transactions'],
            'healthcare': ['patients', 'providers', 'appointments', 'diagnoses'],
            'hr': ['departments', 'employees', 'positions', 'performance'],
            'education': ['students', 'instructors', 'courses', 'enrollments']
        }
        
        return priority_patterns.get(domain, ['primary_entities', 'relationships', 'derived_data'])
    
    def _infer_data_types(self, field_names: List[str]) -> Dict[str, str]:
        """Infer data types from field names."""
        
        type_patterns = {
            'string': ['name', 'description', 'title', 'address', 'email', 'phone'],
            'integer': ['id', 'count', 'quantity', 'number', 'age', 'year'],
            'float': ['price', 'cost', 'rate', 'percentage', 'score', 'balance'],
            'datetime': ['date', 'time', 'created', 'updated', 'modified', 'birth'],
            'boolean': ['active', 'enabled', 'verified', 'confirmed', 'approved']
        }
        
        inferred_types = {}
        
        for field_name in field_names:
            field_lower = field_name.lower()
            inferred_type = 'string'  # default
            
            for data_type, keywords in type_patterns.items():
                if any(keyword in field_lower for keyword in keywords):
                    inferred_type = data_type
                    break
            
            inferred_types[field_name] = inferred_type
        
        return inferred_types
    
    def _get_field_relationships(self, domain: str, entity: str) -> List[Dict[str, str]]:
        """Get field relationships within entity."""
        
        relationships = []
        
        # Common field relationship patterns
        relationship_patterns = [
            {'parent': 'first_name', 'child': 'full_name', 'type': 'computed'},
            {'parent': 'last_name', 'child': 'full_name', 'type': 'computed'},
            {'parent': 'subtotal', 'child': 'total', 'type': 'computed'},
            {'parent': 'tax', 'child': 'total', 'type': 'computed'},
            {'parent': 'created_date', 'child': 'updated_date', 'type': 'temporal'},
        ]
        
        return relationship_patterns
    
    def _get_generation_strategies(self, domain: str, entity: str) -> Dict[str, str]:
        """Get field generation strategies for entity."""
        
        strategies = {
            'id': 'sequential',
            'email': 'pattern_based',
            'phone': 'pattern_based',
            'name': 'lookup_table',
            'date': 'date_range',
            'status': 'vocabulary',
            'price': 'range_normal',
            'description': 'template'
        }
        
        return strategies
    
    def _generate_heuristic_relationships(self, entities: List[str]) -> List[Dict[str, Any]]:
        """Generate relationship suggestions using heuristics."""
        
        suggestions = []
        
        # ID-based relationships
        for entity in entities:
            potential_parents = [e for e in entities if f"{e}_id" in f"{entity}_fields"]
            for parent in potential_parents:
                suggestions.append({
                    'type': 'many_to_one',
                    'parent': parent,
                    'child': entity,
                    'confidence': 0.6,
                    'description': f"Heuristic: {entity} likely references {parent}"
                })
        
        # Hierarchical relationships
        hierarchical_keywords = ['parent', 'manager', 'supervisor', 'owner']
        for entity in entities:
            if any(keyword in entity.lower() for keyword in hierarchical_keywords):
                suggestions.append({
                    'type': 'self_referencing',
                    'parent': entity,
                    'child': entity,
                    'confidence': 0.7,
                    'description': f"Heuristic: {entity} likely has hierarchical structure"
                })
        
        return suggestions
    
    # Utility methods
    def list_domains(self) -> List[str]:
        """List all available domains."""
        return list(self.domain_contexts.keys())
    
    def list_entities(self, domain: str) -> List[str]:
        """List all entities for a domain."""
        if domain in self.entity_contexts:
            return list(self.entity_contexts[domain].keys())
        return []
    
    def add_custom_domain_context(self, domain_context: DomainContext):
        """Add custom domain context."""
        self.domain_contexts[domain_context.domain] = domain_context
        logger.info(f"Added custom domain context: {domain_context.domain}")
    
    def add_custom_entity_context(self, domain: str, entity_context: EntityContext):
        """Add custom entity context."""
        if domain not in self.entity_contexts:
            self.entity_contexts[domain] = {}
        
        self.entity_contexts[domain][entity_context.entity_name] = entity_context
        logger.info(f"Added custom entity context: {domain}.{entity_context.entity_name}")
    
    def export_context(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Export context data for persistence."""
        if domain:
            return {
                'domain_context': self._domain_context_to_dict(self.domain_contexts.get(domain)),
                'entity_contexts': {
                    name: self._entity_context_to_dict(ctx)
                    for name, ctx in self.entity_contexts.get(domain, {}).items()
                }
            }
        else:
            return {
                'domain_contexts': {
                    name: self._domain_context_to_dict(ctx)
                    for name, ctx in self.domain_contexts.items()
                },
                'entity_contexts': {
                    domain: {
                        name: self._entity_context_to_dict(ctx)
                        for name, ctx in entities.items()
                    }
                    for domain, entities in self.entity_contexts.items()
                }
            }
    
    def _domain_context_to_dict(self, context: Optional[DomainContext]) -> Optional[Dict[str, Any]]:
        """Convert DomainContext to dictionary."""
        if not context:
            return None
        
        return {
            'domain': context.domain,
            'description': context.description,
            'key_entities': context.key_entities,
            'common_relationships': context.common_relationships,
            'business_rules': context.business_rules,
            'data_characteristics': context.data_characteristics,
            'vocabulary': context.vocabulary,
            'compliance_requirements': context.compliance_requirements,
            'industry_standards': context.industry_standards
        }
    
    def _entity_context_to_dict(self, context: EntityContext) -> Dict[str, Any]:
        """Convert EntityContext to dictionary."""
        return {
            'entity_name': context.entity_name,
            'domain': context.domain,
            'description': context.description,
            'typical_attributes': context.typical_attributes,
            'required_attributes': context.required_attributes,
            'optional_attributes': context.optional_attributes,
            'validation_rules': context.validation_rules,
            'business_constraints': context.business_constraints,
            'relationship_roles': context.relationship_roles
        }