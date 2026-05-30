"""
Knowledge Graph construction from unstructured text using Apache AGE.

Extracts entities (NER) and relationships (dependency parsing) from text
and creates vertices/edges in an AGE graph.

Requires::

    pip install spacy
    python -m spacy download en_core_web_sm  # or en_core_web_lg for better accuracy

Usage::

    from pgappforge.database.age import AGEManager
    from pgappforge.database.age.knowledge_graph import KnowledgeGraphBuilder

    mgr = AGEManager(engine)
    graph = mgr.create_graph('research')

    builder = KnowledgeGraphBuilder(graph)
    result = builder.extract_from_text(
        "Apple Inc. was founded by Steve Jobs in Cupertino, California."
    )
    # → Creates vertices: Apple Inc (ORG), Steve Jobs (PERSON), Cupertino (GPE)
    # → Creates edges: founded_by, located_in

    # Batch processing
    docs = ["Tesla makes electric cars.", "Elon Musk runs Tesla."]
    result = builder.extract_from_documents(docs)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

log = logging.getLogger(__name__)

# spaCy NER labels mapped to AGE vertex labels
_LABEL_MAP = {
	"PERSON": "Person",
	"ORG": "Organization",
	"GPE": "Location",          # Geopolitical entity
	"LOC": "Location",
	"FAC": "Facility",
	"PRODUCT": "Product",
	"EVENT": "Event",
	"WORK_OF_ART": "WorkOfArt",
	"LAW": "Law",
	"LANGUAGE": "Language",
	"DATE": "Date",
	"MONEY": "MonetaryAmount",
	"NORP": "Group",            # Nationalities, religious groups
}


class KnowledgeGraphBuilder:
	"""Builds an AGE knowledge graph from free-form text.

	Args:
	    graph: An AGEGraph instance to write vertices and edges to.
	    nlp_model: spaCy model name (default: en_core_web_sm).
	"""

	def __init__(self, graph, nlp_model: str = "en_core_web_sm") -> None:
		self.graph = graph
		self.nlp_model = nlp_model
		self._nlp = None

	def _get_nlp(self):
		"""Lazy-load the spaCy model."""
		if self._nlp is not None:
			return self._nlp
		try:
			import spacy
			self._nlp = spacy.load(self.nlp_model)
			return self._nlp
		except ImportError:
			raise RuntimeError(
				"spaCy is required for knowledge graph construction. "
				"Install: pip install spacy && python -m spacy download en_core_web_sm"
			)
		except OSError:
			raise RuntimeError(
				f"spaCy model '{self.nlp_model}' not found. "
				f"Install: python -m spacy download {self.nlp_model}"
			)

	def extract_from_text(
		self,
		text: str,
		label_entities: bool = True,
		extract_relations: bool = True,
	) -> dict[str, Any]:
		"""Extract entities and relationships from a single text.

		Args:
		    text: Input text to process.
		    label_entities: Create vertices for named entities.
		    extract_relations: Create edges for subject-verb-object triples.

		Returns:
		    {"entities": [...], "relationships": [...],
		     "vertices_created": N, "edges_created": M}
		"""
		nlp = self._get_nlp()
		doc = nlp(text)

		entities_created: dict[str, dict] = {}  # text → vertex info
		edges_created = []
		errors = []

		# ── Extract named entities → AGE vertices ────────────────────────────
		if label_entities:
			for ent in doc.ents:
				key = ent.text.strip().lower()
				if key in entities_created:
					entities_created[key]["count"] += 1
					continue

				ag_label = _LABEL_MAP.get(ent.label_, "Entity")
				props = {
					"text": ent.text,
					"type": ent.label_,
					"count": 1,
				}
				try:
					vertex = self.graph.create_vertex(ag_label, props)
					entities_created[key] = {
						"text": ent.text,
						"label": ag_label,
						"spacy_label": ent.label_,
						"vertex_id": getattr(vertex, "id", None),
						"count": 1,
					}
				except Exception as exc:
					errors.append(str(exc))

		# ── Extract SVO triples → AGE edges ──────────────────────────────────
		if extract_relations and entities_created:
			entity_texts = {v["text"].lower(): v for v in entities_created.values()}

			for token in doc:
				if token.dep_ == "ROOT" and token.pos_ == "VERB":
					# Find subject and object
					subj = next(
						(t for t in token.lefts if t.dep_ in ("nsubj", "nsubjpass")),
						None,
					)
					obj = next(
						(t for t in token.rights if t.dep_ in ("dobj", "pobj", "attr")),
						None,
					)

					if subj and obj:
						subj_ent = entity_texts.get(subj.text.lower())
						obj_ent = entity_texts.get(obj.text.lower())

						if subj_ent and obj_ent and subj_ent.get("vertex_id") and obj_ent.get("vertex_id"):
							rel_type = token.lemma_.upper().replace(" ", "_")
							try:
								self.graph.create_edge(
									subj_ent["label"],
									{"text": subj_ent["text"]},
									rel_type,
									obj_ent["label"],
									{"text": obj_ent["text"]},
									properties={"verb": token.text, "sentence": token.sent.text[:200]},
								)
								edges_created.append({
									"from": subj_ent["text"],
									"relation": rel_type,
									"to": obj_ent["text"],
								})
							except Exception as exc:
								errors.append(str(exc))

		return {
			"entities": list(entities_created.values()),
			"relationships": edges_created,
			"vertices_created": len(entities_created),
			"edges_created": len(edges_created),
			"errors": errors,
		}

	def extract_from_documents(self, docs: list[str]) -> dict[str, Any]:
		"""Process multiple documents, tracking co-occurrence across texts.

		Args:
		    docs: List of text strings.

		Returns:
		    Aggregated extraction results with co-occurrence counts.
		"""
		total_entities: dict[str, dict] = defaultdict(lambda: {"count": 0})
		total_relations: list[dict] = []
		total_errors: list[str] = []
		vertices_total = 0
		edges_total = 0

		for i, doc_text in enumerate(docs):
			log.info("Processing document %d/%d", i + 1, len(docs))
			result = self.extract_from_text(doc_text)
			vertices_total += result["vertices_created"]
			edges_total += result["edges_created"]
			total_relations.extend(result["relationships"])
			total_errors.extend(result["errors"])
			for ent in result["entities"]:
				key = ent["text"].lower()
				total_entities[key]["text"] = ent["text"]
				total_entities[key]["label"] = ent["label"]
				total_entities[key]["count"] += ent.get("count", 1)

		return {
			"documents_processed": len(docs),
			"unique_entities": len(total_entities),
			"total_relationships": len(total_relations),
			"vertices_created": vertices_total,
			"edges_created": edges_total,
			"top_entities": sorted(
				total_entities.values(),
				key=lambda x: x["count"],
				reverse=True,
			)[:20],
			"errors": total_errors[:10],
		}

	def entity_stats(self) -> dict[str, Any]:
		"""Return entity counts by type from the current AGE graph."""
		schema = self.graph.schema()
		stats = {}
		for label, props in schema.items():
			count = self.graph.count(label)
			stats[label] = {"count": count, "properties": props}
		return stats

	def find_related(self, entity: str, hops: int = 2) -> list[dict]:
		"""Find all entities related to the named entity within N hops.

		Args:
		    entity: Entity text to search for (case-insensitive).
		    hops: Maximum path length (1-5).

		Returns:
		    List of result row dicts from the Cypher query.
		"""
		hops = max(1, min(hops, 5))
		cypher = (
			f"MATCH (start) WHERE toLower(start.text) = toLower('{entity}') "
			f"MATCH path = (start)-[*1..{hops}]-(end) "
			f"RETURN path LIMIT 200"
		)
		return self.graph.cypher(cypher)

	def build_from_structured(
		self,
		records: list[dict],
		vertex_label: str,
		id_field: str,
		relation_field: str | None = None,
		relation_label: str = "RELATED_TO",
	) -> dict[str, Any]:
		"""Build a graph from structured records (list of dicts).

		Each record becomes a vertex. If relation_field is set, it should
		contain a list of IDs of other records to link to.

		Args:
		    records: List of property dicts.
		    vertex_label: Label for all created vertices.
		    id_field: Property name to use as the unique identifier.
		    relation_field: Optional property containing list of related IDs.
		    relation_label: Edge label for relations.
		"""
		vertices = 0
		edges = 0

		for record in records:
			props = {k: str(v)[:500] for k, v in record.items()
			         if k != relation_field and v is not None}
			self.graph.create_vertex(vertex_label, props)
			vertices += 1

		if relation_field:
			for record in records:
				related_ids = record.get(relation_field) or []
				if isinstance(related_ids, str):
					related_ids = [related_ids]
				for rid in related_ids:
					try:
						self.graph.create_edge(
							vertex_label, {id_field: str(record[id_field])},
							relation_label,
							vertex_label, {id_field: str(rid)},
						)
						edges += 1
					except Exception:
						pass

		return {"vertices_created": vertices, "edges_created": edges}
