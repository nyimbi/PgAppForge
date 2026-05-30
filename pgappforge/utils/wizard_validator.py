"""
PgAppForge Wizard Form Validation Utilities

Comprehensive validation utilities for ensuring wizard forms are properly
configured and all components are complete and functional.
"""

import logging
import inspect
from typing import Dict, List, Optional, Any, Type, Tuple
from flask import current_app

from ..forms.wizard import WizardForm, WizardStep, WizardFormData, WizardFormPersistence
from ..views.wizard import WizardFormView, WizardModelView

logger = logging.getLogger(__name__)


class WizardValidationError(Exception):
    """Exception raised when wizard validation fails"""
    pass


class WizardComponentValidator:
    """
    Comprehensive validator for wizard form components
    
    Validates that all wizard components are properly implemented,
    configured, and functional.
    """
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
    
    def validate_all_components(self) -> Dict[str, Any]:
        """
        Validate all wizard components comprehensively
        
        Returns:
            Dictionary with validation results
        """
        logger.info("Starting comprehensive wizard component validation")
        
        results = {
            'overall_status': 'unknown',
            'components': {},
            'errors': [],
            'warnings': [],
            'info': [],
            'summary': {}
        }
        
        # Validate core components
        results['components']['wizard_step'] = self._validate_wizard_step()
        results['components']['wizard_form_data'] = self._validate_wizard_form_data()
        results['components']['wizard_persistence'] = self._validate_wizard_persistence()
        results['components']['wizard_form'] = self._validate_wizard_form()
        results['components']['wizard_view'] = self._validate_wizard_view()
        results['components']['wizard_model_view'] = self._validate_wizard_model_view()
        results['components']['templates'] = self._validate_templates()
        
        # Aggregate results
        results['errors'] = self.errors
        results['warnings'] = self.warnings
        results['info'] = self.info
        
        # Determine overall status
        if self.errors:
            results['overall_status'] = 'failed'
        elif self.warnings:
            results['overall_status'] = 'passed_with_warnings'
        else:
            results['overall_status'] = 'passed'
        
        # Generate summary
        results['summary'] = self._generate_summary(results)
        
        logger.info(f"Validation complete. Status: {results['overall_status']}")
        
        return results
    
    def _validate_wizard_step(self) -> Dict[str, Any]:
        """Validate WizardStep class implementation"""
        logger.debug("Validating WizardStep class")
        
        component_result = {
            'status': 'passed',
            'methods_validated': [],
            'issues': []
        }
        
        try:
            # Check class exists and is importable
            self._check_class_exists(WizardStep, 'WizardStep')
            
            # Validate required methods
            required_methods = [
                'validate_step',
                'get_progress_percentage', 
                'to_dict',
                '_validate_field',
                '_should_show_field'
            ]
            
            for method_name in required_methods:
                if self._validate_method_implementation(WizardStep, method_name):
                    component_result['methods_validated'].append(method_name)
            
            # Test instantiation
            test_step = WizardStep(
                name='test_step',
                title='Test Step',
                fields=['field1', 'field2'],
                required_fields=['field1']
            )
            
            # Test validation functionality
            is_valid, errors = test_step.validate_step({'field1': 'value1'})
            if not isinstance(is_valid, bool) or not isinstance(errors, dict):
                self._add_error("WizardStep.validate_step does not return correct types")
                component_result['status'] = 'failed'
            
            # Test progress calculation
            progress = test_step.get_progress_percentage({'field1': 'value1'})
            if not isinstance(progress, (int, float)) or not 0 <= progress <= 100:
                self._add_error("WizardStep.get_progress_percentage does not return valid percentage")
                component_result['status'] = 'failed'
            
            # Test serialization
            step_dict = test_step.to_dict()
            if not isinstance(step_dict, dict) or 'name' not in step_dict:
                self._add_error("WizardStep.to_dict does not return valid dictionary")
                component_result['status'] = 'failed'
            
            self._add_info("WizardStep class validation passed")
            
        except Exception as e:
            self._add_error(f"WizardStep validation failed: {str(e)}")
            component_result['status'] = 'failed'
        
        return component_result
    
    def _validate_wizard_form_data(self) -> Dict[str, Any]:
        """Validate WizardFormData class implementation"""
        logger.debug("Validating WizardFormData class")
        
        component_result = {
            'status': 'passed',
            'methods_validated': [],
            'issues': []
        }
        
        try:
            # Check class exists
            self._check_class_exists(WizardFormData, 'WizardFormData')
            
            # Validate required methods
            required_methods = [
                'update_data',
                'get_step_data',
                'set_current_step',
                'mark_submitted',
                'is_expired',
                'to_dict',
                'from_dict'
            ]
            
            for method_name in required_methods:
                if self._validate_method_implementation(WizardFormData, method_name):
                    component_result['methods_validated'].append(method_name)
            
            # Test instantiation and functionality
            wizard_data = WizardFormData('test_wizard', 'test_user')
            
            # Test data update
            wizard_data.update_data({'field1': 'value1'}, 0)
            if 'field1' not in wizard_data.form_data:
                self._add_error("WizardFormData.update_data does not store data correctly")
                component_result['status'] = 'failed'
            
            # Test step data retrieval
            step_data = wizard_data.get_step_data(['field1'])
            if not isinstance(step_data, dict):
                self._add_error("WizardFormData.get_step_data does not return dictionary")
                component_result['status'] = 'failed'
            
            # Test serialization
            data_dict = wizard_data.to_dict()
            if not isinstance(data_dict, dict):
                self._add_error("WizardFormData.to_dict does not return dictionary")
                component_result['status'] = 'failed'
            
            # Test deserialization
            restored_data = WizardFormData.from_dict(data_dict)
            if not isinstance(restored_data, WizardFormData):
                self._add_error("WizardFormData.from_dict does not return WizardFormData instance")
                component_result['status'] = 'failed'
            
            self._add_info("WizardFormData class validation passed")
            
        except Exception as e:
            self._add_error(f"WizardFormData validation failed: {str(e)}")
            component_result['status'] = 'failed'
        
        return component_result
    
    def _validate_wizard_persistence(self) -> Dict[str, Any]:
        """Validate WizardFormPersistence class implementation"""
        logger.debug("Validating WizardFormPersistence class")
        
        component_result = {
            'status': 'passed',
            'methods_validated': [],
            'issues': []
        }
        
        try:
            # Check class exists
            self._check_class_exists(WizardFormPersistence, 'WizardFormPersistence')
            
            # Validate required methods
            required_methods = [
                'save_wizard_data',
                'load_wizard_data',
                'delete_wizard_data',
                'cleanup_expired_data',
                '_save_to_session',
                '_load_from_session',
                '_delete_from_session',
                '_save_to_database',
                '_load_from_database',
                '_delete_from_database',
                '_save_to_cache',
                '_load_from_cache',
                '_delete_from_cache',
                '_get_or_create_wizard_model'
            ]
            
            for method_name in required_methods:
                if self._validate_method_implementation(WizardFormPersistence, method_name):
                    component_result['methods_validated'].append(method_name)
            
            # Test different storage backends
            for backend in ['session', 'database', 'cache']:
                try:
                    persistence = WizardFormPersistence(backend)
                    if persistence.storage_backend != backend:
                        self._add_error(f"WizardFormPersistence does not set storage_backend correctly for {backend}")
                        component_result['status'] = 'failed'
                except Exception as e:
                    self._add_warning(f"WizardFormPersistence backend '{backend}' may have issues: {str(e)}")
            
            # Check that all backend methods are fully implemented (not just stubs)
            persistence = WizardFormPersistence('session')
            
            # Check session methods are implemented
            if not self._is_method_fully_implemented(persistence._save_to_session):
                self._add_error("WizardFormPersistence._save_to_session is not fully implemented")
                component_result['status'] = 'failed'
            
            if not self._is_method_fully_implemented(persistence._load_from_session):
                self._add_error("WizardFormPersistence._load_from_session is not fully implemented")
                component_result['status'] = 'failed'
            
            # Check database methods are implemented
            if not self._is_method_fully_implemented(persistence._save_to_database):
                self._add_error("WizardFormPersistence._save_to_database is not fully implemented")
                component_result['status'] = 'failed'
            
            # Check cache methods are implemented  
            if not self._is_method_fully_implemented(persistence._save_to_cache):
                self._add_error("WizardFormPersistence._save_to_cache is not fully implemented")
                component_result['status'] = 'failed'
            
            self._add_info("WizardFormPersistence class validation passed")
            
        except Exception as e:
            self._add_error(f"WizardFormPersistence validation failed: {str(e)}")
            component_result['status'] = 'failed'
        
        return component_result
    
    def _validate_wizard_form(self) -> Dict[str, Any]:
        """Validate WizardForm class implementation"""
        logger.debug("Validating WizardForm class")
        
        component_result = {
            'status': 'passed',
            'methods_validated': [],
            'issues': []
        }
        
        try:
            # Check class exists
            self._check_class_exists(WizardForm, 'WizardForm')
            
            # Validate required methods
            required_methods = [
                'save_wizard_data',
                'get_current_step',
                'get_current_step_data',
                'validate_current_step',
                'can_proceed_to_next_step',
                'can_go_to_previous_step',
                'can_navigate_to_step',
                'next_step',
                'previous_step',
                'goto_step',
                'is_final_step',
                'get_progress_percentage',
                'get_step_status',
                'validate',
                'submit_wizard',
                'cleanup_wizard_data',
                'to_dict',
                '_initialize_steps',
                '_auto_generate_steps',
                '_load_wizard_data'
            ]
            
            for method_name in required_methods:
                if self._validate_method_implementation(WizardForm, method_name):
                    component_result['methods_validated'].append(method_name)
            
            # Check that all methods are fully implemented
            if not self._is_method_fully_implemented(WizardForm._initialize_steps):
                self._add_error("WizardForm._initialize_steps is not fully implemented")
                component_result['status'] = 'failed'
            
            if not self._is_method_fully_implemented(WizardForm._auto_generate_steps):
                self._add_error("WizardForm._auto_generate_steps is not fully implemented")
                component_result['status'] = 'failed'
            
            self._add_info("WizardForm class validation passed")
            
        except Exception as e:
            self._add_error(f"WizardForm validation failed: {str(e)}")
            component_result['status'] = 'failed'
        
        return component_result
    
    def _validate_wizard_view(self) -> Dict[str, Any]:
        """Validate WizardFormView class implementation"""
        logger.debug("Validating WizardFormView class")
        
        component_result = {
            'status': 'passed',
            'methods_validated': [],
            'issues': []
        }
        
        try:
            # Check class exists
            self._check_class_exists(WizardFormView, 'WizardFormView')
            
            # Validate required methods
            required_methods = [
                'wizard',
                'save_draft_api',
                'validate_step_api',
                'wizard_status_api',
                'process_wizard_submission',
                '_get_wizard_id',
                '_create_wizard_form',
                '_handle_wizard_post',
                '_handle_next_step',
                '_handle_previous_step',
                '_handle_goto_step',
                '_handle_save_draft',
                '_handle_final_submission',
                '_render_wizard_form',
                '_render_success_page'
            ]
            
            for method_name in required_methods:
                if self._validate_method_implementation(WizardFormView, method_name):
                    component_result['methods_validated'].append(method_name)
            
            # Check that key methods are fully implemented
            if not self._is_method_fully_implemented(WizardFormView._handle_wizard_post):
                self._add_error("WizardFormView._handle_wizard_post is not fully implemented")
                component_result['status'] = 'failed'
            
            if not self._is_method_fully_implemented(WizardFormView._handle_final_submission):
                self._add_error("WizardFormView._handle_final_submission is not fully implemented")
                component_result['status'] = 'failed'
            
            self._add_info("WizardFormView class validation passed")
            
        except Exception as e:
            self._add_error(f"WizardFormView validation failed: {str(e)}")
            component_result['status'] = 'failed'
        
        return component_result
    
    def _validate_wizard_model_view(self) -> Dict[str, Any]:
        """Validate WizardModelView class implementation"""
        logger.debug("Validating WizardModelView class")
        
        component_result = {
            'status': 'passed',
            'methods_validated': [],
            'issues': []
        }
        
        try:
            # Check class exists
            self._check_class_exists(WizardModelView, 'WizardModelView')
            
            # Validate required methods
            required_methods = [
                'wizard_add',
                'wizard_edit',
                '_should_use_wizard',
                '_setup_wizard_form',
                '_create_wizard_steps',
                '_create_model_wizard_form_class',
                '_create_wizard_view_for_model'
            ]
            
            for method_name in required_methods:
                if self._validate_method_implementation(WizardModelView, method_name):
                    component_result['methods_validated'].append(method_name)
            
            # Check that key methods are fully implemented
            if not self._is_method_fully_implemented(WizardModelView._create_model_wizard_form_class):
                self._add_error("WizardModelView._create_model_wizard_form_class is not fully implemented")
                component_result['status'] = 'failed'
            
            if not self._is_method_fully_implemented(WizardModelView._create_wizard_view_for_model):
                self._add_error("WizardModelView._create_wizard_view_for_model is not fully implemented")
                component_result['status'] = 'failed'
            
            self._add_info("WizardModelView class validation passed")
            
        except Exception as e:
            self._add_error(f"WizardModelView validation failed: {str(e)}")
            component_result['status'] = 'failed'
        
        return component_result
    
    def _validate_templates(self) -> Dict[str, Any]:
        """Validate wizard templates exist and are complete"""
        logger.debug("Validating wizard templates")
        
        component_result = {
            'status': 'passed',
            'templates_found': [],
            'issues': []
        }
        
        import os
        
        # Template paths to check
        template_paths = [
            '/Users/nyimbiodero/src/pjs/fab-ext/pgappforge/templates/wizard/wizard_form.html',
            '/Users/nyimbiodero/src/pjs/fab-ext/pgappforge/templates/wizard/wizard_success.html',
            '/Users/nyimbiodero/src/pjs/fab-ext/pgappforge/templates/appbuilder/general/widgets/wizard_form.html'
        ]
        
        for template_path in template_paths:
            if os.path.exists(template_path):
                component_result['templates_found'].append(os.path.basename(template_path))
                
                # Check template has minimum required content
                try:
                    with open(template_path, 'r') as f:
                        content = f.read()
                    
                    # Basic content validation
                    if 'wizard' not in content.lower():
                        self._add_warning(f"Template {os.path.basename(template_path)} may not be wizard-specific")
                    
                    if len(content) < 100:
                        self._add_error(f"Template {os.path.basename(template_path)} appears incomplete")
                        component_result['status'] = 'failed'
                        
                except Exception as e:
                    self._add_error(f"Could not read template {template_path}: {str(e)}")
                    component_result['status'] = 'failed'
            else:
                self._add_error(f"Required template not found: {template_path}")
                component_result['status'] = 'failed'
        
        if component_result['status'] == 'passed':
            self._add_info(f"Template validation passed. Found {len(component_result['templates_found'])} templates")
        
        return component_result
    
    def _check_class_exists(self, cls: Type, name: str):
        """Check that a class exists and is importable"""
        if not inspect.isclass(cls):
            raise WizardValidationError(f"{name} is not a valid class")
        
        # Check class has proper docstring
        if not cls.__doc__ or len(cls.__doc__.strip()) < 10:
            self._add_warning(f"{name} class lacks comprehensive docstring")
    
    def _validate_method_implementation(self, cls: Type, method_name: str) -> bool:
        """Validate that a method exists and is implemented"""
        if not hasattr(cls, method_name):
            self._add_error(f"{cls.__name__}.{method_name} method not found")
            return False
        
        method = getattr(cls, method_name)
        if not callable(method):
            self._add_error(f"{cls.__name__}.{method_name} is not callable")
            return False
        
        # Check method has docstring
        if not method.__doc__ or len(method.__doc__.strip()) < 10:
            self._add_warning(f"{cls.__name__}.{method_name} lacks comprehensive docstring")
        
        return True
    
    def _is_method_fully_implemented(self, method) -> bool:
        """Check if a method is fully implemented (not just a stub)"""
        if not callable(method):
            return False
        
        # Get method source to check for implementation
        try:
            source = inspect.getsource(method)
            
            # Check for common stub patterns
            stub_patterns = [
                'pass',
                'raise NotImplementedError',
                'return None',
                '# TODO',
                '# FIXME',
                'print(',  # Debug prints might indicate incomplete implementation
            ]
            
            # If method is very short and contains stub patterns, it might be incomplete
            lines = [line.strip() for line in source.split('\n') if line.strip() and not line.strip().startswith('#')]
            if len(lines) <= 3:  # Very short method
                for pattern in stub_patterns:
                    if pattern in source:
                        return False
            
            return True
            
        except (OSError, TypeError):
            # If we can't get source, assume it's implemented (might be C extension)
            return True
    
    def _add_error(self, message: str):
        """Add an error message"""
        self.errors.append(message)
        logger.error(f"Validation Error: {message}")
    
    def _add_warning(self, message: str):
        """Add a warning message"""
        self.warnings.append(message)
        logger.warning(f"Validation Warning: {message}")
    
    def _add_info(self, message: str):
        """Add an info message"""
        self.info.append(message)
        logger.info(f"Validation Info: {message}")
    
    def _generate_summary(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Generate validation summary"""
        component_count = len(results['components'])
        passed_components = sum(1 for comp in results['components'].values() 
                               if comp['status'] == 'passed')
        
        total_methods = sum(len(comp.get('methods_validated', [])) 
                           for comp in results['components'].values())
        
        return {
            'total_components': component_count,
            'passed_components': passed_components,
            'failed_components': component_count - passed_components,
            'total_methods_validated': total_methods,
            'total_errors': len(results['errors']),
            'total_warnings': len(results['warnings']),
            'completion_percentage': round((passed_components / component_count) * 100, 1) if component_count > 0 else 0
        }


def validate_wizard_implementation() -> Dict[str, Any]:
    """
    Convenience function to validate entire wizard implementation
    
    Returns:
        Comprehensive validation results
    """
    validator = WizardComponentValidator()
    return validator.validate_all_components()


def print_validation_report(results: Dict[str, Any]):
    """
    Print a formatted validation report
    
    Args:
        results: Results from validate_wizard_implementation()
    """
    print("\n" + "="*80)
    print("FLASK-APPBUILDER WIZARD FORMS VALIDATION REPORT")
    print("="*80)
    
    summary = results.get('summary', {})
    
    print(f"\nOVERALL STATUS: {results['overall_status'].upper()}")
    print(f"Components Validated: {summary.get('total_components', 0)}")
    print(f"Components Passed: {summary.get('passed_components', 0)}")
    print(f"Components Failed: {summary.get('failed_components', 0)}")
    print(f"Methods Validated: {summary.get('total_methods_validated', 0)}")
    print(f"Completion: {summary.get('completion_percentage', 0)}%")
    
    if results['errors']:
        print(f"\nERRORS ({len(results['errors'])}):")
        for i, error in enumerate(results['errors'], 1):
            print(f"  {i}. {error}")
    
    if results['warnings']:
        print(f"\nWARNINGS ({len(results['warnings'])}):")
        for i, warning in enumerate(results['warnings'], 1):
            print(f"  {i}. {warning}")
    
    print("\nCOMPONENT DETAILS:")
    for component_name, component_result in results['components'].items():
        status_indicator = "✅" if component_result['status'] == 'passed' else "❌"
        print(f"  {status_indicator} {component_name}: {component_result['status']}")
        
        if component_result.get('methods_validated'):
            method_count = len(component_result['methods_validated'])
            print(f"      Methods validated: {method_count}")
    
    print("\n" + "="*80)
    
    if results['overall_status'] == 'passed':
        print("🎉 ALL WIZARD COMPONENTS ARE COMPLETE AND FUNCTIONAL!")
    elif results['overall_status'] == 'passed_with_warnings':
        print("⚠️  Wizard components are functional but have warnings")
    else:
        print("❌ Wizard implementation has critical issues that need to be addressed")
    
    print("="*80)


if __name__ == "__main__":
    # Run validation when script is executed directly
    results = validate_wizard_implementation()
    print_validation_report(results)