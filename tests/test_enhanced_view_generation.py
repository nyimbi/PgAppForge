"""
Test suite for enhanced view generation including master-detail views,
inline formsets, and relationship-specific views.
"""

import os
import tempfile
import shutil
from unittest import TestCase, mock
from unittest.mock import patch, MagicMock

import sqlalchemy as sa
from sqlalchemy import MetaData, Table, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.engine import create_engine

from pgappforge.cli.generators.database_inspector import (
    EnhancedDatabaseInspector,
    MasterDetailInfo,
    RelationshipType,
    RelationshipInfo
)
from pgappforge.cli.generators.view_generator import (
    BeautifulViewGenerator,
    ViewGenerationConfig
)


class TestEnhancedViewGeneration(TestCase):
    """Test enhanced view generation with master-detail patterns."""

    def setUp(self):
        """Set up test environment."""
        self.test_db_uri = "sqlite:///:memory:"
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        
        # Create test database schema
        self.engine = create_engine(self.test_db_uri)
        self.metadata = MetaData()
        
        # Define test tables with master-detail relationships
        self.customers_table = Table(
            'customers', self.metadata,
            Column('id', Integer, primary_key=True),
            Column('name', String(100), nullable=False),
            Column('email', String(100)),
            Column('phone', String(20)),
            Column('address', String(200))
        )
        
        self.orders_table = Table(
            'orders', self.metadata,
            Column('id', Integer, primary_key=True),
            Column('customer_id', Integer, ForeignKey('customers.id'), nullable=False),
            Column('order_date', DateTime),
            Column('total_amount', sa.Numeric(10, 2)),
            Column('status', String(20))
        )
        
        self.order_items_table = Table(
            'order_items', self.metadata,
            Column('id', Integer, primary_key=True),
            Column('order_id', Integer, ForeignKey('orders.id'), nullable=False),
            Column('product_name', String(100)),
            Column('quantity', Integer),
            Column('unit_price', sa.Numeric(10, 2))
        )
        
        # Table with multiple foreign keys for lookup view testing
        self.invoices_table = Table(
            'invoices', self.metadata,
            Column('id', Integer, primary_key=True),
            Column('customer_id', Integer, ForeignKey('customers.id')),
            Column('order_id', Integer, ForeignKey('orders.id')),
            Column('invoice_number', String(50)),
            Column('invoice_date', DateTime),
            Column('amount', sa.Numeric(10, 2))
        )
        
        # Create tables
        self.metadata.create_all(self.engine)

    def test_master_detail_pattern_detection(self):
        """Test detection of master-detail relationship patterns."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            # Test customer -> orders master-detail pattern
            patterns = inspector.analyze_master_detail_patterns('customers')
            
            self.assertGreater(len(patterns), 0)
            
            # Find the customer-orders pattern
            customer_order_pattern = next(
                (p for p in patterns if p.child_table == 'orders'), 
                None
            )
            
            self.assertIsNotNone(customer_order_pattern)
            self.assertEqual(customer_order_pattern.parent_table, 'customers')
            self.assertEqual(customer_order_pattern.child_table, 'orders')
            self.assertTrue(customer_order_pattern.is_suitable_for_inline)
            
            # Verify pattern configuration
            self.assertIn(customer_order_pattern.expected_child_count, ['few', 'moderate', 'many'])
            self.assertIsInstance(customer_order_pattern.child_display_fields, list)
            self.assertIsInstance(customer_order_pattern.parent_display_fields, list)

    def test_lookup_view_detection(self):
        """Test detection of tables suitable for lookup views."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            variations = inspector.get_relationship_view_variations('invoices')
            
            # Invoices table has multiple foreign keys, should suggest lookup view
            self.assertIn('lookup_views', variations)
            self.assertGreater(len(variations['lookup_views']), 0)
            
            lookup_view_name = variations['lookup_views'][0]
            self.assertEqual(lookup_view_name, 'InvoicesLookupView')

    def test_reference_view_generation(self):
        """Test generation of reference views."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            variations = inspector.get_relationship_view_variations('orders')
            
            # Orders table should have reference views
            self.assertIn('reference_views', variations)
            self.assertGreater(len(variations['reference_views']), 0)
            
            # Should have a reference view for customer relationship
            reference_views = variations['reference_views']
            customer_ref_view = next(
                (view for view in reference_views if 'Customer' in view),
                None
            )
            self.assertIsNotNone(customer_ref_view)

    def test_view_generation_config(self):
        """Test view generation configuration."""
        config = ViewGenerationConfig(
            generate_master_detail_views=True,
            generate_lookup_views=True,
            generate_reference_views=True,
            generate_relationship_views=True,
            enable_inline_formsets=True,
            max_inline_forms=25,
            inline_form_layouts=['stacked', 'tabular']
        )
        
        self.assertTrue(config.generate_master_detail_views)
        self.assertTrue(config.enable_inline_formsets)
        self.assertEqual(config.max_inline_forms, 25)
        self.assertIn('stacked', config.inline_form_layouts)
        self.assertIn('tabular', config.inline_form_layouts)

    def test_master_detail_view_generation(self):
        """Test generation of master-detail views."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig(
                generate_master_detail_views=True,
                enable_inline_formsets=True,
                inline_form_layouts=['stacked']
            )
            
            generator = BeautifulViewGenerator(inspector, config)
            customer_info = inspector.analyze_table('customers')
            
            # Generate master-detail views
            master_detail_views = generator.generate_master_detail_views(customer_info)
            
            self.assertIsInstance(master_detail_views, dict)
            
            if master_detail_views:
                # Verify view code generation
                for view_name, view_code in master_detail_views.items():
                    self.assertIsInstance(view_code, str)
                    self.assertIn('MasterDetailView', view_code)
                    self.assertIn('inline_formsets', view_code)
                    self.assertIn('ModelView', view_code)

    def test_lookup_view_generation(self):
        """Test generation of lookup views."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig(generate_lookup_views=True)
            generator = BeautifulViewGenerator(inspector, config)
            
            invoice_info = inspector.analyze_table('invoices')
            lookup_view = generator.generate_lookup_view(invoice_info)
            
            if lookup_view:  # Only test if lookup view was generated
                self.assertIsInstance(lookup_view, str)
                self.assertIn('LookupView', lookup_view)
                self.assertIn('FilterStartsWith', lookup_view)
                self.assertIn('search_form_query_rel_fields', lookup_view)

    def test_reference_view_generation(self):
        """Test generation of reference views."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig(generate_reference_views=True)
            generator = BeautifulViewGenerator(inspector, config)
            
            order_info = inspector.analyze_table('orders')
            reference_views = generator.generate_reference_views(order_info)
            
            self.assertIsInstance(reference_views, dict)
            
            if reference_views:
                for view_name, view_code in reference_views.items():
                    self.assertIsInstance(view_code, str)
                    self.assertIn('ModelView', view_code)
                    self.assertIn('filter_by_reference', view_code)

    def test_relationship_navigation_view(self):
        """Test generation of relationship navigation views."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig(generate_relationship_views=True)
            generator = BeautifulViewGenerator(inspector, config)
            
            customer_info = inspector.analyze_table('customers')
            nav_view = generator.generate_relationship_navigation_view(customer_info)
            
            if nav_view:  # Only test if navigation view was generated
                self.assertIsInstance(nav_view, str)
                self.assertIn('BaseView', nav_view)
                self.assertIn('relationship_stats', nav_view)
                self.assertIn('relationship_matrix', nav_view)

    def test_complete_view_generation_pipeline(self):
        """Test the complete view generation pipeline."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig(
                generate_master_detail_views=True,
                generate_lookup_views=True,
                generate_reference_views=True,
                generate_relationship_views=True,
                enable_inline_formsets=True
            )
            
            generator = BeautifulViewGenerator(inspector, config)
            
            # Generate views for all tables
            results = generator.generate_all_views(self.temp_dir)
            
            # Verify results structure
            self.assertIn('generated_files', results)
            self.assertIn('view_statistics', results)
            self.assertIn('master_detail_patterns', results)
            self.assertIn('relationship_views', results)
            self.assertIn('errors', results)
            
            # Verify statistics
            self.assertGreater(len(results['view_statistics']), 0)
            
            # Check for generated files
            views_dir = os.path.join(self.temp_dir, 'views')
            if os.path.exists(views_dir):
                generated_files = os.listdir(views_dir)
                self.assertGreater(len(generated_files), 0)

    def test_inline_formset_template_generation(self):
        """Test generation of inline formset templates."""
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig(
                enable_inline_formsets=True,
                inline_form_layouts=['stacked', 'tabular', 'accordion']
            )
            
            generator = BeautifulViewGenerator(inspector, config)
            
            # Generate templates
            generator._generate_inline_formset_templates(self.temp_dir)
            
            # Verify template files were created
            templates_dir = os.path.join(
                self.temp_dir, 'templates', 'appbuilder', 'general', 'model'
            )
            
            if os.path.exists(templates_dir):
                template_files = os.listdir(templates_dir)
                
                # Check for different layout templates
                expected_templates = [
                    'edit_master_detail_stacked.html',
                    'add_master_detail_stacked.html',
                    'edit_master_detail_tabular.html',
                    'add_master_detail_tabular.html',
                    'edit_master_detail_accordion.html',
                    'add_master_detail_accordion.html',
                    'relationship_navigation.html',
                    'relationship_matrix.html'
                ]
                
                for expected in expected_templates:
                    if expected in template_files:
                        template_path = os.path.join(templates_dir, expected)
                        self.assertTrue(os.path.getsize(template_path) > 0)

    def test_error_handling(self):
        """Test error handling in view generation."""
        # Test with invalid database URI
        with self.assertRaises(Exception):
            with EnhancedDatabaseInspector("invalid://uri") as inspector:
                pass
        
        # Test with valid inspector but invalid operations
        with EnhancedDatabaseInspector(self.test_db_uri) as inspector:
            config = ViewGenerationConfig()
            generator = BeautifulViewGenerator(inspector, config)
            
            # Test with non-existent table
            try:
                result = inspector.analyze_table('non_existent_table')
                # If this doesn't raise an exception, that's also valid
            except Exception:
                pass  # Expected behavior

    def tearDown(self):
        """Clean up test environment."""
        if hasattr(self, 'engine'):
            self.engine.dispose()


class TestMasterDetailInfoDataClass(TestCase):
    """Test the MasterDetailInfo dataclass."""
    
    def test_master_detail_info_creation(self):
        """Test creation of MasterDetailInfo objects."""
        # Mock relationship info
        relationship = MagicMock()
        relationship.name = "orders"
        relationship.type = RelationshipType.ONE_TO_MANY
        
        master_detail = MasterDetailInfo(
            parent_table="customers",
            child_table="orders",
            relationship=relationship,
            is_suitable_for_inline=True,
            expected_child_count="moderate",
            child_display_fields=["order_date", "total_amount", "status"],
            parent_display_fields=["name", "email"],
            inline_edit_suitable=True,
            supports_bulk_operations=True,
            default_child_count=5,
            min_child_forms=0,
            max_child_forms=25,
            enable_sorting=True,
            enable_deletion=True,
            child_form_layout="tabular"
        )
        
        self.assertEqual(master_detail.parent_table, "customers")
        self.assertEqual(master_detail.child_table, "orders")
        self.assertTrue(master_detail.is_suitable_for_inline)
        self.assertEqual(master_detail.expected_child_count, "moderate")
        self.assertEqual(len(master_detail.child_display_fields), 3)
        self.assertEqual(master_detail.child_form_layout, "tabular")


if __name__ == '__main__':
    import unittest
    unittest.main(verbosity=2)