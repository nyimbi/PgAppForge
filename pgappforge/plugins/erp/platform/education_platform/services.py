"""
pgappforge/plugins/erp/platform/education_platform/services.py

EducationPlatformService — stateless service for the Education Platform domain.

Responsibilities:
  - LTI 1.3 launch parameter generation
  - xAPI statement recording → LearnerActivity
  - Learning path completion progress calculation
  - Verifiable credential issuance + verification
  - Next learning object recommendation based on competency gaps
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class EducationPlatformError(Exception):
	"""Base error for Education Platform domain violations."""


class LMSToolNotFoundError(EducationPlatformError):
	"""No LMSTool with the given id."""


class LearningObjectNotFoundError(EducationPlatformError):
	"""No LearningObject with the given id."""


class LearningPathNotFoundError(EducationPlatformError):
	"""No LearningPath with the given id."""


class CredentialNotFoundError(EducationPlatformError):
	"""No VerifiableCredential with the given id."""


class CredentialExpiredError(EducationPlatformError):
	"""The EduIssuedCredential has expired."""


class CredentialRevokedError(EducationPlatformError):
	"""The EduIssuedCredential has been revoked."""


# ---------------------------------------------------------------------------
# EducationPlatformService
# ---------------------------------------------------------------------------

class EducationPlatformService:
	"""Stateless Education Platform service.

	All methods take a SQLAlchemy session as first argument.
	"""

	VALID_TOOL_TYPES = frozenset({"LTI_1P3", "SCORM", "XAPI", "AICC"})
	VALID_LO_TYPES = frozenset({"MODULE", "QUIZ", "ASSIGNMENT", "VIDEO", "READING", "SIMULATION"})
	VALID_DIFFICULTIES = frozenset({"BEGINNER", "INTERMEDIATE", "ADVANCED"})
	VALID_CREDENTIAL_TYPES = frozenset({"CERTIFICATE", "BADGE", "DEGREE", "LICENSE"})

	# ------------------------------------------------------------------
	# LTI 1.3 Launch
	# ------------------------------------------------------------------

	def launch_lti_tool(
		self,
		session: Any,
		tool_id: str,
		learner_id: str,
		lo_id: str,
	) -> dict:
		"""Generate LTI 1.3 launch parameters for a tool + learner + LO combination.

		Returns a dict of LTI 1.3 message claims ready for JWT signing by the
		caller.  The caller is responsible for signing with their private key and
		redirecting to tool.launch_url.

		Does NOT perform OIDC login initiation — call auth_login_url separately.

		Returns:
		  {
		    "launch_url": str,
		    "client_id": str,
		    "deployment_id": str,
		    "nonce": str,
		    "iss": str,          # tool's issuer (platform URL)
		    "sub": str,          # learner_id
		    "aud": str,          # client_id
		    "context": {...},
		    "resource_link": {...},
		    "custom": {...},     # from tool.configuration.custom_params
		  }
		"""
		from pgappforge.plugins.erp.platform.education_platform.models import (
			LMSTool, LearningObject,
		)

		tool = session.get(LMSTool, tool_id)
		if tool is None:
			raise LMSToolNotFoundError(f"LMSTool {tool_id!r} not found")
		if tool.tool_type != "LTI_1P3":
			raise EducationPlatformError(
				f"launch_lti_tool only supports LTI_1P3 tools, got {tool.tool_type!r}"
			)
		if not tool.is_active:
			raise EducationPlatformError(f"LMSTool {tool_id!r} is inactive")

		lo = session.get(LearningObject, lo_id)
		if lo is None:
			raise LearningObjectNotFoundError(f"LearningObject {lo_id!r} not found")

		nonce = secrets.token_urlsafe(32)
		now = int(datetime.now(timezone.utc).timestamp())
		cfg = tool.configuration or {}

		params = {
			"launch_url": tool.launch_url,
			"client_id": tool.client_id or "",
			"deployment_id": tool.deployment_id or "",
			"nonce": nonce,
			"iss": cfg.get("platform_iss", ""),
			"sub": learner_id,
			"aud": tool.client_id or "",
			"iat": now,
			"exp": now + 3600,
			"https://purl.imsglobal.org/spec/lti/claim/message_type": "LtiResourceLinkRequest",
			"https://purl.imsglobal.org/spec/lti/claim/version": "1.3.0",
			"https://purl.imsglobal.org/spec/lti/claim/deployment_id": tool.deployment_id or "",
			"https://purl.imsglobal.org/spec/lti/claim/target_link_uri": tool.launch_url,
			"context": {
				"id": lo.lo_id,
				"title": lo.title,
				"type": ["http://purl.imsglobal.org/vocab/lis/v2/course#CourseSection"],
			},
			"resource_link": {
				"id": lo.lo_id,
				"title": lo.title,
				"description": lo.description or "",
			},
			"custom": cfg.get("custom_params", {}),
		}

		log.info(
			"EducationPlatformService: LTI 1.3 launch params generated"
			" tool=%r learner=%r lo=%r",
			tool_id, learner_id, lo_id,
		)
		return params

	# ------------------------------------------------------------------
	# xAPI Statement Recording
	# ------------------------------------------------------------------

	def record_xapi_statement(
		self,
		session: Any,
		learner_id: str,
		verb: str,
		object_id: str,
		result: dict,
		tenant_id: str = "",
	) -> Any:
		"""Record an xAPI statement as a LearnerActivity row.

		Verb semantics:
		  "launched"   → creates a new activity row (started_at = now)
		  "progressed" → updates progress_pct (new row, increments attempts if completed=False)
		  "completed"  → sets completed_at, score, passed
		  "passed"     → sets passed=True
		  "failed"     → sets passed=False

		object_id resolves to LearningObject.id (UUID) or LearningObject.lo_id (external).
		result dict keys: score (0-100), success (bool), duration_seconds (int), progress (0-100).

		Returns the newly inserted LearnerActivity.
		"""
		from pgappforge.plugins.erp.platform.education_platform.models import (
			LearningObject, LearnerActivity,
		)
		from pgappforge.plugins.erp.platform.education_platform.events import (
			LearnerActivityStartedEvent,
			LearnerActivityCompletedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		# Resolve LO by UUID or external lo_id
		lo = session.get(LearningObject, object_id)
		if lo is None:
			lo = session.execute(
				select(LearningObject).where(LearningObject.lo_id == object_id)
			).scalar_one_or_none()
		if lo is None:
			raise LearningObjectNotFoundError(f"LearningObject {object_id!r} not found")

		now = datetime.now(timezone.utc)
		score_val = result.get("score")
		success = result.get("success")
		duration = int(result.get("duration_seconds", 0))
		progress = float(result.get("progress", 0.0))

		completed_at = now if verb in ("completed", "passed", "failed") else None
		passed = None
		if verb == "passed":
			passed = True
		elif verb == "failed":
			passed = False
		elif verb == "completed" and success is not None:
			passed = bool(success)

		statement = {
			"id": str(uuid.uuid4()),
			"actor": {"account": {"homePage": "", "name": learner_id}},
			"verb": {
				"id": f"http://adlnet.gov/expapi/verbs/{verb}",
				"display": {"en-US": verb},
			},
			"object": {
				"id": lo.lo_id,
				"objectType": "Activity",
				"definition": {"name": {"en-US": lo.title}},
			},
			"result": result,
			"timestamp": now.isoformat(),
		}

		activity = LearnerActivity(
			tenant_id=tenant_id,
			learner_id=learner_id,
			lo_id=lo.id,
			started_at=now if verb == "launched" else now,
			completed_at=completed_at,
			progress_pct=min(100, max(0, progress)),
			score=score_val,
			passed=passed,
			time_spent_seconds=duration,
			attempts=1,
			xapi_statements=[statement],
		)
		session.add(activity)
		session.flush()

		if verb == "launched":
			_emit(LearnerActivityStartedEvent(
				aggregate_id=activity.id,
				aggregate_type="LearnerActivity",
				tenant_id=tenant_id,
				activity_id=activity.id,
				learner_id=learner_id,
				lo_id=lo.id,
				started_at=now.isoformat(),
			), session)
		elif verb in ("completed", "passed", "failed"):
			_emit(LearnerActivityCompletedEvent(
				aggregate_id=activity.id,
				aggregate_type="LearnerActivity",
				tenant_id=tenant_id,
				activity_id=activity.id,
				learner_id=learner_id,
				lo_id=lo.id,
				score=float(score_val) if score_val is not None else 0.0,
				passed=bool(passed),
				time_spent_seconds=duration,
			), session)

		log.info(
			"EducationPlatformService: xAPI statement recorded"
			" verb=%r learner=%r lo=%r",
			verb, learner_id, lo.id,
		)
		return activity

	# ------------------------------------------------------------------
	# Learning Path Progress
	# ------------------------------------------------------------------

	def calculate_completion_progress(
		self,
		session: Any,
		learner_id: str,
		path_id: str,
	) -> dict:
		"""Calculate a learner's completion progress through a learning path.

		Returns:
		  {
		    "path_id": str,
		    "total_items": int,
		    "required_items": int,
		    "completed_required": int,
		    "pct_complete": float,       # 0.0–100.0 over required items
		    "next_item": {               # None if all required complete
		      "item_id": str,
		      "lo_id": str,
		      "lo_title": str,
		      "sequence": int,
		    } | None,
		    "is_complete": bool,
		  }
		"""
		from pgappforge.plugins.erp.platform.education_platform.models import (
			LearningPath, PathItem, LearningObject, LearnerActivity,
		)

		path = session.get(LearningPath, path_id)
		if path is None:
			raise LearningPathNotFoundError(f"LearningPath {path_id!r} not found")

		items = session.execute(
			select(PathItem)
			.where(PathItem.path_id == path_id)
			.order_by(PathItem.sequence)
		).scalars().all()

		if not items:
			return {
				"path_id": path_id,
				"total_items": 0,
				"required_items": 0,
				"completed_required": 0,
				"pct_complete": 100.0,
				"next_item": None,
				"is_complete": True,
			}

		# Fetch latest completed activity per LO for this learner
		lo_ids = [item.lo_id for item in items]
		completed_lo_ids: set[str] = set()

		rows = session.execute(
			select(LearnerActivity.lo_id)
			.where(
				LearnerActivity.learner_id == learner_id,
				LearnerActivity.lo_id.in_(lo_ids),
				LearnerActivity.completed_at.isnot(None),
				LearnerActivity.passed.isnot(False),  # passed or None (non-scored)
			)
		).scalars().all()
		completed_lo_ids = set(str(r) for r in rows)

		required_items = [i for i in items if i.is_required]
		completed_required = sum(
			1 for i in required_items if str(i.lo_id) in completed_lo_ids
		)

		pct = (
			(completed_required / len(required_items) * 100.0)
			if required_items else 100.0
		)

		# Next item: first required item not yet completed (prerequisites met)
		next_item = None
		completed_item_ids = {
			str(i.id) for i in items if str(i.lo_id) in completed_lo_ids
		}
		for item in required_items:
			if str(item.lo_id) in completed_lo_ids:
				continue
			prereqs = [str(p) for p in (item.prerequisite_item_ids or [])]
			if prereqs and not set(prereqs).issubset(completed_item_ids):
				continue
			lo = session.get(LearningObject, item.lo_id)
			next_item = {
				"item_id": str(item.id),
				"lo_id": str(item.lo_id),
				"lo_title": lo.title if lo else "",
				"sequence": item.sequence,
			}
			break

		return {
			"path_id": path_id,
			"total_items": len(items),
			"required_items": len(required_items),
			"completed_required": completed_required,
			"pct_complete": round(pct, 2),
			"next_item": next_item,
			"is_complete": next_item is None and completed_required >= len(required_items),
		}

	# ------------------------------------------------------------------
	# Credential Issuance
	# ------------------------------------------------------------------

	def issue_credential(
		self,
		session: Any,
		credential_id: str,
		recipient_id: str,
		evidence: dict,
		tenant_id: str = "",
	) -> Any:
		"""Issue a verifiable credential to a recipient.

		Generates a globally unique verification_url.
		Computes expires_at from credential.valid_duration_days (None = never).

		Returns the newly inserted EduIssuedCredential.
		"""
		from pgappforge.plugins.erp.platform.education_platform.models import (
			VerifiableCredential, EduIssuedCredential,
		)
		from pgappforge.plugins.erp.platform.education_platform.events import (
			CredentialIssuedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit

		credential = session.get(VerifiableCredential, credential_id)
		if credential is None:
			raise CredentialNotFoundError(f"VerifiableCredential {credential_id!r} not found")
		if not credential.is_active:
			raise EducationPlatformError(
				f"VerifiableCredential {credential_id!r} is inactive"
			)

		now = datetime.now(timezone.utc)
		expires_at = None
		if credential.valid_duration_days is not None:
			from datetime import timedelta
			expires_at = now + timedelta(days=credential.valid_duration_days)

		# Deterministic but unique verification token
		token = secrets.token_urlsafe(32)
		verification_url = f"/credentials/verify/{token}"

		issued = EduIssuedCredential(
			tenant_id=tenant_id,
			credential_id=credential_id,
			recipient_id=recipient_id,
			issued_at=now,
			expires_at=expires_at,
			evidence=evidence,
			verification_url=verification_url,
		)
		session.add(issued)
		session.flush()

		_emit(CredentialIssuedEvent(
			aggregate_id=issued.id,
			aggregate_type="EduIssuedCredential",
			tenant_id=tenant_id,
			issued_credential_id=issued.id,
			credential_id=credential_id,
			recipient_id=recipient_id,
			verification_url=verification_url,
			issued_at=now.isoformat(),
		), session)

		log.info(
			"EducationPlatformService: credential issued credential=%r recipient=%r",
			credential_id, recipient_id,
		)
		return issued

	# ------------------------------------------------------------------
	# Credential Verification
	# ------------------------------------------------------------------

	def verify_credential(
		self,
		session: Any,
		verification_url: str,
	) -> dict:
		"""Verify a credential by its verification_url.

		Returns:
		  {
		    "valid": bool,
		    "issued_to": str,       # recipient party id
		    "issued_by": str,       # issuer party id
		    "issued_at": str,       # ISO timestamp
		    "expires_at": str|None,
		    "expired": bool,
		    "revoked": bool,
		    "revocation_reason": str|None,
		    "credential_name": str,
		    "credential_type": str,
		  }
		"""
		from pgappforge.plugins.erp.platform.education_platform.models import (
			EduIssuedCredential, VerifiableCredential,
		)

		issued = session.execute(
			select(EduIssuedCredential).where(
				EduIssuedCredential.verification_url == verification_url
			)
		).scalar_one_or_none()

		if issued is None:
			return {
				"valid": False,
				"issued_to": None,
				"issued_by": None,
				"issued_at": None,
				"expires_at": None,
				"expired": False,
				"revoked": False,
				"revocation_reason": None,
				"credential_name": None,
				"credential_type": None,
			}

		credential = session.get(VerifiableCredential, issued.credential_id)
		now = datetime.now(timezone.utc)

		revoked = issued.revoked_at is not None
		expired = (
			issued.expires_at is not None
			and issued.expires_at.replace(tzinfo=timezone.utc) < now
		)
		valid = not revoked and not expired

		return {
			"valid": valid,
			"issued_to": str(issued.recipient_id),
			"issued_by": str(credential.issuer_id) if credential else None,
			"issued_at": issued.issued_at.isoformat() if issued.issued_at else None,
			"expires_at": issued.expires_at.isoformat() if issued.expires_at else None,
			"expired": expired,
			"revoked": revoked,
			"revocation_reason": issued.revocation_reason,
			"credential_name": credential.name if credential else None,
			"credential_type": credential.credential_type if credential else None,
		}

	# ------------------------------------------------------------------
	# Next Learning Recommendation
	# ------------------------------------------------------------------

	def recommend_next_learning(
		self,
		session: Any,
		learner_id: str,
		tenant_id: str = "",
		limit: int = 5,
	) -> list:
		"""Recommend learning objects based on competency gaps.

		Algorithm:
		1. Collect competencies from all completed LOs for this learner.
		2. Find published LOs whose competencies are NOT in the learner's set.
		3. Prefer lower difficulty for learners with fewer completions.
		4. Return up to `limit` LOs ordered by difficulty then estimated_duration.

		Returns a list of LearningObject instances.
		"""
		from pgappforge.plugins.erp.platform.education_platform.models import (
			LearningObject, LearnerActivity,
		)

		# Completed LO ids for this learner
		completed_lo_ids = set(
			str(r) for r in session.execute(
				select(LearnerActivity.lo_id).where(
					LearnerActivity.learner_id == learner_id,
					LearnerActivity.completed_at.isnot(None),
				).distinct()
			).scalars().all()
		)

		# Competencies already mastered (id strings)
		mastered_competency_ids: set[str] = set()
		if completed_lo_ids:
			mastered_rows = session.execute(
				select(LearningObject.competencies).where(
					LearningObject.id.in_(list(completed_lo_ids)),
				)
			).scalars().all()
			for comp_list in mastered_rows:
				for c in (comp_list or []):
					if isinstance(c, dict) and c.get("id"):
						mastered_competency_ids.add(str(c["id"]))

		# Candidate LOs: published, not yet started, tenant-scoped
		q = (
			select(LearningObject)
			.where(
				LearningObject.is_published.is_(True),
				LearningObject.id.notin_(list(completed_lo_ids)) if completed_lo_ids
				else sa.true(),
			)
			.order_by(
				sa.case(
					(LearningObject.difficulty == "BEGINNER", 1),
					(LearningObject.difficulty == "INTERMEDIATE", 2),
					(LearningObject.difficulty == "ADVANCED", 3),
					else_=4,
				),
				LearningObject.estimated_duration_minutes,
			)
			.limit(limit * 3)	# over-fetch then filter
		)
		if tenant_id:
			q = q.where(LearningObject.tenant_id == tenant_id)

		candidates = session.execute(q).scalars().all()

		# Filter to those with at least one un-mastered competency (gap)
		recommendations = []
		for lo in candidates:
			lo_comp_ids = {
				str(c["id"]) for c in (lo.competencies or [])
				if isinstance(c, dict) and c.get("id")
			}
			if lo_comp_ids and lo_comp_ids.issubset(mastered_competency_ids):
				continue	# all competencies already mastered
			recommendations.append(lo)
			if len(recommendations) >= limit:
				break

		log.info(
			"EducationPlatformService: recommend_next_learning learner=%r → %d items",
			learner_id, len(recommendations),
		)
		return recommendations


__all__ = [
	"EducationPlatformService",
	"EducationPlatformError",
	"LMSToolNotFoundError",
	"LearningObjectNotFoundError",
	"LearningPathNotFoundError",
	"CredentialNotFoundError",
	"CredentialExpiredError",
	"CredentialRevokedError",
]
