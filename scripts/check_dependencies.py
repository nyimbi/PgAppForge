#!/usr/bin/env python3
"""
Flask-AppBuilder Dependencies Checker

This script checks if all required dependencies are properly installed
and configured for Flask-AppBuilder tutorials.

Usage:
    python scripts/check_dependencies.py
    python scripts/check_dependencies.py --fix-missing
    python scripts/check_dependencies.py --ai-only
    python scripts/check_dependencies.py --collaborative-only
"""

import sys
import os
import argparse
import importlib
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json


class DependencyChecker:
    """Check and validate Flask-AppBuilder dependencies."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.missing_deps = []
        self.optional_missing = []
        
    def log(self, message: str, level: str = "INFO"):
        """Log message with level indicator."""
        if self.verbose:
            colors = {
                "INFO": "\033[94m",    # Blue
                "SUCCESS": "\033[92m", # Green
                "WARNING": "\033[93m", # Yellow
                "ERROR": "\033[91m",   # Red
                "END": "\033[0m"       # Reset
            }
            
            color = colors.get(level, colors["INFO"])
            print(f"{color}[{level}] {message}{colors['END']}")
    
    def check_python_version(self) -> bool:
        """Check Python version meets requirements."""
        self.log("Checking Python version...")
        
        version = sys.version_info
        required = (3, 9)
        
        if version >= required:
            self.log(f"✅ Python {version.major}.{version.minor}.{version.micro} (≥{required[0]}.{required[1]} required)", "SUCCESS")
            return True
        else:
            self.log(f"❌ Python {version.major}.{version.minor}.{version.micro} (≥{required[0]}.{required[1]} required)", "ERROR")
            return False
    
    def check_package(self, package_name: str, import_name: str = None, description: str = "") -> bool:
        """Check if a package can be imported."""
        import_name = import_name or package_name
        
        try:
            module = importlib.import_module(import_name)
            
            # Get version if available
            version = getattr(module, '__version__', 'unknown')
            self.log(f"✅ {package_name} ({version}) - {description}", "SUCCESS")
            return True
            
        except ImportError as e:
            self.log(f"❌ {package_name} - {description}: {str(e)}", "ERROR")
            return False
    
    def check_core_dependencies(self) -> Dict[str, bool]:
        """Check core Flask-AppBuilder dependencies."""
        self.log("\n📦 Checking Core Dependencies:")
        
        core_deps = {
            'flask': {'import': 'flask', 'desc': 'Flask web framework'},
            'flask-appbuilder': {'import': 'flask_appbuilder', 'desc': 'Flask-AppBuilder framework'},
            'sqlalchemy': {'import': 'sqlalchemy', 'desc': 'SQLAlchemy ORM'},
            'wtforms': {'import': 'wtforms', 'desc': 'WTForms for form handling'},
            'flask-babel': {'import': 'flask_babel', 'desc': 'Flask-Babel for i18n'},
            'apispec': {'import': 'apispec', 'desc': 'API documentation'},
            'marshmallow': {'import': 'marshmallow', 'desc': 'Serialization library'},
            'click': {'import': 'click', 'desc': 'Command line interface'},
            'colorama': {'import': 'colorama', 'desc': 'Colored terminal output'},
            'email-validator': {'import': 'email_validator', 'desc': 'Email validation'},
            'flask-jwt-extended': {'import': 'flask_jwt_extended', 'desc': 'JWT tokens'},
            'flask-limiter': {'import': 'flask_limiter', 'desc': 'Rate limiting'},
            'flask-login': {'import': 'flask_login', 'desc': 'User session management'},
            'flask-sqlalchemy': {'import': 'flask_sqlalchemy', 'desc': 'SQLAlchemy integration'},
            'flask-wtf': {'import': 'flask_wtf', 'desc': 'WTForms integration'},
            'jinja2': {'import': 'jinja2', 'desc': 'Template engine'},
            'markupsafe': {'import': 'markupsafe', 'desc': 'Safe markup handling'},
            'werkzeug': {'import': 'werkzeug', 'desc': 'WSGI utility library'}
        }
        
        results = {}
        for package, info in core_deps.items():
            success = self.check_package(package, info['import'], info['desc'])
            results[package] = success
            if not success:
                self.missing_deps.append(package)
        
        return results
    
    def check_ai_dependencies(self) -> Dict[str, bool]:
        """Check AI provider dependencies."""
        self.log("\n🤖 Checking AI Dependencies:")
        
        ai_deps = {
            'openai': {'import': 'openai', 'desc': 'OpenAI API client'},
            'anthropic': {'import': 'anthropic', 'desc': 'Anthropic Claude API client'},
            'google-generativeai': {'import': 'google.generativeai', 'desc': 'Google Gemini API client'},
            'groq': {'import': 'groq', 'desc': 'Groq fast inference API client'},
            'huggingface-hub': {'import': 'huggingface_hub', 'desc': 'HuggingFace model hub'},
            'transformers': {'import': 'transformers', 'desc': 'HuggingFace transformers'},
            'torch': {'import': 'torch', 'desc': 'PyTorch for local AI models'},
            'speechrecognition': {'import': 'speech_recognition', 'desc': 'Speech-to-text processing'},
            'pydub': {'import': 'pydub', 'desc': 'Audio processing'},
            'soundfile': {'import': 'soundfile', 'desc': 'Audio file handling'}
        }
        
        results = {}
        for package, info in ai_deps.items():
            success = self.check_package(package, info['import'], info['desc'])
            results[package] = success
            if not success:
                self.optional_missing.append(package)
        
        available_count = sum(results.values())
        total_count = len(results)
        
        if available_count == 0:
            self.log(f"⚠️  No AI providers available. Install at least one for AI features.", "WARNING")
        else:
            self.log(f"ℹ️  AI providers: {available_count}/{total_count} available", "INFO")
        
        return results
    
    def check_collaborative_dependencies(self) -> Dict[str, bool]:
        """Check collaborative feature dependencies."""
        self.log("\n👥 Checking Collaborative Dependencies:")
        
        collab_deps = {
            'redis': {'import': 'redis', 'desc': 'Redis client for real-time features'},
            'flask-socketio': {'import': 'flask_socketio', 'desc': 'WebSocket support for Flask'},
            'python-socketio': {'import': 'socketio', 'desc': 'SocketIO client/server'},
            'python-engineio': {'import': 'engineio', 'desc': 'Engine.IO transport layer'},
            'eventlet': {'import': 'eventlet', 'desc': 'Async networking for SocketIO'}
        }
        
        results = {}
        for package, info in collab_deps.items():
            success = self.check_package(package, info['import'], info['desc'])
            results[package] = success
            if not success:
                self.optional_missing.append(package)
        
        available_count = sum(results.values())
        total_count = len(results)
        
        if available_count == 0:
            self.log(f"⚠️  No collaborative features available. Install Redis and SocketIO for real-time features.", "WARNING")
        else:
            self.log(f"ℹ️  Collaborative features: {available_count}/{total_count} available", "INFO")
        
        return results
    
    def check_optional_dependencies(self) -> Dict[str, bool]:
        """Check optional enhancement dependencies."""
        self.log("\n🔧 Checking Optional Dependencies:")
        
        optional_deps = {
            'openpyxl': {'import': 'openpyxl', 'desc': 'Excel export functionality'},
            'reportlab': {'import': 'reportlab', 'desc': 'PDF generation'},
            'pillow': {'import': 'PIL', 'desc': 'Image processing'},
            'qrcode': {'import': 'qrcode', 'desc': 'QR code generation for MFA'},
            'flask-mail': {'import': 'flask_mail', 'desc': 'Email functionality'},
            'twilio': {'import': 'twilio', 'desc': 'SMS functionality via Twilio'},
            'boto3': {'import': 'boto3', 'desc': 'AWS services integration'},
            'stripe': {'import': 'stripe', 'desc': 'Payment processing'},
            'pandas': {'import': 'pandas', 'desc': 'Data analysis for dashboards'},
            'numpy': {'import': 'numpy', 'desc': 'Numerical computing'},
            'matplotlib': {'import': 'matplotlib', 'desc': 'Chart generation'},
            'authlib': {'import': 'authlib', 'desc': 'OAuth provider support'},
            'flask-talisman': {'import': 'flask_talisman', 'desc': 'Security headers'}
        }
        
        results = {}
        for package, info in optional_deps.items():
            success = self.check_package(package, info['import'], info['desc'])
            results[package] = success
            if not success:
                self.optional_missing.append(package)
        
        return results
    
    def check_development_dependencies(self) -> Dict[str, bool]:
        """Check development and testing dependencies."""
        self.log("\n🛠️  Checking Development Dependencies:")
        
        dev_deps = {
            'pytest': {'import': 'pytest', 'desc': 'Testing framework'},
            'pytest-cov': {'import': 'pytest_cov', 'desc': 'Coverage reporting'},
            'black': {'import': 'black', 'desc': 'Code formatting'},
            'flake8': {'import': 'flake8', 'desc': 'Code linting'},
            'mypy': {'import': 'mypy', 'desc': 'Type checking'},
            'pre-commit': {'import': 'pre_commit', 'desc': 'Git hooks'},
            'nose2': {'import': 'nose2', 'desc': 'Alternative testing framework'}
        }
        
        results = {}
        for package, info in dev_deps.items():
            success = self.check_package(package, info['import'], info['desc'])
            results[package] = success
            if not success:
                self.optional_missing.append(package)
        
        return results
    
    def check_enhanced_features(self) -> Dict[str, bool]:
        """Check if Flask-AppBuilder enhanced features are available."""
        self.log("\n✨ Checking Enhanced Features:")
        
        features = {
            'AI Integration': 'flask_appbuilder.collaborative.ai.ai_models',
            'Collaborative Features': 'flask_appbuilder.collaborative.realtime.websocket_manager',
            'MFA Security': 'flask_appbuilder.security.mfa.models',
            'Process Workflows': 'flask_appbuilder.process.engine.process_engine',
            'Advanced Widgets': 'flask_appbuilder.widgets.modern_ui'
        }
        
        results = {}
        for feature_name, module_path in features.items():
            try:
                importlib.import_module(module_path)
                self.log(f"✅ {feature_name}", "SUCCESS")
                results[feature_name] = True
            except ImportError:
                self.log(f"❌ {feature_name} - Module not found: {module_path}", "ERROR")
                results[feature_name] = False
        
        return results
    
    def check_external_services(self) -> Dict[str, bool]:
        """Check connectivity to external services."""
        self.log("\n🌐 Checking External Service Connectivity:")
        
        results = {}
        
        # Test Redis connection
        try:
            import redis
            r = redis.Redis(host='localhost', port=6379, db=0, socket_timeout=2)
            r.ping()
            self.log("✅ Redis server (localhost:6379)", "SUCCESS")
            results['redis'] = True
        except Exception as e:
            self.log(f"❌ Redis server (localhost:6379): {str(e)}", "ERROR")
            results['redis'] = False
        
        # Test database connectivity (SQLite is always available)
        try:
            import sqlite3
            conn = sqlite3.connect(':memory:')
            conn.close()
            self.log("✅ SQLite database support", "SUCCESS")
            results['sqlite'] = True
        except Exception as e:
            self.log(f"❌ SQLite database support: {str(e)}", "ERROR")
            results['sqlite'] = False
        
        # Test AI provider API keys (without making actual calls)
        ai_keys = {
            'OpenAI': 'OPENAI_API_KEY',
            'Anthropic': 'ANTHROPIC_API_KEY', 
            'Groq': 'GROQ_API_KEY',
            'Google': 'GOOGLE_API_KEY'
        }
        
        for provider, env_var in ai_keys.items():
            if os.environ.get(env_var):
                self.log(f"✅ {provider} API key configured", "SUCCESS")
                results[f'{provider.lower()}_api_key'] = True
            else:
                self.log(f"⚠️  {provider} API key not configured ({env_var})", "WARNING")
                results[f'{provider.lower()}_api_key'] = False
        
        return results
    
    def suggest_installation(self) -> List[str]:
        """Suggest installation commands for missing dependencies."""
        suggestions = []
        
        if self.missing_deps:
            suggestions.append("\n🔧 Install missing core dependencies:")
            suggestions.append(f"pip install {' '.join(self.missing_deps)}")
        
        if self.optional_missing:
            # Group optional dependencies
            ai_deps = ['openai', 'anthropic', 'google-generativeai', 'groq', 'transformers', 'torch']
            collab_deps = ['redis', 'flask-socketio', 'python-socketio', 'eventlet']
            export_deps = ['openpyxl', 'reportlab', 'pillow']
            
            ai_missing = [dep for dep in ai_deps if dep in self.optional_missing]
            collab_missing = [dep for dep in collab_deps if dep in self.optional_missing]
            export_missing = [dep for dep in export_deps if dep in self.optional_missing]
            
            if ai_missing:
                suggestions.append("\n🤖 For AI features:")
                suggestions.append(f"pip install {' '.join(ai_missing)}")
            
            if collab_missing:
                suggestions.append("\n👥 For collaborative features:")
                suggestions.append(f"pip install {' '.join(collab_missing)}")
            
            if export_missing:
                suggestions.append("\n📊 For export features:")
                suggestions.append(f"pip install {' '.join(export_missing)}")
        
        # Installation via extras_require
        suggestions.append("\n💡 Or install with extras:")
        suggestions.append("pip install flask-appbuilder[mfa,export,analytics,oauth]")
        
        return suggestions
    
    def print_summary(self, all_results: Dict):
        """Print a comprehensive summary."""
        self.log("\n📊 Dependency Summary:", "INFO")
        self.log("=" * 50, "INFO")
        
        # Core dependencies
        core_results = all_results.get('core', {})
        core_success = sum(core_results.values())
        core_total = len(core_results)
        
        if core_success == core_total:
            self.log(f"✅ Core Dependencies: {core_success}/{core_total} (All required dependencies available)", "SUCCESS")
        else:
            self.log(f"❌ Core Dependencies: {core_success}/{core_total} (Missing critical dependencies)", "ERROR")
        
        # AI dependencies
        ai_results = all_results.get('ai', {})
        ai_success = sum(ai_results.values())
        ai_total = len(ai_results)
        
        if ai_success == 0:
            self.log(f"⚠️  AI Features: {ai_success}/{ai_total} (No AI providers available)", "WARNING")
        elif ai_success >= 2:
            self.log(f"✅ AI Features: {ai_success}/{ai_total} (Multiple providers available)", "SUCCESS")
        else:
            self.log(f"⚠️  AI Features: {ai_success}/{ai_total} (Limited AI capability)", "WARNING")
        
        # Collaborative dependencies
        collab_results = all_results.get('collaborative', {})
        collab_success = sum(collab_results.values())
        collab_total = len(collab_results)
        
        if collab_success >= 3:  # Need at least Redis, SocketIO, and one transport
            self.log(f"✅ Collaborative Features: {collab_success}/{collab_total} (Real-time features available)", "SUCCESS")
        else:
            self.log(f"⚠️  Collaborative Features: {collab_success}/{collab_total} (Limited real-time capability)", "WARNING")
        
        # Enhanced features
        enhanced_results = all_results.get('enhanced', {})
        enhanced_success = sum(enhanced_results.values())
        enhanced_total = len(enhanced_results)
        
        if enhanced_success == enhanced_total:
            self.log(f"✅ Enhanced Features: {enhanced_success}/{enhanced_total} (All advanced features available)", "SUCCESS")
        else:
            self.log(f"⚠️  Enhanced Features: {enhanced_success}/{enhanced_total} (Some features unavailable)", "WARNING")
        
        # External services
        services_results = all_results.get('services', {})
        redis_available = services_results.get('redis', False)
        api_keys = sum(1 for k, v in services_results.items() if k.endswith('_api_key') and v)
        
        self.log(f"🌐 External Services:", "INFO")
        self.log(f"   Redis: {'✅ Available' if redis_available else '❌ Not available'}", "INFO")
        self.log(f"   AI API Keys: {api_keys} configured", "INFO")
        
        # Overall readiness
        self.log("\n🎯 Tutorial Readiness:", "INFO")
        
        if core_success == core_total:
            self.log("✅ Getting Started Tutorial: Ready", "SUCCESS")
        else:
            self.log("❌ Getting Started Tutorial: Missing dependencies", "ERROR")
        
        if core_success == core_total and collab_success >= 3:
            self.log("✅ Collaborative Tutorial: Ready", "SUCCESS")
        else:
            self.log("⚠️  Collaborative Tutorial: Install collaborative dependencies", "WARNING")
        
        if core_success == core_total and ai_success >= 1:
            self.log("✅ AI Integration Tutorial: Ready", "SUCCESS")
        else:
            self.log("⚠️  AI Integration Tutorial: Install AI provider libraries", "WARNING")
    
    def run_full_check(self, check_ai: bool = True, check_collaborative: bool = True) -> Dict:
        """Run complete dependency check."""
        self.log("🔍 Flask-AppBuilder Dependencies Check", "INFO")
        self.log("=" * 50, "INFO")
        
        results = {}
        
        # Python version
        results['python'] = self.check_python_version()
        
        # Core dependencies
        results['core'] = self.check_core_dependencies()
        
        # Optional feature dependencies
        if check_ai:
            results['ai'] = self.check_ai_dependencies()
        
        if check_collaborative:
            results['collaborative'] = self.check_collaborative_dependencies()
        
        # Enhanced features
        results['enhanced'] = self.check_enhanced_features()
        
        # Development dependencies
        results['development'] = self.check_development_dependencies()
        
        # Optional dependencies
        results['optional'] = self.check_optional_dependencies()
        
        # External services
        results['services'] = self.check_external_services()
        
        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check Flask-AppBuilder dependencies")
    parser.add_argument('--ai-only', action='store_true', help='Check only AI dependencies')
    parser.add_argument('--collaborative-only', action='store_true', help='Check only collaborative dependencies')
    parser.add_argument('--core-only', action='store_true', help='Check only core dependencies')
    parser.add_argument('--fix-missing', action='store_true', help='Show installation commands for missing packages')
    parser.add_argument('--quiet', action='store_true', help='Reduce output verbosity')
    parser.add_argument('--json', help='Output results as JSON to file')
    
    args = parser.parse_args()
    
    checker = DependencyChecker(verbose=not args.quiet)
    
    # Determine what to check
    check_ai = not (args.collaborative_only or args.core_only)
    check_collaborative = not (args.ai_only or args.core_only)
    
    if args.ai_only:
        results = {'ai': checker.check_ai_dependencies()}
    elif args.collaborative_only:
        results = {'collaborative': checker.check_collaborative_dependencies()}
    elif args.core_only:
        results = {'core': checker.check_core_dependencies()}
    else:
        results = checker.run_full_check(check_ai, check_collaborative)
    
    # Print summary
    if not args.quiet:
        checker.print_summary(results)
    
    # Show installation suggestions
    if args.fix_missing:
        suggestions = checker.suggest_installation()
        for suggestion in suggestions:
            checker.log(suggestion, "INFO")
    
    # Save JSON results
    if args.json:
        with open(args.json, 'w') as f:
            json.dump(results, f, indent=2)
        checker.log(f"Results saved to {args.json}", "INFO")
    
    # Exit with appropriate code
    if args.core_only or args.ai_only or args.collaborative_only:
        # For specific checks, only consider that category
        category_results = list(results.values())[0]
        success = sum(category_results.values()) > 0
    else:
        # For full check, require core dependencies
        core_results = results.get('core', {})
        success = sum(core_results.values()) == len(core_results)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()