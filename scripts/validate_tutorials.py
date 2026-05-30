#!/usr/bin/env python3
"""
Flask-AppBuilder Tutorial Validation Script

This script validates that all tutorial examples can run correctly by:
1. Checking Python version and dependencies
2. Testing imports and configurations
3. Validating database connectivity
4. Testing AI provider connections
5. Running basic application startup tests

Usage:
    python scripts/validate_tutorials.py
    python scripts/validate_tutorials.py --tutorial getting_started
    python scripts/validate_tutorials.py --check-deps-only
"""

import sys
import os
import argparse
import importlib
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json


class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


class TutorialValidator:
    """Validates Flask-AppBuilder tutorial examples."""
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results = {}
        self.project_root = Path(__file__).parent.parent
        self.tutorials_dir = self.project_root / "examples"
        
    def log(self, message: str, level: str = "INFO", color: str = Colors.WHITE):
        """Log a message with optional color and level."""
        if self.verbose:
            timestamp = ""  # Simplified for now
            level_color = {
                "INFO": Colors.BLUE,
                "SUCCESS": Colors.GREEN,
                "WARNING": Colors.YELLOW,
                "ERROR": Colors.RED,
                "DEBUG": Colors.CYAN
            }.get(level, Colors.WHITE)
            
            print(f"{level_color}[{level}]{Colors.END} {color}{message}{Colors.END}")
    
    def run_command(self, command: List[str], cwd: Optional[Path] = None, timeout: int = 30) -> Tuple[bool, str, str]:
        """Run a shell command and return success status and output."""
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {timeout} seconds"
        except Exception as e:
            return False, "", str(e)
    
    def check_python_version(self) -> bool:
        """Check if Python version meets requirements."""
        self.log("Checking Python version...", "INFO")
        
        version = sys.version_info
        required_major, required_minor = 3, 9
        
        if version.major >= required_major and version.minor >= required_minor:
            self.log(f"✅ Python {version.major}.{version.minor}.{version.micro} (meets requirement ≥{required_major}.{required_minor})", "SUCCESS", Colors.GREEN)
            return True
        else:
            self.log(f"❌ Python {version.major}.{version.minor}.{version.micro} (requires ≥{required_major}.{required_minor})", "ERROR", Colors.RED)
            return False
    
    def check_core_dependencies(self) -> Dict[str, bool]:
        """Check if core dependencies can be imported."""
        self.log("Checking core dependencies...", "INFO")
        
        dependencies = {
            'flask': 'Flask web framework',
            'flask_appbuilder': 'Flask-AppBuilder framework',
            'sqlalchemy': 'SQLAlchemy ORM',
            'wtforms': 'WTForms for form handling',
            'babel': 'Babel for internationalization'
        }
        
        results = {}
        for dep, description in dependencies.items():
            try:
                importlib.import_module(dep)
                self.log(f"✅ {dep}: {description}", "SUCCESS", Colors.GREEN)
                results[dep] = True
            except ImportError as e:
                self.log(f"❌ {dep}: {description} - {str(e)}", "ERROR", Colors.RED)
                results[dep] = False
        
        return results
    
    def check_ai_dependencies(self) -> Dict[str, bool]:
        """Check if AI provider dependencies are available."""
        self.log("Checking AI dependencies...", "INFO")
        
        ai_deps = {
            'openai': 'OpenAI API client',
            'anthropic': 'Anthropic API client',
            'google.generativeai': 'Google Gemini API client',
            'groq': 'Groq API client'
        }
        
        results = {}
        for dep, description in ai_deps.items():
            try:
                importlib.import_module(dep)
                self.log(f"✅ {dep}: {description}", "SUCCESS", Colors.GREEN)
                results[dep] = True
            except ImportError:
                self.log(f"⚠️  {dep}: {description} - Optional for AI features", "WARNING", Colors.YELLOW)
                results[dep] = False
        
        return results
    
    def check_collaborative_dependencies(self) -> Dict[str, bool]:
        """Check if collaborative feature dependencies are available."""
        self.log("Checking collaborative dependencies...", "INFO")
        
        collab_deps = {
            'redis': 'Redis client for real-time features',
            'flask_socketio': 'WebSocket support for Flask',
            'eventlet': 'Async networking for SocketIO'
        }
        
        results = {}
        for dep, description in collab_deps.items():
            try:
                importlib.import_module(dep)
                self.log(f"✅ {dep}: {description}", "SUCCESS", Colors.GREEN)
                results[dep] = True
            except ImportError:
                self.log(f"⚠️  {dep}: {description} - Optional for collaborative features", "WARNING", Colors.YELLOW)
                results[dep] = False
        
        return results
    
    def test_flask_appbuilder_imports(self) -> bool:
        """Test that Flask-AppBuilder enhanced features can be imported."""
        self.log("Testing Flask-AppBuilder enhanced imports...", "INFO")
        
        enhanced_imports = [
            ('flask_appbuilder.collaborative.ai.ai_models', 'AIModelManager'),
            ('flask_appbuilder.collaborative.realtime.websocket_manager', 'WebSocketManager'),
            ('flask_appbuilder.security.mfa.models', 'MFACredential'),
            ('flask_appbuilder.process.engine.process_engine', 'ProcessEngine')
        ]
        
        success = True
        for module_name, class_name in enhanced_imports:
            try:
                module = importlib.import_module(module_name)
                getattr(module, class_name)
                self.log(f"✅ {module_name}.{class_name}", "SUCCESS", Colors.GREEN)
            except (ImportError, AttributeError) as e:
                self.log(f"❌ {module_name}.{class_name} - {str(e)}", "ERROR", Colors.RED)
                success = False
        
        return success
    
    def test_tutorial_structure(self, tutorial_name: str) -> bool:
        """Test that tutorial directory structure is correct."""
        self.log(f"Checking tutorial structure: {tutorial_name}", "INFO")
        
        tutorial_path = self.tutorials_dir / f"tutorial_{tutorial_name}"
        if not tutorial_path.exists():
            self.log(f"❌ Tutorial directory not found: {tutorial_path}", "ERROR", Colors.RED)
            return False
        
        required_files = [
            'README.md',
            'requirements.txt',
            'app.py',
            'config.py',
            'models.py',
            'views.py'
        ]
        
        success = True
        for file_name in required_files:
            file_path = tutorial_path / file_name
            if file_path.exists():
                self.log(f"✅ {file_name}", "SUCCESS", Colors.GREEN)
            else:
                self.log(f"❌ Missing: {file_name}", "ERROR", Colors.RED)
                success = False
        
        # Check templates directory
        templates_path = tutorial_path / "templates"
        if templates_path.exists():
            self.log(f"✅ templates/ directory", "SUCCESS", Colors.GREEN)
        else:
            self.log(f"⚠️  templates/ directory missing - may use default templates", "WARNING", Colors.YELLOW)
        
        return success
    
    def test_tutorial_imports(self, tutorial_name: str) -> bool:
        """Test that tutorial Python files can be imported without errors."""
        self.log(f"Testing tutorial imports: {tutorial_name}", "INFO")
        
        tutorial_path = self.tutorials_dir / f"tutorial_{tutorial_name}"
        if not tutorial_path.exists():
            return False
        
        # Add tutorial path to Python path
        sys.path.insert(0, str(tutorial_path))
        
        try:
            # Test importing config
            try:
                import config
                self.log("✅ config.py imports successfully", "SUCCESS", Colors.GREEN)
            except Exception as e:
                self.log(f"❌ config.py import failed: {str(e)}", "ERROR", Colors.RED)
                return False
            
            # Test importing models
            try:
                import models
                self.log("✅ models.py imports successfully", "SUCCESS", Colors.GREEN)
            except Exception as e:
                self.log(f"❌ models.py import failed: {str(e)}", "ERROR", Colors.RED)
                return False
            
            # Test importing views
            try:
                import views
                self.log("✅ views.py imports successfully", "SUCCESS", Colors.GREEN)
            except Exception as e:
                self.log(f"❌ views.py import failed: {str(e)}", "ERROR", Colors.RED)
                return False
            
            return True
            
        finally:
            # Clean up Python path
            if str(tutorial_path) in sys.path:
                sys.path.remove(str(tutorial_path))
            
            # Remove imported modules to avoid conflicts
            modules_to_remove = []
            for module_name in sys.modules:
                if module_name in ['config', 'models', 'views'] and hasattr(sys.modules[module_name], '__file__'):
                    module_file = sys.modules[module_name].__file__
                    if module_file and str(tutorial_path) in module_file:
                        modules_to_remove.append(module_name)
            
            for module_name in modules_to_remove:
                del sys.modules[module_name]
    
    def test_database_operations(self, tutorial_name: str) -> bool:
        """Test basic database operations for the tutorial."""
        self.log(f"Testing database operations: {tutorial_name}", "INFO")
        
        tutorial_path = self.tutorials_dir / f"tutorial_{tutorial_name}"
        if not tutorial_path.exists():
            return False
        
        # Create a temporary directory for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Copy tutorial files to temp directory
            for file_name in ['config.py', 'models.py', 'app.py']:
                src = tutorial_path / file_name
                dst = temp_path / file_name
                if src.exists():
                    shutil.copy2(src, dst)
            
            # Modify config for testing
            config_content = (temp_path / 'config.py').read_text()
            test_config = config_content.replace(
                "SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///tutorial_app.db')",
                f"SQLALCHEMY_DATABASE_URI = 'sqlite:///{temp_path}/test.db'"
            )
            (temp_path / 'config.py').write_text(test_config)
            
            # Test database creation
            sys.path.insert(0, str(temp_path))
            try:
                # Import and create app
                import config
                import models
                
                from flask import Flask
                from flask_appbuilder import AppBuilder, SQLA
                
                app = Flask(__name__)
                app.config.from_object(config)
                db = SQLA(app)
                appbuilder = AppBuilder(app, db.session)
                
                with app.app_context():
                    # Create tables
                    db.create_all()
                    
                    # Test basic model operations
                    category = models.TaskCategory(name='Test Category', description='Test description')
                    db.session.add(category)
                    db.session.commit()
                    
                    task = models.Task(title='Test Task', description='Test description', category=category)
                    db.session.add(task)
                    db.session.commit()
                    
                    # Verify data
                    assert db.session.query(models.TaskCategory).count() == 1
                    assert db.session.query(models.Task).count() == 1
                
                self.log("✅ Database operations successful", "SUCCESS", Colors.GREEN)
                return True
                
            except Exception as e:
                self.log(f"❌ Database operations failed: {str(e)}", "ERROR", Colors.RED)
                return False
            finally:
                # Cleanup
                if str(temp_path) in sys.path:
                    sys.path.remove(str(temp_path))
                modules_to_remove = [m for m in sys.modules if m in ['config', 'models']]
                for m in modules_to_remove:
                    if m in sys.modules:
                        del sys.modules[m]
    
    def test_application_startup(self, tutorial_name: str) -> bool:
        """Test that the tutorial application can start up without errors."""
        self.log(f"Testing application startup: {tutorial_name}", "INFO")
        
        tutorial_path = self.tutorials_dir / f"tutorial_{tutorial_name}"
        app_file = tutorial_path / "app.py"
        
        if not app_file.exists():
            self.log(f"❌ app.py not found in {tutorial_path}", "ERROR", Colors.RED)
            return False
        
        # Test that app.py can be executed
        success, stdout, stderr = self.run_command(
            [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); from app import create_app; print('App creation successful')"],
            cwd=tutorial_path,
            timeout=15
        )
        
        if success and "App creation successful" in stdout:
            self.log("✅ Application startup successful", "SUCCESS", Colors.GREEN)
            return True
        else:
            self.log(f"❌ Application startup failed: {stderr}", "ERROR", Colors.RED)
            return False
    
    def test_requirements_installation(self, tutorial_name: str) -> bool:
        """Test that tutorial requirements can be installed."""
        self.log(f"Testing requirements installation: {tutorial_name}", "INFO")
        
        tutorial_path = self.tutorials_dir / f"tutorial_{tutorial_name}"
        requirements_file = tutorial_path / "requirements.txt"
        
        if not requirements_file.exists():
            self.log(f"❌ requirements.txt not found in {tutorial_path}", "ERROR", Colors.RED)
            return False
        
        # Create a temporary virtual environment
        with tempfile.TemporaryDirectory() as temp_dir:
            venv_path = Path(temp_dir) / "test_venv"
            
            # Create virtual environment
            success, stdout, stderr = self.run_command([
                sys.executable, "-m", "venv", str(venv_path)
            ], timeout=60)
            
            if not success:
                self.log(f"❌ Failed to create virtual environment: {stderr}", "ERROR", Colors.RED)
                return False
            
            # Determine pip path
            if os.name == 'nt':  # Windows
                pip_path = venv_path / "Scripts" / "pip"
            else:  # Unix-like
                pip_path = venv_path / "bin" / "pip"
            
            # Install requirements
            success, stdout, stderr = self.run_command([
                str(pip_path), "install", "-r", str(requirements_file)
            ], timeout=300)  # 5 minutes timeout
            
            if success:
                self.log("✅ Requirements installation successful", "SUCCESS", Colors.GREEN)
                return True
            else:
                self.log(f"❌ Requirements installation failed: {stderr}", "ERROR", Colors.RED)
                return False
    
    def validate_tutorial(self, tutorial_name: str) -> Dict[str, bool]:
        """Validate a specific tutorial."""
        self.log(f"\n{Colors.BOLD}=== Validating Tutorial: {tutorial_name} ==={Colors.END}", "INFO")
        
        results = {}
        
        # Test tutorial structure
        results['structure'] = self.test_tutorial_structure(tutorial_name)
        
        # Test tutorial imports
        results['imports'] = self.test_tutorial_imports(tutorial_name)
        
        # Test database operations
        results['database'] = self.test_database_operations(tutorial_name)
        
        # Test application startup
        results['startup'] = self.test_application_startup(tutorial_name)
        
        # Test requirements installation (optional, can be slow)
        # results['requirements'] = self.test_requirements_installation(tutorial_name)
        
        return results
    
    def validate_all(self) -> Dict[str, any]:
        """Run comprehensive validation of all tutorials."""
        self.log(f"\n{Colors.BOLD}{Colors.CYAN}🔍 Flask-AppBuilder Tutorial Validation{Colors.END}", "INFO")
        self.log(f"{Colors.CYAN}{'=' * 50}{Colors.END}", "INFO")
        
        results = {
            'system': {},
            'dependencies': {},
            'tutorials': {}
        }
        
        # System checks
        self.log(f"\n{Colors.BOLD}📋 System Requirements{Colors.END}", "INFO")
        results['system']['python_version'] = self.check_python_version()
        
        # Dependency checks
        self.log(f"\n{Colors.BOLD}📦 Dependencies{Colors.END}", "INFO")
        results['dependencies']['core'] = self.check_core_dependencies()
        results['dependencies']['ai'] = self.check_ai_dependencies()
        results['dependencies']['collaborative'] = self.check_collaborative_dependencies()
        results['dependencies']['enhanced_imports'] = self.test_flask_appbuilder_imports()
        
        # Tutorial validation
        tutorials = ['getting_started']  # Add more tutorials as they're created
        
        for tutorial in tutorials:
            results['tutorials'][tutorial] = self.validate_tutorial(tutorial)
        
        # Summary
        self.print_summary(results)
        
        return results
    
    def print_summary(self, results: Dict):
        """Print validation summary."""
        self.log(f"\n{Colors.BOLD}{Colors.CYAN}📊 Validation Summary{Colors.END}", "INFO")
        self.log(f"{Colors.CYAN}{'=' * 30}{Colors.END}", "INFO")
        
        # System summary
        system_ok = all(results['system'].values())
        status = "✅ PASS" if system_ok else "❌ FAIL"
        color = Colors.GREEN if system_ok else Colors.RED
        self.log(f"System Requirements: {color}{status}{Colors.END}", "INFO")
        
        # Dependencies summary
        core_deps = results['dependencies']['core']
        core_ok = all(core_deps.values())
        status = "✅ PASS" if core_ok else "❌ FAIL"
        color = Colors.GREEN if core_ok else Colors.RED
        self.log(f"Core Dependencies: {color}{status}{Colors.END}", "INFO")
        
        ai_deps = results['dependencies']['ai']
        ai_count = sum(ai_deps.values())
        self.log(f"AI Dependencies: {Colors.YELLOW}⚠️  {ai_count}/{len(ai_deps)} available{Colors.END}", "INFO")
        
        # Tutorial summary
        for tutorial_name, tutorial_results in results['tutorials'].items():
            passed = sum(tutorial_results.values())
            total = len(tutorial_results)
            if passed == total:
                status = f"✅ PASS ({passed}/{total})"
                color = Colors.GREEN
            elif passed > total // 2:
                status = f"⚠️  PARTIAL ({passed}/{total})"
                color = Colors.YELLOW
            else:
                status = f"❌ FAIL ({passed}/{total})"
                color = Colors.RED
            
            self.log(f"Tutorial {tutorial_name}: {color}{status}{Colors.END}", "INFO")
        
        # Overall status
        overall_ok = (
            system_ok and 
            core_ok and 
            all(
                sum(tutorial_results.values()) == len(tutorial_results)
                for tutorial_results in results['tutorials'].values()
            )
        )
        
        self.log(f"\n{Colors.BOLD}Overall Status: ", "INFO", end="")
        if overall_ok:
            self.log(f"{Colors.GREEN}✅ ALL TUTORIALS READY{Colors.END}", "SUCCESS")
        else:
            self.log(f"{Colors.RED}❌ ISSUES FOUND - CHECK DETAILS ABOVE{Colors.END}", "ERROR")
    
    def generate_report(self, results: Dict, output_file: Optional[str] = None) -> str:
        """Generate a detailed validation report."""
        report = {
            'timestamp': str(Path(__file__).stat().st_mtime),  # Simplified timestamp
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            'validation_results': results
        }
        
        if output_file:
            Path(output_file).write_text(json.dumps(report, indent=2))
            self.log(f"📄 Report saved to: {output_file}", "INFO")
        
        return json.dumps(report, indent=2)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate Flask-AppBuilder tutorials")
    parser.add_argument(
        '--tutorial', 
        help='Validate specific tutorial (e.g., getting_started)',
        default=None
    )
    parser.add_argument(
        '--check-deps-only',
        action='store_true',
        help='Only check dependencies, skip tutorial validation'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Reduce output verbosity'
    )
    parser.add_argument(
        '--report',
        help='Generate JSON report file',
        default=None
    )
    
    args = parser.parse_args()
    
    validator = TutorialValidator(verbose=not args.quiet)
    
    if args.check_deps_only:
        # Only check dependencies
        validator.log(f"\n{Colors.BOLD}{Colors.CYAN}🔍 Dependency Check{Colors.END}", "INFO")
        results = {
            'system': {'python_version': validator.check_python_version()},
            'dependencies': {
                'core': validator.check_core_dependencies(),
                'ai': validator.check_ai_dependencies(),
                'collaborative': validator.check_collaborative_dependencies(),
                'enhanced_imports': validator.test_flask_appbuilder_imports()
            }
        }
    elif args.tutorial:
        # Validate specific tutorial
        results = {
            'system': {'python_version': validator.check_python_version()},
            'dependencies': {
                'core': validator.check_core_dependencies(),
                'enhanced_imports': validator.test_flask_appbuilder_imports()
            },
            'tutorials': {args.tutorial: validator.validate_tutorial(args.tutorial)}
        }
    else:
        # Full validation
        results = validator.validate_all()
    
    # Generate report if requested
    if args.report:
        validator.generate_report(results, args.report)
    
    # Return appropriate exit code
    if args.check_deps_only:
        success = all(results['dependencies']['core'].values())
    elif args.tutorial:
        tutorial_results = results['tutorials'][args.tutorial]
        success = sum(tutorial_results.values()) == len(tutorial_results)
    else:
        success = (
            all(results['system'].values()) and
            all(results['dependencies']['core'].values()) and
            all(
                sum(tutorial_results.values()) == len(tutorial_results)
                for tutorial_results in results['tutorials'].values()
            )
        )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()