"""
Migration Tools for Mixin Integration

This module provides tools for migrating existing Flask-AppBuilder applications
to use enhanced mixins, including database migrations, data migration, and
configuration updates.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Type, Tuple
from datetime import datetime
from flask import current_app
from flask_appbuilder import AppBuilder
from sqlalchemy import text, inspect, MetaData, Table, Column
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

log = logging.getLogger(__name__)


class MigrationHelper:
    """
    Helper class for migrating Flask-AppBuilder applications to use enhanced mixins.
    """
    
    def __init__(self, app=None, appbuilder=None):
        self.app = app or current_app
        self.appbuilder = appbuilder or self.app.appbuilder
        self.db = self.appbuilder.get_session
        
    def analyze_current_models(self) -> Dict[str, Any]:
        """
        Analyze current models to determine what mixins can be applied.
        
        Returns:
            Analysis report with recommendations
        """
        analysis = {
            'models': {},
            'recommendations': [],
            'potential_issues': [],
            'migration_steps': []
        }
        
        try:
            # Get all registered models
            for view in self.appbuilder.baseviews:
                if hasattr(view, 'datamodel') and view.datamodel:
                    model_class = view.datamodel.obj
                    model_analysis = self._analyze_model(model_class)
                    analysis['models'][model_class.__name__] = model_analysis
            
            # Generate recommendations
            analysis['recommendations'] = self._generate_recommendations(analysis['models'])
            
            # Identify potential issues
            analysis['potential_issues'] = self._identify_migration_issues(analysis['models'])
            
            # Generate migration steps
            analysis['migration_steps'] = self._generate_migration_steps(analysis['models'])
            
        except Exception as e:
            log.error(f"Failed to analyze current models: {e}")
            analysis['error'] = str(e)
        
        return analysis
    
    def _analyze_model(self, model_class) -> Dict[str, Any]:
        """Analyze a single model for mixin compatibility."""
        analysis = {
            'current_mixins': [],
            'missing_columns': {},
            'recommended_mixins': [],
            'compatibility_score': 0
        }
        
        try:
            # Check current mixins
            for base in model_class.__mro__:
                if 'Mixin' in base.__name__:
                    analysis['current_mixins'].append(base.__name__)
            
            # Check columns
            inspector = inspect(model_class)
            columns = {col.name: str(col.type) for col in inspector.columns}
            
            # Analyze for BaseModelMixin compatibility
            if self._has_audit_columns(columns):
                analysis['recommended_mixins'].append('BaseModelMixin')
                analysis['compatibility_score'] += 20
            
            # Analyze for SoftDeleteMixin compatibility
            if 'is_deleted' in columns:
                analysis['recommended_mixins'].append('SoftDeleteMixin')
                analysis['compatibility_score'] += 15
            
            # Analyze for VersioningMixin compatibility
            if 'version' in columns:
                analysis['recommended_mixins'].append('VersioningMixin')
                analysis['compatibility_score'] += 15
            
            # Analyze for SearchableMixin compatibility
            text_columns = [name for name, type_str in columns.items() 
                          if 'TEXT' in type_str.upper() or 'VARCHAR' in type_str.upper()]
            if len(text_columns) >= 2:
                analysis['recommended_mixins'].append('SearchableMixin')
                analysis['compatibility_score'] += 10
            
            # Analyze for MetadataMixin compatibility
            if any('json' in name.lower() or 'metadata' in name.lower() for name in columns):
                analysis['recommended_mixins'].append('MetadataMixin')
                analysis['compatibility_score'] += 10
            
            # Check for missing columns that would need to be added
            analysis['missing_columns'] = self._get_missing_columns(model_class, analysis['recommended_mixins'])
            
        except Exception as e:
            log.warning(f"Failed to analyze model {model_class.__name__}: {e}")
            analysis['error'] = str(e)
        
        return analysis
    
    def _has_audit_columns(self, columns: Dict[str, str]) -> bool:
        """Check if model has audit columns."""
        audit_columns = ['created_on', 'changed_on', 'created_by_fk', 'changed_by_fk']
        return any(col in columns for col in audit_columns)
    
    def _get_missing_columns(self, model_class, recommended_mixins: List[str]) -> Dict[str, List[str]]:
        """Get columns that would need to be added for recommended mixins."""
        missing = {}
        
        inspector = inspect(model_class)
        existing_columns = {col.name for col in inspector.columns}
        
        mixin_columns = {
            'BaseModelMixin': ['created_on', 'changed_on', 'created_by_fk', 'changed_by_fk', 
                             'is_deleted', 'deleted_at', 'version', 'completion_percentage'],
            'SoftDeleteMixin': ['is_deleted', 'deleted_at'],
            'VersioningMixin': ['version'],
            'SearchableMixin': ['search_vector'],
            'MetadataMixin': ['metadata'],
            'AuditLogMixin': ['audit_context', 'audit_source'],
            'WorkflowMixin': ['current_state', 'state_history'],
            'SchedulingMixin': ['start_time', 'end_time', 'timezone', 'recurrence_pattern'],
            'GeoLocationMixin': ['latitude', 'longitude', 'location'],
            'SlugMixin': ['slug'],
            'InternationalizationMixin': ['locale'],
            'MultiTenancyMixin': ['tenant_id']
        }
        
        for mixin in recommended_mixins:
            if mixin in mixin_columns:
                required_columns = mixin_columns[mixin]
                missing_columns = [col for col in required_columns if col not in existing_columns]
                if missing_columns:
                    missing[mixin] = missing_columns
        
        return missing
    
    def _generate_recommendations(self, models_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate migration recommendations based on model analysis."""
        recommendations = []
        
        for model_name, analysis in models_analysis.items():
            if analysis.get('compatibility_score', 0) > 30:
                recommendations.append({
                    'type': 'high_priority',
                    'model': model_name,
                    'mixins': analysis.get('recommended_mixins', []),
                    'reason': 'High compatibility score suggests easy migration',
                    'estimated_effort': 'Low'
                })
            elif analysis.get('compatibility_score', 0) > 15:
                recommendations.append({
                    'type': 'medium_priority',
                    'model': model_name,
                    'mixins': analysis.get('recommended_mixins', []),
                    'reason': 'Partial compatibility with some missing columns',
                    'estimated_effort': 'Medium'
                })
        
        # Add general recommendations
        recommendations.append({
            'type': 'general',
            'recommendation': 'Start with BaseModelMixin for all models to get audit functionality',
            'estimated_effort': 'Low'
        })
        
        return recommendations
    
    def _identify_migration_issues(self, models_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify potential issues with migration."""
        issues = []
        
        for model_name, analysis in models_analysis.items():
            missing_columns = analysis.get('missing_columns', {})
            
            for mixin, columns in missing_columns.items():
                if len(columns) > 5:
                    issues.append({
                        'type': 'schema_change',
                        'severity': 'medium',
                        'model': model_name,
                        'mixin': mixin,
                        'issue': f'Requires adding {len(columns)} new columns',
                        'columns': columns
                    })
                
                if 'foreign_key' in str(columns).lower():
                    issues.append({
                        'type': 'foreign_key',
                        'severity': 'high',
                        'model': model_name,
                        'mixin': mixin,
                        'issue': 'Requires foreign key relationships',
                        'action': 'Manual review of relationships required'
                    })
        
        return issues
    
    def _generate_migration_steps(self, models_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate step-by-step migration plan."""
        steps = [
            {
                'step': 1,
                'title': 'Backup Database',
                'description': 'Create full database backup before migration',
                'command': 'pg_dump -U username -h host database > backup.sql',
                'required': True
            },
            {
                'step': 2,
                'title': 'Install Enhanced Mixins',
                'description': 'Ensure enhanced mixin package is installed',
                'command': 'pip install flask-appbuilder[mfa,export,analytics]',
                'required': True
            },
            {
                'step': 3,
                'title': 'Generate Migration Scripts',
                'description': 'Create Alembic migration scripts for schema changes',
                'command': 'flask db migrate -m "Add mixin columns"',
                'required': True
            },
            {
                'step': 4,
                'title': 'Review Migration Scripts',
                'description': 'Manually review generated migration scripts',
                'action': 'manual_review',
                'required': True
            },
            {
                'step': 5,
                'title': 'Apply Database Migrations',
                'description': 'Apply schema changes to database',
                'command': 'flask db upgrade',
                'required': True
            },
            {
                'step': 6,
                'title': 'Update Model Classes',
                'description': 'Add mixin inheritance to model classes',
                'action': 'code_changes',
                'required': True
            },
            {
                'step': 7,
                'title': 'Test Application',
                'description': 'Run comprehensive tests after migration',
                'action': 'testing',
                'required': True
            }
        ]
        
        return steps
    
    def generate_migration_script(self, model_class, mixins: List[str]) -> str:
        """
        Generate Alembic migration script for adding mixin columns.
        
        Args:
            model_class: The model class to migrate
            mixins: List of mixin names to add
            
        Returns:
            Migration script content
        """
        table_name = model_class.__tablename__
        
        script_template = '''"""Add mixin columns to {table_name}

Revision ID: {revision_id}
Revises: 
Create Date: {create_date}

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '{revision_id}'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    """Add mixin columns."""
{upgrade_operations}

def downgrade():
    """Remove mixin columns."""
{downgrade_operations}
'''
        
        revision_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        create_date = datetime.now().isoformat()
        
        upgrade_ops = []
        downgrade_ops = []
        
        # Generate operations for each mixin
        missing_columns = self._get_missing_columns(model_class, mixins)
        
        for mixin, columns in missing_columns.items():
            for column in columns:
                column_def = self._get_column_definition(column, mixin)
                if column_def:
                    upgrade_ops.append(f"    op.add_column('{table_name}', {column_def})")
                    downgrade_ops.append(f"    op.drop_column('{table_name}', '{column}')")
        
        upgrade_operations = '\n'.join(upgrade_ops) if upgrade_ops else '    pass'
        downgrade_operations = '\n'.join(downgrade_ops) if downgrade_ops else '    pass'
        
        return script_template.format(
            table_name=table_name,
            revision_id=revision_id,
            create_date=create_date,
            upgrade_operations=upgrade_operations,
            downgrade_operations=downgrade_operations
        )
    
    def _get_column_definition(self, column_name: str, mixin: str) -> Optional[str]:
        """Get SQLAlchemy column definition for mixin columns."""
        column_definitions = {
            # BaseModelMixin columns
            'created_on': "sa.Column('created_on', sa.DateTime(), nullable=True)",
            'changed_on': "sa.Column('changed_on', sa.DateTime(), nullable=True)",
            'created_by_fk': "sa.Column('created_by_fk', sa.Integer(), nullable=True)",
            'changed_by_fk': "sa.Column('changed_by_fk', sa.Integer(), nullable=True)",
            'is_deleted': "sa.Column('is_deleted', sa.Boolean(), default=False)",
            'deleted_at': "sa.Column('deleted_at', sa.DateTime(), nullable=True)",
            'version': "sa.Column('version', sa.Integer(), default=1)",
            'completion_percentage': "sa.Column('completion_percentage', sa.Integer(), default=0)",
            
            # SearchableMixin columns
            'search_vector': "sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True)",
            
            # MetadataMixin columns
            'metadata': "sa.Column('metadata', sa.Text(), nullable=True)",
            
            # WorkflowMixin columns
            'current_state': "sa.Column('current_state', sa.String(50), nullable=True)",
            'state_history': "sa.Column('state_history', sa.Text(), nullable=True)",
            
            # SchedulingMixin columns
            'start_time': "sa.Column('start_time', sa.DateTime(), nullable=True)",
            'end_time': "sa.Column('end_time', sa.DateTime(), nullable=True)",
            'timezone': "sa.Column('timezone', sa.String(50), nullable=True)",
            'recurrence_pattern': "sa.Column('recurrence_pattern', sa.Text(), nullable=True)",
            
            # GeoLocationMixin columns
            'latitude': "sa.Column('latitude', sa.Float(), nullable=True)",
            'longitude': "sa.Column('longitude', sa.Float(), nullable=True)",
            'location': "sa.Column('location', postgresql.GEOMETRY('POINT'), nullable=True)",
            
            # Other mixin columns
            'slug': "sa.Column('slug', sa.String(100), nullable=True, unique=True)",
            'tenant_id': "sa.Column('tenant_id', sa.String(50), nullable=True)",
            'locale': "sa.Column('locale', sa.String(10), nullable=True)",
            'audit_context': "sa.Column('audit_context', sa.String(255), nullable=True)",
            'audit_source': "sa.Column('audit_source', sa.String(50), nullable=True)"
        }
        
        return column_definitions.get(column_name)
    
    def migrate_data(self, model_class, mixin: str) -> bool:
        """
        Migrate existing data to work with new mixin columns.
        
        Args:
            model_class: The model class
            mixin: The mixin being added
            
        Returns:
            True if migration successful, False otherwise
        """
        try:
            table_name = model_class.__tablename__
            
            if mixin == 'BaseModelMixin':
                # Set default values for audit columns
                self.db.execute(text(f"""
                    UPDATE {table_name} 
                    SET created_on = COALESCE(created_on, NOW()),
                        changed_on = COALESCE(changed_on, NOW()),
                        is_deleted = COALESCE(is_deleted, FALSE),
                        version = COALESCE(version, 1),
                        completion_percentage = COALESCE(completion_percentage, 0)
                """))
            
            elif mixin == 'SlugMixin':
                # Generate slugs for existing records
                records = self.db.query(model_class).all()
                for record in records:
                    if hasattr(record, 'create_slug') and not getattr(record, 'slug', None):
                        record.create_slug()
            
            elif mixin == 'SearchableMixin':
                # Update search vectors
                records = self.db.query(model_class).all()
                for record in records:
                    if hasattr(record, '_update_search_vector'):
                        record._update_search_vector()
            
            self.db.commit()
            log.info(f"Successfully migrated data for {mixin} in {model_class.__name__}")
            return True
            
        except Exception as e:
            log.error(f"Failed to migrate data for {mixin} in {model_class.__name__}: {e}")
            self.db.rollback()
            return False
    
    def validate_migration(self, model_class, mixins: List[str]) -> Dict[str, Any]:
        """
        Validate that migration completed successfully.
        
        Args:
            model_class: The model class
            mixins: List of mixins that were migrated
            
        Returns:
            Validation report
        """
        report = {
            'model': model_class.__name__,
            'mixins_validated': [],
            'issues': [],
            'success': True
        }
        
        try:
            # Check that all expected columns exist
            inspector = inspect(model_class)
            existing_columns = {col.name for col in inspector.columns}
            
            for mixin in mixins:
                expected_columns = self._get_mixin_required_columns(mixin)
                missing_columns = [col for col in expected_columns if col not in existing_columns]
                
                if missing_columns:
                    report['issues'].append({
                        'mixin': mixin,
                        'type': 'missing_columns',
                        'columns': missing_columns
                    })
                    report['success'] = False
                else:
                    report['mixins_validated'].append(mixin)
            
            # Check data integrity
            sample_count = min(10, self.db.query(model_class).count())
            if sample_count > 0:
                sample_records = self.db.query(model_class).limit(sample_count).all()
                
                for record in sample_records:
                    if hasattr(record, 'created_on') and not record.created_on:
                        report['issues'].append({
                            'type': 'data_integrity',
                            'issue': 'Missing created_on values'
                        })
                        break
        
        except Exception as e:
            report['issues'].append({
                'type': 'validation_error',
                'error': str(e)
            })
            report['success'] = False
        
        return report
    
    def _get_mixin_required_columns(self, mixin: str) -> List[str]:
        """Get required columns for a mixin."""
        required_columns = {
            'BaseModelMixin': ['created_on', 'changed_on', 'is_deleted', 'version'],
            'SoftDeleteMixin': ['is_deleted', 'deleted_at'],
            'VersioningMixin': ['version'],
            'SearchableMixin': ['search_vector'],
            'MetadataMixin': ['metadata'],
            'WorkflowMixin': ['current_state'],
            'SchedulingMixin': ['start_time', 'end_time'],
            'GeoLocationMixin': ['latitude', 'longitude'],
            'SlugMixin': ['slug'],
            'MultiTenancyMixin': ['tenant_id'],
            'InternationalizationMixin': ['locale']
        }
        
        return required_columns.get(mixin, [])
    
    def generate_migration_report(self, output_file: str = None) -> Dict[str, Any]:
        """
        Generate comprehensive migration report.
        
        Args:
            output_file: Optional file to save report
            
        Returns:
            Complete migration report
        """
        report = {
            'timestamp': datetime.now().isoformat(),
            'analysis': self.analyze_current_models(),
            'migration_ready': True,
            'estimated_duration': '2-4 hours',
            'risk_level': 'medium'
        }
        
        # Calculate overall risk and readiness
        issues = report['analysis'].get('potential_issues', [])
        high_risk_issues = [i for i in issues if i.get('severity') == 'high']
        
        if high_risk_issues:
            report['risk_level'] = 'high'
            report['estimated_duration'] = '1-2 days'
        elif len(issues) > 10:
            report['risk_level'] = 'high'
            report['estimated_duration'] = '4-8 hours'
        
        # Save report if requested
        if output_file:
            try:
                with open(output_file, 'w') as f:
                    json.dump(report, f, indent=2, default=str)
                log.info(f"Migration report saved to {output_file}")
            except Exception as e:
                log.error(f"Failed to save migration report: {e}")
        
        return report


def create_migration_plan(app, output_dir: str = None) -> str:
    """
    Create a complete migration plan for an application.
    
    Args:
        app: Flask application instance
        output_dir: Directory to save migration files
        
    Returns:
        Path to migration plan directory
    """
    if not output_dir:
        output_dir = os.path.join(app.instance_path, 'mixin_migration')
    
    os.makedirs(output_dir, exist_ok=True)
    
    helper = MigrationHelper(app)
    
    # Generate migration report
    report = helper.generate_migration_report(
        os.path.join(output_dir, 'migration_report.json')
    )
    
    # Generate migration scripts for each model
    for model_name, analysis in report['analysis']['models'].items():
        recommended_mixins = analysis.get('recommended_mixins', [])
        if recommended_mixins:
            try:
                # Find the actual model class
                model_class = None
                for view in app.appbuilder.baseviews:
                    if (hasattr(view, 'datamodel') and view.datamodel and 
                        view.datamodel.obj.__name__ == model_name):
                        model_class = view.datamodel.obj
                        break
                
                if model_class:
                    script_content = helper.generate_migration_script(model_class, recommended_mixins)
                    script_file = os.path.join(output_dir, f'migrate_{model_name.lower()}.py')
                    
                    with open(script_file, 'w') as f:
                        f.write(script_content)
            
            except Exception as e:
                log.error(f"Failed to generate migration script for {model_name}: {e}")
    
    # Generate README with instructions
    readme_content = f"""# Mixin Migration Plan

This directory contains the migration plan and scripts for integrating enhanced mixins into your Flask-AppBuilder application.

## Migration Overview

- **Risk Level**: {report['risk_level'].upper()}
- **Estimated Duration**: {report['estimated_duration']}
- **Models to Migrate**: {len(report['analysis']['models'])}

## Files

- `migration_report.json`: Detailed analysis and recommendations
- `migrate_*.py`: Alembic migration scripts for each model

## Migration Steps

1. **Backup Database**: Create a full backup before starting
2. **Review Report**: Read the migration_report.json thoroughly
3. **Test Environment**: Run migration on a test environment first
4. **Apply Migrations**: Use the generated scripts with Alembic
5. **Update Code**: Add mixin inheritance to model classes
6. **Validate**: Test all functionality after migration

## Support

For issues or questions, refer to the Flask-AppBuilder enhanced mixins documentation.

Generated: {datetime.now().isoformat()}
"""
    
    with open(os.path.join(output_dir, 'README.md'), 'w') as f:
        f.write(readme_content)
    
    log.info(f"Migration plan created in {output_dir}")
    return output_dir


__all__ = [
    'MigrationHelper',
    'create_migration_plan'
]