"""
Domain-Aware Data Generator

Generates realistic data based on business domain knowledge and context.
Understands different business domains and applies appropriate generation
strategies for each domain.
"""

import random
import string
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import re
import json
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DomainKnowledge:
    """Domain-specific knowledge for data generation."""
    domain: str
    patterns: Dict[str, List[str]]
    business_rules: List[Dict[str, Any]]
    typical_ranges: Dict[str, Dict[str, Any]]
    relationships: Dict[str, List[str]]
    
    # Sample data for each domain
    sample_names: List[str] = None
    sample_companies: List[str] = None
    sample_products: List[str] = None
    sample_addresses: List[str] = None
    
    def __post_init__(self):
        if self.sample_names is None:
            self.sample_names = []
        if self.sample_companies is None:
            self.sample_companies = []
        if self.sample_products is None:
            self.sample_products = []
        if self.sample_addresses is None:
            self.sample_addresses = []


class DomainDataGenerator:
    """
    Domain-aware data generator that creates realistic data
    based on business domain knowledge.
    """
    
    def __init__(self):
        self.domain_knowledge: Dict[str, DomainKnowledge] = {}
        self.locale_data: Dict[str, Dict[str, Any]] = {}
        
        # Load domain knowledge
        self._load_domain_knowledge()
        self._load_locale_data()
        
        logger.info("Domain Data Generator initialized")
    
    def _load_domain_knowledge(self):
        """Load domain-specific knowledge and patterns."""
        
        # E-commerce domain
        ecommerce_knowledge = DomainKnowledge(
            domain='ecommerce',
            patterns={
                'product_names': [
                    'Premium {adjective} {product_type}',
                    '{brand} {product_type} {model}',
                    '{adjective} {product_type} Collection',
                    'Professional {product_type} Set',
                    '{color} {product_type} {size}'
                ],
                'order_statuses': [
                    'pending', 'processing', 'shipped', 'delivered', 'cancelled', 'returned'
                ],
                'payment_methods': [
                    'credit_card', 'debit_card', 'paypal', 'stripe', 'bank_transfer', 'cash_on_delivery'
                ],
                'categories': [
                    'Electronics', 'Clothing', 'Home & Garden', 'Sports', 'Books', 
                    'Health & Beauty', 'Automotive', 'Toys & Games', 'Food & Beverages'
                ]
            },
            business_rules=[
                {
                    'type': 'order_total_calculation',
                    'description': 'Order total should equal sum of item prices plus tax and shipping'
                },
                {
                    'type': 'inventory_constraint',
                    'description': 'Stock quantity cannot be negative'
                }
            ],
            typical_ranges={
                'product_price': {'min': 1.0, 'max': 10000.0, 'distribution': 'log_normal'},
                'order_quantity': {'min': 1, 'max': 50, 'distribution': 'exponential'},
                'shipping_cost': {'min': 0.0, 'max': 200.0, 'distribution': 'normal'},
                'discount_percentage': {'min': 0, 'max': 75, 'distribution': 'uniform'}
            },
            relationships={
                'customer_orders': ['one_to_many'],
                'order_items': ['one_to_many'],
                'product_categories': ['many_to_one']
            },
            sample_products=[
                'iPhone 14 Pro Max', 'Samsung Galaxy S23', 'MacBook Pro 16"', 'Dell XPS 15',
                'Nike Air Jordan', 'Adidas Ultraboost', 'Sony WH-1000XM5', 'Bose QuietComfort',
                'Canon EOS R5', 'Nikon D850', 'Tesla Model S', 'BMW X5'
            ]
        )
        
        # Finance domain
        finance_knowledge = DomainKnowledge(
            domain='finance',
            patterns={
                'account_types': [
                    'checking', 'savings', 'money_market', 'cd', 'ira', 'investment', 'credit'
                ],
                'transaction_types': [
                    'deposit', 'withdrawal', 'transfer', 'payment', 'fee', 'interest', 'dividend'
                ],
                'account_number_formats': [
                    '{bank_code}-{branch_code}-{account_number}',
                    '{routing_number}{account_number}',
                    'ACC{timestamp}{random_digits}'
                ]
            },
            business_rules=[
                {
                    'type': 'balance_validation',
                    'description': 'Account balance must equal sum of all transactions'
                },
                {
                    'type': 'overdraft_protection',
                    'description': 'Withdrawal cannot exceed available balance plus overdraft limit'
                }
            ],
            typical_ranges={
                'account_balance': {'min': 0.0, 'max': 1000000.0, 'distribution': 'log_normal'},
                'transaction_amount': {'min': 0.01, 'max': 50000.0, 'distribution': 'log_normal'},
                'interest_rate': {'min': 0.01, 'max': 15.0, 'distribution': 'normal'},
                'credit_limit': {'min': 500.0, 'max': 100000.0, 'distribution': 'exponential'}
            },
            relationships={
                'customer_accounts': ['one_to_many'],
                'account_transactions': ['one_to_many']
            }
        )
        
        # Healthcare domain
        healthcare_knowledge = DomainKnowledge(
            domain='healthcare',
            patterns={
                'diagnoses': [
                    'Hypertension', 'Diabetes Type 2', 'Asthma', 'Depression', 'Anxiety',
                    'Arthritis', 'Back Pain', 'Migraine', 'GERD', 'Allergies'
                ],
                'medications': [
                    'Lisinopril', 'Metformin', 'Albuterol', 'Sertraline', 'Ibuprofen',
                    'Omeprazole', 'Acetaminophen', 'Simvastatin', 'Levothyroxine'
                ],
                'appointment_types': [
                    'routine_checkup', 'follow_up', 'consultation', 'procedure', 'emergency',
                    'surgery', 'therapy', 'screening', 'vaccination'
                ]
            },
            business_rules=[
                {
                    'type': 'appointment_scheduling',
                    'description': 'Appointments cannot overlap for the same provider'
                },
                {
                    'type': 'prescription_validation',
                    'description': 'Prescription must be valid and not expired'
                }
            ],
            typical_ranges={
                'patient_age': {'min': 0, 'max': 120, 'distribution': 'normal_skewed'},
                'appointment_duration': {'min': 15, 'max': 240, 'distribution': 'normal'},
                'medication_dosage': {'min': 1, 'max': 1000, 'distribution': 'log_normal'}
            },
            relationships={
                'patient_appointments': ['one_to_many'],
                'patient_prescriptions': ['one_to_many'],
                'doctor_appointments': ['one_to_many']
            }
        )
        
        # HR domain
        hr_knowledge = DomainKnowledge(
            domain='hr',
            patterns={
                'job_titles': [
                    'Software Engineer', 'Product Manager', 'Data Scientist', 'UX Designer',
                    'Sales Representative', 'Marketing Manager', 'HR Specialist', 'Accountant',
                    'Operations Manager', 'Customer Success Manager'
                ],
                'departments': [
                    'Engineering', 'Product', 'Marketing', 'Sales', 'HR', 'Finance',
                    'Operations', 'Customer Support', 'Legal', 'IT'
                ],
                'employment_types': [
                    'full_time', 'part_time', 'contract', 'intern', 'temporary', 'consultant'
                ]
            },
            business_rules=[
                {
                    'type': 'salary_range_validation',
                    'description': 'Salary must be within approved range for position'
                },
                {
                    'type': 'reporting_hierarchy',
                    'description': 'Employee cannot report to themselves or create circular reporting'
                }
            ],
            typical_ranges={
                'salary': {'min': 30000.0, 'max': 500000.0, 'distribution': 'log_normal'},
                'years_experience': {'min': 0, 'max': 45, 'distribution': 'exponential'},
                'performance_rating': {'min': 1.0, 'max': 5.0, 'distribution': 'normal'}
            },
            relationships={
                'employee_manager': ['many_to_one'],
                'department_employees': ['one_to_many']
            }
        )
        
        # Education domain
        education_knowledge = DomainKnowledge(
            domain='education',
            patterns={
                'courses': [
                    'Introduction to Computer Science', 'Calculus I', 'English Composition',
                    'Biology 101', 'Psychology 101', 'History of Art', 'Physics I',
                    'Business Administration', 'Marketing Fundamentals', 'Statistics'
                ],
                'grades': ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D+', 'D', 'F'],
                'academic_levels': [
                    'freshman', 'sophomore', 'junior', 'senior', 'graduate', 'doctoral'
                ]
            },
            business_rules=[
                {
                    'type': 'gpa_calculation',
                    'description': 'GPA must be calculated correctly from course grades'
                },
                {
                    'type': 'prerequisite_validation',
                    'description': 'Students must complete prerequisites before enrolling'
                }
            ],
            typical_ranges={
                'gpa': {'min': 0.0, 'max': 4.0, 'distribution': 'normal'},
                'credit_hours': {'min': 1, 'max': 6, 'distribution': 'uniform'},
                'class_size': {'min': 5, 'max': 300, 'distribution': 'log_normal'}
            },
            relationships={
                'student_enrollments': ['one_to_many'],
                'course_sections': ['one_to_many'],
                'instructor_courses': ['one_to_many']
            }
        )
        
        # Store domain knowledge
        self.domain_knowledge = {
            'ecommerce': ecommerce_knowledge,
            'finance': finance_knowledge,
            'healthcare': healthcare_knowledge,
            'hr': hr_knowledge,
            'education': education_knowledge,
            'generic': DomainKnowledge(
                domain='generic',
                patterns={},
                business_rules=[],
                typical_ranges={},
                relationships={}
            )
        }
    
    def _load_locale_data(self):
        """Load locale-specific data for different regions."""
        
        # English (US) locale
        self.locale_data['en_US'] = {
            'first_names': [
                'James', 'Mary', 'John', 'Patricia', 'Robert', 'Jennifer', 'Michael', 'Linda',
                'William', 'Elizabeth', 'David', 'Barbara', 'Richard', 'Susan', 'Joseph', 'Jessica',
                'Thomas', 'Sarah', 'Christopher', 'Karen', 'Charles', 'Nancy', 'Daniel', 'Lisa'
            ],
            'last_names': [
                'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis',
                'Rodriguez', 'Martinez', 'Hernandez', 'Lopez', 'Gonzalez', 'Wilson', 'Anderson',
                'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin', 'Lee', 'Perez', 'Thompson'
            ],
            'companies': [
                'Tech Innovations Inc', 'Global Solutions LLC', 'Dynamic Systems Corp',
                'Premier Services Group', 'Advanced Technologies Ltd', 'Strategic Partners Inc',
                'Elite Consulting Services', 'Innovative Solutions Group', 'Professional Services Corp'
            ],
            'cities': [
                'New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia',
                'San Antonio', 'San Diego', 'Dallas', 'San Jose', 'Austin', 'Jacksonville'
            ],
            'states': [
                'California', 'Texas', 'Florida', 'New York', 'Illinois', 'Pennsylvania',
                'Ohio', 'Georgia', 'North Carolina', 'Michigan', 'New Jersey', 'Virginia'
            ],
            'phone_formats': [
                '({area_code}) {exchange}-{number}',
                '{area_code}-{exchange}-{number}',
                '{area_code}.{exchange}.{number}'
            ],
            'address_formats': [
                '{street_number} {street_name} {street_type}',
                '{street_number} {direction} {street_name} {street_type}',
                '{street_number} {street_name} {street_type}, Apt {apt_number}'
            ]
        }
        
        # Add more locales as needed
        self.locale_data['en_GB'] = {
            'first_names': ['Oliver', 'Amelia', 'George', 'Isla', 'Noah', 'Ava', 'Arthur', 'Mia'],
            'last_names': ['Smith', 'Jones', 'Taylor', 'Williams', 'Brown', 'Davies', 'Evans', 'Wilson'],
            'companies': ['British Solutions Ltd', 'Royal Services Group', 'United Kingdom Corp'],
            'cities': ['London', 'Birmingham', 'Leeds', 'Glasgow', 'Sheffield', 'Bradford', 'Liverpool'],
            'phone_formats': ['+44 {area_code} {exchange} {number}', '0{area_code} {exchange} {number}']
        }
    
    # Main generation methods
    def generate_value_by_meaning(self, meaning: str, field_type: str, 
                                 domain: str, locale: str, record_index: int) -> Any:
        """Generate value based on business meaning."""
        
        if meaning == 'email':
            return self._generate_email(locale, record_index)
        elif meaning == 'phone':
            return self._generate_phone_number(locale)
        elif meaning == 'name':
            return self._generate_person_name(locale)
        elif meaning == 'address':
            return self._generate_address(locale)
        elif meaning == 'date':
            return self._generate_date(field_type)
        elif meaning == 'id':
            return self._generate_id(field_type)
        elif meaning == 'status':
            return self._generate_status(domain)
        elif meaning == 'amount':
            return self._generate_amount(domain)
        elif meaning == 'description':
            return self._generate_description(domain)
        else:
            # Fallback to type-based generation
            return self.generate_value_by_type(field_type, {}, locale)
    
    def generate_value_by_strategy(self, strategy: str, field, 
                                  domain: str, locale: str, record_index: int) -> Any:
        """Generate value based on specific strategy."""
        
        if strategy == 'product_catalog':
            return self._generate_product_name(domain)
        elif strategy == 'order_sequence':
            return self._generate_order_id(record_index)
        elif strategy == 'account_number':
            return self._generate_account_number()
        elif strategy == 'transaction_pattern':
            return self._generate_transaction_reference()
        elif strategy == 'patient_demographics':
            return self._generate_patient_id()
        elif strategy == 'medical_codes':
            return self._generate_medical_code()
        else:
            return self.generate_value_by_type(field.field_type, field.constraints, locale)
    
    def generate_value_by_type(self, field_type: str, constraints: Dict[str, Any], locale: str) -> Any:
        """Generate value based on field type only."""
        
        if field_type == 'string':
            min_len = constraints.get('min_length', 1)
            max_len = constraints.get('max_length', 50)
            return self._generate_random_string(min_len, max_len)
        
        elif field_type == 'integer':
            min_val = constraints.get('min_value', 1)
            max_val = constraints.get('max_value', 1000)
            return random.randint(min_val, max_val)
        
        elif field_type == 'float':
            min_val = constraints.get('min_value', 0.0)
            max_val = constraints.get('max_value', 1000.0)
            return round(random.uniform(min_val, max_val), 2)
        
        elif field_type == 'boolean':
            return random.choice([True, False])
        
        elif field_type == 'date':
            return self._generate_date('date')
        
        elif field_type == 'datetime':
            return self._generate_date('datetime')
        
        elif field_type == 'email':
            return self._generate_email(locale, 0)
        
        elif field_type == 'url':
            return self._generate_url()
        
        elif field_type == 'phone':
            return self._generate_phone_number(locale)
        
        elif field_type == 'uuid':
            return str(uuid.uuid4())
        
        else:
            return f"generated_{field_type}_{random.randint(1, 1000)}"
    
    # Specific generation methods
    def _generate_email(self, locale: str, record_index: int) -> str:
        """Generate realistic email address."""
        locale_data = self.locale_data.get(locale, self.locale_data['en_US'])
        
        first_name = random.choice(locale_data['first_names']).lower()
        last_name = random.choice(locale_data['last_names']).lower()
        
        domains = [
            'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
            'company.com', 'business.org', 'example.com'
        ]
        
        patterns = [
            f"{first_name}.{last_name}",
            f"{first_name}_{last_name}",
            f"{first_name}{last_name}",
            f"{first_name[0]}{last_name}",
            f"{first_name}.{last_name}{random.randint(1, 99)}"
        ]
        
        username = random.choice(patterns)
        domain = random.choice(domains)
        
        return f"{username}@{domain}"
    
    def _generate_phone_number(self, locale: str) -> str:
        """Generate realistic phone number."""
        locale_data = self.locale_data.get(locale, self.locale_data['en_US'])
        
        if 'phone_formats' in locale_data:
            format_template = random.choice(locale_data['phone_formats'])
            
            # Generate phone number components
            area_code = random.randint(200, 999)
            exchange = random.randint(200, 999)
            number = random.randint(1000, 9999)
            
            return format_template.format(
                area_code=area_code,
                exchange=exchange,
                number=number
            )
        else:
            # Default US format
            return f"({random.randint(200, 999)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}"
    
    def _generate_person_name(self, locale: str) -> str:
        """Generate realistic person name."""
        locale_data = self.locale_data.get(locale, self.locale_data['en_US'])
        
        first_name = random.choice(locale_data['first_names'])
        last_name = random.choice(locale_data['last_names'])
        
        return f"{first_name} {last_name}"
    
    def _generate_address(self, locale: str) -> str:
        """Generate realistic address."""
        locale_data = self.locale_data.get(locale, self.locale_data['en_US'])
        
        street_number = random.randint(1, 9999)
        street_names = [
            'Main', 'Oak', 'Pine', 'Elm', 'Cedar', 'Park', 'Washington', 'Lincoln',
            'Jefferson', 'Madison', 'First', 'Second', 'Third', 'Broadway', 'Market'
        ]
        street_types = ['St', 'Ave', 'Blvd', 'Dr', 'Ln', 'Rd', 'Way', 'Pl', 'Ct']
        
        street_name = random.choice(street_names)
        street_type = random.choice(street_types)
        
        address = f"{street_number} {street_name} {street_type}"
        
        if 'cities' in locale_data and 'states' in locale_data:
            city = random.choice(locale_data['cities'])
            state = random.choice(locale_data['states'])
            zip_code = random.randint(10000, 99999)
            address += f", {city}, {state} {zip_code}"
        
        return address
    
    def _generate_date(self, field_type: str) -> str:
        """Generate realistic date or datetime."""
        # Generate date within reasonable range (past 5 years to next 1 year)
        start_date = datetime.now() - timedelta(days=365 * 5)
        end_date = datetime.now() + timedelta(days=365)
        
        random_date = start_date + timedelta(
            seconds=random.randint(0, int((end_date - start_date).total_seconds()))
        )
        
        if field_type == 'date':
            return random_date.date().isoformat()
        else:
            return random_date.isoformat()
    
    def _generate_id(self, field_type: str) -> Union[str, int]:
        """Generate ID based on type."""
        if field_type == 'uuid':
            return str(uuid.uuid4())
        elif field_type == 'string':
            return f"ID_{random.randint(100000, 999999)}"
        else:
            return random.randint(1, 999999)
    
    def _generate_status(self, domain: str) -> str:
        """Generate domain-appropriate status."""
        domain_knowledge = self.domain_knowledge.get(domain)
        
        if domain_knowledge and 'order_statuses' in domain_knowledge.patterns:
            return random.choice(domain_knowledge.patterns['order_statuses'])
        elif domain_knowledge and 'transaction_types' in domain_knowledge.patterns:
            return random.choice(domain_knowledge.patterns['transaction_types'])
        else:
            # Generic statuses
            return random.choice(['active', 'inactive', 'pending', 'completed', 'cancelled'])
    
    def _generate_amount(self, domain: str) -> float:
        """Generate domain-appropriate monetary amount."""
        domain_knowledge = self.domain_knowledge.get(domain)
        
        if domain_knowledge and domain in domain_knowledge.typical_ranges:
            if 'product_price' in domain_knowledge.typical_ranges:
                range_info = domain_knowledge.typical_ranges['product_price']
                return round(random.uniform(range_info['min'], range_info['max']), 2)
            elif 'transaction_amount' in domain_knowledge.typical_ranges:
                range_info = domain_knowledge.typical_ranges['transaction_amount']
                return round(random.uniform(range_info['min'], range_info['max']), 2)
        
        # Default amount range
        return round(random.uniform(1.0, 10000.0), 2)
    
    def _generate_description(self, domain: str) -> str:
        """Generate domain-appropriate description."""
        domain_knowledge = self.domain_knowledge.get(domain)
        
        if domain == 'ecommerce':
            adjectives = ['Premium', 'High-quality', 'Durable', 'Elegant', 'Professional', 'Innovative']
            features = ['with advanced features', 'for everyday use', 'designed for professionals', 
                       'with superior quality', 'built to last', 'with modern design']
            return f"{random.choice(adjectives)} product {random.choice(features)}"
        
        elif domain == 'finance':
            return f"Transaction processed on {self._generate_date('date')} with reference number {random.randint(1000000, 9999999)}"
        
        elif domain == 'healthcare':
            return f"Medical procedure scheduled for routine checkup and follow-up care"
        
        else:
            # Generic description
            return f"Description for item {random.randint(1, 1000)} with additional details and information"
    
    def _generate_product_name(self, domain: str) -> str:
        """Generate product name for e-commerce domain."""
        domain_knowledge = self.domain_knowledge.get(domain)
        
        if domain_knowledge and domain_knowledge.sample_products:
            return random.choice(domain_knowledge.sample_products)
        
        # Generate synthetic product name
        adjectives = ['Ultra', 'Pro', 'Max', 'Premium', 'Elite', 'Advanced', 'Smart', 'Digital']
        products = ['Phone', 'Laptop', 'Watch', 'Camera', 'Headphones', 'Speaker', 'Tablet', 'Monitor']
        models = ['X1', 'Pro', '2024', 'Elite', 'Max', 'Ultra', 'Plus', 'SE']
        
        return f"{random.choice(adjectives)} {random.choice(products)} {random.choice(models)}"
    
    def _generate_order_id(self, record_index: int) -> str:
        """Generate order ID with sequential pattern."""
        timestamp = datetime.now().strftime('%Y%m%d')
        return f"ORD-{timestamp}-{record_index + 1:06d}"
    
    def _generate_account_number(self) -> str:
        """Generate bank account number."""
        return f"{random.randint(100, 999)}-{random.randint(100, 999)}-{random.randint(100000, 999999)}"
    
    def _generate_transaction_reference(self) -> str:
        """Generate transaction reference number."""
        return f"TXN{datetime.now().strftime('%Y%m%d')}{random.randint(100000, 999999)}"
    
    def _generate_patient_id(self) -> str:
        """Generate patient ID for healthcare."""
        return f"PAT{random.randint(100000, 999999)}"
    
    def _generate_medical_code(self) -> str:
        """Generate medical diagnosis code."""
        # Simple ICD-10 style codes
        categories = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']
        return f"{random.choice(categories)}{random.randint(10, 99)}.{random.randint(0, 9)}"
    
    def _generate_url(self) -> str:
        """Generate realistic URL."""
        domains = ['example.com', 'company.org', 'business.net', 'website.com', 'service.io']
        paths = ['products', 'services', 'about', 'contact', 'blog', 'news', 'help', 'support']
        
        domain = random.choice(domains)
        path = random.choice(paths)
        
        return f"https://www.{domain}/{path}"
    
    def _generate_random_string(self, min_length: int, max_length: int) -> str:
        """Generate random string of specified length."""
        length = random.randint(min_length, max_length)
        characters = string.ascii_letters + string.digits
        return ''.join(random.choices(characters, k=length))
    
    # Domain-specific generators
    def get_domain_patterns(self, domain: str) -> Dict[str, List[str]]:
        """Get available patterns for a domain."""
        domain_knowledge = self.domain_knowledge.get(domain)
        return domain_knowledge.patterns if domain_knowledge else {}
    
    def get_domain_ranges(self, domain: str) -> Dict[str, Dict[str, Any]]:
        """Get typical ranges for a domain."""
        domain_knowledge = self.domain_knowledge.get(domain)
        return domain_knowledge.typical_ranges if domain_knowledge else {}
    
    def get_supported_domains(self) -> List[str]:
        """Get list of supported domains."""
        return list(self.domain_knowledge.keys())
    
    def get_supported_locales(self) -> List[str]:
        """Get list of supported locales."""
        return list(self.locale_data.keys())