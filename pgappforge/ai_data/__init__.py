"""
AI-Powered Realistic Data Generation for PgForge

This module provides intelligent data generation capabilities that understand
business domains and generate contextually appropriate, realistic test data
for PgForge applications.

Features:
- Domain-aware data generation
- Contextual relationships and patterns
- Business rule compliance
- Multi-language support
- Integration with existing testing framework
"""

from .core.ai_engine import AIDataEngine
from .generators.domain_generator import DomainDataGenerator
from .generators.relationship_generator import RelationshipGenerator
from .patterns.business_patterns import BusinessPatternLibrary
from .models.data_models import DataGenerationRequest, GeneratedDataset

__all__ = [
    'AIDataEngine',
    'DomainDataGenerator',
    'RelationshipGenerator', 
    'BusinessPatternLibrary',
    'DataGenerationRequest',
    'GeneratedDataset'
]

__version__ = '1.0.0'