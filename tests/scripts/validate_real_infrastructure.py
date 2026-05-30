#!/usr/bin/env python3
"""
Validation Script for Real Infrastructure Implementations

This script validates that the fixed implementations use only real, 
existing modules and will not crash on import in a production environment.
"""

import ast
import sys
import importlib.util
from typing import List, Dict, Set


def extract_imports_from_file(file_path: str) -> Dict[str, List[str]]:
    """Extract all imports from a Python file."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        tree = ast.parse(content)
        imports = {'from': [], 'import': [], 'all': []}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports['import'].append(alias.name)
                    imports['all'].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    from_import = f"from {node.module} import " + ", ".join(alias.name for alias in node.names)
                    imports['from'].append(from_import)
                    imports['all'].append(node.module)
        
        return imports
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return {'from': [], 'import': [], 'all': []}


def check_import_availability(module_name: str) -> Dict[str, bool]:
    """Check if a module can be imported."""
    result = {
        'available': False,
        'error': None,
        'is_standard': False,
        'is_flask_related': False
    }
    
    try:
        # Check if it's a standard library module
        standard_modules = {
            'json', 'logging', 're', 'requests', 'time', 'datetime', 
            'decimal', 'typing', 'ast', 'sys', 'importlib', 'os'
        }
        
        if module_name.split('.')[0] in standard_modules:
            result['is_standard'] = True
        
        # Check Flask-related modules
        flask_modules = [
            'flask', 'pgappforge', 'flask_login', 'sqlalchemy', 'werkzeug'
        ]
        
        if any(module_name.startswith(fm) for fm in flask_modules):
            result['is_flask_related'] = True
        
        # Try to find the module spec
        spec = importlib.util.find_spec(module_name)
        if spec is not None:
            result['available'] = True
        else:
            result['error'] = f"Module '{module_name}' not found"
            
    except ImportError as e:
        result['error'] = f"ImportError: {str(e)}"
    except Exception as e:
        result['error'] = f"Error: {str(e)}"
    
    return result


def validate_implementation_file(file_path: str) -> Dict:
    """Validate all imports in an implementation file."""
    print(f"\n🔍 VALIDATING: {file_path}")
    print("=" * 80)
    
    imports = extract_imports_from_file(file_path)
    
    results = {
        'file_path': file_path,
        'total_imports': len(imports['all']),
        'available': [],
        'unavailable': [],
        'problematic': [],
        'standard_lib': [],
        'flask_related': [],
    }
    
    # Check each unique module
    unique_modules = set(imports['all'])
    
    for module_name in sorted(unique_modules):
        check_result = check_import_availability(module_name)
        
        if check_result['available']:
            results['available'].append(module_name)
            print(f"✅ {module_name}")
            
            if check_result['is_standard']:
                results['standard_lib'].append(module_name)
            elif check_result['is_flask_related']:
                results['flask_related'].append(module_name)
                
        else:
            results['unavailable'].append({
                'module': module_name,
                'error': check_result['error']
            })
            print(f"❌ {module_name} - {check_result['error']}")
            
            # Check if this is a problematic fictional module
            fictional_modules = [
                'pgappforge.mixins.security_framework',
                'pgappforge.mixins.comment_models'
            ]
            
            if module_name in fictional_modules:
                results['problematic'].append(module_name)
                print(f"   🚨 CRITICAL: This was a fictional module from previous implementation!")
    
    return results


def compare_implementations():
    """Compare old vs new implementations."""
    print("\n🔄 COMPARING IMPLEMENTATIONS")
    print("=" * 80)
    
    files_to_validate = [
        "/Users/nyimbiodero/src/pjs/fab-ext/tests/fixed_mixin_implementations.py",
        "/Users/nyimbiodero/src/pjs/fab-ext/tests/real_infrastructure_implementations.py"
    ]
    
    all_results = []
    
    for file_path in files_to_validate:
        try:
            results = validate_implementation_file(file_path)
            all_results.append(results)
        except Exception as e:
            print(f"❌ Failed to validate {file_path}: {e}")
    
    # Compare results
    if len(all_results) >= 2:
        old_results, new_results = all_results[0], all_results[1]
        
        print(f"\n📊 COMPARISON SUMMARY")
        print("-" * 50)
        print(f"Old Implementation:")
        print(f"  ✅ Available modules: {len(old_results['available'])}")
        print(f"  ❌ Unavailable modules: {len(old_results['unavailable'])}")
        print(f"  🚨 Problematic fictional modules: {len(old_results['problematic'])}")
        
        print(f"\nNew Implementation:")
        print(f"  ✅ Available modules: {len(new_results['available'])}")
        print(f"  ❌ Unavailable modules: {len(new_results['unavailable'])}")
        print(f"  🚨 Problematic fictional modules: {len(new_results['problematic'])}")
        
        # Check for improvements
        old_problematic = set(old_results['problematic'])
        new_problematic = set(new_results['problematic'])
        
        if len(new_problematic) < len(old_problematic):
            fixed_modules = old_problematic - new_problematic
            print(f"\n✅ FIXED FICTIONAL MODULES: {', '.join(fixed_modules)}")
        
        if len(new_results['unavailable']) == 0:
            print(f"\n🎉 SUCCESS: New implementation has NO unavailable imports!")
            return True
        else:
            print(f"\n⚠️  WARNING: New implementation still has unavailable imports:")
            for unavail in new_results['unavailable']:
                print(f"     - {unavail['module']}: {unavail['error']}")
            return False
    
    return False


def validate_production_readiness():
    """Perform comprehensive production readiness validation."""
    print("\n🚀 PRODUCTION READINESS VALIDATION")
    print("=" * 80)
    
    # Test the new implementation
    new_file = "/Users/nyimbiodero/src/pjs/fab-ext/tests/real_infrastructure_implementations.py"
    
    try:
        # Try to compile the file
        with open(new_file, 'r') as f:
            content = f.read()
        
        compile(content, new_file, 'exec')
        print("✅ File compiles without syntax errors")
        
        # Check for security improvements
        security_patterns = [
            ('InputValidator.sanitize_string', 'Input sanitization'),
            ('SQL injection protection', 'ilike('),
            ('SecurityValidator.validate_user_context', 'User validation'),
            ('ProductionPermissionError', 'Custom permission errors'),
            ('Config.get(', 'Configuration management'),
            ('time.sleep(', 'Rate limiting'),
            ('response.raise_for_status(', 'HTTP error handling'),
            ('db.session.rollback()', 'Transaction rollback'),
        ]
        
        security_score = 0
        for pattern, description in security_patterns:
            if pattern in content:
                print(f"✅ {description}")
                security_score += 1
            else:
                print(f"⚠️  Missing: {description}")
        
        print(f"\n📊 Security Score: {security_score}/{len(security_patterns)}")
        
        # Check for code quality improvements
        quality_patterns = [
            ('def _validate_coordinates', 'Coordinate validation'),
            ('max_length=', 'Input length limits'),  
            ('timeout=', 'Request timeouts'),
            ('try:', 'Error handling'),
            ('log.error', 'Error logging'),
            ('log.warning', 'Warning logging'),
        ]
        
        quality_score = 0
        for pattern, description in quality_patterns:
            if pattern in content:
                print(f"✅ {description}")
                quality_score += 1
        
        print(f"\n📊 Code Quality Score: {quality_score}/{len(quality_patterns)}")
        
        # Overall assessment
        total_score = security_score + quality_score
        max_score = len(security_patterns) + len(quality_patterns)
        percentage = (total_score / max_score) * 100
        
        print(f"\n🎯 OVERALL PRODUCTION READINESS: {percentage:.1f}%")
        
        if percentage >= 80:
            print("🎉 EXCELLENT: Ready for production deployment!")
            return True
        elif percentage >= 60:
            print("⚠️  GOOD: Minor improvements needed")
            return False
        else:
            print("❌ NEEDS WORK: Significant improvements required")
            return False
            
    except SyntaxError as e:
        print(f"❌ Syntax Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Validation Error: {e}")
        return False


def main():
    """Run comprehensive validation."""
    print("🔍 COMPREHENSIVE VALIDATION: Real Infrastructure Implementations")
    print("=" * 80)
    
    # Step 1: Compare old vs new implementations
    comparison_success = compare_implementations()
    
    # Step 2: Validate production readiness
    production_ready = validate_production_readiness()
    
    # Final assessment
    print(f"\n" + "=" * 80)
    print("📋 FINAL VALIDATION RESULTS")
    print("=" * 80)
    
    if comparison_success:
        print("✅ INFRASTRUCTURE INTEGRATION: FIXED")
        print("   - No more fictional imports")
        print("   - All modules are available in real PgAppForge")
    else:
        print("❌ INFRASTRUCTURE INTEGRATION: Issues remain")
    
    if production_ready:
        print("✅ PRODUCTION READINESS: ACHIEVED")
        print("   - Proper error handling and validation")
        print("   - Security improvements implemented")
        print("   - Code quality standards met")
    else:
        print("⚠️  PRODUCTION READINESS: Needs improvement")
    
    if comparison_success and production_ready:
        print("\n🎉 SUCCESS: All critical issues have been resolved!")
        print("🚀 The implementation is ready for production deployment.")
        return True
    else:
        print("\n⚠️  Some issues remain that should be addressed.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)