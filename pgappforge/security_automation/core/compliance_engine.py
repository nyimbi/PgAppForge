"""
Compliance Validation Engine

Automated validation against regulatory compliance standards including
GDPR, HIPAA, PCI-DSS, SOX, and other industry regulations.
"""

import logging
import json
import re
import os
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import hashlib

logger = logging.getLogger(__name__)


class ComplianceFramework(Enum):
    """Supported compliance frameworks."""
    GDPR = "gdpr"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    SOX = "sox"
    CCPA = "ccpa"
    COPPA = "coppa"
    FERPA = "ferpa"
    GLBA = "glba"
    ISO_27001 = "iso_27001"
    SOC_2 = "soc_2"


@dataclass
class ComplianceRequirement:
    """Represents a specific compliance requirement."""
    requirement_id: str
    framework: ComplianceFramework
    title: str
    description: str
    category: str
    mandatory: bool
    controls: List[str]
    validation_rules: List[Dict[str, Any]]
    evidence_required: List[str]
    remediation_guidance: str
    priority: int = 1


@dataclass
class ComplianceViolation:
    """Represents a compliance violation found during validation."""
    violation_id: str
    requirement_id: str
    framework: ComplianceFramework
    severity: str  # 'critical', 'high', 'medium', 'low'
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    remediation: str = ""
    risk_score: float = 0.0
    detected_at: datetime = field(default_factory=datetime.now)


@dataclass
class ComplianceReport:
    """Compliance validation report."""
    report_id: str
    framework: ComplianceFramework
    target_path: str
    timestamp: datetime
    overall_score: float
    violations: List[ComplianceViolation]
    requirements_checked: int
    requirements_passed: int
    requirements_failed: int
    evidence_collected: Dict[str, Any]
    recommendations: List[str]
    next_audit_date: Optional[datetime] = None


class ComplianceValidationEngine:
    """
    Automated compliance validation against regulatory frameworks.
    
    Features:
    - Multi-framework compliance validation
    - Automated evidence collection
    - Risk assessment and scoring
    - Remediation recommendations
    - Compliance tracking and reporting
    - Integration with security scanning
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.requirements: Dict[ComplianceFramework, List[ComplianceRequirement]] = {}
        self.validation_history: List[ComplianceReport] = []
        
        # Initialize framework requirements
        self._initialize_gdpr_requirements()
        self._initialize_hipaa_requirements()
        self._initialize_pci_dss_requirements()
        self._initialize_sox_requirements()
        self._initialize_iso_27001_requirements()
        
        logger.info("Compliance Validation Engine initialized")
    
    def _initialize_gdpr_requirements(self):
        """Initialize GDPR compliance requirements."""
        
        gdpr_requirements = [
            ComplianceRequirement(
                requirement_id="gdpr_article_6",
                framework=ComplianceFramework.GDPR,
                title="Lawful Basis for Processing",
                description="Processing of personal data must have a lawful basis",
                category="data_processing",
                mandatory=True,
                controls=[
                    "consent_management",
                    "legitimate_interest_assessment",
                    "legal_basis_documentation"
                ],
                validation_rules=[
                    {
                        "type": "data_field_check",
                        "pattern": r"consent.*status|consent.*flag",
                        "required": True,
                        "description": "Consent status field required"
                    },
                    {
                        "type": "privacy_policy_check",
                        "required": True,
                        "description": "Privacy policy must be accessible"
                    }
                ],
                evidence_required=[
                    "consent_records",
                    "privacy_policy",
                    "data_processing_agreements"
                ],
                remediation_guidance="Implement consent management system and document legal basis for all data processing activities",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="gdpr_article_17",
                framework=ComplianceFramework.GDPR,
                title="Right to Erasure (Right to be Forgotten)",
                description="Individuals have the right to request deletion of their personal data",
                category="data_rights",
                mandatory=True,
                controls=[
                    "data_deletion_mechanism",
                    "deletion_request_handling",
                    "anonymization_procedures"
                ],
                validation_rules=[
                    {
                        "type": "code_pattern_check",
                        "pattern": r"delete.*user|remove.*personal.*data",
                        "required": True,
                        "description": "Data deletion functionality required"
                    },
                    {
                        "type": "api_endpoint_check",
                        "endpoints": ["/api/user/delete", "/api/data/erase"],
                        "required": True,
                        "description": "Data erasure API endpoint required"
                    }
                ],
                evidence_required=[
                    "deletion_procedures",
                    "anonymization_methods",
                    "deletion_logs"
                ],
                remediation_guidance="Implement user data deletion functionality and maintain deletion audit logs",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="gdpr_article_20",
                framework=ComplianceFramework.GDPR,
                title="Right to Data Portability",
                description="Individuals have the right to receive their personal data in a structured format",
                category="data_rights",
                mandatory=True,
                controls=[
                    "data_export_functionality",
                    "structured_data_formats",
                    "automated_export_processes"
                ],
                validation_rules=[
                    {
                        "type": "api_endpoint_check",
                        "endpoints": ["/api/user/export", "/api/data/download"],
                        "required": True,
                        "description": "Data export API endpoint required"
                    },
                    {
                        "type": "export_format_check",
                        "formats": ["json", "csv", "xml"],
                        "required": True,
                        "description": "Structured export formats required"
                    }
                ],
                evidence_required=[
                    "export_functionality",
                    "data_format_specifications"
                ],
                remediation_guidance="Implement user data export functionality in structured formats",
                priority=2
            ),
            
            ComplianceRequirement(
                requirement_id="gdpr_article_32",
                framework=ComplianceFramework.GDPR,
                title="Security of Processing",
                description="Implement appropriate technical and organizational measures to ensure security",
                category="data_security",
                mandatory=True,
                controls=[
                    "encryption_at_rest",
                    "encryption_in_transit",
                    "access_controls",
                    "security_monitoring"
                ],
                validation_rules=[
                    {
                        "type": "encryption_check",
                        "required": True,
                        "description": "Data encryption required"
                    },
                    {
                        "type": "access_control_check", 
                        "required": True,
                        "description": "Access controls required"
                    }
                ],
                evidence_required=[
                    "encryption_implementation",
                    "access_control_policies",
                    "security_audit_logs"
                ],
                remediation_guidance="Implement comprehensive data security measures including encryption and access controls",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="gdpr_article_33_34",
                framework=ComplianceFramework.GDPR,
                title="Data Breach Notification",
                description="Report personal data breaches within 72 hours to supervisory authority",
                category="incident_response",
                mandatory=True,
                controls=[
                    "breach_detection_systems",
                    "notification_procedures",
                    "incident_documentation"
                ],
                validation_rules=[
                    {
                        "type": "incident_response_check",
                        "required": True,
                        "description": "Incident response procedures required"
                    },
                    {
                        "type": "logging_check",
                        "log_types": ["security", "access", "data_changes"],
                        "required": True,
                        "description": "Security logging required"
                    }
                ],
                evidence_required=[
                    "incident_response_plan",
                    "breach_notification_procedures",
                    "security_monitoring_logs"
                ],
                remediation_guidance="Implement incident response procedures and security monitoring for breach detection",
                priority=1
            )
        ]
        
        self.requirements[ComplianceFramework.GDPR] = gdpr_requirements
    
    def _initialize_hipaa_requirements(self):
        """Initialize HIPAA compliance requirements."""
        
        hipaa_requirements = [
            ComplianceRequirement(
                requirement_id="hipaa_164.308",
                framework=ComplianceFramework.HIPAA,
                title="Administrative Safeguards",
                description="Implement administrative safeguards to protect PHI",
                category="administrative",
                mandatory=True,
                controls=[
                    "security_officer_designation",
                    "workforce_training",
                    "access_authorization_procedures"
                ],
                validation_rules=[
                    {
                        "type": "role_check",
                        "roles": ["privacy_officer", "security_officer"],
                        "required": True,
                        "description": "Security officer role required"
                    },
                    {
                        "type": "training_documentation_check",
                        "required": True,
                        "description": "Staff training documentation required"
                    }
                ],
                evidence_required=[
                    "security_policies",
                    "training_records",
                    "role_assignments"
                ],
                remediation_guidance="Designate security officer and implement workforce training programs",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="hipaa_164.312",
                framework=ComplianceFramework.HIPAA,
                title="Technical Safeguards",
                description="Implement technical safeguards to protect PHI",
                category="technical",
                mandatory=True,
                controls=[
                    "access_control",
                    "audit_controls", 
                    "integrity_protection",
                    "transmission_security"
                ],
                validation_rules=[
                    {
                        "type": "encryption_check",
                        "scope": ["database", "transmission"],
                        "required": True,
                        "description": "PHI encryption required"
                    },
                    {
                        "type": "audit_logging_check",
                        "log_types": ["access", "modifications", "deletions"],
                        "required": True,
                        "description": "Comprehensive audit logging required"
                    }
                ],
                evidence_required=[
                    "encryption_configuration",
                    "audit_log_samples",
                    "access_control_implementation"
                ],
                remediation_guidance="Implement encryption, audit controls, and access restrictions for PHI",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="hipaa_164.306",
                framework=ComplianceFramework.HIPAA,
                title="PHI Security Standards",
                description="Ensure confidentiality, integrity, and availability of PHI",
                category="phi_protection",
                mandatory=True,
                controls=[
                    "phi_identification",
                    "minimum_necessary_access",
                    "data_backup_recovery"
                ],
                validation_rules=[
                    {
                        "type": "phi_field_identification",
                        "phi_indicators": ["ssn", "medical_record", "patient_id", "diagnosis"],
                        "required": True,
                        "description": "PHI fields must be identified and protected"
                    },
                    {
                        "type": "minimum_access_check",
                        "required": True,
                        "description": "Minimum necessary access principle required"
                    }
                ],
                evidence_required=[
                    "phi_inventory",
                    "access_control_matrix",
                    "backup_procedures"
                ],
                remediation_guidance="Identify all PHI fields and implement minimum necessary access controls",
                priority=1
            )
        ]
        
        self.requirements[ComplianceFramework.HIPAA] = hipaa_requirements
    
    def _initialize_pci_dss_requirements(self):
        """Initialize PCI-DSS compliance requirements."""
        
        pci_requirements = [
            ComplianceRequirement(
                requirement_id="pci_req_3",
                framework=ComplianceFramework.PCI_DSS,
                title="Protect Stored Cardholder Data",
                description="Cardholder data must be protected wherever it is stored",
                category="data_protection",
                mandatory=True,
                controls=[
                    "data_encryption",
                    "key_management",
                    "secure_storage"
                ],
                validation_rules=[
                    {
                        "type": "card_data_check",
                        "patterns": [r"\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}", r"card.*number|pan"],
                        "encryption_required": True,
                        "description": "Credit card data must be encrypted"
                    },
                    {
                        "type": "key_management_check",
                        "required": True,
                        "description": "Encryption key management required"
                    }
                ],
                evidence_required=[
                    "encryption_implementation",
                    "key_management_procedures",
                    "secure_storage_configuration"
                ],
                remediation_guidance="Encrypt all stored cardholder data and implement secure key management",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="pci_req_4",
                framework=ComplianceFramework.PCI_DSS,
                title="Encrypt Transmission of Cardholder Data",
                description="Encrypt cardholder data when transmitted over public networks",
                category="transmission_security",
                mandatory=True,
                controls=[
                    "tls_encryption",
                    "secure_protocols",
                    "certificate_management"
                ],
                validation_rules=[
                    {
                        "type": "tls_check",
                        "min_version": "TLS 1.2",
                        "required": True,
                        "description": "TLS 1.2 or higher required for cardholder data transmission"
                    },
                    {
                        "type": "certificate_validation",
                        "required": True,
                        "description": "Valid SSL/TLS certificates required"
                    }
                ],
                evidence_required=[
                    "tls_configuration",
                    "certificate_inventory",
                    "secure_transmission_logs"
                ],
                remediation_guidance="Implement strong encryption for all cardholder data transmissions",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="pci_req_8",
                framework=ComplianceFramework.PCI_DSS,
                title="Identify and Authenticate Access",
                description="Assign unique IDs to each person with computer access",
                category="access_control",
                mandatory=True,
                controls=[
                    "unique_user_ids",
                    "strong_authentication",
                    "multi_factor_authentication"
                ],
                validation_rules=[
                    {
                        "type": "user_authentication_check",
                        "requirements": ["unique_ids", "strong_passwords", "mfa"],
                        "required": True,
                        "description": "Strong user authentication required"
                    }
                ],
                evidence_required=[
                    "user_authentication_policies",
                    "mfa_implementation",
                    "password_policies"
                ],
                remediation_guidance="Implement strong user authentication with MFA for cardholder data access",
                priority=1
            )
        ]
        
        self.requirements[ComplianceFramework.PCI_DSS] = pci_requirements
    
    def _initialize_sox_requirements(self):
        """Initialize SOX compliance requirements."""
        
        sox_requirements = [
            ComplianceRequirement(
                requirement_id="sox_section_302",
                framework=ComplianceFramework.SOX,
                title="Corporate Responsibility for Financial Reports",
                description="CEOs and CFOs must certify accuracy of financial reports",
                category="financial_reporting",
                mandatory=True,
                controls=[
                    "financial_data_accuracy",
                    "change_controls",
                    "approval_workflows"
                ],
                validation_rules=[
                    {
                        "type": "financial_data_controls",
                        "required": True,
                        "description": "Controls over financial data required"
                    },
                    {
                        "type": "approval_workflow_check",
                        "required": True,
                        "description": "Financial data approval workflows required"
                    }
                ],
                evidence_required=[
                    "financial_data_controls",
                    "approval_procedures",
                    "accuracy_verification_logs"
                ],
                remediation_guidance="Implement controls and approval workflows for financial data",
                priority=1
            ),
            
            ComplianceRequirement(
                requirement_id="sox_section_404",
                framework=ComplianceFramework.SOX,
                title="Assessment of Internal Control",
                description="Management must assess effectiveness of internal controls",
                category="internal_controls",
                mandatory=True,
                controls=[
                    "control_documentation",
                    "control_testing",
                    "deficiency_remediation"
                ],
                validation_rules=[
                    {
                        "type": "control_documentation_check",
                        "required": True,
                        "description": "Internal controls must be documented"
                    },
                    {
                        "type": "audit_trail_check",
                        "scope": ["financial_transactions", "system_changes"],
                        "required": True,
                        "description": "Comprehensive audit trails required"
                    }
                ],
                evidence_required=[
                    "internal_control_documentation",
                    "control_testing_results",
                    "audit_trails"
                ],
                remediation_guidance="Document and test internal controls over financial reporting",
                priority=1
            )
        ]
        
        self.requirements[ComplianceFramework.SOX] = sox_requirements
    
    def _initialize_iso_27001_requirements(self):
        """Initialize ISO 27001 compliance requirements."""
        
        iso_requirements = [
            ComplianceRequirement(
                requirement_id="iso_27001_a5",
                framework=ComplianceFramework.ISO_27001,
                title="Information Security Policies",
                description="Establish and maintain information security policies",
                category="governance",
                mandatory=True,
                controls=[
                    "security_policy_framework",
                    "policy_communication",
                    "policy_review_process"
                ],
                validation_rules=[
                    {
                        "type": "policy_documentation_check",
                        "policies": ["security", "privacy", "acceptable_use"],
                        "required": True,
                        "description": "Security policies must be documented"
                    }
                ],
                evidence_required=[
                    "security_policies",
                    "policy_approval_records",
                    "policy_review_schedules"
                ],
                remediation_guidance="Develop comprehensive information security policies",
                priority=2
            ),
            
            ComplianceRequirement(
                requirement_id="iso_27001_a8",
                framework=ComplianceFramework.ISO_27001,
                title="Asset Management",
                description="Identify and classify information assets",
                category="asset_management",
                mandatory=True,
                controls=[
                    "asset_inventory",
                    "asset_classification",
                    "asset_handling_procedures"
                ],
                validation_rules=[
                    {
                        "type": "asset_inventory_check",
                        "asset_types": ["data", "systems", "applications"],
                        "required": True,
                        "description": "Information asset inventory required"
                    }
                ],
                evidence_required=[
                    "asset_inventory",
                    "classification_schemes",
                    "handling_procedures"
                ],
                remediation_guidance="Create and maintain information asset inventory with classifications",
                priority=2
            )
        ]
        
        self.requirements[ComplianceFramework.ISO_27001] = iso_requirements
    
    # Main validation methods
    def validate_compliance(self, framework: ComplianceFramework, 
                          target_path: str) -> ComplianceReport:
        """
        Validate compliance against specified framework.
        
        Args:
            framework: Compliance framework to validate against
            target_path: Path to validate (file or directory)
            
        Returns:
            Compliance validation report
        """
        logger.info(f"Starting {framework.value} compliance validation of {target_path}")
        
        report_id = self._generate_report_id(framework, target_path)
        timestamp = datetime.now()
        
        if framework not in self.requirements:
            raise ValueError(f"Framework {framework.value} not supported")
        
        requirements = self.requirements[framework]
        violations = []
        evidence_collected = {}
        
        requirements_checked = len(requirements)
        requirements_passed = 0
        
        try:
            for requirement in requirements:
                logger.debug(f"Checking requirement: {requirement.requirement_id}")
                
                requirement_violations = self._validate_requirement(
                    requirement, target_path
                )
                
                if not requirement_violations:
                    requirements_passed += 1
                else:
                    violations.extend(requirement_violations)
                
                # Collect evidence
                evidence = self._collect_evidence(requirement, target_path)
                if evidence:
                    evidence_collected[requirement.requirement_id] = evidence
            
            requirements_failed = requirements_checked - requirements_passed
            
            # Calculate overall compliance score
            overall_score = (requirements_passed / requirements_checked) * 100
            
            # Generate recommendations
            recommendations = self._generate_recommendations(violations, framework)
            
            # Calculate next audit date
            next_audit_date = self._calculate_next_audit_date(framework, overall_score)
            
            report = ComplianceReport(
                report_id=report_id,
                framework=framework,
                target_path=target_path,
                timestamp=timestamp,
                overall_score=overall_score,
                violations=violations,
                requirements_checked=requirements_checked,
                requirements_passed=requirements_passed,
                requirements_failed=requirements_failed,
                evidence_collected=evidence_collected,
                recommendations=recommendations,
                next_audit_date=next_audit_date
            )
            
            self.validation_history.append(report)
            
            logger.info(f"Compliance validation completed - Score: {overall_score:.1f}% "
                       f"({requirements_passed}/{requirements_checked} requirements passed)")
            
            return report
            
        except Exception as e:
            logger.error(f"Compliance validation failed: {e}")
            raise
    
    def _validate_requirement(self, requirement: ComplianceRequirement, 
                            target_path: str) -> List[ComplianceViolation]:
        """Validate a single compliance requirement."""
        
        violations = []
        
        for rule in requirement.validation_rules:
            rule_violations = self._validate_rule(requirement, rule, target_path)
            violations.extend(rule_violations)
        
        return violations
    
    def _validate_rule(self, requirement: ComplianceRequirement, 
                      rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate a single validation rule."""
        
        violations = []
        rule_type = rule.get('type')
        
        if rule_type == 'data_field_check':
            violations.extend(self._validate_data_field_rule(requirement, rule, target_path))
        elif rule_type == 'code_pattern_check':
            violations.extend(self._validate_code_pattern_rule(requirement, rule, target_path))
        elif rule_type == 'api_endpoint_check':
            violations.extend(self._validate_api_endpoint_rule(requirement, rule, target_path))
        elif rule_type == 'encryption_check':
            violations.extend(self._validate_encryption_rule(requirement, rule, target_path))
        elif rule_type == 'access_control_check':
            violations.extend(self._validate_access_control_rule(requirement, rule, target_path))
        elif rule_type == 'logging_check':
            violations.extend(self._validate_logging_rule(requirement, rule, target_path))
        elif rule_type == 'card_data_check':
            violations.extend(self._validate_card_data_rule(requirement, rule, target_path))
        elif rule_type == 'tls_check':
            violations.extend(self._validate_tls_rule(requirement, rule, target_path))
        elif rule_type == 'phi_field_identification':
            violations.extend(self._validate_phi_rule(requirement, rule, target_path))
        elif rule_type == 'audit_trail_check':
            violations.extend(self._validate_audit_trail_rule(requirement, rule, target_path))
        else:
            logger.warning(f"Unknown rule type: {rule_type}")
        
        return violations
    
    def _validate_data_field_rule(self, requirement: ComplianceRequirement, 
                                rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate data field requirements."""
        
        violations = []
        pattern = rule.get('pattern')
        required = rule.get('required', False)
        
        if not pattern:
            return violations
        
        # Search for pattern in Python files
        python_files = self._get_python_files(target_path)
        pattern_found = False
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if re.search(pattern, content, re.IGNORECASE):
                    pattern_found = True
                    break
                    
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if required and not pattern_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='high',
                title=f"Missing required data field: {pattern}",
                description=rule.get('description', 'Required data field not found'),
                remediation=requirement.remediation_guidance,
                risk_score=8.0
            )
            violations.append(violation)
        
        return violations
    
    def _validate_code_pattern_rule(self, requirement: ComplianceRequirement,
                                  rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate code pattern requirements."""
        
        violations = []
        pattern = rule.get('pattern')
        required = rule.get('required', False)
        
        if not pattern:
            return violations
        
        python_files = self._get_python_files(target_path)
        pattern_found = False
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                
                matches = list(re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE))
                
                if matches:
                    pattern_found = True
                    
                    # For some patterns, finding them might be the violation
                    if not required:
                        for match in matches:
                            line_num = content[:match.start()].count('\n') + 1
                            
                            violation = ComplianceViolation(
                                violation_id=self._generate_violation_id(requirement, rule, target_path, line_num),
                                requirement_id=requirement.requirement_id,
                                framework=requirement.framework,
                                severity='medium',
                                title=f"Compliance concern: {rule.get('description', 'Pattern found')}",
                                description=rule.get('description', 'Potentially non-compliant pattern detected'),
                                file_path=file_path,
                                line_number=line_num,
                                code_snippet=self._extract_code_snippet(content, line_num),
                                remediation=requirement.remediation_guidance,
                                risk_score=5.0
                            )
                            violations.append(violation)
                    
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if required and not pattern_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='high',
                title=f"Missing required functionality: {pattern}",
                description=rule.get('description', 'Required functionality not implemented'),
                remediation=requirement.remediation_guidance,
                risk_score=8.0
            )
            violations.append(violation)
        
        return violations
    
    def _validate_api_endpoint_rule(self, requirement: ComplianceRequirement,
                                  rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate API endpoint requirements."""
        
        violations = []
        endpoints = rule.get('endpoints', [])
        required = rule.get('required', False)
        
        if not endpoints:
            return violations
        
        # Look for Flask route definitions
        python_files = self._get_python_files(target_path)
        found_endpoints = set()
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for Flask route decorators
                route_pattern = r'@app\.route\s*\(\s*["\']([^"\']+)["\']'
                routes = re.findall(route_pattern, content)
                found_endpoints.update(routes)
                
                # Look for Blueprint routes
                blueprint_pattern = r'@\w+\.route\s*\(\s*["\']([^"\']+)["\']'
                blueprint_routes = re.findall(blueprint_pattern, content)
                found_endpoints.update(blueprint_routes)
                
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if required:
            missing_endpoints = []
            for endpoint in endpoints:
                if not any(endpoint in found_endpoint for found_endpoint in found_endpoints):
                    missing_endpoints.append(endpoint)
            
            if missing_endpoints:
                violation = ComplianceViolation(
                    violation_id=self._generate_violation_id(requirement, rule, target_path),
                    requirement_id=requirement.requirement_id,
                    framework=requirement.framework,
                    severity='high',
                    title=f"Missing required API endpoints",
                    description=f"Required endpoints not found: {', '.join(missing_endpoints)}",
                    evidence={'missing_endpoints': missing_endpoints, 'found_endpoints': list(found_endpoints)},
                    remediation=requirement.remediation_guidance,
                    risk_score=7.0
                )
                violations.append(violation)
        
        return violations
    
    def _validate_encryption_rule(self, requirement: ComplianceRequirement,
                                rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate encryption requirements."""
        
        violations = []
        required = rule.get('required', False)
        
        if not required:
            return violations
        
        # Look for encryption implementations
        python_files = self._get_python_files(target_path)
        encryption_found = False
        
        encryption_patterns = [
            r'from\s+cryptography',
            r'import\s+.*crypt',
            r'AES\.|RSA\.|DES\.',
            r'encrypt\s*\(',
            r'decrypt\s*\(',
            r'hashlib\.(sha256|sha512)',
            r'bcrypt\.',
            r'scrypt\(',
            r'PBKDF2',
            r'Fernet\('
        ]
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for pattern in encryption_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        encryption_found = True
                        break
                
                if encryption_found:
                    break
                    
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if not encryption_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='critical',
                title="Missing encryption implementation",
                description="No encryption mechanisms found in codebase",
                remediation=requirement.remediation_guidance,
                risk_score=9.0
            )
            violations.append(violation)
        
        return violations
    
    def _validate_access_control_rule(self, requirement: ComplianceRequirement,
                                    rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate access control requirements."""
        
        violations = []
        required = rule.get('required', False)
        
        if not required:
            return violations
        
        # Look for access control implementations
        python_files = self._get_python_files(target_path)
        access_control_found = False
        
        access_control_patterns = [
            r'@login_required',
            r'@has_access',
            r'@roles_required',
            r'@permission_required',
            r'current_user\.has_role',
            r'check_permission',
            r'authorize\s*\(',
            r'@requires_auth',
            r'flask_principal',
            r'flask_security'
        ]
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for pattern in access_control_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        access_control_found = True
                        break
                
                if access_control_found:
                    break
                    
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if not access_control_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='high',
                title="Missing access control mechanisms",
                description="No access control implementations found",
                remediation=requirement.remediation_guidance,
                risk_score=8.0
            )
            violations.append(violation)
        
        return violations
    
    def _validate_logging_rule(self, requirement: ComplianceRequirement,
                             rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate logging requirements."""
        
        violations = []
        log_types = rule.get('log_types', [])
        required = rule.get('required', False)
        
        if not required:
            return violations
        
        python_files = self._get_python_files(target_path)
        logging_found = False
        found_log_types = set()
        
        logging_patterns = {
            'security': [r'security.*log', r'auth.*log', r'login.*log'],
            'access': [r'access.*log', r'request.*log', r'audit.*log'],
            'data_changes': [r'data.*log', r'change.*log', r'modify.*log'],
            'general': [r'logging\.|logger\.', r'log\.(info|debug|warning|error)']
        }
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for log_type, patterns in logging_patterns.items():
                    for pattern in patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            logging_found = True
                            found_log_types.add(log_type)
                            break
                            
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if not logging_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='medium',
                title="Missing logging implementation",
                description="No logging mechanisms found",
                evidence={'required_log_types': log_types, 'found_log_types': list(found_log_types)},
                remediation=requirement.remediation_guidance,
                risk_score=6.0
            )
            violations.append(violation)
        else:
            # Check if specific log types are missing
            missing_log_types = set(log_types) - found_log_types
            if missing_log_types:
                violation = ComplianceViolation(
                    violation_id=self._generate_violation_id(requirement, rule, target_path),
                    requirement_id=requirement.requirement_id,
                    framework=requirement.framework,
                    severity='medium',
                    title="Incomplete logging coverage",
                    description=f"Missing log types: {', '.join(missing_log_types)}",
                    evidence={'missing_log_types': list(missing_log_types), 'found_log_types': list(found_log_types)},
                    remediation=requirement.remediation_guidance,
                    risk_score=5.0
                )
                violations.append(violation)
        
        return violations
    
    def _validate_card_data_rule(self, requirement: ComplianceRequirement,
                               rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate credit card data handling requirements."""
        
        violations = []
        patterns = rule.get('patterns', [])
        encryption_required = rule.get('encryption_required', False)
        
        python_files = self._get_python_files(target_path)
        card_data_found = []
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                
                for pattern in patterns:
                    matches = list(re.finditer(pattern, content, re.IGNORECASE))
                    
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        card_data_found.append({
                            'file': file_path,
                            'line': line_num,
                            'pattern': pattern,
                            'match': match.group()
                        })
                        
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        # If card data is found, check if encryption is implemented
        if card_data_found and encryption_required:
            # Look for encryption near card data
            for card_data in card_data_found:
                file_path = card_data['file']
                line_num = card_data['line']
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        lines = content.split('\n')
                    
                    # Check surrounding lines for encryption
                    start_line = max(0, line_num - 10)
                    end_line = min(len(lines), line_num + 10)
                    context = '\n'.join(lines[start_line:end_line])
                    
                    encryption_patterns = [r'encrypt', r'hash', r'crypt', r'secure']
                    encryption_found = any(re.search(pattern, context, re.IGNORECASE) 
                                         for pattern in encryption_patterns)
                    
                    if not encryption_found:
                        violation = ComplianceViolation(
                            violation_id=self._generate_violation_id(requirement, rule, target_path, line_num),
                            requirement_id=requirement.requirement_id,
                            framework=requirement.framework,
                            severity='critical',
                            title="Unencrypted card data detected",
                            description="Credit card data found without encryption",
                            file_path=file_path,
                            line_number=line_num,
                            code_snippet=self._extract_code_snippet(content, line_num),
                            evidence={'card_data_pattern': card_data['pattern']},
                            remediation=requirement.remediation_guidance,
                            risk_score=9.5
                        )
                        violations.append(violation)
                        
                except Exception as e:
                    logger.warning(f"Could not validate encryption for {file_path}: {e}")
        
        return violations
    
    def _validate_tls_rule(self, requirement: ComplianceRequirement,
                         rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate TLS/SSL requirements."""
        
        violations = []
        min_version = rule.get('min_version', 'TLS 1.2')
        required = rule.get('required', False)
        
        if not required:
            return violations
        
        # Look for TLS configuration
        python_files = self._get_python_files(target_path)
        config_files = self._get_config_files(target_path)
        all_files = python_files + config_files
        
        tls_config_found = False
        weak_tls_found = []
        
        for file_path in all_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for SSL/TLS configuration
                tls_patterns = [
                    r'ssl_context',
                    r'HTTPS',
                    r'TLS',
                    r'SSL',
                    r'certificates?',
                    r'ssl_verify'
                ]
                
                for pattern in tls_patterns:
                    if re.search(pattern, content, re.IGNORECASE):
                        tls_config_found = True
                        break
                
                # Look for weak TLS versions
                weak_tls_patterns = [
                    r'TLS.*1\.0',
                    r'TLS.*1\.1', 
                    r'SSL.*v[23]',
                    r'ssl_version.*v[23]'
                ]
                
                for pattern in weak_tls_patterns:
                    matches = list(re.finditer(pattern, content, re.IGNORECASE))
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        weak_tls_found.append({
                            'file': file_path,
                            'line': line_num,
                            'match': match.group()
                        })
                        
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        if not tls_config_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='high',
                title="Missing TLS configuration",
                description="No TLS/SSL configuration found",
                remediation=requirement.remediation_guidance,
                risk_score=8.0
            )
            violations.append(violation)
        
        # Report weak TLS versions
        for weak_tls in weak_tls_found:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path, weak_tls['line']),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='high',
                title="Weak TLS version detected",
                description=f"Weak TLS configuration: {weak_tls['match']}",
                file_path=weak_tls['file'],
                line_number=weak_tls['line'],
                evidence={'weak_tls_version': weak_tls['match'], 'min_required': min_version},
                remediation=requirement.remediation_guidance,
                risk_score=7.0
            )
            violations.append(violation)
        
        return violations
    
    def _validate_phi_rule(self, requirement: ComplianceRequirement,
                         rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate PHI (Protected Health Information) requirements."""
        
        violations = []
        phi_indicators = rule.get('phi_indicators', [])
        required = rule.get('required', False)
        
        python_files = self._get_python_files(target_path)
        phi_fields_found = []
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for indicator in phi_indicators:
                    pattern = rf'\b{indicator}\b'
                    matches = list(re.finditer(pattern, content, re.IGNORECASE))
                    
                    for match in matches:
                        line_num = content[:match.start()].count('\n') + 1
                        phi_fields_found.append({
                            'file': file_path,
                            'line': line_num,
                            'indicator': indicator,
                            'context': self._extract_code_snippet(content, line_num)
                        })
                        
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        # Check if PHI fields have proper protection
        for phi_field in phi_fields_found:
            # Look for protection mechanisms around PHI fields
            file_path = phi_field['file']
            line_num = phi_field['line']
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                
                # Check surrounding context for protection
                start_line = max(0, line_num - 5)
                end_line = min(len(lines), line_num + 5)
                context = '\n'.join(lines[start_line:end_line])
                
                protection_patterns = [
                    r'encrypt', r'hash', r'secure', r'protect',
                    r'@login_required', r'@has_access',
                    r'permission', r'authorize'
                ]
                
                protection_found = any(re.search(pattern, context, re.IGNORECASE) 
                                     for pattern in protection_patterns)
                
                if not protection_found:
                    violation = ComplianceViolation(
                        violation_id=self._generate_violation_id(requirement, rule, target_path, line_num),
                        requirement_id=requirement.requirement_id,
                        framework=requirement.framework,
                        severity='high',
                        title=f"Unprotected PHI field: {phi_field['indicator']}",
                        description="PHI field found without adequate protection mechanisms",
                        file_path=file_path,
                        line_number=line_num,
                        code_snippet=phi_field['context'],
                        evidence={'phi_indicator': phi_field['indicator']},
                        remediation=requirement.remediation_guidance,
                        risk_score=8.5
                    )
                    violations.append(violation)
                    
            except Exception as e:
                logger.warning(f"Could not validate PHI protection for {file_path}: {e}")
        
        return violations
    
    def _validate_audit_trail_rule(self, requirement: ComplianceRequirement,
                                 rule: Dict[str, Any], target_path: str) -> List[ComplianceViolation]:
        """Validate audit trail requirements."""
        
        violations = []
        scope = rule.get('scope', [])
        required = rule.get('required', False)
        
        if not required:
            return violations
        
        python_files = self._get_python_files(target_path)
        audit_mechanisms_found = {}
        
        audit_patterns = {
            'financial_transactions': [r'transaction.*log', r'payment.*log', r'financial.*log'],
            'system_changes': [r'change.*log', r'modify.*log', r'update.*log'],
            'user_actions': [r'user.*log', r'action.*log', r'activity.*log'],
            'data_access': [r'access.*log', r'query.*log', r'read.*log']
        }
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for audit_type in scope:
                    patterns = audit_patterns.get(audit_type, [])
                    
                    for pattern in patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            if audit_type not in audit_mechanisms_found:
                                audit_mechanisms_found[audit_type] = []
                            audit_mechanisms_found[audit_type].append(file_path)
                            break
                            
            except Exception as e:
                logger.warning(f"Could not scan file {file_path}: {e}")
        
        # Check for missing audit mechanisms
        missing_audit_types = set(scope) - set(audit_mechanisms_found.keys())
        
        if missing_audit_types:
            violation = ComplianceViolation(
                violation_id=self._generate_violation_id(requirement, rule, target_path),
                requirement_id=requirement.requirement_id,
                framework=requirement.framework,
                severity='medium',
                title="Missing audit trail mechanisms",
                description=f"Audit trails not found for: {', '.join(missing_audit_types)}",
                evidence={
                    'missing_audit_types': list(missing_audit_types),
                    'found_audit_types': list(audit_mechanisms_found.keys())
                },
                remediation=requirement.remediation_guidance,
                risk_score=6.0
            )
            violations.append(violation)
        
        return violations
    
    def _collect_evidence(self, requirement: ComplianceRequirement, 
                        target_path: str) -> Dict[str, Any]:
        """Collect evidence for compliance requirement."""
        
        evidence = {}
        
        for evidence_type in requirement.evidence_required:
            if evidence_type == 'consent_records':
                evidence[evidence_type] = self._collect_consent_evidence(target_path)
            elif evidence_type == 'encryption_implementation':
                evidence[evidence_type] = self._collect_encryption_evidence(target_path)
            elif evidence_type == 'access_control_policies':
                evidence[evidence_type] = self._collect_access_control_evidence(target_path)
            elif evidence_type == 'audit_log_samples':
                evidence[evidence_type] = self._collect_audit_log_evidence(target_path)
            # Add more evidence collection methods as needed
        
        return evidence
    
    def _collect_consent_evidence(self, target_path: str) -> Dict[str, Any]:
        """Collect consent management evidence."""
        
        evidence = {
            'consent_fields_found': [],
            'consent_management_code': [],
            'privacy_policy_references': []
        }
        
        python_files = self._get_python_files(target_path)
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for consent-related fields
                consent_patterns = [r'consent', r'opt.*in', r'agreement', r'terms.*accept']
                for pattern in consent_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        evidence['consent_fields_found'].extend(matches)
                
                # Look for privacy policy references
                if re.search(r'privacy.*policy', content, re.IGNORECASE):
                    evidence['privacy_policy_references'].append(file_path)
                    
            except Exception as e:
                logger.warning(f"Could not collect consent evidence from {file_path}: {e}")
        
        return evidence
    
    def _collect_encryption_evidence(self, target_path: str) -> Dict[str, Any]:
        """Collect encryption implementation evidence."""
        
        evidence = {
            'encryption_libraries': [],
            'encryption_methods': [],
            'key_management': []
        }
        
        python_files = self._get_python_files(target_path)
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for encryption libraries
                crypto_imports = re.findall(r'from\s+(cryptography|crypto|Crypto)\s+import\s+([^\n]+)', content)
                evidence['encryption_libraries'].extend([f"{imp[0]}.{imp[1]}" for imp in crypto_imports])
                
                # Look for encryption methods
                crypto_methods = re.findall(r'(encrypt|decrypt|hash|sign|verify)\s*\(', content, re.IGNORECASE)
                evidence['encryption_methods'].extend(crypto_methods)
                
            except Exception as e:
                logger.warning(f"Could not collect encryption evidence from {file_path}: {e}")
        
        return evidence
    
    def _collect_access_control_evidence(self, target_path: str) -> Dict[str, Any]:
        """Collect access control evidence."""
        
        evidence = {
            'decorators_found': [],
            'role_checks': [],
            'permission_systems': []
        }
        
        python_files = self._get_python_files(target_path)
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for access control decorators
                decorators = re.findall(r'@(login_required|has_access|permission_required|roles_required)', content)
                evidence['decorators_found'].extend(decorators)
                
                # Look for role checks
                role_checks = re.findall(r'current_user\.(has_role|is_admin|can)', content)
                evidence['role_checks'].extend(role_checks)
                
            except Exception as e:
                logger.warning(f"Could not collect access control evidence from {file_path}: {e}")
        
        return evidence
    
    def _collect_audit_log_evidence(self, target_path: str) -> Dict[str, Any]:
        """Collect audit logging evidence."""
        
        evidence = {
            'logging_statements': [],
            'log_levels': [],
            'audit_events': []
        }
        
        python_files = self._get_python_files(target_path)
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Look for logging statements
                log_statements = re.findall(r'log\.(info|debug|warning|error|critical)', content)
                evidence['logging_statements'].extend(log_statements)
                
                # Look for audit-specific events
                audit_events = re.findall(r'audit|log.*event|track.*activity', content, re.IGNORECASE)
                evidence['audit_events'].extend(audit_events)
                
            except Exception as e:
                logger.warning(f"Could not collect audit evidence from {file_path}: {e}")
        
        return evidence
    
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
    
    def _get_config_files(self, path: str) -> List[str]:
        """Get configuration files to scan."""
        
        config_files = []
        config_extensions = ['.json', '.yaml', '.yml', '.ini', '.cfg', '.conf']
        
        if os.path.isfile(path):
            if any(path.endswith(ext) for ext in config_extensions):
                config_files.append(path)
        else:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules'}]
                
                for file in files:
                    if any(file.endswith(ext) for ext in config_extensions):
                        config_files.append(os.path.join(root, file))
        
        return config_files
    
    def _generate_report_id(self, framework: ComplianceFramework, target_path: str) -> str:
        """Generate unique report ID."""
        timestamp = datetime.now().isoformat()
        content = f"{framework.value}_{target_path}_{timestamp}"
        return f"comp_{hashlib.md5(content.encode()).hexdigest()[:8]}"
    
    def _generate_violation_id(self, requirement: ComplianceRequirement, 
                             rule: Dict[str, Any], target_path: str,
                             line_num: Optional[int] = None) -> str:
        """Generate unique violation ID."""
        content = f"{requirement.requirement_id}_{rule.get('type', 'unknown')}_{target_path}"
        if line_num:
            content += f"_{line_num}"
        return f"viol_{hashlib.md5(content.encode()).hexdigest()[:8]}"
    
    def _extract_code_snippet(self, content: str, line_num: int, context: int = 2) -> str:
        """Extract code snippet around line number."""
        lines = content.split('\n')
        start_line = max(0, line_num - context - 1)
        end_line = min(len(lines), line_num + context)
        return '\n'.join(lines[start_line:end_line])
    
    def _generate_recommendations(self, violations: List[ComplianceViolation],
                                framework: ComplianceFramework) -> List[str]:
        """Generate compliance recommendations based on violations."""
        
        recommendations = []
        
        # Group violations by category
        violation_categories = {}
        for violation in violations:
            category = violation.requirement_id.split('_')[1] if '_' in violation.requirement_id else 'general'
            if category not in violation_categories:
                violation_categories[category] = []
            violation_categories[category].append(violation)
        
        # Generate category-specific recommendations
        for category, category_violations in violation_categories.items():
            if category == 'data' or category == 'processing':
                recommendations.append(
                    "Implement comprehensive data processing controls and consent management"
                )
            elif category == 'security' or category == 'technical':
                recommendations.append(
                    "Strengthen technical security measures including encryption and access controls"
                )
            elif category == 'audit' or category == 'logging':
                recommendations.append(
                    "Enhance audit logging and monitoring capabilities"
                )
            elif category == 'access' or category == 'authentication':
                recommendations.append(
                    "Improve access control and authentication mechanisms"
                )
        
        # Add framework-specific recommendations
        if framework == ComplianceFramework.GDPR:
            recommendations.append(
                "Consider implementing a privacy-by-design approach in all new features"
            )
        elif framework == ComplianceFramework.HIPAA:
            recommendations.append(
                "Ensure all PHI is properly identified, classified, and protected"
            )
        elif framework == ComplianceFramework.PCI_DSS:
            recommendations.append(
                "Implement comprehensive cardholder data protection measures"
            )
        
        return list(set(recommendations))  # Remove duplicates
    
    def _calculate_next_audit_date(self, framework: ComplianceFramework, 
                                 overall_score: float) -> datetime:
        """Calculate when the next compliance audit should occur."""
        
        # Base audit frequency by framework
        base_frequencies = {
            ComplianceFramework.GDPR: 180,      # 6 months
            ComplianceFramework.HIPAA: 365,     # 12 months  
            ComplianceFramework.PCI_DSS: 365,   # 12 months
            ComplianceFramework.SOX: 90,        # 3 months
            ComplianceFramework.ISO_27001: 365  # 12 months
        }
        
        base_days = base_frequencies.get(framework, 180)
        
        # Adjust frequency based on compliance score
        if overall_score >= 95:
            multiplier = 1.0  # Full interval
        elif overall_score >= 85:
            multiplier = 0.8  # 20% more frequent
        elif overall_score >= 75:
            multiplier = 0.6  # 40% more frequent
        else:
            multiplier = 0.5  # 50% more frequent
        
        audit_interval_days = int(base_days * multiplier)
        return datetime.now() + timedelta(days=audit_interval_days)
    
    # Public API methods
    def validate_gdpr(self, target_path: str) -> ComplianceReport:
        """Validate GDPR compliance."""
        return self.validate_compliance(ComplianceFramework.GDPR, target_path)
    
    def validate_hipaa(self, target_path: str) -> ComplianceReport:
        """Validate HIPAA compliance."""
        return self.validate_compliance(ComplianceFramework.HIPAA, target_path)
    
    def validate_pci_dss(self, target_path: str) -> ComplianceReport:
        """Validate PCI-DSS compliance."""
        return self.validate_compliance(ComplianceFramework.PCI_DSS, target_path)
    
    def validate_sox(self, target_path: str) -> ComplianceReport:
        """Validate SOX compliance."""
        return self.validate_compliance(ComplianceFramework.SOX, target_path)
    
    def get_supported_frameworks(self) -> List[str]:
        """Get list of supported compliance frameworks."""
        return [framework.value for framework in self.requirements.keys()]
    
    def get_framework_requirements(self, framework: ComplianceFramework) -> List[Dict[str, Any]]:
        """Get requirements for specific framework."""
        if framework not in self.requirements:
            return []
        
        return [
            {
                'requirement_id': req.requirement_id,
                'title': req.title,
                'description': req.description,
                'category': req.category,
                'mandatory': req.mandatory,
                'priority': req.priority
            }
            for req in self.requirements[framework]
        ]
    
    def add_custom_requirement(self, framework: ComplianceFramework, 
                             requirement: ComplianceRequirement):
        """Add custom compliance requirement."""
        if framework not in self.requirements:
            self.requirements[framework] = []
        
        self.requirements[framework].append(requirement)
        logger.info(f"Added custom requirement {requirement.requirement_id} to {framework.value}")
    
    def export_compliance_report(self, report: ComplianceReport, 
                                format: str = 'json') -> str:
        """Export compliance report in various formats."""
        
        if format == 'json':
            return self._export_compliance_json(report)
        elif format == 'html':
            return self._export_compliance_html(report)
        elif format == 'csv':
            return self._export_compliance_csv(report)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def _export_compliance_json(self, report: ComplianceReport) -> str:
        """Export compliance report as JSON."""
        
        data = {
            'report_id': report.report_id,
            'framework': report.framework.value,
            'target_path': report.target_path,
            'timestamp': report.timestamp.isoformat(),
            'overall_score': report.overall_score,
            'requirements_summary': {
                'total': report.requirements_checked,
                'passed': report.requirements_passed,
                'failed': report.requirements_failed
            },
            'violations': [
                {
                    'violation_id': v.violation_id,
                    'requirement_id': v.requirement_id,
                    'severity': v.severity,
                    'title': v.title,
                    'description': v.description,
                    'file_path': v.file_path,
                    'line_number': v.line_number,
                    'remediation': v.remediation,
                    'risk_score': v.risk_score,
                    'detected_at': v.detected_at.isoformat()
                }
                for v in report.violations
            ],
            'recommendations': report.recommendations,
            'next_audit_date': report.next_audit_date.isoformat() if report.next_audit_date else None,
            'evidence_collected': report.evidence_collected
        }
        
        return json.dumps(data, indent=2)
    
    def _export_compliance_html(self, report: ComplianceReport) -> str:
        """Export compliance report as HTML."""
        
        severity_colors = {
            'critical': '#dc3545',
            'high': '#fd7e14',
            'medium': '#ffc107',
            'low': '#28a745'
        }
        
        violations_by_severity = {}
        for violation in report.violations:
            severity = violation.severity
            if severity not in violations_by_severity:
                violations_by_severity[severity] = []
            violations_by_severity[severity].append(violation)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Compliance Report - {report.framework.value.upper()}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background: #f8f9fa; padding: 20px; margin-bottom: 20px; border-radius: 5px; }}
                .score {{ font-size: 2em; font-weight: bold; color: {'#28a745' if report.overall_score >= 80 else '#fd7e14' if report.overall_score >= 60 else '#dc3545'}; }}
                .summary {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 20px; }}
                .summary-box {{ background: #f8f9fa; padding: 15px; text-align: center; border-radius: 5px; }}
                .violation {{ border-left: 4px solid; margin: 10px 0; padding: 15px; background: #f8f9fa; }}
                .severity-critical {{ border-color: {severity_colors['critical']}; }}
                .severity-high {{ border-color: {severity_colors['high']}; }}
                .severity-medium {{ border-color: {severity_colors['medium']}; }}
                .severity-low {{ border-color: {severity_colors['low']}; }}
                .code {{ background: #e9ecef; padding: 10px; font-family: monospace; margin: 10px 0; }}
                .recommendations {{ background: #e3f2fd; padding: 15px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{report.framework.value.upper()} Compliance Report</h1>
                <p><strong>Report ID:</strong> {report.report_id}</p>
                <p><strong>Target:</strong> {report.target_path}</p>
                <p><strong>Generated:</strong> {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p class="score">Compliance Score: {report.overall_score:.1f}%</p>
            </div>
            
            <div class="summary">
                <div class="summary-box">
                    <h3>Requirements Checked</h3>
                    <div style="font-size: 2em;">{report.requirements_checked}</div>
                </div>
                <div class="summary-box">
                    <h3>Requirements Passed</h3>
                    <div style="font-size: 2em; color: #28a745;">{report.requirements_passed}</div>
                </div>
                <div class="summary-box">
                    <h3>Requirements Failed</h3>
                    <div style="font-size: 2em; color: #dc3545;">{report.requirements_failed}</div>
                </div>
            </div>
            
            <h2>Violations ({len(report.violations)})</h2>
        """
        
        for violation in report.violations:
            severity_class = f"severity-{violation.severity}"
            html += f"""
            <div class="violation {severity_class}">
                <h3>[{violation.severity.upper()}] {violation.title}</h3>
                <p><strong>Requirement:</strong> {violation.requirement_id}</p>
                <p><strong>Description:</strong> {violation.description}</p>
                {f'<p><strong>File:</strong> {violation.file_path}:{violation.line_number}</p>' if violation.file_path else ''}
                <p><strong>Remediation:</strong> {violation.remediation}</p>
                <p><strong>Risk Score:</strong> {violation.risk_score}/10</p>
                {f'<div class="code">{violation.code_snippet}</div>' if violation.code_snippet else ''}
            </div>
            """
        
        if report.recommendations:
            html += f"""
            <h2>Recommendations</h2>
            <div class="recommendations">
                <ul>
            """
            for recommendation in report.recommendations:
                html += f"<li>{recommendation}</li>"
            
            html += """
                </ul>
            </div>
            """
        
        if report.next_audit_date:
            html += f"""
            <h2>Next Audit</h2>
            <p>Next compliance audit recommended by: <strong>{report.next_audit_date.strftime('%Y-%m-%d')}</strong></p>
            """
        
        html += """
        </body>
        </html>
        """
        
        return html
    
    def _export_compliance_csv(self, report: ComplianceReport) -> str:
        """Export compliance report as CSV."""
        
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'Violation ID', 'Requirement ID', 'Framework', 'Severity', 'Title',
            'Description', 'File Path', 'Line Number', 'Risk Score', 'Remediation'
        ])
        
        # Violations
        for violation in report.violations:
            writer.writerow([
                violation.violation_id,
                violation.requirement_id,
                violation.framework.value,
                violation.severity,
                violation.title,
                violation.description,
                violation.file_path or '',
                violation.line_number or '',
                violation.risk_score,
                violation.remediation
            ])
        
        return output.getvalue()
    
    def get_compliance_history(self, framework: Optional[ComplianceFramework] = None,
                             limit: Optional[int] = None) -> List[ComplianceReport]:
        """Get compliance validation history."""
        
        history = self.validation_history
        
        if framework:
            history = [r for r in history if r.framework == framework]
        
        if limit:
            history = history[-limit:]
        
        return history