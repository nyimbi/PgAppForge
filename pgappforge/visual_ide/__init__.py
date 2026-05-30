"""
Visual Development IDE for PgForge

A comprehensive visual development environment that allows developers to create
PgForge applications using drag-and-drop interfaces, visual component
composition, and real-time code generation.

Features:
- Drag-and-drop view builder
- Visual component library
- Real-time code generation
- Live preview capabilities
- Integration with PgForge security and permissions
"""

from .core.ide_engine import VisualIDEEngine
from .components.component_library import ComponentLibrary
from .builders.view_builder import ViewBuilder
from .generators.code_generator import VisualCodeGenerator
from .preview.live_preview import LivePreviewEngine

__all__ = [
    'VisualIDEEngine',
    'ComponentLibrary', 
    'ViewBuilder',
    'VisualCodeGenerator',
    'LivePreviewEngine'
]

__version__ = '1.0.0'