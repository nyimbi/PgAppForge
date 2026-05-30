"""
Real-Time Schema Evolution System for PgForge

This package provides comprehensive database schema monitoring, change detection,
and automatic code generation capabilities for continuous development workflows.
"""

from .schema_monitor import SchemaMonitor, SchemaChange, ChangeType
from .evolution_engine import EvolutionEngine, EvolutionConfig, CodeGenerationPipeline
from .change_detector import ChangeDetector, SchemaComparison, ColumnChange, TableChange
from .code_regenerator import CodeRegenerator, RegenerationTask, RegenerationResult

__version__ = "1.0.0"
__author__ = "PgForge Schema Evolution Team"

__all__ = [
    # Schema Monitoring
    "SchemaMonitor",
    "SchemaChange",
    "ChangeType",

    # Evolution Engine
    "EvolutionEngine",
    "EvolutionConfig",
    "CodeGenerationPipeline",

    # Change Detection
    "ChangeDetector",
    "SchemaComparison",
    "ColumnChange",
    "TableChange",

    # Code Regeneration
    "CodeRegenerator",
    "RegenerationTask",
    "RegenerationResult"
]