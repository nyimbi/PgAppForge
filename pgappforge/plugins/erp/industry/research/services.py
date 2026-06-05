"""
pgappforge/plugins/erp/industry/research/services.py

ResearchService — stateless business logic for the Research Data Management plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

DataCite integration:
  - mint_doi uses DataCite REST API (https://api.datacite.org/dois)
  - export_datacite_xml generates DataCite Metadata Schema 4.4 XML
  - DATACITE_API_URL, DATACITE_USERNAME, DATACITE_PASSWORD from Flask config
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any
from xml.etree.ElementTree import Element, SubElement, indent, tostring

import sqlalchemy as sa
from sqlalchemy import func, select

from pgappforge.plugins.erp.foundation.commons import emit_event

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ResearchError(Exception):
	"""Base error for Research Data Management domain violations."""


class ProjectNotFoundError(ResearchError):
	"""No ResearchProject with the given id."""


class DatasetNotFoundError(ResearchError):
	"""No Dataset with the given id."""


class DOIMintError(ResearchError):
	"""DOI minting failed (DataCite API error or configuration missing)."""


class PublicationNotFoundError(ResearchError):
	"""No Publication with the given id."""


class ImmutableProvenanceError(ResearchError):
	"""Attempted to modify an immutable DataProvenance record."""


# ---------------------------------------------------------------------------
# ResearchService
# ---------------------------------------------------------------------------

class ResearchService:
	"""Stateless service for Research Data Management operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# DOI minting via DataCite REST API
	# ------------------------------------------------------------------

	def mint_doi(
		self,
		dataset_id: str,
		session: Any,
		*,
		datacite_url: str = "https://api.datacite.org",
		datacite_username: str = "",
		datacite_password: str = "",
		doi_prefix: str = "10.5281",
		dry_run: bool = False,
	) -> str:
		"""Register a DOI for a dataset via the DataCite REST API.

		Builds a DataCite 4.4 metadata payload from the Dataset record,
		POSTs to the DataCite API, and updates dataset.doi on success.

		dry_run=True generates and returns a DOI stub without calling the API
		(useful for testing and staging environments).

		Raises:
		  DatasetNotFoundError if dataset_id not found.
		  DOIMintError if the dataset already has a DOI, or API call fails.
		"""
		from pgappforge.plugins.erp.industry.research.models import Dataset
		from pgappforge.plugins.erp.industry.research.events import DatasetDOIMintedEvent

		dataset = session.get(Dataset, dataset_id)
		if dataset is None:
			raise DatasetNotFoundError(f"Dataset {dataset_id!r} not found")

		if dataset.doi:
			raise DOIMintError(f"Dataset {dataset_id!r} already has DOI: {dataset.doi!r}")

		# Build DataCite payload
		creators = []
		for cid in (dataset.creator_ids or []):
			creators.append({"name": str(cid), "nameType": "Personal"})

		if not creators:
			creators.append({"name": "Unknown Creator", "nameType": "Organizational"})

		_type_map = {
			"DATASET": "Dataset",
			"SOFTWARE": "Software",
			"IMAGE": "Image",
			"COLLECTION": "Collection",
			"TEXT": "Text",
			"WORKFLOW": "Workflow",
		}
		resource_type_general = _type_map.get(dataset.resource_type, "Dataset")

		payload = {
			"data": {
				"type": "dois",
				"attributes": {
					"prefix": doi_prefix,
					"titles": [{"title": dataset.title}],
					"creators": creators,
					"publisher": "PgAppForge Research Repository",
					"publicationYear": dataset.publication_year or datetime.now(timezone.utc).year,
					"types": {
						"resourceTypeGeneral": resource_type_general,
						"resourceType": dataset.resource_type,
					},
					"language": dataset.language or "en",
					"version": dataset.version or "1",
					"subjects": [{"subject": s} for s in (dataset.subjects or [])],
					"rightsList": (
						[{"rights": dataset.license, "rightsIdentifierScheme": "SPDX"}]
						if dataset.license else []
					),
					"descriptions": (
						[{"description": dataset.description, "descriptionType": "Abstract"}]
						if dataset.description else []
					),
					"url": dataset.storage_url or "",
					"event": "publish" if dataset.is_published else "draft",
					# extra_metadata fields forwarded as-is
					**(dataset.extra_metadata or {}),
				},
			}
		}

		if dry_run:
			# Generate deterministic stub DOI for testing
			stub = f"{doi_prefix}/rdm.{hashlib.md5(dataset_id.encode()).hexdigest()[:10]}"
			dataset.doi = stub
			session.flush()
			log.info("mint_doi: dry_run DOI=%r for dataset=%r", stub, dataset_id)
			emit_event(
				"research.dataset.doi_minted",
				"Dataset",
				dataset_id,
				{"doi": stub, "dry_run": True},
				session,
				tenant_id=str(dataset.tenant_id),
			)
			return stub

		# Live DataCite API call
		try:
			import urllib.request
			import urllib.error
			import base64

			url = f"{datacite_url.rstrip('/')}/dois"
			body = json.dumps(payload).encode()
			req = urllib.request.Request(
				url,
				data=body,
				method="POST",
				headers={
					"Content-Type": "application/vnd.api+json",
					"Accept": "application/vnd.api+json",
					"Authorization": "Basic " + base64.b64encode(
						f"{datacite_username}:{datacite_password}".encode()
					).decode(),
				},
			)
			with urllib.request.urlopen(req, timeout=30) as resp:
				response_data = json.loads(resp.read().decode())
			doi = response_data["data"]["id"]
		except Exception as exc:
			raise DOIMintError(f"DataCite API error for dataset {dataset_id!r}: {exc}") from exc

		dataset.doi = doi
		session.flush()

		from pgappforge.plugins.erp.industry.research.events import DatasetDOIMintedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
		_emit_typed(
			DatasetDOIMintedEvent(
				aggregate_id=dataset_id,
				aggregate_type="Dataset",
				tenant_id=str(dataset.tenant_id),
				dataset_id=dataset_id,
				doi=doi,
				project_id=str(dataset.project_id),
				title=dataset.title,
			),
			session,
		)
		log.info("mint_doi: DOI=%r minted for dataset=%r", doi, dataset_id)
		return doi

	# ------------------------------------------------------------------
	# Data Management Plan generation
	# ------------------------------------------------------------------

	def generate_data_management_plan(
		self,
		project_id: str,
		session: Any,
	) -> str:
		"""Generate a structured Data Management Plan (DMP) for a project.

		Returns a Markdown-formatted DMP document following the Science Europe
		Practical Guide to the International Alignment of RDM (2021).

		Raises:
		  ProjectNotFoundError if project_id not found.
		"""
		from pgappforge.plugins.erp.industry.research.models import (
			ResearchProject, Dataset,
		)

		project = session.get(ResearchProject, project_id)
		if project is None:
			raise ProjectNotFoundError(f"ResearchProject {project_id!r} not found")

		dataset_count = session.execute(
			sa.select(func.count(Dataset.id)).where(Dataset.project_id == project_id)
		).scalar_one() or 0

		datasets = session.execute(
			sa.select(Dataset).where(Dataset.project_id == project_id).limit(20)
		).scalars().all()

		resource_types = sorted({d.resource_type for d in datasets}) if datasets else ["DATASET"]
		access_modes = sorted({d.access_rights for d in datasets}) if datasets else ["OPEN"]
		licenses_used = sorted({d.license for d in datasets if d.license}) if datasets else []

		dmp = f"""# Data Management Plan

**Project**: {project.title}
**Code**: {project.project_code}
**Status**: {project.status}
**Generated**: {date.today().isoformat()}
**DMP Version**: 1.0

---

## 1. Data Description

This project manages {dataset_count} dataset(s) of the following types:
{', '.join(resource_types)}.

**Funding source**: {project.funding_source or 'Not specified'}
**Grant reference**: {project.grant_reference or 'Not specified'}
**Ethical approval**: {project.ethical_approval_number or 'Not required / pending'}

## 2. Documentation and Metadata

All datasets are described using DataCite Metadata Schema 4.4 (DOI-compatible).
Metadata fields: title, creators, resource type, subjects, keywords, language,
version, license, access rights, file format, and file size.

Provenance is tracked per-activity (COLLECTION, PROCESSING, TRANSFORMATION,
ANALYSIS) with inputs, outputs, parameters, and software used recorded for
full reproducibility.

## 3. Storage and Backup

Datasets are stored at the URLs recorded in `storage_url`.
File formats in use: {', '.join({fmt for d in datasets for fmt in (d.file_format or [])}) or 'TBD'}.
Backup policy: 3-2-1 (3 copies, 2 media types, 1 off-site).

## 4. Legal and Ethical Requirements

- Ethical approval number: {project.ethical_approval_number or 'N/A'}
- Access control modes applied: {', '.join(access_modes)}
- Licenses in use: {', '.join(licenses_used) or 'TBD — assign before publication'}
- Personal data: any datasets containing personal data must use
  RESTRICTED or CLOSED access and comply with applicable data protection law.

## 5. Data Sharing and Long-Term Preservation

Datasets with OPEN access will be published with registered DOIs via DataCite.
Embargoed datasets will be made available upon expiry of the embargo period.
Restricted datasets will be shared under a Data Access Agreement.

Target repositories: institutional repository / domain-specific archive.
Preservation horizon: 10 years post-project completion.

## 6. Responsibilities and Resources

| Role | Responsibility |
|------|---------------|
| Principal Investigator | DMP compliance, data quality oversight |
| Data Manager | Dataset registration, DOI minting, provenance logging |
| IT / Repository | Storage, backup, access control |

## 7. Related Documents

- Project data management plan URL: {project.data_management_plan_url or 'Not yet assigned'}
- Science Europe Practical Guide to RDM: https://scienceeurope.org/rdm
- DataCite Metadata Schema 4.4: https://schema.datacite.org/

---
*Generated automatically by PgAppForge Research Data Management plugin.*
"""
		return dmp.strip()

	# ------------------------------------------------------------------
	# Provenance tracking
	# ------------------------------------------------------------------

	def track_provenance(
		self,
		dataset_id: str,
		activity_type: str,
		details: dict,
		session: Any,
		*,
		performed_by_id: str | None = None,
		started_at: datetime | None = None,
		ended_at: datetime | None = None,
	) -> Any:
		"""Record an immutable provenance activity for a dataset.

		details dict supports:
		  inputs: [{dataset_id, description}]
		  outputs: [{dataset_id, description}]
		  parameters: {key: value}
		  software_used: [{name, version, url}]
		  description: str

		Raises:
		  DatasetNotFoundError if dataset_id not found.
		  ResearchError if activity_type is invalid.
		"""
		from pgappforge.plugins.erp.industry.research.models import Dataset, DataProvenance
		from pgappforge.plugins.erp.industry.research.events import ProvenanceRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		valid_types = {"COLLECTION", "PROCESSING", "TRANSFORMATION", "ANALYSIS"}
		if activity_type not in valid_types:
			raise ResearchError(
				f"activity_type must be one of {valid_types}, got {activity_type!r}"
			)

		dataset = session.get(Dataset, dataset_id)
		if dataset is None:
			raise DatasetNotFoundError(f"Dataset {dataset_id!r} not found")

		now = datetime.now(timezone.utc)
		prov = DataProvenance(
			tenant_id=dataset.tenant_id,
			dataset_id=dataset_id,
			activity_type=activity_type,
			performed_by_id=performed_by_id,
			started_at=started_at or now,
			ended_at=ended_at,
			inputs=details.get("inputs", []),
			outputs=details.get("outputs", []),
			parameters=details.get("parameters", {}),
			software_used=details.get("software_used", []),
			description=details.get("description"),
		)
		session.add(prov)
		session.flush()

		_emit_typed(
			ProvenanceRecordedEvent(
				aggregate_id=prov.id,
				aggregate_type="DataProvenance",
				tenant_id=str(dataset.tenant_id),
				provenance_id=prov.id,
				dataset_id=dataset_id,
				activity_type=activity_type,
				performed_by_id=performed_by_id or "",
				started_at=(started_at or now).isoformat(),
			),
			session,
		)
		log.info(
			"track_provenance: dataset=%r activity=%r prov_id=%r",
			dataset_id, activity_type, prov.id,
		)
		return prov

	# ------------------------------------------------------------------
	# Impact metrics
	# ------------------------------------------------------------------

	def calculate_impact_metrics(
		self,
		project_id: str,
		session: Any,
	) -> dict:
		"""Calculate research impact metrics for a project.

		Returns:
		  - total_citations: sum across all publications
		  - total_downloads: count of download events (stub — requires dc_download integration)
		  - h_index: Hirsch index computed from citation_count per publication
		  - open_access_ratio: fraction of publications that are open access
		  - dataset_count: total datasets
		  - published_dataset_count: datasets with is_published=True
		  - top_publications: top 5 by citation_count

		Raises:
		  ProjectNotFoundError if project_id not found.
		"""
		from pgappforge.plugins.erp.industry.research.models import (
			ResearchProject, Dataset, Publication,
		)

		project = session.get(ResearchProject, project_id)
		if project is None:
			raise ProjectNotFoundError(f"ResearchProject {project_id!r} not found")

		# Publications for this project
		pubs = session.execute(
			sa.select(Publication).where(Publication.project_id == project_id)
		).scalars().all()

		# Dataset counts
		dataset_count = session.execute(
			sa.select(func.count(Dataset.id)).where(Dataset.project_id == project_id)
		).scalar_one() or 0

		published_dataset_count = session.execute(
			sa.select(func.count(Dataset.id)).where(
				Dataset.project_id == project_id,
				Dataset.is_published.is_(True),
			)
		).scalar_one() or 0

		total_citations = sum(p.citation_count or 0 for p in pubs)
		oa_count = sum(1 for p in pubs if p.is_open_access)

		# h-index: largest h such that h publications have >= h citations
		citation_counts = sorted(
			[p.citation_count or 0 for p in pubs], reverse=True
		)
		h_index = 0
		for i, c in enumerate(citation_counts, start=1):
			if c >= i:
				h_index = i
			else:
				break

		top_pubs = sorted(pubs, key=lambda p: p.citation_count or 0, reverse=True)[:5]

		return {
			"project_id": project_id,
			"project_code": project.project_code,
			"title": project.title,
			"metrics": {
				"total_citations": total_citations,
				"total_downloads": None,  # requires dc_download integration
				"h_index": h_index,
				"publication_count": len(pubs),
				"open_access_ratio": round(oa_count / len(pubs), 4) if pubs else 0.0,
				"dataset_count": dataset_count,
				"published_dataset_count": published_dataset_count,
			},
			"top_publications": [
				{
					"id": p.id,
					"title": p.title,
					"doi": p.doi,
					"citation_count": p.citation_count,
					"is_open_access": p.is_open_access,
					"publication_date": p.publication_date.isoformat() if p.publication_date else None,
				}
				for p in top_pubs
			],
		}

	# ------------------------------------------------------------------
	# Data quality checks
	# ------------------------------------------------------------------

	def check_data_quality(
		self,
		dataset_id: str,
		session: Any,
	) -> dict:
		"""Run metadata quality checks against DataCite completeness rules.

		Checks:
		  - completeness: mandatory fields populated (title, creators, resource_type)
		  - recommended: publication_year, license, subjects, language, version
		  - consistency: doi format, language code format, access_rights valid value
		  - format_checks: file_format non-empty if storage_url set

		Returns a dict with overall score (0-100), per-check results, and
		a list of issues with field names and descriptions.
		"""
		from pgappforge.plugins.erp.industry.research.models import Dataset

		dataset = session.get(Dataset, dataset_id)
		if dataset is None:
			raise DatasetNotFoundError(f"Dataset {dataset_id!r} not found")

		issues: list[dict] = []
		checks: dict[str, bool] = {}

		# Completeness — mandatory DataCite fields
		checks["has_title"] = bool(dataset.title and dataset.title.strip())
		if not checks["has_title"]:
			issues.append({"field": "title", "severity": "ERROR", "message": "Title is required (DataCite mandatory)"})

		checks["has_creators"] = bool(dataset.creator_ids)
		if not checks["has_creators"]:
			issues.append({"field": "creator_ids", "severity": "ERROR", "message": "At least one creator is required (DataCite mandatory)"})

		checks["has_resource_type"] = bool(dataset.resource_type)
		if not checks["has_resource_type"]:
			issues.append({"field": "resource_type", "severity": "ERROR", "message": "resource_type is required (DataCite mandatory)"})

		checks["has_project"] = bool(dataset.project_id)

		# Recommended fields
		checks["has_publication_year"] = bool(dataset.publication_year)
		if not checks["has_publication_year"]:
			issues.append({"field": "publication_year", "severity": "WARNING", "message": "publication_year recommended for DataCite"})

		checks["has_license"] = bool(dataset.license)
		if not checks["has_license"]:
			issues.append({"field": "license", "severity": "WARNING", "message": "License (SPDX identifier) recommended"})

		checks["has_subjects"] = bool(dataset.subjects)
		if not checks["has_subjects"]:
			issues.append({"field": "subjects", "severity": "WARNING", "message": "At least one subject recommended for discoverability"})

		checks["has_description"] = bool(dataset.description)
		if not checks["has_description"]:
			issues.append({"field": "description", "severity": "WARNING", "message": "Abstract/description recommended"})

		# Consistency checks
		valid_resource_types = {"DATASET", "SOFTWARE", "IMAGE", "COLLECTION", "TEXT", "WORKFLOW"}
		checks["resource_type_valid"] = dataset.resource_type in valid_resource_types
		if not checks["resource_type_valid"]:
			issues.append({
				"field": "resource_type",
				"severity": "ERROR",
				"message": f"resource_type {dataset.resource_type!r} not in {valid_resource_types}",
			})

		valid_access = {"OPEN", "RESTRICTED", "EMBARGOED", "CLOSED"}
		checks["access_rights_valid"] = dataset.access_rights in valid_access
		if not checks["access_rights_valid"]:
			issues.append({
				"field": "access_rights",
				"severity": "ERROR",
				"message": f"access_rights {dataset.access_rights!r} not in {valid_access}",
			})

		lang_re = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
		checks["language_format"] = bool(lang_re.match(dataset.language or ""))
		if not checks["language_format"]:
			issues.append({
				"field": "language",
				"severity": "WARNING",
				"message": f"language {dataset.language!r} should be BCP 47 (e.g. 'en', 'zh-CN')",
			})

		doi_re = re.compile(r"^10\.\d{4,}/\S+$")
		if dataset.doi:
			checks["doi_format"] = bool(doi_re.match(dataset.doi))
			if not checks["doi_format"]:
				issues.append({"field": "doi", "severity": "ERROR", "message": f"DOI {dataset.doi!r} does not match 10.NNNN/suffix pattern"})
		else:
			checks["doi_format"] = True  # no DOI yet is not an error

		# Format checks
		if dataset.storage_url and not dataset.file_format:
			checks["file_format_set"] = False
			issues.append({
				"field": "file_format",
				"severity": "WARNING",
				"message": "storage_url is set but file_format is empty",
			})
		else:
			checks["file_format_set"] = True

		# Score: errors weight 10, warnings weight 3; perfect = all pass
		error_count = sum(1 for i in issues if i["severity"] == "ERROR")
		warning_count = sum(1 for i in issues if i["severity"] == "WARNING")
		total_checks = len(checks)
		passed = sum(1 for v in checks.values() if v)
		score = round(passed / total_checks * 100) if total_checks > 0 else 0

		return {
			"dataset_id": dataset_id,
			"title": dataset.title,
			"score": score,
			"checks_passed": passed,
			"checks_total": total_checks,
			"error_count": error_count,
			"warning_count": warning_count,
			"issues": issues,
			"checks": checks,
			"is_publishable": error_count == 0,
		}

	# ------------------------------------------------------------------
	# DataCite 4.4 XML export
	# ------------------------------------------------------------------

	def export_datacite_xml(
		self,
		dataset_id: str,
		session: Any,
	) -> str:
		"""Generate DataCite Metadata Schema 4.4 XML for a dataset.

		Returns a UTF-8 XML string conforming to:
		  https://schema.datacite.org/meta/kernel-4.4/

		Raises:
		  DatasetNotFoundError if dataset_id not found.
		"""
		from pgappforge.plugins.erp.industry.research.models import Dataset

		dataset = session.get(Dataset, dataset_id)
		if dataset is None:
			raise DatasetNotFoundError(f"Dataset {dataset_id!r} not found")

		NS = "http://datacite.org/schema/kernel-4"
		XSI = "http://www.w3.org/2001/XMLSchema-instance"
		SCHEMA_LOC = (
			"http://datacite.org/schema/kernel-4 "
			"https://schema.datacite.org/meta/kernel-4.4/metadata.xsd"
		)

		root = Element(
			"resource",
			attrib={
				"xmlns": NS,
				"xmlns:xsi": XSI,
				"xsi:schemaLocation": SCHEMA_LOC,
			},
		)

		# identifier
		if dataset.doi:
			id_el = SubElement(root, "identifier", attrib={"identifierType": "DOI"})
			id_el.text = dataset.doi

		# creators
		creators_el = SubElement(root, "creators")
		for cid in (dataset.creator_ids or []):
			c_el = SubElement(creators_el, "creator")
			cn = SubElement(c_el, "creatorName", attrib={"nameType": "Personal"})
			cn.text = str(cid)

		# titles
		titles_el = SubElement(root, "titles")
		t_el = SubElement(titles_el, "title")
		t_el.text = dataset.title

		# publisher
		pub_el = SubElement(root, "publisher")
		pub_el.text = "PgAppForge Research Repository"

		# publicationYear
		year_el = SubElement(root, "publicationYear")
		year_el.text = str(dataset.publication_year or datetime.now(timezone.utc).year)

		# resourceType
		_type_map = {
			"DATASET": "Dataset",
			"SOFTWARE": "Software",
			"IMAGE": "Image",
			"COLLECTION": "Collection",
			"TEXT": "Text",
			"WORKFLOW": "Workflow",
		}
		rt_el = SubElement(
			root, "resourceType",
			attrib={"resourceTypeGeneral": _type_map.get(dataset.resource_type, "Dataset")},
		)
		rt_el.text = dataset.resource_type

		# subjects
		if dataset.subjects:
			subjects_el = SubElement(root, "subjects")
			for s in dataset.subjects:
				s_el = SubElement(subjects_el, "subject")
				s_el.text = str(s)

		# language
		lang_el = SubElement(root, "language")
		lang_el.text = dataset.language or "en"

		# version
		ver_el = SubElement(root, "version")
		ver_el.text = dataset.version or "1"

		# rightsList
		if dataset.license:
			rights_el = SubElement(root, "rightsList")
			r_el = SubElement(rights_el, "rights", attrib={"rightsIdentifierScheme": "SPDX"})
			r_el.text = dataset.license

		# descriptions
		if dataset.description:
			descs_el = SubElement(root, "descriptions")
			d_el = SubElement(descs_el, "description", attrib={"descriptionType": "Abstract"})
			d_el.text = dataset.description

		# sizes
		if dataset.file_size_bytes:
			sizes_el = SubElement(root, "sizes")
			sz_el = SubElement(sizes_el, "size")
			sz_el.text = f"{dataset.file_size_bytes} bytes"

		# formats
		if dataset.file_format:
			formats_el = SubElement(root, "formats")
			for fmt in dataset.file_format:
				f_el = SubElement(formats_el, "format")
				f_el.text = str(fmt)

		indent(root, space="\t")
		return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")


__all__ = [
	"ResearchService",
	"ResearchError",
	"ProjectNotFoundError",
	"DatasetNotFoundError",
	"DOIMintError",
	"PublicationNotFoundError",
	"ImmutableProvenanceError",
]
