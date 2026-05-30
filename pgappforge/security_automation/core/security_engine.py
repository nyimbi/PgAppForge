"""
Security Automation Engine

Core engine for automated security scanning, vulnerability detection, and 
security policy enforcement in PgAppForge applications.
"""

import logging
import json
import ast
import re
import os
import subprocess
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import fnmatch

logger = logging.getLogger(__name__)


@dataclass
class SecurityVulnerability:
    """Represents a security vulnerability found during scanning."""
    id: str
    severity: str  # 'critical', 'high', 'medium', 'low', 'info'
    category: str  # 'injection', 'xss', 'authentication', 'authorization', etc.
    title: str
    description: str
    file_path: str
    line_number: int
    code_snippet: str
    recommendation: str
    cwe_id: Optional[str] = None
    cvss_score: Optional[float] = None
    confidence: float = 1.0
    false_positive: bool = False


@dataclass
class SecurityScanResult:
    """Results from a security scan."""
    scan_id: str
    timestamp: datetime
    scan_type: str
    target_path: str
    vulnerabilities: List[SecurityVulnerability]
    scan_duration: float
    files_scanned: int
    lines_scanned: int
    summary: Dict[str, int]
    metadata: Dict[str, Any]


@dataclass
class SecurityPolicy:
    """Security policy configuration."""
    policy_id: str
    name: str
    description: str
    rules: List[Dict[str, Any]]
    severity: str
    enabled: bool = True
    auto_fix: bool = False


class SecurityAutomationEngine:
    """
    Automated security scanning and vulnerability detection engine.
    
    Features:
    - Static code analysis for security vulnerabilities
    - Dynamic security testing integration
    - Security policy enforcement
    - Vulnerability tracking and management
    - Integration with security tools (bandit, safety, etc.)
    - Custom PgAppForge security rules
    - Automated security testing
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.security_policies: Dict[str, SecurityPolicy] = {}
        self.vulnerability_history: List[SecurityScanResult] = []
        self.scan_cache: Dict[str, SecurityScanResult] = {}
        
        # Initialize security rules and patterns
        self._init_security_patterns()
        self._init_pgappforge_rules()
        self._load_security_policies()
        
        # Tool configurations
        self.external_tools = {
            'bandit': self._check_bandit_available(),
            'safety': self._check_safety_available(),
            'semgrep': self._check_semgrep_available(),
            'eslint': self._check_eslint_available()
        }
        
        logger.info("Security Automation Engine initialized")
    
    def _init_security_patterns(self):
        """Initialize security vulnerability patterns."""
        self.vulnerability_patterns = {
            'sql_injection': [
                {
                    'pattern': r'execute\s*\(\s*["\'].*%.*["\']',
                    'description': 'Potential SQL injection via string formatting',
                    'severity': 'high',
                    'cwe': 'CWE-89'
                },
                {
                    'pattern': r'query\s*\(\s*["\'].*\+.*["\']',
                    'description': 'Potential SQL injection via string concatenation',
                    'severity': 'high',
                    'cwe': 'CWE-89'
                },
                {
                    'pattern': r'\.format\s*\(.*\).*execute',
                    'description': 'Potential SQL injection via .format()',
                    'severity': 'high',
                    'cwe': 'CWE-89'
                }
            ],
            
            'xss': [
                {
                    'pattern': r'render_template_string\s*\(.*request\.',
                    'description': 'XSS via render_template_string with user input',
                    'severity': 'high',
                    'cwe': 'CWE-79'
                },
                {
                    'pattern': r'\|\s*safe\s*}}',
                    'description': 'Potentially unsafe Jinja2 safe filter usage',
                    'severity': 'medium',
                    'cwe': 'CWE-79'
                }
            ],
            
            'authentication': [
                {
                    'pattern': r'@login_required\s*\n\s*def\s+.*admin',
                    'description': 'Admin function may lack proper authorization',
                    'severity': 'medium',
                    'cwe': 'CWE-285'
                },
                {
                    'pattern': r'password\s*=\s*["\'][^"\']*["\']',
                    'description': 'Hardcoded password detected',
                    'severity': 'critical',
                    'cwe': 'CWE-798'
                }
            ],
            
            'authorization': [
                {
                    'pattern': r'if\s+current_user\.is_admin\s*:',
                    'description': 'Simple admin check - consider role-based permissions',
                    'severity': 'low',
                    'cwe': 'CWE-863'
                }
            ],
            
            'crypto': [
                {
                    'pattern': r'hashlib\.md5\s*\(',
                    'description': 'Weak hashing algorithm MD5 used',
                    'severity': 'medium',
                    'cwe': 'CWE-327'
                },
                {
                    'pattern': r'hashlib\.sha1\s*\(',
                    'description': 'Weak hashing algorithm SHA1 used',
                    'severity': 'medium', 
                    'cwe': 'CWE-327'
                }
            ],
            
            'information_disclosure': [
                {
                    'pattern': r'app\.debug\s*=\s*True',
                    'description': 'Debug mode enabled in production',
                    'severity': 'high',
                    'cwe': 'CWE-200'
                },
                {
                    'pattern': r'print\s*\(.*password',
                    'description': 'Sensitive information in print statement',
                    'severity': 'medium',
                    'cwe': 'CWE-532'
                }
            ],
            
            'csrf': [
                {
                    'pattern': r'@app\.route.*methods.*POST.*\n(?!.*@csrf\.exempt)(?!.*csrf_token)',
                    'description': 'POST endpoint may lack CSRF protection',
                    'severity': 'medium',
                    'cwe': 'CWE-352'
                }
            ]
        }
    
    def _init_pgappforge_rules(self):
        """Initialize PgAppForge specific security rules."""
        self.fab_security_rules = [
            {
                'rule_id': 'fab_auth_type',
                'name': 'Authentication Type Configuration',
                'pattern': r'AUTH_TYPE\s*=\s*AUTH_DB',
                'severity': 'info',
                'description': 'Using database authentication - ensure strong password policies',
                'recommendation': 'Consider implementing 2FA and password complexity requirements'
            },
            {
                'rule_id': 'fab_secret_key',
                'name': 'Secret Key Security',
                'pattern': r'SECRET_KEY\s*=\s*["\'][^"\']{1,20}["\']',
                'severity': 'high',
                'description': 'Weak SECRET_KEY detected',
                'recommendation': 'Use a cryptographically secure random key of at least 32 characters'
            },
            {
                'rule_id': 'fab_csrf_enabled',
                'name': 'CSRF Protection',
                'pattern': r'WTF_CSRF_ENABLED\s*=\s*False',
                'severity': 'high',
                'description': 'CSRF protection disabled',
                'recommendation': 'Enable CSRF protection by setting WTF_CSRF_ENABLED = True'
            },
            {
                'rule_id': 'fab_sql_alchemy_track',
                'name': 'SQLAlchemy Event Tracking',
                'pattern': r'SQLALCHEMY_TRACK_MODIFICATIONS\s*=\s*True',
                'severity': 'low',
                'description': 'SQLAlchemy event tracking enabled - performance impact',
                'recommendation': 'Set SQLALCHEMY_TRACK_MODIFICATIONS = False unless needed'
            },
            {
                'rule_id': 'fab_public_role',
                'name': 'Public Role Permissions',
                'pattern': r'AUTH_ROLE_PUBLIC\s*=\s*["\'][^"\']*["\']',
                'severity': 'medium',
                'description': 'Public role configured - review permissions',
                'recommendation': 'Ensure public role has minimal necessary permissions'
            }
        ]
    
    def _load_security_policies(self):
        """Load security policies from configuration."""
        
        # Default security policies
        default_policies = [
            SecurityPolicy(
                policy_id='no_hardcoded_secrets',
                name='No Hardcoded Secrets',
                description='Detect hardcoded passwords, API keys, and other secrets',
                rules=[
                    {'pattern': r'password\s*=\s*["\'][^"\']*["\']', 'severity': 'critical'},
                    {'pattern': r'api_key\s*=\s*["\'][^"\']*["\']', 'severity': 'high'},
                    {'pattern': r'secret\s*=\s*["\'][^"\']*["\']', 'severity': 'high'}
                ],
                severity='critical',
                enabled=True
            ),
            
            SecurityPolicy(
                policy_id='secure_coding_practices',
                name='Secure Coding Practices',
                description='Enforce secure coding practices',
                rules=[
                    {'pattern': r'eval\s*\(', 'severity': 'high'},
                    {'pattern': r'exec\s*\(', 'severity': 'high'},
                    {'pattern': r'subprocess\..*shell\s*=\s*True', 'severity': 'high'}
                ],
                severity='high',
                enabled=True
            ),
            
            SecurityPolicy(
                policy_id='flask_security',
                name='Flask Security Best Practices',
                description='Flask and PgAppForge security requirements',
                rules=[
                    {'pattern': r'app\.debug\s*=\s*True', 'severity': 'high'},
                    {'pattern': r'app\.run\(.*debug\s*=\s*True', 'severity': 'high'}
                ],
                severity='medium',
                enabled=True
            )
        ]
        
        for policy in default_policies:
            self.security_policies[policy.policy_id] = policy
    
    # Main scanning methods
    def scan_codebase(self, target_path: str, scan_type: str = 'comprehensive') -> SecurityScanResult:
        """
        Perform comprehensive security scan of codebase.
        
        Args:
            target_path: Path to scan (file or directory)
            scan_type: Type of scan ('quick', 'comprehensive', 'deep')
            
        Returns:
            Security scan results
        """
        logger.info(f"Starting {scan_type} security scan of {target_path}")
        
        scan_id = self._generate_scan_id(target_path, scan_type)
        start_time = datetime.now()
        
        # Check cache first
        cache_key = f"{target_path}_{scan_type}_{self._get_path_hash(target_path)}"
        if cache_key in self.scan_cache and self._is_cache_valid(cache_key):
            logger.info("Using cached scan results")
            return self.scan_cache[cache_key]
        
        vulnerabilities = []
        files_scanned = 0
        lines_scanned = 0
        
        try:
            # Static analysis
            if scan_type in ['comprehensive', 'deep']:
                static_vulns, static_files, static_lines = self._perform_static_analysis(target_path)
                vulnerabilities.extend(static_vulns)
                files_scanned += static_files
                lines_scanned += static_lines
            
            # Policy validation
            policy_vulns, policy_files, policy_lines = self._validate_security_policies(target_path)
            vulnerabilities.extend(policy_vulns)
            files_scanned += policy_files
            lines_scanned += policy_lines
            
            # PgAppForge specific checks
            fab_vulns = self._check_pgappforge_security(target_path)
            vulnerabilities.extend(fab_vulns)
            
            # External tool integration
            if scan_type == 'deep':
                external_vulns = self._run_external_security_tools(target_path)
                vulnerabilities.extend(external_vulns)
            
            # Dependency scanning
            if scan_type in ['comprehensive', 'deep']:
                dependency_vulns = self._scan_dependencies(target_path)
                vulnerabilities.extend(dependency_vulns)
            
            # Calculate scan summary
            summary = self._calculate_scan_summary(vulnerabilities)
            
            scan_duration = (datetime.now() - start_time).total_seconds()
            
            # Create scan result
            result = SecurityScanResult(
                scan_id=scan_id,
                timestamp=start_time,
                scan_type=scan_type,
                target_path=target_path,
                vulnerabilities=vulnerabilities,
                scan_duration=scan_duration,
                files_scanned=files_scanned,
                lines_scanned=lines_scanned,
                summary=summary,
                metadata={
                    'tools_used': [tool for tool, available in self.external_tools.items() if available],
                    'policies_applied': list(self.security_policies.keys())
                }
            )
            
            # Cache result
            self.scan_cache[cache_key] = result
            self.vulnerability_history.append(result)
            
            logger.info(f"Security scan completed in {scan_duration:.2f}s - found {len(vulnerabilities)} issues")
            return result
            
        except Exception as e:
            logger.error(f"Security scan failed: {e}")
            raise
    
    def _perform_static_analysis(self, target_path: str) -> Tuple[List[SecurityVulnerability], int, int]:
        """Perform static code analysis for security vulnerabilities."""
        
        vulnerabilities = []
        files_scanned = 0
        lines_scanned = 0
        
        # Get all Python files to scan
        python_files = self._get_python_files(target_path)
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                    lines_scanned += len(lines)
                
                files_scanned += 1
                
                # Pattern-based vulnerability detection
                file_vulns = self._scan_file_patterns(file_path, content)
                vulnerabilities.extend(file_vulns)
                
                # AST-based analysis for more complex patterns
                try:
                    tree = ast.parse(content)
                    ast_vulns = self._scan_ast_patterns(file_path, tree, content)
                    vulnerabilities.extend(ast_vulns)
                except SyntaxError:
                    logger.warning(f"Could not parse {file_path} for AST analysis")
                
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        return vulnerabilities, files_scanned, lines_scanned
    
    def _scan_file_patterns(self, file_path: str, content: str) -> List[SecurityVulnerability]:
        """Scan file content using regex patterns."""
        
        vulnerabilities = []
        lines = content.split('\n')
        
        for category, patterns in self.vulnerability_patterns.items():
            for pattern_info in patterns:
                pattern = pattern_info['pattern']
                compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                
                for match in compiled_pattern.finditer(content):
                    # Find line number
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # Extract code snippet
                    start_line = max(0, line_num - 2)
                    end_line = min(len(lines), line_num + 2)
                    code_snippet = '\n'.join(lines[start_line:end_line])
                    
                    vulnerability = SecurityVulnerability(
                        id=self._generate_vulnerability_id(file_path, line_num, category),
                        severity=pattern_info['severity'],
                        category=category,
                        title=pattern_info['description'],
                        description=pattern_info['description'],
                        file_path=file_path,
                        line_number=line_num,
                        code_snippet=code_snippet,
                        recommendation=self._get_recommendation(category, pattern_info),
                        cwe_id=pattern_info.get('cwe'),
                        confidence=0.8
                    )
                    
                    vulnerabilities.append(vulnerability)
        
        return vulnerabilities
    
    def _scan_ast_patterns(self, file_path: str, tree: ast.AST, content: str) -> List[SecurityVulnerability]:
        """Scan using AST analysis for complex patterns."""
        
        vulnerabilities = []
        
        class SecurityVisitor(ast.NodeVisitor):
            def __init__(self, file_path: str, content: str, vulns: List[SecurityVulnerability]):
                self.file_path = file_path
                self.content = content
                self.lines = content.split('\n')
                self.vulnerabilities = vulns
            
            def visit_Call(self, node):
                # Check for dangerous function calls
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    
                    if func_name in ['eval', 'exec']:
                        self.add_vulnerability(
                            node, 'dangerous_functions', 'high',
                            f'Dangerous function {func_name}() detected',
                            f'Avoid using {func_name}() as it can execute arbitrary code'
                        )
                    
                    elif func_name == 'input' and sys.version_info[0] == 2:
                        self.add_vulnerability(
                            node, 'dangerous_functions', 'high',
                            'Python 2 input() function detected',
                            'Use raw_input() instead of input() in Python 2'
                        )
                
                # Check method calls
                elif isinstance(node.func, ast.Attribute):
                    if (isinstance(node.func.value, ast.Name) and 
                        node.func.value.id == 'subprocess' and
                        node.func.attr in ['call', 'run', 'Popen']):
                        
                        # Check for shell=True
                        for keyword in node.keywords:
                            if keyword.arg == 'shell' and isinstance(keyword.value, ast.Constant):
                                if keyword.value.value is True:
                                    self.add_vulnerability(
                                        node, 'command_injection', 'high',
                                        'subprocess call with shell=True',
                                        'Avoid shell=True to prevent command injection'
                                    )
                
                self.generic_visit(node)
            
            def visit_Assign(self, node):
                # Check for hardcoded secrets in assignments
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    var_name = node.targets[0].id.lower()
                    
                    if any(keyword in var_name for keyword in ['password', 'secret', 'key', 'token']):
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            if len(node.value.value) > 4:  # Skip empty or very short strings
                                self.add_vulnerability(
                                    node, 'hardcoded_secrets', 'critical',
                                    f'Hardcoded secret in variable {var_name}',
                                    'Move secrets to environment variables or secure configuration'
                                )
                
                self.generic_visit(node)
            
            def add_vulnerability(self, node, category, severity, title, recommendation):
                line_num = node.lineno
                
                # Extract code snippet
                start_line = max(0, line_num - 2)
                end_line = min(len(self.lines), line_num + 2)
                code_snippet = '\n'.join(self.lines[start_line:end_line])
                
                vulnerability = SecurityVulnerability(
                    id=self._generate_vulnerability_id(self.file_path, line_num, category),
                    severity=severity,
                    category=category,
                    title=title,
                    description=title,
                    file_path=self.file_path,
                    line_number=line_num,
                    code_snippet=code_snippet,
                    recommendation=recommendation,
                    confidence=0.9
                )
                
                self.vulnerabilities.append(vulnerability)
        
        visitor = SecurityVisitor(file_path, content, vulnerabilities)
        visitor.visit(tree)
        
        return vulnerabilities
    
    def _validate_security_policies(self, target_path: str) -> Tuple[List[SecurityVulnerability], int, int]:
        """Validate against configured security policies."""
        
        vulnerabilities = []
        files_scanned = 0
        lines_scanned = 0
        
        python_files = self._get_python_files(target_path)
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines_scanned += len(content.split('\n'))
                
                files_scanned += 1
                
                # Check each enabled policy
                for policy_id, policy in self.security_policies.items():
                    if not policy.enabled:
                        continue
                    
                    for rule in policy.rules:
                        pattern = rule['pattern']
                        severity = rule['severity']
                        
                        compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                        
                        for match in compiled_pattern.finditer(content):
                            line_num = content[:match.start()].count('\n') + 1
                            
                            vulnerability = SecurityVulnerability(
                                id=self._generate_vulnerability_id(file_path, line_num, policy_id),
                                severity=severity,
                                category='policy_violation',
                                title=f'Policy violation: {policy.name}',
                                description=policy.description,
                                file_path=file_path,
                                line_number=line_num,
                                code_snippet=self._extract_code_snippet(content, line_num),
                                recommendation=f'Follow policy: {policy.name}',
                                confidence=0.85
                            )
                            
                            vulnerabilities.append(vulnerability)
                            
            except Exception as e:
                logger.warning(f"Could not validate policies for {file_path}: {e}")
        
        return vulnerabilities, files_scanned, lines_scanned
    
    def _check_pgappforge_security(self, target_path: str) -> List[SecurityVulnerability]:
        """Check PgAppForge specific security configurations."""
        
        vulnerabilities = []
        
        # Look for PgAppForge configuration files
        config_files = []
        
        if os.path.isfile(target_path):
            if 'config' in target_path.lower() or target_path.endswith('.py'):
                config_files.append(target_path)
        else:
            for root, dirs, files in os.walk(target_path):
                for file in files:
                    if (file.endswith('.py') and 
                        ('config' in file.lower() or 'settings' in file.lower())):
                        config_files.append(os.path.join(root, file))
        
        # Scan configuration files
        for config_file in config_files:
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check PgAppForge specific rules
                for rule in self.fab_security_rules:
                    pattern = rule['pattern']
                    compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                    
                    for match in compiled_pattern.finditer(content):
                        line_num = content[:match.start()].count('\n') + 1
                        
                        vulnerability = SecurityVulnerability(
                            id=self._generate_vulnerability_id(config_file, line_num, rule['rule_id']),
                            severity=rule['severity'],
                            category='pgappforge_security',
                            title=rule['name'],
                            description=rule['description'],
                            file_path=config_file,
                            line_number=line_num,
                            code_snippet=self._extract_code_snippet(content, line_num),
                            recommendation=rule['recommendation'],
                            confidence=0.9
                        )
                        
                        vulnerabilities.append(vulnerability)
                        
            except Exception as e:
                logger.warning(f"Could not scan PgAppForge config {config_file}: {e}")
        
        return vulnerabilities
    
    def _run_external_security_tools(self, target_path: str) -> List[SecurityVulnerability]:
        """Run external security scanning tools."""
        
        vulnerabilities = []
        
        # Run Bandit for Python security issues
        if self.external_tools.get('bandit'):
            bandit_results = self._run_bandit(target_path)
            vulnerabilities.extend(bandit_results)
        
        # Run Safety for dependency vulnerabilities
        if self.external_tools.get('safety'):
            safety_results = self._run_safety(target_path)
            vulnerabilities.extend(safety_results)
        
        # Run Semgrep for advanced pattern matching
        if self.external_tools.get('semgrep'):
            semgrep_results = self._run_semgrep(target_path)
            vulnerabilities.extend(semgrep_results)
        
        return vulnerabilities
    
    def _run_bandit(self, target_path: str) -> List[SecurityVulnerability]:
        """Run Bandit security scanner."""
        
        vulnerabilities = []
        
        try:
            # Run bandit with JSON output
            cmd = ['bandit', '-r', target_path, '-f', 'json', '-q']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode in [0, 1]:  # 0 = no issues, 1 = issues found
                output = json.loads(result.stdout)
                
                for issue in output.get('results', []):
                    vulnerability = SecurityVulnerability(
                        id=f"bandit_{issue['test_id']}_{issue['line_number']}",
                        severity=issue['issue_severity'].lower(),
                        category='bandit_' + issue['test_name'].lower().replace(' ', '_'),
                        title=issue['test_name'],
                        description=issue['issue_text'],
                        file_path=issue['filename'],
                        line_number=issue['line_number'],
                        code_snippet=issue['code'],
                        recommendation=f"See: {issue.get('more_info', 'N/A')}",
                        confidence=issue['issue_confidence'].lower(),
                        cwe_id=issue.get('cwe', {}).get('id')
                    )
                    vulnerabilities.append(vulnerability)
        
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            logger.warning(f"Bandit scan failed: {e}")
        except FileNotFoundError:
            logger.warning("Bandit not found - install with: pip install bandit")
        
        return vulnerabilities
    
    def _run_safety(self, target_path: str) -> List[SecurityVulnerability]:
        """Run Safety dependency scanner."""
        
        vulnerabilities = []
        
        try:
            # Look for requirements files
            req_files = []
            if os.path.isfile(target_path):
                if target_path.endswith('requirements.txt'):
                    req_files.append(target_path)
            else:
                for root, dirs, files in os.walk(target_path):
                    for file in files:
                        if file in ['requirements.txt', 'requirements-dev.txt', 'Pipfile']:
                            req_files.append(os.path.join(root, file))
            
            for req_file in req_files:
                cmd = ['safety', 'check', '-r', req_file, '--json']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                
                if result.returncode in [0, 64]:  # 0 = safe, 64 = vulnerabilities found
                    if result.stdout.strip():
                        try:
                            output = json.loads(result.stdout)
                            
                            for issue in output:
                                vulnerability = SecurityVulnerability(
                                    id=f"safety_{issue['id']}",
                                    severity='high',  # Safety issues are typically high severity
                                    category='dependency_vulnerability',
                                    title=f"Vulnerable dependency: {issue['package']}",
                                    description=issue['advisory'],
                                    file_path=req_file,
                                    line_number=1,
                                    code_snippet=f"{issue['package']}=={issue['installed_version']}",
                                    recommendation=f"Upgrade to {issue['package']}>={issue['safe_version']}",
                                    confidence=0.95
                                )
                                vulnerabilities.append(vulnerability)
                        except json.JSONDecodeError:
                            logger.warning(f"Could not parse Safety output for {req_file}")
        
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            logger.warning(f"Safety scan failed: {e}")
        except FileNotFoundError:
            logger.warning("Safety not found - install with: pip install safety")
        
        return vulnerabilities
    
    def _run_semgrep(self, target_path: str) -> List[SecurityVulnerability]:
        """Run Semgrep advanced pattern scanner."""
        
        vulnerabilities = []
        
        try:
            cmd = [
                'semgrep', 
                '--config=auto',  # Use automatic rule selection
                '--json',
                '--quiet',
                target_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0 and result.stdout.strip():
                output = json.loads(result.stdout)
                
                for finding in output.get('results', []):
                    vulnerability = SecurityVulnerability(
                        id=f"semgrep_{finding['check_id']}_{finding['start']['line']}",
                        severity=finding.get('extra', {}).get('severity', 'medium').lower(),
                        category='semgrep_' + finding['check_id'].split('.')[-1],
                        title=finding.get('extra', {}).get('message', finding['check_id']),
                        description=finding.get('extra', {}).get('message', ''),
                        file_path=finding['path'],
                        line_number=finding['start']['line'],
                        code_snippet=finding.get('extra', {}).get('lines', ''),
                        recommendation=finding.get('extra', {}).get('fix', 'Review and fix this issue'),
                        confidence=0.8
                    )
                    vulnerabilities.append(vulnerability)
        
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, json.JSONDecodeError) as e:
            logger.warning(f"Semgrep scan failed: {e}")
        except FileNotFoundError:
            logger.warning("Semgrep not found - install with: pip install semgrep")
        
        return vulnerabilities
    
    def _scan_dependencies(self, target_path: str) -> List[SecurityVulnerability]:
        """Scan for vulnerable dependencies."""
        
        vulnerabilities = []
        
        # This is handled by Safety in _run_external_security_tools
        # but we can add additional dependency analysis here
        
        return vulnerabilities
    
    # Utility methods
    def _get_python_files(self, path: str) -> List[str]:
        """Get all Python files to scan."""
        
        python_files = []
        
        if os.path.isfile(path):
            if path.endswith('.py'):
                python_files.append(path)
        else:
            for root, dirs, files in os.walk(path):
                # Skip common directories that shouldn't be scanned
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.pytest_cache', 'node_modules'}]
                
                for file in files:
                    if file.endswith('.py'):
                        python_files.append(os.path.join(root, file))
        
        return python_files
    
    def _generate_scan_id(self, target_path: str, scan_type: str) -> str:
        """Generate unique scan ID."""
        timestamp = datetime.now().isoformat()
        return f"scan_{hashlib.md5(f'{target_path}_{scan_type}_{timestamp}'.encode()).hexdigest()[:8]}"
    
    def _generate_vulnerability_id(self, file_path: str, line_num: int, category: str) -> str:
        """Generate unique vulnerability ID."""
        return f"vuln_{hashlib.md5(f'{file_path}_{line_num}_{category}'.encode()).hexdigest()[:8]}"
    
    def _get_path_hash(self, path: str) -> str:
        """Get hash of path contents for cache invalidation."""
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()[:8]
        else:
            # Hash directory structure and file modification times
            hash_content = []
            for root, dirs, files in os.walk(path):
                for file in files:
                    if file.endswith('.py'):
                        file_path = os.path.join(root, file)
                        mtime = os.path.getmtime(file_path)
                        hash_content.append(f"{file_path}_{mtime}")
            return hashlib.md5('\n'.join(hash_content).encode()).hexdigest()[:8]
    
    def _is_cache_valid(self, cache_key: str, max_age_hours: int = 1) -> bool:
        """Check if cached scan result is still valid."""
        if cache_key not in self.scan_cache:
            return False
        
        scan_result = self.scan_cache[cache_key]
        age = datetime.now() - scan_result.timestamp
        return age < timedelta(hours=max_age_hours)
    
    def _extract_code_snippet(self, content: str, line_num: int, context: int = 2) -> str:
        """Extract code snippet around line number."""
        lines = content.split('\n')
        start_line = max(0, line_num - context - 1)
        end_line = min(len(lines), line_num + context)
        return '\n'.join(lines[start_line:end_line])
    
    def _get_recommendation(self, category: str, pattern_info: Dict[str, Any]) -> str:
        """Get security recommendation for vulnerability category."""
        
        recommendations = {
            'sql_injection': 'Use parameterized queries or ORM methods to prevent SQL injection',
            'xss': 'Sanitize user input and use template escaping mechanisms',
            'authentication': 'Implement proper authentication and session management',
            'authorization': 'Use role-based access control and principle of least privilege',
            'crypto': 'Use strong cryptographic algorithms (SHA-256 or better)',
            'information_disclosure': 'Remove debug information and sensitive data from production',
            'csrf': 'Implement CSRF protection tokens for state-changing operations'
        }
        
        return recommendations.get(category, 'Review and fix this security issue')
    
    def _calculate_scan_summary(self, vulnerabilities: List[SecurityVulnerability]) -> Dict[str, int]:
        """Calculate summary statistics for scan results."""
        
        summary = {
            'total': len(vulnerabilities),
            'critical': 0,
            'high': 0,
            'medium': 0,
            'low': 0,
            'info': 0
        }
        
        for vuln in vulnerabilities:
            if not vuln.false_positive:
                summary[vuln.severity] = summary.get(vuln.severity, 0) + 1
        
        return summary
    
    # External tool availability checks
    def _check_bandit_available(self) -> bool:
        """Check if Bandit is available."""
        try:
            subprocess.run(['bandit', '--help'], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _check_safety_available(self) -> bool:
        """Check if Safety is available."""
        try:
            subprocess.run(['safety', '--help'], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _check_semgrep_available(self) -> bool:
        """Check if Semgrep is available."""
        try:
            subprocess.run(['semgrep', '--help'], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _check_eslint_available(self) -> bool:
        """Check if ESLint is available."""
        try:
            subprocess.run(['eslint', '--help'], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    # Public API methods
    def quick_scan(self, target_path: str) -> SecurityScanResult:
        """Perform a quick security scan."""
        return self.scan_codebase(target_path, 'quick')
    
    def comprehensive_scan(self, target_path: str) -> SecurityScanResult:
        """Perform a comprehensive security scan."""
        return self.scan_codebase(target_path, 'comprehensive')
    
    def deep_scan(self, target_path: str) -> SecurityScanResult:
        """Perform a deep security scan with all tools."""
        return self.scan_codebase(target_path, 'deep')
    
    def get_scan_history(self, limit: Optional[int] = None) -> List[SecurityScanResult]:
        """Get scan history."""
        if limit:
            return self.vulnerability_history[-limit:]
        return self.vulnerability_history
    
    def mark_false_positive(self, vulnerability_id: str):
        """Mark vulnerability as false positive."""
        for result in self.vulnerability_history:
            for vuln in result.vulnerabilities:
                if vuln.id == vulnerability_id:
                    vuln.false_positive = True
                    logger.info(f"Marked vulnerability {vulnerability_id} as false positive")
                    return
        
        logger.warning(f"Vulnerability {vulnerability_id} not found")
    
    def add_security_policy(self, policy: SecurityPolicy):
        """Add custom security policy."""
        self.security_policies[policy.policy_id] = policy
        logger.info(f"Added security policy: {policy.name}")
    
    def export_scan_results(self, scan_result: SecurityScanResult, format: str = 'json') -> str:
        """Export scan results in various formats."""
        
        if format == 'json':
            return self._export_json(scan_result)
        elif format == 'sarif':
            return self._export_sarif(scan_result)
        elif format == 'html':
            return self._export_html(scan_result)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def _export_json(self, scan_result: SecurityScanResult) -> str:
        """Export results as JSON."""
        
        data = {
            'scan_id': scan_result.scan_id,
            'timestamp': scan_result.timestamp.isoformat(),
            'scan_type': scan_result.scan_type,
            'target_path': scan_result.target_path,
            'summary': scan_result.summary,
            'vulnerabilities': []
        }
        
        for vuln in scan_result.vulnerabilities:
            vuln_data = {
                'id': vuln.id,
                'severity': vuln.severity,
                'category': vuln.category,
                'title': vuln.title,
                'description': vuln.description,
                'file_path': vuln.file_path,
                'line_number': vuln.line_number,
                'code_snippet': vuln.code_snippet,
                'recommendation': vuln.recommendation,
                'cwe_id': vuln.cwe_id,
                'confidence': vuln.confidence,
                'false_positive': vuln.false_positive
            }
            data['vulnerabilities'].append(vuln_data)
        
        return json.dumps(data, indent=2)
    
    def _export_sarif(self, scan_result: SecurityScanResult) -> str:
        """Export results as SARIF format."""
        # SARIF (Static Analysis Results Interchange Format) implementation
        # This is a simplified version - full SARIF has many more fields
        
        sarif = {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "PgAppForge Security Scanner",
                            "version": "1.0.0"
                        }
                    },
                    "results": []
                }
            ]
        }
        
        for vuln in scan_result.vulnerabilities:
            result = {
                "ruleId": vuln.category,
                "message": {
                    "text": vuln.description
                },
                "level": self._sarif_severity_mapping(vuln.severity),
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": vuln.file_path
                            },
                            "region": {
                                "startLine": vuln.line_number
                            }
                        }
                    }
                ]
            }
            
            sarif["runs"][0]["results"].append(result)
        
        return json.dumps(sarif, indent=2)
    
    def _sarif_severity_mapping(self, severity: str) -> str:
        """Map severity to SARIF levels."""
        mapping = {
            'critical': 'error',
            'high': 'error', 
            'medium': 'warning',
            'low': 'note',
            'info': 'note'
        }
        return mapping.get(severity, 'note')
    
    def _export_html(self, scan_result: SecurityScanResult) -> str:
        """Export results as HTML report."""
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Security Scan Report - {scan_result.scan_id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f5f5f5; padding: 20px; margin-bottom: 20px; }}
                .summary {{ display: flex; gap: 20px; margin-bottom: 20px; }}
                .severity-box {{ padding: 10px; border-radius: 4px; text-align: center; }}
                .critical {{ background: #ff4444; color: white; }}
                .high {{ background: #ff8800; color: white; }}
                .medium {{ background: #ffaa00; color: black; }}
                .low {{ background: #88cc00; color: black; }}
                .vuln {{ border: 1px solid #ddd; margin: 10px 0; padding: 15px; }}
                .code {{ background: #f8f8f8; padding: 10px; font-family: monospace; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Security Scan Report</h1>
                <p>Scan ID: {scan_result.scan_id}</p>
                <p>Target: {scan_result.target_path}</p>
                <p>Scan Type: {scan_result.scan_type}</p>
                <p>Timestamp: {scan_result.timestamp}</p>
            </div>
            
            <div class="summary">
                <div class="severity-box critical">Critical<br>{scan_result.summary.get('critical', 0)}</div>
                <div class="severity-box high">High<br>{scan_result.summary.get('high', 0)}</div>
                <div class="severity-box medium">Medium<br>{scan_result.summary.get('medium', 0)}</div>
                <div class="severity-box low">Low<br>{scan_result.summary.get('low', 0)}</div>
            </div>
            
            <h2>Vulnerabilities ({scan_result.summary['total']})</h2>
        """
        
        for vuln in scan_result.vulnerabilities:
            if not vuln.false_positive:
                html += f"""
                <div class="vuln">
                    <h3>[{vuln.severity.upper()}] {vuln.title}</h3>
                    <p><strong>File:</strong> {vuln.file_path}:{vuln.line_number}</p>
                    <p><strong>Category:</strong> {vuln.category}</p>
                    <p><strong>Description:</strong> {vuln.description}</p>
                    <p><strong>Recommendation:</strong> {vuln.recommendation}</p>
                    <div class="code">{vuln.code_snippet}</div>
                </div>
                """
        
        html += """
        </body>
        </html>
        """
        
        return html