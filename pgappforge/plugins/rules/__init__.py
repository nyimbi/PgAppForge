"""
pgappforge/plugins/rules
========================

Rules Engine Plugin — visual no-code business rule builder.

Public surface
--------------
RulesEngine            — evaluates rule sets against (model, event, record)
RulesValidationError   — raised when a "block" action fires
get_rules_engine()     — module-level singleton
RulesMixin             — SQLAlchemy model mixin; auto-wires event listeners
RuleSet                — ORM model: collection of rules for a model class
Rule                   — ORM model: single rule (conditions + actions)
RuleExecution          — ORM model: audit log row
RulesBuilderView       — Flask/FAB view: dashboard + REST API
"""

from .engine import RulesEngine, RulesValidationError, get_rules_engine
from .mixin import RulesMixin
from .models import Rule, RuleExecution, RuleSet
from .views import RulesBuilderView

__all__ = [
	"RulesEngine",
	"RulesValidationError",
	"get_rules_engine",
	"RulesMixin",
	"RuleSet",
	"Rule",
	"RuleExecution",
	"RulesBuilderView",
]
