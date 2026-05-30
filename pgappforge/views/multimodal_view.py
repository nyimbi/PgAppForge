"""
Multi-Modal Integration View

Flask view for the multi-modal data integration system.
Provides interface for processing and analyzing images, audio, text, and video files.
"""

import json
import logging
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash
from werkzeug.utils import secure_filename
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden
import os

from ..database.multimodal_integration import (
	get_multimodal_integration,
	process_media_batch,
	analyze_media_similarity,
	get_media_analysis_report
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


class MultiModalView(BaseView):
	"""
	Multi-modal data integration interface
	
	Provides comprehensive interface for processing images, audio, text,
	and video files with advanced feature extraction and similarity analysis.
	"""
	
	route_base = "/multimodal"
	default_view = "index"
	
	def __init__(self):
		"""Initialize multi-modal view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.supported_image_types = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
		self.supported_audio_types = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
		self.supported_video_types = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}
		self.supported_text_types = {'.txt', '.json', '.csv', '.xml', '.html', '.md', '.pdf'}
		
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
	@permission_name("can_use_multimodal")
	def index(self):
		"""Main multi-modal integration dashboard"""
		try:
			self._ensure_admin_access()
			
			# Get available graphs
			available_graphs = self._get_available_graphs()
			
			# Get processing statistics
			processing_stats = self._get_processing_statistics()
			
			# Get recent processing activities
			recent_activities = self._get_recent_activities()
			
			# Get supported file types
			supported_types = self._get_supported_file_types()
			
			return render_template(
				"multimodal/index.html",
				title="Multi-Modal Data Integration",
				available_graphs=available_graphs,
				processing_stats=processing_stats,
				recent_activities=recent_activities,
				supported_types=supported_types,
				max_file_size_mb=100  # 100MB limit
			)
			
		except Exception as e:
			logger.error(f"Error in multimodal dashboard: {e}")
			flash(f"Error loading multimodal dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))

	@expose("/analyze/<graph_name>/")
	@has_access
	@permission_name("can_analyze_multimodal")
	def analyze_media(self, graph_name):
		"""Media analysis interface"""
		try:
			self._ensure_admin_access()
			
			integration = get_multimodal_integration(graph_name)
			
			# Get media analysis report
			analysis_report = get_media_analysis_report(graph_name)
			
			# Get similarity clusters
			similarity_clusters = self._get_similarity_clusters(graph_name)
			
			# Get media statistics
			media_stats = self._get_media_statistics(graph_name)
			
			return render_template(
				"multimodal/analyze.html",
				title=f"Media Analysis - {graph_name}",
				graph_name=graph_name,
				analysis_report=analysis_report,
				similarity_clusters=similarity_clusters,
				media_stats=media_stats
			)
			
		except Exception as e:
			logger.error(f"Error in media analysis: {e}")
			flash(f"Error loading media analysis: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))

	def _get_available_graphs(self) -> List[str]:
		"""Get list of available graphs"""
		# Mock implementation - would typically query database
		return ["company_knowledge", "social_network", "product_catalog", "research_data"]

	def _get_processing_statistics(self) -> Dict[str, Any]:
		"""Get processing statistics across all graphs"""
		# Mock implementation - would query actual processing history
		return {
			"total_files_processed": 1247,
			"images_processed": 856,
			"audio_processed": 234,
			"video_processed": 89,
			"text_processed": 68,
			"total_features_extracted": 15678,
			"similarity_clusters_found": 123,
			"processing_time_hours": 45.7
		}

	def _get_recent_activities(self) -> List[Dict[str, Any]]:
		"""Get recent processing activities"""
		# Mock implementation - would query activity history
		return [
			{
				"timestamp": "2024-01-15T14:30:00",
				"action": "Batch Image Processing",
				"graph": "company_knowledge",
				"details": "Processed 25 images, extracted 340 features",
				"files_count": 25,
				"status": "completed"
			},
			{
				"timestamp": "2024-01-15T13:45:00",
				"action": "Audio Analysis",
				"graph": "research_data",
				"details": "Analyzed 8 audio files, found 12 similarity clusters",
				"files_count": 8,
				"status": "completed"
			},
			{
				"timestamp": "2024-01-15T12:20:00",
				"action": "Video Feature Extraction",
				"graph": "social_network",
				"details": "Extracted features from 3 videos",
				"files_count": 3,
				"status": "completed"
			}
		]

	def _get_supported_file_types(self) -> Dict[str, List[str]]:
		"""Get supported file types by category"""
		return {
			"image": list(self.supported_image_types),
			"audio": list(self.supported_audio_types),
			"video": list(self.supported_video_types),
			"text": list(self.supported_text_types)
		}

	def _get_similarity_clusters(self, graph_name: str) -> List[Dict[str, Any]]:
		"""Get similarity clusters for a graph"""
		# Mock implementation
		return [
			{
				"cluster_id": "cluster_001",
				"media_type": "image",
				"cluster_size": 12,
				"similarity_score": 0.89,
				"representative_files": ["photo_001.jpg", "image_045.png"],
				"dominant_features": ["blue_dominant", "outdoor_scene", "high_contrast"]
			},
			{
				"cluster_id": "cluster_002",
				"media_type": "audio",
				"cluster_size": 8,
				"similarity_score": 0.76,
				"representative_files": ["audio_12.mp3", "sound_34.wav"],
				"dominant_features": ["high_tempo", "electronic_genre", "stereo"]
			}
		]

	def _get_media_statistics(self, graph_name: str) -> Dict[str, Any]:
		"""Get media statistics for a specific graph"""
		return {
			"total_media_items": 456,
			"images": 234,
			"audio_files": 123,
			"video_files": 67,
			"text_documents": 32,
			"total_features": 8954,
			"similarity_relationships": 234,
			"processing_accuracy": 94.2
		}

	def _validate_file_type(self, filename: str) -> str:
		"""Validate and determine file type"""
		if not filename:
			raise BadRequest("No filename provided")
			
		ext = os.path.splitext(filename.lower())[1]
		
		if ext in self.supported_image_types:
			return "image"
		elif ext in self.supported_audio_types:
			return "audio"
		elif ext in self.supported_video_types:
			return "video"
		elif ext in self.supported_text_types:
			return "text"
		else:
			raise BadRequest(f"Unsupported file type: {ext}")

	# API Endpoints

	@expose_api("post", "/api/upload-media/")
	@has_access
	@permission_name("can_upload_media")
	def api_upload_media(self):
		"""API endpoint to upload and process media files"""
		try:
			self._ensure_admin_access()
			
			if 'files' not in request.files:
				raise BadRequest("No files provided")
				
			files = request.files.getlist('files')
			graph_name = request.form.get('graph_name')
			
			if not graph_name:
				raise BadRequest("Graph name is required")
			
			if not files or all(f.filename == '' for f in files):
				raise BadRequest("No files selected")
			
			user_id = self._get_current_user_id()
			integration = get_multimodal_integration(graph_name)
			
			processed_files = []
			total_features = 0
			
			for file in files:
				if file.filename == '':
					continue
					
				filename = secure_filename(file.filename)
				file_type = self._validate_file_type(filename)
				
				# Read file data
				file_data = file.read()
				
				# Process based on file type
				if file_type == "image":
					features = integration.image_processor.extract_features(file_data, filename)
					media_item = integration.create_media_node(
						graph_name, filename, file_type, features
					)
				elif file_type == "audio":
					features = integration.audio_processor.extract_features(file_data, filename)
					media_item = integration.create_media_node(
						graph_name, filename, file_type, features
					)
				elif file_type == "video":
					features = integration.video_processor.extract_features(file_data, filename)
					media_item = integration.create_media_node(
						graph_name, filename, file_type, features
					)
				else:  # text
					content = file_data.decode('utf-8', errors='ignore')
					features = integration.text_processor.extract_features(content, filename)
					media_item = integration.create_media_node(
						graph_name, filename, file_type, features
					)
				
				processed_files.append({
					"filename": filename,
					"file_type": file_type,
					"features_count": len(features),
					"node_id": media_item.get("node_id")
				})
				
				total_features += len(features)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.MEDIA_PROCESSED,
				target=f"Graph: {graph_name}",
				description=f"Uploaded and processed {len(processed_files)} media files",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"files_processed": len(processed_files),
					"total_features_extracted": total_features,
					"file_types": list(set(f["file_type"] for f in processed_files))
				}
			)
			
			return jsonify({
				"success": True,
				"graph_name": graph_name,
				"processed_files": processed_files,
				"summary": {
					"files_processed": len(processed_files),
					"total_features_extracted": total_features,
					"file_types_processed": list(set(f["file_type"] for f in processed_files))
				},
				"message": f"Successfully processed {len(processed_files)} media files"
			})
			
		except Exception as e:
			logger.error(f"API error uploading media: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("post", "/api/analyze-similarity/")
	@has_access
	@permission_name("can_analyze_similarity")
	def api_analyze_similarity(self):
		"""API endpoint to analyze media similarity"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			media_type = data.get("media_type", "all")
			similarity_threshold = data.get("similarity_threshold", 0.7)
			
			if not graph_name:
				raise BadRequest("Graph name is required")
			
			user_id = self._get_current_user_id()
			
			# Run similarity analysis
			similarity_results = analyze_media_similarity(
				graph_name, 
				media_type=media_type,
				threshold=similarity_threshold
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.SIMILARITY_ANALYSIS_RUN,
				target=f"Graph: {graph_name}",
				description=f"Media similarity analysis completed",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"media_type": media_type,
					"similarity_threshold": similarity_threshold,
					"clusters_found": len(similarity_results.get("clusters", [])),
					"relationships_created": similarity_results.get("relationships_created", 0)
				}
			)
			
			return jsonify({
				"success": True,
				"graph_name": graph_name,
				"similarity_results": similarity_results,
				"message": f"Similarity analysis completed: {len(similarity_results.get('clusters', []))} clusters found"
			})
			
		except Exception as e:
			logger.error(f"API error analyzing similarity: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("post", "/api/batch-process/")
	@has_access
	@permission_name("can_batch_process")
	def api_batch_process(self):
		"""API endpoint for batch media processing"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			file_paths = data.get("file_paths", [])
			max_workers = data.get("max_workers", 4)
			
			if not graph_name:
				raise BadRequest("Graph name is required")
			
			if not file_paths:
				raise BadRequest("File paths are required")
			
			user_id = self._get_current_user_id()
			
			# Process media batch
			batch_results = process_media_batch(
				graph_name,
				file_paths,
				max_workers=max_workers
			)
			
			# Track activity
			track_database_activity(
				activity_type=ActivityType.BATCH_PROCESSING_COMPLETED,
				target=f"Graph: {graph_name}",
				description=f"Batch processed {len(file_paths)} media files",
				details={
					"user_id": user_id,
					"graph_name": graph_name,
					"files_requested": len(file_paths),
					"files_processed": batch_results.get("files_processed", 0),
					"total_features": batch_results.get("total_features_extracted", 0),
					"processing_time_seconds": batch_results.get("processing_time", 0),
					"max_workers": max_workers
				}
			)
			
			return jsonify({
				"success": True,
				"graph_name": graph_name,
				"batch_results": batch_results,
				"message": f"Batch processing completed: {batch_results.get('files_processed', 0)}/{len(file_paths)} files processed"
			})
			
		except Exception as e:
			logger.error(f"API error in batch processing: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("get", "/api/analysis-report/<graph_name>/")
	@has_access
	@permission_name("can_view_analysis_reports")
	def api_get_analysis_report(self, graph_name):
		"""API endpoint to get media analysis report"""
		try:
			self._ensure_admin_access()
			
			report = get_media_analysis_report(graph_name)
			
			return jsonify({
				"success": True,
				"report": report
			})
			
		except Exception as e:
			logger.error(f"API error getting analysis report: {e}")
			return jsonify({"success": False, "error": str(e)}), 500

	@expose_api("get", "/api/processing-stats/")
	@has_access
	@permission_name("can_view_processing_stats")
	def api_get_processing_stats(self):
		"""API endpoint to get processing statistics"""
		try:
			self._ensure_admin_access()
			
			stats = self._get_processing_statistics()
			
			return jsonify({
				"success": True,
				"statistics": stats
			})
			
		except Exception as e:
			logger.error(f"API error getting processing stats: {e}")
			return jsonify({"success": False, "error": str(e)}), 500