#!/usr/bin/env python3
"""
Enhanced View Generation Demo

Demonstrates the new master-detail views, inline formsets, and relationship-specific 
view generation capabilities of PgAppForge.

Usage:
    python enhanced_view_generation_demo.py [DATABASE_URI] [OUTPUT_DIR]
    
Example:
    python enhanced_view_generation_demo.py "postgresql://user:pass@localhost/db" ./generated_views
"""

import sys
import os
import tempfile
from pathlib import Path

# Add the parent directory to the path so we can import the generators
sys.path.insert(0, str(Path(__file__).parent.parent))

from pgappforge.cli.generators.database_inspector import EnhancedDatabaseInspector
from pgappforge.cli.generators.view_generator import (
    BeautifulViewGenerator,
    ViewGenerationConfig
)


def create_demo_database(db_uri: str = "sqlite:///demo.db"):
    """
    Create a demo database with master-detail relationships.
    
    Args:
        db_uri: Database URI for the demo database
    """
    import sqlalchemy as sa
    from sqlalchemy import MetaData, Table, Column, Integer, String, DateTime, ForeignKey, Numeric
    
    print("🔧 Creating demo database schema...")
    
    engine = sa.create_engine(db_uri)
    metadata = MetaData()
    
    # Companies table (parent)
    companies = Table(
        'companies', metadata,
        Column('id', Integer, primary_key=True),
        Column('name', String(100), nullable=False),
        Column('email', String(100)),
        Column('phone', String(20)),
        Column('website', String(100)),
        Column('industry', String(50)),
        Column('founded_date', DateTime),
        Column('employee_count', Integer),
        Column('address', String(200)),
        Column('city', String(50)),
        Column('country', String(50))
    )
    
    # Employees table (child of companies)
    employees = Table(
        'employees', metadata,
        Column('id', Integer, primary_key=True),
        Column('company_id', Integer, ForeignKey('companies.id'), nullable=False),
        Column('first_name', String(50), nullable=False),
        Column('last_name', String(50), nullable=False),
        Column('email', String(100)),
        Column('phone', String(20)),
        Column('department', String(50)),
        Column('position', String(100)),
        Column('salary', Numeric(10, 2)),
        Column('hire_date', DateTime),
        Column('manager_id', Integer, ForeignKey('employees.id'))  # Self-referencing
    )
    
    # Projects table (parent)
    projects = Table(
        'projects', metadata,
        Column('id', Integer, primary_key=True),
        Column('company_id', Integer, ForeignKey('companies.id')),
        Column('name', String(100), nullable=False),
        Column('description', String(500)),
        Column('start_date', DateTime),
        Column('end_date', DateTime),
        Column('status', String(20)),
        Column('budget', Numeric(12, 2)),
        Column('project_manager_id', Integer, ForeignKey('employees.id'))
    )
    
    # Tasks table (child of projects)
    tasks = Table(
        'tasks', metadata,
        Column('id', Integer, primary_key=True),
        Column('project_id', Integer, ForeignKey('projects.id'), nullable=False),
        Column('name', String(100), nullable=False),
        Column('description', String(500)),
        Column('assigned_to_id', Integer, ForeignKey('employees.id')),
        Column('status', String(20)),
        Column('priority', String(10)),
        Column('estimated_hours', Integer),
        Column('actual_hours', Integer),
        Column('due_date', DateTime),
        Column('completed_date', DateTime)
    )
    
    # Time entries table (child of tasks)
    time_entries = Table(
        'time_entries', metadata,
        Column('id', Integer, primary_key=True),
        Column('task_id', Integer, ForeignKey('tasks.id'), nullable=False),
        Column('employee_id', Integer, ForeignKey('employees.id'), nullable=False),
        Column('date', DateTime),
        Column('hours', Numeric(4, 2)),
        Column('description', String(200))
    )
    
    # Invoices table (multiple foreign keys - good for lookup views)
    invoices = Table(
        'invoices', metadata,
        Column('id', Integer, primary_key=True),
        Column('company_id', Integer, ForeignKey('companies.id')),
        Column('project_id', Integer, ForeignKey('projects.id')),
        Column('employee_id', Integer, ForeignKey('employees.id')),  # Who created it
        Column('invoice_number', String(50)),
        Column('invoice_date', DateTime),
        Column('due_date', DateTime),
        Column('amount', Numeric(10, 2)),
        Column('tax_amount', Numeric(10, 2)),
        Column('total_amount', Numeric(10, 2)),
        Column('status', String(20)),
        Column('notes', String(500))
    )
    
    # Create all tables
    metadata.create_all(engine)
    
    print("✅ Demo database schema created!")
    return engine


def demonstrate_master_detail_detection(inspector: EnhancedDatabaseInspector):
    """Demonstrate master-detail pattern detection."""
    print("\n🔍 Master-Detail Pattern Detection")
    print("=" * 50)
    
    tables = ['companies', 'projects', 'tasks']
    
    for table in tables:
        print(f"\n📋 Analyzing {table} for master-detail patterns...")
        patterns = inspector.analyze_master_detail_patterns(table)
        
        if patterns:
            print(f"   Found {len(patterns)} master-detail pattern(s):")
            for pattern in patterns:
                print(f"   • {pattern.parent_table} → {pattern.child_table}")
                print(f"     Layout: {pattern.child_form_layout}")
                print(f"     Expected child count: {pattern.expected_child_count}")
                print(f"     Inline suitable: {pattern.is_suitable_for_inline}")
                print(f"     Child fields: {', '.join(pattern.child_display_fields)}")
        else:
            print("   No master-detail patterns found")


def demonstrate_relationship_views(inspector: EnhancedDatabaseInspector):
    """Demonstrate relationship view detection."""
    print("\n🔗 Relationship View Detection")
    print("=" * 50)
    
    tables = ['companies', 'employees', 'projects', 'invoices']
    
    for table in tables:
        print(f"\n📊 Analyzing {table} for relationship views...")
        variations = inspector.get_relationship_view_variations(table)
        
        for view_type, views in variations.items():
            if views:
                print(f"   {view_type}: {len(views)} view(s)")
                for view in views[:3]:  # Show first 3
                    print(f"     • {view}")


def demonstrate_view_generation(inspector: EnhancedDatabaseInspector, output_dir: str):
    """Demonstrate complete view generation."""
    print("\n🎨 View Generation")
    print("=" * 50)
    
    # Configure generation with all new features enabled
    config = ViewGenerationConfig(
        # Standard views
        use_modern_widgets=True,
        generate_api_views=True,
        generate_chart_views=True,
        generate_calendar_views=True,
        
        # NEW: Enhanced relationship views
        generate_master_detail_views=True,
        generate_lookup_views=True,
        generate_reference_views=True,
        generate_relationship_views=True,
        
        # NEW: Inline formsets
        enable_inline_formsets=True,
        max_inline_forms=50,
        inline_form_layouts=['stacked', 'tabular', 'accordion'],
        
        # Other options
        enable_real_time=True,
        theme='modern'
    )
    
    print("⚙️ Configuration:")
    print(f"   • Master-detail views: {config.generate_master_detail_views}")
    print(f"   • Lookup views: {config.generate_lookup_views}")
    print(f"   • Reference views: {config.generate_reference_views}")
    print(f"   • Relationship views: {config.generate_relationship_views}")
    print(f"   • Inline formsets: {config.enable_inline_formsets}")
    print(f"   • Max inline forms: {config.max_inline_forms}")
    print(f"   • Layouts: {', '.join(config.inline_form_layouts)}")
    
    # Create generator and generate views
    generator = BeautifulViewGenerator(inspector, config)
    
    print(f"\n🚀 Generating views to {output_dir}...")
    results = generator.generate_all_views(output_dir)
    
    # Display results
    print("\n📊 Generation Results:")
    print(f"   • Files generated: {len(results['generated_files'])}")
    print(f"   • Tables processed: {len(results['view_statistics'])}")
    
    total_views = sum(stats['view_count'] for stats in results['view_statistics'].values())
    print(f"   • Total views: {total_views}")
    
    if results['master_detail_patterns']:
        master_detail_count = sum(len(patterns) for patterns in results['master_detail_patterns'].values())
        print(f"   • Master-detail patterns: {master_detail_count}")
    
    if results['relationship_views']:
        rel_view_count = sum(
            len([v for views in variations.values() for v in views if views])
            for variations in results['relationship_views'].values()
        )
        print(f"   • Relationship views: {rel_view_count}")
    
    if results['errors']:
        print(f"   • Errors: {len(results['errors'])}")
        for error in results['errors'][:3]:  # Show first 3 errors
            print(f"     • {error}")
    
    # Show some generated files
    print(f"\n📁 Generated files (showing first 10):")
    for file_path in results['generated_files'][:10]:
        rel_path = os.path.relpath(file_path, output_dir)
        print(f"   • {rel_path}")
    
    if len(results['generated_files']) > 10:
        print(f"   ... and {len(results['generated_files']) - 10} more files")


def main():
    """Main demonstration function."""
    print("🌟 PgAppForge Enhanced View Generation Demo")
    print("=" * 60)
    
    # Parse command line arguments
    if len(sys.argv) >= 2:
        db_uri = sys.argv[1]
        create_db = False
    else:
        db_uri = "sqlite:///demo.db"
        create_db = True
        print("No database URI provided, creating demo SQLite database...")
    
    if len(sys.argv) >= 3:
        output_dir = sys.argv[2]
    else:
        output_dir = tempfile.mkdtemp(prefix="fab_views_")
        print(f"No output directory provided, using temporary directory: {output_dir}")
    
    try:
        # Create demo database if needed
        if create_db:
            engine = create_demo_database(db_uri)
        
        # Initialize enhanced inspector
        with EnhancedDatabaseInspector(db_uri) as inspector:
            print(f"🔗 Connected to database: {db_uri}")
            
            # Get basic database info
            tables = inspector.get_all_tables()
            print(f"📊 Found {len(tables)} tables: {', '.join(tables)}")
            
            # Demonstrate master-detail detection
            demonstrate_master_detail_detection(inspector)
            
            # Demonstrate relationship views
            demonstrate_relationship_views(inspector)
            
            # Demonstrate view generation
            demonstrate_view_generation(inspector, output_dir)
        
        print("\n✨ Demo completed successfully!")
        print(f"📂 Generated files are available in: {output_dir}")
        
        # Show next steps
        print("\n📋 Next Steps:")
        print("   1. Review the generated view files")
        print("   2. Copy templates to your PgAppForge templates directory")
        print("   3. Import and register views in your Flask app")
        print("   4. Test the master-detail forms with inline formsets")
        print("   5. Explore relationship navigation views")
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()