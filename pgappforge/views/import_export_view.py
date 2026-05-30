"""
Import/Export View for Graph Data Exchange

Provides web interface for importing and exporting graph data in multiple
formats with comprehensive job management and progress tracking.
"""

import json
import logging
import tempfile
import os
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash, send_file
from pgappforge import permission_name
from pgappforge.security.decorators import has_access
from pgappforge.baseviews import BaseView, expose, expose_api
from werkzeug.exceptions import BadRequest, Forbidden
from werkzeug.utils import secure_filename

from ..database.import_export_pipeline import (
	get_import_export_pipeline,
	ImportExportPipeline,
	ExportFormat,
	ImportFormat,
	ImportMapping,
	DataExchangeJob,
	ProcessingStatus
)
from ..database.graph_manager import get_graph_manager
from ..database.multi_graph_manager import get_graph_registry
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


class ImportExportView(BaseView):
	"""
	Import/Export interface for graph data exchange
	
	Provides comprehensive data exchange capabilities with multiple formats,
	job management, and progress tracking through intuitive web interface.
	"""
	
	route_base = "/graph/import-export"
	default_view = "index"
	
	def __init__(self):
		"""Initialize import/export view"""
		super().__init__()
		self.error_handler = WizardErrorHandler()
		self.pipeline = None
		
		# Configure upload settings
		self.ALLOWED_EXTENSIONS = {
			'graphml', 'xml', 'gexf', 'csv', 'json', 
			'cypher', 'cql', 'txt', 'zip'
		}
		self.MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
	
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
	
	def _get_pipeline(self) -> ImportExportPipeline:
		"""Get or initialize import/export pipeline"""
		try:
			return get_import_export_pipeline()
		except Exception as e:
			logger.error(f"Failed to initialize import/export pipeline: {e}")
			self.error_handler.handle_error(
				e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
			)
			raise
	
	def _allowed_file(self, filename: str) -> bool:
		"""Check if file extension is allowed"""
		return '.' in filename and \
			   filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS
	
	@expose("/")
	@has_access
	@permission_name("can_import_export")
	def index(self):
		"""Import/Export dashboard"""
		try:
			self._ensure_admin_access()
			
			pipeline = self._get_pipeline()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			# Get active jobs
			active_jobs = pipeline.get_active_jobs()
			
			# Get recent job history
			job_history = pipeline.get_job_history(20)
			
			# Get format information
			export_formats = pipeline.get_format_info("export")
			import_formats = pipeline.get_format_info("import")
			
			# Calculate job statistics
			job_stats = {
				"total_jobs": len(active_jobs) + len(job_history),
				"active_jobs": len(active_jobs),
				"completed_jobs": len([j for j in job_history if j.status == ProcessingStatus.COMPLETED]),
				"failed_jobs": len([j for j in job_history if j.status == ProcessingStatus.FAILED])
			}
			
			return render_template(
				"import_export/index.html",
				title="Graph Import/Export",
				graphs=[graph.to_dict() for graph in graphs],
				active_jobs=[job.to_dict() for job in active_jobs],
				job_history=[job.to_dict() for job in job_history],
				export_formats=export_formats,
				import_formats=import_formats,
				job_stats=job_stats
			)
			
		except Exception as e:
			logger.error(f"Error in import/export dashboard: {e}")
			flash(f"Error loading import/export dashboard: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/export/")
	@has_access
	@permission_name("can_import_export")
	def export(self):
		"""Export interface"""
		try:
			self._ensure_admin_access()
			
			# Get available graphs
			registry = get_graph_registry()
			graphs = registry.list_graphs()
			
			pipeline = self._get_pipeline()
			export_formats = pipeline.get_format_info("export")
			
			return render_template(
				"import_export/export.html",
				title="Export Graph Data",
				graphs=[graph.to_dict() for graph in graphs],
				export_formats=export_formats
			)
			
		except Exception as e:
			logger.error(f"Error in export interface: {e}")
			flash(f"Error loading export interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/import/")
	@has_access
	@permission_name("can_import_export")
	def import_data(self):
		"""Import interface"""
		try:
			self._ensure_admin_access()
			
			pipeline = self._get_pipeline()
			import_formats = pipeline.get_format_info("import")
			
			return render_template(
				"import_export/import.html",
				title="Import Graph Data",
				import_formats=import_formats
			)
			
		except Exception as e:
			logger.error(f"Error in import interface: {e}")
			flash(f"Error loading import interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	@expose("/jobs/")
	@has_access
	@permission_name("can_import_export")
	def jobs(self):
		"""Job management interface"""
		try:
			self._ensure_admin_access()
			
			pipeline = self._get_pipeline()
			active_jobs = pipeline.get_active_jobs()
			job_history = pipeline.get_job_history(50)
			
			return render_template(
				"import_export/jobs.html",
				title="Import/Export Jobs",
				active_jobs=[job.to_dict() for job in active_jobs],
				job_history=[job.to_dict() for job in job_history]
			)
			
		except Exception as e:
			logger.error(f"Error in jobs interface: {e}")
			flash(f"Error loading jobs interface: {str(e)}", "error")
			return render_template("graph/error.html", error=str(e))
	
	# API Endpoints
	
	@expose_api("get", "/api/formats/")
	@has_access
	@permission_name("can_import_export")
	def api_get_formats(self):
		"""API endpoint to get supported formats"""
		try:
			self._ensure_admin_access()
			
			format_type = request.args.get("type", "all")  # "import", "export", or "all"
			
			pipeline = self._get_pipeline()
			
			if format_type == "import":
				formats = pipeline.get_format_info("import")
			elif format_type == "export":
				formats = pipeline.get_format_info("export")
			else:
				formats = {
					"import": pipeline.get_format_info("import"),
					"export": pipeline.get_format_info("export")
				}
			
			return jsonify({
				"success": True,
				"formats": formats
			})
			
		except Exception as e:
			logger.error(f"API error getting formats: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/export/")
	@has_access
	@permission_name("can_import_export")
	def api_start_export(self):
		"""API endpoint to start export job"""
		try:
			self._ensure_admin_access()
			
			data = request.get_json()
			if not data:
				raise BadRequest("No JSON data provided")
			
			graph_name = data.get("graph_name")
			format_str = data.get("format")
			filename = data.get("filename")
			options = data.get("options", {})
			
			if not all([graph_name, format_str, filename]):
				raise BadRequest("graph_name, format, and filename are required")
			
			# Validate format
			try:
				export_format = ExportFormat(format_str)
			except ValueError:
				raise BadRequest(f"Invalid export format: {format_str}")
			
			# Create temporary output path
			temp_dir = tempfile.gettempdir()
			output_path = os.path.join(temp_dir, secure_filename(filename))
			
			# Start export job
			pipeline = self._get_pipeline()
			job_id = pipeline.start_export_job(
				graph_name=graph_name,
				format=export_format,
				output_path=output_path,
				options=options
			)
			
			return jsonify({
				"success": True,
				"job_id": job_id,
				"message": f"Export job {job_id} started"
			})
			
		except Exception as e:
			logger.error(f"API error starting export: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/import/")
	@has_access
	@permission_name("can_import_export")
	def api_start_import(self):
		"""API endpoint to start import job"""
		try:
			self._ensure_admin_access()
			
			# Handle file upload
			if 'file' not in request.files:
				raise BadRequest("No file uploaded")
			
			file = request.files['file']
			if file.filename == '':
				raise BadRequest("No file selected")
			
			if not self._allowed_file(file.filename):
				raise BadRequest("File type not allowed")
			
			# Get form data
			target_graph_name = request.form.get("target_graph_name")
			format_str = request.form.get("format")
			mapping_json = request.form.get("mapping", "{}")
			
			if not all([target_graph_name, format_str]):
				raise BadRequest("target_graph_name and format are required")
			
			# Validate format
			try:
				import_format = ImportFormat(format_str)
			except ValueError:
				raise BadRequest(f"Invalid import format: {format_str}")
			
			# Parse mapping
			try:
				mapping_data = json.loads(mapping_json)
				mapping = ImportMapping(**mapping_data)
			except (json.JSONDecodeError, TypeError) as e:
				mapping = ImportMapping()  # Use defaults
			
			# Save uploaded file
			temp_dir = tempfile.gettempdir()
			filename = secure_filename(file.filename)
			file_path = os.path.join(temp_dir, filename)
			file.save(file_path)
			
			# Start import job
			pipeline = self._get_pipeline()
			job_id = pipeline.start_import_job(
				target_graph_name=target_graph_name,
				format=import_format,
				source_path=file_path,
				mapping=mapping
			)
			
			return jsonify({
				"success": True,
				"job_id": job_id,
				"message": f"Import job {job_id} started"
			})
			
		except Exception as e:
			logger.error(f"API error starting import: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/jobs/")
	@has_access
	@permission_name("can_import_export")
	def api_get_jobs(self):
		"""API endpoint to get jobs"""
		try:
			self._ensure_admin_access()
			
			job_type = request.args.get("type", "all")  # "active", "history", or "all"
			limit = int(request.args.get("limit", 50))
			
			pipeline = self._get_pipeline()
			
			if job_type == "active":
				jobs = pipeline.get_active_jobs()
			elif job_type == "history":
				jobs = pipeline.get_job_history(limit)
			else:
				active_jobs = pipeline.get_active_jobs()
				history_jobs = pipeline.get_job_history(limit - len(active_jobs))
				jobs = active_jobs + history_jobs
			
			return jsonify({
				"success": True,
				"jobs": [job.to_dict() for job in jobs]
			})
			
		except Exception as e:
			logger.error(f"API error getting jobs: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/jobs/<job_id>/")
	@has_access
	@permission_name("can_import_export")
	def api_get_job(self, job_id: str):
		"""API endpoint to get specific job"""
		try:
			self._ensure_admin_access()
			
			pipeline = self._get_pipeline()
			job = pipeline.get_job_status(job_id)
			
			if not job:
				return jsonify({"success": False, "error": "Job not found"}), 404
			
			return jsonify({
				"success": True,
				"job": job.to_dict()
			})
			
		except Exception as e:
			logger.error(f"API error getting job: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/jobs/<job_id>/cancel/")
	@has_access
	@permission_name("can_import_export")
	def api_cancel_job(self, job_id: str):
		"""API endpoint to cancel job"""
		try:
			self._ensure_admin_access()
			
			pipeline = self._get_pipeline()
			success = pipeline.cancel_job(job_id)
			
			if success:
				# Track activity
				track_database_activity(
					activity_type=ActivityType.SYSTEM_MAINTENANCE,
					target=f"Import/Export Job: {job_id}",
					description="Cancelled import/export job",
					details={"job_id": job_id, "action": "cancelled"}
				)
				
				return jsonify({
					"success": True,
					"message": f"Job {job_id} cancelled successfully"
				})
			else:
				return jsonify({
					"success": False,
					"error": "Job could not be cancelled"
				}), 400
			
		except Exception as e:
			logger.error(f"API error cancelling job: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/download/<job_id>/")
	@has_access
	@permission_name("can_import_export")
	def api_download_export(self, job_id: str):
		"""API endpoint to download export file"""
		try:
			self._ensure_admin_access()
			
			pipeline = self._get_pipeline()
			job = pipeline.get_job_status(job_id)
			
			if not job:
				return jsonify({"success": False, "error": "Job not found"}), 404
			
			if job.job_type != "export":
				return jsonify({"success": False, "error": "Job is not an export"}), 400
			
			if job.status != ProcessingStatus.COMPLETED:
				return jsonify({
					"success": False, 
					"error": f"Export not completed (status: {job.status.value})"
				}), 400
			
			# Check if file exists
			if not os.path.exists(job.target):
				return jsonify({"success": False, "error": "Export file not found"}), 404
			
			# Determine filename
			filename = os.path.basename(job.target)
			if not filename:
				filename = f"export_{job.source}_{job.format}"
			
			return send_file(
				job.target,
				as_attachment=True,
				download_name=filename,
				mimetype='application/octet-stream'
			)
			
		except Exception as e:
			logger.error(f"API error downloading export: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("get", "/api/validate-mapping/")
	@has_access
	@permission_name("can_import_export")
	def api_validate_mapping(self):
		"""API endpoint to validate import mapping"""
		try:
			self._ensure_admin_access()
			
			mapping_json = request.args.get("mapping", "{}")
			
			try:
				mapping_data = json.loads(mapping_json)
				mapping = ImportMapping(**mapping_data)
				
				return jsonify({
					"success": True,
					"mapping": mapping.__dict__,
					"is_valid": True
				})
				
			except (json.JSONDecodeError, TypeError) as e:
				return jsonify({
					"success": False,
					"error": f"Invalid mapping: {str(e)}",
					"is_valid": False
				})
			
		except Exception as e:
			logger.error(f"API error validating mapping: {e}")
			return jsonify({"success": False, "error": str(e)}), 500
	
	@expose_api("post", "/api/preview-import/")
	@has_access
	@permission_name("can_import_export")
	def api_preview_import(self):
		"""API endpoint to preview import data"""
		try:
			self._ensure_admin_access()
			
			# Handle file upload for preview
			if 'file' not in request.files:
				raise BadRequest("No file uploaded")
			
			file = request.files['file']
			if file.filename == '':
				raise BadRequest("No file selected")
			
			if not self._allowed_file(file.filename):
				raise BadRequest("File type not allowed")
			
			# Get format
			format_str = request.form.get("format")
			if not format_str:
				raise BadRequest("Format is required")
			
			try:
				import_format = ImportFormat(format_str)
			except ValueError:
				raise BadRequest(f"Invalid import format: {format_str}")
			
			# Save file temporarily
			temp_dir = tempfile.gettempdir()
			filename = secure_filename(file.filename)
			file_path = os.path.join(temp_dir, filename)
			file.save(file_path)
			
			try:
				# Preview import (limit to first few items)
				pipeline = self._get_pipeline()
				
				# Use default mapping for preview
				mapping = ImportMapping()
				
				# Get appropriate importer
				if import_format == ImportFormat.JSON:
					result = pipeline._import_json(file_path, mapping)
				elif import_format == ImportFormat.CSV_NODES_EDGES:
					from ..database.import_export_pipeline import CSVImporter
					importer = CSVImporter()
					result = importer.import_data(file_path, mapping)
				elif import_format == ImportFormat.GRAPHML:
					from ..database.import_export_pipeline import GraphMLImporter
					importer = GraphMLImporter()
					result = importer.import_data(file_path, mapping)
				else:
					raise BadRequest(f"Preview not supported for format: {format_str}")
				
				if result.get("success"):
					# Limit preview data
					preview_nodes = result.get("nodes", [])[:10]
					preview_edges = result.get("edges", [])[:10]
					
					return jsonify({
						"success": True,
						"preview": {
							"nodes": preview_nodes,
							"edges": preview_edges,
							"total_nodes": len(result.get("nodes", [])),
							"total_edges": len(result.get("edges", [])),
							"metadata": result.get("metadata", {})
						}
					})
				else:
					return jsonify({
						"success": False,
						"error": result.get("error", "Preview failed")
					})
					
			finally:
				# Clean up temporary file
				try:
					os.unlink(file_path)
				except:
					pass
			
		except Exception as e:
			logger.error(f"API error previewing import: {e}")
			return jsonify({"success": False, "error": str(e)}), 500