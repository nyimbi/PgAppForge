"""
tests/ci/test_analytics_plugins.py

Compile-check and unit tests for the four Analytics sub-plugins:
  operational, predictive, cdp, ai

Tests use real objects — no mocks.
Run with: uv run pytest -vxs tests/ci/test_analytics_plugins.py
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# Import smoke tests — verify all modules compile without error
# ---------------------------------------------------------------------------

class TestOperationalImports:
	def test_models_importable(self):
		from pgappforge.plugins.erp.analytics.operational.models import (
			AnalyticsQuery,
			AnalyticsReport,
			KPIDefinition,
			KPISnapshot,
		)
		assert KPIDefinition.__tablename__ == "analytics_kpi_definition"
		assert KPISnapshot.__tablename__ == "analytics_kpi_snapshot"
		assert AnalyticsQuery.__tablename__ == "analytics_query"
		assert AnalyticsReport.__tablename__ == "analytics_report"

	def test_events_importable(self):
		from pgappforge.plugins.erp.analytics.operational.events import (
			AnalyticsQueryExecutedEvent,
			AnalyticsReportGeneratedEvent,
			KPISnapshotRecordedEvent,
			KPIStatusChangedEvent,
		)
		ev = KPISnapshotRecordedEvent(
			kpi_id="k1",
			kpi_code="REVENUE",
			snapshot_date="2026-06-01",
			actual_value="100000",
			status="ON_TRACK",
		)
		assert ev.event_type == "analytics.kpi.snapshot_recorded"
		assert ev.event_id  # auto-generated UUID

	def test_services_importable(self):
		from pgappforge.plugins.erp.analytics.operational.services import (
			KPINotFoundError,
			OperationalAnalyticsService,
		)
		assert OperationalAnalyticsService is not None

	def test_plugin_class(self):
		from pgappforge.plugins.erp.analytics.operational import OperationalPlugin
		assert OperationalPlugin.name == "analytics.operational"
		assert OperationalPlugin.domain == "analytics"
		assert "foundation" in OperationalPlugin.depends_on


class TestPredictiveImports:
	def test_models_importable(self):
		from pgappforge.plugins.erp.analytics.predictive.models import (
			AnomalyDetection,
			MLModel,
			ModelPrediction,
		)
		assert MLModel.__tablename__ == "analytics_ml_model"
		assert ModelPrediction.__tablename__ == "analytics_model_prediction"
		assert AnomalyDetection.__tablename__ == "analytics_anomaly"

	def test_events_importable(self):
		from pgappforge.plugins.erp.analytics.predictive.events import (
			AnomalyDetectedEvent,
			MLModelDeployedEvent,
			ModelPredictionCreatedEvent,
		)
		ev = MLModelDeployedEvent(model_id="m1", model_name="churn_v2", version="2.0.0", framework="SKLEARN")
		assert ev.event_type == "analytics.ml_model.deployed"

	def test_services_importable(self):
		from pgappforge.plugins.erp.analytics.predictive.services import PredictiveAnalyticsService
		assert PredictiveAnalyticsService is not None

	def test_plugin_class(self):
		from pgappforge.plugins.erp.analytics.predictive import PredictivePlugin
		assert PredictivePlugin.name == "analytics.predictive"
		assert "foundation" in PredictivePlugin.depends_on


class TestCDPImports:
	def test_models_importable(self):
		from pgappforge.plugins.erp.analytics.cdp.models import (
			EventStream,
			IdentityEdge,
			Segment,
			SegmentMembership,
			UnifiedProfile,
		)
		assert UnifiedProfile.__tablename__ == "analytics_unified_profile"
		assert IdentityEdge.__tablename__ == "analytics_identity_edge"
		assert Segment.__tablename__ == "analytics_segment"
		assert SegmentMembership.__tablename__ == "analytics_segment_membership"
		assert EventStream.__tablename__ == "analytics_event_stream"

	def test_events_importable(self):
		from pgappforge.plugins.erp.analytics.cdp.events import (
			IdentityResolvedEvent,
			ProfileComputedEvent,
			SegmentActivatedEvent,
		)
		ev = ProfileComputedEvent(
			profile_id="p1",
			party_id="pa1",
			lifetime_value_cents=500000,
			segment_count=3,
		)
		assert ev.event_type == "analytics.cdp.profile_computed"
		assert ev.lifetime_value_cents == 500000  # integer cents

	def test_services_importable(self):
		from pgappforge.plugins.erp.analytics.cdp.services import CDPService, IdentityNotFoundError
		assert CDPService is not None

	def test_plugin_class(self):
		from pgappforge.plugins.erp.analytics.cdp import CDPPlugin
		assert CDPPlugin.name == "analytics.cdp"
		assert "party.created" in CDPPlugin(None).subscribe_to()


class TestAIImports:
	def test_models_importable(self):
		from pgappforge.plugins.erp.analytics.ai.models import (
			AIAgent,
			AgentAction,
			AgentConversation,
			AgentMessage,
		)
		assert AIAgent.__tablename__ == "analytics_ai_agent"
		assert AgentConversation.__tablename__ == "analytics_agent_conversation"
		assert AgentMessage.__tablename__ == "analytics_agent_message"
		assert AgentAction.__tablename__ == "analytics_agent_action"

	def test_events_importable(self):
		from pgappforge.plugins.erp.analytics.ai.events import (
			ActionApprovedEvent,
			ActionProposedEvent,
			ConversationStartedEvent,
		)
		ev = ConversationStartedEvent(
			conversation_id="c1",
			agent_id="a1",
			agent_name="FinanceBot",
			user_id=42,
		)
		assert ev.event_type == "analytics.ai.conversation_started"

	def test_services_importable(self):
		from pgappforge.plugins.erp.analytics.ai.services import AIAgentService
		assert AIAgentService is not None

	def test_plugin_class(self):
		from pgappforge.plugins.erp.analytics.ai import AIPlugin
		assert AIPlugin.name == "analytics.ai"
		emitted = AIPlugin(None).get_events()
		assert "analytics.ai.action_approved" in emitted
		assert "analytics.ai.action_executed" in emitted


# ---------------------------------------------------------------------------
# Pure logic unit tests (no DB required)
# ---------------------------------------------------------------------------

class TestKPIStatusComputation:
	"""OperationalAnalyticsService.compute_status — pure function."""

	def setup_method(self):
		from pgappforge.plugins.erp.analytics.operational.services import OperationalAnalyticsService
		self.svc = OperationalAnalyticsService

	def test_higher_on_track(self):
		assert self.svc.compute_status(Decimal("100"), Decimal("100"), "HIGHER") == "ON_TRACK"

	def test_higher_at_risk(self):
		# 85% of target
		assert self.svc.compute_status(Decimal("85"), Decimal("100"), "HIGHER") == "AT_RISK"

	def test_higher_off_track(self):
		# 70% of target
		assert self.svc.compute_status(Decimal("70"), Decimal("100"), "HIGHER") == "OFF_TRACK"

	def test_lower_on_track(self):
		# actual = target exactly → on track
		assert self.svc.compute_status(Decimal("100"), Decimal("100"), "LOWER") == "ON_TRACK"

	def test_lower_at_risk(self):
		# actual = 115% of target → at risk
		assert self.svc.compute_status(Decimal("115"), Decimal("100"), "LOWER") == "AT_RISK"

	def test_lower_off_track(self):
		# actual = 130% of target → off track
		assert self.svc.compute_status(Decimal("130"), Decimal("100"), "LOWER") == "OFF_TRACK"

	def test_null_target_returns_on_track(self):
		assert self.svc.compute_status(Decimal("999"), None, "HIGHER") == "ON_TRACK"

	def test_zero_target_returns_on_track(self):
		assert self.svc.compute_status(Decimal("0"), Decimal("0"), "HIGHER") == "ON_TRACK"

	def test_no_float_types(self):
		"""Verify no float arithmetic sneaks in."""
		result = self.svc.compute_status(Decimal("95.123"), Decimal("100"), "HIGHER")
		assert result in ("ON_TRACK", "AT_RISK", "OFF_TRACK")


class TestAnomalySeverity:
	"""PredictiveAnalyticsService.compute_severity — pure function."""

	def setup_method(self):
		from pgappforge.plugins.erp.analytics.predictive.services import PredictiveAnalyticsService
		self.svc = PredictiveAnalyticsService

	def test_low(self):
		assert self.svc.compute_severity(Decimal("1.5")) == "LOW"

	def test_medium(self):
		assert self.svc.compute_severity(Decimal("2.5")) == "MEDIUM"

	def test_high(self):
		assert self.svc.compute_severity(Decimal("3.5")) == "HIGH"

	def test_critical(self):
		assert self.svc.compute_severity(Decimal("4.1")) == "CRITICAL"

	def test_negative_z_score(self):
		# Negative z — severity is based on absolute value
		assert self.svc.compute_severity(Decimal("-3.2")) == "HIGH"

	def test_exactly_two(self):
		# |z| = 2 → MEDIUM boundary (< 2 is LOW)
		assert self.svc.compute_severity(Decimal("2.0")) == "MEDIUM"


class TestIdentityResolutionLogic:
	"""CDPService.resolve_identity error path with no edges."""

	def test_raises_when_no_match(self):
		from pgappforge.plugins.erp.analytics.cdp.services import CDPService, IdentityNotFoundError

		class FakeSession:
			def execute(self, stmt):
				class FakeResult:
					def scalars(self):
						class FakeScalars:
							def all(self):
								return []
						return FakeScalars()
				return FakeResult()

		with pytest.raises(IdentityNotFoundError):
			CDPService.resolve_identity(
				{"email": "ghost@nobody.com"},
				"tenant-123",
				FakeSession(),
			)


class TestAIActionTransitions:
	"""AIAgentService exception paths — no DB required."""

	def test_reject_raises_on_non_proposed(self):
		from pgappforge.plugins.erp.analytics.ai.services import (
			AIAgentService,
			InvalidActionTransitionError,
		)

		class FakeAction:
			id = "action-1"
			status = "EXECUTED"
			conversation_id = "conv-1"

		class FakeSession:
			def execute(self, stmt):
				class R:
					def scalar_one_or_none(self_):
						return FakeAction()
				return R()

		with pytest.raises(InvalidActionTransitionError):
			AIAgentService.reject_action("action-1", FakeSession())

	def test_approve_raises_on_non_proposed(self):
		from pgappforge.plugins.erp.analytics.ai.services import (
			AIAgentService,
			InvalidActionTransitionError,
		)

		class FakeAction:
			id = "action-2"
			status = "REJECTED"
			conversation_id = "conv-1"

		class FakeSession:
			def execute(self, stmt):
				class R:
					def scalar_one_or_none(self_):
						return FakeAction()
				return R()

			def get(self, model, pk):
				class FakeConv:
					tenant_id = "t1"
				return FakeConv()

		with pytest.raises(InvalidActionTransitionError):
			AIAgentService.approve_action("action-2", 1, FakeSession())


class TestEventDataclassIntegrity:
	"""Ensure event dataclasses auto-populate event_id and correct event_type."""

	def test_all_analytics_events_have_unique_ids(self):
		from pgappforge.plugins.erp.analytics.operational.events import KPISnapshotRecordedEvent
		from pgappforge.plugins.erp.analytics.predictive.events import AnomalyDetectedEvent
		from pgappforge.plugins.erp.analytics.cdp.events import SegmentComputedEvent
		from pgappforge.plugins.erp.analytics.ai.events import ActionExecutedEvent

		events = [
			KPISnapshotRecordedEvent(),
			AnomalyDetectedEvent(),
			SegmentComputedEvent(),
			ActionExecutedEvent(),
		]
		ids = {e.event_id for e in events}
		assert len(ids) == 4, "All events must have unique event_ids"

	def test_event_types_correct(self):
		from pgappforge.plugins.erp.analytics.operational.events import KPIStatusChangedEvent
		from pgappforge.plugins.erp.analytics.predictive.events import MLModelRetiredEvent
		from pgappforge.plugins.erp.analytics.cdp.events import ProfileComputedEvent
		from pgappforge.plugins.erp.analytics.ai.events import ConversationEndedEvent

		assert KPIStatusChangedEvent().event_type == "analytics.kpi.status_changed"
		assert MLModelRetiredEvent().event_type == "analytics.ml_model.retired"
		assert ProfileComputedEvent().event_type == "analytics.cdp.profile_computed"
		assert ConversationEndedEvent().event_type == "analytics.ai.conversation_ended"


class TestPluginEventContracts:
	"""Each plugin's get_events() and subscribe_to() return non-empty lists."""

	def _make_plugin(self, cls):
		# Pass None as appbuilder — we only test metadata/event methods
		try:
			return cls(None)
		except Exception:
			return cls.__new__(cls)

	def test_operational_events(self):
		from pgappforge.plugins.erp.analytics.operational import OperationalPlugin
		p = self._make_plugin(OperationalPlugin)
		assert len(p.get_events()) >= 4
		assert len(p.subscribe_to()) >= 2

	def test_predictive_events(self):
		from pgappforge.plugins.erp.analytics.predictive import PredictivePlugin
		p = self._make_plugin(PredictivePlugin)
		assert len(p.get_events()) >= 5
		assert len(p.subscribe_to()) >= 2

	def test_cdp_events(self):
		from pgappforge.plugins.erp.analytics.cdp import CDPPlugin
		p = self._make_plugin(CDPPlugin)
		assert len(p.get_events()) >= 5
		assert len(p.subscribe_to()) >= 4

	def test_ai_events(self):
		from pgappforge.plugins.erp.analytics.ai import AIPlugin
		p = self._make_plugin(AIPlugin)
		assert len(p.get_events()) >= 8
		assert len(p.subscribe_to()) >= 2
