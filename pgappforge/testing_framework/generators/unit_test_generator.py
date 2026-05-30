"""
Unit Test Generator

Generates comprehensive unit tests for PgForge models, views, and components.
Includes CRUD operations, validation, relationships, and business logic testing.
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from .base_generator import BaseTestGenerator, TestCase

logger = logging.getLogger(__name__)


@dataclass
class ModelTestContext:
    """Context for model test generation."""
    model_name: str
    table_name: str
    columns: List[Any]
    relationships: List[Any]
    primary_key: str
    required_fields: List[str]
    optional_fields: List[str]
    foreign_keys: List[str]
    unique_fields: List[str]
    validation_rules: Dict[str, Any]


class UnitTestGenerator(BaseTestGenerator):
    """
    Unit test generator for PgForge applications.
    
    Generates comprehensive unit tests including:
    - Model CRUD operations
    - Model validation and constraints
    - Model relationships and cascading
    - View method testing
    - Form validation testing
    - Business logic testing
    - Error handling testing
    """
    
    def get_generator_type(self) -> str:
        """Return generator type."""
        return "unit"
    
    def generate_all_tests(self, schema) -> Dict[str, str]:
        """
        Generate all unit tests for the schema.
        
        Args:
            schema: Database schema information
            
        Returns:
            Dictionary mapping test file names to test code
        """
        logger.info("Generating unit tests for schema")
        
        test_files = {}
        
        # Get all tables from schema
        tables = getattr(schema, 'tables', [])
        if hasattr(schema, 'get_all_tables'):
            table_names = schema.get_all_tables()
            tables = [self.inspector.analyze_table(name) for name in table_names]
        
        for table_info in tables:
            # Generate model tests
            model_tests = self.generate_model_tests(table_info)
            test_files[f"test_{table_info.name}_model.py"] = model_tests
            
            # Generate view tests if views exist
            view_tests = self.generate_view_tests(table_info)
            if view_tests:
                test_files[f"test_{table_info.name}_views.py"] = view_tests
            
            # Generate form tests
            form_tests = self.generate_form_tests(table_info)
            if form_tests:
                test_files[f"test_{table_info.name}_forms.py"] = form_tests
        
        # Generate utility and helper tests
        utility_tests = self.generate_utility_tests(schema)
        if utility_tests:
            test_files["test_utilities.py"] = utility_tests
        
        logger.info(f"Generated {len(test_files)} unit test files")
        return test_files
    
    def generate_model_tests(self, table_info) -> str:
        """
        Generate comprehensive model tests for a table.
        
        Args:
            table_info: Table information from database analysis
            
        Returns:
            Generated model test code
        """
        context = self._build_model_test_context(table_info)
        
        # Generate individual test cases
        test_cases = []
        
        # CRUD operation tests
        test_cases.extend(self._generate_crud_tests(context))
        
        # Validation tests
        test_cases.extend(self._generate_validation_tests(context))
        
        # Relationship tests
        test_cases.extend(self._generate_relationship_tests(context))
        
        # Constraint tests
        test_cases.extend(self._generate_constraint_tests(context))
        
        # Edge case tests
        if self.config.include_edge_cases:
            test_cases.extend(self._generate_edge_case_tests(context))
        
        # Error scenario tests
        if self.config.include_error_scenarios:
            test_cases.extend(self._generate_error_scenario_tests(context))
        
        # Build complete test file
        return self._build_model_test_file(context, test_cases)
    
    def _build_model_test_context(self, table_info) -> ModelTestContext:
        """Build context for model test generation."""
        model_name = self._to_pascal_case(table_info.name)
        columns = getattr(table_info, 'columns', [])
        relationships = getattr(table_info, 'relationships', [])
        
        # Categorize fields
        required_fields = []
        optional_fields = []
        foreign_keys = []
        unique_fields = []
        primary_key = 'id'
        
        for column in columns:
            if column.primary_key:
                primary_key = column.name
            elif column.foreign_key:
                foreign_keys.append(column.name)
            elif getattr(column, 'nullable', True):
                optional_fields.append(column.name)
            else:
                required_fields.append(column.name)
            
            if getattr(column, 'unique', False):
                unique_fields.append(column.name)
        
        # Build validation rules
        validation_rules = self._extract_validation_rules(columns)
        
        return ModelTestContext(
            model_name=model_name,
            table_name=table_info.name,
            columns=columns,
            relationships=relationships,
            primary_key=primary_key,
            required_fields=required_fields,
            optional_fields=optional_fields,
            foreign_keys=foreign_keys,
            unique_fields=unique_fields,
            validation_rules=validation_rules
        )
    
    def _extract_validation_rules(self, columns) -> Dict[str, Any]:
        """Extract validation rules from column information."""
        rules = {}
        
        for column in columns:
            column_rules = {}
            
            # Length constraints
            if hasattr(column, 'type') and hasattr(column.type, 'length'):
                if column.type.length:
                    column_rules['max_length'] = column.type.length
            
            # Nullable constraint
            if hasattr(column, 'nullable'):
                column_rules['nullable'] = column.nullable
            
            # Unique constraint
            if hasattr(column, 'unique'):
                column_rules['unique'] = column.unique
            
            # Default value
            if hasattr(column, 'default') and column.default:
                column_rules['default'] = column.default
            
            if column_rules:
                rules[column.name] = column_rules
        
        return rules
    
    def _generate_crud_tests(self, context: ModelTestContext) -> List[TestCase]:
        """Generate CRUD operation test cases."""
        test_cases = []
        
        # Create test
        create_test = TestCase(
            name=f"create_{context.table_name}",
            description=f"Test creating new {context.model_name} instance",
            test_type="unit",
            method_name=f"test_create_{context.table_name}",
            test_code=f'''
    def test_create_{context.table_name}(self):
        """Test creating a new {context.model_name} instance."""
        # Arrange
        test_data = {{
            {self._generate_test_data_dict(context)}
        }}
        
        # Act
        instance = {context.model_name}(**test_data)
        db.session.add(instance)
        db.session.commit()
        
        # Assert
        assert instance.{context.primary_key} is not None
        {self._generate_field_assertions(context, 'instance')}
        
        # Verify in database
        saved_instance = {context.model_name}.query.get(instance.{context.primary_key})
        assert saved_instance is not None
        {self._generate_field_assertions(context, 'saved_instance')}''',
            tags=['crud', 'create']
        )
        test_cases.append(create_test)
        
        # Read test
        read_test = TestCase(
            name=f"read_{context.table_name}",
            description=f"Test reading {context.model_name} instance",
            test_type="unit",
            method_name=f"test_read_{context.table_name}",
            test_code=f'''
    def test_read_{context.table_name}(self):
        """Test reading a {context.model_name} instance."""
        # Arrange
        test_data = {{
            {self._generate_test_data_dict(context)}
        }}
        instance = {context.model_name}(**test_data)
        db.session.add(instance)
        db.session.commit()
        instance_id = instance.{context.primary_key}
        
        # Act
        retrieved_instance = {context.model_name}.query.get(instance_id)
        
        # Assert
        assert retrieved_instance is not None
        assert retrieved_instance.{context.primary_key} == instance_id
        {self._generate_field_assertions(context, 'retrieved_instance')}''',
            tags=['crud', 'read']
        )
        test_cases.append(read_test)
        
        # Update test
        update_test = TestCase(
            name=f"update_{context.table_name}",
            description=f"Test updating {context.model_name} instance",
            test_type="unit",
            method_name=f"test_update_{context.table_name}",
            test_code=f'''
    def test_update_{context.table_name}(self):
        """Test updating a {context.model_name} instance."""
        # Arrange
        original_data = {{
            {self._generate_test_data_dict(context)}
        }}
        instance = {context.model_name}(**original_data)
        db.session.add(instance)
        db.session.commit()
        instance_id = instance.{context.primary_key}
        
        # Act - Update some fields
        {self._generate_update_operations(context)}
        db.session.commit()
        
        # Assert
        updated_instance = {context.model_name}.query.get(instance_id)
        assert updated_instance is not None
        {self._generate_update_assertions(context)}''',
            tags=['crud', 'update']
        )
        test_cases.append(update_test)
        
        # Delete test
        delete_test = TestCase(
            name=f"delete_{context.table_name}",
            description=f"Test deleting {context.model_name} instance",
            test_type="unit",
            method_name=f"test_delete_{context.table_name}",
            test_code=f'''
    def test_delete_{context.table_name}(self):
        """Test deleting a {context.model_name} instance."""
        # Arrange
        test_data = {{
            {self._generate_test_data_dict(context)}
        }}
        instance = {context.model_name}(**test_data)
        db.session.add(instance)
        db.session.commit()
        instance_id = instance.{context.primary_key}
        
        # Verify instance exists
        assert {context.model_name}.query.get(instance_id) is not None
        
        # Act
        db.session.delete(instance)
        db.session.commit()
        
        # Assert
        deleted_instance = {context.model_name}.query.get(instance_id)
        assert deleted_instance is None''',
            tags=['crud', 'delete']
        )
        test_cases.append(delete_test)
        
        return test_cases
    
    def _generate_validation_tests(self, context: ModelTestContext) -> List[TestCase]:
        """Generate validation test cases."""
        test_cases = []
        
        # Required field validation tests
        for field in context.required_fields:
            validation_test = TestCase(
                name=f"validate_{field}_required",
                description=f"Test that {field} field is required",
                test_type="unit",
                method_name=f"test_{field}_required_validation",
                test_code=f'''
    def test_{field}_required_validation(self):
        """Test that {field} field is required."""
        # Arrange
        test_data = {{
            {self._generate_test_data_dict(context, exclude=[field])}
        }}
        
        # Act & Assert
        with pytest.raises((ValidationError, IntegrityError)):
            instance = {context.model_name}(**test_data)
            db.session.add(instance)
            db.session.commit()''',
                tags=['validation', 'required']
            )
            test_cases.append(validation_test)
        
        # Unique field validation tests
        for field in context.unique_fields:
            unique_test = TestCase(
                name=f"validate_{field}_unique",
                description=f"Test that {field} field is unique",
                test_type="unit",
                method_name=f"test_{field}_unique_validation",
                test_code=f'''
    def test_{field}_unique_validation(self):
        """Test that {field} field must be unique."""
        # Arrange
        test_data = {{
            {self._generate_test_data_dict(context)}
        }}
        
        # Create first instance
        instance1 = {context.model_name}(**test_data)
        db.session.add(instance1)
        db.session.commit()
        
        # Act & Assert - Try to create duplicate
        with pytest.raises((ValidationError, IntegrityError)):
            instance2 = {context.model_name}(**test_data)
            db.session.add(instance2)
            db.session.commit()''',
                tags=['validation', 'unique']
            )
            test_cases.append(unique_test)
        
        # Field-specific validation tests
        for field_name, rules in context.validation_rules.items():
            if 'max_length' in rules:
                length_test = TestCase(
                    name=f"validate_{field_name}_length",
                    description=f"Test {field_name} field length validation",
                    test_type="unit",
                    method_name=f"test_{field_name}_length_validation",
                    test_code=f'''
    def test_{field_name}_length_validation(self):
        """Test {field_name} field length validation."""
        # Arrange
        max_length = {rules['max_length']}
        long_value = 'x' * (max_length + 1)
        
        test_data = {{
            {self._generate_test_data_dict(context, overrides={field_name: 'long_value'})}
        }}
        
        # Act & Assert
        with pytest.raises((ValidationError, DataError)):
            instance = {context.model_name}(**test_data)
            db.session.add(instance)
            db.session.commit()''',
                    tags=['validation', 'length']
                )
                test_cases.append(length_test)
        
        return test_cases
    
    def _generate_relationship_tests(self, context: ModelTestContext) -> List[TestCase]:
        """Generate relationship test cases."""
        test_cases = []
        
        for relationship in context.relationships:
            # One-to-many relationship test
            if hasattr(relationship, 'type') and 'one_to_many' in str(relationship.type).lower():
                relationship_test = TestCase(
                    name=f"test_{relationship.name}_relationship",
                    description=f"Test {relationship.name} one-to-many relationship",
                    test_type="unit",
                    method_name=f"test_{relationship.name}_relationship",
                    test_code=f'''
    def test_{relationship.name}_relationship(self):
        """Test {relationship.name} one-to-many relationship."""
        # Arrange
        parent_data = {{
            {self._generate_test_data_dict(context)}
        }}
        parent = {context.model_name}(**parent_data)
        db.session.add(parent)
        db.session.commit()
        
        # Act - Add child records
        child1 = {self._to_pascal_case(relationship.remote_table)}(
            {relationship.local_columns[0]}=parent.{context.primary_key}
        )
        child2 = {self._to_pascal_case(relationship.remote_table)}(
            {relationship.local_columns[0]}=parent.{context.primary_key}
        )
        
        db.session.add(child1)
        db.session.add(child2)
        db.session.commit()
        
        # Assert
        assert len(parent.{relationship.name}) == 2
        assert child1 in parent.{relationship.name}
        assert child2 in parent.{relationship.name}''',
                    tags=['relationship', 'one_to_many']
                )
                test_cases.append(relationship_test)
            
            # Many-to-one relationship test
            elif hasattr(relationship, 'type') and 'many_to_one' in str(relationship.type).lower():
                relationship_test = TestCase(
                    name=f"test_{relationship.name}_relationship",
                    description=f"Test {relationship.name} many-to-one relationship",
                    test_type="unit",
                    method_name=f"test_{relationship.name}_relationship",
                    test_code=f'''
    def test_{relationship.name}_relationship(self):
        """Test {relationship.name} many-to-one relationship."""
        # Arrange - Create parent record
        parent = {self._to_pascal_case(relationship.remote_table)}()
        db.session.add(parent)
        db.session.commit()
        
        # Act - Create child with relationship
        child_data = {{
            {self._generate_test_data_dict(context)},
            '{relationship.local_columns[0]}': parent.{relationship.remote_columns[0]}
        }}
        child = {context.model_name}(**child_data)
        db.session.add(child)
        db.session.commit()
        
        # Assert
        assert child.{relationship.name} is not None
        assert child.{relationship.name}.{relationship.remote_columns[0]} == parent.{relationship.remote_columns[0]}''',
                    tags=['relationship', 'many_to_one']
                )
                test_cases.append(relationship_test)
        
        return test_cases
    
    def _generate_constraint_tests(self, context: ModelTestContext) -> List[TestCase]:
        """Generate constraint test cases."""
        test_cases = []
        
        # Foreign key constraint tests
        for fk_field in context.foreign_keys:
            fk_test = TestCase(
                name=f"test_{fk_field}_foreign_key_constraint",
                description=f"Test {fk_field} foreign key constraint",
                test_type="unit",
                method_name=f"test_{fk_field}_foreign_key_constraint",
                test_code=f'''
    def test_{fk_field}_foreign_key_constraint(self):
        """Test {fk_field} foreign key constraint."""
        # Arrange
        invalid_fk_id = 99999  # Non-existent ID
        test_data = {{
            {self._generate_test_data_dict(context, overrides={fk_field: 'invalid_fk_id'})}
        }}
        
        # Act & Assert
        with pytest.raises((ValidationError, IntegrityError, ForeignKeyViolation)):
            instance = {context.model_name}(**test_data)
            db.session.add(instance)
            db.session.commit()''',
                tags=['constraint', 'foreign_key']
            )
            test_cases.append(fk_test)
        
        return test_cases
    
    def _generate_edge_case_tests(self, context: ModelTestContext) -> List[TestCase]:
        """Generate edge case test cases."""
        test_cases = []
        
        # Boundary value tests
        boundary_test = TestCase(
            name=f"test_{context.table_name}_boundary_values",
            description=f"Test {context.model_name} with boundary values",
            test_type="unit",
            method_name=f"test_{context.table_name}_boundary_values",
            test_code=f'''
    def test_{context.table_name}_boundary_values(self):
        """Test {context.model_name} with boundary values."""
        # Test with minimum values
        min_data = {{
            {self._generate_boundary_test_data(context, 'min')}
        }}
        min_instance = {context.model_name}(**min_data)
        db.session.add(min_instance)
        
        # Test with maximum values
        max_data = {{
            {self._generate_boundary_test_data(context, 'max')}
        }}
        max_instance = {context.model_name}(**max_data)
        db.session.add(max_instance)
        
        # Commit and verify
        db.session.commit()
        assert min_instance.{context.primary_key} is not None
        assert max_instance.{context.primary_key} is not None''',
            tags=['edge_case', 'boundary']
        )
        test_cases.append(boundary_test)
        
        return test_cases
    
    def _generate_error_scenario_tests(self, context: ModelTestContext) -> List[TestCase]:
        """Generate error scenario test cases."""
        test_cases = []
        
        # Database connection error simulation
        db_error_test = TestCase(
            name=f"test_{context.table_name}_database_error_handling",
            description=f"Test {context.model_name} database error handling",
            test_type="unit",
            method_name=f"test_{context.table_name}_database_error_handling",
            test_code=f'''
    def test_{context.table_name}_database_error_handling(self):
        """Test {context.model_name} database error handling."""
        # Arrange
        test_data = {{
            {self._generate_test_data_dict(context)}
        }}
        
        # Simulate database error
        with patch('flask_sqlalchemy.SQLAlchemy.session') as mock_session:
            mock_session.commit.side_effect = DatabaseError("Connection lost", None, None)
            
            # Act & Assert
            with pytest.raises(DatabaseError):
                instance = {context.model_name}(**test_data)
                db.session.add(instance)
                db.session.commit()''',
            tags=['error', 'database']
        )
        test_cases.append(db_error_test)
        
        return test_cases
    
    def _build_model_test_file(self, context: ModelTestContext, test_cases: List[TestCase]) -> str:
        """Build complete model test file."""
        # Generate imports
        imports = self._generate_imports()
        imports.extend([
            f'from app.models import {context.model_name}',
            'from app import db',
            'from sqlalchemy.exc import IntegrityError, DataError',
            'from werkzeug.exceptions import ValidationError',
            'import pytest'
        ])
        
        # Build test class
        test_class_code = f'''
class Test{context.model_name}Model(unittest.TestCase):
    """Comprehensive unit tests for {context.model_name} model."""
    
    def setUp(self):
        """Set up test environment before each test."""
        self.app = create_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
    
    def tearDown(self):
        """Clean up test environment after each test."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
'''
        
        # Add test methods
        for test_case in test_cases:
            test_class_code += f"\n{test_case.test_code}\n"
        
        # Add helper methods
        test_class_code += self._generate_test_helpers(context)
        
        # Combine everything
        file_content = f'''"""
Unit tests for {context.model_name} model.

Generated automatically by PgForge Testing Framework.
Generated at: {self._get_timestamp()}
"""

{chr(10).join(imports)}

{test_class_code}

{self.generate_assertion_helpers()}

{self.generate_mock_helpers()}

if __name__ == '__main__':
    unittest.main()
'''
        
        return file_content
    
    def _generate_test_data_dict(self, context: ModelTestContext, exclude: List[str] = None, 
                                overrides: Dict[str, str] = None) -> str:
        """Generate test data dictionary for a model."""
        exclude = exclude or []
        overrides = overrides or {}
        
        data_lines = []
        
        for column in context.columns:
            if column.name in exclude or column.primary_key:
                continue
            
            if column.name in overrides:
                data_lines.append(f"            '{column.name}': {overrides[column.name]}")
            else:
                sample_value = self._generate_sample_value_for_column(column)
                data_lines.append(f"            '{column.name}': {sample_value}")
        
        return ',\n'.join(data_lines)
    
    def _generate_field_assertions(self, context: ModelTestContext, instance_var: str) -> str:
        """Generate field assertion statements."""
        assertions = []
        
        for column in context.columns:
            if column.primary_key:
                continue
            
            sample_value = self._generate_sample_value_for_column(column)
            assertions.append(f"        assert {instance_var}.{column.name} == {sample_value}")
        
        return '\n'.join(assertions)
    
    def _generate_update_operations(self, context: ModelTestContext) -> str:
        """Generate update operation statements."""
        updates = []
        
        # Update first few non-key fields
        updateable_columns = [col for col in context.columns[:3] if not col.primary_key and not col.foreign_key]
        
        for column in updateable_columns:
            new_value = self._generate_sample_value_for_column(column, suffix="_updated")
            updates.append(f"        instance.{column.name} = {new_value}")
        
        return '\n'.join(updates)
    
    def _generate_update_assertions(self, context: ModelTestContext) -> str:
        """Generate assertions for updated fields."""
        assertions = []
        
        updateable_columns = [col for col in context.columns[:3] if not col.primary_key and not col.foreign_key]
        
        for column in updateable_columns:
            new_value = self._generate_sample_value_for_column(column, suffix="_updated")
            assertions.append(f"        assert updated_instance.{column.name} == {new_value}")
        
        return '\n'.join(assertions)
    
    def _generate_boundary_test_data(self, context: ModelTestContext, boundary_type: str) -> str:
        """Generate boundary test data."""
        data_lines = []
        
        for column in context.columns:
            if column.primary_key or column.foreign_key:
                continue
            
            if boundary_type == 'min':
                if hasattr(column, 'type') and 'string' in str(column.type).lower():
                    value = "''"  # Empty string
                elif 'integer' in str(getattr(column, 'type', '')).lower():
                    value = "0"
                else:
                    value = self._generate_sample_value_for_column(column)
            else:  # max
                if hasattr(column, 'type') and hasattr(column.type, 'length') and column.type.length:
                    value = f"'{'x' * column.type.length}'"
                elif 'integer' in str(getattr(column, 'type', '')).lower():
                    value = "2147483647"  # Max int32
                else:
                    value = self._generate_sample_value_for_column(column)
            
            data_lines.append(f"            '{column.name}': {value}")
        
        return ',\n'.join(data_lines)
    
    def _generate_sample_value_for_column(self, column, suffix: str = "") -> str:
        """Generate sample value for a column with optional suffix."""
        if hasattr(column, 'category'):
            category = str(column.category).lower()
            if 'string' in category or 'text' in category:
                return f"'test_{column.name}{suffix}'"
            elif 'integer' in category:
                return "123"
            elif 'float' in category or 'numeric' in category:
                return "123.45"
            elif 'boolean' in category:
                return "True"
            elif 'date' in category or 'time' in category:
                return "datetime.now()"
            elif 'json' in category:
                return "{}"
        
        # Fallback based on column name
        name_lower = column.name.lower()
        if 'email' in name_lower:
            return f"'test{suffix}@example.com'"
        elif 'phone' in name_lower:
            return "'123-456-7890'"
        elif 'url' in name_lower:
            return "'http://example.com'"
        elif 'name' in name_lower:
            return f"'Test {column.name.title()}{suffix}'"
        
        return f"'test_{column.name}{suffix}'"
    
    def _generate_test_helpers(self, context: ModelTestContext) -> str:
        """Generate helper methods for the test class."""
        return f'''
    def create_valid_{context.table_name}(self, **overrides):
        """Create a valid {context.model_name} instance for testing."""
        data = {{
            {self._generate_test_data_dict(context)}
        }}
        data.update(overrides)
        return {context.model_name}(**data)
    
    def assert_{context.table_name}_equals(self, actual, expected):
        """Assert two {context.model_name} instances are equal."""
        {self._generate_equality_assertions(context)}
'''
    
    def _generate_equality_assertions(self, context: ModelTestContext) -> str:
        """Generate equality assertion statements."""
        assertions = []
        
        for column in context.columns:
            if not column.primary_key:
                assertions.append(f"        assert actual.{column.name} == expected.{column.name}")
        
        return '\n'.join(assertions)
    
    def generate_view_tests(self, table_info) -> Optional[str]:
        """Generate view tests for a table (placeholder for now)."""
        # This would generate tests for PgForge views
        # Implementation depends on view generation patterns
        return None
    
    def generate_form_tests(self, table_info) -> Optional[str]:
        """Generate form tests for a table (placeholder for now)."""
        # This would generate tests for WTForms
        # Implementation depends on form generation patterns
        return None
    
    def generate_utility_tests(self, schema) -> Optional[str]:
        """Generate tests for utility functions and helpers."""
        # This would generate tests for common utilities
        return None