"""
Integration Test Generator for PgForge Testing Framework

This module generates comprehensive integration tests that verify the interaction
between different components: views, models, APIs, security, and database operations.
"""

import os
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
import inflection

from .base_generator import BaseTestGenerator
from ..core.config import TestGenerationConfig
from ...cli.generators.database_inspector import EnhancedDatabaseInspector, TableInfo


@dataclass
class IntegrationTestSuite:
    """Represents a complete integration test suite for a model/view combination."""
    model_name: str
    view_tests: str
    api_tests: str
    security_tests: str
    workflow_tests: str
    permission_tests: str
    relationship_tests: str


class IntegrationTestGenerator(BaseTestGenerator):
    """
    Generates integration tests that verify component interactions.

    Tests generated:
    - View-Model integration (CRUD operations through views)
    - API-Model integration (REST endpoint functionality)
    - Security integration (authentication, authorization)
    - Workflow integration (multi-step business processes)
    - Permission integration (role-based access control)
    - Relationship integration (cascading operations)
    """

    def __init__(self, config: TestGenerationConfig, inspector: EnhancedDatabaseInspector):
        super().__init__(config, inspector)
        self.template_dir = "integration_tests"

    def generate_all_integration_tests(self) -> Dict[str, IntegrationTestSuite]:
        """Generate integration tests for all models."""
        test_suites = {}

        for table_info in self.inspector.get_all_tables():
            if not self._should_generate_tests(table_info):
                continue

            suite = self._generate_model_integration_suite(table_info)
            test_suites[table_info.name] = suite

        return test_suites

    def _generate_model_integration_suite(self, table_info: TableInfo) -> IntegrationTestSuite:
        """Generate complete integration test suite for a model."""
        model_name = inflection.camelize(table_info.name)

        return IntegrationTestSuite(
            model_name=model_name,
            view_tests=self._generate_view_integration_tests(table_info),
            api_tests=self._generate_api_integration_tests(table_info),
            security_tests=self._generate_security_integration_tests(table_info),
            workflow_tests=self._generate_workflow_tests(table_info),
            permission_tests=self._generate_permission_tests(table_info),
            relationship_tests=self._generate_relationship_integration_tests(table_info)
        )

    def _generate_view_integration_tests(self, table_info: TableInfo) -> str:
        """Generate view-model integration tests."""
        model_name = inflection.camelize(table_info.name)
        view_name = f"{model_name}ModelView"

        template = f'''
class Test{model_name}ViewIntegration(BaseIntegrationTest):
    """Integration tests for {model_name} view-model interactions."""

    def setUp(self):
        super().setUp()
        self.view_class = {view_name}
        self.endpoint_base = '/{table_info.name.lower()}'

    def test_view_list_displays_correct_data(self):
        """Test that list view displays model data correctly."""
        # Create test data
        test_records = self._create_test_{table_info.name}(count=5)

        # Access list view
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertEqual(response.status_code, 200)

        # Verify all records are displayed
        for record in test_records:
{self._generate_field_assertions(table_info, indent="            ")}

    def test_view_add_creates_model_instance(self):
        """Test that add view creates model instances correctly."""
        form_data = self._get_valid_form_data()

        # Submit add form
        response = self.client.post(
            self.endpoint_base + '/add/',
            data=form_data,
            follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)

        # Verify model was created
        created_record = self.session.query({model_name}).filter_by(
            **{{k: v for k, v in form_data.items() if k in {self._get_model_fields(table_info)}}}
        ).first()

        self.assertIsNotNone(created_record)
{self._generate_field_verifications(table_info, "created_record", "form_data", indent="        ")}

    def test_view_edit_updates_model_instance(self):
        """Test that edit view updates model instances correctly."""
        # Create initial record
        original_record = self._create_test_{table_info.name}()[0]

        # Prepare update data
        update_data = self._get_valid_form_data(exclude_required=True)

        # Submit edit form
        response = self.client.post(
            f'{{self.endpoint_base}}/edit/{{original_record.id}}/',
            data=update_data,
            follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)

        # Verify model was updated
        self.session.refresh(original_record)
{self._generate_update_verifications(table_info, indent="        ")}

    def test_view_delete_removes_model_instance(self):
        """Test that delete view removes model instances correctly."""
        # Create record to delete
        record_to_delete = self._create_test_{table_info.name}()[0]
        record_id = record_to_delete.id

        # Submit delete request
        response = self.client.post(
            f'{{self.endpoint_base}}/delete/{{record_id}}/',
            follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)

        # Verify model was deleted
        deleted_record = self.session.query({model_name}).filter_by(id=record_id).first()
        self.assertIsNone(deleted_record)

    def test_view_show_displays_model_details(self):
        """Test that show view displays model details correctly."""
        # Create record to view
        test_record = self._create_test_{table_info.name}()[0]

        # Access show view
        response = self.client.get(f'{{self.endpoint_base}}/show/{{test_record.id}}/')
        self.assertEqual(response.status_code, 200)

        # Verify all fields are displayed
{self._generate_show_field_assertions(table_info, "test_record", indent="        ")}

    def test_view_handles_validation_errors(self):
        """Test that view handles model validation errors correctly."""
        # Submit invalid form data
        invalid_data = self._get_invalid_form_data()

        response = self.client.post(
            self.endpoint_base + '/add/',
            data=invalid_data
        )

        # Should stay on form with errors displayed
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'alert-danger', response.data)

        # Verify no model was created
        count = self.session.query({model_name}).count()
        self.assertEqual(count, 0)

{self._generate_search_filter_tests(table_info)}

{self._generate_pagination_tests(table_info)}
'''

        return self._format_template(template)

    def _generate_api_integration_tests(self, table_info: TableInfo) -> str:
        """Generate API-model integration tests."""
        model_name = inflection.camelize(table_info.name)
        api_endpoint = f'/api/v1/{table_info.name.lower()}'

        template = f'''
class Test{model_name}APIIntegration(BaseIntegrationTest):
    """Integration tests for {model_name} API-model interactions."""

    def setUp(self):
        super().setUp()
        self.api_endpoint = '{api_endpoint}'
        self.headers = {{'Content-Type': 'application/json'}}

    def test_api_get_list_returns_model_data(self):
        """Test that GET /api/v1/{table_info.name.lower()} returns model data."""
        # Create test data
        test_records = self._create_test_{table_info.name}(count=3)

        # Make API request
        response = self.client.get(
            self.api_endpoint + '/',
            headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # Verify response structure
        self.assertIn('result', data)
        self.assertEqual(len(data['result']), 3)

        # Verify data matches models
        for i, record in enumerate(test_records):
            api_record = data['result'][i]
{self._generate_api_field_assertions(table_info, "record", "api_record", indent="            ")}

    def test_api_get_detail_returns_single_model(self):
        """Test that GET /api/v1/{table_info.name.lower()}/id returns single model."""
        # Create test record
        test_record = self._create_test_{table_info.name}()[0]

        # Make API request
        response = self.client.get(
            f'{{self.api_endpoint}}/{{test_record.id}}',
            headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # Verify response structure and data
        self.assertIn('result', data)
        api_record = data['result']
{self._generate_api_field_assertions(table_info, "test_record", "api_record", indent="        ")}

    def test_api_post_creates_model_instance(self):
        """Test that POST /api/v1/{table_info.name.lower()} creates model instance."""
        # Prepare test data
        test_data = self._get_valid_api_data()

        # Make API request
        response = self.client.post(
            self.api_endpoint + '/',
            json=test_data,
            headers=self.headers
        )

        self.assertEqual(response.status_code, 201)
        data = response.get_json()

        # Verify response
        self.assertIn('result', data)
        created_id = data['result']['id']

        # Verify model was created in database
        created_record = self.session.query({model_name}).filter_by(id=created_id).first()
        self.assertIsNotNone(created_record)
{self._generate_model_api_verifications(table_info, "created_record", "test_data", indent="        ")}

    def test_api_put_updates_model_instance(self):
        """Test that PUT /api/v1/{table_info.name.lower()}/id updates model instance."""
        # Create initial record
        original_record = self._create_test_{table_info.name}()[0]

        # Prepare update data
        update_data = self._get_valid_api_data(partial=True)

        # Make API request
        response = self.client.put(
            f'{{self.api_endpoint}}/{{original_record.id}}',
            json=update_data,
            headers=self.headers
        )

        self.assertEqual(response.status_code, 200)

        # Verify model was updated
        self.session.refresh(original_record)
{self._generate_api_update_verifications(table_info, "original_record", "update_data", indent="        ")}

    def test_api_delete_removes_model_instance(self):
        """Test that DELETE /api/v1/{table_info.name.lower()}/id removes model instance."""
        # Create record to delete
        record_to_delete = self._create_test_{table_info.name}()[0]
        record_id = record_to_delete.id

        # Make API request
        response = self.client.delete(
            f'{{self.api_endpoint}}/{{record_id}}',
            headers=self.headers
        )

        self.assertEqual(response.status_code, 204)

        # Verify model was deleted
        deleted_record = self.session.query({model_name}).filter_by(id=record_id).first()
        self.assertIsNone(deleted_record)

    def test_api_handles_validation_errors(self):
        """Test that API handles model validation errors correctly."""
        # Submit invalid data
        invalid_data = self._get_invalid_api_data()

        response = self.client.post(
            self.api_endpoint + '/',
            json=invalid_data,
            headers=self.headers
        )

        self.assertEqual(response.status_code, 422)
        data = response.get_json()

        # Verify error response structure
        self.assertIn('message', data)
        self.assertIn('errors', data)

        # Verify no model was created
        count = self.session.query({model_name}).count()
        self.assertEqual(count, 0)

{self._generate_api_filtering_tests(table_info)}

{self._generate_api_pagination_tests(table_info)}
'''

        return self._format_template(template)

    def _generate_security_integration_tests(self, table_info: TableInfo) -> str:
        """Generate security integration tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}SecurityIntegration(BaseIntegrationTest):
    """Integration tests for {model_name} security and authentication."""

    def setUp(self):
        super().setUp()
        self.endpoint_base = '/{table_info.name.lower()}'
        self.api_endpoint = '/api/v1/{table_info.name.lower()}'

        # Create test users with different roles
        self.admin_user = self._create_test_user('admin', roles=['Admin'])
        self.user_user = self._create_test_user('user', roles=['User'])
        self.readonly_user = self._create_test_user('readonly', roles=['ReadOnly'])

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated users cannot access protected resources."""
        # Test view endpoints
        for endpoint in ['/list/', '/add/', '/edit/1/', '/delete/1/', '/show/1/']:
            response = self.client.get(self.endpoint_base + endpoint)
            self.assertIn(response.status_code, [302, 401])  # Redirect to login or 401

        # Test API endpoints
        for method, endpoint in [
            ('GET', '/'),
            ('POST', '/'),
            ('PUT', '/1'),
            ('DELETE', '/1')
        ]:
            response = getattr(self.client, method.lower())(self.api_endpoint + endpoint)
            self.assertEqual(response.status_code, 401)

    def test_admin_full_access(self):
        """Test that admin users have full access to all operations."""
        self._login_as(self.admin_user)

        # Test view access
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertEqual(response.status_code, 200)

        response = self.client.get(self.endpoint_base + '/add/')
        self.assertEqual(response.status_code, 200)

        # Test API access
        response = self.client.get(self.api_endpoint + '/')
        self.assertEqual(response.status_code, 200)

    def test_user_role_permissions(self):
        """Test that regular users have appropriate permissions."""
        self._login_as(self.user_user)

        # Test what user should be able to access
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertEqual(response.status_code, 200)

        # Test what user should not be able to access (if applicable)
        # This depends on your specific permission model

    def test_readonly_user_restrictions(self):
        """Test that readonly users can only view, not modify."""
        self._login_as(self.readonly_user)

        # Should be able to view
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertEqual(response.status_code, 200)

        # Should not be able to add
        response = self.client.get(self.endpoint_base + '/add/')
        self.assertIn(response.status_code, [403, 302])

        # Should not be able to POST via API
        response = self.client.post(
            self.api_endpoint + '/',
            json={{'name': 'test'}},
            headers={{'Content-Type': 'application/json'}}
        )
        self.assertEqual(response.status_code, 403)

    def test_row_level_security(self):
        """Test row-level security if implemented."""
        # This test depends on your specific security implementation
        # Example: users can only see their own records
        pass

    def test_field_level_security(self):
        """Test field-level security if implemented."""
        # This test depends on your specific security implementation
        # Example: certain fields are hidden from certain roles
        pass

    def test_csrf_protection(self):
        """Test that CSRF protection works correctly."""
        self._login_as(self.user_user)

        # Submit form without CSRF token (should fail)
        form_data = self._get_valid_form_data()
        response = self.client.post(
            self.endpoint_base + '/add/',
            data=form_data
        )

        # Should be rejected (exact response depends on CSRF implementation)
        self.assertNotEqual(response.status_code, 201)

    def test_session_management(self):
        """Test session management and timeout."""
        # Login
        self._login_as(self.user_user)

        # Verify session works
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertEqual(response.status_code, 200)

        # Logout
        self.client.get('/logout')

        # Verify session is invalidated
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertIn(response.status_code, [302, 401])
'''

        return self._format_template(template)

    def _generate_workflow_tests(self, table_info: TableInfo) -> str:
        """Generate workflow integration tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}WorkflowIntegration(BaseIntegrationTest):
    """Integration tests for {model_name} business workflows."""

    def setUp(self):
        super().setUp()
        self.endpoint_base = '/{table_info.name.lower()}'
        self.api_endpoint = '/api/v1/{table_info.name.lower()}'

    def test_create_read_update_delete_workflow(self):
        """Test complete CRUD workflow integration."""
        # 1. Create
        create_data = self._get_valid_form_data()
        response = self.client.post(
            self.endpoint_base + '/add/',
            data=create_data,
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        # Find created record
        created_record = self.session.query({model_name}).filter_by(
            **{{k: v for k, v in create_data.items() if k in {self._get_model_fields(table_info)}}}
        ).first()
        self.assertIsNotNone(created_record)
        record_id = created_record.id

        # 2. Read
        response = self.client.get(f'{{self.endpoint_base}}/show/{{record_id}}/')
        self.assertEqual(response.status_code, 200)

        # 3. Update
        update_data = self._get_valid_form_data(exclude_required=True)
        response = self.client.post(
            f'{{self.endpoint_base}}/edit/{{record_id}}/',
            data=update_data,
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        # Verify update
        self.session.refresh(created_record)
        # Add specific field verifications based on update_data

        # 4. Delete
        response = self.client.post(
            f'{{self.endpoint_base}}/delete/{{record_id}}/',
            follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)

        # Verify deletion
        deleted_record = self.session.query({model_name}).filter_by(id=record_id).first()
        self.assertIsNone(deleted_record)

    def test_bulk_operations_workflow(self):
        """Test bulk operations workflow."""
        # Create multiple records
        test_records = self._create_test_{table_info.name}(count=5)
        record_ids = [r.id for r in test_records]

        # Test bulk selection and actions
        bulk_data = {{
            'rowid': record_ids[:3],  # Select first 3 records
            'action': 'muldelete'
        }}

        response = self.client.post(
            self.endpoint_base + '/list/',
            data=bulk_data,
            follow_redirects=True
        )

        # Verify bulk delete worked
        remaining_count = self.session.query({model_name}).filter(
            {model_name}.id.in_(record_ids[:3])
        ).count()
        self.assertEqual(remaining_count, 0)

        # Verify other records remain
        remaining_count = self.session.query({model_name}).filter(
            {model_name}.id.in_(record_ids[3:])
        ).count()
        self.assertEqual(remaining_count, 2)

{self._generate_relationship_workflow_tests(table_info)}

{self._generate_business_logic_workflow_tests(table_info)}
'''

        return self._format_template(template)

    def _generate_permission_tests(self, table_info: TableInfo) -> str:
        """Generate permission integration tests."""
        model_name = inflection.camelize(table_info.name)

        template = f'''
class Test{model_name}PermissionIntegration(BaseIntegrationTest):
    """Integration tests for {model_name} permission system."""

    def setUp(self):
        super().setUp()
        self.model_name = '{model_name}'
        self.view_name = '{model_name}ModelView'

        # Create users with specific permissions
        self.full_access_user = self._create_user_with_permissions([
            f'can_list_{{self.model_name}}',
            f'can_show_{{self.model_name}}',
            f'can_add_{{self.model_name}}',
            f'can_edit_{{self.model_name}}',
            f'can_delete_{{self.model_name}}'
        ])

        self.read_only_user = self._create_user_with_permissions([
            f'can_list_{{self.model_name}}',
            f'can_show_{{self.model_name}}'
        ])

        self.no_access_user = self._create_user_with_permissions([])

    def test_permission_enforcement_on_views(self):
        """Test that view permissions are enforced correctly."""
        test_record = self._create_test_{table_info.name}()[0]

        # Test full access user
        self._login_as(self.full_access_user)

        for endpoint in ['/list/', '/add/', f'/edit/{{test_record.id}}/', f'/show/{{test_record.id}}/']:
            response = self.client.get('/{table_info.name.lower()}' + endpoint)
            self.assertEqual(response.status_code, 200,
                           f"Full access user should access {{endpoint}}")

        # Test read-only user
        self._login_as(self.read_only_user)

        # Should have read access
        response = self.client.get('/{table_info.name.lower()}/list/')
        self.assertEqual(response.status_code, 200)

        response = self.client.get(f'/{table_info.name.lower()}/show/{{test_record.id}}/')
        self.assertEqual(response.status_code, 200)

        # Should not have write access
        response = self.client.get('/{table_info.name.lower()}/add/')
        self.assertIn(response.status_code, [403, 302])

        response = self.client.get(f'/{table_info.name.lower()}/edit/{{test_record.id}}/')
        self.assertIn(response.status_code, [403, 302])

        # Test no access user
        self._login_as(self.no_access_user)

        for endpoint in ['/list/', '/add/', f'/edit/{{test_record.id}}/', f'/show/{{test_record.id}}/']:
            response = self.client.get('/{table_info.name.lower()}' + endpoint)
            self.assertIn(response.status_code, [403, 302],
                         f"No access user should be denied {{endpoint}}")

    def test_permission_enforcement_on_api(self):
        """Test that API permissions are enforced correctly."""
        test_record = self._create_test_{table_info.name}()[0]
        api_base = '/api/v1/{table_info.name.lower()}'

        # Test full access user
        self._login_as(self.full_access_user)

        response = self.client.get(api_base + '/')
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            api_base + '/',
            json=self._get_valid_api_data()
        )
        self.assertEqual(response.status_code, 201)

        # Test read-only user
        self._login_as(self.read_only_user)

        response = self.client.get(api_base + '/')
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            api_base + '/',
            json=self._get_valid_api_data()
        )
        self.assertEqual(response.status_code, 403)

        # Test no access user
        self._login_as(self.no_access_user)

        response = self.client.get(api_base + '/')
        self.assertEqual(response.status_code, 403)

    def test_menu_visibility_based_on_permissions(self):
        """Test that menu items are visible based on permissions."""
        # Test full access user sees menu
        self._login_as(self.full_access_user)
        response = self.client.get('/')
        self.assertIn('{model_name}'.encode(), response.data)

        # Test no access user doesn't see menu
        self._login_as(self.no_access_user)
        response = self.client.get('/')
        self.assertNotIn('{model_name}'.encode(), response.data)

    def test_dynamic_permission_checking(self):
        """Test dynamic permission checking during operations."""
        # Create record as full access user
        self._login_as(self.full_access_user)
        test_record = self._create_test_{table_info.name}()[0]

        # Switch to read-only user and try to modify
        self._login_as(self.read_only_user)

        update_data = self._get_valid_form_data()
        response = self.client.post(
            f'/{table_info.name.lower()}/edit/{{test_record.id}}/',
            data=update_data
        )

        self.assertIn(response.status_code, [403, 302])

        # Verify record was not modified
        self.session.refresh(test_record)
        # Add specific field checks to verify no changes
'''

        return self._format_template(template)

    def _generate_relationship_integration_tests(self, table_info: TableInfo) -> str:
        """Generate relationship integration tests."""
        model_name = inflection.camelize(table_info.name)
        relationships = self.inspector.get_relationships(table_info.name)

        if not relationships:
            return f"# No relationships found for {model_name}"

        template = f'''
class Test{model_name}RelationshipIntegration(BaseIntegrationTest):
    """Integration tests for {model_name} relationship operations."""

    def setUp(self):
        super().setUp()

{self._generate_relationship_test_methods(table_info, relationships)}
'''

        return self._format_template(template)

    def _generate_field_assertions(self, table_info: TableInfo, indent: str = "") -> str:
        """Generate field assertions for view tests."""
        assertions = []
        for column in table_info.columns:
            if column.type.lower() in ['varchar', 'text', 'string']:
                assertions.append(f"{indent}self.assertIn(str(record.{column.name}).encode(), response.data)")
        return "\n".join(assertions)

    def _generate_show_field_assertions(self, table_info: TableInfo, record_var: str, indent: str = "") -> str:
        """Generate show view field assertions."""
        assertions = []
        for column in table_info.columns:
            if column.type.lower() in ['varchar', 'text', 'string']:
                assertions.append(f"{indent}self.assertIn(str({record_var}.{column.name}).encode(), response.data)")
        return "\n".join(assertions)

    def _generate_api_field_assertions(self, table_info: TableInfo, model_var: str, api_var: str, indent: str = "") -> str:
        """Generate API field assertions."""
        assertions = []
        for column in table_info.columns:
            assertions.append(f"{indent}self.assertEqual({api_var}['{column.name}'], {model_var}.{column.name})")
        return "\n".join(assertions)

    def _get_model_fields(self, table_info: TableInfo) -> Set[str]:
        """Get set of model field names."""
        return {col.name for col in table_info.columns}

    def write_integration_tests_to_file(self, output_dir: str, test_suites: Dict[str, IntegrationTestSuite]):
        """Write all integration test suites to files."""
        os.makedirs(output_dir, exist_ok=True)

        for model_name, suite in test_suites.items():
            # Write main integration test file
            test_content = f'''
"""
Integration tests for {model_name} model.

This file contains comprehensive integration tests that verify the interaction
between views, models, APIs, security, and database operations.
"""

import unittest
from flask import url_for
from flask_testing import TestCase

from tests.base_integration_test import BaseIntegrationTest
from app.models import {suite.model_name}


{suite.view_tests}

{suite.api_tests}

{suite.security_tests}

{suite.workflow_tests}

{suite.permission_tests}

{suite.relationship_tests}


if __name__ == '__main__':
    unittest.main()
'''

            filename = f"test_{model_name.lower()}_integration.py"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w') as f:
                f.write(test_content)

    def _generate_search_filter_tests(self, table_info: TableInfo) -> str:
        """Generate search and filter integration tests."""
        searchable_columns = [col for col in table_info.columns
                            if col.type.lower() in ['varchar', 'text', 'string']]

        if not searchable_columns:
            return ""

        template = '''
    def test_view_search_functionality(self):
        """Test that search functionality works correctly."""
        # Create test data with searchable values
        test_records = self._create_test_{table_name}(count=5)
        search_term = str(test_records[0].{search_field})[:5]

        # Perform search
        response = self.client.post(
            self.endpoint_base + '/list/',
            data={{'_flt_0_{search_field}': search_term}}
        )

        self.assertEqual(response.status_code, 200)
        # Verify search results contain the term
        self.assertIn(search_term.encode(), response.data)

    def test_view_filter_functionality(self):
        """Test that filter functionality works correctly."""
        # Create test data with different values
        test_records = self._create_test_{table_name}(count=3)

        # Apply filter
        filter_value = test_records[0].{filter_field}
        response = self.client.get(
            self.endpoint_base + f'/list/?_flt_0_{filter_field}={{filter_value}}'
        )

        self.assertEqual(response.status_code, 200)
        # Verify only matching records are shown
        '''.format(
            table_name=table_info.name,
            search_field=searchable_columns[0].name,
            filter_field=searchable_columns[0].name
        )

        return template

    def _generate_pagination_tests(self, table_info: TableInfo) -> str:
        """Generate pagination integration tests."""
        template = '''
    def test_view_pagination_functionality(self):
        """Test that pagination works correctly."""
        # Create more records than page size
        test_records = self._create_test_{table_name}(count=25)

        # Test first page
        response = self.client.get(self.endpoint_base + '/list/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Page 1', response.data)

        # Test second page
        response = self.client.get(self.endpoint_base + '/list/?page=1')
        self.assertEqual(response.status_code, 200)
        # Should contain different records or page indicator
        '''.format(table_name=table_info.name)

        return template

    def _generate_api_filtering_tests(self, table_info: TableInfo) -> str:
        """Generate API filtering tests."""
        template = '''
    def test_api_filtering_functionality(self):
        """Test that API filtering works correctly."""
        # Create test data
        test_records = self._create_test_{table_name}(count=5)

        # Test API filtering
        filter_params = {{'q': f'(filters:[{{col:"{filter_field}",opr:"eq",value:"{test_records[0].{filter_field}}"}}])'}}
        response = self.client.get(
            self.api_endpoint + '/',
            query_string=filter_params,
            headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # Verify filtered results
        self.assertTrue(len(data['result']) >= 1)
        for record in data['result']:
            self.assertEqual(record['{filter_field}'], test_records[0].{filter_field})
        '''.format(
            table_name=table_info.name,
            filter_field=table_info.columns[0].name
        )

        return template

    def _generate_api_pagination_tests(self, table_info: TableInfo) -> str:
        """Generate API pagination tests."""
        template = '''
    def test_api_pagination_functionality(self):
        """Test that API pagination works correctly."""
        # Create more records than page size
        test_records = self._create_test_{table_name}(count=25)

        # Test first page
        response = self.client.get(
            self.api_endpoint + '/?page_size=10&page=0',
            headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        # Verify pagination info
        self.assertEqual(len(data['result']), 10)
        self.assertIn('count', data)
        self.assertEqual(data['count'], 25)

        # Test second page
        response = self.client.get(
            self.api_endpoint + '/?page_size=10&page=1',
            headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        second_page_data = response.get_json()

        # Verify different records on second page
        first_page_ids = [r['id'] for r in data['result']]
        second_page_ids = [r['id'] for r in second_page_data['result']]
        self.assertEqual(len(set(first_page_ids) & set(second_page_ids)), 0)
        '''.format(table_name=table_info.name)

        return template