"""
AI Data Generation Engine

Core engine that coordinates intelligent data generation using domain knowledge,
business patterns, and contextual understanding to produce realistic test data.
"""

import logging
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import random
import re

from ..models.data_models import DataGenerationRequest, GeneratedDataset, DataField, DataRelationship
from ..generators.domain_generator import DomainDataGenerator
from ..generators.relationship_generator import RelationshipGenerator
from ..patterns.business_patterns import BusinessPatternLibrary
from ..utils.data_analyzer import DataPatternAnalyzer
from ..utils.context_manager import BusinessContextManager

logger = logging.getLogger(__name__)


@dataclass
class AIDataConfiguration:
    """Configuration for AI data generation engine."""
    # Domain understanding
    enable_domain_detection: bool = True
    domain_confidence_threshold: float = 0.7
    
    # Pattern recognition
    enable_pattern_learning: bool = True
    pattern_memory_size: int = 1000
    
    # Data quality
    consistency_level: float = 0.9  # 0.0 to 1.0
    realism_level: float = 0.8
    
    # Performance
    generation_batch_size: int = 100
    max_generation_time: int = 300  # seconds
    
    # Language and localization
    default_locale: str = 'en_US'
    supported_locales: List[str] = None
    
    # External services (optional)
    enable_llm_assistance: bool = False
    llm_api_key: Optional[str] = None
    
    def __post_init__(self):
        if self.supported_locales is None:
            self.supported_locales = ['en_US', 'en_GB', 'es_ES', 'fr_FR', 'de_DE']


class AIDataEngine:
    """
    AI-powered data generation engine with domain intelligence.
    
    This engine combines multiple AI techniques to generate realistic,
    contextually appropriate test data:
    
    1. Domain Detection: Automatically identifies business domains
    2. Pattern Learning: Learns patterns from existing data
    3. Context Awareness: Understands relationships and constraints
    4. Business Rules: Applies domain-specific business logic
    5. Quality Assurance: Ensures data consistency and realism
    """
    
    def __init__(self, config: Optional[AIDataConfiguration] = None):
        self.config = config or AIDataConfiguration()
        
        # Initialize core components
        self.domain_generator = DomainDataGenerator()
        self.relationship_generator = RelationshipGenerator()
        self.pattern_library = BusinessPatternLibrary()
        self.data_analyzer = DataPatternAnalyzer()
        self.context_manager = BusinessContextManager()
        
        # State tracking
        self.learned_patterns: Dict[str, Any] = {}
        self.domain_cache: Dict[str, str] = {}
        self.generation_history: List[Dict[str, Any]] = []
        
        # Load pre-trained patterns
        self._load_pretrained_patterns()
        
        logger.info("AI Data Generation Engine initialized")
    
    def _load_pretrained_patterns(self):
        """Load pre-trained business patterns and domain knowledge."""
        try:
            # Load built-in patterns
            patterns_file = Path(__file__).parent.parent / 'data' / 'patterns.json'
            if patterns_file.exists():
                with open(patterns_file, 'r') as f:
                    pretrained = json.load(f)
                self.learned_patterns.update(pretrained)
                logger.info(f"Loaded {len(pretrained)} pre-trained patterns")
        except Exception as e:
            logger.warning(f"Could not load pre-trained patterns: {e}")
    
    # Main Generation API
    def generate_dataset(self, request: DataGenerationRequest) -> GeneratedDataset:
        """
        Generate a complete dataset based on the request.
        
        Args:
            request: Data generation request with specifications
            
        Returns:
            Generated dataset with metadata
        """
        logger.info(f"Generating dataset: {request.name}")
        start_time = datetime.now()
        
        try:
            # Step 1: Analyze request and detect domain
            domain = self._detect_domain(request)
            logger.info(f"Detected domain: {domain}")
            
            # Step 2: Build generation context
            context = self._build_generation_context(request, domain)
            
            # Step 3: Generate base data
            base_data = self._generate_base_data(request, context)
            
            # Step 4: Apply relationships and constraints
            related_data = self._apply_relationships(base_data, request.relationships, context)
            
            # Step 5: Apply business rules and patterns
            refined_data = self._apply_business_rules(related_data, domain, context)
            
            # Step 6: Quality assurance and validation
            final_data = self._validate_and_refine(refined_data, request, context)
            
            # Step 7: Create result dataset
            generation_time = (datetime.now() - start_time).total_seconds()
            
            dataset = GeneratedDataset(
                name=request.name,
                domain=domain,
                records=final_data,
                metadata={
                    'generation_time': generation_time,
                    'record_count': len(final_data),
                    'field_count': len(request.fields),
                    'relationship_count': len(request.relationships),
                    'domain_confidence': context.get('domain_confidence', 0.0),
                    'quality_score': self._calculate_quality_score(final_data, request),
                    'patterns_used': context.get('patterns_used', []),
                    'locale': context.get('locale', self.config.default_locale)
                },
                created_at=datetime.now()
            )
            
            # Update learning history
            self._update_learning_history(request, dataset, context)
            
            logger.info(f"Dataset generated successfully in {generation_time:.2f}s")
            return dataset
            
        except Exception as e:
            logger.error(f"Dataset generation failed: {e}")
            raise
    
    def _detect_domain(self, request: DataGenerationRequest) -> str:
        """
        Detect the business domain from the data request.
        
        Uses field names, table names, and context clues to identify
        the most likely business domain.
        """
        # Check cache first
        cache_key = f"{request.name}_{hash(tuple(f.name for f in request.fields))}"
        if cache_key in self.domain_cache:
            return self.domain_cache[cache_key]
        
        # Analyze field names and patterns
        field_indicators = []
        for field in request.fields:
            field_indicators.extend([
                field.name.lower(),
                field.field_type.lower(),
                field.description.lower() if field.description else ""
            ])
        
        # Add table/entity name
        if request.name:
            field_indicators.append(request.name.lower())
        
        # Domain detection patterns
        domain_patterns = {
            'ecommerce': [
                'product', 'order', 'customer', 'price', 'cart', 'payment',
                'shipping', 'inventory', 'catalog', 'purchase', 'sku', 'category'
            ],
            'finance': [
                'account', 'transaction', 'balance', 'credit', 'debit', 'loan',
                'interest', 'rate', 'currency', 'invoice', 'payment', 'bank'
            ],
            'healthcare': [
                'patient', 'doctor', 'diagnosis', 'treatment', 'medication',
                'appointment', 'medical', 'hospital', 'clinic', 'prescription'
            ],
            'education': [
                'student', 'teacher', 'course', 'grade', 'enrollment', 'class',
                'school', 'university', 'exam', 'assignment', 'semester'
            ],
            'hr': [
                'employee', 'department', 'salary', 'position', 'hire', 'manager',
                'performance', 'benefits', 'payroll', 'staff', 'team'
            ],
            'crm': [
                'lead', 'contact', 'opportunity', 'campaign', 'prospect',
                'client', 'deal', 'pipeline', 'sales', 'marketing'
            ],
            'inventory': [
                'warehouse', 'stock', 'item', 'location', 'quantity', 'supplier',
                'vendor', 'shipment', 'tracking', 'logistics'
            ],
            'real_estate': [
                'property', 'listing', 'agent', 'buyer', 'seller', 'commission',
                'mortgage', 'rent', 'lease', 'address', 'square_feet'
            ]
        }
        
        # Calculate domain scores
        domain_scores = {}
        for domain, keywords in domain_patterns.items():
            score = 0
            for indicator in field_indicators:
                for keyword in keywords:
                    if keyword in indicator:
                        score += 1
            
            # Normalize by keyword count
            domain_scores[domain] = score / len(keywords) if keywords else 0
        
        # Find best match
        best_domain = max(domain_scores.items(), key=lambda x: x[1])
        
        if best_domain[1] >= self.config.domain_confidence_threshold:
            detected_domain = best_domain[0]
        else:
            detected_domain = 'generic'
        
        # Cache result
        self.domain_cache[cache_key] = detected_domain
        
        return detected_domain
    
    def _build_generation_context(self, request: DataGenerationRequest, domain: str) -> Dict[str, Any]:
        """Build context for data generation including domain knowledge and patterns."""
        context = {
            'domain': domain,
            'locale': getattr(request, 'locale', self.config.default_locale),
            'patterns_used': [],
            'domain_confidence': 0.0,
            'business_rules': [],
            'constraints': {},
            'field_context': {}
        }
        
        # Add domain-specific context
        domain_context = self.context_manager.get_domain_context(domain)
        context.update(domain_context)
        
        # Analyze field context
        for field in request.fields:
            field_context = self._analyze_field_context(field, domain)
            context['field_context'][field.name] = field_context
        
        # Load applicable patterns
        patterns = self.pattern_library.get_patterns_for_domain(domain)
        context['patterns_used'] = [p.name for p in patterns]
        context['domain_confidence'] = self._calculate_domain_confidence(request, domain)
        
        return context
    
    def _analyze_field_context(self, field: DataField, domain: str) -> Dict[str, Any]:
        """Analyze individual field context for intelligent generation."""
        context = {
            'generation_strategy': 'random',
            'constraints': [],
            'patterns': [],
            'related_fields': [],
            'business_meaning': None
        }
        
        field_name = field.name.lower()
        field_type = field.field_type.lower()
        
        # Detect field purpose and meaning
        field_meanings = {
            'email': ['email', 'mail', 'e_mail'],
            'phone': ['phone', 'telephone', 'mobile', 'tel'],
            'name': ['name', 'first_name', 'last_name', 'full_name', 'username'],
            'address': ['address', 'street', 'city', 'state', 'zip', 'postal'],
            'date': ['date', 'created', 'updated', 'birth', 'hired'],
            'id': ['id', 'key', 'identifier', 'uuid'],
            'status': ['status', 'state', 'condition', 'phase'],
            'amount': ['amount', 'price', 'cost', 'value', 'salary', 'total'],
            'description': ['description', 'notes', 'comment', 'summary']
        }
        
        for meaning, keywords in field_meanings.items():
            if any(keyword in field_name for keyword in keywords):
                context['business_meaning'] = meaning
                break
        
        # Add domain-specific field analysis
        if domain == 'ecommerce':
            if 'product' in field_name:
                context['generation_strategy'] = 'product_catalog'
            elif 'order' in field_name:
                context['generation_strategy'] = 'order_sequence'
        elif domain == 'finance':
            if 'account' in field_name:
                context['generation_strategy'] = 'account_number'
            elif 'transaction' in field_name:
                context['generation_strategy'] = 'transaction_pattern'
        elif domain == 'healthcare':
            if 'patient' in field_name:
                context['generation_strategy'] = 'patient_demographics'
            elif 'diagnosis' in field_name:
                context['generation_strategy'] = 'medical_codes'
        
        # Add validation patterns
        if field.validation_rules:
            context['constraints'] = field.validation_rules
        
        return context
    
    def _generate_base_data(self, request: DataGenerationRequest, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate base data for all fields."""
        records = []
        
        for i in range(request.record_count):
            record = {}
            
            for field in request.fields:
                field_context = context['field_context'][field.name]
                value = self._generate_field_value(field, field_context, context, i)
                record[field.name] = value
            
            records.append(record)
        
        return records
    
    def _generate_field_value(self, field: DataField, field_context: Dict[str, Any], 
                            global_context: Dict[str, Any], record_index: int) -> Any:
        """Generate a single field value using AI-driven strategies."""
        
        strategy = field_context.get('generation_strategy', 'random')
        business_meaning = field_context.get('business_meaning')
        domain = global_context['domain']
        locale = global_context['locale']
        
        # Use domain generator for intelligent value generation
        if business_meaning:
            return self.domain_generator.generate_value_by_meaning(
                business_meaning, field.field_type, domain, locale, record_index
            )
        elif strategy != 'random':
            return self.domain_generator.generate_value_by_strategy(
                strategy, field, domain, locale, record_index
            )
        else:
            # Fallback to type-based generation
            return self.domain_generator.generate_value_by_type(
                field.field_type, field.constraints, locale
            )
    
    def _apply_relationships(self, base_data: List[Dict[str, Any]], 
                           relationships: List[DataRelationship],
                           context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Apply relationships and referential integrity."""
        if not relationships:
            return base_data
        
        return self.relationship_generator.apply_relationships(
            base_data, relationships, context
        )
    
    def _apply_business_rules(self, data: List[Dict[str, Any]], 
                            domain: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Apply domain-specific business rules and patterns."""
        
        # Get business rules for domain
        business_rules = self.pattern_library.get_business_rules(domain)
        
        if not business_rules:
            return data
        
        modified_data = []
        
        for record in data:
            # Apply each business rule
            for rule in business_rules:
                record = self._apply_single_business_rule(record, rule, context)
            
            modified_data.append(record)
        
        return modified_data
    
    def _apply_single_business_rule(self, record: Dict[str, Any], 
                                  rule: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply a single business rule to a record."""
        
        rule_type = rule.get('type')
        
        if rule_type == 'conditional_value':
            # Apply conditional value rules
            condition_field = rule.get('condition_field')
            condition_value = rule.get('condition_value')
            target_field = rule.get('target_field')
            target_value = rule.get('target_value')
            
            if (condition_field in record and 
                record[condition_field] == condition_value and
                target_field in record):
                record[target_field] = target_value
                
        elif rule_type == 'calculated_field':
            # Apply calculated field rules
            target_field = rule.get('target_field')
            calculation = rule.get('calculation')
            source_fields = rule.get('source_fields', [])
            
            if all(field in record for field in source_fields):
                try:
                    # Simple calculation evaluation (extend as needed)
                    if calculation == 'sum':
                        record[target_field] = sum(record[f] for f in source_fields if isinstance(record[f], (int, float)))
                    elif calculation == 'average':
                        values = [record[f] for f in source_fields if isinstance(record[f], (int, float))]
                        record[target_field] = sum(values) / len(values) if values else 0
                    elif calculation == 'concat':
                        record[target_field] = ' '.join(str(record[f]) for f in source_fields)
                except Exception as e:
                    logger.warning(f"Failed to apply calculation {calculation}: {e}")
        
        elif rule_type == 'data_consistency':
            # Apply data consistency rules
            consistency_rules = rule.get('rules', [])
            for consistency_rule in consistency_rules:
                record = self._apply_consistency_rule(record, consistency_rule)
        
        return record
    
    def _apply_consistency_rule(self, record: Dict[str, Any], rule: Dict[str, Any]) -> Dict[str, Any]:
        """Apply data consistency rules."""
        
        rule_name = rule.get('name')
        
        if rule_name == 'email_username_consistency':
            # Ensure email matches username pattern
            if 'email' in record and 'username' in record:
                username = record['username']
                if '@' not in str(record['email']) or not str(record['email']).startswith(username):
                    domain_part = '@company.com'  # Default domain
                    record['email'] = f"{username}{domain_part}"
        
        elif rule_name == 'date_ordering':
            # Ensure date fields are in logical order
            date_fields = rule.get('date_fields', [])
            date_values = []
            
            for field in date_fields:
                if field in record and record[field]:
                    try:
                        if isinstance(record[field], str):
                            date_val = datetime.fromisoformat(record[field].replace('Z', '+00:00'))
                        else:
                            date_val = record[field]
                        date_values.append((field, date_val))
                    except:
                        continue
            
            # Sort and reassign if needed
            if len(date_values) > 1:
                date_values.sort(key=lambda x: x[1])
                for i, (field, _) in enumerate(date_values):
                    if i > 0:
                        # Ensure later dates are actually later
                        prev_date = date_values[i-1][1]
                        if date_values[i][1] <= prev_date:
                            # Add random time difference
                            time_diff = timedelta(
                                hours=random.randint(1, 24),
                                minutes=random.randint(0, 59)
                            )
                            new_date = prev_date + time_diff
                            record[field] = new_date.isoformat()
        
        return record
    
    def _validate_and_refine(self, data: List[Dict[str, Any]], 
                           request: DataGenerationRequest, 
                           context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate generated data and apply final refinements."""
        
        refined_data = []
        
        for record in data:
            # Validate each field
            valid_record = {}
            
            for field in request.fields:
                field_value = record.get(field.name)
                
                # Apply field-level validation
                validated_value = self._validate_field_value(field_value, field)
                valid_record[field.name] = validated_value
            
            # Apply record-level validation
            if self._validate_record(valid_record, request.validation_rules):
                refined_data.append(valid_record)
        
        # Ensure we have enough valid records
        while len(refined_data) < request.record_count:
            # Generate additional records if validation failed some
            additional_record = {}
            for field in request.fields:
                field_context = context['field_context'][field.name]
                value = self._generate_field_value(field, field_context, context, len(refined_data))
                validated_value = self._validate_field_value(value, field)
                additional_record[field.name] = validated_value
            
            if self._validate_record(additional_record, request.validation_rules):
                refined_data.append(additional_record)
        
        return refined_data[:request.record_count]
    
    def _validate_field_value(self, value: Any, field: DataField) -> Any:
        """Validate and fix a single field value."""
        
        # Type validation
        if field.field_type == 'integer' and not isinstance(value, int):
            try:
                value = int(float(value))
            except (ValueError, TypeError):
                value = 0
        
        elif field.field_type == 'float' and not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (ValueError, TypeError):
                value = 0.0
        
        elif field.field_type == 'string' and not isinstance(value, str):
            value = str(value)
        
        elif field.field_type == 'boolean':
            if not isinstance(value, bool):
                value = bool(value) if value not in [0, '0', '', None] else False
        
        # Constraint validation
        if field.constraints:
            if 'min_length' in field.constraints and isinstance(value, str):
                min_len = field.constraints['min_length']
                if len(value) < min_len:
                    value = value + 'x' * (min_len - len(value))
            
            if 'max_length' in field.constraints and isinstance(value, str):
                max_len = field.constraints['max_length']
                if len(value) > max_len:
                    value = value[:max_len]
            
            if 'min_value' in field.constraints and isinstance(value, (int, float)):
                value = max(value, field.constraints['min_value'])
            
            if 'max_value' in field.constraints and isinstance(value, (int, float)):
                value = min(value, field.constraints['max_value'])
        
        return value
    
    def _validate_record(self, record: Dict[str, Any], validation_rules: List[Dict[str, Any]]) -> bool:
        """Validate a complete record against rules."""
        
        if not validation_rules:
            return True
        
        for rule in validation_rules:
            rule_type = rule.get('type')
            
            if rule_type == 'required_fields':
                required_fields = rule.get('fields', [])
                for field in required_fields:
                    if field not in record or record[field] is None or record[field] == '':
                        return False
            
            elif rule_type == 'unique_combination':
                # This would require checking against all generated records
                # Skip for now, could be implemented with a global registry
                continue
            
            elif rule_type == 'custom_validation':
                # Execute custom validation function
                validation_func = rule.get('function')
                if validation_func and callable(validation_func):
                    if not validation_func(record):
                        return False
        
        return True
    
    def _calculate_quality_score(self, data: List[Dict[str, Any]], 
                               request: DataGenerationRequest) -> float:
        """Calculate a quality score for the generated data."""
        
        if not data:
            return 0.0
        
        scores = []
        
        # Completeness score
        completeness = 0
        total_fields = len(request.fields) * len(data)
        filled_fields = sum(
            1 for record in data 
            for field in request.fields 
            if record.get(field.name) is not None and record.get(field.name) != ''
        )
        completeness = filled_fields / total_fields if total_fields > 0 else 0
        scores.append(completeness)
        
        # Uniqueness score (for fields that should be unique)
        uniqueness_scores = []
        for field in request.fields:
            if field.constraints and field.constraints.get('unique', False):
                values = [record.get(field.name) for record in data]
                unique_values = len(set(v for v in values if v is not None))
                total_values = len([v for v in values if v is not None])
                uniqueness = unique_values / total_values if total_values > 0 else 1.0
                uniqueness_scores.append(uniqueness)
        
        if uniqueness_scores:
            scores.append(sum(uniqueness_scores) / len(uniqueness_scores))
        
        # Realism score (basic heuristic)
        realism = self.config.realism_level  # Use configured realism level
        scores.append(realism)
        
        # Consistency score (basic heuristic)
        consistency = self.config.consistency_level  # Use configured consistency level
        scores.append(consistency)
        
        # Return average of all scores
        return sum(scores) / len(scores)
    
    def _calculate_domain_confidence(self, request: DataGenerationRequest, domain: str) -> float:
        """Calculate confidence in domain detection."""
        # This is a simplified implementation
        # In practice, this could use machine learning models
        
        field_names = [f.name.lower() for f in request.fields]
        
        # Count domain-specific keywords
        domain_keywords = {
            'ecommerce': ['product', 'order', 'customer', 'price', 'cart'],
            'finance': ['account', 'transaction', 'balance', 'payment'],
            'healthcare': ['patient', 'doctor', 'diagnosis', 'treatment'],
            'education': ['student', 'teacher', 'course', 'grade'],
            'hr': ['employee', 'department', 'salary', 'position'],
            'crm': ['lead', 'contact', 'opportunity', 'campaign'],
        }
        
        if domain in domain_keywords:
            keywords = domain_keywords[domain]
            matches = sum(1 for field in field_names for keyword in keywords if keyword in field)
            confidence = min(matches / len(keywords), 1.0)
        else:
            confidence = 0.5  # Default confidence for generic domain
        
        return confidence
    
    def _update_learning_history(self, request: DataGenerationRequest, 
                               dataset: GeneratedDataset, context: Dict[str, Any]):
        """Update learning history for continuous improvement."""
        
        history_entry = {
            'timestamp': datetime.now().isoformat(),
            'request_name': request.name,
            'domain': dataset.domain,
            'record_count': len(dataset.records),
            'field_count': len(request.fields),
            'quality_score': dataset.metadata.get('quality_score', 0.0),
            'generation_time': dataset.metadata.get('generation_time', 0.0),
            'patterns_used': context.get('patterns_used', []),
            'successful_strategies': []
        }
        
        # Track successful generation strategies
        for field_name, field_context in context.get('field_context', {}).items():
            if field_context.get('generation_strategy') != 'random':
                history_entry['successful_strategies'].append({
                    'field': field_name,
                    'strategy': field_context['generation_strategy'],
                    'meaning': field_context.get('business_meaning')
                })
        
        self.generation_history.append(history_entry)
        
        # Limit history size
        if len(self.generation_history) > self.config.pattern_memory_size:
            self.generation_history = self.generation_history[-self.config.pattern_memory_size:]
        
        logger.debug(f"Updated learning history: {len(self.generation_history)} entries")
    
    # Utility methods
    def get_supported_domains(self) -> List[str]:
        """Get list of supported business domains."""
        return self.pattern_library.get_supported_domains()
    
    def get_domain_patterns(self, domain: str) -> List[Dict[str, Any]]:
        """Get available patterns for a specific domain."""
        patterns = self.pattern_library.get_patterns_for_domain(domain)
        return [{'name': p.name, 'description': p.description} for p in patterns]
    
    def analyze_existing_data(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze existing data to learn patterns."""
        return self.data_analyzer.analyze_patterns(data)
    
    def get_generation_statistics(self) -> Dict[str, Any]:
        """Get statistics about data generation performance."""
        if not self.generation_history:
            return {'total_generations': 0}
        
        total_generations = len(self.generation_history)
        avg_quality = sum(h.get('quality_score', 0) for h in self.generation_history) / total_generations
        avg_time = sum(h.get('generation_time', 0) for h in self.generation_history) / total_generations
        
        domains_used = {}
        for entry in self.generation_history:
            domain = entry.get('domain', 'unknown')
            domains_used[domain] = domains_used.get(domain, 0) + 1
        
        return {
            'total_generations': total_generations,
            'average_quality_score': avg_quality,
            'average_generation_time': avg_time,
            'domains_used': domains_used,
            'most_common_domain': max(domains_used.items(), key=lambda x: x[1])[0] if domains_used else None
        }