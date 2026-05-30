/**
 * Collaboration Manager
 * 
 * Main JavaScript client for real-time collaboration features.
 * Handles WebSocket communication, presence indicators, conflict resolution,
 * and real-time form synchronization.
 */

class CollaborationManager {
    constructor(options = {}) {
        // Configuration
        this.sessionId = options.sessionId;
        this.modelName = options.modelName;
        this.recordId = options.recordId;
        this.websocketUrl = options.websocketUrl || '/collaboration';
        this.userId = options.userId;
        this.username = options.username;
        this.permissions = options.permissions || ['can_edit'];
        
        // State
        this.socket = null;
        this.isConnected = false;
        this.participants = new Map();
        this.cursors = new Map();
        this.presenceIndicators = new Map();
        this.activeFields = new Set();
        this.conflictQueue = [];
        
        // Event handlers
        this.eventHandlers = new Map();
        
        // Debouncing for field changes
        this.fieldChangeTimeouts = new Map();
        this.changeDebounceMs = 500;
        
        // UI elements cache
        this.formElement = null;
        this.participantsContainer = null;
        this.conflictModal = null;
        
        this.init();
    }
    
    /**
     * Initialize collaboration manager
     */
    init() {
        try {
            console.log('Initializing collaboration manager', {
                sessionId: this.sessionId,
                modelName: this.modelName,
                recordId: this.recordId
            });
            
            this.initializeSocket();
            this.setupFormListeners();
            this.setupUI();
            this.registerEventHandlers();
            
        } catch (error) {
            console.error('Error initializing collaboration manager:', error);
        }
    }
    
    /**
     * Initialize Socket.IO connection
     */
    initializeSocket() {
        try {
            // Import Socket.IO (assuming it's loaded globally)
            if (typeof io === 'undefined') {
                console.error('Socket.IO not loaded. Please include Socket.IO library.');
                return;
            }
            
            this.socket = io(this.websocketUrl, {
                transports: ['websocket', 'polling'],
                auth: {
                    token: this.getAuthToken()
                }
            });
            
            this.setupSocketEventHandlers();
            
        } catch (error) {
            console.error('Error initializing socket:', error);
        }
    }
    
    /**
     * Set up Socket.IO event handlers
     */
    setupSocketEventHandlers() {
        // Connection events
        this.socket.on('connect', () => {
            console.log('Connected to collaboration server');
            this.isConnected = true;
            this.updateConnectionStatus('Connected');
            this.joinCollaboration();
        });
        
        this.socket.on('disconnect', () => {
            console.log('Disconnected from collaboration server');
            this.isConnected = false;
            this.updateConnectionStatus('Disconnected');
            this.clearPresenceIndicators();
        });
        
        this.socket.on('connect_error', (error) => {
            console.error('Connection error:', error);
            this.updateConnectionStatus('Connection Error');
        });
        
        // Collaboration events
        this.socket.on('connection_confirmed', (data) => {
            console.log('Connection confirmed:', data);
        });
        
        this.socket.on('collaboration_joined', (data) => {
            console.log('Joined collaboration:', data);
            this.updateParticipants(data.participants || []);
        });
        
        this.socket.on('user_joined', (data) => {
            console.log('User joined:', data);
            this.addParticipant(data);
            this.showNotification(`${data.username} joined the session`, 'info');
        });
        
        this.socket.on('user_left', (data) => {
            console.log('User left:', data);
            this.removeParticipant(data.user_id);
            this.showNotification(`${data.username} left the session`, 'info');
        });
        
        this.socket.on('user_disconnected', (data) => {
            console.log('User disconnected:', data);
            this.removeParticipant(data.user_id);
        });
        
        // Field change events
        this.socket.on('field_changed', (data) => {
            console.log('Remote field change:', data);
            this.handleRemoteFieldChange(data);
        });
        
        this.socket.on('cursor_moved', (data) => {
            console.log('Remote cursor move:', data);
            this.updateRemoteCursor(data);
        });
        
        // Conflict events
        this.socket.on('conflict_detected', (data) => {
            console.log('Conflict detected:', data);
            this.handleConflict(data);
        });
        
        this.socket.on('conflict_resolved', (data) => {
            console.log('Conflict resolved:', data);
            this.handleConflictResolution(data);
        });
        
        // Model events
        this.socket.on('model_changed', (data) => {
            console.log('Model changed:', data);
            this.handleModelChange(data);
        });
        
        // Error events
        this.socket.on('error', (data) => {
            console.error('Collaboration error:', data);
            this.showNotification(data.message || 'Collaboration error occurred', 'error');
        });
    }
    
    /**
     * Join collaboration session
     */
    joinCollaboration() {
        if (!this.socket || !this.sessionId) return;
        
        this.socket.emit('join_collaboration', {
            session_id: this.sessionId,
            model: this.modelName,
            record_id: this.recordId
        });
    }
    
    /**
     * Leave collaboration session
     */
    leaveCollaboration() {
        if (!this.socket) return;
        
        this.socket.emit('leave_collaboration', {
            model: this.modelName,
            record_id: this.recordId
        });
    }
    
    /**
     * Set up form field listeners for collaboration
     */
    setupFormListeners() {
        try {
            // Find the main form
            this.formElement = document.querySelector('form[data-collaboration="true"]') ||
                              document.querySelector('form');
            
            if (!this.formElement) {
                console.warn('No form found for collaboration');
                return;
            }
            
            // Add collaboration attributes
            this.formElement.setAttribute('data-collaboration-session', this.sessionId);
            this.formElement.setAttribute('data-collaboration-model', this.modelName);
            this.formElement.setAttribute('data-collaboration-record', this.recordId);
            
            // Set up field listeners
            const fields = this.formElement.querySelectorAll('input, textarea, select');
            fields.forEach(field => this.setupFieldListeners(field));
            
            console.log(`Set up collaboration for ${fields.length} form fields`);
            
        } catch (error) {
            console.error('Error setting up form listeners:', error);
        }
    }
    
    /**
     * Set up listeners for a specific field
     */
    setupFieldListeners(field) {
        // Skip certain field types
        if (field.type === 'hidden' || field.name === 'csrf_token') {
            return;
        }
        
        // Add collaboration class
        field.classList.add('collaboration-field');
        field.setAttribute('data-collaboration-field', field.name);
        
        // Focus events for cursor tracking
        field.addEventListener('focus', (e) => {
            this.handleFieldFocus(field);
        });
        
        field.addEventListener('blur', (e) => {
            this.handleFieldBlur(field);
        });
        
        // Change events for real-time sync
        field.addEventListener('input', (e) => {
            this.handleFieldInput(field, e);
        });
        
        field.addEventListener('change', (e) => {
            this.handleFieldChange(field, e);
        });
        
        // Cursor position tracking for text fields
        if (field.type === 'text' || field.type === 'textarea') {
            field.addEventListener('keyup', (e) => {
                this.handleCursorMove(field);
            });
            
            field.addEventListener('click', (e) => {
                this.handleCursorMove(field);
            });
        }
    }
    
    /**
     * Handle field focus
     */
    handleFieldFocus(field) {
        this.activeFields.add(field.name);
        this.broadcastCursorPosition(field.name, 'focus');
        this.highlightField(field, 'editing');
    }
    
    /**
     * Handle field blur
     */
    handleFieldBlur(field) {
        this.activeFields.delete(field.name);
        this.broadcastCursorPosition(field.name, 'blur');
        this.unhighlightField(field);
    }
    
    /**
     * Handle field input (real-time changes)
     */
    handleFieldInput(field, event) {
        // Debounce field changes to avoid excessive updates
        const fieldName = field.name;
        
        if (this.fieldChangeTimeouts.has(fieldName)) {
            clearTimeout(this.fieldChangeTimeouts.get(fieldName));
        }
        
        const timeout = setTimeout(() => {
            this.broadcastFieldChange(field);
            this.fieldChangeTimeouts.delete(fieldName);
        }, this.changeDebounceMs);
        
        this.fieldChangeTimeouts.set(fieldName, timeout);
        
        // Visual feedback for typing
        this.highlightField(field, 'typing');
    }
    
    /**
     * Handle field change (committed changes)
     */
    handleFieldChange(field, event) {
        // Clear any pending input timeout
        const fieldName = field.name;
        if (this.fieldChangeTimeouts.has(fieldName)) {
            clearTimeout(this.fieldChangeTimeouts.get(fieldName));
            this.fieldChangeTimeouts.delete(fieldName);
        }
        
        // Broadcast immediate change
        this.broadcastFieldChange(field);
    }
    
    /**
     * Handle cursor movement in text fields
     */
    handleCursorMove(field) {
        if (field.type !== 'text' && field.tagName !== 'TEXTAREA') return;
        
        const position = field.selectionStart;
        this.socket?.emit('cursor_move', {
            model: this.modelName,
            record_id: this.recordId,
            field_name: field.name,
            position: position
        });
    }
    
    /**
     * Broadcast field change to other participants
     */
    broadcastFieldChange(field) {
        if (!this.socket || !this.isConnected) return;
        
        const oldValue = field.getAttribute('data-collaboration-value') || '';
        const newValue = field.value;
        
        // Only broadcast if value actually changed
        if (oldValue === newValue) return;
        
        // Store current value for future comparisons
        field.setAttribute('data-collaboration-value', newValue);
        
        this.socket.emit('field_change', {
            model: this.modelName,
            record_id: this.recordId,
            field_name: field.name,
            old_value: oldValue,
            new_value: newValue,
            timestamp: new Date().toISOString()
        });
    }
    
    /**
     * Broadcast cursor position
     */
    broadcastCursorPosition(fieldName, position) {
        if (!this.socket || !this.isConnected) return;
        
        this.socket.emit('cursor_move', {
            model: this.modelName,
            record_id: this.recordId,
            field_name: fieldName,
            position: position
        });
    }
    
    /**
     * Handle remote field changes
     */
    handleRemoteFieldChange(data) {
        if (data.user_id === this.userId) {
            return; // Ignore own changes
        }
        
        const field = this.getFieldByName(data.field_name);
        if (!field) {
            console.warn('Field not found for remote change:', data.field_name);
            return;
        }
        
        // Check for conflicts
        const currentValue = field.value;
        const expectedOldValue = data.old_value;
        
        if (currentValue !== expectedOldValue && currentValue !== '') {
            // Potential conflict
            this.handlePotentialConflict(field, data);
        } else {
            // Apply change directly
            this.applyRemoteFieldChange(field, data);
        }
    }
    
    /**
     * Apply remote field change
     */
    applyRemoteFieldChange(field, data) {
        // Temporarily disable event listeners to prevent loops
        this.disableFieldEvents(field);
        
        // Apply the change
        field.value = data.new_value;
        field.setAttribute('data-collaboration-value', data.new_value);
        
        // Visual feedback
        this.highlightFieldChange(field, data.username);
        
        // Re-enable events after a short delay
        setTimeout(() => {
            this.enableFieldEvents(field);
        }, 100);
    }
    
    /**
     * Handle potential conflicts
     */
    handlePotentialConflict(field, remoteChange) {
        console.log('Potential conflict detected', {
            field: field.name,
            localValue: field.value,
            remoteValue: remoteChange.new_value,
            remoteUser: remoteChange.username
        });
        
        // Create conflict data
        const conflictData = {
            field_name: field.name,
            local_value: field.value,
            remote_value: remoteChange.new_value,
            remote_user: remoteChange.username,
            remote_user_id: remoteChange.user_id,
            timestamp: remoteChange.timestamp
        };
        
        // Show conflict resolution UI
        this.showConflictResolution(conflictData);
    }
    
    /**
     * Handle conflict resolution
     */
    handleConflict(data) {
        this.showConflictResolution(data);
    }
    
    /**
     * Handle conflict resolution result
     */
    handleConflictResolution(data) {
        const field = this.getFieldByName(data.field_name);
        if (field && data.resolved_value !== undefined) {
            this.applyRemoteFieldChange(field, {
                new_value: data.resolved_value,
                username: 'System'
            });
            
            this.showNotification(`Conflict resolved for ${data.field_name}`, 'success');
        }
    }
    
    /**
     * Handle model changes
     */
    handleModelChange(data) {
        console.log('Model change received:', data);
        
        // Apply changes to multiple fields
        if (data.changes) {
            Object.entries(data.changes).forEach(([fieldName, change]) => {
                const field = this.getFieldByName(fieldName);
                if (field) {
                    this.applyRemoteFieldChange(field, {
                        new_value: change.new,
                        username: data.username || 'Unknown'
                    });
                }
            });
        }
    }
    
    /**
     * Update remote cursor position
     */
    updateRemoteCursor(data) {
        if (data.user_id === this.userId) return;
        
        const field = this.getFieldByName(data.field_name);
        if (!field) return;
        
        const userId = data.user_id;
        const username = data.username;
        const position = data.position;
        
        if (position === 'focus') {
            this.showRemoteCursor(field, userId, username);
        } else if (position === 'blur') {
            this.hideRemoteCursor(field, userId);
        } else if (typeof position === 'number') {
            this.updateRemoteCursorPosition(field, userId, position);
        }
    }
    
    /**
     * Show remote cursor
     */
    showRemoteCursor(field, userId, username) {
        // Add visual indicator for remote user editing this field
        const indicator = this.getOrCreateCursorIndicator(userId, username);
        this.positionCursorIndicator(indicator, field);
        
        // Highlight field as being edited by remote user
        this.highlightField(field, 'remote-editing', username);
    }
    
    /**
     * Hide remote cursor
     */
    hideRemoteCursor(field, userId) {
        const indicator = document.querySelector(`[data-cursor-user="${userId}"]`);
        if (indicator) {
            indicator.style.display = 'none';
        }
        
        this.unhighlightField(field, 'remote-editing');
    }
    
    /**
     * Get or create cursor indicator
     */
    getOrCreateCursorIndicator(userId, username) {
        let indicator = document.querySelector(`[data-cursor-user="${userId}"]`);
        
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.className = 'collaboration-cursor-indicator';
            indicator.setAttribute('data-cursor-user', userId);
            indicator.innerHTML = `
                <div class="cursor-pointer"></div>
                <div class="cursor-label">${username}</div>
            `;
            document.body.appendChild(indicator);
        }
        
        return indicator;
    }
    
    /**
     * Position cursor indicator
     */
    positionCursorIndicator(indicator, field) {
        const rect = field.getBoundingClientRect();
        indicator.style.position = 'absolute';
        indicator.style.left = rect.left + 'px';
        indicator.style.top = (rect.top - 30) + 'px';
        indicator.style.display = 'block';
        indicator.style.zIndex = '9999';
    }
    
    /**
     * Add participant to the session
     */
    addParticipant(participantData) {
        this.participants.set(participantData.user_id, participantData);
        this.updateParticipantsUI();
    }
    
    /**
     * Remove participant from the session
     */
    removeParticipant(userId) {
        this.participants.delete(userId);
        this.updateParticipantsUI();
        
        // Clean up cursors and indicators
        const cursor = document.querySelector(`[data-cursor-user="${userId}"]`);
        if (cursor) cursor.remove();
    }
    
    /**
     * Update participants list
     */
    updateParticipants(participantsList) {
        this.participants.clear();
        participantsList.forEach(participant => {
            this.participants.set(participant.user_id, participant);
        });
        this.updateParticipantsUI();
    }
    
    /**
     * Update participants UI
     */
    updateParticipantsUI() {
        const container = this.getParticipantsContainer();
        if (!container) return;
        
        container.innerHTML = '';
        
        this.participants.forEach(participant => {
            const element = document.createElement('div');
            element.className = 'participant-avatar';
            element.setAttribute('data-user-id', participant.user_id);
            element.innerHTML = `
                <img src="${participant.avatar_url || '/static/img/default-avatar.png'}" 
                     alt="${participant.username}" 
                     title="${participant.username}" />
                <span class="participant-name">${participant.username}</span>
            `;
            container.appendChild(element);
        });
        
        // Update participant count
        const countElement = document.querySelector('.collaboration-participant-count');
        if (countElement) {
            countElement.textContent = this.participants.size;
        }
    }
    
    /**
     * Get participants container element
     */
    getParticipantsContainer() {
        if (!this.participantsContainer) {
            this.participantsContainer = document.querySelector('.collaboration-participants') ||
                                       document.getElementById('collaboration-participants');
        }
        return this.participantsContainer;
    }
    
    /**
     * Set up UI components
     */
    setupUI() {
        this.createCollaborationUI();
        this.createConflictModal();
        this.updateConnectionStatus('Connecting...');
    }
    
    /**
     * Create collaboration UI elements
     */
    createCollaborationUI() {
        // Check if UI already exists
        if (document.querySelector('.collaboration-toolbar')) return;
        
        const toolbar = document.createElement('div');
        toolbar.className = 'collaboration-toolbar';
        toolbar.innerHTML = `
            <div class="collaboration-status">
                <span class="status-indicator"></span>
                <span class="status-text">Connecting...</span>
            </div>
            <div class="collaboration-participants" id="collaboration-participants">
                <!-- Participants will be added dynamically -->
            </div>
            <div class="collaboration-participant-count">
                <i class="fa fa-users"></i>
                <span>0</span>
            </div>
        `;
        
        // Insert toolbar at the top of the form or body
        const formContainer = this.formElement?.parentElement || document.body;
        formContainer.insertBefore(toolbar, formContainer.firstChild);
    }
    
    /**
     * Create conflict resolution modal
     */
    createConflictModal() {
        const modal = document.createElement('div');
        modal.className = 'modal fade collaboration-conflict-modal';
        modal.id = 'collaborationConflictModal';
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Resolve Conflict</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="conflict-info">
                            <p>There's a conflict in the <strong class="conflict-field-name"></strong> field:</p>
                        </div>
                        <div class="conflict-options">
                            <div class="row">
                                <div class="col-6">
                                    <h6>Your Version:</h6>
                                    <div class="conflict-value local-value"></div>
                                    <button class="btn btn-primary btn-sm mt-2" data-resolution="local">Keep Mine</button>
                                </div>
                                <div class="col-6">
                                    <h6 class="remote-user-name">Their Version:</h6>
                                    <div class="conflict-value remote-value"></div>
                                    <button class="btn btn-secondary btn-sm mt-2" data-resolution="remote">Use Theirs</button>
                                </div>
                            </div>
                            <div class="mt-3">
                                <h6>Custom Resolution:</h6>
                                <textarea class="form-control conflict-custom-value" rows="3" placeholder="Enter custom value..."></textarea>
                                <button class="btn btn-success btn-sm mt-2" data-resolution="custom">Use Custom</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        this.conflictModal = modal;
        
        // Set up conflict resolution handlers
        modal.addEventListener('click', (e) => {
            if (e.target.hasAttribute('data-resolution')) {
                this.resolveConflict(e.target.getAttribute('data-resolution'));
            }
        });
    }
    
    /**
     * Show conflict resolution modal
     */
    showConflictResolution(conflictData) {
        if (!this.conflictModal) return;
        
        // Store conflict data for resolution
        this.currentConflict = conflictData;
        
        // Populate modal with conflict information
        this.conflictModal.querySelector('.conflict-field-name').textContent = conflictData.field_name;
        this.conflictModal.querySelector('.remote-user-name').textContent = `${conflictData.remote_user}'s Version:`;
        this.conflictModal.querySelector('.local-value').textContent = conflictData.local_value;
        this.conflictModal.querySelector('.remote-value').textContent = conflictData.remote_value;
        this.conflictModal.querySelector('.conflict-custom-value').value = `${conflictData.local_value}\\n${conflictData.remote_value}`;
        
        // Show modal
        const modal = new bootstrap.Modal(this.conflictModal);
        modal.show();
    }
    
    /**
     * Resolve conflict with user choice
     */
    resolveConflict(resolution) {
        if (!this.currentConflict) return;
        
        let resolvedValue;
        
        switch (resolution) {
            case 'local':
                resolvedValue = this.currentConflict.local_value;
                break;
            case 'remote':
                resolvedValue = this.currentConflict.remote_value;
                break;
            case 'custom':
                resolvedValue = this.conflictModal.querySelector('.conflict-custom-value').value;
                break;
            default:
                return;
        }
        
        // Apply resolution locally
        const field = this.getFieldByName(this.currentConflict.field_name);
        if (field) {
            field.value = resolvedValue;
            field.setAttribute('data-collaboration-value', resolvedValue);
        }
        
        // Send resolution to server
        this.sendConflictResolution(resolution, resolvedValue);
        
        // Hide modal
        const modal = bootstrap.Modal.getInstance(this.conflictModal);
        modal?.hide();
        
        this.currentConflict = null;
    }
    
    /**
     * Send conflict resolution to server
     */
    sendConflictResolution(resolution, value) {
        if (!this.socket) return;
        
        // This would send to a REST endpoint or WebSocket event
        fetch('/api/collaboration/resolve_conflict', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                conflict_id: this.currentConflict.conflict_id,
                resolution_choice: resolution,
                custom_value: resolution === 'custom' ? value : null
            })
        }).then(response => response.json())
          .then(data => {
              if (data.success) {
                  this.showNotification('Conflict resolved successfully', 'success');
              } else {
                  this.showNotification('Failed to resolve conflict: ' + data.error, 'error');
              }
          })
          .catch(error => {
              console.error('Error resolving conflict:', error);
              this.showNotification('Error resolving conflict', 'error');
          });
    }
    
    /**
     * Update connection status
     */
    updateConnectionStatus(status) {
        const statusElement = document.querySelector('.collaboration-status .status-text');
        const indicatorElement = document.querySelector('.collaboration-status .status-indicator');
        
        if (statusElement) statusElement.textContent = status;
        
        if (indicatorElement) {
            indicatorElement.className = 'status-indicator';
            if (status === 'Connected') {
                indicatorElement.classList.add('connected');
            } else if (status === 'Disconnected') {
                indicatorElement.classList.add('disconnected');
            } else {
                indicatorElement.classList.add('connecting');
            }
        }
    }
    
    /**
     * Show notification to user
     */
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} collaboration-notification`;
        notification.innerHTML = `
            <div class="d-flex align-items-center">
                <div class="flex-grow-1">${message}</div>
                <button type="button" class="btn-close" onclick="this.parentElement.parentElement.remove()"></button>
            </div>
        `;
        
        // Add to page
        const container = document.querySelector('.collaboration-notifications') || document.body;
        container.appendChild(notification);
        
        // Auto-remove after delay
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }
    
    /**
     * Highlight field with visual feedback
     */
    highlightField(field, type, username = null) {
        field.classList.add(`collaboration-${type}`);
        
        if (username) {
            field.setAttribute('data-collaboration-user', username);
            field.title = `Being edited by ${username}`;
        }
    }
    
    /**
     * Remove field highlighting
     */
    unhighlightField(field, type = null) {
        if (type) {
            field.classList.remove(`collaboration-${type}`);
        } else {
            // Remove all collaboration classes
            field.className = field.className.replace(/collaboration-\\w+/g, '');
        }
        
        field.removeAttribute('data-collaboration-user');
        field.removeAttribute('title');
    }
    
    /**
     * Highlight field change with animation
     */
    highlightFieldChange(field, username) {
        this.highlightField(field, 'changed', username);
        
        // Remove highlight after animation
        setTimeout(() => {
            this.unhighlightField(field, 'changed');
        }, 2000);
    }
    
    /**
     * Clear all presence indicators
     */
    clearPresenceIndicators() {
        document.querySelectorAll('.collaboration-cursor-indicator').forEach(el => el.remove());
        this.participants.clear();
        this.updateParticipantsUI();
    }
    
    /**
     * Utility methods
     */
    
    getFieldByName(fieldName) {
        return this.formElement?.querySelector(`[name="${fieldName}"]`);
    }
    
    getAuthToken() {
        // Get authentication token from meta tag, cookie, or localStorage
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta?.getAttribute('content') || '';
    }
    
    getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta?.getAttribute('content') || '';
    }
    
    disableFieldEvents(field) {
        field.setAttribute('data-events-disabled', 'true');
    }
    
    enableFieldEvents(field) {
        field.removeAttribute('data-events-disabled');
    }
    
    registerEventHandlers() {
        // Custom event handlers can be registered here
    }
    
    /**
     * Public API methods
     */
    
    on(event, handler) {
        if (!this.eventHandlers.has(event)) {
            this.eventHandlers.set(event, []);
        }
        this.eventHandlers.get(event).push(handler);
    }
    
    emit(event, data) {
        const handlers = this.eventHandlers.get(event);
        if (handlers) {
            handlers.forEach(handler => {
                try {
                    handler(data);
                } catch (error) {
                    console.error('Error in event handler:', error);
                }
            });
        }
    }
    
    /**
     * Cleanup and destroy
     */
    destroy() {
        try {
            if (this.socket) {
                this.leaveCollaboration();
                this.socket.disconnect();
            }
            
            // Clear timeouts
            this.fieldChangeTimeouts.forEach(timeout => clearTimeout(timeout));
            this.fieldChangeTimeouts.clear();
            
            // Remove event listeners
            // (Would need to track these to remove properly)
            
            // Clean up UI elements
            document.querySelectorAll('.collaboration-cursor-indicator').forEach(el => el.remove());
            
            console.log('Collaboration manager destroyed');
            
        } catch (error) {
            console.error('Error destroying collaboration manager:', error);
        }
    }
}

// Auto-initialize collaboration if configuration is present
document.addEventListener('DOMContentLoaded', function() {
    const collaborationConfig = window.collaborationConfig || {};
    
    if (collaborationConfig.enabled && collaborationConfig.sessionId) {
        console.log('Auto-initializing collaboration with config:', collaborationConfig);
        window.collaboration = new CollaborationManager(collaborationConfig);
    }
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CollaborationManager;
} else {
    window.CollaborationManager = CollaborationManager;
}