"""
Workflow Definition Language (WDL) Generator - Inspired by JHipster
Generates complete PgForge workflow implementations from WDL files.
"""

import os
import yaml
import logging
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from jinja2 import Environment, FileSystemLoader, Template
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass
class GeneratedComponent:
    """Represents a generated component from WDL."""
    file_path: str
    content: str
    component_type: str
    depends_on: List[str] = None


@dataclass
class WorkflowDefinition:
    """Parsed WDL workflow definition."""
    name: str
    version: str
    description: str
    entities: Dict[str, Any]
    steps: Dict[str, Any]
    triggers: Dict[str, Any]
    sla: Dict[str, Any]
    notifications: Dict[str, Any]
    analytics: Dict[str, Any] = None
    compliance: Dict[str, Any] = None


class WDLParser:
    """Parses Workflow Definition Language files."""

    def parse_file(self, wdl_file: Path) -> WorkflowDefinition:
        """Parse WDL file into structured definition."""
        with open(wdl_file, 'r') as f:
            content = f.read()

        # Custom parser for WDL format (simplified YAML-like)
        parsed = self._parse_wdl_content(content)

        workflow_name = list(parsed.keys())[0]
        workflow_data = parsed[workflow_name]

        return WorkflowDefinition(
            name=workflow_name,
            version=workflow_data.get('version', '1.0.0'),
            description=workflow_data.get('description', ''),
            entities=workflow_data.get('entities', {}),
            steps=workflow_data.get('steps', {}),
            triggers=workflow_data.get('triggers', {}),
            sla=workflow_data.get('sla', {}),
            notifications=workflow_data.get('notifications', {}),
            analytics=workflow_data.get('analytics'),
            compliance=workflow_data.get('compliance')
        )

    def _parse_wdl_content(self, content: str) -> Dict[str, Any]:
        """Parse WDL content with proper validation and fallback."""
        # First attempt: Try to parse as structured WDL format
        try:
            # Remove comments and normalize whitespace
            normalized_content = self._normalize_wdl_content(content)

            # Validate WDL syntax structure
            if not self._validate_wdl_structure(normalized_content):
                raise ValueError("Invalid WDL structure")

            # Convert WDL blocks to YAML-compatible format
            yaml_content = self._convert_wdl_to_yaml(normalized_content)

            # Parse as YAML
            parsed_data = yaml.safe_load(yaml_content)

            # Validate required WDL sections
            if not self._validate_parsed_wdl(parsed_data):
                raise ValueError("Missing required WDL sections")

            log.info("Successfully parsed WDL content")
            return parsed_data

        except (yaml.YAMLError, ValueError) as e:
            log.warning(f"WDL parsing failed, attempting YAML fallback: {e}")

            # Fallback: Try direct YAML parsing for development
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError as yaml_error:
                log.error(f"Both WDL and YAML parsing failed. WDL error: {e}, YAML error: {yaml_error}")
                raise ValueError(f"Invalid WDL syntax: {e}. YAML fallback also failed: {yaml_error}")

    def _normalize_wdl_content(self, content: str) -> str:
        """Normalize WDL content by removing comments and fixing formatting."""
        lines = []
        for line in content.split('\n'):
            # Remove comments but preserve quoted strings
            if '#' in line and not self._is_in_quotes(line, line.index('#')):
                line = line[:line.index('#')]
            line = line.strip()
            if line:
                lines.append(line)
        return '\n'.join(lines)

    def _is_in_quotes(self, line: str, position: int) -> bool:
        """Check if position is inside quoted string."""
        in_quotes = False
        escape_next = False
        for i, char in enumerate(line[:position]):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
            elif char in ['"', "'"]:
                in_quotes = not in_quotes
        return in_quotes

    def _validate_wdl_structure(self, content: str) -> bool:
        """Validate basic WDL structure."""
        required_patterns = [
            r'workflow\s+\w+\s*\{',  # workflow block
            r'steps\s*\{',           # steps block
        ]

        for pattern in required_patterns:
            if not re.search(pattern, content, re.IGNORECASE):
                log.error(f"Missing required WDL pattern: {pattern}")
                return False

        return True

    def _convert_wdl_to_yaml(self, content: str) -> str:
        """Convert WDL-specific syntax to YAML format using proper parsing."""
        import re
        from typing import List, Tuple

        # Parse the WDL into a structured format
        parsed_data = self._parse_wdl_structure(content)

        # Convert to YAML string
        import yaml
        return yaml.dump(parsed_data, default_flow_style=False, sort_keys=False)

    def _parse_wdl_structure(self, content: str) -> Dict[str, Any]:
        """Parse WDL content into a structured dictionary."""
        import re
        from typing import Dict, Any, List

        # Tokenize the content
        tokens = self._tokenize_wdl(content)

        # Parse tokens into structure
        result = {}
        i = 0

        while i < len(tokens):
            token = tokens[i]

            if token[0] == 'KEYWORD' and token[1] == 'workflow':
                # Parse workflow block
                i += 1
                if i < len(tokens) and tokens[i][0] == 'IDENTIFIER':
                    workflow_name = tokens[i][1]
                    i += 1
                    if i < len(tokens) and tokens[i][0] == 'LBRACE':
                        i += 1
                        workflow_data, i = self._parse_block(tokens, i)
                        result[workflow_name] = workflow_data
                    else:
                        raise ValueError(f"Expected '{{' after workflow name at position {i}")
                else:
                    raise ValueError(f"Expected workflow name at position {i}")
            else:
                i += 1

        return result

    def _tokenize_wdl(self, content: str) -> List[Tuple[str, str]]:
        """Tokenize WDL content."""
        import re

        # Define token patterns
        token_patterns = [
            ('COMMENT', r'#.*'),
            ('STRING', r'"[^"]*"'),
            ('NUMBER', r'\d+\.?\d*'),
            ('KEYWORD', r'\b(workflow|entities|steps|fields|permissions|validation|notifications|triggers|sla|analytics|compliance)\b'),
            ('BOOLEAN', r'\b(true|false|existing|generated|required)\b'),
            ('IDENTIFIER', r'[a-zA-Z_][a-zA-Z0-9_]*'),
            ('COLON', r':'),
            ('SEMICOLON', r';'),
            ('COMMA', r','),
            ('LBRACE', r'\{'),
            ('RBRACE', r'\}'),
            ('LBRACKET', r'\['),
            ('RBRACKET', r'\]'),
            ('LPAREN', r'\('),
            ('RPAREN', r'\)'),
            ('WHITESPACE', r'\s+'),
        ]

        # Compile patterns
        token_regex = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in token_patterns)

        tokens = []
        for match in re.finditer(token_regex, content):
            token_type = match.lastgroup
            token_value = match.group()

            # Skip whitespace and comments
            if token_type not in ('WHITESPACE', 'COMMENT'):
                tokens.append((token_type, token_value))

        return tokens

    def _parse_block(self, tokens: List[Tuple[str, str]], start_index: int) -> Tuple[Dict[str, Any], int]:
        """Parse a block of tokens between braces with proper nesting."""
        result = {}
        i = start_index

        while i < len(tokens):
            token = tokens[i]

            if token[0] == 'RBRACE':
                # This closing brace ends the current block
                return result, i + 1

            elif token[0] == 'IDENTIFIER' or token[0] == 'KEYWORD':
                key = token[1]
                i += 1

                if i >= len(tokens):
                    raise ValueError(f"Unexpected end of tokens after '{key}'")

                next_token = tokens[i]

                if next_token[0] == 'COLON':
                    # Handle key: value pattern
                    i += 1
                    value, i = self._parse_value(tokens, i)
                    result[key] = value

                elif next_token[0] == 'LBRACE':
                    # Handle key { block } pattern
                    i += 1  # Skip the opening brace
                    nested_block, i = self._parse_block(tokens, i)
                    result[key] = nested_block

                else:
                    # Handle standalone keyword (treat as empty object)
                    result[key] = {}
            else:
                # Skip other tokens
                i += 1

        # If we reach here, we hit end of tokens without finding closing brace
        raise ValueError("Unexpected end of tokens - missing closing brace")

    def _parse_value(self, tokens: List[Tuple[str, str]], start_index: int) -> Tuple[Any, int]:
        """Parse a value (string, number, array, or object) with improved nesting."""
        i = start_index

        if i >= len(tokens):
            return None, i

        token = tokens[i]

        if token[0] == 'STRING':
            return token[1].strip('"'), i + 1
            
        elif token[0] == 'NUMBER':
            try:
                return int(token[1]) if '.' not in token[1] else float(token[1]), i + 1
            except ValueError:
                return token[1], i + 1
                
        elif token[0] == 'BOOLEAN':
            return token[1] in ('true', 'required'), i + 1
            
        elif token[0] == 'IDENTIFIER':
            return token[1], i + 1
            
        elif token[0] == 'LBRACE':
            # Parse nested object
            i += 1
            obj, i = self._parse_block(tokens, i)
            return obj, i
            
        elif token[0] == 'LBRACKET':
            # Parse array
            i += 1
            arr = []
            
            while i < len(tokens) and tokens[i][0] != 'RBRACKET':
                if tokens[i][0] == 'COMMA':
                    i += 1
                    continue

                # Handle array element which could be:
                # 1. Simple value
                # 2. Object with identifier: { ... }
                # 3. Nested structure
                
                if (i + 2 < len(tokens) and
                    tokens[i][0] in ('IDENTIFIER', 'KEYWORD') and
                    tokens[i + 1][0] == 'COLON' and
                    tokens[i + 2][0] == 'LBRACE'):
                    
                    # Array element is: identifier: { ... }
                    key = tokens[i][1]
                    i += 2  # Skip identifier and colon
                    i += 1  # Skip opening brace
                    obj, i = self._parse_block(tokens, i)
                    arr.append({key: obj})
                    
                elif (i + 1 < len(tokens) and
                      tokens[i][0] in ('IDENTIFIER', 'KEYWORD') and
                      tokens[i + 1][0] == 'COLON'):
                    
                    # Array element is: identifier: value
                    key = tokens[i][1]
                    i += 2  # Skip identifier and colon
                    value, i = self._parse_value(tokens, i)
                    arr.append({key: value})
                    
                else:
                    # Simple array element
                    value, i = self._parse_value(tokens, i)
                    arr.append(value)

            if i < len(tokens) and tokens[i][0] == 'RBRACKET':
                return arr, i + 1
            else:
                raise ValueError("Unclosed array - missing ']'")
                
        else:
            raise ValueError(f"Unexpected token '{token[1]}' of type '{token[0]}' at position {i}")

    def _validate_parsed_wdl(self, parsed_data: Dict[str, Any]) -> bool:
        """Validate parsed WDL data has required sections."""
        if not isinstance(parsed_data, dict):
            return False

        # Must have at least one workflow
        workflow_names = [k for k in parsed_data.keys() if isinstance(parsed_data[k], dict)]
        if not workflow_names:
            log.error("No workflow definitions found")
            return False

        # Each workflow must have steps
        for workflow_name in workflow_names:
            workflow_data = parsed_data[workflow_name]
            if not isinstance(workflow_data, dict) or 'steps' not in workflow_data:
                log.error(f"Workflow {workflow_name} missing steps section")
                return False

        return True


class WorkflowCodeGenerator:
    """Generates PgForge code from WDL definitions."""

    def __init__(self, template_dir: str = None):
        self.template_dir = template_dir or self._get_default_template_dir()
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.template_dir),
            trim_blocks=True,
            lstrip_blocks=True
        )

    def generate_from_wdl(self, wdl_file: Path, output_dir: Path) -> List[GeneratedComponent]:
        """Generate complete workflow implementation from WDL file."""
        parser = WDLParser()
        workflow_def = parser.parse_file(wdl_file)

        generated_components = []

        # Generate each component type
        generated_components.extend(self._generate_models(workflow_def, output_dir))
        generated_components.extend(self._generate_views(workflow_def, output_dir))
        generated_components.extend(self._generate_forms(workflow_def, output_dir))
        generated_components.extend(self._generate_apis(workflow_def, output_dir))
        generated_components.extend(self._generate_templates(workflow_def, output_dir))
        generated_components.extend(self._generate_tests(workflow_def, output_dir))
        generated_components.extend(self._generate_migrations(workflow_def, output_dir))
        generated_components.extend(self._generate_config(workflow_def, output_dir))

        # Write all generated components to files
        self._write_components(generated_components)

        return generated_components

    def _generate_models(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate SQLAlchemy models for workflow entities."""
        components = []

        # Generate main workflow state model
        model_template = self.jinja_env.get_template('models/workflow_state.py.j2')
        content = model_template.render(
            workflow=workflow_def,
            timestamp=datetime.now(),
            fields=self._extract_all_fields(workflow_def)
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"models/{workflow_def.name.lower()}_models.py",
            content=content,
            component_type="model"
        ))

        # Generate entity models for 'generated' entities
        for entity_name, entity_config in workflow_def.entities.items():
            if entity_config == 'generated' or isinstance(entity_config, dict):
                entity_template = self.jinja_env.get_template('models/entity.py.j2')
                content = entity_template.render(
                    entity_name=entity_name,
                    entity_config=entity_config,
                    workflow=workflow_def,
                    timestamp=datetime.now()
                )

                components.append(GeneratedComponent(
                    file_path=output_dir / f"models/{entity_name.lower()}.py",
                    content=content,
                    component_type="entity_model",
                    depends_on=[f"{workflow_def.name.lower()}_models.py"]
                ))

        return components

    def _generate_views(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate PgForge ModelView classes."""
        components = []

        # Generate main workflow view
        view_template = self.jinja_env.get_template('views/workflow_view.py.j2')
        content = view_template.render(
            workflow=workflow_def,
            timestamp=datetime.now(),
            steps=workflow_def.steps,
            permissions=self._extract_permissions(workflow_def)
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"views/{workflow_def.name.lower()}_views.py",
            content=content,
            component_type="view",
            depends_on=[f"{workflow_def.name.lower()}_models.py"]
        ))

        # Generate step-specific views
        for step_name, step_config in workflow_def.steps.items():
            step_view_template = self.jinja_env.get_template('views/step_view.py.j2')
            content = step_view_template.render(
                workflow=workflow_def,
                step_name=step_name,
                step_config=step_config,
                timestamp=datetime.now()
            )

            components.append(GeneratedComponent(
                file_path=output_dir / f"views/{workflow_def.name.lower()}_{step_name.lower()}_view.py",
                content=content,
                component_type="step_view",
                depends_on=[f"{workflow_def.name.lower()}_views.py"]
            ))

        return components

    def _generate_forms(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate WTForms form classes with validation."""
        components = []

        forms_template = self.jinja_env.get_template('forms/workflow_forms.py.j2')
        content = forms_template.render(
            workflow=workflow_def,
            timestamp=datetime.now(),
            steps=workflow_def.steps,
            validation_rules=self._extract_validation_rules(workflow_def)
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"forms/{workflow_def.name.lower()}_forms.py",
            content=content,
            component_type="forms"
        ))

        return components

    def _generate_apis(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate REST API endpoints with OpenAPI documentation."""
        components = []

        api_template = self.jinja_env.get_template('apis/workflow_api.py.j2')
        content = api_template.render(
            workflow=workflow_def,
            timestamp=datetime.now(),
            endpoints=self._extract_api_endpoints(workflow_def)
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"apis/{workflow_def.name.lower()}_api.py",
            content=content,
            component_type="api",
            depends_on=[f"{workflow_def.name.lower()}_models.py"]
        ))

        # Generate OpenAPI spec
        openapi_template = self.jinja_env.get_template('apis/openapi_spec.yaml.j2')
        spec_content = openapi_template.render(
            workflow=workflow_def,
            timestamp=datetime.now()
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"specs/{workflow_def.name.lower()}_openapi.yaml",
            content=spec_content,
            component_type="openapi_spec"
        ))

        return components

    def _generate_templates(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate Jinja2 HTML templates."""
        components = []

        # Generate main workflow template
        workflow_template = self.jinja_env.get_template('templates/workflow.html.j2')
        content = workflow_template.render(
            workflow=workflow_def,
            timestamp=datetime.now()
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"templates/{workflow_def.name.lower()}/workflow.html",
            content=content,
            component_type="template"
        ))

        # Generate step templates
        for step_name, step_config in workflow_def.steps.items():
            step_template = self.jinja_env.get_template('templates/step.html.j2')
            content = step_template.render(
                workflow=workflow_def,
                step_name=step_name,
                step_config=step_config,
                timestamp=datetime.now()
            )

            components.append(GeneratedComponent(
                file_path=output_dir / f"templates/{workflow_def.name.lower()}/{step_name.lower()}.html",
                content=content,
                component_type="step_template"
            ))

        return components

    def _generate_tests(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate comprehensive test suites."""
        components = []

        # Unit tests
        unit_test_template = self.jinja_env.get_template('tests/test_workflow_unit.py.j2')
        content = unit_test_template.render(
            workflow=workflow_def,
            timestamp=datetime.now()
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"tests/unit/test_{workflow_def.name.lower()}_unit.py",
            content=content,
            component_type="unit_test"
        ))

        # Integration tests
        integration_test_template = self.jinja_env.get_template('tests/test_workflow_integration.py.j2')
        content = integration_test_template.render(
            workflow=workflow_def,
            timestamp=datetime.now()
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"tests/integration/test_{workflow_def.name.lower()}_integration.py",
            content=content,
            component_type="integration_test"
        ))

        # End-to-end tests
        e2e_test_template = self.jinja_env.get_template('tests/test_workflow_e2e.py.j2')
        content = e2e_test_template.render(
            workflow=workflow_def,
            timestamp=datetime.now()
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"tests/e2e/test_{workflow_def.name.lower()}_e2e.py",
            content=content,
            component_type="e2e_test"
        ))

        return components

    def _generate_migrations(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate database migration scripts."""
        components = []

        migration_template = self.jinja_env.get_template('migrations/workflow_migration.py.j2')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        content = migration_template.render(
            workflow=workflow_def,
            timestamp=timestamp,
            tables=self._extract_tables(workflow_def)
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"migrations/{timestamp}_create_{workflow_def.name.lower()}_workflow.py",
            content=content,
            component_type="migration"
        ))

        return components

    def _generate_config(self, workflow_def: WorkflowDefinition, output_dir: Path) -> List[GeneratedComponent]:
        """Generate configuration files."""
        components = []

        # Workflow configuration
        config_template = self.jinja_env.get_template('config/workflow_config.py.j2')
        content = config_template.render(
            workflow=workflow_def,
            timestamp=datetime.now()
        )

        components.append(GeneratedComponent(
            file_path=output_dir / f"config/{workflow_def.name.lower()}_config.py",
            content=content,
            component_type="config"
        ))

        # Docker configuration
        if workflow_def.notifications or workflow_def.analytics:
            docker_template = self.jinja_env.get_template('config/docker-compose.yml.j2')
            content = docker_template.render(
                workflow=workflow_def,
                timestamp=datetime.now()
            )

            components.append(GeneratedComponent(
                file_path=output_dir / f"docker/{workflow_def.name.lower()}-docker-compose.yml",
                content=content,
                component_type="docker_config"
            ))

        return components

    def _extract_all_fields(self, workflow_def: WorkflowDefinition) -> List[Dict[str, Any]]:
        """Extract all fields from workflow steps."""
        all_fields = []
        for step_name, step_config in workflow_def.steps.items():
            fields = step_config.get('fields', [])
            for field_name, field_config in fields.items():
                all_fields.append({
                    'name': field_name,
                    'step': step_name,
                    'config': field_config
                })
        return all_fields

    def _extract_permissions(self, workflow_def: WorkflowDefinition) -> Dict[str, List[str]]:
        """Extract permission requirements from workflow."""
        permissions = {}
        for step_name, step_config in workflow_def.steps.items():
            step_permissions = step_config.get('permissions', {})
            permissions[step_name] = step_permissions
        return permissions

    def _extract_validation_rules(self, workflow_def: WorkflowDefinition) -> Dict[str, Any]:
        """Extract validation rules from workflow steps."""
        validation_rules = {}
        for step_name, step_config in workflow_def.steps.items():
            fields = step_config.get('fields', {})
            step_validations = {}
            for field_name, field_config in fields.items():
                if 'validation' in field_config:
                    step_validations[field_name] = field_config['validation']
            if step_validations:
                validation_rules[step_name] = step_validations
        return validation_rules

    def _extract_api_endpoints(self, workflow_def: WorkflowDefinition) -> List[Dict[str, Any]]:
        """Extract API endpoint definitions."""
        endpoints = [
            {'method': 'GET', 'path': f'/api/v1/workflows/{workflow_def.name.lower()}', 'description': 'List workflows'},
            {'method': 'POST', 'path': f'/api/v1/workflows/{workflow_def.name.lower()}', 'description': 'Create workflow'},
            {'method': 'GET', 'path': f'/api/v1/workflows/{workflow_def.name.lower()}/{{id}}', 'description': 'Get workflow'},
            {'method': 'PUT', 'path': f'/api/v1/workflows/{workflow_def.name.lower()}/{{id}}/advance', 'description': 'Advance workflow'},
        ]

        for step_name in workflow_def.steps.keys():
            endpoints.extend([
                {'method': 'GET', 'path': f'/api/v1/workflows/{workflow_def.name.lower()}/{{id}}/steps/{step_name.lower()}', 'description': f'Get {step_name} step'},
                {'method': 'PUT', 'path': f'/api/v1/workflows/{workflow_def.name.lower()}/{{id}}/steps/{step_name.lower()}', 'description': f'Update {step_name} step'},
            ])

        return endpoints

    def _extract_tables(self, workflow_def: WorkflowDefinition) -> List[Dict[str, Any]]:
        """Extract database table definitions."""
        tables = []

        # Main workflow state table
        tables.append({
            'name': f'{workflow_def.name.lower()}_workflow_states',
            'fields': self._extract_all_fields(workflow_def)
        })

        # Entity tables
        for entity_name, entity_config in workflow_def.entities.items():
            if isinstance(entity_config, dict) and 'fields' in entity_config:
                tables.append({
                    'name': f'{entity_name.lower()}s',
                    'fields': entity_config['fields']
                })

        return tables

    def _get_default_template_dir(self) -> str:
        """Get default template directory."""
        current_dir = Path(__file__).parent
        return str(current_dir / 'templates')

    def _write_components(self, components: List[GeneratedComponent]) -> List[str]:
        """Write generated components to filesystem with error handling."""
        written_files = []
        failed_files = []

        for component in components:
            try:
                file_path = Path(component.file_path)

                # Validate file path security
                if not self._is_safe_path(file_path):
                    raise ValueError(f"Unsafe file path: {file_path}")

                # Create directory with proper permissions
                file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)

                # Atomic write operation
                temp_path = file_path.with_suffix('.tmp')
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(component.content)

                # Validate generated content
                if not self._validate_generated_content(component):
                    raise ValueError(f"Generated content validation failed for {component.component_type}")

                # Atomic move
                temp_path.rename(file_path)
                written_files.append(str(file_path))

                log.info(f"Generated {component.component_type}: {file_path}")

            except Exception as e:
                error_msg = f"Failed to write {component.component_type} to {component.file_path}: {e}"
                log.error(error_msg)
                failed_files.append(error_msg)

                # Clean up temp file if it exists
                try:
                    temp_path = Path(component.file_path).with_suffix('.tmp')
                    if temp_path.exists():
                        temp_path.unlink()
                except Exception:
                    pass  # Ignore cleanup errors

        if failed_files:
            raise RuntimeError(f"Failed to write {len(failed_files)} components: {failed_files}")

        return written_files

    def _is_safe_path(self, file_path: Path) -> bool:
        """Validate file path is safe (no directory traversal)."""
        try:
            resolved = file_path.resolve()
            # Ensure path doesn't contain directory traversal attempts
            path_str = str(resolved)
            if '..' in path_str or path_str.startswith('/'):
                return False
            return True
        except Exception:
            return False

    def _validate_generated_content(self, component: GeneratedComponent) -> bool:
        """Validate generated content for basic correctness."""
        if not component.content.strip():
            log.error(f"Empty content for {component.component_type}")
            return False

        # Basic syntax validation for Python files
        if component.file_path.endswith('.py'):
            try:
                compile(component.content, component.file_path, 'exec')
            except SyntaxError as e:
                log.error(f"Syntax error in generated Python file {component.file_path}: {e}")
                return False

        # Check for potential security issues
        dangerous_patterns = [
            r'eval\s*\(',
            r'exec\s*\(',
            r'__import__\s*\(',
            r'open\s*\([^)]*["\']w["\']',  # File writing in templates
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, component.content):
                log.warning(f"Potentially dangerous pattern found in {component.component_type}: {pattern}")

        return True


class WorkflowDevelopmentServer:
    """Development server with hot reload for WDL changes."""

    def __init__(self, wdl_dir: Path, output_dir: Path):
        self.wdl_dir = wdl_dir
        self.output_dir = output_dir
        self.generator = WorkflowCodeGenerator()

    def start_watch_mode(self):
        """Start watching WDL files for changes."""
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class WDLChangeHandler(FileSystemEventHandler):
            def __init__(self, server):
                self.server = server

            def on_modified(self, event):
                if event.src_path.endswith('.wdl'):
                    log.info(f"WDL file changed: {event.src_path}")
                    self.server.regenerate_workflow(Path(event.src_path))

        event_handler = WDLChangeHandler(self)
        observer = Observer()
        observer.schedule(event_handler, str(self.wdl_dir), recursive=True)
        observer.start()

        log.info(f"Watching for WDL changes in {self.wdl_dir}")

        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    def regenerate_workflow(self, wdl_file: Path):
        """Regenerate workflow from WDL file."""
        try:
            components = self.generator.generate_from_wdl(wdl_file, self.output_dir)
            log.info(f"Regenerated {len(components)} components from {wdl_file}")

            # Run tests after regeneration
            self._run_tests()

        except Exception as e:
            log.error(f"Failed to regenerate workflow from {wdl_file}: {e}")

    def _run_tests(self):
        """Run tests for generated workflow."""
        import subprocess
        try:
            result = subprocess.run(
                ['python', '-m', 'pytest', str(self.output_dir / 'tests'), '-v'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log.info("All tests passed ✅")
            else:
                log.warning(f"Some tests failed ❌:\n{result.stdout}\n{result.stderr}")
        except Exception as e:
            log.error(f"Failed to run tests: {e}")


if __name__ == "__main__":
    # Example usage
    generator = WorkflowCodeGenerator()
    wdl_file = Path("examples/workflow_definitions/employee_onboarding.wdl")
    output_dir = Path("generated/employee_onboarding")

    components = generator.generate_from_wdl(wdl_file, output_dir)
    print(f"Generated {len(components)} components")