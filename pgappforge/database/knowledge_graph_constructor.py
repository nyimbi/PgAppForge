"""
Advanced Knowledge Graph Construction System

Comprehensive system for automatically constructing knowledge graphs from various
data sources using NLP, entity extraction, and relationship inference.
"""

import logging
import json
import re
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Union, Set
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import DBSCAN, KMeans
from sklearn.preprocessing import StandardScaler

import spacy
import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer

import psycopg2
from pydantic import BaseModel, Field
from uuid_extensions import uuid7str

from .graph_manager import GraphManager
from .activity_tracker import track_database_activity, ActivityType, ActivitySeverity
from ..utils.error_handling import WizardErrorHandler, WizardErrorType, WizardErrorSeverity

logger = logging.getLogger(__name__)


@dataclass
class Entity:
	"""Represents an extracted entity"""
	entity_id: str
	text: str
	label: str  # Entity type (PERSON, ORG, GPE, etc.)
	confidence: float
	start_pos: int
	end_pos: int
	context: str
	properties: Dict[str, Any]
	source_document: Optional[str] = None
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"entity_id": self.entity_id,
			"text": self.text,
			"label": self.label,
			"confidence": self.confidence,
			"start_pos": self.start_pos,
			"end_pos": self.end_pos,
			"context": self.context,
			"properties": self.properties,
			"source_document": self.source_document
		}


@dataclass
class Relationship:
	"""Represents an extracted relationship between entities"""
	relationship_id: str
	subject_entity: Entity
	predicate: str
	object_entity: Entity
	confidence: float
	context: str
	evidence: str
	properties: Dict[str, Any]
	source_document: Optional[str] = None
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"relationship_id": self.relationship_id,
			"subject": self.subject_entity.to_dict(),
			"predicate": self.predicate,
			"object": self.object_entity.to_dict(),
			"confidence": self.confidence,
			"context": self.context,
			"evidence": self.evidence,
			"properties": self.properties,
			"source_document": self.source_document
		}


@dataclass
class DocumentMetadata:
	"""Metadata for processed documents"""
	document_id: str
	title: str
	source: str
	content_type: str
	processing_timestamp: datetime
	entity_count: int
	relationship_count: int
	confidence_score: float
	
	def to_dict(self) -> Dict[str, Any]:
		return {
			"document_id": self.document_id,
			"title": self.title,
			"source": self.source,
			"content_type": self.content_type,
			"processing_timestamp": self.processing_timestamp.isoformat(),
			"entity_count": self.entity_count,
			"relationship_count": self.relationship_count,
			"confidence_score": self.confidence_score
		}


class EntityExtractor:
	"""Advanced entity extraction using multiple NLP techniques"""
	
	def __init__(self):
		try:
			# Initialize spaCy model
			self.nlp = spacy.load("en_core_web_sm")
		except OSError:
			logger.warning("spaCy model not found. Install with: python -m spacy download en_core_web_sm")
			self.nlp = None
		
		# Initialize NLTK components
		try:
			nltk.data.find('tokenizers/punkt')
			nltk.data.find('corpora/stopwords')
			nltk.data.find('corpora/wordnet')
		except LookupError:
			logger.warning("NLTK data not found. Download with: nltk.download(['punkt', 'stopwords', 'wordnet'])")
		
		self.lemmatizer = WordNetLemmatizer()
		self.stop_words = set(stopwords.words('english'))
		
		# Custom entity patterns for domain-specific extraction
		self.custom_patterns = {
			"EMAIL": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
			"PHONE": r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
			"URL": r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',
			"DATE": r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
			"MONEY": r'\$\d+(?:,\d{3})*(?:\.\d{2})?',
			"PERCENTAGE": r'\b\d+(?:\.\d+)?%\b'
		}
		
		logger.info("Entity extractor initialized")
	
	def extract_entities(self, text: str, document_id: str = None) -> List[Entity]:
		"""Extract entities from text using multiple techniques"""
		entities = []
		
		# Extract using spaCy NER
		if self.nlp:
			spacy_entities = self._extract_spacy_entities(text, document_id)
			entities.extend(spacy_entities)
		
		# Extract using custom patterns
		pattern_entities = self._extract_pattern_entities(text, document_id)
		entities.extend(pattern_entities)
		
		# Extract using statistical methods
		statistical_entities = self._extract_statistical_entities(text, document_id)
		entities.extend(statistical_entities)
		
		# Deduplicate and merge similar entities
		entities = self._deduplicate_entities(entities)
		
		return entities
	
	def _extract_spacy_entities(self, text: str, document_id: str = None) -> List[Entity]:
		"""Extract entities using spaCy NER"""
		entities = []
		
		if not self.nlp:
			return entities
		
		doc = self.nlp(text)
		
		for ent in doc.ents:
			# Get context (surrounding words)
			start_context = max(0, ent.start - 10)
			end_context = min(len(doc), ent.end + 10)
			context = doc[start_context:end_context].text
			
			entity = Entity(
				entity_id=uuid7str(),
				text=ent.text,
				label=ent.label_,
				confidence=0.8,  # spaCy doesn't provide confidence scores by default
				start_pos=ent.start_char,
				end_pos=ent.end_char,
				context=context,
				properties={
					"spacy_confidence": 0.8,
					"lemma": ent.lemma_,
					"pos": ent.root.pos_
				},
				source_document=document_id
			)
			entities.append(entity)
		
		return entities
	
	def _extract_pattern_entities(self, text: str, document_id: str = None) -> List[Entity]:
		"""Extract entities using regex patterns"""
		entities = []
		
		for label, pattern in self.custom_patterns.items():
			matches = re.finditer(pattern, text)
			
			for match in matches:
				# Get context
				start_context = max(0, match.start() - 100)
				end_context = min(len(text), match.end() + 100)
				context = text[start_context:end_context]
				
				entity = Entity(
					entity_id=uuid7str(),
					text=match.group(),
					label=label,
					confidence=0.9,  # High confidence for pattern matches
					start_pos=match.start(),
					end_pos=match.end(),
					context=context,
					properties={
						"extraction_method": "pattern",
						"pattern": pattern
					},
					source_document=document_id
				)
				entities.append(entity)
		
		return entities
	
	def _extract_statistical_entities(self, text: str, document_id: str = None) -> List[Entity]:
		"""Extract entities using statistical methods (TF-IDF, etc.)"""
		entities = []
		
		# Tokenize and clean text
		sentences = sent_tokenize(text)
		
		# Find important noun phrases using TF-IDF
		all_words = []
		for sentence in sentences:
			words = word_tokenize(sentence.lower())
			words = [self.lemmatizer.lemmatize(word) for word in words 
					if word.isalpha() and word not in self.stop_words]
			all_words.extend(words)
		
		# Find frequent terms that might be entities
		word_freq = Counter(all_words)
		important_words = [word for word, freq in word_freq.most_common(20) 
						  if freq > 2 and len(word) > 2]
		
		for word in important_words:
			# Find occurrences in original text
			pattern = r'\b' + re.escape(word) + r'\b'
			matches = re.finditer(pattern, text, re.IGNORECASE)
			
			for match in matches:
				# Get context
				start_context = max(0, match.start() - 50)
				end_context = min(len(text), match.end() + 50)
				context = text[start_context:end_context]
				
				entity = Entity(
					entity_id=uuid7str(),
					text=match.group(),
					label="CONCEPT",
					confidence=min(word_freq[word] / 10.0, 0.7),  # Confidence based on frequency
					start_pos=match.start(),
					end_pos=match.end(),
					context=context,
					properties={
						"extraction_method": "statistical",
						"frequency": word_freq[word],
						"tf_score": word_freq[word] / len(all_words)
					},
					source_document=document_id
				)
				entities.append(entity)
		
		return entities
	
	def _deduplicate_entities(self, entities: List[Entity]) -> List[Entity]:
		"""Remove duplicate and overlapping entities"""
		# Sort by start position
		entities.sort(key=lambda e: e.start_pos)
		
		deduplicated = []
		for entity in entities:
			# Check for overlaps with existing entities
			is_duplicate = False
			
			for existing in deduplicated:
				# Check for text overlap
				if (entity.start_pos < existing.end_pos and 
					entity.end_pos > existing.start_pos):
					
					# If substantial overlap, keep the one with higher confidence
					overlap_ratio = (min(entity.end_pos, existing.end_pos) - 
								   max(entity.start_pos, existing.start_pos)) / max(1, entity.end_pos - entity.start_pos)
					
					if overlap_ratio > 0.5:
						if entity.confidence > existing.confidence:
							deduplicated.remove(existing)
						else:
							is_duplicate = True
						break
			
			if not is_duplicate:
				deduplicated.append(entity)
		
		return deduplicated


class RelationshipExtractor:
	"""Advanced relationship extraction between entities"""
	
	def __init__(self):
		try:
			self.nlp = spacy.load("en_core_web_sm")
		except OSError:
			logger.warning("spaCy model not found")
			self.nlp = None
		
		# Predefined relationship patterns
		self.relationship_patterns = {
			"WORKS_FOR": [
				r"(.+) works for (.+)",
				r"(.+) is employed by (.+)",
				r"(.+) employee of (.+)"
			],
			"LOCATED_IN": [
				r"(.+) is located in (.+)",
				r"(.+) in (.+)",
				r"(.+) based in (.+)"
			],
			"OWNS": [
				r"(.+) owns (.+)",
				r"(.+) possesses (.+)",
				r"(.+) has (.+)"
			],
			"MARRIED_TO": [
				r"(.+) is married to (.+)",
				r"(.+) married (.+)",
				r"(.+) spouse of (.+)"
			],
			"MEMBER_OF": [
				r"(.+) is a member of (.+)",
				r"(.+) belongs to (.+)",
				r"(.+) part of (.+)"
			]
		}
		
		logger.info("Relationship extractor initialized")
	
	def extract_relationships(self, text: str, entities: List[Entity], 
							 document_id: str = None) -> List[Relationship]:
		"""Extract relationships between entities"""
		relationships = []
		
		# Extract using dependency parsing
		if self.nlp:
			dep_relationships = self._extract_dependency_relationships(text, entities, document_id)
			relationships.extend(dep_relationships)
		
		# Extract using pattern matching
		pattern_relationships = self._extract_pattern_relationships(text, entities, document_id)
		relationships.extend(pattern_relationships)
		
		# Extract using co-occurrence analysis
		cooccurrence_relationships = self._extract_cooccurrence_relationships(text, entities, document_id)
		relationships.extend(cooccurrence_relationships)
		
		# Deduplicate relationships
		relationships = self._deduplicate_relationships(relationships)
		
		return relationships
	
	def _extract_dependency_relationships(self, text: str, entities: List[Entity], 
										 document_id: str = None) -> List[Relationship]:
		"""Extract relationships using dependency parsing"""
		relationships = []
		
		if not self.nlp:
			return relationships
		
		doc = self.nlp(text)
		
		# Create entity mapping for quick lookup
		entity_map = {}
		for entity in entities:
			for token in doc:
				if (token.idx >= entity.start_pos and 
					token.idx + len(token.text) <= entity.end_pos):
					entity_map[token.i] = entity
		
		# Extract relationships based on dependency structure
		for token in doc:
			if token.i in entity_map:
				subject_entity = entity_map[token.i]
				
				# Look for verb relationships
				for child in token.children:
					if child.dep_ in ["dobj", "pobj", "attr"] and child.i in entity_map:
						object_entity = entity_map[child.i]
						
						# Get the verb or predicate
						predicate = token.head.lemma_ if token.head.pos_ == "VERB" else "RELATED_TO"
						
						# Get context sentence
						sentence_start = token.sent.start_char
						sentence_end = token.sent.end_char
						context = text[sentence_start:sentence_end]
						
						relationship = Relationship(
							relationship_id=uuid7str(),
							subject_entity=subject_entity,
							predicate=predicate.upper(),
							object_entity=object_entity,
							confidence=0.7,
							context=context,
							evidence=f"Dependency: {token.dep_} -> {child.dep_}",
							properties={
								"extraction_method": "dependency_parsing",
								"dependency_path": f"{token.dep_}-{child.dep_}"
							},
							source_document=document_id
						)
						relationships.append(relationship)
		
		return relationships
	
	def _extract_pattern_relationships(self, text: str, entities: List[Entity], 
									  document_id: str = None) -> List[Relationship]:
		"""Extract relationships using predefined patterns"""
		relationships = []
		
		for predicate, patterns in self.relationship_patterns.items():
			for pattern in patterns:
				matches = re.finditer(pattern, text, re.IGNORECASE)
				
				for match in matches:
					subject_text = match.group(1).strip()
					object_text = match.group(2).strip()
					
					# Find matching entities
					subject_entity = self._find_matching_entity(subject_text, entities)
					object_entity = self._find_matching_entity(object_text, entities)
					
					if subject_entity and object_entity:
						# Get context
						context_start = max(0, match.start() - 100)
						context_end = min(len(text), match.end() + 100)
						context = text[context_start:context_end]
						
						relationship = Relationship(
							relationship_id=uuid7str(),
							subject_entity=subject_entity,
							predicate=predicate,
							object_entity=object_entity,
							confidence=0.8,
							context=context,
							evidence=match.group(0),
							properties={
								"extraction_method": "pattern_matching",
								"pattern": pattern
							},
							source_document=document_id
						)
						relationships.append(relationship)
		
		return relationships
	
	def _extract_cooccurrence_relationships(self, text: str, entities: List[Entity], 
										   document_id: str = None) -> List[Relationship]:
		"""Extract relationships based on entity co-occurrence"""
		relationships = []
		
		# Split text into sentences
		sentences = sent_tokenize(text)
		
		for sentence in sentences:
			# Find entities in this sentence
			sentence_entities = []
			for entity in entities:
				if entity.context and entity.context in sentence:
					sentence_entities.append(entity)
			
			# Create relationships between co-occurring entities
			for i, entity1 in enumerate(sentence_entities):
				for j, entity2 in enumerate(sentence_entities):
					if i != j and entity1.label != entity2.label:
						# Calculate confidence based on distance and context
						distance = abs(entity1.start_pos - entity2.start_pos)
						confidence = max(0.3, 1.0 - (distance / 1000.0))  # Closer entities have higher confidence
						
						if confidence > 0.4:  # Minimum confidence threshold
							relationship = Relationship(
								relationship_id=uuid7str(),
								subject_entity=entity1,
								predicate="CO_OCCURS_WITH",
								object_entity=entity2,
								confidence=confidence,
								context=sentence,
								evidence=f"Co-occurrence in sentence",
								properties={
									"extraction_method": "co_occurrence",
									"distance": distance,
									"sentence_length": len(sentence)
								},
								source_document=document_id
							)
							relationships.append(relationship)
		
		return relationships
	
	def _find_matching_entity(self, text: str, entities: List[Entity]) -> Optional[Entity]:
		"""Find entity that matches the given text"""
		text = text.lower().strip()
		
		for entity in entities:
			if entity.text.lower().strip() == text:
				return entity
			# Also check if text is contained in entity text
			if text in entity.text.lower() or entity.text.lower() in text:
				return entity
		
		return None
	
	def _deduplicate_relationships(self, relationships: List[Relationship]) -> List[Relationship]:
		"""Remove duplicate relationships"""
		seen = set()
		deduplicated = []
		
		for rel in relationships:
			# Create a signature for the relationship
			signature = (
				rel.subject_entity.text.lower(),
				rel.predicate,
				rel.object_entity.text.lower()
			)
			
			if signature not in seen:
				seen.add(signature)
				deduplicated.append(rel)
			else:
				# If duplicate, keep the one with higher confidence
				for i, existing_rel in enumerate(deduplicated):
					existing_signature = (
						existing_rel.subject_entity.text.lower(),
						existing_rel.predicate,
						existing_rel.object_entity.text.lower()
					)
					
					if existing_signature == signature and rel.confidence > existing_rel.confidence:
						deduplicated[i] = rel
						break
		
		return deduplicated


class KnowledgeGraphBuilder:
	"""Main knowledge graph construction orchestrator"""
	
	def __init__(self, graph_name: str):
		self.graph_name = graph_name
		self.graph_manager = GraphManager(graph_name)
		self.entity_extractor = EntityExtractor()
		self.relationship_extractor = RelationshipExtractor()
		self.error_handler = WizardErrorHandler()
		
		# Processing statistics
		self.processing_stats = {
			"documents_processed": 0,
			"entities_extracted": 0,
			"relationships_extracted": 0,
			"total_processing_time": 0.0
		}
		
		logger.info(f"Knowledge graph builder initialized for graph: {graph_name}")
	
	def process_document(self, content: str, metadata: Dict[str, Any]) -> DocumentMetadata:
		"""Process a single document and extract knowledge"""
		start_time = datetime.now()
		
		try:
			document_id = metadata.get("id", uuid7str())
			title = metadata.get("title", "Untitled Document")
			source = metadata.get("source", "unknown")
			content_type = metadata.get("type", "text")
			
			logger.info(f"Processing document: {title}")
			
			# Extract entities
			entities = self.entity_extractor.extract_entities(content, document_id)
			
			# Extract relationships
			relationships = self.relationship_extractor.extract_relationships(
				content, entities, document_id
			)
			
			# Store entities in graph
			self._store_entities(entities)
			
			# Store relationships in graph
			self._store_relationships(relationships)
			
			# Calculate confidence score
			entity_confidences = [e.confidence for e in entities if e.confidence > 0]
			relationship_confidences = [r.confidence for r in relationships if r.confidence > 0]
			all_confidences = entity_confidences + relationship_confidences
			
			overall_confidence = np.mean(all_confidences) if all_confidences else 0.0
			
			# Create document metadata
			doc_metadata = DocumentMetadata(
				document_id=document_id,
				title=title,
				source=source,
				content_type=content_type,
				processing_timestamp=datetime.now(),
				entity_count=len(entities),
				relationship_count=len(relationships),
				confidence_score=overall_confidence
			)
			
			# Store document metadata
			self._store_document_metadata(doc_metadata)
			
			# Update processing statistics
			processing_time = (datetime.now() - start_time).total_seconds()
			self.processing_stats["documents_processed"] += 1
			self.processing_stats["entities_extracted"] += len(entities)
			self.processing_stats["relationships_extracted"] += len(relationships)
			self.processing_stats["total_processing_time"] += processing_time
			
			logger.info(f"Document processed: {len(entities)} entities, {len(relationships)} relationships")
			
			return doc_metadata
			
		except Exception as e:
			self.error_handler.handle_error(
				e, WizardErrorType.DATA_PROCESSING_ERROR, WizardErrorSeverity.MEDIUM
			)
			logger.error(f"Document processing failed: {e}")
			raise
	
	def process_documents_batch(self, documents: List[Dict[str, Any]], 
							   max_workers: int = 4) -> List[DocumentMetadata]:
		"""Process multiple documents in parallel"""
		results = []
		
		with ThreadPoolExecutor(max_workers=max_workers) as executor:
			# Submit all documents for processing
			future_to_doc = {
				executor.submit(self.process_document, doc["content"], doc["metadata"]): doc
				for doc in documents
			}
			
			# Collect results
			for future in as_completed(future_to_doc):
				doc = future_to_doc[future]
				try:
					result = future.result()
					results.append(result)
				except Exception as e:
					logger.error(f"Failed to process document {doc.get('metadata', {}).get('title', 'Unknown')}: {e}")
		
		return results
	
	def _store_entities(self, entities: List[Entity]):
		"""Store entities in the knowledge graph"""
		for entity in entities:
			try:
				# Create node in graph
				node_properties = {
					"entity_id": entity.entity_id,
					"text": entity.text,
					"label": entity.label,
					"confidence": entity.confidence,
					"context": entity.context,
					"created_at": datetime.now().isoformat(),
					**entity.properties
				}
				
				self.graph_manager.create_node(entity.label, node_properties)
				
			except Exception as e:
				logger.error(f"Failed to store entity {entity.text}: {e}")
	
	def _store_relationships(self, relationships: List[Relationship]):
		"""Store relationships in the knowledge graph"""
		for rel in relationships:
			try:
				# Create relationship in graph
				rel_properties = {
					"relationship_id": rel.relationship_id,
					"confidence": rel.confidence,
					"context": rel.context,
					"evidence": rel.evidence,
					"created_at": datetime.now().isoformat(),
					**rel.properties
				}
				
				# Note: This assumes entities are already stored and have database IDs
				# In a real implementation, you'd need to map entity IDs to database node IDs
				self.graph_manager.create_relationship(
					rel.subject_entity.entity_id,
					rel.object_entity.entity_id,
					rel.predicate,
					rel_properties
				)
				
			except Exception as e:
				logger.error(f"Failed to store relationship {rel.predicate}: {e}")
	
	def _store_document_metadata(self, doc_metadata: DocumentMetadata):
		"""Store document metadata in the graph"""
		try:
			# Create document node
			doc_properties = doc_metadata.to_dict()
			self.graph_manager.create_node("DOCUMENT", doc_properties)
			
		except Exception as e:
			logger.error(f"Failed to store document metadata: {e}")
	
	def analyze_knowledge_graph(self) -> Dict[str, Any]:
		"""Analyze the constructed knowledge graph"""
		try:
			# Get basic graph statistics
			node_count_query = "MATCH (n) RETURN count(n) as node_count"
			relationship_count_query = "MATCH ()-[r]->() RETURN count(r) as relationship_count"
			
			node_results = self.graph_manager.execute_cypher_query(node_count_query)
			rel_results = self.graph_manager.execute_cypher_query(relationship_count_query)
			
			node_count = node_results[0]["node_count"] if node_results else 0
			relationship_count = rel_results[0]["relationship_count"] if rel_results else 0
			
			# Get entity type distribution
			entity_type_query = """
			MATCH (n)
			WHERE n.label IS NOT NULL
			RETURN n.label as entity_type, count(*) as count
			ORDER BY count DESC
			"""
			entity_type_results = self.graph_manager.execute_cypher_query(entity_type_query)
			entity_distribution = {r["entity_type"]: r["count"] for r in entity_type_results}
			
			# Get relationship type distribution
			rel_type_query = """
			MATCH ()-[r]->()
			RETURN type(r) as relationship_type, count(*) as count
			ORDER BY count DESC
			"""
			rel_type_results = self.graph_manager.execute_cypher_query(rel_type_query)
			relationship_distribution = {r["relationship_type"]: r["count"] for r in rel_type_results}
			
			# Calculate graph density
			density = 0.0
			if node_count > 1:
				max_possible_edges = node_count * (node_count - 1)
				density = (2 * relationship_count) / max_possible_edges
			
			analysis = {
				"graph_statistics": {
					"node_count": node_count,
					"relationship_count": relationship_count,
					"density": density,
					"processing_stats": self.processing_stats
				},
				"entity_distribution": entity_distribution,
				"relationship_distribution": relationship_distribution,
				"quality_metrics": self._calculate_quality_metrics(),
				"analysis_timestamp": datetime.now().isoformat()
			}
			
			return analysis
			
		except Exception as e:
			logger.error(f"Graph analysis failed: {e}")
			return {}
	
	def _calculate_quality_metrics(self) -> Dict[str, float]:
		"""Calculate quality metrics for the knowledge graph"""
		try:
			# Average entity confidence
			avg_entity_confidence_query = """
			MATCH (n)
			WHERE n.confidence IS NOT NULL
			RETURN avg(n.confidence) as avg_confidence
			"""
			entity_results = self.graph_manager.execute_cypher_query(avg_entity_confidence_query)
			avg_entity_confidence = entity_results[0]["avg_confidence"] if entity_results else 0.0
			
			# Average relationship confidence
			avg_rel_confidence_query = """
			MATCH ()-[r]->()
			WHERE r.confidence IS NOT NULL
			RETURN avg(r.confidence) as avg_confidence
			"""
			rel_results = self.graph_manager.execute_cypher_query(avg_rel_confidence_query)
			avg_rel_confidence = rel_results[0]["avg_confidence"] if rel_results else 0.0
			
			# Overall quality score (weighted average)
			overall_quality = (avg_entity_confidence * 0.6 + avg_rel_confidence * 0.4)
			
			return {
				"average_entity_confidence": float(avg_entity_confidence),
				"average_relationship_confidence": float(avg_rel_confidence),
				"overall_quality_score": float(overall_quality),
				"completeness_score": min(1.0, len(self.processing_stats) / 100.0)  # Mock completeness
			}
			
		except Exception as e:
			logger.error(f"Quality metrics calculation failed: {e}")
			return {}
	
	def export_knowledge_graph(self, format: str = "json") -> Dict[str, Any]:
		"""Export the knowledge graph in specified format"""
		try:
			if format == "json":
				# Export as JSON structure
				nodes_query = "MATCH (n) RETURN n"
				relationships_query = "MATCH (a)-[r]->(b) RETURN a, r, b"
				
				node_results = self.graph_manager.execute_cypher_query(nodes_query)
				rel_results = self.graph_manager.execute_cypher_query(relationships_query)
				
				export_data = {
					"graph_name": self.graph_name,
					"exported_at": datetime.now().isoformat(),
					"nodes": node_results,
					"relationships": rel_results,
					"metadata": {
						"node_count": len(node_results),
						"relationship_count": len(rel_results),
						"processing_stats": self.processing_stats
					}
				}
				
				return export_data
			else:
				raise ValueError(f"Unsupported export format: {format}")
				
		except Exception as e:
			logger.error(f"Knowledge graph export failed: {e}")
			return {}


# Global knowledge graph builders
_kg_builders = {}


def get_knowledge_graph_builder(graph_name: str) -> KnowledgeGraphBuilder:
	"""Get or create a knowledge graph builder for the specified graph"""
	if graph_name not in _kg_builders:
		_kg_builders[graph_name] = KnowledgeGraphBuilder(graph_name)
	return _kg_builders[graph_name]


def construct_knowledge_graph_from_documents(graph_name: str, documents: List[Dict[str, Any]],
											max_workers: int = 4) -> List[DocumentMetadata]:
	"""Convenience function to construct knowledge graph from documents"""
	builder = get_knowledge_graph_builder(graph_name)
	return builder.process_documents_batch(documents, max_workers)