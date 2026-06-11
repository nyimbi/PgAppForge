"""
pgappforge/plugins/fintech/core_banking/kyc.py

KYC (Know Your Customer) / CDD (Customer Due Diligence) workflow.

Models
------
  KYCProfile   — one per customer; tracks overall tier and status.
  KYCDocument  — individual identity / address / source-of-funds docs.

Tier logic
----------
  TIER0: no verified documents (default at onboarding)
  TIER1: at least 1 verified photo ID (NATIONAL_ID | PASSPORT | DRIVING_LICENSE)
  TIER2: TIER1 + address proof (UTILITY_BILL | BANK_STATEMENT)
  TIER3: TIER2 + source-of-funds / business docs (BUSINESS_REG | PIN_CERT | KRA_PIN)

Daily transaction limits per tier (enforced via upgrade_account_limits()):
  TIER0:  50,000 KES/day
  TIER1: 500,000 KES/day
  TIER2: 2,000,000 KES/day
  TIER3: unlimited (None)

NOTE: Alembic migration required to create cb_kyc_profile and cb_kyc_document
tables before using this module.  Run::

    flask db migrate -m "add kyc tables"
    flask db upgrade
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, date, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# KYCProfile — one per customer
# ---------------------------------------------------------------------------

class KYCProfile(AuditMixin, Model):
	"""Consolidated KYC status for a customer.

	kyc_tier:       TIER0 (none) / TIER1 (basic) / TIER2 (full) / TIER3 (enhanced)
	overall_status: UNVERIFIED / PENDING / VERIFIED / REJECTED / EXPIRED

	risk_rating: 1 (low) → 5 (critical); used for Enhanced Due Diligence triggers.
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_kyc_profile"
	__table_args__ = (
		Index("ix_cb_kyc_profile_customer", "customer_id"),
		Index("ix_cb_kyc_profile_tenant", "tenant_id"),
		Index("ix_cb_kyc_profile_status", "overall_status"),
		UniqueConstraint("customer_id", "tenant_id", name="uq_cb_kyc_profile_customer_tenant"),
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
		index=True,
		comment="FK to erp_party.id (not enforced at DB level for cross-schema flexibility)",
	)
	account_id = Column(
		UUID(as_uuid=False),
		ForeignKey("cb_account.id"),
		nullable=True,
		index=True,
		comment="Primary account associated with this KYC profile (nullable)",
	)
	kyc_tier = Column(
		String(10),
		nullable=False,
		default="TIER0",
		comment="TIER0 (none) / TIER1 (basic) / TIER2 (full) / TIER3 (enhanced)",
	)
	overall_status = Column(
		String(15),
		nullable=False,
		default="UNVERIFIED",
		comment="UNVERIFIED / PENDING / VERIFIED / REJECTED / EXPIRED",
	)
	risk_rating = Column(
		Integer,
		nullable=False,
		default=1,
		comment="1=low, 2=medium-low, 3=medium, 4=high, 5=critical",
	)
	notes = Column(Text, nullable=True)
	verified_at = Column(DateTime(timezone=True), nullable=True)
	verified_by = Column(UUID(as_uuid=False), nullable=True, comment="Staff member who approved")

	# Timestamps
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
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	documents: list[KYCDocument] = relationship(
		"KYCDocument",
		back_populates="profile",
		lazy="select",
		cascade="all, delete-orphan",
	)

	def __repr__(self) -> str:
		return (
			f"<KYCProfile customer={self.customer_id!r} "
			f"tier={self.kyc_tier!r} status={self.overall_status!r}>"
		)


# ---------------------------------------------------------------------------
# KYCDocument — individual document submission
# ---------------------------------------------------------------------------

_PHOTO_ID_TYPES = frozenset({"NATIONAL_ID", "PASSPORT", "DRIVING_LICENSE"})
_ADDRESS_PROOF_TYPES = frozenset({"UTILITY_BILL", "BANK_STATEMENT"})
_SOF_TYPES = frozenset({"BUSINESS_REG", "PIN_CERT", "KRA_PIN"})

_ALL_DOC_TYPES = _PHOTO_ID_TYPES | _ADDRESS_PROOF_TYPES | _SOF_TYPES


class KYCDocument(AuditMixin, Model):
	"""A single identity or supporting document within a KYC profile.

	document_type values:
	  Photo ID:       NATIONAL_ID | PASSPORT | DRIVING_LICENSE
	  Address proof:  UTILITY_BILL | BANK_STATEMENT
	  Source-of-funds / business: BUSINESS_REG | PIN_CERT | KRA_PIN

	verification_status flow:
	  PENDING → VERIFIED (approved) | REJECTED (declined)
	  VERIFIED → EXPIRED (on expiry_date)

	verification_provider:
	  MANUAL | SMILE_IDENTITY | JUMIO | IPRS | ECITIZEN
	"""

	__allow_unmapped__ = True
	__tablename__ = "cb_kyc_document"
	__table_args__ = (
		Index("ix_cb_kyc_doc_profile", "profile_id"),
		Index("ix_cb_kyc_doc_type", "document_type"),
		Index("ix_cb_kyc_doc_status", "verification_status"),
		Index("ix_cb_kyc_doc_tenant", "tenant_id"),
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
		ForeignKey("cb_kyc_profile.id"),
		nullable=False,
		index=True,
	)
	document_type = Column(
		String(30),
		nullable=False,
		comment=(
			"NATIONAL_ID | PASSPORT | DRIVING_LICENSE | "
			"UTILITY_BILL | BANK_STATEMENT | "
			"BUSINESS_REG | PIN_CERT | KRA_PIN"
		),
	)
	document_number = Column(String(100), nullable=True)
	issuing_country = Column(String(2), nullable=False, default="KE")
	issue_date = Column(Date, nullable=True)
	expiry_date = Column(Date, nullable=True)
	verification_status = Column(
		String(15),
		nullable=False,
		default="PENDING",
		comment="PENDING | VERIFIED | REJECTED | EXPIRED",
	)
	verification_ref = Column(
		String(100),
		nullable=True,
		comment="External verification provider's reference / case ID",
	)
	verification_provider = Column(
		String(50),
		nullable=True,
		comment="SMILE_IDENTITY | JUMIO | MANUAL | IPRS | ECITIZEN",
	)
	rejection_reason = Column(Text, nullable=True)
	image_url = Column(String(500), nullable=True, comment="Object-storage URL for document scan")

	# Timestamps
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
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	profile: KYCProfile = relationship(
		"KYCProfile",
		back_populates="documents",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<KYCDocument type={self.document_type!r} "
			f"status={self.verification_status!r} "
			f"profile={self.profile_id!r}>"
		)


# ---------------------------------------------------------------------------
# KYCService
# ---------------------------------------------------------------------------

class KYCService:
	"""Customer KYC / CDD workflow.

	All methods accept an explicit SQLAlchemy *session*; the caller controls
	commit/rollback.  The service never commits.

	Usage::

		svc = KYCService()
		profile = svc.get_or_create_profile(customer_id, tenant_id, session)
		doc = svc.submit_document(
			customer_id, "NATIONAL_ID", "12345678", tenant_id, session,
			expiry_date=date(2030, 1, 1),
		)
		svc.verify_document(doc.id, "IPRS-REF-001", tenant_id, session, provider="IPRS")
		status = svc.get_kyc_status(customer_id, tenant_id, session)
	"""

	# ------------------------------------------------------------------
	# Profile management
	# ------------------------------------------------------------------

	def get_or_create_profile(
		self,
		customer_id: str,
		tenant_id: str,
		session: Any,
	) -> KYCProfile:
		"""Return the existing KYCProfile for this customer or create a new one."""
		profile = session.execute(
			sa.select(KYCProfile).where(
				KYCProfile.customer_id == customer_id,
				KYCProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if profile is not None:
			return profile

		profile = KYCProfile(
			tenant_id=tenant_id,
			customer_id=customer_id,
			kyc_tier="TIER0",
			overall_status="UNVERIFIED",
			risk_rating=1,
		)
		session.add(profile)
		session.flush()
		log.info("KYCService: created new profile for customer %s (tenant %s)", customer_id, tenant_id)
		return profile

	# ------------------------------------------------------------------
	# Document submission
	# ------------------------------------------------------------------

	def submit_document(
		self,
		customer_id: str,
		document_type: str,
		document_number: str | None,
		tenant_id: str,
		session: Any,
		*,
		expiry_date: date | None = None,
		issue_date: date | None = None,
		image_url: str | None = None,
		issuing_country: str = "KE",
	) -> KYCDocument:
		"""Create a new KYCDocument in PENDING status.

		Validates document_type against the known set.  Automatically creates
		a KYCProfile if one does not yet exist.
		"""
		if document_type not in _ALL_DOC_TYPES:
			raise ValueError(
				f"Unknown document_type {document_type!r}. "
				f"Valid: {sorted(_ALL_DOC_TYPES)}"
			)

		profile = self.get_or_create_profile(customer_id, tenant_id, session)

		# Mark profile PENDING if currently UNVERIFIED
		if profile.overall_status == "UNVERIFIED":
			profile.overall_status = "PENDING"

		doc = KYCDocument(
			tenant_id=tenant_id,
			profile_id=profile.id,
			document_type=document_type,
			document_number=document_number,
			issuing_country=issuing_country,
			issue_date=issue_date,
			expiry_date=expiry_date,
			image_url=image_url,
			verification_status="PENDING",
		)
		session.add(doc)
		session.flush()
		log.info(
			"KYCService.submit_document: doc %s (%s) submitted for customer %s",
			doc.id, document_type, customer_id,
		)
		return doc

	# ------------------------------------------------------------------
	# Document verification
	# ------------------------------------------------------------------

	def verify_document(
		self,
		document_id: str,
		verification_ref: str,
		tenant_id: str,
		session: Any,
		*,
		provider: str = "MANUAL",
		approved: bool = True,
		rejection_reason: str | None = None,
	) -> KYCDocument:
		"""Approve or reject a KYCDocument.

		Sets verification_status to VERIFIED or REJECTED, stamps
		verification_ref and verification_provider, then recalculates
		the parent profile's KYC tier.
		"""
		doc = session.execute(
			sa.select(KYCDocument).where(
				KYCDocument.id == document_id,
				KYCDocument.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if doc is None:
			raise ValueError(f"KYCDocument {document_id!r} not found for tenant {tenant_id!r}")

		doc.verification_ref = verification_ref
		doc.verification_provider = provider
		if approved:
			doc.verification_status = "VERIFIED"
			doc.rejection_reason = None
		else:
			doc.verification_status = "REJECTED"
			doc.rejection_reason = rejection_reason

		session.flush()

		# Recalculate the parent profile's tier
		new_tier = self._recalculate_kyc_tier(doc.profile_id, tenant_id, session)
		log.info(
			"KYCService.verify_document: doc %s → %s; profile tier now %s",
			document_id, doc.verification_status, new_tier,
		)
		return doc

	# ------------------------------------------------------------------
	# Tier recalculation (internal)
	# ------------------------------------------------------------------

	def _recalculate_kyc_tier(
		self,
		profile_id: str,
		tenant_id: str,
		session: Any,
	) -> str:
		"""Recompute and persist the KYC tier for a profile.

		Tier rules (cumulative):
		  TIER1 requires: ≥1 VERIFIED photo ID
		  TIER2 requires: TIER1 + ≥1 VERIFIED address proof
		  TIER3 requires: TIER2 + ≥1 VERIFIED source-of-funds / business doc

		Returns the new tier string.
		"""
		profile = session.execute(
			sa.select(KYCProfile).where(
				KYCProfile.id == profile_id,
				KYCProfile.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if profile is None:
			log.warning("_recalculate_kyc_tier: profile %s not found", profile_id)
			return "TIER0"

		verified_types: set[str] = set(
			row[0]
			for row in session.execute(
				sa.select(KYCDocument.document_type).where(
					KYCDocument.profile_id == profile_id,
					KYCDocument.tenant_id == tenant_id,
					KYCDocument.verification_status == "VERIFIED",
				)
			).all()
		)

		has_photo_id = bool(verified_types & _PHOTO_ID_TYPES)
		has_address = bool(verified_types & _ADDRESS_PROOF_TYPES)
		has_sof = bool(verified_types & _SOF_TYPES)

		if has_photo_id and has_address and has_sof:
			tier = "TIER3"
		elif has_photo_id and has_address:
			tier = "TIER2"
		elif has_photo_id:
			tier = "TIER1"
		else:
			tier = "TIER0"

		profile.kyc_tier = tier
		if tier >= "TIER1":
			profile.overall_status = "VERIFIED"
			if profile.verified_at is None:
				profile.verified_at = datetime.now(timezone.utc)
		else:
			# Check if any docs are PENDING — keep PENDING status
			pending_count = session.execute(
				sa.select(sa.func.count()).where(
					KYCDocument.profile_id == profile_id,
					KYCDocument.verification_status == "PENDING",
				)
			).scalar_one()
			profile.overall_status = "PENDING" if pending_count > 0 else "UNVERIFIED"

		session.flush()
		return tier

	# ------------------------------------------------------------------
	# Status query
	# ------------------------------------------------------------------

	def get_kyc_status(
		self,
		customer_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a structured KYC status dict for the given customer.

		Shape::

			{
			    "customer_id": str,
			    "kyc_tier": "TIER0"|"TIER1"|"TIER2"|"TIER3",
			    "overall_status": str,
			    "risk_rating": int,
			    "verified_at": str|None,
			    "documents": [
			        {"id": str, "type": str, "status": str, "ref": str|None}, ...
			    ],
			    "missing_for_next_tier": [str, ...],
			}
		"""
		profile = self.get_or_create_profile(customer_id, tenant_id, session)

		docs = session.execute(
			sa.select(KYCDocument).where(
				KYCDocument.profile_id == profile.id,
				KYCDocument.tenant_id == tenant_id,
			)
		).scalars().all()

		verified_types: set[str] = {
			d.document_type for d in docs if d.verification_status == "VERIFIED"
		}

		missing: list[str] = []
		tier = profile.kyc_tier
		if tier == "TIER0":
			missing = sorted(_PHOTO_ID_TYPES - verified_types) or sorted(_PHOTO_ID_TYPES)
		elif tier == "TIER1":
			missing = sorted(_ADDRESS_PROOF_TYPES - verified_types) or sorted(_ADDRESS_PROOF_TYPES)
		elif tier == "TIER2":
			missing = sorted(_SOF_TYPES - verified_types) or sorted(_SOF_TYPES)
		# TIER3 = fully upgraded; no missing docs

		return {
			"customer_id": customer_id,
			"kyc_tier": profile.kyc_tier,
			"overall_status": profile.overall_status,
			"risk_rating": profile.risk_rating,
			"verified_at": profile.verified_at.isoformat() if profile.verified_at else None,
			"documents": [
				{
					"id": d.id,
					"document_type": d.document_type,
					"document_number": d.document_number,
					"verification_status": d.verification_status,
					"verification_ref": d.verification_ref,
					"verification_provider": d.verification_provider,
					"expiry_date": d.expiry_date.isoformat() if d.expiry_date else None,
				}
				for d in docs
			],
			"missing_for_next_tier": missing,
		}

	# ------------------------------------------------------------------
	# Account limit upgrade
	# ------------------------------------------------------------------

	def upgrade_account_limits(
		self,
		customer_id: str,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Apply KYC-tier-based daily withdrawal limits to the customer's accounts.

		Limits applied to BankProduct.max_withdrawal_per_day_cents for the
		customer's accounts (ACTIVE / DORMANT):
		  TIER0:  5,000,000 (KES 50,000)
		  TIER1: 50,000,000 (KES 500,000)
		  TIER2: 200,000,000 (KES 2,000,000)
		  TIER3: None (unlimited)

		Returns a summary dict with accounts_updated count and new limit.
		"""
		try:
			from pgappforge.plugins.fintech.core_banking.models import Account
		except ImportError:
			return {"error": "core_banking.models not available"}

		profile = self.get_or_create_profile(customer_id, tenant_id, session)

		_tier_limits: dict[str, int | None] = {
			"TIER0": 5_000_000,       # KES 50,000 in cents
			"TIER1": 50_000_000,      # KES 500,000
			"TIER2": 200_000_000,     # KES 2,000,000
			"TIER3": None,            # unlimited
		}
		new_limit = _tier_limits.get(profile.kyc_tier, 5_000_000)

		accounts = session.execute(
			sa.select(Account).where(
				Account.customer_id == customer_id,
				Account.tenant_id == tenant_id,
				Account.status.in_(["ACTIVE", "DORMANT"]),
			)
		).scalars().all()

		updated = 0
		for account in accounts:
			product = account.product
			if product is not None:
				product.max_withdrawal_per_day_cents = new_limit
				updated += 1

		session.flush()
		log.info(
			"KYCService.upgrade_account_limits: customer %s tier %s → limit %s cents (%d accounts)",
			customer_id, profile.kyc_tier, new_limit, updated,
		)
		return {
			"customer_id": customer_id,
			"kyc_tier": profile.kyc_tier,
			"new_daily_limit_cents": new_limit,
			"accounts_updated": updated,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = ["KYCService", "KYCProfile", "KYCDocument"]
