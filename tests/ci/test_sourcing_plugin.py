"""
tests/ci/test_sourcing_plugin.py

Unit tests for the Strategic Sourcing plugin.

Strategy
--------
- Pure-logic tests: no real DB, no Flask context.
- Session is a MagicMock; model instances are SimpleNamespace objects.
- Event emission and SCM plugin are monkey-patched.
- Covers: create_rfq, publish_rfq, submit_bid, evaluate_bids, award_rfq,
          cancel_rfq, deadline enforcement, duplicate bid guard,
          evaluation scoring formula.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.erp.procurement.sourcing.services import (
	SourcingService,
	SourcingServiceError,
	RFQNotFoundError,
	BidNotFoundError,
	InvalidStatusTransitionError,
	DeadlinePassedError,
	DuplicateBidError,
	_validate_criteria,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
	return str(uuid.uuid4())


def _now_utc() -> datetime:
	return datetime.now(timezone.utc)


def _make_rfq(**kw) -> SimpleNamespace:
	tid = _uid()
	defaults = dict(
		id=_uid(),
		tenant_id=tid,
		rfq_ref="RFQ-20250101-00001",
		title="Office Supplies",
		description=None,
		rfq_type="COMPETITIVE",
		status="DRAFT",
		submission_deadline=None,
		evaluation_criteria={"price_weight": 60, "quality_weight": 20, "delivery_weight": 20},
		items=[{"item_code": "A001", "qty": 10, "unit": "BOX", "estimated_unit_price_cents": 5000}],
		invited_suppliers=[],
		entity_id=None,
		created_by=None,
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _make_bid(**kw) -> SimpleNamespace:
	defaults = dict(
		id=_uid(),
		tenant_id=_uid(),
		rfq_id=_uid(),
		supplier_id=_uid(),
		submitted_at=_now_utc(),
		status="SUBMITTED",
		total_bid_cents=100_000,
		currency_code="USD",
		validity_days=30,
		delivery_days=14,
		quality_notes=None,
		line_items=[],
		technical_score=None,
		commercial_score=None,
		composite_score=None,
	)
	defaults.update(kw)
	return SimpleNamespace(**defaults)


def _mock_session(get_result=None, scalar_result=0) -> MagicMock:
	session = MagicMock()
	session.get.return_value = get_result
	session.execute.return_value.scalar.return_value = scalar_result
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.execute.return_value.scalar_one_or_none.return_value = None
	session.flush = MagicMock()
	session.add = MagicMock()
	return session


# ---------------------------------------------------------------------------
# _validate_criteria
# ---------------------------------------------------------------------------

class TestValidateCriteria:
	def test_valid_criteria_passes(self):
		_validate_criteria({"price_weight": 60, "quality_weight": 20, "delivery_weight": 20})

	def test_missing_key_raises(self):
		with pytest.raises(SourcingServiceError, match="missing key"):
			_validate_criteria({"price_weight": 60, "quality_weight": 20})

	def test_negative_weight_raises(self):
		with pytest.raises(SourcingServiceError, match="non-negative"):
			_validate_criteria({"price_weight": -10, "quality_weight": 60, "delivery_weight": 50})


# ---------------------------------------------------------------------------
# create_rfq
# ---------------------------------------------------------------------------

class TestCreateRFQ:
	def test_creates_rfq_in_draft(self):
		session = _mock_session(scalar_result=0)
		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			rfq = SourcingService.create_rfq(
				title="Stationery Q1",
				items=[{"item_code": "PEN-001", "qty": 100}],
				tenant_id=_uid(),
				session=session,
			)
		assert rfq.status == "DRAFT"
		assert rfq.rfq_ref.startswith("RFQ-")
		session.add.assert_called_once()

	def test_empty_title_raises(self):
		session = _mock_session(scalar_result=0)
		with pytest.raises(SourcingServiceError, match="empty"):
			SourcingService.create_rfq(
				title="   ",
				items=[{"item_code": "X"}],
				tenant_id=_uid(),
				session=session,
			)

	def test_empty_items_raises(self):
		session = _mock_session(scalar_result=0)
		with pytest.raises(SourcingServiceError, match="at least one item"):
			SourcingService.create_rfq(
				title="Valid Title",
				items=[],
				tenant_id=_uid(),
				session=session,
			)

	def test_invalid_rfq_type_raises(self):
		session = _mock_session(scalar_result=0)
		with pytest.raises(SourcingServiceError, match="Invalid rfq_type"):
			SourcingService.create_rfq(
				title="Valid",
				items=[{"item_code": "X"}],
				tenant_id=_uid(),
				session=session,
				rfq_type="BOGUS",
			)

	def test_custom_evaluation_criteria(self):
		session = _mock_session(scalar_result=0)
		criteria = {"price_weight": 50, "quality_weight": 30, "delivery_weight": 20}
		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			rfq = SourcingService.create_rfq(
				title="IT Equipment",
				items=[{"item_code": "LAPTOP-01", "qty": 5}],
				tenant_id=_uid(),
				session=session,
				evaluation_criteria=criteria,
			)
		assert rfq.evaluation_criteria["price_weight"] == 50

	def test_ref_sequential(self):
		session = _mock_session(scalar_result=9)
		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			rfq = SourcingService.create_rfq(
				title="T",
				items=[{"item_code": "X"}],
				tenant_id=_uid(),
				session=session,
			)
		assert rfq.rfq_ref.endswith("00010")


# ---------------------------------------------------------------------------
# publish_rfq
# ---------------------------------------------------------------------------

class TestPublishRFQ:
	def test_publishes_draft(self):
		rfq = _make_rfq(status="DRAFT")
		session = _mock_session(get_result=rfq)
		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			result = SourcingService.publish_rfq(
				rfq_id=rfq.id,
				invited_supplier_ids=["S1", "S2", "S3"],
				session=session,
			)
		assert result.status == "PUBLISHED"
		assert len(result.invited_suppliers) == 3

	def test_no_suppliers_raises(self):
		rfq = _make_rfq(status="DRAFT")
		session = _mock_session(get_result=rfq)
		with pytest.raises(SourcingServiceError, match="At least one supplier"):
			SourcingService.publish_rfq(
				rfq_id=rfq.id,
				invited_supplier_ids=[],
				session=session,
			)

	def test_cannot_publish_non_draft(self):
		rfq = _make_rfq(status="PUBLISHED")
		session = _mock_session(get_result=rfq)
		with pytest.raises(InvalidStatusTransitionError):
			SourcingService.publish_rfq(
				rfq_id=rfq.id,
				invited_supplier_ids=["S1"],
				session=session,
			)

	def test_rfq_not_found(self):
		session = _mock_session(get_result=None)
		with pytest.raises(RFQNotFoundError):
			SourcingService.publish_rfq(
				rfq_id=_uid(),
				invited_supplier_ids=["S1"],
				session=session,
			)


# ---------------------------------------------------------------------------
# submit_bid
# ---------------------------------------------------------------------------

class TestSubmitBid:
	def test_submits_bid(self):
		rfq = _make_rfq(status="PUBLISHED", submission_deadline=None)
		session = MagicMock()
		session.get.return_value = rfq
		session.flush = MagicMock()
		session.add = MagicMock()
		# duplicate count = 0
		session.execute.return_value.scalar.return_value = 0

		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			bid = SourcingService.submit_bid(
				rfq_id=rfq.id,
				supplier_id="SUP-001",
				line_items=[{"item_code": "PEN-001", "unit_price_cents": 500, "qty": 100}],
				total_cents=50_000,
				session=session,
				delivery_days=10,
			)
		assert bid.status == "SUBMITTED"
		assert bid.total_bid_cents == 50_000
		assert bid.delivery_days == 10

	def test_deadline_passed_raises(self):
		past = _now_utc() - timedelta(hours=1)
		rfq = _make_rfq(status="PUBLISHED", submission_deadline=past)
		session = _mock_session(get_result=rfq)
		with pytest.raises(DeadlinePassedError):
			SourcingService.submit_bid(
				rfq_id=rfq.id,
				supplier_id="SUP-001",
				line_items=[],
				total_cents=10_000,
				session=session,
			)

	def test_duplicate_bid_raises(self):
		rfq = _make_rfq(status="PUBLISHED", submission_deadline=None)
		session = MagicMock()
		session.get.return_value = rfq
		session.execute.return_value.scalar.return_value = 1  # existing bid
		with pytest.raises(DuplicateBidError):
			SourcingService.submit_bid(
				rfq_id=rfq.id,
				supplier_id="SUP-DUPE",
				line_items=[],
				total_cents=10_000,
				session=session,
			)

	def test_non_published_rfq_raises(self):
		rfq = _make_rfq(status="DRAFT")
		session = _mock_session(get_result=rfq)
		with pytest.raises(InvalidStatusTransitionError):
			SourcingService.submit_bid(
				rfq_id=rfq.id,
				supplier_id="SUP-001",
				line_items=[],
				total_cents=10_000,
				session=session,
			)

	def test_zero_total_raises(self):
		rfq = _make_rfq(status="PUBLISHED", submission_deadline=None)
		session = MagicMock()
		session.get.return_value = rfq
		session.execute.return_value.scalar.return_value = 0
		with pytest.raises(SourcingServiceError, match="positive"):
			SourcingService.submit_bid(
				rfq_id=rfq.id,
				supplier_id="SUP-001",
				line_items=[],
				total_cents=0,
				session=session,
			)


# ---------------------------------------------------------------------------
# evaluate_bids
# ---------------------------------------------------------------------------

class TestEvaluateBids:
	def _make_bids(self, rfq):
		bid_a = _make_bid(
			rfq_id=rfq.id,
			tenant_id=rfq.tenant_id,
			supplier_id="SUP-A",
			total_bid_cents=80_000,
			delivery_days=7,
			technical_score=Decimal("80"),
			status="SUBMITTED",
		)
		bid_b = _make_bid(
			rfq_id=rfq.id,
			tenant_id=rfq.tenant_id,
			supplier_id="SUP-B",
			total_bid_cents=100_000,
			delivery_days=14,
			technical_score=Decimal("60"),
			status="SUBMITTED",
		)
		return [bid_a, bid_b]

	def test_scores_bids_and_sets_evaluated(self):
		rfq = _make_rfq(status="PUBLISHED")
		bids = self._make_bids(rfq)

		session = MagicMock()
		session.get.return_value = rfq
		session.flush = MagicMock()
		session.execute.return_value.scalars.return_value.all.return_value = bids

		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			result = SourcingService.evaluate_bids(rfq_id=rfq.id, session=session)

		assert all(b.status == "EVALUATED" for b in result)
		assert all(b.composite_score is not None for b in result)
		# bid_a has lower price → higher price_score → should win
		assert result[0].supplier_id == "SUP-A"
		assert rfq.status == "CLOSED"

	def test_no_bids_raises(self):
		rfq = _make_rfq(status="PUBLISHED")
		session = MagicMock()
		session.get.return_value = rfq
		session.execute.return_value.scalars.return_value.all.return_value = []
		with pytest.raises(SourcingServiceError, match="No bids"):
			SourcingService.evaluate_bids(rfq_id=rfq.id, session=session)

	def test_wrong_status_raises(self):
		rfq = _make_rfq(status="DRAFT")
		session = _mock_session(get_result=rfq)
		with pytest.raises(InvalidStatusTransitionError):
			SourcingService.evaluate_bids(rfq_id=rfq.id, session=session)


# ---------------------------------------------------------------------------
# award_rfq
# ---------------------------------------------------------------------------

class TestAwardRFQ:
	def test_awards_rfq(self):
		rfq = _make_rfq(status="CLOSED")
		bid = _make_bid(rfq_id=rfq.id, tenant_id=rfq.tenant_id, status="EVALUATED")

		session = MagicMock()
		session.flush = MagicMock()

		def _get(model, id_):
			from pgappforge.plugins.erp.procurement.sourcing.models import RFQ, SupplierBid
			if model == RFQ or str(model) == str(RFQ):
				return rfq
			return bid

		session.get.side_effect = _get
		session.execute.return_value.scalars.return_value.all.return_value = []

		# award_rfq() tries: from pgappforge.plugins.erp.operations.scm.services import SCMService
		# That module may or may not be importable. Either way the try/except catches it
		# and po_id stays "". We just verify the award itself completes correctly.
		import sys
		scm_mod = "pgappforge.plugins.erp.operations.scm.services"
		originally_present = scm_mod in sys.modules
		# Force ImportError by temporarily removing the module if present
		saved = sys.modules.pop(scm_mod, None)
		try:
			with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
				result = SourcingService.award_rfq(
					rfq_id=rfq.id,
					winning_bid_id=bid.id,
					session=session,
				)
		finally:
			if saved is not None:
				sys.modules[scm_mod] = saved

		assert result["rfq_id"] == rfq.id
		assert result["winning_bid_id"] == bid.id
		assert rfq.status == "AWARDED"
		assert bid.status == "AWARDED"

	def test_cannot_award_already_awarded(self):
		rfq = _make_rfq(status="AWARDED")
		session = _mock_session(get_result=rfq)
		with pytest.raises(InvalidStatusTransitionError):
			SourcingService.award_rfq(rfq_id=rfq.id, winning_bid_id=_uid(), session=session)


# ---------------------------------------------------------------------------
# cancel_rfq
# ---------------------------------------------------------------------------

class TestCancelRFQ:
	def test_cancels_published_rfq(self):
		rfq = _make_rfq(status="PUBLISHED")
		session = _mock_session(get_result=rfq)
		with patch("pgappforge.plugins.erp.procurement.sourcing.services._emit"):
			result = SourcingService.cancel_rfq(
				rfq_id=rfq.id,
				reason="Budget cut",
				session=session,
			)
		assert result.status == "CANCELLED"

	def test_idempotent_cancel(self):
		rfq = _make_rfq(status="CANCELLED")
		session = _mock_session(get_result=rfq)
		result = SourcingService.cancel_rfq(rfq_id=rfq.id, reason="again", session=session)
		assert result.status == "CANCELLED"

	def test_cannot_cancel_awarded(self):
		rfq = _make_rfq(status="AWARDED")
		session = _mock_session(get_result=rfq)
		with pytest.raises(InvalidStatusTransitionError):
			SourcingService.cancel_rfq(rfq_id=rfq.id, reason="Too late", session=session)
