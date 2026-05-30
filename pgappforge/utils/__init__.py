"""PgForge Utils Package

Utility functions and classes for PgForge.
"""

from .py314 import (
    PY314,
    ParameterizedQuery,
    safe_sql,
    safe_sql_kw,
    get_field_annotations,
    describe_field_type,
    is_template,
    is_interpolation,
)

try:
    from .wizard_validator import WizardComponentValidator, validate_wizard_implementation, print_validation_report
    __all__ = [
        # py314
        'PY314',
        'ParameterizedQuery',
        'safe_sql',
        'safe_sql_kw',
        'get_field_annotations',
        'describe_field_type',
        'is_template',
        'is_interpolation',
        # wizard
        'WizardComponentValidator',
        'validate_wizard_implementation',
        'print_validation_report',
    ]
except ImportError:
    __all__ = [
        'PY314',
        'ParameterizedQuery',
        'safe_sql',
        'safe_sql_kw',
        'get_field_annotations',
        'describe_field_type',
        'is_template',
        'is_interpolation',
    ]