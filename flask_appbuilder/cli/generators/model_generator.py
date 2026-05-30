"""
Enhanced Model Generator for Flask-AppBuilder

Generates beautiful, modern SQLAlchemy models with advanced features including:
- Modern Python typing and type hints
- Enhanced validation and constraints
- Sophisticated relationship handling
- Performance optimizations
- Documentation generation
- Pydantic integration for API serialization
- Hybrid properties and computed fields
- Event listeners and hooks
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass
from jinja2 import Environment, FileSystemLoader, Template
import os
import inflect

from .database_inspector import (
    EnhancedDatabaseInspector,
    TableInfo,
    ColumnInfo,
    RelationshipInfo,
    RelationshipType,
    ColumnType
)

logger = logging.getLogger(__name__)
p = inflect.engine()


@dataclass
class ModelGenerationConfig:
    """Configuration for model generation."""
    use_type_hints: bool = True
    generate_pydantic: bool = True
    generate_validation: bool = True
    generate_hybrid_properties: bool = True
    generate_event_listeners: bool = True
    generate_indexes: bool = True
    generate_repr: bool = True
    generate_str: bool = True
    generate_json_methods: bool = True
    use_dataclasses: bool = False
    include_documentation: bool = True
    performance_optimizations: bool = True
    security_features: bool = True
    include_timestamps: bool = True
    custom_base_class: Optional[str] = None


class EnhancedModelGenerator:
    """
    Enhanced model generator that creates beautiful, modern SQLAlchemy models.

    Features:
    - Modern Python type hints and typing
    - Enhanced validation with custom validators
    - Sophisticated relationship handling
    - Performance optimizations (lazy loading, indexing hints)
    - Pydantic model generation for API serialization
    - Hybrid properties for computed fields
    - Event listeners for business logic
    - Comprehensive documentation
    - Security features (field-level access control)
    """

    def __init__(
        self,
        inspector: EnhancedDatabaseInspector,
        config: Optional[ModelGenerationConfig] = None
    ):
        """
        Initialize the model generator.

        Args:
            inspector: Enhanced database inspector instance
            config: Generation configuration
        """
        self.inspector = inspector
        self.config = config or ModelGenerationConfig()
        
        # Set up Jinja2 environment with template directory
        template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True
        )

        # Analysis cache
        self.database_analysis = None
        self.generated_models: Dict[str, str] = {}
        self.import_statements: Set[str] = set()
        self.pydantic_models: Dict[str, str] = {}

        logger.info("Enhanced model generator initialized")

    def generate_all_models(self) -> Dict[str, str]:
        """
        Generate all models from the database.

        Returns:
            Dictionary mapping model names to generated code
        """
        logger.info("Starting enhanced model generation...")

        # Analyze database
        self.database_analysis = self.inspector.analyze_database()

        # Generate imports
        self._generate_imports()

        # Generate each model
        for table_name, table_info in self.database_analysis['tables'].items():
            model_code = self.generate_model(table_info)
            self.generated_models[table_name] = model_code

            # Generate Pydantic model if enabled
            if self.config.generate_pydantic:
                pydantic_code = self.generate_pydantic_model(table_info)
                self.pydantic_models[table_name] = pydantic_code

        # Generate complete file
        complete_models = self._generate_complete_file()

        logger.info(f"Generated {len(self.generated_models)} models successfully")
        return {
            'models.py': complete_models,
            'schemas.py': self._generate_pydantic_file() if self.config.generate_pydantic else '',
            'validators.py': self._generate_validators_file() if self.config.generate_validation else ''
        }

    def generate_model(self, table_info: TableInfo) -> str:
        """
        Generate a single SQLAlchemy model.

        Args:
            table_info: Table information from database analysis

        Returns:
            Generated model code
        """
        template = self.jinja_env.get_template('model.j2')

        # Prepare template context
        context = {
            'table_info': table_info,
            'config': self.config,
            'columns': self._process_columns(table_info.columns),
            'relationships': self._process_relationships(table_info.relationships),
            'constraints': self._process_constraints(table_info.constraints),
            'indexes': self._process_indexes(table_info.indexes),
            'hybrid_properties': self._generate_hybrid_properties(table_info),
            'event_listeners': self._generate_event_listeners(table_info),
            'validation_methods': self._generate_validation_methods(table_info),
            'utility_methods': self._generate_utility_methods(table_info),
            'class_name': self._to_pascal_case(table_info.name),
            'base_class': self.config.custom_base_class or 'Model',
            'timestamp': datetime.now().isoformat(),
            'security_settings': self._generate_security_settings(table_info)
        }

        return template.render(**context)

    def generate_pydantic_model(self, table_info: TableInfo) -> str:
        """Generate Pydantic model for API serialization."""
        template = self.jinja_env.get_template('pydantic_schema.j2')

        cols = []
        for col in table_info.columns:
            if col.primary_key:
                continue
            python_type = self._get_python_type(col) or 'str'
            # Strip Optional[...] wrapper to get inner type
            inner = python_type.replace('Optional[', '').rstrip(']') if python_type.startswith('Optional[') else python_type
            nullable = col.nullable or python_type.startswith('Optional[')
            field_type = f'Optional[{inner}]' if nullable else inner
            comment = f' = Field(description="{col.comment}")' if col.comment else ''
            example = '"example_value"' if 'str' in inner else ('123' if 'int' in inner else ('True' if 'bool' in inner else 'None'))
            cols.append({
                'name': col.name,
                'definition': f'    {col.name}: {field_type}{comment}',
                'example': example,
                'nullable': nullable,
                'python_type': inner,
                'comment': col.comment,
            })

        context = {
            'table_info': table_info,
            'class_name': f"{self._to_pascal_case(table_info.name)}Schema",
            'columns': cols,
            'relationships': table_info.relationships,
        }
        return template.render(**context)

    def _process_columns(self, columns: List[ColumnInfo]) -> List[Dict[str, Any]]:
        """Process columns for template rendering."""
        processed = []

        for column in columns:
            sql_type = self._get_sqlalchemy_type(column)
            constraints = self._get_column_constraints(column)
            python_type = self._get_python_type(column)

            # Pre-compute the full definition string so the template avoids
            # inline {% if %} tags that cause trim_blocks to eat newlines.
            type_hint = f": {python_type}" if self.config.use_type_hints and python_type else ""
            constraint_part = f", {', '.join(constraints)}" if constraints else ""
            comment_part = f"  # {column.comment}" if column.comment else ""
            definition = (
                f"    {column.name}{type_hint} = Column({sql_type}{constraint_part}){comment_part}"
            )

            col_dict = {
                'name': column.name,
                'type': sql_type,
                'constraints': constraints,
                'comment': column.comment,
                'python_type': python_type,
                'definition': definition,
                'validation': column.validation_rules,
                'widget_type': column.widget_type,
                'display_name': column.display_name,
                'description': column.description,
                'is_sensitive': self._is_sensitive_field(column.name)
            }
            processed.append(col_dict)

        return processed

    def _process_relationships(self, relationships: List[RelationshipInfo]) -> List[Dict[str, Any]]:
        """Process relationships for template rendering."""
        processed = []

        for rel in relationships:
            rel_dict = {
                'name': rel.name,
                'type': rel.type.value,
                'remote_table': rel.remote_table,
                'remote_class': self._to_pascal_case(rel.remote_table),
                'local_columns': rel.local_columns,
                'remote_columns': rel.remote_columns,
                'association_table': rel.association_table,
                'back_populates': rel.back_populates,
                'cascade': ', '.join(f"'{c}'" for c in rel.cascade_options),
                'lazy': rel.lazy_loading,
                'display_name': rel.display_name,
                'description': rel.description,
                'ui_hint': rel.ui_hint
            }
            processed.append(rel_dict)

        return processed

    def _process_constraints(self, constraints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process constraints for template rendering."""
        processed = []
        for constraint in constraints:
            if constraint['type'] not in ['primary_key', 'foreign_key']:  # These are handled elsewhere
                processed.append(constraint)
        return processed

    def _process_indexes(self, indexes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process indexes for template rendering."""
        return [idx for idx in indexes if self.config.generate_indexes]

    def _generate_hybrid_properties(self, table_info: TableInfo) -> List[Dict[str, str]]:
        """Generate hybrid properties based on table structure."""
        if not self.config.generate_hybrid_properties:
            return []

        properties = []

        # Generate full_name property if we have first_name and last_name
        column_names = [col.name for col in table_info.columns]
        if 'first_name' in column_names and 'last_name' in column_names:
            properties.append({
                'name': 'full_name',
                'expression': "func.concat(self.first_name, ' ', self.last_name)",
                'setter': '''
    @full_name.setter
    def full_name(self, value):
        if value:
            parts = value.split(' ', 1)
            self.first_name = parts[0]
            self.last_name = parts[1] if len(parts) > 1 else ''
                '''.strip()
            })

        # Generate display_name for common patterns
        if 'name' in column_names:
            properties.append({
                'name': 'display_name',
                'expression': 'self.name or f"#{self.id}"',
                'setter': None
            })

        return properties

    def _generate_event_listeners(self, table_info: TableInfo) -> List[Dict[str, str]]:
        """Generate event listeners for business logic."""
        if not self.config.generate_event_listeners:
            return []

        listeners = []

        # Add timestamp listeners if timestamps are enabled
        if self.config.include_timestamps:
            column_names = [col.name for col in table_info.columns]
            if 'created_at' in column_names or 'updated_at' in column_names:
                listeners.append({
                    'event': 'before_insert',
                    'code': '''
@event.listens_for({class_name}, 'before_insert')
def before_insert_{table_name}(mapper, connection, target):
    """Set creation timestamp."""
    target.created_at = datetime.utcnow()
    target.updated_at = datetime.utcnow()
                    '''.strip()
                })

                listeners.append({
                    'event': 'before_update',
                    'code': '''
@event.listens_for({class_name}, 'before_update')
def before_update_{table_name}(mapper, connection, target):
    """Update modification timestamp."""
    target.updated_at = datetime.utcnow()
                    '''.strip()
                })

        return listeners

    def _generate_validation_methods(self, table_info: TableInfo) -> List[Dict[str, str]]:
        """Generate validation methods."""
        if not self.config.generate_validation:
            return []

        validations = []

        # Email validation
        email_columns = [col for col in table_info.columns if 'email' in col.name.lower()]
        for col in email_columns:
            validations.append({
                'column': col.name,
                'method': f'validate_{col.name}',
                'code': f'''
    @validates('{col.name}')
    def validate_{col.name}(self, key, value):
        """Validate email format."""
        if value and '@' not in value:
            raise ValueError('Invalid email format')
        return value
                '''.strip()
            })

        return validations

    def _generate_utility_methods(self, table_info: TableInfo) -> List[Dict[str, str]]:
        """Generate utility methods."""
        methods = []

        if self.config.generate_json_methods:
            methods.append({
                'name': 'to_dict',
                'code': '''
    def to_dict(self, include_relationships=False):
        """Convert model to dictionary."""
        result = {}
        for column in self.__table__.columns:
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[column.name] = value

        if include_relationships:
            for rel in self.__mapper__.relationships:
                rel_value = getattr(self, rel.key)
                if rel_value is not None:
                    if hasattr(rel_value, 'to_dict'):
                        result[rel.key] = rel_value.to_dict()
                    elif hasattr(rel_value, '__iter__'):
                        result[rel.key] = [item.to_dict() if hasattr(item, 'to_dict') else str(item) for item in rel_value]
                    else:
                        result[rel.key] = str(rel_value)

        return result
                '''.strip()
            })

            methods.append({
                'name': 'from_dict',
                'code': '''
    @classmethod
    def from_dict(cls, data):
        """Create model instance from dictionary."""
        instance = cls()
        for key, value in data.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        return instance
                '''.strip()
            })

        return methods

    def _generate_security_settings(self, table_info: TableInfo) -> Dict[str, Any]:
        """Generate security settings for the model."""
        if not self.config.security_features:
            return {}

        sensitive_fields = [col.name for col in table_info.columns
                          if self._is_sensitive_field(col.name)]

        return {
            'security_level': table_info.security_level,
            'sensitive_fields': sensitive_fields,
            'audit_enabled': table_info.security_level in ['HIGH', 'MEDIUM']
        }

    def _get_sqlalchemy_type(self, column: ColumnInfo) -> str:
        """Get SQLAlchemy type string with PostgreSQL dialect support."""
        
        # PostgreSQL-specific types that use dialect imports
        postgresql_types = {
            'UUID': 'UUID',
            'JSONB': 'JSONB', 
            'HSTORE': 'HSTORE',
            'INET': 'INET',
            'CIDR': 'CIDR',
            'MACADDR': 'MACADDR',
            'TSVECTOR': 'TSVECTOR',
            'TSQUERY': 'TSQUERY',
            'INT4RANGE': 'INT4RANGE',
            'INT8RANGE': 'INT8RANGE',
            'NUMRANGE': 'NUMRANGE',
            'TSRANGE': 'TSRANGE',
            'TSTZRANGE': 'TSTZRANGE',
            'DATERANGE': 'DATERANGE'
        }
        
        # PostGIS spatial types
        spatial_types = {
            'GEOMETRY': 'Geometry',
            'GEOGRAPHY': 'Geography',
            'RASTER': 'Raster'
        }
        
        # pgVector types
        vector_types = {
            'VECTOR': 'Vector'
        }
        
        # Standard SQLAlchemy types
        standard_types = {
            'VARCHAR': f'String({column.length})' if column.length else 'String(255)',
            'TEXT': 'Text',
            'INTEGER': 'Integer',
            'BIGINT': 'BigInteger',
            'SMALLINT': 'SmallInteger',
            'DECIMAL': f'Numeric({column.precision}, {column.scale})' if column.precision else 'Numeric',
            'FLOAT': 'Float',
            'DOUBLE': 'Float(precision=53)',
            'BOOLEAN': 'Boolean',
            'DATE': 'Date',
            'DATETIME': 'DateTime',
            'TIMESTAMP': 'DateTime(timezone=True)',
            'TIME': 'Time',
            'JSON': 'JSON',
            'ARRAY': 'ARRAY',
            'BINARY': 'LargeBinary',
            'BYTEA': 'LargeBinary'
        }

        base_type = column.type.upper()
        
        # Handle parameterized types
        if base_type.startswith('VARCHAR'):
            import re
            match = re.search(r'VARCHAR\((\d+)\)', base_type)
            length = match.group(1) if match else '255'
            return f'String({length})'
        elif base_type.startswith('GEOMETRY'):
            # Handle PostGIS GEOMETRY(type, srid) format
            import re
            match = re.search(r'GEOMETRY\(([^,]+),?\s*(\d+)?\)', base_type)
            if match:
                geom_type = match.group(1).strip()
                srid = match.group(2)
                if srid:
                    return f'Geometry(geometry_type="{geom_type}", srid={srid})'
                else:
                    return f'Geometry(geometry_type="{geom_type}")'
            return 'Geometry'
        elif base_type.startswith('VECTOR'):
            # Handle pgVector VECTOR(dimensions) format
            import re
            match = re.search(r'VECTOR\((\d+)\)', base_type)
            if match:
                dimensions = match.group(1)
                return f'Vector({dimensions})'
            return 'Vector'
        
        # Check type categories in priority order
        clean_type = base_type.split('(')[0]  # Remove parameters for lookup
        
        if clean_type in postgresql_types:
            return postgresql_types[clean_type]
        elif clean_type in spatial_types:
            return spatial_types[clean_type]
        elif clean_type in vector_types:
            return vector_types[clean_type]
        elif clean_type in standard_types:
            return standard_types[clean_type]
        else:
            return 'String(255)'  # Safe default

    def _get_python_type(self, column: ColumnInfo) -> str:
        """Get Python type hint for a column."""
        if not self.config.use_type_hints:
            return ''

        type_mapping = {
            ColumnType.PRIMARY_KEY: 'int',
            ColumnType.FOREIGN_KEY: 'int',
            ColumnType.TEXT: 'str',
            ColumnType.NUMERIC: 'int' if 'INT' in column.type.upper() else 'float',
            ColumnType.BOOLEAN: 'bool',
            ColumnType.DATE_TIME: 'datetime',
            ColumnType.JSON: 'dict',
            ColumnType.JSONB: 'dict',
            ColumnType.ARRAY: 'list',
            ColumnType.BINARY: 'bytes',
            ColumnType.UUID: 'str',
            ColumnType.ENUM: 'str',
        }

        python_type = type_mapping.get(column.category, 'str')
        return f'Optional[{python_type}]' if column.nullable else python_type

    def _get_column_constraints(self, column: ColumnInfo) -> List[str]:
        """Get column constraints."""
        constraints = []

        if column.primary_key:
            constraints.append('primary_key=True')

        if column.foreign_key:
            # Foreign key constraint will be handled separately
            pass

        if not column.nullable:
            constraints.append('nullable=False')

        if column.unique:
            constraints.append('unique=True')

        if column.default is not None:
            default_val = self._format_default_value(column.default)
            if default_val:
                constraints.append(f'default={default_val}')

        if column.comment:
            constraints.append(f'comment="{column.comment}"')

        return constraints

    def _format_default_value(self, default_value: Any) -> str:
        """Format default value for SQLAlchemy."""
        if default_value is None:
            return 'None'
        elif isinstance(default_value, str):
            if 'now()' in default_value.lower():
                return 'func.now()'
            elif default_value.lower() in ('true', 'false'):
                return default_value.title()
            else:
                return f"'{default_value}'"
        elif isinstance(default_value, bool):
            return str(default_value)
        else:
            return str(default_value)

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Check if a field contains sensitive data."""
        sensitive_patterns = [
            'password', 'pwd', 'secret', 'token', 'key', 'ssn',
            'social_security', 'credit_card', 'bank_account',
            'salary', 'wage', 'income', 'tax_id'
        ]
        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in sensitive_patterns)

    def _to_pascal_case(self, snake_str: str) -> str:
        """Convert snake_case to PascalCase."""
        return ''.join(word.capitalize() for word in snake_str.split('_'))

    def _generate_imports(self):
        """Build import set from code_headers.gen_model_header() — comprehensive PostgreSQL coverage."""
        from flask_appbuilder.cli.generators.code_headers import gen_model_header
        for block in gen_model_header():
            self.import_statements.add(block.strip())

        # Add Pydantic if requested
        if self.config.generate_pydantic:
            self.import_statements.add('from pydantic import BaseModel, Field, validator')
        if self.config.use_dataclasses:
            self.import_statements.add('from dataclasses import dataclass')

    def _has_postgresql_types(self) -> bool:
        """Check if any PostgreSQL-specific types are used."""
        if not self.database_analysis:
            return False
            
        postgresql_types = {
            ColumnType.UUID, ColumnType.JSONB, ColumnType.HSTORE, ColumnType.LTREE,
            ColumnType.INET, ColumnType.CIDR, ColumnType.MACADDR, ColumnType.TSVECTOR,
            ColumnType.TSQUERY, ColumnType.INT4RANGE, ColumnType.INT8RANGE,
            ColumnType.NUMRANGE, ColumnType.TSRANGE, ColumnType.TSTZRANGE, ColumnType.DATERANGE
        }
        
        for table_info in self.database_analysis['tables'].values():
            for column in table_info.columns:
                if column.category in postgresql_types:
                    return True
        return False

    def _has_spatial_types(self) -> bool:
        """Check if any PostGIS spatial types are used."""
        if not self.database_analysis:
            return False
            
        spatial_types = {ColumnType.GEOMETRY, ColumnType.GEOGRAPHY, ColumnType.RASTER}
        
        for table_info in self.database_analysis['tables'].values():
            for column in table_info.columns:
                if column.category in spatial_types:
                    return True
        return False

    def _has_vector_types(self) -> bool:
        """Check if any pgVector types are used."""
        if not self.database_analysis:
            return False
            
        for table_info in self.database_analysis['tables'].values():
            for column in table_info.columns:
                if column.category == ColumnType.VECTOR:
                    return True
        return False



    def _generate_complete_file(self) -> str:
        """Generate complete models file."""
        template = self.jinja_env.get_template('models_file.j2')

        return template.render(
            imports=sorted(self.import_statements),
            models=self.generated_models,
            config=self.config,
            database_info=self.database_analysis['database_info'],
            statistics=self.database_analysis['statistics'],
            timestamp=datetime.now().isoformat()
        )

    def _generate_pydantic_file(self) -> str:
        """Generate Pydantic schemas file."""
        template = self.jinja_env.get_template('pydantic_file.j2')

        return template.render(
            schemas=self.pydantic_models,
            timestamp=datetime.now().isoformat()
        )

    def _generate_validators_file(self) -> str:
        """Generate custom validators file."""
        template = self.jinja_env.get_template('validators.j2')

        return template.render(
            timestamp=datetime.now().isoformat()
        )

