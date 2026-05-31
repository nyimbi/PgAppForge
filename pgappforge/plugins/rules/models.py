"""
pgappforge/plugins/rules/models.py

SQLAlchemy models for the Rules Engine plugin.

Tables
------
rules_ruleset    — named collection of rules targeting a model
rules_rule       — individual rule with conditions + actions JSON
rules_execution  — audit log of every rule trigger
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model

log = logging.getLogger(__name__)


class RuleSet(Model):
	"""Named collection of rules that applies to one model class."""

	__allow_unmapped__ = True
	__tablename__ = "rules_ruleset"
	__table_args__ = (
		Index("ix_rules_ruleset_model_name", "model_name"),
		{"extend_existing": True},
	)

	id          = Column(Integer, primary_key=True, autoincrement=True)
	name        = Column(String(255), nullable=False, unique=True)
	description = Column(Text, nullable=True)
	model_name  = Column(String(255), nullable=False)  # indexed by ix_rules_ruleset_model_name in __table_args__
	enabled     = Column(Boolean, nullable=False, default=True)
	priority    = Column(Integer, nullable=False, default=100)

	rules: list[Rule] = relationship(
		"Rule",
		back_populates="ruleset",
		cascade="all, delete-orphan",
		order_by="Rule.order",
	)

	def __repr__(self) -> str:
		return f"<RuleSet {self.name!r} model={self.model_name!r}>"


class Rule(Model):
	"""Single rule: trigger event + condition list + action list."""

	__allow_unmapped__ = True
	__tablename__ = "rules_rule"
	__table_args__ = {"extend_existing": True}

	id             = Column(Integer, primary_key=True, autoincrement=True)
	ruleset_id     = Column(Integer, ForeignKey("rules_ruleset.id"), nullable=False)
	name           = Column(String(255), nullable=False)
	trigger_event  = Column(String(100), nullable=False, default="on_create")
	# [{field, op, value, logic}]
	conditions_json: list[dict[str, Any]] = Column(JSONB, nullable=False, default=list)
	# [{type, ...params}]
	actions_json: list[dict[str, Any]]    = Column(JSONB, nullable=False, default=list)
	enabled        = Column(Boolean, nullable=False, default=True)
	order          = Column(Integer, nullable=False, default=0)

	ruleset: RuleSet = relationship("RuleSet", back_populates="rules")
	executions: list[RuleExecution] = relationship(
		"RuleExecution",
		back_populates="rule",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return f"<Rule {self.name!r} event={self.trigger_event!r}>"


class RuleExecution(Model):
	"""Audit record written every time a rule is evaluated and fires."""

	__allow_unmapped__ = True
	__tablename__ = "rules_execution"
	__table_args__ = {"extend_existing": True}

	id           = Column(Integer, primary_key=True, autoincrement=True)
	rule_id      = Column(Integer, ForeignKey("rules_rule.id"), nullable=False)
	triggered_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
	)
	record_id    = Column(String(100), nullable=True)
	# "executed" | "skipped" | "blocked" | "error"
	outcome      = Column(String(20), nullable=False, default="executed")
	error        = Column(Text, nullable=True)

	rule: Rule = relationship("Rule", back_populates="executions")

	def __repr__(self) -> str:
		return f"<RuleExecution rule={self.rule_id} outcome={self.outcome!r}>"
