"""
Business Pattern Library

Contains domain-specific business rules, patterns, and logic for generating
realistic, contextually appropriate data across different business domains.
"""

import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


@dataclass
class BusinessPattern:
    """Represents a business pattern or rule."""
    name: str
    description: str
    domain: str
    pattern_type: str  # 'validation', 'generation', 'relationship', 'constraint'
    rules: List[Dict[str, Any]]
    priority: int = 1
    enabled: bool = True
    metadata: Optional[Dict[str, Any]] = None


@dataclass  
class ValidationRule:
    """Represents a data validation rule."""
    name: str
    description: str
    rule_type: str  # 'format', 'range', 'conditional', 'cross_field'
    condition: Dict[str, Any]
    error_message: str
    severity: str = 'error'  # 'error', 'warning', 'info'


class BusinessPatternLibrary:
    """
    Library of business patterns and rules for different domains.
    
    Provides domain-specific logic for:
    - Data generation patterns
    - Validation rules
    - Business constraints
    - Relationship patterns
    - Industry-specific regulations
    """
    
    def __init__(self):
        self.patterns: Dict[str, List[BusinessPattern]] = {}
        self.validation_rules: Dict[str, List[ValidationRule]] = {}
        self.business_rules: Dict[str, List[Dict[str, Any]]] = {}
        
        self._initialize_patterns()
        
    def _initialize_patterns(self):
        """Initialize domain-specific patterns and rules."""
        self._init_ecommerce_patterns()
        self._init_finance_patterns()
        self._init_healthcare_patterns()
        self._init_hr_patterns()
        self._init_education_patterns()
        self._init_crm_patterns()
        self._init_real_estate_patterns()
        self._init_generic_patterns()
    
    def _init_ecommerce_patterns(self):
        """Initialize e-commerce business patterns."""
        domain = 'ecommerce'
        
        patterns = [
            BusinessPattern(
                name="product_pricing",
                description="Product pricing patterns and constraints",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "price_tiers",
                        "categories": {
                            "electronics": {"min": 10, "max": 2000, "typical_range": [50, 500]},
                            "clothing": {"min": 5, "max": 500, "typical_range": [20, 100]},
                            "books": {"min": 5, "max": 100, "typical_range": [10, 30]},
                            "home": {"min": 15, "max": 1000, "typical_range": [25, 200]}
                        }
                    },
                    {
                        "type": "discount_patterns",
                        "max_discount_percent": 70,
                        "seasonal_multipliers": {
                            "black_friday": 1.5,
                            "christmas": 1.3,
                            "summer": 1.1
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="order_workflow",
                description="Order processing workflow patterns",
                domain=domain,
                pattern_type="constraint",
                rules=[
                    {
                        "type": "status_progression",
                        "valid_transitions": {
                            "pending": ["processing", "cancelled"],
                            "processing": ["shipped", "cancelled"],
                            "shipped": ["delivered", "returned"],
                            "delivered": ["returned"],
                            "cancelled": [],
                            "returned": ["refunded"]
                        }
                    },
                    {
                        "type": "inventory_constraints",
                        "rules": ["quantity_available >= quantity_ordered"]
                    }
                ]
            ),
            BusinessPattern(
                name="customer_behavior",
                description="Customer behavior patterns",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "purchase_frequency",
                        "customer_segments": {
                            "frequent": {"orders_per_month": [3, 10], "avg_order_value": [30, 100]},
                            "regular": {"orders_per_month": [1, 3], "avg_order_value": [50, 150]},
                            "occasional": {"orders_per_month": [0.1, 1], "avg_order_value": [80, 250]}
                        }
                    },
                    {
                        "type": "seasonal_patterns",
                        "peak_seasons": ["november", "december", "june"],
                        "multipliers": {"november": 2.5, "december": 3.0, "june": 1.5}
                    }
                ]
            )
        ]
        
        business_rules = [
            {
                "type": "conditional_value",
                "name": "free_shipping_threshold",
                "condition_field": "order_total",
                "condition_operator": ">=",
                "condition_value": 50,
                "target_field": "shipping_cost",
                "target_value": 0
            },
            {
                "type": "calculated_field",
                "name": "order_total_calculation",
                "target_field": "order_total",
                "calculation": "sum",
                "source_fields": ["subtotal", "tax", "shipping_cost"]
            },
            {
                "type": "data_consistency",
                "name": "inventory_consistency",
                "rules": [
                    {
                        "name": "stock_validation",
                        "condition": "quantity_ordered <= quantity_available"
                    }
                ]
            }
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = business_rules
    
    def _init_finance_patterns(self):
        """Initialize finance business patterns."""
        domain = 'finance'
        
        patterns = [
            BusinessPattern(
                name="account_types",
                description="Banking account type patterns",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "account_categories",
                        "types": {
                            "checking": {
                                "typical_balance": [500, 5000],
                                "transaction_frequency": "daily",
                                "interest_rate": [0.01, 0.05]
                            },
                            "savings": {
                                "typical_balance": [1000, 50000],
                                "transaction_frequency": "weekly",
                                "interest_rate": [0.5, 2.5]
                            },
                            "credit": {
                                "typical_balance": [-10000, 0],
                                "transaction_frequency": "daily",
                                "credit_limit": [1000, 25000]
                            }
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="transaction_patterns",
                description="Financial transaction patterns",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "transaction_categories",
                        "categories": {
                            "groceries": {"typical_amount": [20, 150], "frequency": "weekly"},
                            "utilities": {"typical_amount": [50, 300], "frequency": "monthly"},
                            "salary": {"typical_amount": [2000, 8000], "frequency": "biweekly"},
                            "rent": {"typical_amount": [800, 3000], "frequency": "monthly"},
                            "entertainment": {"typical_amount": [15, 200], "frequency": "weekly"}
                        }
                    },
                    {
                        "type": "transaction_timing",
                        "patterns": {
                            "salary": {"days": [1, 15]},  # 1st and 15th of month
                            "rent": {"days": [1]},        # 1st of month
                            "utilities": {"days": [15, 30]} # Mid to end of month
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="compliance_rules", 
                description="Financial compliance and regulatory patterns",
                domain=domain,
                pattern_type="validation",
                rules=[
                    {
                        "type": "aml_patterns",  # Anti-Money Laundering
                        "large_transaction_threshold": 10000,
                        "suspicious_patterns": [
                            "rapid_succession_deposits",
                            "round_number_transactions",
                            "cross_border_transfers"
                        ]
                    },
                    {
                        "type": "kyc_requirements",  # Know Your Customer
                        "required_fields": ["ssn", "address", "employment_status"],
                        "verification_levels": ["basic", "enhanced", "premium"]
                    }
                ]
            )
        ]
        
        business_rules = [
            {
                "type": "calculated_field",
                "name": "running_balance",
                "target_field": "balance",
                "calculation": "running_sum",
                "source_fields": ["amount"],
                "order_by": "transaction_date"
            },
            {
                "type": "conditional_value",
                "name": "overdraft_fee",
                "condition_field": "balance",
                "condition_operator": "<",
                "condition_value": 0,
                "target_field": "fee",
                "target_value": 35
            },
            {
                "type": "data_consistency",
                "name": "transaction_consistency",
                "rules": [
                    {
                        "name": "debit_credit_balance",
                        "condition": "debit_amount + credit_amount == transaction_amount"
                    },
                    {
                        "name": "transaction_date_ordering",
                        "fields": ["transaction_date", "posted_date"],
                        "rule": "transaction_date <= posted_date"
                    }
                ]
            }
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = business_rules
    
    def _init_healthcare_patterns(self):
        """Initialize healthcare business patterns."""
        domain = 'healthcare'
        
        patterns = [
            BusinessPattern(
                name="patient_demographics",
                description="Patient demographic patterns and medical relevance",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "age_disease_correlation",
                        "correlations": {
                            "diabetes": {"age_groups": {"50-70": 0.3, "70+": 0.4}},
                            "hypertension": {"age_groups": {"40-60": 0.25, "60+": 0.45}},
                            "asthma": {"age_groups": {"0-18": 0.15, "18-40": 0.1}}
                        }
                    },
                    {
                        "type": "demographic_health_patterns",
                        "patterns": {
                            "gender_conditions": {
                                "male": ["heart_disease", "stroke"],
                                "female": ["osteoporosis", "breast_cancer"]
                            }
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="medical_coding",
                description="Medical coding standards (ICD-10, CPT)",
                domain=domain,
                pattern_type="validation",
                rules=[
                    {
                        "type": "icd10_validation",
                        "format": r"^[A-Z][0-9]{2}(\.[0-9X]{1,4})?$",
                        "common_codes": {
                            "I10": "Essential hypertension",
                            "E11.9": "Type 2 diabetes mellitus without complications",
                            "J45.9": "Asthma, unspecified"
                        }
                    },
                    {
                        "type": "cpt_validation", 
                        "format": r"^[0-9]{5}$",
                        "code_ranges": {
                            "evaluation": [99201, 99499],
                            "surgery": [10021, 69990],
                            "radiology": [70010, 79999]
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="appointment_scheduling",
                description="Healthcare appointment patterns",
                domain=domain,
                pattern_type="constraint",
                rules=[
                    {
                        "type": "scheduling_constraints",
                        "business_hours": {"start": "08:00", "end": "18:00"},
                        "appointment_duration": {
                            "routine_checkup": 30,
                            "consultation": 60,
                            "procedure": 120
                        },
                        "buffer_time": 15  # minutes between appointments
                    },
                    {
                        "type": "provider_specialization",
                        "specializations": {
                            "cardiology": ["heart_conditions", "blood_pressure"],
                            "endocrinology": ["diabetes", "thyroid"],
                            "pulmonology": ["asthma", "copd", "lung_conditions"]
                        }
                    }
                ]
            )
        ]
        
        business_rules = [
            {
                "type": "conditional_value",
                "name": "emergency_priority",
                "condition_field": "diagnosis_code", 
                "condition_operator": "in",
                "condition_value": ["R06.02", "R50.9"],  # Shortness of breath, fever
                "target_field": "priority",
                "target_value": "urgent"
            },
            {
                "type": "data_consistency",
                "name": "medical_consistency",
                "rules": [
                    {
                        "name": "age_appropriate_procedures",
                        "validation": "procedure_age_appropriate"
                    },
                    {
                        "name": "medication_allergy_check",
                        "fields": ["prescribed_medication", "known_allergies"]
                    }
                ]
            }
        ]
        
        self.patterns[domain] = patterns 
        self.business_rules[domain] = business_rules
    
    def _init_hr_patterns(self):
        """Initialize HR/Human Resources business patterns."""
        domain = 'hr'
        
        patterns = [
            BusinessPattern(
                name="compensation_bands",
                description="Salary and compensation patterns by role and experience",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "salary_ranges",
                        "positions": {
                            "software_engineer": {
                                "junior": [60000, 85000],
                                "mid": [85000, 120000], 
                                "senior": [120000, 160000],
                                "staff": [160000, 200000]
                            },
                            "data_scientist": {
                                "junior": [70000, 95000],
                                "mid": [95000, 130000],
                                "senior": [130000, 170000]
                            },
                            "product_manager": {
                                "junior": [80000, 110000],
                                "mid": [110000, 140000],
                                "senior": [140000, 180000]
                            }
                        }
                    },
                    {
                        "type": "benefits_packages",
                        "standard_benefits": {
                            "health_insurance": {"employer_contribution": [70, 100]},
                            "retirement_401k": {"employer_match": [3, 6]},
                            "vacation_days": {"annual": [15, 30]}
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="organizational_hierarchy",
                description="Organizational structure and reporting patterns",
                domain=domain,
                pattern_type="relationship",
                rules=[
                    {
                        "type": "management_structure",
                        "reporting_ratios": {
                            "c_level": {"direct_reports": [3, 8]},
                            "director": {"direct_reports": [4, 12]},
                            "manager": {"direct_reports": [3, 10]},
                            "team_lead": {"direct_reports": [2, 6]}
                        }
                    },
                    {
                        "type": "promotion_patterns",
                        "typical_tenure": {
                            "junior_to_mid": [18, 36],      # months
                            "mid_to_senior": [24, 48],
                            "ic_to_management": [36, 72]     # IC = Individual Contributor
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="performance_evaluation",
                description="Performance review and evaluation patterns",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "rating_distribution",
                        "scale": [1, 5],
                        "distribution": {
                            "1": 0.05,  # 5% low performers
                            "2": 0.15,  # 15% below expectations
                            "3": 0.60,  # 60% meets expectations
                            "4": 0.15,  # 15% exceeds expectations  
                            "5": 0.05   # 5% outstanding
                        }
                    },
                    {
                        "type": "review_cycles",
                        "frequencies": ["quarterly", "semi_annual", "annual"],
                        "common_frequency": "semi_annual"
                    }
                ]
            )
        ]
        
        business_rules = [
            {
                "type": "conditional_value",
                "name": "overtime_eligibility",
                "condition_field": "salary",
                "condition_operator": "<",
                "condition_value": 47476,  # FLSA threshold
                "target_field": "overtime_eligible", 
                "target_value": True
            },
            {
                "type": "data_consistency",
                "name": "employment_consistency",
                "rules": [
                    {
                        "name": "start_before_end_date",
                        "fields": ["start_date", "end_date"],
                        "rule": "start_date < end_date"
                    },
                    {
                        "name": "manager_hierarchy",
                        "validation": "manager_not_subordinate"
                    }
                ]
            },
            {
                "type": "calculated_field",
                "name": "tenure_calculation",
                "target_field": "tenure_years",
                "calculation": "date_diff",
                "source_fields": ["start_date", "current_date"],
                "unit": "years"
            }
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = business_rules
    
    def _init_education_patterns(self):
        """Initialize education business patterns."""
        domain = 'education'
        
        patterns = [
            BusinessPattern(
                name="academic_calendar",
                description="Academic year and semester patterns",
                domain=domain,
                pattern_type="constraint",
                rules=[
                    {
                        "type": "semester_structure", 
                        "semesters": {
                            "fall": {"start_month": 8, "end_month": 12},
                            "spring": {"start_month": 1, "end_month": 5},
                            "summer": {"start_month": 6, "end_month": 7}
                        }
                    },
                    {
                        "type": "grading_periods",
                        "periods": ["midterm", "final"],
                        "grade_submission_deadlines": [7, 14]  # days after period
                    }
                ]
            ),
            BusinessPattern(
                name="student_performance",
                description="Student academic performance patterns",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "grade_distribution",
                        "gpa_scale": [0.0, 4.0],
                        "distribution": {
                            "A": {"gpa_range": [3.7, 4.0], "percentage": 0.25},
                            "B": {"gpa_range": [2.7, 3.6], "percentage": 0.35},
                            "C": {"gpa_range": [1.7, 2.6], "percentage": 0.25},
                            "D": {"gpa_range": [1.0, 1.6], "percentage": 0.10},
                            "F": {"gpa_range": [0.0, 0.9], "percentage": 0.05}
                        }
                    },
                    {
                        "type": "course_difficulty",
                        "difficulty_modifiers": {
                            "introductory": {"grade_boost": 0.2},
                            "intermediate": {"grade_boost": 0.0},
                            "advanced": {"grade_boost": -0.3},
                            "graduate": {"grade_boost": -0.5}
                        }
                    }
                ]
            )
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = []
    
    def _init_crm_patterns(self):
        """Initialize CRM business patterns.""" 
        domain = 'crm'
        
        patterns = [
            BusinessPattern(
                name="lead_lifecycle",
                description="Lead progression and conversion patterns",
                domain=domain,
                pattern_type="constraint",
                rules=[
                    {
                        "type": "lead_stages",
                        "progression": [
                            "prospect",
                            "marketing_qualified_lead",
                            "sales_qualified_lead", 
                            "opportunity",
                            "customer"
                        ],
                        "conversion_rates": {
                            "prospect_to_mql": 0.15,
                            "mql_to_sql": 0.25,
                            "sql_to_opportunity": 0.60,
                            "opportunity_to_customer": 0.30
                        }
                    },
                    {
                        "type": "sales_cycle",
                        "average_duration": {
                            "smb": {"days": [30, 90]},      # Small/Medium Business
                            "enterprise": {"days": [120, 365]}
                        }
                    }
                ]
            ),
            BusinessPattern(
                name="deal_sizing",
                description="Deal value and sizing patterns", 
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "deal_values",
                        "segments": {
                            "smb": {"min": 1000, "max": 25000},
                            "mid_market": {"min": 25000, "max": 100000},
                            "enterprise": {"min": 100000, "max": 1000000}
                        }
                    }
                ]
            )
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = []
    
    def _init_real_estate_patterns(self):
        """Initialize real estate business patterns."""
        domain = 'real_estate'
        
        patterns = [
            BusinessPattern(
                name="property_valuation",
                description="Property pricing and valuation patterns",
                domain=domain,
                pattern_type="generation", 
                rules=[
                    {
                        "type": "price_per_sqft",
                        "market_segments": {
                            "luxury": {"price_range": [300, 800]},
                            "mid_tier": {"price_range": [150, 300]},
                            "affordable": {"price_range": [75, 150]}
                        }
                    },
                    {
                        "type": "location_multipliers",
                        "factors": {
                            "school_district": {"multiplier": [1.1, 1.3]},
                            "public_transport": {"multiplier": [1.05, 1.15]},
                            "waterfront": {"multiplier": [1.2, 1.8]}
                        }
                    }
                ]
            )
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = []
    
    def _init_generic_patterns(self):
        """Initialize generic patterns applicable across domains."""
        domain = 'generic'
        
        patterns = [
            BusinessPattern(
                name="data_quality",
                description="Generic data quality patterns",
                domain=domain,
                pattern_type="validation",
                rules=[
                    {
                        "type": "completeness",
                        "required_field_threshold": 0.95,
                        "critical_fields": ["id", "created_at"]
                    },
                    {
                        "type": "consistency",
                        "cross_field_validation": True,
                        "temporal_ordering": True
                    }
                ]
            ),
            BusinessPattern(
                name="audit_trail",
                description="Generic audit and tracking patterns",
                domain=domain,
                pattern_type="generation",
                rules=[
                    {
                        "type": "timestamp_fields",
                        "standard_fields": ["created_at", "updated_at"],
                        "precision": "seconds"
                    },
                    {
                        "type": "user_tracking", 
                        "fields": ["created_by", "updated_by"],
                        "format": "user_id"
                    }
                ]
            )
        ]
        
        self.patterns[domain] = patterns
        self.business_rules[domain] = []
    
    # Public API methods
    def get_supported_domains(self) -> List[str]:
        """Get list of supported business domains."""
        return list(self.patterns.keys())
    
    def get_patterns_for_domain(self, domain: str) -> List[BusinessPattern]:
        """Get all patterns for a specific domain."""
        patterns = self.patterns.get(domain, [])
        
        # Also include generic patterns
        if domain != 'generic':
            patterns.extend(self.patterns.get('generic', []))
        
        return patterns
    
    def get_business_rules(self, domain: str) -> List[Dict[str, Any]]:
        """Get business rules for a domain.""" 
        rules = self.business_rules.get(domain, []).copy()
        
        # Include generic rules
        if domain != 'generic':
            rules.extend(self.business_rules.get('generic', []))
            
        return rules
    
    def get_pattern_by_name(self, domain: str, pattern_name: str) -> Optional[BusinessPattern]:
        """Get specific pattern by name."""
        domain_patterns = self.get_patterns_for_domain(domain)
        
        for pattern in domain_patterns:
            if pattern.name == pattern_name:
                return pattern
                
        return None
    
    def validate_data_against_patterns(self, data: List[Dict[str, Any]], 
                                     domain: str) -> Dict[str, Any]:
        """Validate data against domain patterns."""
        patterns = self.get_patterns_for_domain(domain)
        validation_results = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'pattern_compliance': {}
        }
        
        for pattern in patterns:
            if pattern.pattern_type == 'validation':
                pattern_result = self._validate_against_pattern(data, pattern)
                validation_results['pattern_compliance'][pattern.name] = pattern_result
                
                if not pattern_result['valid']:
                    validation_results['valid'] = False
                    validation_results['errors'].extend(pattern_result['errors'])
                    validation_results['warnings'].extend(pattern_result['warnings'])
        
        return validation_results
    
    def _validate_against_pattern(self, data: List[Dict[str, Any]], 
                                pattern: BusinessPattern) -> Dict[str, Any]:
        """Validate data against a specific pattern."""
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'checked_records': len(data)
        }
        
        for rule in pattern.rules:
            rule_type = rule.get('type')
            
            if rule_type == 'format_validation':
                # Validate field formats
                field_name = rule.get('field')
                format_pattern = rule.get('pattern')
                
                if field_name and format_pattern:
                    import re
                    pattern_regex = re.compile(format_pattern)
                    
                    for i, record in enumerate(data):
                        if field_name in record:
                            value = str(record[field_name])
                            if not pattern_regex.match(value):
                                result['errors'].append(
                                    f"Record {i}: {field_name} '{value}' doesn't match pattern {format_pattern}"
                                )
                                result['valid'] = False
            
            elif rule_type == 'range_validation':
                # Validate numeric ranges
                field_name = rule.get('field')
                min_value = rule.get('min')
                max_value = rule.get('max')
                
                if field_name:
                    for i, record in enumerate(data):
                        if field_name in record:
                            try:
                                value = float(record[field_name])
                                if min_value is not None and value < min_value:
                                    result['errors'].append(
                                        f"Record {i}: {field_name} {value} below minimum {min_value}"
                                    )
                                    result['valid'] = False
                                if max_value is not None and value > max_value:
                                    result['errors'].append(
                                        f"Record {i}: {field_name} {value} above maximum {max_value}"
                                    )
                                    result['valid'] = False
                            except (ValueError, TypeError):
                                result['warnings'].append(
                                    f"Record {i}: {field_name} is not numeric"
                                )
        
        return result
    
    def get_generation_suggestions(self, domain: str, 
                                 field_name: str) -> List[Dict[str, Any]]:
        """Get generation suggestions for a field based on domain patterns."""
        suggestions = []
        patterns = self.get_patterns_for_domain(domain)
        
        for pattern in patterns:
            if pattern.pattern_type == 'generation':
                for rule in pattern.rules:
                    # Check if rule applies to this field
                    if self._rule_applies_to_field(rule, field_name):
                        suggestion = {
                            'pattern_name': pattern.name,
                            'rule_type': rule.get('type'),
                            'suggestion': self._extract_suggestion_from_rule(rule, field_name),
                            'confidence': 0.8,  # Could be calculated based on pattern match
                            'description': pattern.description
                        }
                        suggestions.append(suggestion)
        
        return suggestions
    
    def _rule_applies_to_field(self, rule: Dict[str, Any], field_name: str) -> bool:
        """Check if a generation rule applies to a specific field."""
        rule_type = rule.get('type', '')
        field_lower = field_name.lower()
        
        # Check for direct field mentions
        if 'field' in rule and rule['field'].lower() == field_lower:
            return True
        
        # Check for pattern matches
        field_patterns = {
            'price': ['price', 'cost', 'amount', 'fee', 'total'],
            'date': ['date', 'time', 'created', 'updated', 'birth'],
            'status': ['status', 'state', 'phase', 'stage'],
            'category': ['category', 'type', 'kind', 'class']
        }
        
        for pattern_type, keywords in field_patterns.items():
            if pattern_type in rule_type.lower():
                if any(keyword in field_lower for keyword in keywords):
                    return True
        
        return False
    
    def _extract_suggestion_from_rule(self, rule: Dict[str, Any], 
                                    field_name: str) -> Dict[str, Any]:
        """Extract generation suggestion from a rule."""
        rule_type = rule.get('type', '')
        
        if 'price' in rule_type or 'salary' in rule_type:
            # Extract pricing/salary suggestions
            ranges = rule.get('categories', rule.get('positions', {}))
            return {
                'type': 'range',
                'ranges': ranges,
                'unit': 'currency'
            }
        
        elif 'status' in rule_type or 'stage' in rule_type:
            # Extract status/stage suggestions
            stages = rule.get('progression', rule.get('valid_transitions', {}))
            return {
                'type': 'enum',
                'values': stages if isinstance(stages, list) else list(stages.keys()),
                'progression': isinstance(stages, list)
            }
        
        elif 'frequency' in rule_type or 'timing' in rule_type:
            # Extract timing suggestions
            patterns = rule.get('patterns', rule.get('frequencies', {}))
            return {
                'type': 'temporal',
                'patterns': patterns
            }
        
        else:
            # Generic suggestion
            return {
                'type': 'generic',
                'data': rule
            }
    
    def add_custom_pattern(self, domain: str, pattern: BusinessPattern):
        """Add a custom business pattern to the library."""
        if domain not in self.patterns:
            self.patterns[domain] = []
        
        self.patterns[domain].append(pattern)
        logger.info(f"Added custom pattern '{pattern.name}' to domain '{domain}'")
    
    def export_patterns(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Export patterns for external use or persistence.""" 
        if domain:
            return {
                'domain': domain,
                'patterns': [self._pattern_to_dict(p) for p in self.get_patterns_for_domain(domain)],
                'business_rules': self.get_business_rules(domain)
            }
        else:
            return {
                'all_domains': {
                    d: {
                        'patterns': [self._pattern_to_dict(p) for p in patterns],
                        'business_rules': self.business_rules.get(d, [])
                    }
                    for d, patterns in self.patterns.items()
                }
            }
    
    def _pattern_to_dict(self, pattern: BusinessPattern) -> Dict[str, Any]:
        """Convert BusinessPattern to dictionary."""
        return {
            'name': pattern.name,
            'description': pattern.description,
            'domain': pattern.domain,
            'pattern_type': pattern.pattern_type,
            'rules': pattern.rules,
            'priority': pattern.priority,
            'enabled': pattern.enabled,
            'metadata': pattern.metadata
        }
    
    def import_patterns(self, pattern_data: Dict[str, Any]):
        """Import patterns from external source."""
        if 'all_domains' in pattern_data:
            # Import all domains
            for domain, domain_data in pattern_data['all_domains'].items():
                patterns = []
                for pattern_dict in domain_data.get('patterns', []):
                    pattern = BusinessPattern(**pattern_dict)
                    patterns.append(pattern)
                self.patterns[domain] = patterns
                self.business_rules[domain] = domain_data.get('business_rules', [])
        
        elif 'domain' in pattern_data:
            # Import single domain
            domain = pattern_data['domain']
            patterns = []
            for pattern_dict in pattern_data.get('patterns', []):
                pattern = BusinessPattern(**pattern_dict)
                patterns.append(pattern)
            self.patterns[domain] = patterns
            self.business_rules[domain] = pattern_data.get('business_rules', [])
        
        logger.info(f"Imported patterns for domains: {list(pattern_data.keys())}")