"""
Visual IDE Engine - Main orchestrator for the visual development environment.

This module provides the core engine that coordinates all visual development
activities including drag-and-drop building, code generation, and live preview.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime

from ..components.component_library import ComponentLibrary
from ..builders.view_builder import ViewBuilder
from ..generators.code_generator import VisualCodeGenerator
from ..preview.live_preview import LivePreviewEngine
from ..models.project_model import IDEProject, ViewDefinition
from ..utils.file_manager import IDEFileManager

logger = logging.getLogger(__name__)


@dataclass
class IDEConfiguration:
    """Configuration for the Visual IDE Engine."""
    workspace_path: str
    project_name: str
    auto_save_interval: int = 30  # seconds
    enable_live_preview: bool = True
    enable_hot_reload: bool = True
    component_library_path: Optional[str] = None
    custom_templates_path: Optional[str] = None
    output_directory: str = "generated"
    backup_directory: str = "backups"


class VisualIDEEngine:
    """
    Main engine for the Visual Development IDE.
    
    Orchestrates all visual development activities:
    - Project management
    - Component library management
    - View building and editing
    - Code generation
    - Live preview coordination
    - File management and versioning
    """
    
    def __init__(self, config: IDEConfiguration):
        self.config = config
        self.workspace_path = Path(config.workspace_path)
        self.project_path = self.workspace_path / config.project_name
        
        # Initialize core components
        self.component_library = ComponentLibrary(
            library_path=config.component_library_path
        )
        self.view_builder = ViewBuilder(self.component_library)
        self.code_generator = VisualCodeGenerator(
            output_path=self.project_path / config.output_directory
        )
        self.live_preview = LivePreviewEngine() if config.enable_live_preview else None
        self.file_manager = IDEFileManager(
            project_path=self.project_path,
            backup_path=self.project_path / config.backup_directory
        )
        
        # Project state
        self.current_project: Optional[IDEProject] = None
        self.active_views: Dict[str, ViewDefinition] = {}
        self.is_initialized = False
        
        # Initialize workspace
        self._initialize_workspace()
    
    def _initialize_workspace(self):
        """Initialize the IDE workspace and project structure."""
        try:
            # Create directory structure
            self.project_path.mkdir(parents=True, exist_ok=True)
            (self.project_path / self.config.output_directory).mkdir(exist_ok=True)
            (self.project_path / self.config.backup_directory).mkdir(exist_ok=True)
            (self.project_path / "views").mkdir(exist_ok=True)
            (self.project_path / "components").mkdir(exist_ok=True)
            (self.project_path / "templates").mkdir(exist_ok=True)
            
            # Load or create project
            self._load_or_create_project()
            
            self.is_initialized = True
            logger.info(f"Visual IDE initialized for project: {self.config.project_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Visual IDE workspace: {e}")
            raise
    
    def _load_or_create_project(self):
        """Load existing project or create new one."""
        project_file = self.project_path / "project.json"
        
        if project_file.exists():
            try:
                with open(project_file, 'r') as f:
                    project_data = json.load(f)
                self.current_project = IDEProject.from_dict(project_data)
                logger.info(f"Loaded existing project: {self.current_project.name}")
            except Exception as e:
                logger.error(f"Failed to load project: {e}")
                self._create_new_project()
        else:
            self._create_new_project()
    
    def _create_new_project(self):
        """Create a new IDE project."""
        self.current_project = IDEProject(
            name=self.config.project_name,
            created_at=datetime.now(),
            version="1.0.0",
            description=f"Visual IDE project for {self.config.project_name}"
        )
        self._save_project()
        logger.info(f"Created new project: {self.current_project.name}")
    
    def _save_project(self):
        """Save current project state to disk."""
        if not self.current_project:
            return
            
        project_file = self.project_path / "project.json"
        try:
            with open(project_file, 'w') as f:
                json.dump(asdict(self.current_project), f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save project: {e}")
    
    # View Management
    def create_view(self, view_name: str, view_type: str = "ModelView") -> ViewDefinition:
        """
        Create a new view using the visual builder.
        
        Args:
            view_name: Name for the new view
            view_type: Type of view to create (ModelView, BaseView, etc.)
            
        Returns:
            ViewDefinition object for the created view
        """
        try:
            view_definition = self.view_builder.create_view(
                name=view_name,
                view_type=view_type
            )
            
            # Store in active views
            self.active_views[view_name] = view_definition
            
            # Add to project
            if self.current_project:
                self.current_project.views[view_name] = view_definition
                self._save_project()
            
            logger.info(f"Created view: {view_name} of type {view_type}")
            return view_definition
            
        except Exception as e:
            logger.error(f"Failed to create view {view_name}: {e}")
            raise
    
    def edit_view(self, view_name: str) -> ViewDefinition:
        """
        Open a view for editing in the visual builder.
        
        Args:
            view_name: Name of the view to edit
            
        Returns:
            ViewDefinition object for editing
        """
        if view_name not in self.active_views:
            raise ValueError(f"View {view_name} not found in active views")
        
        view_definition = self.active_views[view_name]
        logger.info(f"Opening view for editing: {view_name}")
        return view_definition
    
    def delete_view(self, view_name: str) -> bool:
        """
        Delete a view from the project.
        
        Args:
            view_name: Name of the view to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            # Remove from active views
            if view_name in self.active_views:
                del self.active_views[view_name]
            
            # Remove from project
            if self.current_project and view_name in self.current_project.views:
                del self.current_project.views[view_name]
                self._save_project()
            
            # Remove generated files
            self.file_manager.delete_view_files(view_name)
            
            logger.info(f"Deleted view: {view_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete view {view_name}: {e}")
            return False
    
    # Code Generation
    def generate_code(self, view_name: Optional[str] = None) -> Dict[str, str]:
        """
        Generate code for views.
        
        Args:
            view_name: Specific view to generate code for, or None for all views
            
        Returns:
            Dictionary mapping file paths to generated code
        """
        try:
            if view_name:
                if view_name not in self.active_views:
                    raise ValueError(f"View {view_name} not found")
                
                views_to_generate = {view_name: self.active_views[view_name]}
            else:
                views_to_generate = self.active_views
            
            generated_files = {}
            
            for name, view_def in views_to_generate.items():
                files = self.code_generator.generate_view_code(view_def)
                generated_files.update(files)
                
                # Update live preview if enabled
                if self.live_preview:
                    self.live_preview.update_view(name, view_def)
            
            logger.info(f"Generated code for {len(views_to_generate)} views")
            return generated_files
            
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            raise
    
    def generate_full_application(self) -> Dict[str, str]:
        """
        Generate a complete PgForge application.
        
        Returns:
            Dictionary mapping file paths to generated code
        """
        try:
            if not self.current_project:
                raise ValueError("No active project")
            
            # Generate all view code
            all_files = self.generate_code()
            
            # Generate application structure
            app_files = self.code_generator.generate_application_structure(
                self.current_project
            )
            all_files.update(app_files)
            
            # Generate configuration files
            config_files = self.code_generator.generate_configuration_files(
                self.current_project
            )
            all_files.update(config_files)
            
            logger.info(f"Generated complete application with {len(all_files)} files")
            return all_files
            
        except Exception as e:
            logger.error(f"Full application generation failed: {e}")
            raise
    
    # Component Management
    def add_component_to_view(self, view_name: str, component_type: str, 
                             config: Dict[str, Any]) -> bool:
        """
        Add a component to a view using drag-and-drop.
        
        Args:
            view_name: Target view name
            component_type: Type of component to add
            config: Component configuration
            
        Returns:
            True if component was added successfully
        """
        try:
            if view_name not in self.active_views:
                raise ValueError(f"View {view_name} not found")
            
            view_def = self.active_views[view_name]
            component = self.component_library.get_component(component_type)
            
            success = self.view_builder.add_component(view_def, component, config)
            
            if success:
                # Update live preview
                if self.live_preview:
                    self.live_preview.update_view(view_name, view_def)
                
                logger.info(f"Added {component_type} to view {view_name}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to add component to view: {e}")
            return False
    
    def remove_component_from_view(self, view_name: str, component_id: str) -> bool:
        """
        Remove a component from a view.
        
        Args:
            view_name: Target view name
            component_id: ID of component to remove
            
        Returns:
            True if component was removed successfully
        """
        try:
            if view_name not in self.active_views:
                raise ValueError(f"View {view_name} not found")
            
            view_def = self.active_views[view_name]
            success = self.view_builder.remove_component(view_def, component_id)
            
            if success:
                # Update live preview
                if self.live_preview:
                    self.live_preview.update_view(view_name, view_def)
                
                logger.info(f"Removed component {component_id} from view {view_name}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to remove component from view: {e}")
            return False
    
    # Preview Management
    def start_live_preview(self, port: int = 5000) -> bool:
        """
        Start the live preview server.
        
        Args:
            port: Port to run preview server on
            
        Returns:
            True if preview server started successfully
        """
        if not self.live_preview:
            logger.warning("Live preview is disabled")
            return False
        
        try:
            return self.live_preview.start_server(port)
        except Exception as e:
            logger.error(f"Failed to start live preview: {e}")
            return False
    
    def stop_live_preview(self) -> bool:
        """
        Stop the live preview server.
        
        Returns:
            True if preview server stopped successfully
        """
        if not self.live_preview:
            return True
        
        try:
            return self.live_preview.stop_server()
        except Exception as e:
            logger.error(f"Failed to stop live preview: {e}")
            return False
    
    # Project Operations
    def export_project(self, export_path: str) -> bool:
        """
        Export the entire project including visual definitions and generated code.
        
        Args:
            export_path: Path to export the project to
            
        Returns:
            True if export was successful
        """
        try:
            export_dir = Path(export_path)
            export_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate all code first
            all_files = self.generate_full_application()
            
            # Copy all files to export directory
            for file_path, content in all_files.items():
                target_file = export_dir / file_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(target_file, 'w') as f:
                    f.write(content)
            
            # Copy project metadata
            if self.current_project:
                project_file = export_dir / "project.json"
                with open(project_file, 'w') as f:
                    json.dump(asdict(self.current_project), f, indent=2, default=str)
            
            logger.info(f"Exported project to: {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to export project: {e}")
            return False
    
    def import_project(self, import_path: str) -> bool:
        """
        Import a project from an export directory.
        
        Args:
            import_path: Path to import the project from
            
        Returns:
            True if import was successful
        """
        try:
            import_dir = Path(import_path)
            if not import_dir.exists():
                raise ValueError(f"Import path does not exist: {import_path}")
            
            # Load project metadata
            project_file = import_dir / "project.json"
            if project_file.exists():
                with open(project_file, 'r') as f:
                    project_data = json.load(f)
                self.current_project = IDEProject.from_dict(project_data)
                
                # Load views
                self.active_views = self.current_project.views
                
                logger.info(f"Imported project: {self.current_project.name}")
                return True
            else:
                raise ValueError("No project.json found in import directory")
            
        except Exception as e:
            logger.error(f"Failed to import project: {e}")
            return False
    
    def get_project_status(self) -> Dict[str, Any]:
        """
        Get current project status and statistics.
        
        Returns:
            Dictionary containing project status information
        """
        if not self.current_project:
            return {"status": "no_project"}
        
        return {
            "status": "active",
            "project_name": self.current_project.name,
            "version": self.current_project.version,
            "created_at": self.current_project.created_at.isoformat(),
            "views_count": len(self.active_views),
            "views": list(self.active_views.keys()),
            "live_preview_active": self.live_preview.is_running if self.live_preview else False,
            "workspace_path": str(self.workspace_path),
            "project_path": str(self.project_path)
        }
    
    def cleanup(self):
        """Clean up resources and stop services."""
        try:
            # Stop live preview
            if self.live_preview:
                self.live_preview.stop_server()
            
            # Save project state
            self._save_project()
            
            logger.info("Visual IDE engine cleaned up successfully")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")