"""
Flask-AppBuilder Workflow Generation CLI Commands

JHipster-inspired code generation from workflow definitions.
"""

import click
import os
import yaml
from pathlib import Path
from typing import Optional

from ..workflow.generators.wdl_generator import WorkflowCodeGenerator
from ..security.path_validation import validate_safe_path, PathTraversalError, InvalidPathError


@click.group(name='workflow')
def workflow():
    """JHipster-inspired workflow generation commands."""
    pass


@workflow.command('generate')
@click.argument('workflow_file', type=click.Path(exists=True, readable=True))
@click.option('--app-name', '-n', required=True, help='Name of the Flask-AppBuilder application')
@click.option('--output-dir', '-o', default='.', help='Output directory for generated code', type=click.Path())
@click.option('--format', default='yaml', type=click.Choice(['yaml', 'wdl']), help='Input format (yaml or wdl)')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing files without confirmation')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
@click.option('--dry-run', is_flag=True, help='Show what would be generated without creating files')
def generate_workflow(workflow_file: str, app_name: str, output_dir: str, format: str, 
                     force: bool, verbose: bool, dry_run: bool):
    """Generate Flask-AppBuilder code from workflow definition.
    
    Examples:
        flask fab workflow generate employee_onboarding.yaml --app-name my_app
        flask fab workflow generate workflow.wdl --app-name hr_system --output-dir ./generated
        flask fab workflow generate workflow.yaml --dry-run --verbose
    """
    try:
        click.echo("🚀 JHipster-inspired Flask-AppBuilder Workflow Generation")
        click.echo("=" * 60)
        
        # Validate inputs and paths for security
        try:
            workflow_path = validate_safe_path(workflow_file)
            output_path = validate_safe_path(output_dir)
        except (PathTraversalError, InvalidPathError) as e:
            click.echo(click.style(f"❌ Insecure path detected: {e}", fg='red'))
            return
        
        if not workflow_path.exists():
            click.echo(click.style(f"❌ Workflow file not found: {workflow_file}", fg='red'))
            return
        
        # Validate app name
        if not app_name.replace('_', '').replace('-', '').isalnum():
            click.echo(click.style("❌ App name must contain only letters, numbers, hyphens, and underscores", fg='red'))
            return
        
        if verbose:
            click.echo(f"📁 Workflow file: {workflow_path.absolute()}")
            click.echo(f"📦 App name: {app_name}")
            click.echo(f"📂 Output directory: {output_path.absolute()}")
            click.echo(f"📋 Format: {format}")
            click.echo()
        
        # Load and validate workflow definition
        click.echo("📋 Loading workflow definition...")
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if format == 'yaml' or workflow_path.suffix.lower() in ['.yaml', '.yml']:
                # Direct YAML parsing
                workflow_data = yaml.safe_load(content)
                click.echo("✅ YAML workflow loaded successfully")
            else:
                # WDL parsing (with YAML fallback)
                generator = WorkflowCodeGenerator(app_name)
                workflow_data = generator._parse_wdl_content(content)
                click.echo("✅ WDL workflow parsed successfully")
                
        except Exception as e:
            click.echo(click.style(f"❌ Failed to parse workflow file: {e}", fg='red'))
            if verbose:
                import traceback
                click.echo(traceback.format_exc())
            return
        
        # Validate workflow structure
        if not isinstance(workflow_data, dict):
            click.echo(click.style("❌ Invalid workflow format: must be a dictionary", fg='red'))
            return
        
        workflow_names = list(workflow_data.keys())
        if not workflow_names:
            click.echo(click.style("❌ No workflows found in definition", fg='red'))
            return
        
        workflow_name = workflow_names[0]
        workflow = workflow_data[workflow_name]
        
        if not isinstance(workflow, dict):
            click.echo(click.style(f"❌ Invalid workflow '{workflow_name}': must be a dictionary", fg='red'))
            return
        
        # Check required sections
        required_sections = ['steps']
        missing_sections = [s for s in required_sections if s not in workflow]
        if missing_sections:
            click.echo(click.style(f"❌ Missing required sections: {', '.join(missing_sections)}", fg='red'))
            return
        
        click.echo(f"📊 Workflow: {workflow.get('description', workflow_name)}")
        click.echo(f"📦 Version: {workflow.get('version', '1.0.0')}")
        
        # Show generation plan
        entities = workflow.get('entities', {})
        steps = workflow.get('steps', {})
        
        click.echo()
        click.echo("📋 Generation Plan:")
        click.echo(f"   • Models: {len([e for e in entities.values() if isinstance(e, dict)])}")
        click.echo(f"   • Views: {len(steps)}")
        click.echo(f"   • Forms: {len(steps)}")
        click.echo(f"   • Templates: {len(steps)}")
        click.echo(f"   • API endpoints: 1")
        click.echo(f"   • Tests: 1")
        click.echo(f"   • Migrations: 1")
        
        # Dry run mode
        if dry_run:
            click.echo()
            click.echo("🔍 DRY RUN MODE - No files will be created")
            click.echo()
            
            # Show what would be generated
            click.echo("📁 Files that would be generated:")
            
            # Models
            for entity_name, entity_data in entities.items():
                if isinstance(entity_data, dict):
                    model_file = f"models/{entity_name.lower()}_model.py"
                    click.echo(f"   📋 {model_file}")
            
            # Views and Forms
            for step_name in steps.keys():
                view_file = f"views/{step_name.lower()}_view.py"
                form_file = f"forms/{step_name.lower()}_form.py"
                template_file = f"templates/{step_name.lower()}.html"
                click.echo(f"   📊 {view_file}")
                click.echo(f"   📝 {form_file}")
                click.echo(f"   🎨 {template_file}")
            
            # Other files
            click.echo(f"   🌐 api/workflow_api.py")
            click.echo(f"   🧪 tests/test_{workflow_name.lower()}.py")
            click.echo(f"   🗄️  migrations/001_{workflow_name.lower()}.py")
            
            click.echo()
            click.echo("✅ Dry run completed. Run without --dry-run to generate files.")
            return
        
        # Check for existing files if not forcing
        if not force:
            existing_files = []
            check_paths = [
                output_path / "models",
                output_path / "views", 
                output_path / "forms",
                output_path / "templates",
                output_path / "api",
                output_path / "tests",
                output_path / "migrations"
            ]
            
            for check_path in check_paths:
                if check_path.exists() and any(check_path.iterdir()):
                    existing_files.extend([str(f) for f in check_path.iterdir() if f.is_file()])
            
            if existing_files:
                click.echo()
                click.echo(f"⚠️  Found {len(existing_files)} existing files in output directory")
                if not click.confirm("Continue and overwrite existing files?"):
                    click.echo("Generation cancelled.")
                    return
        
        # Generate code
        click.echo()
        click.echo("🏗️  Generating Flask-AppBuilder application...")
        
        try:
            generator = WorkflowCodeGenerator(app_name)
            
            # Set output directory
            generator.output_dir = output_path
            
            # Generate all components
            if format == 'yaml' or workflow_path.suffix.lower() in ['.yaml', '.yml']:
                # Use YAML data directly
                generated_files = generator.generate_from_yaml_data(workflow_data)
            else:
                # Use WDL parsing
                generated_files = generator.generate_from_file(str(workflow_path))
            
            click.echo()
            click.echo("✅ Generation completed successfully!")
            click.echo(f"📁 Generated {len(generated_files)} files:")
            
            # Group files by type
            file_types = {}
            for file_path in generated_files:
                rel_path = Path(file_path).relative_to(output_path) if output_path != Path('.') else Path(file_path)
                file_type = rel_path.parts[0] if rel_path.parts else 'root'
                if file_type not in file_types:
                    file_types[file_type] = []
                file_types[file_type].append(str(rel_path))
            
            for file_type, files in sorted(file_types.items()):
                click.echo(f"   📂 {file_type}:")
                for file_path in sorted(files):
                    click.echo(f"      • {file_path}")
            
            click.echo()
            click.echo("🎯 Next Steps:")
            click.echo("1. Review generated code")
            click.echo("2. Integrate with your Flask-AppBuilder application")
            click.echo("3. Run database migrations")
            click.echo("4. Register views with appbuilder.add_view()")
            click.echo("5. Test the generated workflow")
            
        except Exception as e:
            click.echo(click.style(f"❌ Generation failed: {e}", fg='red'))
            if verbose:
                import traceback
                click.echo(traceback.format_exc())
            return
            
    except Exception as e:
        click.echo(click.style(f"❌ Unexpected error: {e}", fg='red'))
        if verbose:
            import traceback
            click.echo(traceback.format_exc())


@workflow.command('validate')
@click.argument('workflow_file', type=click.Path(exists=True, readable=True))
@click.option('--format', default='auto', type=click.Choice(['auto', 'yaml', 'wdl']), help='Input format')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def validate_workflow(workflow_file: str, format: str, verbose: bool):
    """Validate a workflow definition file.
    
    Examples:
        flask fab workflow validate employee_onboarding.yaml
        flask fab workflow validate workflow.wdl --verbose
    """
    try:
        click.echo(f"🔍 Validating workflow: {workflow_file}")
        
        workflow_path = Path(workflow_file)
        
        # Auto-detect format
        if format == 'auto':
            if workflow_path.suffix.lower() in ['.yaml', '.yml']:
                format = 'yaml'
            elif workflow_path.suffix.lower() == '.wdl':
                format = 'wdl'
            else:
                format = 'yaml'  # Default to YAML
        
        # Load and parse
        with open(workflow_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if format == 'yaml':
            workflow_data = yaml.safe_load(content)
            click.echo("✅ YAML syntax valid")
        else:
            generator = WorkflowCodeGenerator('validation_app')
            workflow_data = generator._parse_wdl_content(content)
            click.echo("✅ WDL syntax valid")
        
        # Validate structure
        if not isinstance(workflow_data, dict):
            click.echo(click.style("❌ Invalid structure: must be a dictionary", fg='red'))
            return
        
        workflow_names = list(workflow_data.keys())
        if not workflow_names:
            click.echo(click.style("❌ No workflows found", fg='red'))
            return
        
        click.echo(f"📋 Found {len(workflow_names)} workflow(s)")
        
        for workflow_name in workflow_names:
            workflow = workflow_data[workflow_name]
            click.echo(f"🔧 Validating workflow: {workflow_name}")
            
            if not isinstance(workflow, dict):
                click.echo(click.style(f"❌ Invalid workflow '{workflow_name}': must be a dictionary", fg='red'))
                continue
            
            # Check required sections
            if 'steps' not in workflow:
                click.echo(click.style(f"❌ Missing required 'steps' section", fg='red'))
                continue
            
            steps = workflow['steps']
            if not isinstance(steps, dict):
                click.echo(click.style(f"❌ Invalid 'steps' section: must be a dictionary", fg='red'))
                continue
            
            click.echo(f"   ✅ {len(steps)} steps defined")
            
            # Validate entities if present
            entities = workflow.get('entities', {})
            if entities and isinstance(entities, dict):
                model_count = len([e for e in entities.values() if isinstance(e, dict)])
                ref_count = len([e for e in entities.values() if isinstance(e, str)])
                click.echo(f"   ✅ {len(entities)} entities ({model_count} generated, {ref_count} referenced)")
            
            # Check optional sections
            optional_sections = ['permissions', 'notifications', 'features', 'ui', 'security', 'metadata']
            present_sections = [s for s in optional_sections if s in workflow]
            if present_sections:
                click.echo(f"   ✅ Optional sections: {', '.join(present_sections)}")
            
            click.echo(f"   ✅ Workflow '{workflow_name}' is valid")
        
        click.echo()
        click.echo("🎉 Validation completed successfully!")
        
    except yaml.YAMLError as e:
        click.echo(click.style(f"❌ YAML parsing error: {e}", fg='red'))
    except Exception as e:
        click.echo(click.style(f"❌ Validation failed: {e}", fg='red'))
        if verbose:
            import traceback
            click.echo(traceback.format_exc())


@workflow.command('init')
@click.argument('workflow_name')
@click.option('--format', default='yaml', type=click.Choice(['yaml', 'wdl']), help='Output format')
@click.option('--output', '-o', help='Output file path')
@click.option('--template', default='basic', type=click.Choice(['basic', 'crud', 'approval']), 
              help='Workflow template')
def init_workflow(workflow_name: str, format: str, output: Optional[str], template: str):
    """Create a new workflow definition from template.
    
    Examples:
        flask fab workflow init employee_onboarding --template approval
        flask fab workflow init user_registration --format wdl
    """
    try:
        click.echo(f"🚀 Creating new workflow: {workflow_name}")
        
        # Determine output file
        if output:
            output_path = Path(output)
        else:
            extension = 'yaml' if format == 'yaml' else 'wdl'
            output_path = Path(f"{workflow_name}.{extension}")
        
        if output_path.exists():
            if not click.confirm(f"File {output_path} exists. Overwrite?"):
                click.echo("Cancelled.")
                return
        
        # Generate template content
        template_content = _generate_workflow_template(workflow_name, template, format)
        
        # Write file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        click.echo(f"✅ Created workflow definition: {output_path}")
        click.echo()
        click.echo("🎯 Next steps:")
        click.echo(f"1. Edit {output_path} to customize your workflow")
        click.echo(f"2. Validate: flask fab workflow validate {output_path}")
        click.echo(f"3. Generate: flask fab workflow generate {output_path} --app-name your_app")
        
    except Exception as e:
        click.echo(click.style(f"❌ Failed to create workflow: {e}", fg='red'))


def _generate_workflow_template(workflow_name: str, template: str, format: str) -> str:
    """Generate workflow template content."""
    workflow_class_name = ''.join(word.capitalize() for word in workflow_name.split('_'))
    
    if template == 'basic':
        template_data = {
            workflow_class_name: {
                'version': '1.0.0',
                'description': f'{workflow_name.replace("_", " ").title()} workflow',
                'entities': {
                    'Record': {
                        'fields': [
                            {'name': {'type': 'string', 'required': True}},
                            {'description': {'type': 'textarea', 'required': False}},
                            {'created_at': {'type': 'datetime', 'default': 'now'}}
                        ]
                    }
                },
                'steps': {
                    'BasicInfo': {
                        'title': 'Basic Information',
                        'description': 'Enter basic information',
                        'icon': 'edit',
                        'fields': [
                            {'title': {'type': 'string', 'required': True}},
                            {'notes': {'type': 'textarea', 'required': False}}
                        ]
                    }
                }
            }
        }
    elif template == 'crud':
        template_data = {
            workflow_class_name: {
                'version': '1.0.0',
                'description': f'{workflow_name.replace("_", " ").title()} CRUD workflow',
                'entities': {
                    'Item': {
                        'fields': [
                            {'name': {'type': 'string', 'required': True}},
                            {'category': {'type': 'select', 'choices': [['A', 'Category A'], ['B', 'Category B']]}},
                            {'active': {'type': 'boolean', 'default': True}}
                        ]
                    }
                },
                'steps': {
                    'Create': {
                        'title': 'Create Item',
                        'icon': 'plus',
                        'fields': [
                            {'name': {'type': 'string', 'required': True}},
                            {'category': {'type': 'select', 'required': True}}
                        ]
                    },
                    'Edit': {
                        'title': 'Edit Item', 
                        'icon': 'edit',
                        'fields': [
                            {'name': {'type': 'string', 'required': True}},
                            {'category': {'type': 'select', 'required': True}},
                            {'active': {'type': 'boolean'}}
                        ]
                    }
                }
            }
        }
    else:  # approval template
        template_data = {
            workflow_class_name: {
                'version': '1.0.0',
                'description': f'{workflow_name.replace("_", " ").title()} approval workflow',
                'entities': {
                    'Request': {
                        'fields': [
                            {'title': {'type': 'string', 'required': True}},
                            {'description': {'type': 'textarea', 'required': True}},
                            {'status': {'type': 'select', 'choices': [['pending', 'Pending'], ['approved', 'Approved'], ['rejected', 'Rejected']]}},
                            {'submitted_at': {'type': 'datetime', 'default': 'now'}}
                        ]
                    }
                },
                'steps': {
                    'Submit': {
                        'title': 'Submit Request',
                        'icon': 'send',
                        'fields': [
                            {'title': {'type': 'string', 'required': True}},
                            {'description': {'type': 'textarea', 'required': True}}
                        ]
                    },
                    'Review': {
                        'title': 'Manager Review',
                        'icon': 'check-circle',
                        'permissions': {'view': ['manager'], 'edit': ['manager']},
                        'fields': [
                            {'decision': {'type': 'select', 'choices': [['approve', 'Approve'], ['reject', 'Reject']]}},
                            {'comments': {'type': 'textarea', 'required': False}}
                        ]
                    }
                },
                'permissions': {
                    'Submit': {'view': ['employee'], 'edit': ['employee']},
                    'Review': {'view': ['manager'], 'edit': ['manager']}
                }
            }
        }
    
    if format == 'yaml':
        return yaml.dump(template_data, default_flow_style=False, indent=2, sort_keys=False)
    else:
        # Convert to WDL format (simplified)
        wdl_content = f"""# {workflow_name.replace("_", " ").title()} Workflow Definition

workflow {workflow_class_name} {{
  version: "1.0.0"
  description: "{workflow_name.replace("_", " ").title()} workflow"
  
  # Add your entities here
  entities {{
    # Define your data models
  }}
  
  # Add your workflow steps here  
  steps {{
    # Define your workflow steps
  }}
}}
"""
        return wdl_content