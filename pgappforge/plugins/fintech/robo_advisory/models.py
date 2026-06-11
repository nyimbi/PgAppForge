"""
pgappforge/plugins/fintech/robo_advisory/models.py

Robo Advisory models — investor profiles, goals, model portfolios, drift reports.

Design rules:
  - All PKs: UUID via gen_random_uuid() server-default + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True))
  - All models: tenant_id VARCHAR(64) NOT NULL
  - ALL monetary amounts: INTEGER cents (BigInteger)
  - Allocation stored as JSONB: {EQUITY: 60, BOND: 30, CASH: 10}

Table name convention: ft_robo_<entity>
"""
from __future__ import annotations

import uuid
import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	BigInteger,
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	Numeric,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RoboInvestorProfile
# ---------------------------------------------------------------------------

class RoboInvestorProfile(AuditMixin, Model):
	"""Robo-advisory investor profile — KYC, risk tolerance, automation settings."""

	__allow_unmapped__ = True
	__tablename__ = "ft_robo_profile"
	__table_args__ = (
		Index("ix_ft_robo_profile_tenant", "tenant_id"),
		Index("ix_ft_robo_profile_customer", "customer_id"),
		UniqueConstraint("tenant_id", "customer_id", name="uq_ft_robo_profile_tenant_customer"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True, comment="Tenant identifier")
	customer_id = Column(
		UUID(as_uuid=False),
		nullable=False,
		comment="FK to core banking customer — unique per tenant",
	)

	# Risk / horizon
	risk_tolerance = Column(
		String(15),
		nullable=False,
		default="MEDIUM",
		comment="LOW | MEDIUM | HIGH",
	)
	investment_horizon_years = Column(
		Integer,
		nullable=False,
		default=5,
		comment="Target investment horizon in years (>= 1 for suitability)",
	)

	# Auto-investment settings
	monthly_investment_cents = Column(
		BigInteger,
		nullable=False,
		default=0,
		comment="Recurring monthly investment amount in cents",
	)
	automation_enabled = Column(Boolean, nullable=False, default=False)
	automation_cadence = Column(
		String(10),
		nullable=False,
		default="MONTHLY",
		comment="DAILY | WEEKLY | MONTHLY | QUARTERLY",
	)

	# KYC / suitability gates
	kyc_verified = Column(Boolean, nullable=False, default=False)
	suitability_completed = Column(Boolean, nullable=False, default=False)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	goals: list["RoboGoal"] = relationship(
		"RoboGoal",
		back_populates="profile",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return (
			f"<RoboInvestorProfile customer={self.customer_id} "
			f"risk={self.risk_tolerance} kyc={self.kyc_verified}>"
		)


# ---------------------------------------------------------------------------
# RoboGoal
# ---------------------------------------------------------------------------

class RoboGoal(AuditMixin, Model):
	"""Investment goal — target amount, contribution schedule, linked model portfolio."""

	__allow_unmapped__ = True
	__tablename__ = "ft_robo_goal"
	__table_args__ = (
		Index("ix_ft_robo_goal_tenant", "tenant_id"),
		Index("ix_ft_robo_goal_profile", "profile_id"),
		Index("ix_ft_robo_goal_status", "status"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	profile_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_robo_profile.id", ondelete="CASCADE"),
		nullable=False,
	)

	goal_type = Column(
		String(20),
		nullable=False,
		comment="RETIREMENT | EDUCATION | HOME | WEALTH_GROWTH | INCOME | EMERGENCY",
	)
	goal_name = Column(String(200), nullable=False)

	# Financial target
	target_amount_cents = Column(BigInteger, nullable=False, comment="Goal target in cents")
	current_amount_cents = Column(BigInteger, nullable=False, default=0)
	target_date = Column(Date, nullable=True, comment="Optional target achievement date")
	monthly_contribution_cents = Column(BigInteger, nullable=False, default=0)

	# Linked portfolio (from wealth_management plugin or external)
	assigned_portfolio_id = Column(UUID(as_uuid=False), nullable=True)

	status = Column(
		String(10),
		nullable=False,
		default="ACTIVE",
		comment="ACTIVE | PAUSED | ACHIEVED | CANCELLED",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
		onupdate=lambda: datetime.now(timezone.utc),
	)

	# Relationships
	profile: "RoboInvestorProfile" = relationship("RoboInvestorProfile", back_populates="goals")
	drift_reports: list["RoboDriftReport"] = relationship(
		"RoboDriftReport",
		back_populates="goal",
		cascade="all, delete-orphan",
		lazy="dynamic",
	)

	def __repr__(self) -> str:
		return f"<RoboGoal {self.goal_name!r} type={self.goal_type} status={self.status}>"


# ---------------------------------------------------------------------------
# ModelPortfolio
# ---------------------------------------------------------------------------

class ModelPortfolio(AuditMixin, Model):
	"""Model portfolio template — defines asset allocation for a given risk level."""

	__allow_unmapped__ = True
	__tablename__ = "ft_robo_model_portfolio"
	__table_args__ = (
		Index("ix_ft_robo_model_portfolio_tenant", "tenant_id"),
		Index("ix_ft_robo_model_portfolio_risk", "risk_level"),
		Index("ix_ft_robo_model_portfolio_active", "is_active"),
		UniqueConstraint("tenant_id", "name", name="uq_ft_robo_model_portfolio_tenant_name"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	name = Column(String(100), nullable=False)
	risk_level = Column(
		String(15),
		nullable=False,
		comment="CONSERVATIVE | MODERATE | BALANCED | GROWTH | AGGRESSIVE",
	)
	description = Column(Text, nullable=True)

	# Allocation — {EQUITY: 60, BOND: 30, CASH: 10} — must sum to 100
	allocation: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		server_default="{}",
		comment="Asset class allocation percentages; values sum to 100",
	)

	# Expected characteristics
	expected_return_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		comment="Expected annual return percentage",
	)
	expected_volatility_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		comment="Expected annual volatility percentage",
	)

	is_active = Column(Boolean, nullable=False, default=True)

	def __repr__(self) -> str:
		return f"<ModelPortfolio {self.name!r} risk={self.risk_level}>"


# ---------------------------------------------------------------------------
# RoboDriftReport
# ---------------------------------------------------------------------------

class RoboDriftReport(AuditMixin, Model):
	"""Drift report — compares current allocation vs model target for a goal."""

	__allow_unmapped__ = True
	__tablename__ = "ft_robo_drift"
	__table_args__ = (
		Index("ix_ft_robo_drift_tenant", "tenant_id"),
		Index("ix_ft_robo_drift_goal", "goal_id"),
		Index("ix_ft_robo_drift_generated", "generated_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(String(64), nullable=False, index=True)
	goal_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_robo_goal.id", ondelete="CASCADE"),
		nullable=False,
	)
	model_portfolio_id = Column(
		UUID(as_uuid=False),
		ForeignKey("ft_robo_model_portfolio.id", ondelete="SET NULL"),
		nullable=True,
	)

	# Allocation snapshots
	target_allocation: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		server_default="{}",
		comment="Model portfolio target allocation at report time",
	)
	current_allocation: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		server_default="{}",
		comment="Observed portfolio allocation at report time",
	)

	# Drift metrics
	max_drift_pct = Column(
		Numeric(5, 2),
		nullable=False,
		default=0,
		comment="Maximum absolute drift across all asset classes",
	)
	rebalance_recommended = Column(Boolean, nullable=False, default=False)

	generated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	goal: "RoboGoal" = relationship("RoboGoal", back_populates="drift_reports")
	model_portfolio: "ModelPortfolio" = relationship("ModelPortfolio")

	def __repr__(self) -> str:
		return (
			f"<RoboDriftReport goal={self.goal_id} "
			f"max_drift={self.max_drift_pct}% rebalance={self.rebalance_recommended}>"
		)


__all__ = [
	"RoboInvestorProfile",
	"RoboGoal",
	"ModelPortfolio",
	"RoboDriftReport",
]
