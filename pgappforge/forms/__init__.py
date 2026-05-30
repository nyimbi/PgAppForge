"""
PgForge Forms Package

Enhanced form functionality including wizard forms for multi-step data entry.
This module provides both the original PgForge forms functionality
and the new wizard form system.
"""

# Import basic form functionality
try:
    from wtforms import Form, StringField, IntegerField, FloatField, BooleanField
    from flask_wtf import FlaskForm
    __all__ = ['Form', 'StringField', 'IntegerField', 'FloatField', 'BooleanField', 'FlaskForm']
except ImportError:
    __all__ = []

# Embedded DynamicForm to avoid circular import issues
try:
    from flask_wtf import FlaskForm
    from wtforms import widgets
    from wtforms.fields import Field
    
    class DynamicForm(FlaskForm):
        """
        Dynamic form generation for PgForge.
        
        Allows for runtime form creation based on model metadata.
        This is embedded here to avoid circular import issues.
        """
        
        def __init__(self, *args, **kwargs):
            super(DynamicForm, self).__init__(*args, **kwargs)
            
        def refresh(self, obj=None):
            """Refresh form with new data"""
            return self.__class__(obj=obj)
    
    # Embedded GeneralModelConverter
    class GeneralModelConverter:
        """
        General model converter for form generation.
        
        Converts SQLAlchemy models to WTForms for automatic form generation.
        This is embedded here to avoid circular import issues.
        """
        
        def __init__(self, datamodel):
            self.datamodel = datamodel
            
        def create_form(self, label_columns=None, include_cols=None, 
                       description_columns=None, validators_columns=None,
                       extra_fields=None, filter_rel_fields=None):
            """Create a form from model"""
            # Basic implementation to avoid import issues
            form_props = {'csrf_token': None}
            
            if extra_fields:
                form_props.update(extra_fields)
                
            return type("DynamicForm", (DynamicForm,), form_props)
    
    __all__.extend(['DynamicForm', 'GeneralModelConverter'])
    
except ImportError:
    # Minimal fallback
    class DynamicForm:
        pass
    class GeneralModelConverter:
        def __init__(self, datamodel):
            self.datamodel = datamodel
    __all__.extend(['DynamicForm', 'GeneralModelConverter'])

# Import wizard forms
try:
    from .wizard import WizardForm, WizardStep, WizardFormData, WizardFormPersistence

    wizard_exports = [
        'WizardForm',
        'WizardStep',
        'WizardFormData',
        'WizardFormPersistence'
    ]

    __all__.extend(wizard_exports)

except ImportError:
    pass  # Continue without wizard forms if not available

# Import form layout editor
try:
    from .layout_manager import FormLayout, FormLayoutManager, AVAILABLE_WIDGETS
    from .layout_editor import FormLayoutEditorView, inject_edit_button

    __all__.extend([
        'FormLayout',
        'FormLayoutManager',
        'AVAILABLE_WIDGETS',
        'FormLayoutEditorView',
        'inject_edit_button',
    ])

except ImportError:
    pass  # SQLAlchemy or pgappforge not fully available in this environment
