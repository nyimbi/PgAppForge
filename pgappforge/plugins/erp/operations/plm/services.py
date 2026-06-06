"""
pgappforge/plugins/erp/operations/plm/services.py

PlmService — stateless business logic for the Product Lifecycle Management plugin.

All methods receive an explicit SQLAlchemy 2.x session; no Flask context assumed.
Transaction boundaries owned by the caller.

Public API:
  create_product(name, product_code, tenant_id, session,
                 *, category, entity_id)                                       -> PlmProduct
  create_version(product_id, version_number, session,
                 *, version_type, changes)                                     -> PlmProductVersion
  approve_version(version_id, approver_id, session)                           -> PlmProductVersion
  release_version(version_id, session)                                        -> PlmProductVersion
  create_bom(product_id, version_id, items, session)                          -> BillOfMaterials
  release_bom(bom_id, released_by, session)                                   -> BillOfMaterials
  submit_eco(title, description, product_id, eco_type, submitted_by,
             tenant_id, session)                                               -> EngineeringChangeOrder
  approve_eco(eco_id, approver_id, session)                                   -> EngineeringChangeOrder
  pass_stage_gate(product_id, gate_name, approver_id, session)                -> PlmProduct
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PlmServiceError(Exception):
	"""Base domain error for PLM operations."""


class PlmNotFoundError(PlmServiceError):
	"""Raised when a PLM entity cannot be found."""


class PlmStateError(PlmServiceError):
	"""Raised when an operation is invalid for the current entity status."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(timezone.utc)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# PlmService
# ---------------------------------------------------------------------------

class PlmService:
	"""Stateless PLM business logic.

	Instantiate once per request/task; pass an explicit SQLAlchemy 2.x session
	to every method.  Caller owns commit/rollback.
	"""

	# ------------------------------------------------------------------
	# 1. create_product
	# ------------------------------------------------------------------

	@staticmethod
	def create_product(
		name: str,
		product_code: str,
		tenant_id: str,
		session: Any,
		*,
		category: str | None = None,
		description: str | None = None,
		entity_id: str | None = None,
		created_by: str | None = None,
	) -> Any:
		"""Register a new PLM product.

		Returns:
			PlmProduct — flushed but not committed.

		Raises:
			PlmServiceError if product_code already exists for tenant.
		"""
		from pgappforge.plugins.erp.operations.plm.models import PlmProduct

		assert name, "name is required"
		assert product_code, "product_code is required"
		assert tenant_id, "tenant_id is required"

		existing = session.execute(
			sa.select(PlmProduct).where(
				PlmProduct.tenant_id == tenant_id,
				PlmProduct.product_code == product_code,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise PlmServiceError(
				f"product_code {product_code!r} already exists for tenant {tenant_id}"
			)

		product = PlmProduct(
			tenant_id=tenant_id,
			name=name,
			product_code=product_code,
			description=description,
			category=category,
			entity_id=entity_id,
			created_by=created_by,
			lifecycle_stage="CONCEPT",
		)
		session.add(product)
		session.flush()

		log.info(
			"PlmService.create_product: %s %r tenant=%s",
			product.id, product_code, tenant_id,
		)
		return product

	# ------------------------------------------------------------------
	# 2. create_version
	# ------------------------------------------------------------------

	@staticmethod
	def create_version(
		product_id: str,
		version_number: str,
		session: Any,
		*,
		version_type: str = "MINOR",
		changes: str | None = None,
	) -> Any:
		"""Create a new draft product version.

		Emits ProductVersionCreatedEvent.

		Returns:
			PlmProductVersion — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import PlmProduct, PlmProductVersion
		from pgappforge.plugins.erp.operations.plm.events import ProductVersionCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert version_number, "version_number is required"
		valid_types = {"MAJOR", "MINOR", "PATCH"}
		if version_type not in valid_types:
			raise PlmServiceError(f"version_type must be one of {valid_types}, got {version_type!r}")

		product = session.get(PlmProduct, product_id)
		if product is None:
			raise PlmNotFoundError(f"PlmProduct {product_id} not found")

		# Check uniqueness
		dupe = session.execute(
			sa.select(PlmProductVersion).where(
				PlmProductVersion.product_id == product_id,
				PlmProductVersion.version_number == version_number,
			)
		).scalar_one_or_none()
		if dupe is not None:
			raise PlmServiceError(
				f"Version {version_number!r} already exists for product {product_id}"
			)

		version = PlmProductVersion(
			tenant_id=product.tenant_id,
			product_id=product_id,
			version_number=version_number,
			version_type=version_type,
			changes=changes,
			status="DRAFT",
		)
		session.add(version)
		session.flush()

		emit_event(
			ProductVersionCreatedEvent(
				aggregate_id=version.id,
				aggregate_type="PlmProductVersion",
				version_id=version.id,
				product_id=product_id,
				version_number=version_number,
				tenant_id=product.tenant_id,
			),
			session,
		)
		log.info(
			"PlmService.create_version: %s v%s product=%s type=%s",
			version.id, version_number, product_id, version_type,
		)
		return version

	# ------------------------------------------------------------------
	# 3. approve_version
	# ------------------------------------------------------------------

	@staticmethod
	def approve_version(
		version_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Approve a product version: REVIEW → APPROVED.

		Also updates product.current_version to this version_number.

		Returns:
			PlmProductVersion — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import PlmProduct, PlmProductVersion

		assert approver_id, "approver_id is required"

		version = session.get(PlmProductVersion, version_id)
		if version is None:
			raise PlmNotFoundError(f"PlmProductVersion {version_id} not found")
		if version.status != "REVIEW":
			raise PlmStateError(
				f"Cannot approve version in status {version.status!r}; expected REVIEW"
			)

		now = _now()
		version.status = "APPROVED"
		version.approved_by = approver_id
		version.updated_at = now

		# Update product.current_version
		product = session.get(PlmProduct, version.product_id)
		if product is not None:
			product.current_version = version.version_number
			product.updated_at = now

		session.flush()
		log.info(
			"PlmService.approve_version: %s v%s → APPROVED by %s",
			version_id, version.version_number, approver_id,
		)
		return version

	# ------------------------------------------------------------------
	# 4. release_version
	# ------------------------------------------------------------------

	@staticmethod
	def release_version(
		version_id: str,
		session: Any,
	) -> Any:
		"""Release an approved product version: APPROVED → RELEASED.

		Returns:
			PlmProductVersion — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import PlmProductVersion

		version = session.get(PlmProductVersion, version_id)
		if version is None:
			raise PlmNotFoundError(f"PlmProductVersion {version_id} not found")
		if version.status != "APPROVED":
			raise PlmStateError(
				f"Cannot release version in status {version.status!r}; expected APPROVED"
			)

		now = _now()
		version.status = "RELEASED"
		version.released_at = now
		version.updated_at = now
		session.flush()

		log.info(
			"PlmService.release_version: %s v%s → RELEASED",
			version_id, version.version_number,
		)
		return version

	# ------------------------------------------------------------------
	# 5. create_bom
	# ------------------------------------------------------------------

	@staticmethod
	def create_bom(
		product_id: str,
		version_id: str,
		items: list[dict[str, Any]],
		session: Any,
		*,
		effective_from: Any | None = None,
	) -> Any:
		"""Create a draft Bill of Materials for a product version.

		items: [{component_id, component_name, quantity, unit, notes}]

		Returns:
			BillOfMaterials — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import (
			PlmProduct,
			PlmProductVersion,
			BillOfMaterials,
		)

		assert isinstance(items, list), "items must be a list"

		product = session.get(PlmProduct, product_id)
		if product is None:
			raise PlmNotFoundError(f"PlmProduct {product_id} not found")

		version = session.get(PlmProductVersion, version_id)
		if version is None:
			raise PlmNotFoundError(f"PlmProductVersion {version_id} not found")
		if version.product_id != product_id:
			raise PlmServiceError(
				f"Version {version_id} does not belong to product {product_id}"
			)

		# Determine next revision number for this product+version
		max_rev = session.execute(
			sa.select(sa.func.max(BillOfMaterials.version_number)).where(
				BillOfMaterials.product_id == product_id,
				BillOfMaterials.version_id == version_id,
			)
		).scalar_one_or_none()
		next_rev = (max_rev or 0) + 1

		bom = BillOfMaterials(
			tenant_id=product.tenant_id,
			product_id=product_id,
			version_id=version_id,
			version_number=next_rev,
			items=items,
			effective_from=effective_from,
			status="DRAFT",
		)
		session.add(bom)
		session.flush()

		log.info(
			"PlmService.create_bom: %s product=%s version=%s rev=%d items=%d",
			bom.id, product_id, version_id, next_rev, len(items),
		)
		return bom

	# ------------------------------------------------------------------
	# 6. release_bom
	# ------------------------------------------------------------------

	@staticmethod
	def release_bom(
		bom_id: str,
		released_by: str,
		session: Any,
	) -> Any:
		"""Release a BOM: DRAFT | REVIEW → RELEASED.

		Emits BomReleasedEvent.

		Returns:
			BillOfMaterials — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import BillOfMaterials, PlmProductVersion
		from pgappforge.plugins.erp.operations.plm.events import BomReleasedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert released_by, "released_by is required"

		bom = session.get(BillOfMaterials, bom_id)
		if bom is None:
			raise PlmNotFoundError(f"BillOfMaterials {bom_id} not found")
		if bom.status not in ("DRAFT", "REVIEW"):
			raise PlmStateError(
				f"Cannot release BOM in status {bom.status!r}; expected DRAFT or REVIEW"
			)

		now = _now()
		bom.status = "RELEASED"
		bom.released_by = released_by
		bom.updated_at = now
		session.flush()

		# Resolve version_number string for event
		version_number_str = ""
		version = session.get(PlmProductVersion, bom.version_id)
		if version is not None:
			version_number_str = version.version_number

		emit_event(
			BomReleasedEvent(
				aggregate_id=bom.id,
				aggregate_type="BillOfMaterials",
				bom_id=bom.id,
				product_id=str(bom.product_id),
				version_number=version_number_str,
				tenant_id=bom.tenant_id,
			),
			session,
		)
		log.info(
			"PlmService.release_bom: %s product=%s released_by=%s",
			bom_id, bom.product_id, released_by,
		)
		return bom

	# ------------------------------------------------------------------
	# 7. submit_eco
	# ------------------------------------------------------------------

	@staticmethod
	def submit_eco(
		title: str,
		description: str,
		product_id: str,
		eco_type: str,
		submitted_by: str,
		tenant_id: str,
		session: Any,
		*,
		priority: str = "MEDIUM",
		current_version_id: str | None = None,
	) -> Any:
		"""Create and submit an Engineering Change Order.

		Creates ECO in SUBMITTED status and emits EcoSubmittedEvent.

		valid eco_type: DEFECT_FIX | DESIGN_CHANGE | COST_REDUCTION | SAFETY | REGULATORY
		valid priority: LOW | MEDIUM | HIGH | CRITICAL

		Returns:
			EngineeringChangeOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import PlmProduct, EngineeringChangeOrder
		from pgappforge.plugins.erp.operations.plm.events import EcoSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert title, "title is required"
		assert description, "description is required"
		assert submitted_by, "submitted_by is required"

		valid_types = {"DEFECT_FIX", "DESIGN_CHANGE", "COST_REDUCTION", "SAFETY", "REGULATORY"}
		if eco_type not in valid_types:
			raise PlmServiceError(f"eco_type must be one of {valid_types}, got {eco_type!r}")

		valid_priorities = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
		if priority not in valid_priorities:
			raise PlmServiceError(f"priority must be one of {valid_priorities}, got {priority!r}")

		product = session.get(PlmProduct, product_id)
		if product is None:
			raise PlmNotFoundError(f"PlmProduct {product_id} not found")

		eco = EngineeringChangeOrder(
			tenant_id=tenant_id,
			title=title,
			description=description,
			product_id=product_id,
			current_version_id=current_version_id,
			eco_type=eco_type,
			priority=priority,
			status="SUBMITTED",
			submitted_by=submitted_by,
		)
		session.add(eco)
		session.flush()

		emit_event(
			EcoSubmittedEvent(
				aggregate_id=eco.id,
				aggregate_type="EngineeringChangeOrder",
				eco_id=eco.id,
				title=title,
				submitted_by=submitted_by,
				tenant_id=tenant_id,
			),
			session,
		)
		log.info(
			"PlmService.submit_eco: %s %r product=%s type=%s",
			eco.id, title, product_id, eco_type,
		)
		return eco

	# ------------------------------------------------------------------
	# 8. approve_eco
	# ------------------------------------------------------------------

	@staticmethod
	def approve_eco(
		eco_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Approve an ECO: REVIEW → APPROVED.

		Emits EcoApprovedEvent.

		Returns:
			EngineeringChangeOrder — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import EngineeringChangeOrder
		from pgappforge.plugins.erp.operations.plm.events import EcoApprovedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert approver_id, "approver_id is required"

		eco = session.get(EngineeringChangeOrder, eco_id)
		if eco is None:
			raise PlmNotFoundError(f"EngineeringChangeOrder {eco_id} not found")

		# Accept both SUBMITTED (direct approval) and REVIEW status
		if eco.status not in ("REVIEW", "SUBMITTED"):
			raise PlmStateError(
				f"Cannot approve ECO in status {eco.status!r}; expected REVIEW or SUBMITTED"
			)

		now = _now()
		eco.status = "APPROVED"
		eco.approved_by = approver_id
		eco.updated_at = now
		session.flush()

		emit_event(
			EcoApprovedEvent(
				aggregate_id=eco.id,
				aggregate_type="EngineeringChangeOrder",
				eco_id=eco.id,
				approved_by=approver_id,
				tenant_id=eco.tenant_id,
			),
			session,
		)
		log.info("PlmService.approve_eco: %s → APPROVED by %s", eco_id, approver_id)
		return eco

	# ------------------------------------------------------------------
	# 9. pass_stage_gate
	# ------------------------------------------------------------------

	@staticmethod
	def pass_stage_gate(
		product_id: str,
		gate_name: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Record that a product has passed a named stage gate review.

		Appends an entry to product.metadata_["stage_gates"] and emits
		StageGatePassedEvent.

		Returns:
			PlmProduct — flushed but not committed.
		"""
		from pgappforge.plugins.erp.operations.plm.models import PlmProduct
		from pgappforge.plugins.erp.operations.plm.events import StageGatePassedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		assert gate_name, "gate_name is required"
		assert approver_id, "approver_id is required"

		product = session.get(PlmProduct, product_id)
		if product is None:
			raise PlmNotFoundError(f"PlmProduct {product_id} not found")

		now = _now()
		metadata = dict(product.metadata_ or {})
		gates = list(metadata.get("stage_gates", []))
		gates.append({
			"gate": gate_name,
			"passed_at": now.isoformat(),
			"approved_by": approver_id,
		})
		metadata["stage_gates"] = gates
		product.metadata_ = metadata
		product.updated_at = now
		session.flush()

		emit_event(
			StageGatePassedEvent(
				aggregate_id=product.id,
				aggregate_type="PlmProduct",
				product_id=product_id,
				gate_name=gate_name,
				approved_by=approver_id,
				tenant_id=product.tenant_id,
			),
			session,
		)
		log.info(
			"PlmService.pass_stage_gate: product=%s gate=%r approved_by=%s",
			product_id, gate_name, approver_id,
		)
		return product


__all__ = [
	"PlmService",
	"PlmServiceError",
	"PlmNotFoundError",
	"PlmStateError",
]
