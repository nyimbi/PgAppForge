"""
View Builder for Visual IDE.

Handles the visual construction of PgForge views through drag-and-drop
operations, component composition, and real-time validation.
"""

import uuid
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from ..models.project_model import (
    ViewDefinition, ViewType, ComponentConfig, ComponentType, 
    ComponentPosition, ComponentStyle, ViewLayout, ViewSecurity
)
from ..components.component_library import ComponentLibrary, ComponentTemplate

logger = logging.getLogger(__name__)


@dataclass
class DragOperation:
    """Represents a drag-and-drop operation in progress."""
    source_component_id: str
    target_component_id: Optional[str]
    operation_type: str  # 'move', 'copy', 'create'
    position: ComponentPosition
    component_data: Optional[Dict[str, Any]] = None


@dataclass
class LayoutConstraint:
    """Layout constraint for component positioning."""
    constraint_type: str  # 'grid', 'flex', 'absolute'
    min_width: Optional[int] = None
    max_width: Optional[int] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None
    snap_to_grid: bool = True
    grid_size: int = 10


class ViewBuilder:
    """
    Visual view builder with drag-and-drop capabilities.
    
    Provides methods for creating, editing, and organizing components within
    a view using visual operations. Handles layout constraints, validation,
    and component relationships.
    """
    
    def __init__(self, component_library: ComponentLibrary):
        self.component_library = component_library
        self.active_view: Optional[ViewDefinition] = None
        self.layout_constraints: Dict[str, LayoutConstraint] = {}
        self.validation_enabled = True
        
        # Operation history for undo/redo
        self.operation_history: List[Dict[str, Any]] = []
        self.history_position = 0
        self.max_history_size = 50
        
        logger.info("View builder initialized")
    
    # View Operations
    def create_view(self, name: str, view_type: str = "ModelView", 
                   model_name: Optional[str] = None) -> ViewDefinition:
        """
        Create a new view definition.
        
        Args:
            name: Name for the view
            view_type: Type of view to create
            model_name: Associated model name if applicable
            
        Returns:
            New ViewDefinition instance
        """
        try:
            view_type_enum = ViewType(view_type)
        except ValueError:
            logger.error(f"Invalid view type: {view_type}")
            view_type_enum = ViewType.BASE_VIEW
        
        view = ViewDefinition(
            name=name,
            view_type=view_type_enum,
            model_name=model_name
        )
        
        # Set up default layout based on view type
        self._setup_default_layout(view)
        
        # Add to operation history
        self._add_to_history({
            'operation': 'create_view',
            'view_name': name,
            'view_type': view_type
        })
        
        logger.info(f"Created view: {name} of type {view_type}")
        return view
    
    def _setup_default_layout(self, view: ViewDefinition):
        """Set up default layout configuration for a view."""
        if view.view_type == ViewType.MODEL_VIEW:
            # Standard CRUD layout
            view.layout.layout_type = "grid"
            view.layout.columns = 12
            self._add_default_crud_components(view)
        elif view.view_type == ViewType.MASTER_DETAIL_VIEW:
            # Master-detail layout
            view.layout.layout_type = "grid" 
            view.layout.columns = 12
            self._add_default_master_detail_components(view)
        elif view.view_type == ViewType.FORM_VIEW:
            # Form-focused layout
            view.layout.layout_type = "grid"
            view.layout.columns = 8  # Narrower for forms
            self._add_default_form_components(view)
        elif view.view_type == ViewType.CHART_VIEW:
            # Chart-focused layout
            view.layout.layout_type = "flex"
            self._add_default_chart_components(view)
    
    def _add_default_crud_components(self, view: ViewDefinition):
        """Add default components for CRUD views."""
        # Add toolbar with CRUD actions
        toolbar_config = self.component_library.create_component_instance(
            ComponentType.TOOLBAR,
            f"{view.name}_toolbar",
            {
                'label': f'{view.name} Actions',
                'position': {'row': 0, 'column': 0, 'span': 12}
            }
        )
        if toolbar_config:
            view.add_component(toolbar_config)
        
        # Add data table
        table_config = self.component_library.create_component_instance(
            ComponentType.DATA_TABLE,
            f"{view.name}_table",
            {
                'label': f'{view.name} List',
                'position': {'row': 1, 'column': 0, 'span': 12},
                'sortable': True,
                'filterable': True,
                'paginated': True
            }
        )
        if table_config:
            view.add_component(table_config)
    
    def _add_default_master_detail_components(self, view: ViewDefinition):
        """Add default components for master-detail views."""
        # Master list (left side)
        master_table = self.component_library.create_component_instance(
            ComponentType.DATA_TABLE,
            f"{view.name}_master",
            {
                'label': 'Master Records',
                'position': {'row': 0, 'column': 0, 'span': 6}
            }
        )
        if master_table:
            view.add_component(master_table)
        
        # Detail form (right side)
        detail_form = self.component_library.create_component_instance(
            ComponentType.CONTAINER,
            f"{view.name}_detail",
            {
                'label': 'Detail View',
                'position': {'row': 0, 'column': 6, 'span': 6}
            }
        )
        if detail_form:
            view.add_component(detail_form)
    
    def _add_default_form_components(self, view: ViewDefinition):
        """Add default components for form views."""
        # Form container
        form_container = self.component_library.create_component_instance(
            ComponentType.CONTAINER,
            f"{view.name}_form",
            {
                'label': f'{view.name} Form',
                'position': {'row': 0, 'column': 0, 'span': 8}
            }
        )
        if form_container:
            view.add_component(form_container)
    
    def _add_default_chart_components(self, view: ViewDefinition):
        """Add default components for chart views."""
        # Chart container
        chart_config = self.component_library.create_component_instance(
            ComponentType.CHART,
            f"{view.name}_chart",
            {
                'label': f'{view.name} Chart',
                'chart_type': 'line',
                'width': '100%',
                'height': '400px'
            }
        )
        if chart_config:
            view.add_component(chart_config)
    
    def set_active_view(self, view: ViewDefinition):
        """Set the currently active view for editing."""
        self.active_view = view
        logger.info(f"Set active view: {view.name}")
    
    # Component Operations
    def add_component(self, view: ViewDefinition, component_template: ComponentTemplate,
                     config: Dict[str, Any], parent_id: Optional[str] = None) -> bool:
        """
        Add a component to a view.
        
        Args:
            view: Target view definition
            component_template: Component template to instantiate
            config: Component configuration
            parent_id: Parent component ID if adding as child
            
        Returns:
            True if component was added successfully
        """
        try:
            # Generate unique component ID
            component_id = f"{view.name}_{component_template.component_type.value}_{uuid.uuid4().hex[:8]}"
            
            # Create component instance
            component = self.component_library.create_component_instance(
                component_template.component_type,
                component_id,
                config
            )
            
            if not component:
                logger.error(f"Failed to create component instance: {component_template.component_type}")
                return False
            
            # Apply position and styling from config
            if 'position' in config:
                self._apply_position_config(component, config['position'])
            
            if 'style' in config:
                self._apply_style_config(component, config['style'])
            
            # Validate component configuration
            if self.validation_enabled:
                validation_errors = self.component_library.validate_component_config(
                    component_template.component_type, config
                )
                if validation_errors:
                    logger.error(f"Component validation failed: {validation_errors}")
                    return False
            
            # Validate layout constraints
            if not self._validate_layout_constraints(view, component, parent_id):
                logger.error("Component violates layout constraints")
                return False
            
            # Add component to view
            view.add_component(component, parent_id)
            
            # Add to operation history
            self._add_to_history({
                'operation': 'add_component',
                'view_name': view.name,
                'component_id': component_id,
                'component_type': component_template.component_type.value,
                'parent_id': parent_id,
                'config': config
            })
            
            logger.info(f"Added component {component_id} to view {view.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add component: {e}")
            return False
    
    def remove_component(self, view: ViewDefinition, component_id: str) -> bool:
        """
        Remove a component from a view.
        
        Args:
            view: Target view definition
            component_id: ID of component to remove
            
        Returns:
            True if component was removed successfully
        """
        try:
            # Check if component exists
            component = view.get_component(component_id)
            if not component:
                logger.error(f"Component not found: {component_id}")
                return False
            
            # Store component data for undo
            component_data = {
                'component': component,
                'parent_id': self._find_parent_component(view, component_id)
            }
            
            # Remove component
            success = view.remove_component(component_id)
            
            if success:
                # Add to operation history
                self._add_to_history({
                    'operation': 'remove_component',
                    'view_name': view.name,
                    'component_id': component_id,
                    'component_data': component_data
                })
                
                logger.info(f"Removed component {component_id} from view {view.name}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to remove component: {e}")
            return False
    
    def move_component(self, view: ViewDefinition, component_id: str,
                      new_position: ComponentPosition, new_parent_id: Optional[str] = None) -> bool:
        """
        Move a component to a new position or parent.
        
        Args:
            view: Target view definition
            component_id: ID of component to move
            new_position: New position for the component
            new_parent_id: New parent component ID (optional)
            
        Returns:
            True if component was moved successfully
        """
        try:
            component = view.get_component(component_id)
            if not component:
                logger.error(f"Component not found: {component_id}")
                return False
            
            # Store old position for undo
            old_position = component.position
            old_parent_id = self._find_parent_component(view, component_id)
            
            # Validate new position against layout constraints
            temp_component = ComponentConfig(
                component_id=component_id,
                component_type=component.component_type,
                position=new_position
            )
            
            if not self._validate_layout_constraints(view, temp_component, new_parent_id):
                logger.error("New position violates layout constraints")
                return False
            
            # Update component position
            component.position = new_position
            
            # Handle parent change if needed
            if new_parent_id != old_parent_id:
                # Remove from old parent
                if old_parent_id:
                    old_parent = view.get_component(old_parent_id)
                    if old_parent and component_id in old_parent.children:
                        old_parent.children.remove(component_id)
                else:
                    if component_id in view.root_components:
                        view.root_components.remove(component_id)
                
                # Add to new parent
                if new_parent_id:
                    new_parent = view.get_component(new_parent_id)
                    if new_parent:
                        new_parent.children.append(component_id)
                else:
                    view.root_components.append(component_id)
            
            # Add to operation history
            self._add_to_history({
                'operation': 'move_component',
                'view_name': view.name,
                'component_id': component_id,
                'old_position': old_position,
                'new_position': new_position,
                'old_parent_id': old_parent_id,
                'new_parent_id': new_parent_id
            })
            
            logger.info(f"Moved component {component_id} in view {view.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to move component: {e}")
            return False
    
    def duplicate_component(self, view: ViewDefinition, component_id: str,
                          offset_position: Optional[Tuple[int, int]] = None) -> Optional[str]:
        """
        Duplicate a component and all its children.
        
        Args:
            view: Target view definition
            component_id: ID of component to duplicate
            offset_position: Position offset for the duplicate (x, y)
            
        Returns:
            ID of the duplicated component or None if failed
        """
        try:
            component = view.get_component(component_id)
            if not component:
                logger.error(f"Component not found: {component_id}")
                return None
            
            # Create new component ID
            new_component_id = f"{component_id}_copy_{uuid.uuid4().hex[:8]}"
            
            # Create duplicate component config
            new_component = ComponentConfig(
                component_id=new_component_id,
                component_type=component.component_type,
                label=f"{component.label} (Copy)" if component.label else None,
                placeholder=component.placeholder,
                default_value=component.default_value,
                options=component.options.copy(),
                data_source=component.data_source,
                position=ComponentPosition(
                    x=component.position.x + (offset_position[0] if offset_position else 20),
                    y=component.position.y + (offset_position[1] if offset_position else 20),
                    width=component.position.width,
                    height=component.position.height,
                    z_index=component.position.z_index,
                    row=component.position.row,
                    column=component.position.column,
                    span=component.position.span
                ),
                style=ComponentStyle(
                    css_classes=component.style.css_classes.copy(),
                    custom_css=component.style.custom_css.copy(),
                    theme=component.style.theme,
                    variant=component.style.variant,
                    size=component.style.size,
                    color=component.style.color
                ),
                validation=component.validation,
                permissions=component.permissions.copy(),
                events=component.events.copy(),
                properties=component.properties.copy(),
                children=[]  # Will be populated when duplicating children
            )
            
            # Find parent for positioning the duplicate
            parent_id = self._find_parent_component(view, component_id)
            
            # Add duplicate to view
            view.add_component(new_component, parent_id)
            
            # Recursively duplicate children
            for child_id in component.children:
                child_duplicate_id = self.duplicate_component(view, child_id)
                if child_duplicate_id:
                    new_component.children.append(child_duplicate_id)
            
            # Add to operation history
            self._add_to_history({
                'operation': 'duplicate_component',
                'view_name': view.name,
                'original_component_id': component_id,
                'duplicate_component_id': new_component_id,
                'offset_position': offset_position
            })
            
            logger.info(f"Duplicated component {component_id} as {new_component_id}")
            return new_component_id
            
        except Exception as e:
            logger.error(f"Failed to duplicate component: {e}")
            return None
    
    # Layout and Positioning
    def _apply_position_config(self, component: ComponentConfig, position_config: Dict[str, Any]):
        """Apply position configuration to a component."""
        if 'x' in position_config:
            component.position.x = position_config['x']
        if 'y' in position_config:
            component.position.y = position_config['y']
        if 'width' in position_config:
            component.position.width = position_config['width']
        if 'height' in position_config:
            component.position.height = position_config['height']
        if 'row' in position_config:
            component.position.row = position_config['row']
        if 'column' in position_config:
            component.position.column = position_config['column']
        if 'span' in position_config:
            component.position.span = position_config['span']
    
    def _apply_style_config(self, component: ComponentConfig, style_config: Dict[str, Any]):
        """Apply style configuration to a component."""
        if 'css_classes' in style_config:
            component.style.css_classes = style_config['css_classes']
        if 'custom_css' in style_config:
            component.style.custom_css.update(style_config['custom_css'])
        if 'theme' in style_config:
            component.style.theme = style_config['theme']
        if 'variant' in style_config:
            component.style.variant = style_config['variant']
        if 'size' in style_config:
            component.style.size = style_config['size']
        if 'color' in style_config:
            component.style.color = style_config['color']
    
    def _validate_layout_constraints(self, view: ViewDefinition, 
                                   component: ComponentConfig,
                                   parent_id: Optional[str] = None) -> bool:
        """Validate component against layout constraints."""
        try:
            # Check grid constraints for grid layouts
            if view.layout.layout_type == "grid":
                if component.position.column is not None:
                    if component.position.column >= view.layout.columns:
                        return False
                    
                    if (component.position.column + component.position.span) > view.layout.columns:
                        return False
            
            # Check parent container constraints
            if parent_id:
                parent = view.get_component(parent_id)
                if parent:
                    parent_template = self.component_library.get_component(parent.component_type)
                    if parent_template:
                        # Check if parent supports children
                        if not parent_template.supports_children:
                            return False
                        
                        # Check maximum children limit
                        if (parent_template.max_children and 
                            len(parent.children) >= parent_template.max_children):
                            return False
            
            # Check component-specific constraints
            component_constraints = self.layout_constraints.get(component.component_id)
            if component_constraints:
                if component_constraints.min_width and component.position.width < component_constraints.min_width:
                    return False
                if component_constraints.max_width and component.position.width > component_constraints.max_width:
                    return False
                if component_constraints.min_height and component.position.height < component_constraints.min_height:
                    return False
                if component_constraints.max_height and component.position.height > component_constraints.max_height:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Layout validation failed: {e}")
            return False
    
    def _find_parent_component(self, view: ViewDefinition, component_id: str) -> Optional[str]:
        """Find the parent component ID for a given component."""
        for comp_id, component in view.components.items():
            if component_id in component.children:
                return comp_id
        return None
    
    def set_layout_constraint(self, component_id: str, constraint: LayoutConstraint):
        """Set layout constraint for a component."""
        self.layout_constraints[component_id] = constraint
        logger.info(f"Set layout constraint for component {component_id}")
    
    def auto_arrange_components(self, view: ViewDefinition, algorithm: str = "grid") -> bool:
        """
        Auto-arrange components in a view using specified algorithm.
        
        Args:
            view: View to arrange components in
            algorithm: Arrangement algorithm ('grid', 'flow', 'columns')
            
        Returns:
            True if arrangement was successful
        """
        try:
            root_components = view.get_root_components()
            
            if algorithm == "grid":
                return self._arrange_grid(view, root_components)
            elif algorithm == "flow":
                return self._arrange_flow(view, root_components)
            elif algorithm == "columns":
                return self._arrange_columns(view, root_components)
            else:
                logger.error(f"Unknown arrangement algorithm: {algorithm}")
                return False
                
        except Exception as e:
            logger.error(f"Auto-arrangement failed: {e}")
            return False
    
    def _arrange_grid(self, view: ViewDefinition, components: List[ComponentConfig]) -> bool:
        """Arrange components in a grid layout."""
        if not components:
            return True
        
        cols = view.layout.columns
        current_row = 0
        current_col = 0
        
        for component in components:
            component.position.row = current_row
            component.position.column = current_col
            
            # Calculate span based on component type and content
            span = self._calculate_optimal_span(component, cols)
            component.position.span = span
            
            current_col += span
            if current_col >= cols:
                current_row += 1
                current_col = 0
        
        logger.info(f"Arranged {len(components)} components in grid layout")
        return True
    
    def _arrange_flow(self, view: ViewDefinition, components: List[ComponentConfig]) -> bool:
        """Arrange components in a flowing layout."""
        x_offset = view.layout.padding
        y_offset = view.layout.padding
        row_height = 0
        max_width = 800  # Default container width
        
        for component in components:
            # Check if component fits in current row
            if x_offset + component.position.width > max_width:
                # Move to next row
                x_offset = view.layout.padding
                y_offset += row_height + view.layout.gap
                row_height = 0
            
            component.position.x = x_offset
            component.position.y = y_offset
            
            x_offset += component.position.width + view.layout.gap
            row_height = max(row_height, component.position.height)
        
        logger.info(f"Arranged {len(components)} components in flow layout")
        return True
    
    def _arrange_columns(self, view: ViewDefinition, components: List[ComponentConfig]) -> bool:
        """Arrange components in equal-width columns."""
        if not components:
            return True
        
        num_cols = min(3, len(components))  # Max 3 columns
        col_width = view.layout.columns // num_cols
        
        for i, component in enumerate(components):
            col_index = i % num_cols
            row_index = i // num_cols
            
            component.position.column = col_index * col_width
            component.position.row = row_index
            component.position.span = col_width
        
        logger.info(f"Arranged {len(components)} components in {num_cols} columns")
        return True
    
    def _calculate_optimal_span(self, component: ComponentConfig, max_cols: int) -> int:
        """Calculate optimal column span for a component."""
        # Default spans based on component type
        span_map = {
            ComponentType.TEXT_FIELD: 4,
            ComponentType.TEXT_AREA: 8,
            ComponentType.SELECT_FIELD: 4,
            ComponentType.DATA_TABLE: 12,
            ComponentType.CHART: 12,
            ComponentType.BUTTON: 2,
            ComponentType.CARD: 6
        }
        
        default_span = span_map.get(component.component_type, 6)
        return min(default_span, max_cols)
    
    # History and Undo/Redo
    def _add_to_history(self, operation: Dict[str, Any]):
        """Add operation to history for undo/redo."""
        # Remove any operations after current position
        self.operation_history = self.operation_history[:self.history_position]
        
        # Add new operation
        operation['timestamp'] = logger.handlers[0].format(logging.LogRecord(
            'history', logging.INFO, '', 0, '', (), None
        )) if logger.handlers else ''
        
        self.operation_history.append(operation)
        self.history_position = len(self.operation_history)
        
        # Limit history size
        if len(self.operation_history) > self.max_history_size:
            self.operation_history.pop(0)
            self.history_position -= 1
    
    def undo(self, view: ViewDefinition) -> bool:
        """Undo the last operation."""
        if self.history_position <= 0:
            return False
        
        self.history_position -= 1
        operation = self.operation_history[self.history_position]
        
        return self._reverse_operation(view, operation)
    
    def redo(self, view: ViewDefinition) -> bool:
        """Redo the next operation."""
        if self.history_position >= len(self.operation_history):
            return False
        
        operation = self.operation_history[self.history_position]
        self.history_position += 1
        
        return self._apply_operation(view, operation)
    
    def _reverse_operation(self, view: ViewDefinition, operation: Dict[str, Any]) -> bool:
        """Reverse a specific operation."""
        try:
            op_type = operation['operation']
            
            if op_type == 'add_component':
                return view.remove_component(operation['component_id'])
            
            elif op_type == 'remove_component':
                # Restore component from stored data
                component_data = operation['component_data']
                view.add_component(component_data['component'], component_data['parent_id'])
                return True
            
            elif op_type == 'move_component':
                component = view.get_component(operation['component_id'])
                if component:
                    component.position = operation['old_position']
                    return True
                return False
            
            elif op_type == 'duplicate_component':
                return view.remove_component(operation['duplicate_component_id'])
            
            # Add more operation reversals as needed
            return False
            
        except Exception as e:
            logger.error(f"Failed to reverse operation: {e}")
            return False
    
    def _apply_operation(self, view: ViewDefinition, operation: Dict[str, Any]) -> bool:
        """Re-apply a specific operation."""
        try:
            op_type = operation['operation']
            
            if op_type == 'move_component':
                component = view.get_component(operation['component_id'])
                if component:
                    component.position = operation['new_position']
                    return True
                return False
            
            # Add more operation re-applications as needed
            return False
            
        except Exception as e:
            logger.error(f"Failed to apply operation: {e}")
            return False
    
    def get_history(self) -> List[Dict[str, Any]]:
        """Get operation history."""
        return self.operation_history.copy()
    
    def clear_history(self):
        """Clear operation history."""
        self.operation_history.clear()
        self.history_position = 0
        logger.info("Cleared operation history")
    
    # View Validation
    def validate_view(self, view: ViewDefinition) -> List[str]:
        """
        Validate a complete view definition.
        
        Returns:
            List of validation error messages
        """
        errors = []
        
        try:
            # Check basic view properties
            if not view.name:
                errors.append("View name is required")
            
            if not view.view_type:
                errors.append("View type is required")
            
            # Validate components
            for component_id, component in view.components.items():
                component_errors = self.component_library.validate_component_config(
                    component.component_type, component.properties
                )
                for error in component_errors:
                    errors.append(f"Component {component_id}: {error}")
            
            # Check for orphaned components
            all_children = set()
            for component in view.components.values():
                all_children.update(component.children)
            
            orphaned = set(view.components.keys()) - all_children - set(view.root_components)
            if orphaned:
                errors.append(f"Orphaned components found: {', '.join(orphaned)}")
            
            # Validate layout constraints
            for component in view.components.values():
                if not self._validate_layout_constraints(view, component):
                    errors.append(f"Component {component.component_id} violates layout constraints")
            
        except Exception as e:
            errors.append(f"Validation error: {e}")
        
        return errors
    
    def get_view_statistics(self, view: ViewDefinition) -> Dict[str, Any]:
        """Get statistics about a view."""
        component_counts = {}
        for component in view.components.values():
            comp_type = component.component_type.value
            component_counts[comp_type] = component_counts.get(comp_type, 0) + 1
        
        return {
            'total_components': len(view.components),
            'root_components': len(view.root_components),
            'component_types': component_counts,
            'layout_type': view.layout.layout_type,
            'max_depth': self._calculate_max_depth(view),
            'validation_errors': len(self.validate_view(view))
        }
    
    def _calculate_max_depth(self, view: ViewDefinition) -> int:
        """Calculate maximum nesting depth of components."""
        def get_depth(component_id: str, current_depth: int = 0) -> int:
            component = view.get_component(component_id)
            if not component or not component.children:
                return current_depth
            
            max_child_depth = 0
            for child_id in component.children:
                child_depth = get_depth(child_id, current_depth + 1)
                max_child_depth = max(max_child_depth, child_depth)
            
            return max_child_depth
        
        max_depth = 0
        for root_id in view.root_components:
            depth = get_depth(root_id)
            max_depth = max(max_depth, depth)
        
        return max_depth