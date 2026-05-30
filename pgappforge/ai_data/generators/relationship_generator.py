"""
Relationship Generator

Handles generation of related data with proper referential integrity,
foreign key relationships, and cross-table dependencies.
"""

import logging
import random
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime, timedelta
from dataclasses import dataclass

from ..models.data_models import DataRelationship

logger = logging.getLogger(__name__)


@dataclass
class RelationshipContext:
    """Context for relationship generation."""
    parent_records: List[Dict[str, Any]]
    child_records: List[Dict[str, Any]]
    relationship_config: Dict[str, Any]
    generation_strategy: str = "balanced"
    integrity_level: float = 0.95


class RelationshipGenerator:
    """
    Generates realistic relationships between data entities.
    
    Supports various relationship types:
    - One-to-one (1:1)
    - One-to-many (1:N)  
    - Many-to-many (M:N)
    - Self-referencing relationships
    - Hierarchical relationships
    """
    
    def __init__(self):
        self.relationship_patterns = self._init_relationship_patterns()
        self.integrity_rules = self._init_integrity_rules()
        
    def _init_relationship_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Initialize common relationship patterns by domain."""
        return {
            'ecommerce': {
                'customer_orders': {
                    'type': 'one_to_many',
                    'cardinality_range': (1, 8),
                    'distribution': 'power_law',  # Few customers with many orders
                    'temporal_pattern': 'seasonal',
                    'business_rules': ['no_future_orders', 'increasing_order_ids']
                },
                'order_items': {
                    'type': 'one_to_many', 
                    'cardinality_range': (1, 12),
                    'distribution': 'normal',
                    'business_rules': ['total_amount_consistency', 'valid_quantities']
                },
                'product_categories': {
                    'type': 'many_to_many',
                    'cardinality_range': (1, 5),
                    'distribution': 'normal'
                }
            },
            'finance': {
                'account_transactions': {
                    'type': 'one_to_many',
                    'cardinality_range': (5, 100),
                    'distribution': 'exponential',
                    'temporal_pattern': 'daily_pattern',
                    'business_rules': ['balance_consistency', 'transaction_ordering']
                },
                'customer_accounts': {
                    'type': 'one_to_many',
                    'cardinality_range': (1, 5),
                    'distribution': 'normal',
                    'business_rules': ['account_type_consistency']
                }
            },
            'healthcare': {
                'patient_appointments': {
                    'type': 'one_to_many',
                    'cardinality_range': (1, 20),
                    'distribution': 'normal',
                    'temporal_pattern': 'appointment_scheduling',
                    'business_rules': ['no_overlapping_appointments', 'logical_scheduling']
                },
                'doctor_patients': {
                    'type': 'many_to_many',
                    'cardinality_range': (10, 200),
                    'distribution': 'power_law'
                }
            },
            'hr': {
                'department_employees': {
                    'type': 'one_to_many',
                    'cardinality_range': (3, 50),
                    'distribution': 'normal',
                    'business_rules': ['manager_hierarchy', 'salary_consistency']
                },
                'employee_manager': {
                    'type': 'many_to_one',
                    'cardinality_range': (1, 1),
                    'distribution': 'hierarchical',
                    'business_rules': ['no_self_management', 'hierarchy_depth_limit']
                }
            }
        }
    
    def _init_integrity_rules(self) -> Dict[str, Dict[str, Any]]:
        """Initialize referential integrity rules."""
        return {
            'foreign_key_constraints': {
                'enforce_existence': True,
                'null_percentage': 0.05,  # 5% can be null if allowed
                'orphan_prevention': True
            },
            'cascade_rules': {
                'delete_cascade': False,  # Don't generate deleted records
                'update_cascade': True    # Update references when parent changes
            },
            'temporal_consistency': {
                'child_after_parent': True,
                'logical_ordering': True,
                'timestamp_precision': 'seconds'
            }
        }
    
    def apply_relationships(self, base_data: List[Dict[str, Any]], 
                          relationships: List[DataRelationship],
                          context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Apply relationships to base data, generating realistic relationship patterns.
        
        Args:
            base_data: Generated base data records
            relationships: List of relationships to apply
            context: Generation context with domain information
            
        Returns:
            Data with properly applied relationships
        """
        if not relationships:
            return base_data
        
        logger.info(f"Applying {len(relationships)} relationships")
        
        # Group data by entity/table
        data_by_entity = self._group_data_by_entity(base_data, context)
        
        # Sort relationships by dependency order
        sorted_relationships = self._sort_relationships_by_dependency(relationships)
        
        # Apply each relationship
        for relationship in sorted_relationships:
            data_by_entity = self._apply_single_relationship(
                data_by_entity, relationship, context
            )
        
        # Flatten back to single list
        return self._flatten_data(data_by_entity)
    
    def _group_data_by_entity(self, base_data: List[Dict[str, Any]], 
                            context: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Group data records by entity/table name."""
        # For now, assume all data belongs to same entity
        # In practice, this would separate by table/entity name
        entity_name = context.get('entity_name', 'main_entity')
        return {entity_name: base_data}
    
    def _sort_relationships_by_dependency(self, relationships: List[DataRelationship]) -> List[DataRelationship]:
        """Sort relationships to handle dependencies in correct order."""
        # Simple implementation - in practice would use topological sort
        return sorted(relationships, key=lambda r: (r.relationship_type, r.from_table, r.to_table))
    
    def _apply_single_relationship(self, data_by_entity: Dict[str, List[Dict[str, Any]]], 
                                 relationship: DataRelationship,
                                 context: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Apply a single relationship between entities."""
        
        from_entity = relationship.from_table
        to_entity = relationship.to_table
        
        if from_entity not in data_by_entity or to_entity not in data_by_entity:
            logger.warning(f"Entity not found for relationship {from_entity} -> {to_entity}")
            return data_by_entity
        
        from_records = data_by_entity[from_entity]
        to_records = data_by_entity[to_entity]
        
        # Get relationship pattern for domain
        domain = context.get('domain', 'generic')
        pattern = self._get_relationship_pattern(relationship, domain)
        
        # Apply relationship based on type
        if relationship.relationship_type == 'one_to_one':
            self._apply_one_to_one(from_records, to_records, relationship, pattern)
        elif relationship.relationship_type == 'one_to_many':
            self._apply_one_to_many(from_records, to_records, relationship, pattern)
        elif relationship.relationship_type == 'many_to_many':
            self._apply_many_to_many(from_records, to_records, relationship, pattern, data_by_entity)
        elif relationship.relationship_type == 'many_to_one':
            self._apply_many_to_one(from_records, to_records, relationship, pattern)
        
        return data_by_entity
    
    def _get_relationship_pattern(self, relationship: DataRelationship, 
                                domain: str) -> Dict[str, Any]:
        """Get relationship pattern configuration for domain."""
        
        # Check if we have domain-specific patterns
        domain_patterns = self.relationship_patterns.get(domain, {})
        
        # Try to match by relationship name or entities
        pattern_key = f"{relationship.from_table}_{relationship.to_table}"
        if pattern_key in domain_patterns:
            return domain_patterns[pattern_key]
        
        # Try entity names
        for entity in [relationship.from_table, relationship.to_table]:
            for pattern_name, pattern in domain_patterns.items():
                if entity.lower() in pattern_name.lower():
                    return pattern
        
        # Default pattern based on relationship type
        return self._get_default_pattern(relationship.relationship_type)
    
    def _get_default_pattern(self, relationship_type: str) -> Dict[str, Any]:
        """Get default pattern for relationship type."""
        defaults = {
            'one_to_one': {
                'cardinality_range': (1, 1),
                'distribution': 'uniform',
                'business_rules': []
            },
            'one_to_many': {
                'cardinality_range': (1, 10),
                'distribution': 'normal',
                'business_rules': []
            },
            'many_to_many': {
                'cardinality_range': (1, 5),
                'distribution': 'normal',
                'business_rules': []
            },
            'many_to_one': {
                'cardinality_range': (1, 1),
                'distribution': 'uniform',
                'business_rules': []
            }
        }
        
        return defaults.get(relationship_type, defaults['one_to_many'])
    
    def _apply_one_to_one(self, from_records: List[Dict[str, Any]], 
                         to_records: List[Dict[str, Any]], 
                         relationship: DataRelationship,
                         pattern: Dict[str, Any]):
        """Apply one-to-one relationship."""
        
        # Shuffle to randomize pairing
        available_to_records = to_records.copy()
        random.shuffle(available_to_records)
        
        for i, from_record in enumerate(from_records):
            if i < len(available_to_records):
                to_record = available_to_records[i]
                
                # Create foreign key reference
                from_key_value = from_record.get(relationship.from_column)
                to_record[relationship.to_column] = from_key_value
                
                # Apply business rules
                self._apply_relationship_business_rules(
                    from_record, to_record, pattern.get('business_rules', [])
                )
    
    def _apply_one_to_many(self, from_records: List[Dict[str, Any]], 
                          to_records: List[Dict[str, Any]], 
                          relationship: DataRelationship,
                          pattern: Dict[str, Any]):
        """Apply one-to-many relationship."""
        
        cardinality_range = pattern.get('cardinality_range', (1, 10))
        distribution = pattern.get('distribution', 'normal')
        
        # Calculate how many children each parent should have
        parent_child_counts = self._calculate_cardinalities(
            len(from_records), len(to_records), cardinality_range, distribution
        )
        
        child_index = 0
        for parent_index, from_record in enumerate(from_records):
            child_count = parent_child_counts[parent_index]
            
            # Assign children to this parent
            for _ in range(child_count):
                if child_index < len(to_records):
                    to_record = to_records[child_index]
                    
                    # Create foreign key reference
                    parent_key_value = from_record.get(relationship.from_column)
                    to_record[relationship.to_column] = parent_key_value
                    
                    # Apply business rules
                    self._apply_relationship_business_rules(
                        from_record, to_record, pattern.get('business_rules', [])
                    )
                    
                    child_index += 1
                else:
                    break
    
    def _apply_many_to_many(self, from_records: List[Dict[str, Any]], 
                           to_records: List[Dict[str, Any]], 
                           relationship: DataRelationship,
                           pattern: Dict[str, Any],
                           data_by_entity: Dict[str, List[Dict[str, Any]]]):
        """Apply many-to-many relationship through junction table."""
        
        cardinality_range = pattern.get('cardinality_range', (1, 5))
        distribution = pattern.get('distribution', 'normal')
        
        # Create junction table records
        junction_records = []
        
        for from_record in from_records:
            # Determine how many relationships this record should have
            relationship_count = self._sample_cardinality(cardinality_range, distribution)
            
            # Select random to_records for relationships
            selected_to_records = random.sample(
                to_records, 
                min(relationship_count, len(to_records))
            )
            
            for to_record in selected_to_records:
                junction_record = {
                    relationship.from_column: from_record.get(relationship.from_column),
                    relationship.to_column: to_record.get(relationship.to_column),
                    'created_at': datetime.now().isoformat()
                }
                
                # Add any additional junction table fields
                if hasattr(relationship, 'junction_fields'):
                    for field_name, field_config in relationship.junction_fields.items():
                        junction_record[field_name] = self._generate_junction_field_value(
                            field_name, field_config, from_record, to_record
                        )
                
                junction_records.append(junction_record)
        
        # Add junction table to data
        junction_table_name = f"{relationship.from_table}_{relationship.to_table}"
        data_by_entity[junction_table_name] = junction_records
    
    def _apply_many_to_one(self, from_records: List[Dict[str, Any]], 
                          to_records: List[Dict[str, Any]], 
                          relationship: DataRelationship,
                          pattern: Dict[str, Any]):
        """Apply many-to-one relationship."""
        
        distribution = pattern.get('distribution', 'uniform')
        
        # Assign each from_record to a to_record
        for from_record in from_records:
            # Select parent based on distribution
            if distribution == 'uniform':
                to_record = random.choice(to_records)
            elif distribution == 'power_law':
                # Some parents get more children
                weights = [(i + 1) ** -1.5 for i in range(len(to_records))]
                to_record = random.choices(to_records, weights=weights)[0]
            else:
                to_record = random.choice(to_records)
            
            # Create foreign key reference
            parent_key_value = to_record.get(relationship.to_column)
            from_record[relationship.from_column] = parent_key_value
            
            # Apply business rules
            self._apply_relationship_business_rules(
                to_record, from_record, pattern.get('business_rules', [])
            )
    
    def _calculate_cardinalities(self, parent_count: int, child_count: int,
                               cardinality_range: Tuple[int, int],
                               distribution: str) -> List[int]:
        """Calculate how many children each parent should have."""
        
        min_children, max_children = cardinality_range
        
        if distribution == 'uniform':
            # Uniform distribution
            return [random.randint(min_children, max_children) for _ in range(parent_count)]
        
        elif distribution == 'normal':
            # Normal distribution around mean
            mean_children = (min_children + max_children) / 2
            std_dev = (max_children - min_children) / 4
            
            cardinalities = []
            remaining_children = child_count
            
            for i in range(parent_count):
                if i == parent_count - 1:
                    # Last parent gets remaining children
                    cardinalities.append(max(0, remaining_children))
                else:
                    # Sample from normal distribution
                    children = max(min_children, 
                                 min(max_children,
                                     int(random.normalvariate(mean_children, std_dev))))
                    children = min(children, remaining_children)
                    cardinalities.append(children)
                    remaining_children -= children
            
            return cardinalities
        
        elif distribution == 'power_law':
            # Power law - few parents with many children
            cardinalities = []
            remaining_children = child_count
            
            # Generate power law weights
            weights = [(i + 1) ** -1.5 for i in range(parent_count)]
            total_weight = sum(weights)
            
            for i, weight in enumerate(weights):
                if i == parent_count - 1:
                    cardinalities.append(remaining_children)
                else:
                    proportion = weight / total_weight
                    children = max(min_children,
                                 min(max_children,
                                     int(child_count * proportion)))
                    children = min(children, remaining_children)
                    cardinalities.append(children)
                    remaining_children -= children
            
            return cardinalities
        
        else:
            # Default to uniform
            return self._calculate_cardinalities(parent_count, child_count, 
                                               cardinality_range, 'uniform')
    
    def _sample_cardinality(self, cardinality_range: Tuple[int, int], 
                          distribution: str) -> int:
        """Sample a single cardinality value."""
        min_val, max_val = cardinality_range
        
        if distribution == 'uniform':
            return random.randint(min_val, max_val)
        elif distribution == 'normal':
            mean = (min_val + max_val) / 2
            std_dev = (max_val - min_val) / 4
            return max(min_val, min(max_val, int(random.normalvariate(mean, std_dev))))
        else:
            return random.randint(min_val, max_val)
    
    def _generate_junction_field_value(self, field_name: str, field_config: Dict[str, Any],
                                     from_record: Dict[str, Any], 
                                     to_record: Dict[str, Any]) -> Any:
        """Generate value for junction table field."""
        
        field_type = field_config.get('type', 'string')
        
        if field_name.endswith('_at') or field_name.endswith('_date'):
            # Timestamp fields
            return datetime.now().isoformat()
        elif field_name == 'priority' or field_name == 'weight':
            # Priority or weight fields
            return random.randint(1, 10)
        elif field_name == 'status':
            # Status fields
            statuses = field_config.get('values', ['active', 'inactive'])
            return random.choice(statuses)
        elif field_type == 'integer':
            return random.randint(field_config.get('min', 0), field_config.get('max', 100))
        elif field_type == 'float':
            return random.uniform(field_config.get('min', 0.0), field_config.get('max', 100.0))
        else:
            return field_config.get('default', '')
    
    def _apply_relationship_business_rules(self, parent_record: Dict[str, Any], 
                                         child_record: Dict[str, Any],
                                         business_rules: List[str]):
        """Apply domain-specific business rules to relationships."""
        
        for rule in business_rules:
            if rule == 'no_future_orders':
                # Ensure order dates are not in the future
                if 'order_date' in child_record:
                    order_date = datetime.fromisoformat(child_record['order_date'].replace('Z', '+00:00'))
                    if order_date > datetime.now():
                        child_record['order_date'] = datetime.now().isoformat()
            
            elif rule == 'increasing_order_ids':
                # Ensure order IDs increase over time
                if 'order_id' in child_record and 'customer_since' in parent_record:
                    # Generate order ID based on customer age
                    customer_since = datetime.fromisoformat(parent_record['customer_since'].replace('Z', '+00:00'))
                    days_since = (datetime.now() - customer_since).days
                    base_order_id = max(1000, days_since * 10)
                    child_record['order_id'] = base_order_id + random.randint(1, 100)
            
            elif rule == 'balance_consistency':
                # Ensure account balance reflects transaction history
                if 'balance' in parent_record and 'amount' in child_record:
                    # This would require more complex logic to track running balance
                    pass
            
            elif rule == 'transaction_ordering':
                # Ensure transactions are ordered chronologically
                if 'transaction_date' in child_record:
                    # Add small random offset to avoid exact duplicates
                    base_time = datetime.now() - timedelta(days=random.randint(0, 365))
                    offset = timedelta(hours=random.randint(0, 23), minutes=random.randint(0, 59))
                    child_record['transaction_date'] = (base_time + offset).isoformat()
            
            elif rule == 'salary_consistency':
                # Ensure salary is consistent with department/position
                if 'department' in parent_record and 'salary' in child_record:
                    dept_salary_ranges = {
                        'engineering': (80000, 150000),
                        'sales': (50000, 120000),
                        'marketing': (60000, 110000),
                        'hr': (55000, 100000),
                        'finance': (65000, 130000)
                    }
                    
                    dept = parent_record['department'].lower()
                    if dept in dept_salary_ranges:
                        min_salary, max_salary = dept_salary_ranges[dept]
                        child_record['salary'] = random.randint(min_salary, max_salary)
            
            elif rule == 'no_self_management':
                # Ensure employee doesn't manage themselves
                if 'employee_id' in parent_record and 'manager_id' in child_record:
                    if parent_record['employee_id'] == child_record['manager_id']:
                        # Find a different manager or set to null
                        child_record['manager_id'] = None
            
            elif rule == 'hierarchy_depth_limit':
                # Limit organizational hierarchy depth
                if 'level' in parent_record:
                    parent_level = parent_record.get('level', 0)
                    if parent_level >= 5:  # Max 5 levels
                        child_record['manager_id'] = None
                    else:
                        child_record['level'] = parent_level + 1
    
    def _flatten_data(self, data_by_entity: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Flatten grouped data back to single list."""
        all_records = []
        for entity_name, records in data_by_entity.items():
            # Add entity type to each record
            for record in records:
                record['_entity_type'] = entity_name
            all_records.extend(records)
        return all_records
    
    # Utility methods for relationship analysis
    def analyze_relationship_quality(self, data: List[Dict[str, Any]], 
                                   relationships: List[DataRelationship]) -> Dict[str, Any]:
        """Analyze the quality of generated relationships."""
        
        analysis = {
            'total_relationships': len(relationships),
            'referential_integrity_score': 0.0,
            'distribution_quality': {},
            'business_rule_compliance': 0.0
        }
        
        # Group data by entity type
        entity_groups = {}
        for record in data:
            entity_type = record.get('_entity_type', 'unknown')
            if entity_type not in entity_groups:
                entity_groups[entity_type] = []
            entity_groups[entity_type].append(record)
        
        # Check referential integrity
        integrity_violations = 0
        total_references = 0
        
        for relationship in relationships:
            from_entity = relationship.from_table
            to_entity = relationship.to_table
            
            if from_entity in entity_groups and to_entity in entity_groups:
                from_records = entity_groups[from_entity]
                to_records = entity_groups[to_entity]
                
                # Get all referenced keys
                to_keys = set(r.get(relationship.to_column) for r in to_records if r.get(relationship.to_column))
                
                # Check if all foreign keys exist
                for from_record in from_records:
                    foreign_key = from_record.get(relationship.from_column)
                    if foreign_key is not None:
                        total_references += 1
                        if foreign_key not in to_keys:
                            integrity_violations += 1
        
        if total_references > 0:
            analysis['referential_integrity_score'] = 1.0 - (integrity_violations / total_references)
        else:
            analysis['referential_integrity_score'] = 1.0
        
        return analysis
    
    def suggest_relationship_optimizations(self, data: List[Dict[str, Any]], 
                                         relationships: List[DataRelationship]) -> List[Dict[str, Any]]:
        """Suggest optimizations for relationship generation."""
        
        suggestions = []
        
        # Analyze current relationship patterns
        analysis = self.analyze_relationship_quality(data, relationships)
        
        if analysis['referential_integrity_score'] < 0.95:
            suggestions.append({
                'type': 'integrity_improvement',
                'description': 'Referential integrity can be improved',
                'action': 'Review foreign key generation logic',
                'priority': 'high'
            })
        
        # Check for unbalanced relationships
        entity_counts = {}
        for record in data:
            entity_type = record.get('_entity_type', 'unknown')
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
        
        for relationship in relationships:
            from_count = entity_counts.get(relationship.from_table, 0)
            to_count = entity_counts.get(relationship.to_table, 0)
            
            if relationship.relationship_type == 'one_to_many':
                ratio = to_count / from_count if from_count > 0 else 0
                if ratio < 1.0:
                    suggestions.append({
                        'type': 'cardinality_adjustment',
                        'description': f'Low child/parent ratio for {relationship.from_table}->{relationship.to_table}',
                        'action': 'Consider increasing child record generation',
                        'priority': 'medium'
                    })
        
        return suggestions