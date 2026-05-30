"""
Knowledge Graph Construction View

Flask view for the advanced knowledge graph construction system.
Provides interface for building knowledge graphs from various data sources.
"""

import json
import logging
import io
import base64
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash, send_file
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden
from werkzeug.utils import secure_filename

from ..database.knowledge_graph_constructor import (
	get_knowledge_graph_builder,
	construct_knowledge_graph_from_documents,
	KnowledgeGraphBuilder
)
from ..database.activity_tracker import (
	track_database_activity,
	ActivityType,
	ActivitySeverity
)
from ..utils.error_handling import (
	WizardErrorHandler,
	WizardErrorType,
	WizardErrorSeverity
)

logger = logging.getLogger(__name__)


class KnowledgeGraphView(BaseView):
	"""
	Knowledge graph construction interface
	
	Provides comprehensive interface for building and managing knowledge graphs
	from various data sources using NLP and entity extraction.
	"""
	
	route_base = "/knowledge-graph"
	default_view = "index"
	
	def __init__(self):
		"""Initialize knowledge graph view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		
		# Supported file types for document processing
		self.supported_extensions = {'.txt', '.csv', '.json', '.xml', '.html'}
		
	def _ensure_admin_access(self):
		"""Ensure current user has admin privileges"""
		try:
			from flask_login import current_user
			
			if not current_user or not current_user.is_authenticated:
				raise Forbidden("Authentication required")
			
			# Check if user has admin role
			if hasattr(current_user, "roles"):
				admin_roles = ["Admin", "admin", "Administrator", "administrator"]
				user_roles = [
					role.name if hasattr(role, "name") else str(role)
					for role in current_user.roles
				]
				
				if not any(role in admin_roles for role in user_roles):
					raise Forbidden("Administrator privileges required")
			else:
				# Fallback check for is_admin attribute
				if not getattr(current_user, "is_admin", False):
					raise Forbidden("Administrator privileges required")
					
		except Exception as e:
			logger.error(f"Admin access check failed: {e}")
			raise Forbidden("Access denied")
	
	def _get_current_user_id(self) -> str:
		"""Get current user ID"""
		try:
			from flask_login import current_user
			if current_user and current_user.is_authenticated:
				return str(current_user.id) if hasattr(current_user, 'id') else str(current_user)
			return "admin"
		except:
			return "admin"
	
	@expose("/")
	@has_access
	@permission_name("can_build_knowledge_graphs")
	def index(self):
		"""Main knowledge graph construction dashboard"""
		try:
			self._ensure_admin_access()
			
			# Get available graphs
			available_graphs = self._get_available_graphs()
			
			# Get recent construction activities
			recent_activities = self._get_recent_activities()
			
			# Get construction statistics
			construction_stats = self._get_construction_statistics()
			
			return render_template(
				"knowledge_graph/index.html",
				title="Knowledge Graph Construction",
				available_graphs=available_graphs,
				recent_activities=recent_activities,
				construction_stats=construction_stats,
				supported_extensions=list(self.supported_extensions)
			)
			
		except Exception as e:
			logger.error(f"Error in knowledge graph dashboard: {e}")
			flash(f"Error loading knowledge graph dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/build/<graph_name>/")
	@has_access
	@permission_name("can_build_knowledge_graphs")
	def build_interface(self, graph_name):
		"""Knowledge graph building interface for specific graph"""
		try:
			self._ensure_admin_access()
			
			# Get or create knowledge graph builder
			builder = get_knowledge_graph_builder(graph_name)
			
			# Get current graph analysis
			graph_analysis = builder.analyze_knowledge_graph()
			
			# Get processing statistics
			processing_stats = builder.processing_stats
			
			return render_template(
				"knowledge_graph/build.html",
				title=f"Build Knowledge Graph - {graph_name}",
				graph_name=graph_name,
				graph_analysis=graph_analysis,
				processing_stats=processing_stats,
				supported_extensions=list(self.supported_extensions)
			)
			
		except Exception as e:
			logger.error(f"Error in build interface: {e}")
			flash(f"Error loading build interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/analyze/<graph_name>/")
	@has_access
	@permission_name("can_analyze_knowledge_graphs")
	def analyze_graph(self, graph_name):
		"""Knowledge graph analysis interface"""
		try:
			self._ensure_admin_access()
			
			builder = get_knowledge_graph_builder(graph_name)
			analysis = builder.analyze_knowledge_graph()
			
			# Get additional insights
			insights = self._generate_graph_insights(analysis)
			
			return render_template(
				"knowledge_graph/analyze.html",
				title=f"Analyze Knowledge Graph - {graph_name}",
				graph_name=graph_name,
				analysis=analysis,
				insights=insights
			)
			
		except Exception as e:
			logger.error(f"Error in graph analysis: {e}")
			flash(f"Error analyzing knowledge graph: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	def _get_available_graphs(self) -> List[str]:
		"""Get list of available graphs"""
		# Mock implementation - would typically query database
		return ["company_knowledge", "research_papers", "social_network", "product_catalog"]
	
	def _get_recent_activities(self) -> List[Dict[str, Any]]:
		"""Get recent construction activities"""
		# Mock implementation - would query activity log
		return [
			{
				"timestamp": "2024-01-15T10:30:00",
				"action": "Document Processed",
				"graph": "company_knowledge",
				"details": "Extracted 45 entities, 23 relationships",
				"user": "admin"
			},
			{
				"timestamp": "2024-01-15T09:15:00",
				"action": "Batch Processing Complete",
				"graph": "research_papers",
				"details": "Processed 15 documents",
				"user": "admin"
			}
		]
	
	def _get_construction_statistics(self) -> Dict[str, Any]:
		"""Get overall construction statistics"""
		# Mock implementation - would aggregate from all builders
		return {
			"total_documents_processed": 156,
			"total_entities_extracted": 4523,
			"total_relationships_extracted": 2876,
			"average_processing_time": 2.3,
			"graphs_built": 4,
			"average_quality_score": 0.78
		}
	
	def _generate_graph_insights(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""Generate insights from graph analysis"""
		insights = []
		
		if analysis.get("graph_statistics"):
			stats = analysis["graph_statistics"]
			
			# Density insight
			density = stats.get("density", 0)
			if density > 0.5:
				insights.append({
					"type": "density",
					"level": "high",
					"message": f"High graph density ({density:.2%}) indicates rich interconnections",
					"recommendation": "Consider clustering or hierarchical organization"
				})
			elif density < 0.1:
				insights.append({
					"type": "density",
					"level": "low",
					"message": f"Low graph density ({density:.2%}) suggests sparse connections",
					"recommendation": "Look for missing relationships or consider entity consolidation"
				})
			
			# Size insight
			node_count = stats.get("node_count", 0)
			if node_count > 10000:
				insights.append({
					"type": "scale",
					"level": "large",
					"message": f"Large graph ({node_count:,} nodes) may benefit from optimization",
					"recommendation": "Consider implementing graph partitioning or indexing strategies"
				})
		
		if analysis.get("quality_metrics"):
			quality = analysis["quality_metrics"]
			
			# Quality insight
			overall_quality = quality.get("overall_quality_score", 0)
			if overall_quality > 0.8:
				insights.append({
					"type": "quality",
					"level": "high",
					"message": f"High quality score ({overall_quality:.1%}) indicates reliable extractions",
					"recommendation": "Graph is ready for production use"
				})
			elif overall_quality < 0.6:
				insights.append({
					"type": "quality",
					"level": "low",
					"message": f"Low quality score ({overall_quality:.1%}) suggests extraction issues",
					"recommendation": "Review source documents and extraction parameters"
				})
		
		return insights
	
	# API Endpoints
	
	@expose_api("post", "/api/process-document/")
	@has_access
	@permission_name("can_process_documents")
	def api_process_document(self):
		"""API endpoint to process a single document"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			content = data.get("content")
			metadata = data.get("metadata", {})
			
			if not all([graph_name, content]):
				raise BadRequest("graph_name and content are required")
			
			user_id = self._get_current_user_id()
			
			# Process document
			builder = get_knowledge_graph_builder(graph_name)
			doc_metadata = builder.process_document(content, metadata)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.DOCUMENT_PROCESSED,
				target=f"Graph: {graph_name}",
				description="Document processed for knowledge extraction",
				details={
					"user_id": user_id,
					"document_id": doc_metadata.document_id,
					"entity_count": doc_metadata.entity_count,
					"relationship_count": doc_metadata.relationship_count
				}
			)
			
			return jsonify({
				"success": True,
				"document_metadata": doc_metadata.to_dict(),
				"message": f"Processed document: {doc_metadata.entity_count} entities, {doc_metadata.relationship_count} relationships"
			})
			
		except Exception as e:
			logger.error(f"API error processing document: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/process-batch/")
	@has_access
	@permission_name("can_process_documents")
	def api_process_batch(self):
		"""API endpoint to process multiple documents"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			documents = data.get("documents", [])
			max_workers = data.get("max_workers", 4)
			
			if not graph_name or not documents:
				raise BadRequest("graph_name and documents are required")
			
			user_id = self._get_current_user_id()
			
			# Process documents in batch
			results = construct_knowledge_graph_from_documents(
				graph_name, documents, max_workers
			)
			
			# Track activity
			total_entities = sum(doc.entity_count for doc in results)
			total_relationships = sum(doc.relationship_count for doc in results)
			
			track_database_activity(
				activity_type=ActivityType.BATCH_PROCESSED,
				target=f"Graph: {graph_name}",
				description=f"Batch processing completed: {len(documents)} documents",
				details={
					"user_id": user_id,
					"document_count": len(documents),
					"total_entities": total_entities,
					"total_relationships": total_relationships,
					"max_workers": max_workers
				}
			)
			
			return jsonify({
				"success": True,
				"results": [doc.to_dict() for doc in results],
				"summary": {
					"documents_processed": len(results),
					"total_entities": total_entities,
					"total_relationships": total_relationships
				},
				"message": f"Batch processed {len(results)} documents successfully"
			})
			
		except Exception as e:
			logger.error(f"API error processing batch: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/upload-file/")
	@has_access
	@permission_name("can_upload_files")
	def api_upload_file(self):
		"""API endpoint to upload and process file"""
		try:
			self._ensure_admin_access()
			
			if 'file' not in request.files:
				raise BadRequest("No file provided")
			
			file = request.files['file']
			graph_name = request.form.get('graph_name')
			
			if not graph_name:
				raise BadRequest("graph_name is required")
			
			if file.filename == '':
				raise BadRequest("No file selected")
			
			# Check file extension
			filename = secure_filename(file.filename)
			file_ext = '.' + filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
			
			if file_ext not in self.supported_extensions:
				raise BadRequest(f"Unsupported file type. Supported: {', '.join(self.supported_extensions)}")
			
			# Read file content
			content = file.read().decode('utf-8', errors='ignore')
			
			# Prepare metadata
			metadata = {
				"title": filename,
				"source": "file_upload",
				"type": file_ext[1:],  # Remove dot from extension
				"size": len(content)
			}
			
			# Process document
			builder = get_knowledge_graph_builder(graph_name)
			doc_metadata = builder.process_document(content, metadata)
			
			user_id = self._get_current_user_id()
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.FILE_UPLOADED,
				target=f"File: {filename}",
				description="File uploaded and processed for knowledge extraction",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"filename": filename,
					"file_size": len(content),
					"entity_count": doc_metadata.entity_count,
					"relationship_count": doc_metadata.relationship_count
				}
			)
			
			return jsonify({
				"success": True,
				"document_metadata": doc_metadata.to_dict(),
				"message": f"File processed successfully: {filename}"
			})
			
		except Exception as e:
			logger.error(f"API error uploading file: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/analyze/<graph_name>/")
	@has_access
	@permission_name("can_analyze_knowledge_graphs")
	def api_analyze_graph(self, graph_name):
		"""API endpoint to get graph analysis"""
		try:
			self._ensure_admin_access()
			
			builder = get_knowledge_graph_builder(graph_name)
			analysis = builder.analyze_knowledge_graph()
			
			# Generate insights
			insights = self._generate_graph_insights(analysis)
			
			return jsonify({
				"success": True,
				"analysis": analysis,
				"insights": insights,
				"graph_name": graph_name
			})
			
		except Exception as e:
			logger.error(f"API error analyzing graph: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/export/<graph_name>/")
	@has_access
	@permission_name("can_export_knowledge_graphs")
	def api_export_graph(self, graph_name):
		"""API endpoint to export knowledge graph"""
		try:
			self._ensure_admin_access()
			
			export_format = request.args.get("format", "json")
			
			builder = get_knowledge_graph_builder(graph_name)
			exported_data = builder.export_knowledge_graph(export_format)
			
			user_id = self._get_current_user_id()
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.KNOWLEDGE_GRAPH_EXPORTED,
				target=f"Graph: {graph_name}",
				description=f"Knowledge graph exported in {export_format} format",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"format": export_format,
					"node_count": exported_data.get("metadata", {}).get("node_count", 0),
					"relationship_count": exported_data.get("metadata", {}).get("relationship_count", 0)
				}
			)
			
			return jsonify({
				"success": True,
				"data": exported_data,
				"format": export_format
			})
			
		except Exception as e:
			logger.error(f"API error exporting graph: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/statistics/")
	@has_access
	@permission_name("can_view_statistics")
	def api_get_statistics(self):
		"""API endpoint to get construction statistics"""
		try:
			self._ensure_admin_access()
			
			statistics = self._get_construction_statistics()
			
			# Get per-graph statistics
			graph_stats = {}
			for graph_name in self._get_available_graphs():
				try:
					builder = get_knowledge_graph_builder(graph_name)
					graph_stats[graph_name] = builder.processing_stats
				except Exception as e:
					logger.warning(f"Could not get stats for {graph_name}: {e}")
			
			return jsonify({
				"success": True,
				"overall_statistics": statistics,
				"graph_statistics": graph_stats
			})
			
		except Exception as e:
			logger.error(f"API error getting statistics: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/extract-entities/")
	@has_access
	@permission_name("can_extract_entities")
	def api_extract_entities(self):
		"""API endpoint for entity extraction testing"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			text = data.get("text")
			if not text:
				raise BadRequest("text is required")
			
			# Use a temporary builder for entity extraction
			from ..database.knowledge_graph_constructor import EntityExtractor
			extractor = EntityExtractor()
			entities = extractor.extract_entities(text)
			
			return jsonify({
				"success": True,
				"entities": [entity.to_dict() for entity in entities],
				"entity_count": len(entities),
				"text_length": len(text)
			})
			
		except Exception as e:
			logger.error(f"API error extracting entities: {e}")
			return jsonify({"success": False, "error": str(e)}), 500