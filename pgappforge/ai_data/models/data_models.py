"""
Data Models for AI-Powered Data Generation

Defines the data structures used for AI data generation requests,
configurations, and results.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union, Callable
from datetime import datetime
from enum import Enum
import json


class FieldType(Enum):
    """Supported field types for data generation."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    EMAIL = "email"
    URL = "url"
    PHONE = "phone"
    UUID = "uuid"
    JSON = "json"
    TEXT = "text"  # Long text content
    DECIMAL = "decimal"
    TIME = "time"


class RelationshipType(Enum):
    """Types of relationships between data fields."""
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    FOREIGN_KEY = "foreign_key"
    REFERENCE = "reference"
    DEPENDENCY = "dependency"


class DataDistribution(Enum):
    """Data distribution patterns for realistic generation."""
    UNIFORM = "uniform"
    NORMAL = "normal"
    EXPONENTIAL = "exponential"
    PARETO = "pareto"  # 80/20 rule
    ZIPFIAN = "zipfian"  # Long tail distribution
    CUSTOM = "custom"


@dataclass
class DataConstraints:
    """Constraints and validation rules for data fields."""
    # Basic constraints
    required: bool = False
    unique: bool = False
    nullable: bool = True
    
    # String constraints
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None  # Regex pattern
    format: Optional[str] = None  # Format specification
    
    # Numeric constraints
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    precision: Optional[int] = None  # Decimal places
    
    # Date constraints
    min_date: Optional[datetime] = None
    max_date: Optional[datetime] = None
    
    # List constraints
    allowed_values: Optional[List[Any]] = None
    forbidden_values: Optional[List[Any]] = None
    
    # Custom validation
    custom_validator: Optional[Callable[[Any], bool]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {}
        for key, value in self.__dict__.items():
            if value is not None and key != 'custom_validator':
                if isinstance(value, datetime):
                    result[key] = value.isoformat()
                else:
                    result[key] = value
        return result


@dataclass
class DataField:
    """Definition of a data field for generation."""
    name: str
    field_type: FieldType
    description: Optional[str] = None
    
    # Generation parameters
    constraints: Optional[DataConstraints] = None
    distribution: DataDistribution = DataDistribution.UNIFORM
    
    # Business context
    business_meaning: Optional[str] = None  # e.g., "customer_name", "product_price"
    domain_context: Optional[Dict[str, Any]] = None
    
    # Generation hints
    sample_values: Optional[List[Any]] = None
    generation_strategy: Optional[str] = None  # Custom strategy
    locale_specific: bool = False
    
    # Relationships
    references: Optional[str] = None  # Field this references
    referenced_by: Optional[List[str]] = None  # Fields that reference this
    
    # Validation rules
    validation_rules: Optional[List[Dict[str, Any]]] = None
    
    def __post_init__(self):
        if self.constraints is None:
            self.constraints = DataConstraints()
        if self.referenced_by is None:
            self.referenced_by = []
        if self.validation_rules is None:
            self.validation_rules = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'field_type': self.field_type.value,
            'description': self.description,
            'constraints': self.constraints.to_dict() if self.constraints else {},
            'distribution': self.distribution.value,
            'business_meaning': self.business_meaning,
            'domain_context': self.domain_context,
            'sample_values': self.sample_values,
            'generation_strategy': self.generation_strategy,
            'locale_specific': self.locale_specific,
            'references': self.references,
            'referenced_by': self.referenced_by,
            'validation_rules': self.validation_rules
        }


@dataclass
class DataRelationship:
    """Defines relationships between data fields or entities."""
    name: str
    relationship_type: RelationshipType
    source_field: str
    target_field: str
    
    # Relationship properties
    strength: float = 1.0  # 0.0 to 1.0, how strongly correlated
    nullable: bool = False
    cascade_delete: bool = False
    
    # Generation parameters
    distribution: DataDistribution = DataDistribution.UNIFORM
    cardinality_min: int = 1
    cardinality_max: int = 1
    
    # Business rules
    business_rules: Optional[List[Dict[str, Any]]] = None
    constraints: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.business_rules is None:
            self.business_rules = []
        if self.constraints is None:
            self.constraints = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'relationship_type': self.relationship_type.value,
            'source_field': self.source_field,
            'target_field': self.target_field,
            'strength': self.strength,
            'nullable': self.nullable,
            'cascade_delete': self.cascade_delete,
            'distribution': self.distribution.value,
            'cardinality_min': self.cardinality_min,
            'cardinality_max': self.cardinality_max,
            'business_rules': self.business_rules,
            'constraints': self.constraints
        }


@dataclass
class DataGenerationRequest:
    """Request for AI-powered data generation."""
    name: str
    fields: List[DataField]
    record_count: int
    
    # Optional parameters
    description: Optional[str] = None
    domain: Optional[str] = None  # Business domain hint
    locale: Optional[str] = None
    
    # Relationships and constraints
    relationships: Optional[List[DataRelationship]] = None
    validation_rules: Optional[List[Dict[str, Any]]] = None
    
    # Generation preferences
    realism_level: float = 0.8  # 0.0 to 1.0
    consistency_level: float = 0.9  # 0.0 to 1.0
    diversity_level: float = 0.7  # 0.0 to 1.0
    
    # Advanced options
    seed: Optional[int] = None  # For reproducible generation
    template_data: Optional[List[Dict[str, Any]]] = None  # Sample data to learn from
    business_rules: Optional[List[Dict[str, Any]]] = None
    
    # Output options
    output_format: str = "json"  # json, csv, sql, etc.
    include_metadata: bool = True
    
    def __post_init__(self):
        if self.relationships is None:
            self.relationships = []
        if self.validation_rules is None:
            self.validation_rules = []
        if self.business_rules is None:
            self.business_rules = []
    
    def add_field(self, field: DataField):
        """Add a field to the request."""
        self.fields.append(field)
    
    def add_relationship(self, relationship: DataRelationship):
        """Add a relationship to the request."""
        self.relationships.append(relationship)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'fields': [field.to_dict() for field in self.fields],
            'record_count': self.record_count,
            'description': self.description,
            'domain': self.domain,
            'locale': self.locale,
            'relationships': [rel.to_dict() for rel in self.relationships],
            'validation_rules': self.validation_rules,
            'realism_level': self.realism_level,
            'consistency_level': self.consistency_level,
            'diversity_level': self.diversity_level,
            'seed': self.seed,
            'template_data': self.template_data,
            'business_rules': self.business_rules,
            'output_format': self.output_format,
            'include_metadata': self.include_metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DataGenerationRequest':
        """Create from dictionary representation."""
        fields = []
        for field_data in data.get('fields', []):
            constraints = None
            if field_data.get('constraints'):
                constraints = DataConstraints(**field_data['constraints'])
            
            field = DataField(
                name=field_data['name'],
                field_type=FieldType(field_data['field_type']),
                description=field_data.get('description'),
                constraints=constraints,
                distribution=DataDistribution(field_data.get('distribution', 'uniform')),
                business_meaning=field_data.get('business_meaning'),
                domain_context=field_data.get('domain_context'),
                sample_values=field_data.get('sample_values'),
                generation_strategy=field_data.get('generation_strategy'),
                locale_specific=field_data.get('locale_specific', False),
                references=field_data.get('references'),
                referenced_by=field_data.get('referenced_by', []),
                validation_rules=field_data.get('validation_rules', [])
            )
            fields.append(field)
        
        relationships = []
        for rel_data in data.get('relationships', []):
            relationship = DataRelationship(
                name=rel_data['name'],
                relationship_type=RelationshipType(rel_data['relationship_type']),
                source_field=rel_data['source_field'],
                target_field=rel_data['target_field'],
                strength=rel_data.get('strength', 1.0),
                nullable=rel_data.get('nullable', False),
                cascade_delete=rel_data.get('cascade_delete', False),
                distribution=DataDistribution(rel_data.get('distribution', 'uniform')),
                cardinality_min=rel_data.get('cardinality_min', 1),
                cardinality_max=rel_data.get('cardinality_max', 1),
                business_rules=rel_data.get('business_rules', []),
                constraints=rel_data.get('constraints', {})
            )
            relationships.append(relationship)
        
        return cls(
            name=data['name'],
            fields=fields,
            record_count=data['record_count'],
            description=data.get('description'),
            domain=data.get('domain'),
            locale=data.get('locale'),
            relationships=relationships,
            validation_rules=data.get('validation_rules', []),
            realism_level=data.get('realism_level', 0.8),
            consistency_level=data.get('consistency_level', 0.9),
            diversity_level=data.get('diversity_level', 0.7),
            seed=data.get('seed'),
            template_data=data.get('template_data'),
            business_rules=data.get('business_rules', []),
            output_format=data.get('output_format', 'json'),
            include_metadata=data.get('include_metadata', True)
        )


@dataclass
class GeneratedDataset:
    """Result of AI-powered data generation."""
    name: str
    domain: str
    records: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    created_at: datetime
    
    # Optional additional information
    quality_metrics: Optional[Dict[str, float]] = None
    generation_log: Optional[List[Dict[str, Any]]] = None
    schema: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.quality_metrics is None:
            self.quality_metrics = {}
        if self.generation_log is None:
            self.generation_log = []
        if self.schema is None:
            self.schema = self._infer_schema()
    
    def _infer_schema(self) -> Dict[str, Any]:
        """Infer schema from generated records."""
        if not self.records:
            return {}
        
        schema = {}
        sample_record = self.records[0]
        
        for field_name, value in sample_record.items():
            field_type = type(value).__name__
            
            # Convert Python types to schema types
            if field_type == 'str':
                schema_type = 'string'
            elif field_type == 'int':
                schema_type = 'integer'
            elif field_type == 'float':
                schema_type = 'float'
            elif field_type == 'bool':
                schema_type = 'boolean'
            elif field_type == 'datetime':
                schema_type = 'datetime'
            else:
                schema_type = 'unknown'
            
            schema[field_name] = {
                'type': schema_type,
                'nullable': any(record.get(field_name) is None for record in self.records),
                'unique': len(set(str(record.get(field_name)) for record in self.records)) == len(self.records)
            }
        
        return schema
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'domain': self.domain,
            'records': self.records,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat(),
            'quality_metrics': self.quality_metrics,
            'generation_log': self.generation_log,
            'schema': self.schema,
            'record_count': len(self.records)
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string representation."""
        data = self.to_dict()
        return json.dumps(data, indent=indent, default=str)
    
    def to_csv(self) -> str:
        """Convert records to CSV format."""
        import csv
        from io import StringIO
        
        if not self.records:
            return ""
        
        output = StringIO()
        fieldnames = list(self.records[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        
        writer.writeheader()
        for record in self.records:
            writer.writerow(record)
        
        return output.getvalue()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistical information about the dataset."""
        if not self.records:
            return {'record_count': 0}
        
        stats = {
            'record_count': len(self.records),
            'field_count': len(self.records[0]) if self.records else 0,
            'domain': self.domain,
            'created_at': self.created_at.isoformat(),
            'field_statistics': {}
        }
        
        # Field-level statistics
        for field_name in self.records[0].keys():
            values = [record.get(field_name) for record in self.records]
            non_null_values = [v for v in values if v is not None]
            
            field_stats = {
                'null_count': len(values) - len(non_null_values),
                'null_percentage': (len(values) - len(non_null_values)) / len(values) * 100,
                'unique_count': len(set(str(v) for v in non_null_values)),
                'unique_percentage': len(set(str(v) for v in non_null_values)) / len(non_null_values) * 100 if non_null_values else 0
            }
            
            # Type-specific statistics
            if non_null_values and isinstance(non_null_values[0], (int, float)):
                numeric_values = [v for v in non_null_values if isinstance(v, (int, float))]
                if numeric_values:
                    field_stats.update({
                        'min_value': min(numeric_values),
                        'max_value': max(numeric_values),
                        'mean_value': sum(numeric_values) / len(numeric_values),
                    })
            
            elif non_null_values and isinstance(non_null_values[0], str):
                str_values = [v for v in non_null_values if isinstance(v, str)]
                if str_values:
                    field_stats.update({
                        'min_length': min(len(v) for v in str_values),
                        'max_length': max(len(v) for v in str_values),
                        'avg_length': sum(len(v) for v in str_values) / len(str_values),
                    })
            
            stats['field_statistics'][field_name] = field_stats
        
        return stats


@dataclass
class DataGenerationTemplate:
    """Template for common data generation patterns."""
    name: str
    description: str
    domain: str
    fields: List[DataField]
    relationships: List[DataRelationship]
    business_rules: List[Dict[str, Any]]
    
    # Template metadata
    version: str = "1.0"
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    def to_request(self, record_count: int = 100, **overrides) -> DataGenerationRequest:
        """Convert template to a data generation request."""
        request = DataGenerationRequest(
            name=overrides.get('name', self.name),
            fields=self.fields.copy(),
            record_count=record_count,
            domain=self.domain,
            relationships=self.relationships.copy(),
            business_rules=self.business_rules.copy()
        )
        
        # Apply any overrides
        for key, value in overrides.items():
            if hasattr(request, key):
                setattr(request, key, value)
        
        return request
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'description': self.description,
            'domain': self.domain,
            'fields': [field.to_dict() for field in self.fields],
            'relationships': [rel.to_dict() for rel in self.relationships],
            'business_rules': self.business_rules,
            'version': self.version,
            'author': self.author,
            'tags': self.tags
        }


# Helper functions
def create_simple_field(name: str, field_type: str, **kwargs) -> DataField:
    """Create a simple data field with common defaults."""
    return DataField(
        name=name,
        field_type=FieldType(field_type),
        **kwargs
    )


def create_foreign_key_relationship(name: str, source_field: str, target_field: str, **kwargs) -> DataRelationship:
    """Create a foreign key relationship."""
    return DataRelationship(
        name=name,
        relationship_type=RelationshipType.FOREIGN_KEY,
        source_field=source_field,
        target_field=target_field,
        **kwargs
    )


def create_basic_request(name: str, fields: List[Dict[str, Any]], record_count: int = 100) -> DataGenerationRequest:
    """Create a basic data generation request from field specifications."""
    data_fields = []
    
    for field_spec in fields:
        field = DataField(
            name=field_spec['name'],
            field_type=FieldType(field_spec['type']),
            description=field_spec.get('description'),
            business_meaning=field_spec.get('meaning')
        )
        
        # Add constraints if specified
        if 'constraints' in field_spec:
            constraints = DataConstraints(**field_spec['constraints'])
            field.constraints = constraints
        
        data_fields.append(field)
    
    return DataGenerationRequest(
        name=name,
        fields=data_fields,
        record_count=record_count
    )