"""
Web API for Visual IDE.

RESTful API endpoints for the visual development environment,
providing web-based access to all IDE functionality.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import Blueprint, request, jsonify, send_file, abort
from werkzeug.exceptions import BadRequest, NotFound, InternalServerError
from dataclasses import asdict
from datetime import datetime

from ..core.ide_engine import VisualIDEEngine, IDEConfiguration
from ..models.project_model import (
    ViewDefinition, ViewType, ComponentConfig, ComponentType, IDEProject
)
from ..components.component_library import ComponentLibrary
from ..preview.live_preview import LivePreviewEngine, PreviewConfiguration

logger = logging.getLogger(__name__)


class IDEWebAPI:
    """
    Web API interface for the Visual IDE.
    
    Provides RESTful endpoints for:
    - Project management
    - View creation and editing
    - Component library access
    - Live preview control
    - File operations
    - Code generation
    """
    
    def __init__(self, ide_engine: VisualIDEEngine):
        self.ide_engine = ide_engine
        self.blueprint = Blueprint('visual_ide_api', __name__, url_prefix='/api/visual-ide')
        self._setup_routes()
        
        logger.info("Visual IDE Web API initialized")
    
    def _setup_routes(self):
        """Setup all API routes."""
        
        # Project routes
        self.blueprint.add_url_rule('/project', 'get_project', self.get_project, methods=['GET'])
        self.blueprint.add_url_rule('/project', 'update_project', self.update_project, methods=['PUT'])
        self.blueprint.add_url_rule('/project/export', 'export_project', self.export_project, methods=['POST'])
        self.blueprint.add_url_rule('/project/import', 'import_project', self.import_project, methods=['POST'])
        self.blueprint.add_url_rule('/project/status', 'get_project_status', self.get_project_status, methods=['GET'])
        
        # View routes
        self.blueprint.add_url_rule('/views', 'list_views', self.list_views, methods=['GET'])
        self.blueprint.add_url_rule('/views', 'create_view', self.create_view, methods=['POST'])
        self.blueprint.add_url_rule('/views/<view_name>', 'get_view', self.get_view, methods=['GET'])
        self.blueprint.add_url_rule('/views/<view_name>', 'update_view', self.update_view, methods=['PUT'])
        self.blueprint.add_url_rule('/views/<view_name>', 'delete_view', self.delete_view, methods=['DELETE'])
        self.blueprint.add_url_rule('/views/<view_name>/duplicate', 'duplicate_view', self.duplicate_view, methods=['POST'])
        
        # Component routes
        self.blueprint.add_url_rule('/views/<view_name>/components', 'list_view_components', self.list_view_components, methods=['GET'])
        self.blueprint.add_url_rule('/views/<view_name>/components', 'add_component', self.add_component, methods=['POST'])
        self.blueprint.add_url_rule('/views/<view_name>/components/<component_id>', 'get_component', self.get_component, methods=['GET'])
        self.blueprint.add_url_rule('/views/<view_name>/components/<component_id>', 'update_component', self.update_component, methods=['PUT'])
        self.blueprint.add_url_rule('/views/<view_name>/components/<component_id>', 'delete_component', self.delete_component, methods=['DELETE'])
        self.blueprint.add_url_rule('/views/<view_name>/components/<component_id>/move', 'move_component', self.move_component, methods=['PUT'])
        self.blueprint.add_url_rule('/views/<view_name>/components/<component_id>/duplicate', 'duplicate_component', self.duplicate_component, methods=['POST'])
        
        # Component library routes
        self.blueprint.add_url_rule('/components/library', 'get_component_library', self.get_component_library, methods=['GET'])
        self.blueprint.add_url_rule('/components/library/<component_type>', 'get_component_template', self.get_component_template, methods=['GET'])
        self.blueprint.add_url_rule('/components/search', 'search_components', self.search_components, methods=['GET'])
        self.blueprint.add_url_rule('/components/categories', 'get_component_categories', self.get_component_categories, methods=['GET'])
        
        # Code generation routes
        self.blueprint.add_url_rule('/generate/view/<view_name>', 'generate_view_code', self.generate_view_code, methods=['POST'])
        self.blueprint.add_url_rule('/generate/application', 'generate_application', self.generate_application, methods=['POST'])
        self.blueprint.add_url_rule('/generated-files', 'list_generated_files', self.list_generated_files, methods=['GET'])
        self.blueprint.add_url_rule('/generated-files/<path:file_path>', 'get_generated_file', self.get_generated_file, methods=['GET'])
        
        # Preview routes
        self.blueprint.add_url_rule('/preview/status', 'get_preview_status', self.get_preview_status, methods=['GET'])
        self.blueprint.add_url_rule('/preview/start', 'start_preview', self.start_preview, methods=['POST'])
        self.blueprint.add_url_rule('/preview/stop', 'stop_preview', self.stop_preview, methods=['POST'])
        self.blueprint.add_url_rule('/preview/url', 'get_preview_url', self.get_preview_url, methods=['GET'])
        
        # File management routes
        self.blueprint.add_url_rule('/files', 'list_files', self.list_files, methods=['GET'])
        self.blueprint.add_url_rule('/files', 'save_file', self.save_file, methods=['POST'])
        self.blueprint.add_url_rule('/files/<path:file_path>', 'get_file', self.get_file, methods=['GET'])
        self.blueprint.add_url_rule('/files/<path:file_path>', 'delete_file', self.delete_file, methods=['DELETE'])
        self.blueprint.add_url_rule('/files/<path:file_path>/versions', 'get_file_versions', self.get_file_versions, methods=['GET'])
        
        # Backup routes
        self.blueprint.add_url_rule('/backups', 'list_backups', self.list_backups, methods=['GET'])
        self.blueprint.add_url_rule('/backups', 'create_backup', self.create_backup, methods=['POST'])
        self.blueprint.add_url_rule('/backups/<backup_id>', 'restore_backup', self.restore_backup, methods=['POST'])
        self.blueprint.add_url_rule('/backups/<backup_id>', 'delete_backup', self.delete_backup, methods=['DELETE'])
    
    # Utility methods
    def _handle_error(self, error_msg: str, status_code: int = 400):
        """Handle API errors consistently."""
        logger.error(error_msg)
        return jsonify({'error': error_msg}), status_code
    
    def _serialize_datetime(self, obj):
        """Serialize datetime objects to ISO format."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
    
    def _validate_json_request(self, required_fields: List[str] = None):
        """Validate JSON request data."""
        if not request.is_json:
            abort(400, description="Request must be JSON")
        
        data = request.get_json()
        if not data:
            abort(400, description="Invalid JSON data")
        
        if required_fields:
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                abort(400, description=f"Missing required fields: {', '.join(missing_fields)}")
        
        return data
    
    # Project API endpoints
    def get_project(self):
        """Get current project information."""
        try:
            status = self.ide_engine.get_project_status()
            return jsonify(status)
        except Exception as e:
            return self._handle_error(f"Failed to get project: {e}", 500)
    
    def update_project(self):
        """Update project configuration."""
        try:
            data = self._validate_json_request(['name'])
            
            if self.ide_engine.current_project:
                self.ide_engine.current_project.name = data['name']
                if 'description' in data:
                    self.ide_engine.current_project.description = data['description']
                if 'flask_config' in data:
                    self.ide_engine.current_project.flask_config.update(data['flask_config'])
                if 'database_config' in data:
                    self.ide_engine.current_project.database_config.update(data['database_config'])
                if 'security_config' in data:
                    self.ide_engine.current_project.security_config.update(data['security_config'])
                
                self.ide_engine._save_project()
                
                return jsonify({'message': 'Project updated successfully'})
            else:
                return self._handle_error("No active project", 404)
                
        except Exception as e:
            return self._handle_error(f"Failed to update project: {e}", 500)
    
    def export_project(self):
        """Export project to specified path."""
        try:
            data = self._validate_json_request(['export_path'])
            export_path = data['export_path']
            
            success = self.ide_engine.export_project(export_path)
            if success:
                return jsonify({'message': f'Project exported to {export_path}'})
            else:
                return self._handle_error("Failed to export project", 500)
                
        except Exception as e:
            return self._handle_error(f"Export failed: {e}", 500)
    
    def import_project(self):
        """Import project from specified path."""
        try:
            data = self._validate_json_request(['import_path'])
            import_path = data['import_path']
            
            success = self.ide_engine.import_project(import_path)
            if success:
                return jsonify({'message': f'Project imported from {import_path}'})
            else:
                return self._handle_error("Failed to import project", 500)
                
        except Exception as e:
            return self._handle_error(f"Import failed: {e}", 500)
    
    def get_project_status(self):
        """Get detailed project status."""
        try:
            status = self.ide_engine.get_project_status()
            return jsonify(status)
        except Exception as e:
            return self._handle_error(f"Failed to get project status: {e}", 500)
    
    # View API endpoints
    def list_views(self):
        """List all views in the project."""
        try:
            views_data = {}
            for view_name, view_def in self.ide_engine.active_views.items():
                views_data[view_name] = {
                    'name': view_def.name,
                    'view_type': view_def.view_type.value,
                    'model_name': view_def.model_name,
                    'components_count': len(view_def.components),
                    'created_at': view_def.created_at.isoformat(),
                    'modified_at': view_def.modified_at.isoformat(),
                    'description': view_def.description,
                    'tags': view_def.tags
                }
            
            return jsonify({'views': views_data})
            
        except Exception as e:
            return self._handle_error(f"Failed to list views: {e}", 500)
    
    def create_view(self):
        """Create a new view."""
        try:
            data = self._validate_json_request(['name'])
            
            view_name = data['name']
            view_type = data.get('view_type', 'ModelView')
            model_name = data.get('model_name')
            
            view_def = self.ide_engine.create_view(view_name, view_type, model_name)
            
            return jsonify({
                'message': f'View {view_name} created successfully',
                'view': view_def.to_dict()
            }), 201
            
        except Exception as e:
            return self._handle_error(f"Failed to create view: {e}", 500)
    
    def get_view(self, view_name: str):
        """Get a specific view."""
        try:
            view_def = self.ide_engine.edit_view(view_name)
            return jsonify({'view': view_def.to_dict()})
            
        except ValueError as e:
            return self._handle_error(str(e), 404)
        except Exception as e:
            return self._handle_error(f"Failed to get view: {e}", 500)
    
    def update_view(self, view_name: str):
        """Update a view configuration."""
        try:
            data = self._validate_json_request()
            
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            view_def = self.ide_engine.active_views[view_name]
            
            # Update view properties
            if 'description' in data:
                view_def.description = data['description']
            if 'tags' in data:
                view_def.tags = data['tags']
            if 'list_columns' in data:
                view_def.list_columns = data['list_columns']
            if 'show_columns' in data:
                view_def.show_columns = data['show_columns']
            if 'add_columns' in data:
                view_def.add_columns = data['add_columns']
            if 'edit_columns' in data:
                view_def.edit_columns = data['edit_columns']
            if 'search_columns' in data:
                view_def.search_columns = data['search_columns']
            if 'enable_api' in data:
                view_def.enable_api = data['enable_api']
            
            view_def.modified_at = datetime.now()
            
            # Update live preview
            if self.ide_engine.live_preview:
                self.ide_engine.live_preview.update_view(view_name, view_def)
            
            return jsonify({'message': f'View {view_name} updated successfully'})
            
        except Exception as e:
            return self._handle_error(f"Failed to update view: {e}", 500)
    
    def delete_view(self, view_name: str):
        """Delete a view."""
        try:
            success = self.ide_engine.delete_view(view_name)
            if success:
                return jsonify({'message': f'View {view_name} deleted successfully'})
            else:
                return self._handle_error(f"Failed to delete view {view_name}", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to delete view: {e}", 500)
    
    def duplicate_view(self, view_name: str):
        """Duplicate a view."""
        try:
            data = self._validate_json_request(['new_name'])
            new_name = data['new_name']
            
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            original_view = self.ide_engine.active_views[view_name]
            
            # Create duplicate
            new_view = ViewDefinition.from_dict(original_view.to_dict())
            new_view.name = new_name
            new_view.created_at = datetime.now()
            new_view.modified_at = datetime.now()
            
            # Add to active views
            self.ide_engine.active_views[new_name] = new_view
            
            if self.ide_engine.current_project:
                self.ide_engine.current_project.views[new_name] = new_view
                self.ide_engine._save_project()
            
            return jsonify({
                'message': f'View duplicated as {new_name}',
                'view': new_view.to_dict()
            }), 201
            
        except Exception as e:
            return self._handle_error(f"Failed to duplicate view: {e}", 500)
    
    # Component API endpoints
    def list_view_components(self, view_name: str):
        """List all components in a view."""
        try:
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            view_def = self.ide_engine.active_views[view_name]
            
            components_data = {}
            for comp_id, component in view_def.components.items():
                components_data[comp_id] = {
                    'component_id': component.component_id,
                    'component_type': component.component_type.value,
                    'label': component.label,
                    'position': {
                        'x': component.position.x,
                        'y': component.position.y,
                        'width': component.position.width,
                        'height': component.position.height,
                        'row': component.position.row,
                        'column': component.position.column,
                        'span': component.position.span
                    },
                    'children': component.children,
                    'properties': component.properties
                }
            
            return jsonify({
                'components': components_data,
                'root_components': view_def.root_components
            })
            
        except Exception as e:
            return self._handle_error(f"Failed to list components: {e}", 500)
    
    def add_component(self, view_name: str):
        """Add a component to a view."""
        try:
            data = self._validate_json_request(['component_type'])
            
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            component_type = ComponentType(data['component_type'])
            config = data.get('config', {})
            parent_id = data.get('parent_id')
            
            template = self.ide_engine.component_library.get_component(component_type)
            if not template:
                return self._handle_error(f"Unknown component type: {component_type}", 400)
            
            view_def = self.ide_engine.active_views[view_name]
            success = self.ide_engine.add_component_to_view(view_name, component_type.value, config)
            
            if success:
                # Update live preview
                if self.ide_engine.live_preview:
                    self.ide_engine.live_preview.update_view(view_name, view_def)
                
                return jsonify({'message': 'Component added successfully'}), 201
            else:
                return self._handle_error("Failed to add component", 500)
                
        except ValueError as e:
            return self._handle_error(f"Invalid component type: {e}", 400)
        except Exception as e:
            return self._handle_error(f"Failed to add component: {e}", 500)
    
    def get_component(self, view_name: str, component_id: str):
        """Get a specific component."""
        try:
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            view_def = self.ide_engine.active_views[view_name]
            component = view_def.get_component(component_id)
            
            if not component:
                return self._handle_error(f"Component {component_id} not found", 404)
            
            return jsonify({'component': component.to_dict()})
            
        except Exception as e:
            return self._handle_error(f"Failed to get component: {e}", 500)
    
    def update_component(self, view_name: str, component_id: str):
        """Update a component configuration."""
        try:
            data = self._validate_json_request()
            
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            view_def = self.ide_engine.active_views[view_name]
            component = view_def.get_component(component_id)
            
            if not component:
                return self._handle_error(f"Component {component_id} not found", 404)
            
            # Update component properties
            if 'label' in data:
                component.label = data['label']
            if 'placeholder' in data:
                component.placeholder = data['placeholder']
            if 'properties' in data:
                component.properties.update(data['properties'])
            if 'style' in data:
                if 'css_classes' in data['style']:
                    component.style.css_classes = data['style']['css_classes']
                if 'custom_css' in data['style']:
                    component.style.custom_css.update(data['style']['custom_css'])
            if 'validation' in data:
                if 'required' in data['validation']:
                    component.validation.required = data['validation']['required']
            
            view_def.modified_at = datetime.now()
            
            # Update live preview
            if self.ide_engine.live_preview:
                self.ide_engine.live_preview.update_view(view_name, view_def)
            
            return jsonify({'message': f'Component {component_id} updated successfully'})
            
        except Exception as e:
            return self._handle_error(f"Failed to update component: {e}", 500)
    
    def delete_component(self, view_name: str, component_id: str):
        """Delete a component from a view."""
        try:
            success = self.ide_engine.remove_component_from_view(view_name, component_id)
            if success:
                return jsonify({'message': f'Component {component_id} deleted successfully'})
            else:
                return self._handle_error(f"Failed to delete component {component_id}", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to delete component: {e}", 500)
    
    def move_component(self, view_name: str, component_id: str):
        """Move a component to a new position."""
        try:
            data = self._validate_json_request(['position'])
            
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            view_def = self.ide_engine.active_views[view_name]
            component = view_def.get_component(component_id)
            
            if not component:
                return self._handle_error(f"Component {component_id} not found", 404)
            
            # Update position
            position_data = data['position']
            if 'x' in position_data:
                component.position.x = position_data['x']
            if 'y' in position_data:
                component.position.y = position_data['y']
            if 'row' in position_data:
                component.position.row = position_data['row']
            if 'column' in position_data:
                component.position.column = position_data['column']
            if 'span' in position_data:
                component.position.span = position_data['span']
            
            view_def.modified_at = datetime.now()
            
            # Update live preview
            if self.ide_engine.live_preview:
                self.ide_engine.live_preview.update_view(view_name, view_def)
            
            return jsonify({'message': f'Component {component_id} moved successfully'})
            
        except Exception as e:
            return self._handle_error(f"Failed to move component: {e}", 500)
    
    def duplicate_component(self, view_name: str, component_id: str):
        """Duplicate a component."""
        try:
            if view_name not in self.ide_engine.active_views:
                return self._handle_error(f"View {view_name} not found", 404)
            
            view_def = self.ide_engine.active_views[view_name]
            new_component_id = self.ide_engine.view_builder.duplicate_component(view_def, component_id)
            
            if new_component_id:
                # Update live preview
                if self.ide_engine.live_preview:
                    self.ide_engine.live_preview.update_view(view_name, view_def)
                
                return jsonify({
                    'message': f'Component duplicated successfully',
                    'new_component_id': new_component_id
                }), 201
            else:
                return self._handle_error("Failed to duplicate component", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to duplicate component: {e}", 500)
    
    # Component Library API endpoints
    def get_component_library(self):
        """Get the complete component library."""
        try:
            library_data = {}
            all_components = self.ide_engine.component_library.get_all_components()
            
            for comp_type, template in all_components.items():
                library_data[comp_type.value] = {
                    'name': template.name,
                    'description': template.description,
                    'category': template.category,
                    'icon': template.icon,
                    'default_properties': template.default_properties,
                    'configurable_properties': template.configurable_properties,
                    'supported_events': template.supported_events,
                    'requires_data_source': template.requires_data_source,
                    'supports_children': template.supports_children,
                    'max_children': template.max_children
                }
            
            return jsonify({'components': library_data})
            
        except Exception as e:
            return self._handle_error(f"Failed to get component library: {e}", 500)
    
    def get_component_template(self, component_type: str):
        """Get a specific component template."""
        try:
            comp_type = ComponentType(component_type)
            template = self.ide_engine.component_library.get_component(comp_type)
            
            if not template:
                return self._handle_error(f"Component type {component_type} not found", 404)
            
            return jsonify({
                'name': template.name,
                'description': template.description,
                'category': template.category,
                'icon': template.icon,
                'default_properties': template.default_properties,
                'configurable_properties': template.configurable_properties,
                'supported_events': template.supported_events,
                'requires_data_source': template.requires_data_source,
                'supports_children': template.supports_children,
                'max_children': template.max_children,
                'template_code': template.template_code
            })
            
        except ValueError:
            return self._handle_error(f"Invalid component type: {component_type}", 400)
        except Exception as e:
            return self._handle_error(f"Failed to get component template: {e}", 500)
    
    def search_components(self):
        """Search component library."""
        try:
            query = request.args.get('q', '')
            if not query:
                return self._handle_error("Query parameter 'q' is required", 400)
            
            results = self.ide_engine.component_library.search_components(query)
            
            search_results = []
            for template in results:
                search_results.append({
                    'component_type': template.component_type.value,
                    'name': template.name,
                    'description': template.description,
                    'category': template.category,
                    'icon': template.icon
                })
            
            return jsonify({
                'query': query,
                'results': search_results,
                'count': len(search_results)
            })
            
        except Exception as e:
            return self._handle_error(f"Failed to search components: {e}", 500)
    
    def get_component_categories(self):
        """Get all component categories."""
        try:
            categories = self.ide_engine.component_library.get_categories()
            
            categories_data = {}
            for category in categories:
                components = self.ide_engine.component_library.get_components_by_category(category)
                categories_data[category] = [
                    {
                        'component_type': comp.component_type.value,
                        'name': comp.name,
                        'description': comp.description,
                        'icon': comp.icon
                    }
                    for comp in components
                ]
            
            return jsonify({'categories': categories_data})
            
        except Exception as e:
            return self._handle_error(f"Failed to get component categories: {e}", 500)
    
    # Code Generation API endpoints
    def generate_view_code(self, view_name: str):
        """Generate code for a specific view."""
        try:
            generated_files = self.ide_engine.generate_code(view_name)
            
            return jsonify({
                'message': f'Code generated for view {view_name}',
                'files': list(generated_files.keys()),
                'files_count': len(generated_files)
            })
            
        except ValueError as e:
            return self._handle_error(str(e), 404)
        except Exception as e:
            return self._handle_error(f"Failed to generate code: {e}", 500)
    
    def generate_application(self):
        """Generate complete application code."""
        try:
            generated_files = self.ide_engine.generate_full_application()
            
            return jsonify({
                'message': 'Application code generated successfully',
                'files': list(generated_files.keys()),
                'files_count': len(generated_files)
            })
            
        except Exception as e:
            return self._handle_error(f"Failed to generate application: {e}", 500)
    
    def list_generated_files(self):
        """List all generated files."""
        try:
            generated_files = self.ide_engine.code_generator.get_generated_files()
            
            files_data = {}
            for path, file_obj in generated_files.items():
                files_data[path] = {
                    'path': file_obj.path,
                    'file_type': file_obj.file_type,
                    'language': file_obj.language,
                    'size': len(file_obj.content)
                }
            
            return jsonify({'files': files_data})
            
        except Exception as e:
            return self._handle_error(f"Failed to list generated files: {e}", 500)
    
    def get_generated_file(self, file_path: str):
        """Get content of a generated file."""
        try:
            generated_files = self.ide_engine.code_generator.get_generated_files()
            
            if file_path not in generated_files:
                return self._handle_error(f"Generated file {file_path} not found", 404)
            
            file_obj = generated_files[file_path]
            
            return jsonify({
                'path': file_obj.path,
                'content': file_obj.content,
                'file_type': file_obj.file_type,
                'language': file_obj.language,
                'size': len(file_obj.content)
            })
            
        except Exception as e:
            return self._handle_error(f"Failed to get generated file: {e}", 500)
    
    # Preview API endpoints
    def get_preview_status(self):
        """Get live preview server status."""
        try:
            if self.ide_engine.live_preview:
                status = self.ide_engine.live_preview.get_status()
                return jsonify(status)
            else:
                return jsonify({'running': False, 'message': 'Live preview disabled'})
                
        except Exception as e:
            return self._handle_error(f"Failed to get preview status: {e}", 500)
    
    def start_preview(self):
        """Start the live preview server."""
        try:
            data = request.get_json() or {}
            port = data.get('port', 5001)
            
            success = self.ide_engine.start_live_preview(port)
            if success:
                return jsonify({'message': 'Live preview started successfully'})
            else:
                return self._handle_error("Failed to start live preview", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to start preview: {e}", 500)
    
    def stop_preview(self):
        """Stop the live preview server."""
        try:
            success = self.ide_engine.stop_live_preview()
            if success:
                return jsonify({'message': 'Live preview stopped successfully'})
            else:
                return self._handle_error("Failed to stop live preview", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to stop preview: {e}", 500)
    
    def get_preview_url(self):
        """Get the preview URL."""
        try:
            view_name = request.args.get('view')
            
            if self.ide_engine.live_preview:
                url = self.ide_engine.live_preview.get_preview_url(view_name)
                return jsonify({'url': url})
            else:
                return self._handle_error("Live preview not available", 404)
                
        except Exception as e:
            return self._handle_error(f"Failed to get preview URL: {e}", 500)
    
    # File Management API endpoints
    def list_files(self):
        """List project files."""
        try:
            path = request.args.get('path', '')
            files = self.ide_engine.file_manager.list_directory(path)
            
            return jsonify({'files': files, 'path': path})
            
        except Exception as e:
            return self._handle_error(f"Failed to list files: {e}", 500)
    
    def save_file(self):
        """Save a file."""
        try:
            data = self._validate_json_request(['path', 'content'])
            
            path = data['path']
            content = data['content']
            description = data.get('description', '')
            
            success = self.ide_engine.file_manager.save_file(path, content, description)
            if success:
                return jsonify({'message': f'File {path} saved successfully'})
            else:
                return self._handle_error(f"Failed to save file {path}", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to save file: {e}", 500)
    
    def get_file(self, file_path: str):
        """Get file content."""
        try:
            version = request.args.get('version')
            content = self.ide_engine.file_manager.read_file(file_path, version)
            
            if content is not None:
                return jsonify({'path': file_path, 'content': content})
            else:
                return self._handle_error(f"File {file_path} not found", 404)
                
        except Exception as e:
            return self._handle_error(f"Failed to get file: {e}", 500)
    
    def delete_file(self, file_path: str):
        """Delete a file."""
        try:
            keep_versions = request.args.get('keep_versions', 'true').lower() == 'true'
            
            success = self.ide_engine.file_manager.delete_file(file_path, keep_versions)
            if success:
                return jsonify({'message': f'File {file_path} deleted successfully'})
            else:
                return self._handle_error(f"Failed to delete file {file_path}", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to delete file: {e}", 500)
    
    def get_file_versions(self, file_path: str):
        """Get file version history."""
        try:
            versions = self.ide_engine.file_manager.get_file_versions(file_path)
            
            versions_data = []
            for version in versions:
                versions_data.append({
                    'version': version.version,
                    'timestamp': version.timestamp.isoformat(),
                    'file_hash': version.file_hash,
                    'file_size': version.file_size,
                    'description': version.description,
                    'tags': version.tags
                })
            
            return jsonify({'file_path': file_path, 'versions': versions_data})
            
        except Exception as e:
            return self._handle_error(f"Failed to get file versions: {e}", 500)
    
    # Backup API endpoints
    def list_backups(self):
        """List all backups."""
        try:
            backups = self.ide_engine.file_manager.list_backups()
            
            backups_data = []
            for backup in backups:
                backups_data.append({
                    'backup_id': backup.backup_id,
                    'timestamp': backup.timestamp.isoformat(),
                    'description': backup.description,
                    'files_count': backup.files_count,
                    'backup_size': backup.backup_size,
                    'project_version': backup.project_version
                })
            
            return jsonify({'backups': backups_data})
            
        except Exception as e:
            return self._handle_error(f"Failed to list backups: {e}", 500)
    
    def create_backup(self):
        """Create a project backup."""
        try:
            data = request.get_json() or {}
            description = data.get('description', '')
            
            backup_info = self.ide_engine.file_manager.create_backup(description)
            if backup_info:
                return jsonify({
                    'message': 'Backup created successfully',
                    'backup_id': backup_info.backup_id,
                    'files_count': backup_info.files_count,
                    'backup_size': backup_info.backup_size
                }), 201
            else:
                return self._handle_error("Failed to create backup", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to create backup: {e}", 500)
    
    def restore_backup(self, backup_id: str):
        """Restore from a backup."""
        try:
            success = self.ide_engine.file_manager.restore_backup(backup_id)
            if success:
                return jsonify({'message': f'Backup {backup_id} restored successfully'})
            else:
                return self._handle_error(f"Failed to restore backup {backup_id}", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to restore backup: {e}", 500)
    
    def delete_backup(self, backup_id: str):
        """Delete a backup."""
        try:
            success = self.ide_engine.file_manager.delete_backup(backup_id)
            if success:
                return jsonify({'message': f'Backup {backup_id} deleted successfully'})
            else:
                return self._handle_error(f"Failed to delete backup {backup_id}", 500)
                
        except Exception as e:
            return self._handle_error(f"Failed to delete backup: {e}", 500)
    
    def get_blueprint(self) -> Blueprint:
        """Get the Flask blueprint for the API."""
        return self.blueprint