"""
Flask view for Federated Graph Analytics System

Provides web interface for managing and executing federated graph analytics
operations across distributed systems, including cross-organizational queries,
pattern detection, and synchronized operations.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from flask import request, flash, redirect, url_for, jsonify, render_template
from pgappforge import ModelView, BaseView, has_access, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.security.decorators import protect
from sqlalchemy import text

from ..database.federated_analytics import (
	get_federated_analytics,
	execute_cross_organizational_query,
	FederationProtocol,
	NodeRole,
	PrivacyLevel,
	FederatedNode,
	FederatedQuery
)
from ..database.multi_graph_manager import get_graph_registry
from ..database.activity_tracker import track_database_activity, ActivityType
from ..utils.error_handling import WizardErrorHandler, WizardErrorType

logger = logging.getLogger(__name__)


class FederatedAnalyticsView(BaseView):
	"""View for managing federated graph analytics operations"""
	
	route_base = '/federated_analytics'
	default_view = 'index'
	
	# Security - Admin only
	base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
	
	@expose('/')
	@has_access
	def index(self):
		"""Main federated analytics dashboard"""
		try:
			federation = get_federated_analytics()
			status = federation.get_system_status()
			
			# Get recent federated queries
			recent_queries = federation.get_query_history(limit=10)
			
			# Get active federated nodes
			active_nodes = [
				node for node in federation.nodes.values()
				if node.status == "active"
			]
			
			# Get available graphs for federation
			graph_registry = get_graph_registry()
			available_graphs = graph_registry.list_graphs()
			
			return self.render_template(
				'federated_analytics/index.html',
				system_status=status,
				recent_queries=recent_queries,
				active_nodes=active_nodes,
				available_graphs=available_graphs,
				federation_protocols=list(FederationProtocol),
				node_roles=list(NodeRole),
				privacy_levels=list(PrivacyLevel)
			)
			
		except Exception as e:
			error_handler = WizardErrorHandler()
			error_handler.handle_error(
				error=e,
				error_type=WizardErrorType.FEDERATION_ERROR,
				context={'action': 'dashboard_load'}
			)
			flash(f'Error loading federated analytics dashboard: {str(e)}', 'error')
			return self.render_template('federated_analytics/error.html', error=str(e))
	
	@expose('/nodes/')
	@has_access
	def list_nodes(self):
		"""List and manage federated nodes"""
		try:
			federation = get_federated_analytics()
			nodes = list(federation.nodes.values())
			
			return self.render_template(
				'federated_analytics/nodes.html',
				nodes=nodes,
				federation_protocols=list(FederationProtocol),
				node_roles=list(NodeRole)
			)
			
		except Exception as e:
			flash(f'Error loading federated nodes: {str(e)}', 'error')
			return redirect(url_for('FederatedAnalyticsView.index'))
	
	@expose('/register_node/', methods=['GET', 'POST'])
	@has_access
	def register_node(self):
		"""Register a new federated node"""
		if request.method == 'POST':
			try:
				federation = get_federated_analytics()
				
				# Extract form data
				node_data = {
					'node_id': request.form.get('node_id'),
					'name': request.form.get('name'),
					'endpoint': request.form.get('endpoint'),
					'organization': request.form.get('organization'),
					'protocol': FederationProtocol(request.form.get('protocol')),
					'role': NodeRole(request.form.get('role')),
					'capabilities': request.form.getlist('capabilities'),
					'description': request.form.get('description', '')
				}
				
				# Create federated node
				node = FederatedNode(
					node_id=node_data['node_id'],
					name=node_data['name'],
					endpoint=node_data['endpoint'],
					protocol=node_data['protocol'],
					role=node_data['role'],
					metadata={
						'organization': node_data['organization'],
						'description': node_data['description'],
						'registered_at': datetime.now().isoformat(),
						'capabilities': node_data['capabilities']
					}
				)
				
				# Register node
				result = federation.register_node(node)
				
				if result['success']:
					flash('Federated node registered successfully!', 'success')
					track_database_activity(ActivityType.NODE_REGISTRATION, {
						'node_id': node_data['node_id'],
						'organization': node_data['organization'],
						'protocol': node_data['protocol'].value
					})
				else:
					flash(f"Failed to register node: {result.get('error', 'Unknown error')}", 'error')
				
				return redirect(url_for('FederatedAnalyticsView.list_nodes'))
				
			except Exception as e:
				error_handler = WizardErrorHandler()
				error_handler.handle_error(
					error=e,
					error_type=WizardErrorType.FEDERATION_ERROR,
					context={'action': 'node_registration', 'node_data': request.form.to_dict()}
				)
				flash(f'Error registering federated node: {str(e)}', 'error')
		
		# GET request - show registration form
		graph_registry = get_graph_registry()
		available_graphs = graph_registry.list_graphs()
		
		return self.render_template(
			'federated_analytics/register_node.html',
			available_graphs=available_graphs,
			federation_protocols=list(FederationProtocol),
			node_roles=list(NodeRole)
		)
	
	@expose('/queries/')
	@has_access
	def list_queries(self):
		"""List federated queries and their status"""
		try:
			federation = get_federated_analytics()
			queries = federation.get_query_history(limit=50)
			
			return self.render_template(
				'federated_analytics/queries.html',
				queries=queries
			)
			
		except Exception as e:
			flash(f'Error loading federated queries: {str(e)}', 'error')
			return redirect(url_for('FederatedAnalyticsView.index'))
	
	@expose('/execute_query/', methods=['GET', 'POST'])
	@has_access
	def execute_query(self):
		"""Execute a federated query across multiple nodes"""
		if request.method == 'POST':
			try:
				federation = get_federated_analytics()
				
				# Extract query parameters
				query_text = request.form.get('query_text', '').strip()
				target_nodes = request.form.getlist('target_nodes')
				privacy_level = PrivacyLevel(request.form.get('privacy_level', 'STANDARD'))
				aggregation_function = request.form.get('aggregation_function')
				
				if not query_text:
					flash('Query text is required', 'error')
					return redirect(url_for('FederatedAnalyticsView.execute_query'))
				
				if not target_nodes:
					flash('At least one target node must be selected', 'error')
					return redirect(url_for('FederatedAnalyticsView.execute_query'))
				
				# Execute federated query
				federated_query = federation.execute_federated_query(
					query_text=query_text,
					target_nodes=target_nodes,
					privacy_level=privacy_level,
					aggregation_function=aggregation_function if aggregation_function else None
				)
				
				flash(f'Federated query started successfully! Query ID: {federated_query.query_id}', 'success')
				
				track_database_activity(ActivityType.FEDERATED_QUERY, {
					'query_id': federated_query.query_id,
					'target_nodes': len(target_nodes),
					'privacy_level': privacy_level.value
				})
				
				return redirect(url_for('FederatedAnalyticsView.query_status', query_id=federated_query.query_id))
				
			except Exception as e:
				error_handler = WizardErrorHandler()
				error_handler.handle_error(
					error=e,
					error_type=WizardErrorType.QUERY_EXECUTION_ERROR,
					context={'query_text': request.form.get('query_text', ''), 'target_nodes': request.form.getlist('target_nodes')}
				)
				flash(f'Error executing federated query: {str(e)}', 'error')
		
		# GET request - show query form
		try:
			federation = get_federated_analytics()
			available_nodes = list(federation.nodes.values())
			
			return self.render_template(
				'federated_analytics/execute_query.html',
				available_nodes=available_nodes,
				privacy_levels=list(PrivacyLevel)
			)
			
		except Exception as e:
			flash(f'Error loading query form: {str(e)}', 'error')
			return redirect(url_for('FederatedAnalyticsView.index'))
	
	@expose('/query_status/<string:query_id>')
	@has_access
	def query_status(self, query_id):
		"""View status and results of a specific federated query"""
		try:
			federation = get_federated_analytics()
			query_info = federation.get_query_status(query_id)
			
			if not query_info:
				flash('Query not found', 'error')
				return redirect(url_for('FederatedAnalyticsView.list_queries'))
			
			return self.render_template(
				'federated_analytics/query_status.html',
				query=query_info
			)
			
		except Exception as e:
			flash(f'Error loading query status: {str(e)}', 'error')
			return redirect(url_for('FederatedAnalyticsView.list_queries'))
	
	@expose('/cross_organizational/', methods=['GET', 'POST'])
	@has_access
	def cross_organizational_analysis(self):
		"""Execute cross-organizational federated analysis"""
		if request.method == 'POST':
			try:
				# Extract parameters
				query = request.form.get('query', '').strip()
				organizations = request.form.getlist('organizations')
				privacy_level = PrivacyLevel(request.form.get('privacy_level', 'STANDARD'))
				aggregation = request.form.get('aggregation')
				
				if not query:
					flash('Query is required', 'error')
					return redirect(url_for('FederatedAnalyticsView.cross_organizational_analysis'))
				
				if not organizations:
					flash('At least one organization must be selected', 'error')
					return redirect(url_for('FederatedAnalyticsView.cross_organizational_analysis'))
				
				# Execute cross-organizational query
				result = execute_cross_organizational_query(
					query=query,
					organizations=organizations,
					privacy_level=privacy_level,
					aggregation=aggregation if aggregation else None
				)
				
				flash(f'Cross-organizational analysis started! Query ID: {result["query_id"]}', 'success')
				
				return redirect(url_for('FederatedAnalyticsView.query_status', query_id=result['query_id']))
				
			except Exception as e:
				error_handler = WizardErrorHandler()
				error_handler.handle_error(
					error=e,
					error_type=WizardErrorType.FEDERATION_ERROR,
					context={'organizations': request.form.getlist('organizations')}
				)
				flash(f'Error executing cross-organizational analysis: {str(e)}', 'error')
		
		# GET request - show analysis form
		try:
			federation = get_federated_analytics()
			
			# Get organizations from registered nodes
			organizations = set()
			for node in federation.nodes.values():
				org = node.metadata.get('organization')
				if org:
					organizations.add(org)
			
			return self.render_template(
				'federated_analytics/cross_organizational.html',
				organizations=sorted(organizations),
				privacy_levels=list(PrivacyLevel)
			)
			
		except Exception as e:
			flash(f'Error loading cross-organizational analysis form: {str(e)}', 'error')
			return redirect(url_for('FederatedAnalyticsView.index'))
	
	# API Endpoints
	
	@expose('/api/system_status')
	@has_access
	def api_system_status(self):
		"""API endpoint for system status"""
		try:
			federation = get_federated_analytics()
			status = federation.get_system_status()
			return jsonify(status)
		except Exception as e:
			return jsonify({'error': str(e)}), 500
	
	@expose('/api/nodes')
	@has_access
	def api_nodes(self):
		"""API endpoint for federated nodes"""
		try:
			federation = get_federated_analytics()
			nodes = [
				{
					'node_id': node.node_id,
					'name': node.name,
					'endpoint': node.endpoint,
					'status': node.status,
					'organization': node.metadata.get('organization'),
					'protocol': node.protocol.value,
					'role': node.role.value,
					'last_ping': node.last_ping.isoformat() if node.last_ping else None
				}
				for node in federation.nodes.values()
			]
			return jsonify({'nodes': nodes})
		except Exception as e:
			return jsonify({'error': str(e)}), 500
	
	@expose('/api/queries')
	@has_access
	def api_queries(self):
		"""API endpoint for federated queries"""
		try:
			federation = get_federated_analytics()
			limit = int(request.args.get('limit', 20))
			queries = federation.get_query_history(limit=limit)
			
			# Convert to JSON-serializable format
			serialized_queries = []
			for query in queries:
				serialized_query = {
					'query_id': query.query_id,
					'query_text': query.query_text,
					'status': query.status.value,
					'created_at': query.created_at.isoformat(),
					'target_nodes': query.target_nodes,
					'privacy_level': query.privacy_level.value,
					'result_count': len(query.results) if query.results else 0
				}
				if query.completed_at:
					serialized_query['completed_at'] = query.completed_at.isoformat()
				if query.error_message:
					serialized_query['error_message'] = query.error_message
				serialized_queries.append(serialized_query)
			
			return jsonify({'queries': serialized_queries})
		except Exception as e:
			return jsonify({'error': str(e)}), 500
	
	@expose('/api/query/<string:query_id>')
	@has_access
	def api_query_detail(self, query_id):
		"""API endpoint for detailed query information"""
		try:
			federation = get_federated_analytics()
			query_info = federation.get_query_status(query_id)
			
			if not query_info:
				return jsonify({'error': 'Query not found'}), 404
			
			# Convert to JSON-serializable format
			serialized_query = {
				'query_id': query_info.query_id,
				'query_text': query_info.query_text,
				'status': query_info.status.value,
				'created_at': query_info.created_at.isoformat(),
				'target_nodes': query_info.target_nodes,
				'privacy_level': query_info.privacy_level.value,
				'results': query_info.results,
				'execution_stats': query_info.execution_stats
			}
			
			if query_info.completed_at:
				serialized_query['completed_at'] = query_info.completed_at.isoformat()
			if query_info.error_message:
				serialized_query['error_message'] = query_info.error_message
			
			return jsonify(serialized_query)
		except Exception as e:
			return jsonify({'error': str(e)}), 500
	
	@expose('/api/execute_query', methods=['POST'])
	@has_access
	def api_execute_query(self):
		"""API endpoint for executing federated queries"""
		try:
			data = request.get_json()
			
			if not data:
				return jsonify({'error': 'No JSON data provided'}), 400
			
			query_text = data.get('query_text', '').strip()
			target_nodes = data.get('target_nodes', [])
			privacy_level = PrivacyLevel(data.get('privacy_level', 'STANDARD'))
			aggregation_function = data.get('aggregation_function')
			
			if not query_text:
				return jsonify({'error': 'Query text is required'}), 400
			
			if not target_nodes:
				return jsonify({'error': 'Target nodes are required'}), 400
			
			federation = get_federated_analytics()
			federated_query = federation.execute_federated_query(
				query_text=query_text,
				target_nodes=target_nodes,
				privacy_level=privacy_level,
				aggregation_function=aggregation_function
			)
			
			track_database_activity(ActivityType.FEDERATED_QUERY, {
				'query_id': federated_query.query_id,
				'target_nodes': len(target_nodes),
				'privacy_level': privacy_level.value,
				'via_api': True
			})
			
			return jsonify({
				'query_id': federated_query.query_id,
				'status': federated_query.status.value,
				'created_at': federated_query.created_at.isoformat(),
				'target_nodes': len(target_nodes)
			})
			
		except Exception as e:
			error_handler = WizardErrorHandler()
			error_handler.handle_error(
				error=e,
				error_type=WizardErrorType.API_ERROR,
				context={'endpoint': 'api_execute_query', 'data': request.get_json()}
			)
			return jsonify({'error': str(e)}), 500
	
	@expose('/api/organizations')
	@has_access
	def api_organizations(self):
		"""API endpoint for available organizations"""
		try:
			federation = get_federated_analytics()
			
			organizations = set()
			for node in federation.nodes.values():
				org = node.metadata.get('organization')
				if org:
					organizations.add(org)
			
			return jsonify({'organizations': sorted(organizations)})
		except Exception as e:
			return jsonify({'error': str(e)}), 500