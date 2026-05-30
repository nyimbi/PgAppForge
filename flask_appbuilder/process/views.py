"""
Process Management Views for Flask-AppBuilder.

Provides comprehensive web interface and REST APIs for business process
management including process definitions, instances, execution, and monitoring.
"""

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional

from flask import request, jsonify, flash, redirect, url_for, current_app, g
from flask_appbuilder import ModelView, expose, action, has_access
from flask_appbuilder.api import ModelRestApi, BaseApi
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.security.decorators import has_access_api, permission_name, protect
from flask_appbuilder.api import safe
from flask_appbuilder.const import API_RESULT_RES_KEY
from flask_babel import lazy_gettext
from flask_appbuilder.widgets import ListWidget, ShowWidget
from wtforms import StringField, TextAreaField, SelectField
from wtforms.validators import DataRequired, ValidationError
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from marshmallow import fields, post_load

from flask_appbuilder import db
from flask_appbuilder.models.tenant_context import get_current_tenant_id
from .models.process_models import (
    ProcessDefinition, ProcessInstance, ProcessStep, ProcessTemplate,
    ApprovalRequest, SmartTrigger, ProcessMetric, ProcessInstanceStatus,
    ProcessStepStatus, ApprovalStatus, SubprocessDefinition, SubprocessExecution,
    ProcessPool, ProcessLane
)
# Conditional imports for optional process engine components
try:
    from .engine.process_service import get_process_service
except ImportError:
    log.warning("Process service engine not available")
    def get_process_service():
        raise NotImplementedError("Process engine not configured")

try:
    from .tasks import execute_node_async, retry_step_async
except ImportError:
    log.warning("Process task queue not available")
    class MockAsyncTask:
        def delay(self, *args, **kwargs):
            raise NotImplementedError("Task queue not configured")
    execute_node_async = MockAsyncTask()
    retry_step_async = MockAsyncTask()

try:
    from .security.validation import ProcessValidator
except ImportError:
    log.warning("Process validator not available")
    class ProcessValidator:
        @staticmethod
        def validate_process_graph(graph_data):
            return True, []


class ProcessDefinitionSchema(SQLAlchemyAutoSchema):
    """Schema for ProcessDefinition serialization."""
    
    class Meta:
        model = ProcessDefinition
        load_instance = True
        include_relationships = True
        
    process_graph = fields.Raw()
    variables = fields.Raw()
    configuration = fields.Raw()
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ProcessInstanceSchema(SQLAlchemyAutoSchema):
    """Schema for ProcessInstance serialization."""
    
    class Meta:
        model = ProcessInstance
        load_instance = True
        include_relationships = True
        
    input_data = fields.Raw()
    output_data = fields.Raw()
    context_variables = fields.Raw()
    error_details = fields.Raw()
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ProcessStepSchema(SQLAlchemyAutoSchema):
    """Schema for ProcessStep serialization."""
    
    class Meta:
        model = ProcessStep
        load_instance = True
        
    input_data = fields.Raw()
    output_data = fields.Raw()
    configuration = fields.Raw()
    error_details = fields.Raw()
    created_at = fields.DateTime(dump_only=True)


class ProcessDefinitionView(ModelView):
    """View for managing process definitions."""
    
    datamodel = SQLAInterface(ProcessDefinition)
    
    list_columns = [
        'name', 'version', 'category', 'status', 'created_by', 'created_at'
    ]
    
    show_columns = [
        'name', 'description', 'version', 'category', 'status',
        'process_graph', 'variables', 'configuration',
        'created_by', 'created_at', 'updated_at'
    ]
    
    edit_columns = [
        'name', 'description', 'version', 'category', 'status',
        'process_graph', 'variables', 'configuration'
    ]
    
    add_columns = edit_columns
    
    search_columns = ['name', 'description', 'category', 'created_by.username']
    
    base_permissions = ['can_list', 'can_show', 'can_add', 'can_edit', 'can_delete']
    
    @action('deploy', lazy_gettext('Deploy Process'), lazy_gettext('Deploy this process definition'), 'fa-rocket')
    @permission_name('can_deploy_process')
    @has_access
    def deploy_process(self, items):
        """Deploy selected process definitions."""
        if not items:
            flash(lazy_gettext('No processes selected'), 'warning')
            return redirect(self.get_redirect())
            
        deployed_count = 0
        errors = []
        
        try:
            for definition in items:
                try:
                    # Validate process definition before deployment
                    if definition.process_graph:
                        ProcessValidator.validate_process_definition({
                            'name': definition.name,
                            'definition': definition.process_graph,
                            'description': definition.description or ''
                        })
                    
                    if definition.status == 'draft':
                        definition.status = 'active'
                        definition.deployed_at = datetime.now(tz=timezone.utc)
                        deployed_count += 1
                        
                except ValidationError as e:
                    errors.append(lazy_gettext('Validation failed for %(name)s: %(error)s', name=definition.name, error=str(e)))
                except Exception as e:
                    log.error(f'Error deploying process {definition.name}: {e}')
                    errors.append(lazy_gettext('Error deploying %(name)s: %(error)s', name=definition.name, error=str(e)))
            
            # Single commit at the end
            if deployed_count > 0:
                self.datamodel.session.commit()
                flash(lazy_gettext('Deployed %(count)d process definitions', count=deployed_count), 'success')
            else:
                flash(lazy_gettext('No processes were deployed (only draft processes can be deployed)'), 'warning')
            
            # Report errors after successful operations
            for error in errors:
                flash(error, 'error')
                
        except Exception as e:
            self.datamodel.session.rollback()
            flash(lazy_gettext('Failed to deploy processes: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())
    
    @action('archive', lazy_gettext('Archive Process'), lazy_gettext('Archive this process definition'), 'fa-archive')
    @permission_name('can_edit_process')
    @has_access
    def archive_process(self, items):
        """Archive selected process definitions."""
        if not items:
            flash(lazy_gettext('No processes selected'), 'warning')
            return redirect(self.get_redirect())
            
        archived_count = 0
        
        try:
            for definition in items:
                if definition.status in ['active', 'inactive']:
                    definition.status = 'archived'
                    archived_count += 1
            
            if archived_count > 0:
                self.datamodel.session.commit()
                flash(lazy_gettext('Archived %(count)d process definitions', count=archived_count), 'success')
            else:
                flash(lazy_gettext('No processes were archived'), 'warning')
                
        except Exception as e:
            self.datamodel.session.rollback()
            flash(lazy_gettext('Failed to archive processes: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())
    
    @expose('/designer/<int:definition_id>')
    @has_access
    def designer(self, definition_id):
        """Visual process designer interface."""
        definition = self.datamodel.get(definition_id)
        if not definition:
            flash(lazy_gettext('Process definition not found'), 'error')
            return redirect(self.get_redirect())
            
        return self.render_template(
            'process/designer.html',
            definition=definition,
            process_graph=json.dumps(definition.process_graph or {'nodes': [], 'edges': []})
        )


class ProcessInstanceView(ModelView):
    """View for managing process instances."""
    
    datamodel = SQLAInterface(ProcessInstance)
    
    list_columns = [
        'definition.name', 'status', 'initiated_by', 'progress_percentage',
        'started_at', 'last_activity_at'
    ]
    
    show_columns = [
        'definition', 'status', 'initiated_by', 'current_step',
        'progress_percentage', 'input_data', 'output_data',
        'context_variables', 'error_message', 'error_details',
        'started_at', 'completed_at', 'last_activity_at'
    ]
    
    search_columns = [
        'definition.name', 'status', 'initiated_by.username', 'current_step'
    ]
    
    base_permissions = ['can_list', 'can_show', 'can_delete']
    
    @action('suspend', lazy_gettext('Suspend Process'), lazy_gettext('Suspend running processes'), 'fa-pause')
    @permission_name('can_execute_process')
    @has_access
    def suspend_process(self, items):
        """Suspend selected running process instances."""
        if not items:
            flash(lazy_gettext('No processes selected'), 'warning')
            return redirect(self.get_redirect())
            
        suspended_count = 0
        
        try:
            for instance in items:
                if instance.status == ProcessInstanceStatus.RUNNING.value:
                    instance.status = ProcessInstanceStatus.SUSPENDED.value
                    instance.suspended_at = datetime.now(tz=timezone.utc)
                    suspended_count += 1
            
            if suspended_count > 0:
                self.datamodel.session.commit()
                flash(lazy_gettext('Suspended %(count)d process instances', count=suspended_count), 'success')
            else:
                flash(lazy_gettext('No running processes found to suspend'), 'warning')
                
        except Exception as e:
            self.datamodel.session.rollback()
            flash(lazy_gettext('Failed to suspend processes: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())
    
    @action('resume', lazy_gettext('Resume Process'), lazy_gettext('Resume suspended processes'), 'fa-play')
    @permission_name('can_execute_process')
    @has_access
    def resume_process(self, items):
        """Resume selected suspended process instances."""
        if not items:
            flash(lazy_gettext('No processes selected'), 'warning')
            return redirect(self.get_redirect())
            
        resumed_count = 0
        errors = []
        process_service = get_process_service()
        
        try:
            for instance in items:
                if instance.status == ProcessInstanceStatus.SUSPENDED.value:
                    try:
                        # Resume process execution using sync service
                        if process_service.resume_process(instance.id):
                            resumed_count += 1
                        else:
                            errors.append(f'Failed to resume process {instance.id}')
                    except Exception as e:
                        log.error(f"Failed to resume process {instance.id}: {str(e)}")
                        errors.append(f'Failed to resume process {instance.id}: {str(e)}')
            
            if resumed_count > 0:
                flash(lazy_gettext('Resumed %(count)d process instances', count=resumed_count), 'success')
            
            for error in errors:
                flash(error, 'error')
                
        except Exception as e:
            flash(lazy_gettext('Failed to resume processes: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())
    
    @action('cancel', lazy_gettext('Cancel Process'), lazy_gettext('Cancel running/suspended processes'), 'fa-stop')
    @permission_name('can_execute_process')
    @has_access
    def cancel_process(self, items):
        """Cancel selected process instances."""
        if not items:
            flash(lazy_gettext('No processes selected'), 'warning')
            return redirect(self.get_redirect())
            
        cancelled_count = 0
        
        try:
            for instance in items:
                if instance.status in [ProcessInstanceStatus.RUNNING.value, 
                                     ProcessInstanceStatus.SUSPENDED.value]:
                    instance.status = ProcessInstanceStatus.CANCELLED.value
                    instance.completed_at = datetime.now(tz=timezone.utc)
                    cancelled_count += 1
            
            if cancelled_count > 0:
                self.datamodel.session.commit()
                flash(lazy_gettext('Cancelled %(count)d process instances', count=cancelled_count), 'success')
            else:
                flash(lazy_gettext('No active processes found to cancel'), 'warning')
                
        except Exception as e:
            self.datamodel.session.rollback()
            flash(lazy_gettext('Failed to cancel processes: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())
    
    @expose('/monitor/<int:instance_id>')
    @permission_name('can_show')
    @has_access
    def monitor(self, instance_id):
        """Real-time process monitoring interface."""
        instance = self.datamodel.get(instance_id)
        if not instance:
            flash(lazy_gettext('Process instance not found'), 'error')
            return redirect(self.get_redirect())
            
        # Get process steps for timeline using datamodel for security
        step_view = ProcessStepView()
        steps = step_view.datamodel.get_related_obj(
            ProcessStep, 'instance_id', instance_id
        )
        
        return self.render_template(
            'process/monitor.html',
            instance=instance,
            steps=steps,
            definition=instance.definition
        )


class ProcessStepView(ModelView):
    """View for managing process steps."""
    
    datamodel = SQLAInterface(ProcessStep)
    
    list_columns = [
        'instance.definition.name', 'node_id', 'node_type', 'status',
        'started_at', 'completed_at'
    ]
    
    show_columns = [
        'instance', 'node_id', 'node_type', 'status',
        'input_data', 'output_data', 'configuration',
        'error_message', 'error_details', 'retry_count',
        'started_at', 'completed_at'
    ]
    
    search_columns = [
        'instance.definition.name', 'node_id', 'node_type', 'status'
    ]
    
    base_permissions = ['can_list', 'can_show']
    
    @action('retry', lazy_gettext('Retry Step'), lazy_gettext('Retry failed process steps'), 'fa-refresh')
    @permission_name('can_edit_process_step')
    @has_access
    def retry_step(self, items):
        """Retry selected failed process steps."""
        if not items:
            flash('No steps selected', 'warning')
            return redirect(self.get_redirect())
            
        retried_count = 0
        errors = []
        
        try:
            for step in items:
                if step.status == ProcessStepStatus.FAILED.value:
                    try:
                        # Trigger async retry
                        retry_step_async.delay(step.id)
                        retried_count += 1
                    except Exception as e:
                        log.error(f"Failed to retry step {step.id}: {str(e)}")
                        errors.append(f'Failed to retry step {step.id}: {str(e)}')
            
            if retried_count > 0:
                flash(lazy_gettext('Triggered retry for %(count)d failed steps', count=retried_count), 'success')
            else:
                flash(lazy_gettext('No failed steps found to retry'), 'warning')
            
            for error in errors:
                flash(error, 'error')
                
        except Exception as e:
            flash(lazy_gettext('Failed to retry steps: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())


class ApprovalRequestView(ModelView):
    """View for managing approval requests."""
    
    datamodel = SQLAInterface(ApprovalRequest)
    
    list_columns = [
        'step.instance.definition.name', 'approver', 'status',
        'requested_at', 'responded_at'
    ]
    
    show_columns = [
        'step', 'approver', 'status', 'priority',
        'approval_data', 'response_data', 'notes',
        'requested_at', 'responded_at', 'expires_at'
    ]
    
    search_columns = [
        'step.instance.definition.name', 'approver.username', 'status'
    ]
    
    base_permissions = ['can_list', 'can_show']
    
    @action('approve', lazy_gettext('Approve Request'), lazy_gettext('Approve selected requests'), 'fa-check')
    @permission_name('can_approve_process')
    @has_access
    def approve_request(self, items):
        """Approve selected approval requests."""
        if not items:
            flash('No requests selected', 'warning')
            return redirect(self.get_redirect())
            
        approved_count = 0
        errors = []
        process_service = get_process_service()
        
        try:
            for request in items:
                if request.status == ApprovalStatus.PENDING.value:
                    try:
                        request.status = ApprovalStatus.APPROVED.value
                        request.responded_at = datetime.now(tz=timezone.utc)
                        request.response_data = {'approved_by': g.user.username if g.user else 'system'}
                        
                        # Continue process execution
                        step = request.step
                        step.mark_completed({'approval_result': 'approved'})
                        
                        # Continue process using sync service
                        process_service.continue_from_step(step.instance, step.node_id)
                        
                        approved_count += 1
                        
                    except Exception as e:
                        log.error(f"Failed to approve request {request.id}: {str(e)}")
                        errors.append(f'Failed to approve request {request.id}: {str(e)}')
            
            if approved_count > 0:
                self.datamodel.session.commit()
                flash(lazy_gettext('Approved %(count)d requests', count=approved_count), 'success')
            
            for error in errors:
                flash(error, 'error')
                
        except Exception as e:
            self.datamodel.session.rollback()
            flash(lazy_gettext('Failed to approve requests: %(error)s', error=str(e)), 'error')
            
        return redirect(self.get_redirect())


class ProcessApi(ModelRestApi):
    """REST API for process definitions."""
    
    resource_name = 'process'
    datamodel = SQLAInterface(ProcessDefinition)
    
    class_permission_name = 'ProcessDefinition'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'post': 'can_add',
        'put': 'can_edit',
        'delete': 'can_delete'
    }
    
    list_columns = [
        'id', 'name', 'description', 'version', 'category', 'status',
        'created_by.username', 'created_at'
    ]
    
    show_columns = [
        'id', 'name', 'description', 'version', 'category', 'status',
        'process_graph', 'variables', 'configuration',
        'created_by.username', 'created_at', 'updated_at'
    ]
    
    add_columns = [
        'name', 'description', 'version', 'category',
        'process_graph', 'variables', 'configuration'
    ]
    
    edit_columns = add_columns
    
    @expose('/deploy/<int:definition_id>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def deploy_definition(self, definition_id):
        """Deploy a process definition."""
        definition = self.datamodel.get(definition_id)
        if not definition:
            return self.response_404()
            
        if definition.status != 'draft':
            return self.response_400(message=lazy_gettext('Only draft processes can be deployed'))
        
        try:
            # Validate process definition before deployment
            if definition.process_graph:
                ProcessValidator.validate_process_definition({
                    'name': definition.name,
                    'definition': definition.process_graph,
                    'description': definition.description or ''
                })
            
            definition.status = 'active'
            definition.deployed_at = datetime.now(tz=timezone.utc)
            self.datamodel.session.commit()
            
            return self.response(200, message='Process deployed successfully')
            
        except ValidationError as e:
            return self.response_400(message=f'Validation failed: {str(e)}')
        except Exception as e:
            log.error(f"Failed to deploy process: {str(e)}")
            self.datamodel.session.rollback()
            return self.response_400(message=f'Failed to deploy process: {str(e)}')
    
    @expose('/start/<int:definition_id>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def start_process(self, definition_id):
        """Start a new process instance."""
        definition = self.datamodel.get(definition_id)
        if not definition:
            return self.response_404()
            
        if definition.status != 'active':
            return self.response_400(message=lazy_gettext('Process is not active'))
        
        # Validate request format
        if not request.is_json:
            return self.response_400(message=lazy_gettext('Request must be JSON'))
        
        try:
            data = request.get_json() or {}
            input_data = data.get('input_data', {})
        except Exception:
            return self.response_400(message=lazy_gettext('Invalid JSON format'))
            
        try:
            process_service = get_process_service()
            instance = process_service.start_process(
                definition_id=definition_id,
                input_data=input_data,
                initiated_by=g.user.id if g.user else None
            )
            
            return self.response(201, **{
                API_RESULT_RES_KEY: {
                    'instance_id': instance.id,
                    'status': instance.status
                },
                'message': lazy_gettext('Process started successfully')
            })
            
        except Exception as e:
            log.error(f"Failed to start process: {str(e)}")
            return self.response_400(message=lazy_gettext('Failed to start process: %(error)s', error=str(e)))
    
    @expose('/graph/<int:definition_id>', methods=['PUT'])
    @protect()
    @safe
    @has_access_api
    def update_process_graph(self, definition_id):
        """Update process definition graph from designer."""
        definition = self.datamodel.get(definition_id)
        if not definition:
            return self.response_404()
            
        # Check if user can edit this definition
        if definition.status not in ['draft', 'inactive']:
            return self.response_400(message=lazy_gettext('Cannot edit active or deployed processes'))
        
        # Validate request format
        if not request.is_json:
            return self.response_400(message=lazy_gettext('Request must be JSON'))
        
        try:
            data = request.get_json()
            if not data:
                return self.response_400(message=lazy_gettext('Invalid JSON payload'))
            
            if 'process_graph' not in data:
                return self.response_400(message=lazy_gettext('Missing process_graph in request'))
            
            process_graph = data['process_graph']
            
            # Validate process_graph structure
            if not isinstance(process_graph, dict):
                return self.response_400(message=lazy_gettext('Process graph must be a JSON object'))
            
            # Validate required graph components
            if 'nodes' not in process_graph:
                return self.response_400(message=lazy_gettext('Process graph missing nodes array'))
            
            if 'edges' not in process_graph:
                return self.response_400(message=lazy_gettext('Process graph missing edges array'))
            
            if not isinstance(process_graph['nodes'], list):
                return self.response_400(message=lazy_gettext('Process graph nodes must be an array'))
            
            if not isinstance(process_graph['edges'], list):
                return self.response_400(message=lazy_gettext('Process graph edges must be an array'))
            
            # Basic size validation to prevent abuse
            if len(process_graph['nodes']) > 1000:
                return self.response_400(message=lazy_gettext('Too many nodes in process graph (max 1000)'))
            
            if len(process_graph['edges']) > 2000:
                return self.response_400(message=lazy_gettext('Too many edges in process graph (max 2000)'))
            
            # Validate graph structure before saving
            if process_graph:
                try:
                    ProcessValidator.validate_process_definition({
                        'nodes': process_graph.get('nodes', []),
                        'edges': process_graph.get('edges', [])
                    })
                except Exception as validation_error:
                    return self.response_400(message=lazy_gettext('Process validation failed: %(error)s', error=str(validation_error)))
            
            # Update the process graph
            definition.process_graph = process_graph
            definition.updated_at = datetime.now(tz=timezone.utc)
            
            try:
                self.datamodel.edit(definition)
                
                log.info(f"Process graph updated for definition {definition_id} by user {g.user.id if g.user else 'unknown'}")
                
                return self.response(200, **{
                    API_RESULT_RES_KEY: {
                        'definition_id': definition.id,
                        'updated_at': definition.updated_at.isoformat()
                    },
                    'message': lazy_gettext('Process graph updated successfully')
                })
                
            except Exception as save_error:
                self.datamodel.session.rollback()
                log.error(f"Failed to save process graph: {str(save_error)}")
                return self.response_400(message=lazy_gettext('Failed to save process graph: %(error)s', error=str(save_error)))
                
        except Exception as e:
            log.error(f"Failed to update process graph: {str(e)}")
            return self.response_400(message=lazy_gettext('Failed to update process graph: %(error)s', error=str(e)))
    
    @expose('/validate', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def validate_process_graph(self):
        """Validate process graph without saving."""
        if not request.is_json:
            return self.response_400(message=lazy_gettext('Request must be JSON'))
        
        try:
            data = request.get_json()
            if not data or 'process_graph' not in data:
                return self.response_400(message=lazy_gettext('Missing process_graph in request'))
            
            process_graph = data['process_graph']
            
            # Validate graph structure
            validation_result = ProcessValidator.validate_process_definition({
                'nodes': process_graph.get('nodes', []),
                'edges': process_graph.get('edges', [])
            })
            
            return self.response(200, **{
                API_RESULT_RES_KEY: {
                    'is_valid': validation_result.get('is_valid', True),
                    'errors': validation_result.get('errors', []),
                    'warnings': validation_result.get('warnings', [])
                },
                'message': lazy_gettext('Process validation completed')
            })
            
        except Exception as e:
            log.error(f"Failed to validate process graph: {str(e)}")
            return self.response_400(message=lazy_gettext('Validation failed: %(error)s', error=str(e)))


class ProcessInstanceApi(ModelRestApi):
    """REST API for process instances."""
    
    resource_name = 'process_instance'
    datamodel = SQLAInterface(ProcessInstance)
    
    class_permission_name = 'ProcessInstance'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'delete': 'can_delete'
    }
    
    list_columns = [
        'id', 'definition.name', 'status', 'initiated_by.username',
        'progress_percentage', 'started_at', 'last_activity_at'
    ]
    
    show_columns = [
        'id', 'definition.name', 'status', 'initiated_by.username',
        'current_step', 'progress_percentage', 'input_data', 'output_data',
        'context_variables', 'error_message', 'error_details',
        'started_at', 'completed_at', 'last_activity_at'
    ]
    
    @expose('/suspend/<int:instance_id>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def suspend_instance(self, instance_id):
        """Suspend a running process instance."""
        instance = self.datamodel.get(instance_id)
        if not instance:
            return self.response_404()
            
        if instance.status != ProcessInstanceStatus.RUNNING.value:
            return self.response_400(message='Process is not running')
            
        instance.status = ProcessInstanceStatus.SUSPENDED.value
        instance.suspended_at = datetime.now(tz=timezone.utc)
        self.datamodel.session.commit()
        
        return self.response(200, message=lazy_gettext('Process suspended successfully'))
    
    @expose('/resume/<int:instance_id>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def resume_instance(self, instance_id):
        """Resume a suspended process instance."""
        instance = self.datamodel.get(instance_id)
        if not instance:
            return self.response_404()
            
        if instance.status != ProcessInstanceStatus.SUSPENDED.value:
            return self.response_400(message='Process is not suspended')
            
        try:
            process_service = get_process_service()
            if process_service.resume_process(instance_id):
                return self.response(200, message=lazy_gettext('Process resumed successfully'))
            else:
                return self.response_400(message='Failed to resume process')
            
        except Exception as e:
            log.error(f"Failed to resume process: {str(e)}")
            return self.response_400(f'Failed to resume process: {str(e)}')
    
    @expose('/cancel/<int:instance_id>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def cancel_instance(self, instance_id):
        """Cancel a process instance."""
        instance = self.datamodel.get(instance_id)
        if not instance:
            return self.response_404()
            
        if instance.status not in [ProcessInstanceStatus.RUNNING.value, 
                                 ProcessInstanceStatus.SUSPENDED.value]:
            return self.response_400(message='Process cannot be cancelled in current status')
            
        instance.status = ProcessInstanceStatus.CANCELLED.value
        instance.completed_at = datetime.now(tz=timezone.utc)
        self.datamodel.session.commit()
        
        return self.response(200, message=lazy_gettext('Process cancelled successfully'))
    
    @expose('/steps/<int:instance_id>', methods=['GET'])
    @protect()
    @safe
    @has_access_api
    def get_instance_steps(self, instance_id):
        """Get all steps for a process instance with optimized queries."""
        instance = self.datamodel.get(instance_id)
        if not instance:
            return self.response_404()
            
        # Get process steps with optimized query and eager loading
        from sqlalchemy.orm import selectinload
        from sqlalchemy import and_
        from flask_appbuilder.models.tenant_context import get_current_tenant_id
        
        tenant_id = get_current_tenant_id()
        query_conditions = [ProcessStep.instance_id == instance_id]
        if tenant_id:
            query_conditions.append(ProcessStep.tenant_id == tenant_id)
        
        steps = db.session.query(ProcessStep).options(
            selectinload(ProcessStep.instance),
            selectinload(ProcessStep.assigned_user)
        ).filter(and_(*query_conditions)).order_by(ProcessStep.step_order).all()
        
        step_data = []
        for step in steps:
            step_data.append({
                'id': step.id,
                'node_id': step.node_id,
                'node_type': step.node_type,
                'status': step.status,
                'started_at': step.started_at.isoformat() if step.started_at else None,
                'completed_at': step.completed_at.isoformat() if step.completed_at else None,
                'error_message': step.error_message,
                'retry_count': step.retry_count,
                'assigned_user_id': step.assigned_user_id,
                'step_order': step.step_order
            })
            
        return self.response(200, result=step_data)


class ProcessMetricsApi(BaseApi):
    """API for process analytics and metrics."""
    
    resource_name = 'process_metrics'
    
    @expose('/dashboard', methods=['GET'])
    @protect()
    @safe
    @has_access_api
    def get_dashboard_metrics(self):
        """Get metrics for process dashboard."""
        try:
            tenant_id = get_current_tenant_id()
            
            # Removed inefficient multiple separate queries - now using optimized approach
            
            # Use optimized single queries instead of multiple separate queries
            dashboard_data = self._get_optimized_dashboard_metrics(tenant_id)
            
            return self.response(200, result={
                'summary': {
                    'total_definitions': dashboard_data['total_definitions'],
                    'active_definitions': dashboard_data['active_definitions'],
                    'running_instances': dashboard_data['running_instances'],
                    'completed_today': dashboard_data['completed_today'],
                    'failed_today': dashboard_data['failed_today']
                },
                'metrics': dashboard_data['recent_metrics']
            })
            
        except Exception as e:
            log.error(f"Failed to get dashboard metrics: {str(e)}")
            return self.response_400(f'Failed to get metrics: {str(e)}')
    
    def _get_optimized_dashboard_metrics(self, tenant_id: Optional[str]) -> Dict[str, Any]:
        """Get dashboard metrics with optimized database queries."""
        from sqlalchemy import func, and_, case
        
        # Build base query conditions
        base_conditions = []
        if tenant_id:
            base_conditions.append(ProcessDefinition.tenant_id == tenant_id)
        
        # Single optimized query for definition counts using aggregation
        definition_counts = db.session.query(
            func.count(ProcessDefinition.id).label('total_definitions'),
            func.sum(case([(ProcessDefinition.status == 'active', 1)], else_=0)).label('active_definitions')
        ).filter(and_(*base_conditions) if base_conditions else True).first()
        
        # Single optimized query for instance counts with date filtering
        today = datetime.now(tz=timezone.utc).date()
        instance_conditions = []
        if tenant_id:
            instance_conditions.append(ProcessInstance.tenant_id == tenant_id)
        
        instance_counts = db.session.query(
            func.sum(case([(ProcessInstance.status == ProcessInstanceStatus.RUNNING.value, 1)], else_=0)).label('running_instances'),
            func.sum(case([
                (and_(ProcessInstance.status == ProcessInstanceStatus.COMPLETED.value, 
                     func.date(ProcessInstance.completed_at) == today), 1)
            ], else_=0)).label('completed_today'),
            func.sum(case([
                (and_(ProcessInstance.status == ProcessInstanceStatus.FAILED.value,
                     func.date(ProcessInstance.completed_at) == today), 1)
            ], else_=0)).label('failed_today')
        ).filter(and_(*instance_conditions) if instance_conditions else True).first()
        
        # Optimized metrics query with batch loading
        cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=7)
        metric_conditions = [ProcessMetric.metric_date >= cutoff_date]
        if tenant_id:
            metric_conditions.append(ProcessMetric.tenant_id == tenant_id)
        
        recent_metrics = db.session.query(ProcessMetric).filter(
            and_(*metric_conditions)
        ).order_by(ProcessMetric.metric_date.desc()).all()
        
        # Process metrics data efficiently
        metrics_data = {}
        for metric in recent_metrics:
            if metric.metric_type not in metrics_data:
                metrics_data[metric.metric_type] = []
            metrics_data[metric.metric_type].append({
                'date': metric.metric_date.isoformat(),
                'value': float(metric.value)
            })
        
        return {
            'total_definitions': int(definition_counts.total_definitions or 0),
            'active_definitions': int(definition_counts.active_definitions or 0),
            'running_instances': int(instance_counts.running_instances or 0),
            'completed_today': int(instance_counts.completed_today or 0),
            'failed_today': int(instance_counts.failed_today or 0),
            'recent_metrics': metrics_data
        }
    
    @expose('/performance/<int:definition_id>', methods=['GET'])
    @protect()
    @safe
    @has_access_api
    def get_process_performance(self, definition_id):
        """Get performance metrics for a specific process definition."""
        try:
            tenant_id = get_current_tenant_id()
            
            # Verify definition exists and belongs to tenant using datamodel
            definition_datamodel = SQLAInterface(ProcessDefinition)
            definition = definition_datamodel.get(definition_id)
            
            if not definition or (tenant_id and getattr(definition, 'tenant_id', None) != tenant_id):
                return self.response_404()
            
            # Get performance data for last 30 days using datamodel
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=30)
            instance_datamodel = SQLAInterface(ProcessInstance)
            
            filters = [
                ('definition_id', '==', definition_id),
                ('started_at', '>=', cutoff_date)
            ]
            if tenant_id:
                filters.append(('tenant_id', '==', tenant_id))
            
            _, instances = instance_datamodel.query(filters=filters)
            
            performance_data = {
                'total_instances': len(instances),
                'completed': len([i for i in instances if i.status == ProcessInstanceStatus.COMPLETED.value]),
                'failed': len([i for i in instances if i.status == ProcessInstanceStatus.FAILED.value]),
                'running': len([i for i in instances if i.status == ProcessInstanceStatus.RUNNING.value]),
                'average_duration': None,
                'success_rate': 0
            }
            
            # Calculate average duration for completed processes
            completed_instances = [i for i in instances 
                                 if i.status == ProcessInstanceStatus.COMPLETED.value and i.completed_at]
            
            if completed_instances:
                total_duration = sum(
                    (i.completed_at - i.started_at).total_seconds() 
                    for i in completed_instances
                )
                performance_data['average_duration'] = total_duration / len(completed_instances)
                
            # Calculate success rate
            if instances:
                performance_data['success_rate'] = performance_data['completed'] / len(instances) * 100
                
            return self.response(200, result=performance_data)
            
        except Exception as e:
            log.error(f"Failed to get process performance: {str(e)}")
            return self.response_400(f'Failed to get performance metrics: {str(e)}')


# =======================================
# Subprocess Management Views and APIs
# =======================================

class SubprocessDefinitionSchema(SQLAlchemyAutoSchema):
    """Schema for SubprocessDefinition serialization."""
    
    class Meta:
        model = SubprocessDefinition
        load_instance = True
        include_relationships = True
        
    definition = fields.Raw()
    parameters = fields.Raw()


class SubprocessDefinitionView(ModelView):
    """Management view for subprocess definitions."""
    
    datamodel = SQLAInterface(SubprocessDefinition)
    
    list_columns = ['name', 'subprocess_type', 'process_definition', 'version', 'is_active', 'created_at']
    show_columns = ['name', 'description', 'subprocess_type', 'process_definition', 'definition_version', 
                   'version', 'definition', 'parameters', 'is_active', 'created_at', 'updated_at']
    search_columns = ['name', 'subprocess_type', 'description']
    edit_columns = ['name', 'description', 'subprocess_type', 'process_definition', 'definition', 
                   'parameters', 'is_active']
    add_columns = ['name', 'description', 'subprocess_type', 'process_definition', 'definition', 
                  'parameters', 'is_active']
    
    label_columns = {
        'name': lazy_gettext('Name'),
        'description': lazy_gettext('Description'), 
        'subprocess_type': lazy_gettext('Type'),
        'process_definition': lazy_gettext('Parent Process'),
        'definition': lazy_gettext('Definition'),
        'parameters': lazy_gettext('Parameters'),
        'is_active': lazy_gettext('Active')
    }
    
    @expose('/design/<int:pk>')
    @has_access
    def design_subprocess(self, pk):
        """Open subprocess designer interface."""
        subprocess_def = self.datamodel.get(pk, self._base_filters)
        if not subprocess_def:
            flash(lazy_gettext('Subprocess definition not found'), 'error')
            return redirect(self.get_redirect())
            
        return self.render_template(
            'subprocess/designer.html',
            subprocess_definition=subprocess_def,
            subprocess_graph=subprocess_def.definition or {'nodes': [], 'edges': []}
        )


class SubprocessDefinitionApi(ModelRestApi):
    """REST API for subprocess definitions."""
    
    resource_name = 'subprocess_definition'
    datamodel = SQLAInterface(SubprocessDefinition)
    
    class_permission_name = 'SubprocessDefinition'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'post': 'can_add',
        'put': 'can_edit',
        'delete': 'can_delete'
    }
    
    list_columns = ['id', 'name', 'subprocess_type', 'process_definition_id', 'version', 'is_active']
    show_columns = ['id', 'name', 'description', 'subprocess_type', 'process_definition_id', 
                   'definition_version', 'version', 'definition', 'parameters', 'is_active']
    add_columns = ['name', 'description', 'subprocess_type', 'process_definition_id', 'definition', 
                  'parameters', 'is_active']
    edit_columns = ['name', 'description', 'subprocess_type', 'process_definition_id', 'definition', 
                   'parameters', 'is_active']
    
    @expose('/execute/<int:pk>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def execute_subprocess(self, pk):
        """Execute a subprocess definition."""
        try:
            subprocess_def = self.datamodel.get(pk, self._base_filters)
            if not subprocess_def:
                return self.response_404()
            
            input_data = request.json or {}
            
            # Create subprocess execution record
            execution = SubprocessExecution(
                subprocess_definition_id=subprocess_def.id,
                subprocess_type=subprocess_def.subprocess_type,
                status='running',
                started_at=datetime.now(tz=timezone.utc),
                input_data=input_data,
                tenant_id=get_current_tenant_id()
            )
            db.session.add(execution)
            db.session.commit()
            
            # Execute using subprocess executor
            from .engine.executors import SubprocessExecutor
            from .engine.process_engine import ProcessEngine
            
            engine = ProcessEngine()
            executor = SubprocessExecutor(engine)
            
            # Create a mock parent instance for execution context
            parent_instance = ProcessInstance(
                process_definition_id=subprocess_def.parent_process_id,
                name=f"Subprocess Test - {subprocess_def.name}",
                status=ProcessInstanceStatus.RUNNING.value,
                tenant_id=get_current_tenant_id()
            )
            
            if subprocess_def.subprocess_type == 'embedded':
                # For synchronous execution in Flask views, use simplified result
                result = {
                    'message': 'Embedded subprocess execution initiated',
                    'execution_id': execution.id,
                    'subprocess_type': 'embedded'
                }
            else:
                result = {'message': 'Subprocess execution started', 'execution_id': execution.id}
            
            return self.response(200, result={
                'execution_id': execution.id,
                'status': 'started',
                'result': result
            })
            
        except Exception as e:
            log.error(f"Failed to execute subprocess: {str(e)}")
            return self.response_400(f'Execution failed: {str(e)}')


class SubprocessExecutionView(ModelView):
    """Management view for subprocess executions."""
    
    datamodel = SQLAInterface(SubprocessExecution)
    
    list_columns = ['subprocess_definition', 'parent_instance', 'subprocess_type', 'status', 'started_at', 'completed_at']
    show_columns = ['subprocess_definition', 'parent_instance', 'called_instance', 'subprocess_type', 'status', 
                   'started_at', 'completed_at', 'input_data', 'output_data', 'error_message', 'event_configuration']
    search_columns = ['subprocess_type', 'status']
    
    label_columns = {
        'subprocess_definition': lazy_gettext('Subprocess'),
        'parent_instance': lazy_gettext('Parent Instance'),
        'called_instance': lazy_gettext('Called Instance'),
        'subprocess_type': lazy_gettext('Type'),
        'status': lazy_gettext('Status'),
        'input_data': lazy_gettext('Input Data'),
        'output_data': lazy_gettext('Output Data'),
        'error_message': lazy_gettext('Error'),
        'event_configuration': lazy_gettext('Event Config')
    }


# =======================================
# Pool and Lane Management Views and APIs  
# =======================================

class ProcessPoolSchema(SQLAlchemyAutoSchema):
    """Schema for ProcessPool serialization."""
    
    class Meta:
        model = ProcessPool
        load_instance = True
        include_relationships = True


class ProcessPoolView(ModelView):
    """Management view for process pools."""
    
    datamodel = SQLAInterface(ProcessPool)
    
    list_columns = ['name', 'pool_type', 'organization', 'is_active', 'created_at']
    show_columns = ['name', 'description', 'pool_type', 'organization', 'configuration', 
                   'is_active', 'lanes', 'created_at', 'updated_at']
    search_columns = ['name', 'pool_type', 'organization']
    edit_columns = ['name', 'description', 'pool_type', 'organization', 'configuration', 'is_active']
    add_columns = ['name', 'description', 'pool_type', 'organization', 'configuration', 'is_active']
    
    label_columns = {
        'name': lazy_gettext('Pool Name'),
        'description': lazy_gettext('Description'),
        'pool_type': lazy_gettext('Pool Type'),
        'organization': lazy_gettext('Organization'),
        'configuration': lazy_gettext('Configuration'),
        'is_active': lazy_gettext('Active'),
        'lanes': lazy_gettext('Lanes')
    }
    
    @action('assign_roles', lazy_gettext('Assign Roles'), lazy_gettext('Assign roles to pool lanes'))
    def assign_roles_action(self, items):
        """Bulk assign roles to pool lanes."""
        if not items:
            flash(lazy_gettext('No pools selected'), 'warning')
            return redirect(self.get_redirect())
        
        # Redirect to role assignment interface
        pool_ids = [str(item.id) for item in items]
        return redirect(url_for('ProcessPoolView.assign_roles_bulk', pool_ids=','.join(pool_ids)))
    
    @expose('/assign-roles/<pool_ids>')
    @has_access
    def assign_roles_bulk(self, pool_ids):
        """Bulk role assignment interface."""
        from .security.integration import pool_lane_security_manager
        
        pool_id_list = pool_ids.split(',')
        pools = []
        all_lanes = []
        
        for pool_id in pool_id_list:
            pool = self.datamodel.get(int(pool_id), self._base_filters)
            if pool:
                pools.append(pool)
                all_lanes.extend(pool.lanes)
        
        available_roles = pool_lane_security_manager.get_available_roles(get_current_tenant_id())
        
        return self.render_template(
            'pool/assign_roles.html',
            pools=pools,
            lanes=all_lanes,
            available_roles=available_roles
        )


class ProcessPoolApi(ModelRestApi):
    """REST API for process pools."""
    
    resource_name = 'process_pool'
    datamodel = SQLAInterface(ProcessPool)
    
    class_permission_name = 'ProcessPool'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show', 
        'post': 'can_add',
        'put': 'can_edit',
        'delete': 'can_delete'
    }
    
    list_columns = ['id', 'name', 'pool_type', 'organization', 'is_active']
    show_columns = ['id', 'name', 'description', 'pool_type', 'organization', 'configuration', 'is_active']
    add_columns = ['name', 'description', 'pool_type', 'organization', 'configuration', 'is_active']
    edit_columns = ['name', 'description', 'pool_type', 'organization', 'configuration', 'is_active']
    
    @expose('/lanes/<int:pk>', methods=['GET'])
    @protect()
    @safe
    @has_access_api
    def get_pool_lanes(self, pk):
        """Get lanes for a specific pool."""
        try:
            pool = self.datamodel.get(pk, self._base_filters)
            if not pool:
                return self.response_404()
            
            lanes = [{
                'id': lane.id,
                'name': lane.name,
                'assigned_role': lane.assigned_role,
                'workload_balancing': lane.workload_balancing,
                'is_active': lane.is_active
            } for lane in pool.lanes if lane.is_active]
            
            return self.response(200, result={'lanes': lanes})
            
        except Exception as e:
            log.error(f"Failed to get pool lanes: {str(e)}")
            return self.response_400(f'Failed to get lanes: {str(e)}')


class ProcessLaneSchema(SQLAlchemyAutoSchema):
    """Schema for ProcessLane serialization."""
    
    class Meta:
        model = ProcessLane
        load_instance = True
        include_relationships = True


class ProcessLaneView(ModelView):
    """Management view for process lanes."""
    
    datamodel = SQLAInterface(ProcessLane)
    
    list_columns = ['name', 'pool', 'assigned_role', 'workload_balancing', 'is_active', 'created_at']
    show_columns = ['name', 'description', 'pool', 'assigned_role', 'workload_balancing', 
                   'configuration', 'is_active', 'created_at', 'updated_at']
    search_columns = ['name', 'assigned_role', 'workload_balancing']
    edit_columns = ['name', 'description', 'pool', 'assigned_role', 'workload_balancing', 
                   'configuration', 'is_active']
    add_columns = ['name', 'description', 'pool', 'assigned_role', 'workload_balancing', 
                  'configuration', 'is_active']
    
    label_columns = {
        'name': lazy_gettext('Lane Name'),
        'description': lazy_gettext('Description'),
        'pool': lazy_gettext('Pool'),
        'assigned_role': lazy_gettext('Assigned Role'),
        'workload_balancing': lazy_gettext('Workload Balancing'),
        'configuration': lazy_gettext('Configuration'),
        'is_active': lazy_gettext('Active')
    }
    
    @action('test_access', lazy_gettext('Test Access'), lazy_gettext('Test user access to selected lanes'))
    def test_access_action(self, items):
        """Test user access to selected lanes."""
        from .security.integration import pool_lane_security_manager
        
        results = []
        for lane in items:
            has_access = pool_lane_security_manager.check_lane_access(lane.id)
            results.append({
                'lane': lane.name,
                'access': 'Allowed' if has_access else 'Denied',
                'role': lane.assigned_role or 'No role assigned'
            })
        
        flash(f"Access test completed for {len(results)} lanes", 'info')
        return redirect(self.get_redirect())


class ProcessLaneApi(ModelRestApi):
    """REST API for process lanes."""
    
    resource_name = 'process_lane'
    datamodel = SQLAInterface(ProcessLane)
    
    class_permission_name = 'ProcessLane'
    method_permission_name = {
        'get_list': 'can_list',
        'get': 'can_show',
        'post': 'can_add', 
        'put': 'can_edit',
        'delete': 'can_delete'
    }
    
    list_columns = ['id', 'name', 'pool_id', 'assigned_role', 'workload_balancing', 'is_active']
    show_columns = ['id', 'name', 'description', 'pool_id', 'assigned_role', 'workload_balancing', 
                   'configuration', 'is_active']
    add_columns = ['name', 'description', 'pool_id', 'assigned_role', 'workload_balancing', 
                  'configuration', 'is_active']
    edit_columns = ['name', 'description', 'pool_id', 'assigned_role', 'workload_balancing', 
                   'configuration', 'is_active']
    
    @expose('/assign-role/<int:pk>', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def assign_role(self, pk):
        """Assign a role to a lane."""
        try:
            from .security.integration import pool_lane_security_manager
            
            lane = self.datamodel.get(pk, self._base_filters)
            if not lane:
                return self.response_404()
            
            data = request.json or {}
            role_name = data.get('role_name')
            
            if not role_name:
                return self.response_400('Role name is required')
            
            success = pool_lane_security_manager.assign_role_to_lane(lane.id, role_name)
            
            if success:
                return self.response(200, result={
                    'message': f'Role {role_name} assigned to lane {lane.name}',
                    'lane_id': lane.id,
                    'assigned_role': role_name
                })
            else:
                return self.response_400('Failed to assign role')
                
        except Exception as e:
            log.error(f"Failed to assign role: {str(e)}")
            return self.response_400(f'Role assignment failed: {str(e)}')
    
    @expose('/accessible', methods=['GET'])
    @protect()
    @safe
    @has_access_api
    def get_accessible_lanes(self):
        """Get lanes accessible to current user."""
        try:
            from .security.integration import pool_lane_security_manager
            
            pool_id = request.args.get('pool_id', type=int)
            accessible_lanes = pool_lane_security_manager.get_user_accessible_lanes(pool_id)
            
            return self.response(200, result={'accessible_lanes': accessible_lanes})
            
        except Exception as e:
            log.error(f"Failed to get accessible lanes: {str(e)}")
            return self.response_400(f'Failed to get accessible lanes: {str(e)}')


# =======================================
# Event Subprocess Management API
# =======================================

class EventSubprocessApi(BaseApi):
    """API for managing event-triggered subprocesses."""
    
    resource_name = 'event_subprocess'
    
    @expose('/trigger', methods=['POST'])
    @protect()
    @safe
    @has_access_api
    def trigger_event(self):
        """Trigger event subprocesses by event name."""
        try:
            from .engine.executors import SubprocessExecutor
            from .engine.process_engine import ProcessEngine
            
            data = request.json or {}
            event_name = data.get('event_name')
            event_data = data.get('event_data', {})
            tenant_id = data.get('tenant_id', get_current_tenant_id())
            
            if not event_name:
                return self.response_400('Event name is required')
            
            # For synchronous Flask views, create a simplified event trigger response
            # The actual async processing will be handled by background tasks
            from .tasks import execute_node_async
            
            # Schedule background event processing
            execute_node_async.delay('event_subprocess_trigger', {
                'event_name': event_name,
                'event_data': event_data,
                'tenant_id': tenant_id
            })
            
            # Return immediate response
            results = [{
                'status': 'event_triggered',
                'event_name': event_name,
                'processing': 'background'
            }]
            
            return self.response(200, result={
                'event_name': event_name,
                'triggered_subprocesses': len(results),
                'results': results
            })
            
        except Exception as e:
            log.error(f"Failed to trigger event subprocesses: {str(e)}")
            return self.response_400(f'Event trigger failed: {str(e)}')
    
    @expose('/waiting', methods=['GET'])
    @protect()
    @safe
    @has_access_api
    def get_waiting_subprocesses(self):
        """Get list of subprocesses waiting for events."""
        try:
            tenant_id = get_current_tenant_id()
            
            datamodel = SQLAInterface(SubprocessExecution)
            filters = [
                ('status', '==', 'waiting_for_event'),
                ('subprocess_type', '==', 'event')
            ]
            if tenant_id:
                filters.append(('tenant_id', '==', tenant_id))
            
            _, waiting_executions = datamodel.query(filters=filters)
            
            results = []
            for execution in waiting_executions:
                event_config = execution.event_configuration or {}
                results.append({
                    'execution_id': execution.id,
                    'subprocess_definition_id': execution.subprocess_definition_id,
                    'parent_instance_id': execution.parent_instance_id,
                    'event_name': event_config.get('event_name'),
                    'event_type': event_config.get('event_type'),
                    'waiting_since': execution.started_at.isoformat() if execution.started_at else None,
                    'timeout_seconds': event_config.get('timeout_seconds')
                })
            
            return self.response(200, result={'waiting_subprocesses': results})
            
        except Exception as e:
            log.error(f"Failed to get waiting subprocesses: {str(e)}")
            return self.response_400(f'Failed to get waiting subprocesses: {str(e)}')