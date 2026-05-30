"""
Process State Machine.

Manages process and step state transitions with validation,
event handling, and state persistence for robust process execution.
"""

import logging
import asyncio
from typing import Dict, List, Set, Tuple, Optional, Callable, Any
from enum import Enum
from datetime import datetime, timezone
import threading

from ..models.process_models import (
    ProcessInstance, ProcessStep, ProcessInstanceStatus, ProcessStepStatus
)

log = logging.getLogger(__name__)


class StateTransitionError(Exception):
    """Exception raised for invalid state transitions."""
    pass


class ProcessStateMachine:
    """
    State machine for managing process instance and step state transitions.
    
    Provides validation, event handling, and audit trails for all state changes
    to ensure process integrity and consistency.
    """
    
    def __init__(self):
        """Initialize the state machine with valid transitions."""
        self._lock = threading.RLock()
        
        # Define valid process instance state transitions
        self.process_transitions = {
            ProcessInstanceStatus.RUNNING.value: {
                ProcessInstanceStatus.COMPLETED.value,
                ProcessInstanceStatus.FAILED.value,
                ProcessInstanceStatus.SUSPENDED.value,
                ProcessInstanceStatus.CANCELLED.value
            },
            ProcessInstanceStatus.SUSPENDED.value: {
                ProcessInstanceStatus.RUNNING.value,
                ProcessInstanceStatus.CANCELLED.value,
                ProcessInstanceStatus.FAILED.value
            },
            ProcessInstanceStatus.COMPLETED.value: set(),  # Terminal state
            ProcessInstanceStatus.FAILED.value: {
                ProcessInstanceStatus.RUNNING.value  # Allow restart
            },
            ProcessInstanceStatus.CANCELLED.value: {
                ProcessInstanceStatus.RUNNING.value  # Allow restart
            }
        }
        
        # Define valid process step state transitions
        self.step_transitions = {
            ProcessStepStatus.PENDING.value: {
                ProcessStepStatus.RUNNING.value,
                ProcessStepStatus.SKIPPED.value,
                ProcessStepStatus.FAILED.value
            },
            ProcessStepStatus.RUNNING.value: {
                ProcessStepStatus.COMPLETED.value,
                ProcessStepStatus.FAILED.value,
                ProcessStepStatus.WAITING.value,
                ProcessStepStatus.SUSPENDED.value
            },
            ProcessStepStatus.WAITING.value: {
                ProcessStepStatus.RUNNING.value,
                ProcessStepStatus.COMPLETED.value,
                ProcessStepStatus.FAILED.value,
                ProcessStepStatus.SKIPPED.value
            },
            ProcessStepStatus.COMPLETED.value: set(),  # Terminal state
            ProcessStepStatus.FAILED.value: {
                ProcessStepStatus.PENDING.value,  # Allow retry
                ProcessStepStatus.RUNNING.value   # Allow retry
            },
            ProcessStepStatus.SKIPPED.value: set()  # Terminal state
        }
        
        # State transition hooks
        self.process_transition_hooks: Dict[Tuple[str, str], List[Callable]] = {}
        self.step_transition_hooks: Dict[Tuple[str, str], List[Callable]] = {}
        
        # State entry/exit hooks
        self.process_entry_hooks: Dict[str, List[Callable]] = {}
        self.process_exit_hooks: Dict[str, List[Callable]] = {}
        self.step_entry_hooks: Dict[str, List[Callable]] = {}
        self.step_exit_hooks: Dict[str, List[Callable]] = {}
    
    def is_valid_process_transition(self, from_status: str, to_status: str) -> bool:
        """Check if process state transition is valid."""
        with self._lock:
            if from_status not in self.process_transitions:
                return False
            
            return to_status in self.process_transitions[from_status]
    
    def is_valid_step_transition(self, from_status: str, to_status: str) -> bool:
        """Check if step state transition is valid."""
        with self._lock:
            if from_status not in self.step_transitions:
                return False
            
            return to_status in self.step_transitions[from_status]
    
    def get_valid_process_transitions(self, current_status: str) -> Set[str]:
        """Get all valid transitions from current process status."""
        with self._lock:
            return self.process_transitions.get(current_status, set()).copy()
    
    def get_valid_step_transitions(self, current_status: str) -> Set[str]:
        """Get all valid transitions from current step status."""
        with self._lock:
            return self.step_transitions.get(current_status, set()).copy()
    
    async def transition_process(self, instance: ProcessInstance, new_status: str,
                               context: Dict[str, Any] = None) -> bool:
        """
        Transition process instance to new status with validation and hooks.
        
        Args:
            instance: Process instance to transition
            new_status: Target status
            context: Additional context for the transition
        
        Returns:
            bool: True if transition was successful
        """
        with self._lock:
            old_status = instance.status
            
            # Validate transition
            if not self.is_valid_process_transition(old_status, new_status):
                raise StateTransitionError(
                    f"Invalid process transition from {old_status} to {new_status} "
                    f"for instance {instance.id}"
                )
            
            try:
                # Execute exit hooks for old status
                await self._execute_process_exit_hooks(instance, old_status, context or {})
                
                # Execute transition hooks
                await self._execute_process_transition_hooks(
                    instance, old_status, new_status, context or {}
                )
                
                # Perform the transition
                instance.status = new_status
                instance.update_activity()
                
                # Set specific timestamps based on new status
                if new_status == ProcessInstanceStatus.COMPLETED.value:
                    instance.completed_at = datetime.now(tz=timezone.utc)
                elif new_status == ProcessInstanceStatus.SUSPENDED.value:
                    instance.suspended_at = datetime.now(tz=timezone.utc)
                elif new_status == ProcessInstanceStatus.RUNNING.value:
                    instance.suspended_at = None  # Clear suspension
                
                # Execute entry hooks for new status
                await self._execute_process_entry_hooks(instance, new_status, context or {})
                
                log.info(f"Process instance {instance.id} transitioned from {old_status} to {new_status}")
                return True
                
            except Exception as e:
                log.error(f"Error during process transition: {str(e)}")
                # Rollback status change if it was made
                instance.status = old_status
                raise StateTransitionError(f"Process transition failed: {str(e)}")
    
    async def transition_step(self, step: ProcessStep, new_status: str,
                             context: Dict[str, Any] = None) -> bool:
        """
        Transition process step to new status with validation and hooks.
        
        Args:
            step: Process step to transition
            new_status: Target status
            context: Additional context for the transition
        
        Returns:
            bool: True if transition was successful
        """
        with self._lock:
            old_status = step.status
            
            # Validate transition
            if not self.is_valid_step_transition(old_status, new_status):
                raise StateTransitionError(
                    f"Invalid step transition from {old_status} to {new_status} "
                    f"for step {step.id} (node: {step.node_id})"
                )
            
            try:
                # Execute exit hooks for old status
                await self._execute_step_exit_hooks(step, old_status, context or {})
                
                # Execute transition hooks
                await self._execute_step_transition_hooks(
                    step, old_status, new_status, context or {}
                )
                
                # Perform the transition
                step.status = new_status
                
                # Set specific timestamps based on new status
                if new_status == ProcessStepStatus.RUNNING.value:
                    step.started_at = datetime.now(tz=timezone.utc)
                elif new_status in [ProcessStepStatus.COMPLETED.value, 
                                   ProcessStepStatus.FAILED.value,
                                   ProcessStepStatus.SKIPPED.value]:
                    step.completed_at = datetime.now(tz=timezone.utc)
                
                # Execute entry hooks for new status
                await self._execute_step_entry_hooks(step, new_status, context or {})
                
                log.debug(f"Process step {step.id} transitioned from {old_status} to {new_status}")
                return True
                
            except Exception as e:
                log.error(f"Error during step transition: {str(e)}")
                # Rollback status change if it was made
                step.status = old_status
                raise StateTransitionError(f"Step transition failed: {str(e)}")
    
    def register_process_transition_hook(self, from_status: str, to_status: str,
                                       hook: Callable):
        """Register hook for specific process state transition."""
        with self._lock:
            transition = (from_status, to_status)
            if transition not in self.process_transition_hooks:
                self.process_transition_hooks[transition] = []
            
            self.process_transition_hooks[transition].append(hook)
            log.debug(f"Registered process transition hook: {from_status} -> {to_status}")
    
    def register_step_transition_hook(self, from_status: str, to_status: str,
                                    hook: Callable):
        """Register hook for specific step state transition."""
        with self._lock:
            transition = (from_status, to_status)
            if transition not in self.step_transition_hooks:
                self.step_transition_hooks[transition] = []
            
            self.step_transition_hooks[transition].append(hook)
            log.debug(f"Registered step transition hook: {from_status} -> {to_status}")
    
    def register_process_entry_hook(self, status: str, hook: Callable):
        """Register hook for process status entry."""
        with self._lock:
            if status not in self.process_entry_hooks:
                self.process_entry_hooks[status] = []
            
            self.process_entry_hooks[status].append(hook)
            log.debug(f"Registered process entry hook for status: {status}")
    
    def register_process_exit_hook(self, status: str, hook: Callable):
        """Register hook for process status exit."""
        with self._lock:
            if status not in self.process_exit_hooks:
                self.process_exit_hooks[status] = []
            
            self.process_exit_hooks[status].append(hook)
            log.debug(f"Registered process exit hook for status: {status}")
    
    def register_step_entry_hook(self, status: str, hook: Callable):
        """Register hook for step status entry."""
        with self._lock:
            if status not in self.step_entry_hooks:
                self.step_entry_hooks[status] = []
            
            self.step_entry_hooks[status].append(hook)
            log.debug(f"Registered step entry hook for status: {status}")
    
    def register_step_exit_hook(self, status: str, hook: Callable):
        """Register hook for step status exit."""
        with self._lock:
            if status not in self.step_exit_hooks:
                self.step_exit_hooks[status] = []
            
            self.step_exit_hooks[status].append(hook)
            log.debug(f"Registered step exit hook for status: {status}")
    
    async def _execute_process_transition_hooks(self, instance: ProcessInstance,
                                              from_status: str, to_status: str,
                                              context: Dict[str, Any]):
        """Execute hooks for process state transition."""
        transition = (from_status, to_status)
        hooks = self.process_transition_hooks.get(transition, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance, from_status, to_status, context)
                else:
                    hook(instance, from_status, to_status, context)
            except Exception as e:
                log.error(f"Error executing process transition hook: {str(e)}")
    
    async def _execute_step_transition_hooks(self, step: ProcessStep,
                                           from_status: str, to_status: str,
                                           context: Dict[str, Any]):
        """Execute hooks for step state transition."""
        transition = (from_status, to_status)
        hooks = self.step_transition_hooks.get(transition, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(step, from_status, to_status, context)
                else:
                    hook(step, from_status, to_status, context)
            except Exception as e:
                log.error(f"Error executing step transition hook: {str(e)}")
    
    async def _execute_process_entry_hooks(self, instance: ProcessInstance,
                                         status: str, context: Dict[str, Any]):
        """Execute hooks for process status entry."""
        hooks = self.process_entry_hooks.get(status, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance, status, context)
                else:
                    hook(instance, status, context)
            except Exception as e:
                log.error(f"Error executing process entry hook: {str(e)}")
    
    async def _execute_process_exit_hooks(self, instance: ProcessInstance,
                                        status: str, context: Dict[str, Any]):
        """Execute hooks for process status exit."""
        hooks = self.process_exit_hooks.get(status, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(instance, status, context)
                else:
                    hook(instance, status, context)
            except Exception as e:
                log.error(f"Error executing process exit hook: {str(e)}")
    
    async def _execute_step_entry_hooks(self, step: ProcessStep,
                                      status: str, context: Dict[str, Any]):
        """Execute hooks for step status entry."""
        hooks = self.step_entry_hooks.get(status, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(step, status, context)
                else:
                    hook(step, status, context)
            except Exception as e:
                log.error(f"Error executing step entry hook: {str(e)}")
    
    async def _execute_step_exit_hooks(self, step: ProcessStep,
                                     status: str, context: Dict[str, Any]):
        """Execute hooks for step status exit."""
        hooks = self.step_exit_hooks.get(status, [])
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(step, status, context)
                else:
                    hook(step, status, context)
            except Exception as e:
                log.error(f"Error executing step exit hook: {str(e)}")
    
    def get_state_diagram(self) -> Dict[str, Any]:
        """Get visual representation of state machine."""
        return {
            'process_states': {
                'transitions': {
                    state: list(transitions) 
                    for state, transitions in self.process_transitions.items()
                },
                'terminal_states': [
                    state for state, transitions in self.process_transitions.items()
                    if not transitions
                ]
            },
            'step_states': {
                'transitions': {
                    state: list(transitions) 
                    for state, transitions in self.step_transitions.items()
                },
                'terminal_states': [
                    state for state, transitions in self.step_transitions.items()
                    if not transitions
                ]
            }
        }
    
    def validate_state_consistency(self, instance: ProcessInstance) -> List[str]:
        """Validate state consistency for a process instance."""
        issues = []
        
        # Check if process status is valid
        if instance.status not in self.process_transitions:
            issues.append(f"Invalid process status: {instance.status}")
        
        # Check step statuses
        for step in instance.steps:
            if step.status not in self.step_transitions:
                issues.append(f"Invalid step status: {step.status} for step {step.id}")
        
        # Check process-step consistency
        if instance.status == ProcessInstanceStatus.COMPLETED.value:
            incomplete_steps = [
                step for step in instance.steps 
                if step.status not in [ProcessStepStatus.COMPLETED.value, ProcessStepStatus.SKIPPED.value]
            ]
            if incomplete_steps:
                issues.append(f"Process marked complete but has incomplete steps: {[s.id for s in incomplete_steps]}")
        
        if instance.status == ProcessInstanceStatus.RUNNING.value:
            if not any(step.status == ProcessStepStatus.RUNNING.value for step in instance.steps):
                if not any(step.status == ProcessStepStatus.WAITING.value for step in instance.steps):
                    issues.append("Process marked as running but no steps are running or waiting")
        
        return issues