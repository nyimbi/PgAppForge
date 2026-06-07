"""
pgappforge/plugins/erp/platform/process_mining/services.py

ProcessMiningService — discover processes, compute metrics, detect variants,
find bottlenecks, check conformance from DomainEventLog data.
"""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("ProcessMining event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("process_mining.discover")
	def _bpm_discover(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "process_mining.discover", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — ProcessMining BPM actions not registered")


# ---------------------------------------------------------------------------
# ProcessMiningService
# ---------------------------------------------------------------------------

class ProcessMiningService:
	"""Service layer for Process Mining analytics."""

	def discover_process(
		self,
		event_types: list[str],
		tenant_id: str,
		from_date: datetime,
		to_date: datetime,
		session: Any,
	) -> dict[str, Any]:
		"""Discover a process graph from DomainEventLog within a date range.

		Builds a directed transition graph (from_event → to_event) with counts.
		Emits ProcessDiscoveredEvent.

		Returns: {nodes, edges (sorted desc by count), case_count}
		"""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		from pgappforge.plugins.erp.platform.process_mining.events import ProcessDiscoveredEvent

		rows = session.execute(
			sa.select(
				DomainEventLog.aggregate_id,
				DomainEventLog.event_type,
				DomainEventLog.occurred_at,
			)
			.where(
				DomainEventLog.tenant_id == tenant_id,
				DomainEventLog.event_type.in_(event_types),
				DomainEventLog.occurred_at >= from_date,
				DomainEventLog.occurred_at <= to_date,
			)
			.order_by(DomainEventLog.aggregate_id, DomainEventLog.occurred_at)
		).all()

		transitions: dict[tuple[str, str], int] = {}
		last_event_per_case: dict[str, str] = {}

		for row in rows:
			prev = last_event_per_case.get(row.aggregate_id)
			if prev is not None:
				key = (prev, row.event_type)
				transitions[key] = transitions.get(key, 0) + 1
			last_event_per_case[row.aggregate_id] = row.event_type

		nodes = list(set(event_types))
		edges = [
			{"from": k[0], "to": k[1], "count": v}
			for k, v in transitions.items()
		]
		case_count = len(set(r.aggregate_id for r in rows))

		_emit(
			ProcessDiscoveredEvent(
				aggregate_id=tenant_id,
				aggregate_type="ProcessMining",
				tenant_id=tenant_id,
				case_count=case_count,
				edge_count=len(edges),
			),
			session,
		)

		return {
			"nodes": nodes,
			"edges": sorted(edges, key=lambda x: -x["count"]),
			"case_count": case_count,
		}

	def compute_process_metrics(
		self,
		event_types: list[str],
		tenant_id: str,
		period_start: datetime,
		period_end: datetime,
		session: Any,
	) -> dict[str, Any]:
		"""Compute cycle time statistics across all cases in the period.

		Cycle time = elapsed seconds from first to last event per aggregate_id.
		Returns: {avg_cycle_time_seconds, median_cycle_time_seconds, case_count, throughput_per_day}
		"""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog

		rows = session.execute(
			sa.select(
				DomainEventLog.aggregate_id,
				DomainEventLog.occurred_at,
			)
			.where(
				DomainEventLog.tenant_id == tenant_id,
				DomainEventLog.event_type.in_(event_types),
				DomainEventLog.occurred_at >= period_start,
				DomainEventLog.occurred_at <= period_end,
			)
			.order_by(DomainEventLog.aggregate_id, DomainEventLog.occurred_at)
		).all()

		# Group by case
		cases: dict[str, list[datetime]] = {}
		for row in rows:
			cases.setdefault(row.aggregate_id, []).append(row.occurred_at)

		cycle_times: list[float] = []
		for timestamps in cases.values():
			if len(timestamps) >= 2:
				delta = (timestamps[-1] - timestamps[0]).total_seconds()
				cycle_times.append(delta)

		case_count = len(cases)
		period_days = max(1, (period_end - period_start).total_seconds() / 86400)
		throughput_per_day = case_count / period_days

		return {
			"avg_cycle_time_seconds": statistics.mean(cycle_times) if cycle_times else 0.0,
			"median_cycle_time_seconds": statistics.median(cycle_times) if cycle_times else 0.0,
			"case_count": case_count,
			"throughput_per_day": round(throughput_per_day, 4),
		}

	def detect_variants(
		self,
		event_types: list[str],
		tenant_id: str,
		session: Any,
		*,
		top_n: int = 5,
	) -> list[dict[str, Any]]:
		"""Identify the top N process variants (unique event sequences) by frequency.

		Returns: [{sequence: str, count: int, frequency_pct: float}]
		"""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog

		rows = session.execute(
			sa.select(
				DomainEventLog.aggregate_id,
				DomainEventLog.event_type,
				DomainEventLog.occurred_at,
			)
			.where(
				DomainEventLog.tenant_id == tenant_id,
				DomainEventLog.event_type.in_(event_types),
			)
			.order_by(DomainEventLog.aggregate_id, DomainEventLog.occurred_at)
		).all()

		# Build sequence string per case
		sequences: dict[str, str] = {}
		for row in rows:
			seq = sequences.get(row.aggregate_id, "")
			sequences[row.aggregate_id] = (seq + " → " + row.event_type).lstrip(" → ")

		# Count variants
		variant_counts: dict[str, int] = {}
		for seq in sequences.values():
			variant_counts[seq] = variant_counts.get(seq, 0) + 1

		total = sum(variant_counts.values()) or 1
		sorted_variants = sorted(variant_counts.items(), key=lambda x: -x[1])

		return [
			{
				"sequence": seq,
				"count": cnt,
				"frequency_pct": round(cnt / total * 100, 2),
			}
			for seq, cnt in sorted_variants[:top_n]
		]

	def find_bottlenecks(
		self,
		event_types: list[str],
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Identify transition bottlenecks by computing average wait time per transition.

		The top 3 transitions by avg wait time are flagged as bottlenecks.
		Emits BottleneckFoundEvent for each.
		Returns: [{transition, avg_wait_seconds, case_count, impact_pct}]
		"""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog
		from pgappforge.plugins.erp.platform.process_mining.events import BottleneckFoundEvent

		rows = session.execute(
			sa.select(
				DomainEventLog.aggregate_id,
				DomainEventLog.event_type,
				DomainEventLog.occurred_at,
			)
			.where(
				DomainEventLog.tenant_id == tenant_id,
				DomainEventLog.event_type.in_(event_types),
			)
			.order_by(DomainEventLog.aggregate_id, DomainEventLog.occurred_at)
		).all()

		# Compute wait times per transition
		transition_waits: dict[tuple[str, str], list[float]] = {}
		last_per_case: dict[str, tuple[str, datetime]] = {}

		for row in rows:
			prev = last_per_case.get(row.aggregate_id)
			if prev is not None:
				prev_type, prev_time = prev
				wait = (row.occurred_at - prev_time).total_seconds()
				key = (prev_type, row.event_type)
				transition_waits.setdefault(key, []).append(wait)
			last_per_case[row.aggregate_id] = (row.event_type, row.occurred_at)

		if not transition_waits:
			return []

		total_waits = sum(sum(v) for v in transition_waits.values())

		transition_stats = [
			{
				"from_event": k[0],
				"to_event": k[1],
				"avg_wait_seconds": statistics.mean(v),
				"case_count": len(v),
				"impact_pct": round(sum(v) / total_waits * 100, 2) if total_waits > 0 else 0.0,
			}
			for k, v in transition_waits.items()
		]
		bottlenecks = sorted(transition_stats, key=lambda x: -x["avg_wait_seconds"])[:3]

		for bn in bottlenecks:
			_emit(
				BottleneckFoundEvent(
					aggregate_id=tenant_id,
					aggregate_type="ProcessMining",
					tenant_id=tenant_id,
					from_event=bn["from_event"],
					to_event=bn["to_event"],
					avg_wait_seconds=bn["avg_wait_seconds"],
					impact_pct=bn["impact_pct"],
				),
				session,
			)

		return [
			{
				"transition": f"{b['from_event']} → {b['to_event']}",
				"avg_wait_seconds": b["avg_wait_seconds"],
				"case_count": b["case_count"],
				"impact_pct": b["impact_pct"],
			}
			for b in bottlenecks
		]

	def check_conformance(
		self,
		event_types: list[str],
		expected_sequence: list[str],
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compare each case's actual event sequence against an expected sequence.

		A case is deviant if its sequence of event types does not match the
		expected_sequence exactly (strict order, all events present).

		Returns: {deviation_rate_pct, deviant_cases_count, total_cases}
		"""
		from pgappforge.plugins.erp.foundation.models import DomainEventLog

		rows = session.execute(
			sa.select(
				DomainEventLog.aggregate_id,
				DomainEventLog.event_type,
				DomainEventLog.occurred_at,
			)
			.where(
				DomainEventLog.tenant_id == tenant_id,
				DomainEventLog.event_type.in_(event_types),
			)
			.order_by(DomainEventLog.aggregate_id, DomainEventLog.occurred_at)
		).all()

		# Build sequence per case (only include expected event types in order)
		case_sequences: dict[str, list[str]] = {}
		for row in rows:
			case_sequences.setdefault(row.aggregate_id, []).append(row.event_type)

		total = len(case_sequences)
		deviant = 0
		for seq in case_sequences.values():
			# Filter to only expected event types, preserving order
			filtered = [e for e in seq if e in expected_sequence]
			if filtered != expected_sequence:
				deviant += 1

		deviation_rate = round(deviant / total * 100, 2) if total > 0 else 0.0

		return {
			"total_cases": total,
			"deviant_cases_count": deviant,
			"conformant_cases_count": total - deviant,
			"deviation_rate_pct": deviation_rate,
		}
