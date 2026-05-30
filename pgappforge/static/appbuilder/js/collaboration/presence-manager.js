/**
 * Presence Management for Flask-AppBuilder Collaboration
 * 
 * Manages user presence indicators, live cursors, and participant tracking
 */

class PresenceManager {
    constructor(collaborationManager) {
        this.collaboration = collaborationManager;
        this.participants = new Map();
        this.cursors = new Map();
        this.presenceContainer = null;
        this.cursorContainer = null;
        this.isInitialized = false;
        
        this.colors = [
            '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
            '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9'
        ];
        
        this.init();
    }
    
    init() {
        try {
            this.createPresenceContainer();
            this.createCursorContainer();
            this.setupEventListeners();
            this.isInitialized = true;
            console.log('Presence manager initialized');
        } catch (error) {
            console.error('Error initializing presence manager:', error);
        }
    }
    
    createPresenceContainer() {
        // Create or find presence container
        this.presenceContainer = document.querySelector('.collaboration-presence');
        
        if (!this.presenceContainer) {
            this.presenceContainer = document.createElement('div');
            this.presenceContainer.className = 'collaboration-presence';
            this.presenceContainer.innerHTML = `
                <span class="collaboration-presence-count">0 active</span>
            `;
            
            // Add to form container or body
            const formContainer = document.querySelector('.form-container, .panel-body, main');
            if (formContainer) {
                formContainer.appendChild(this.presenceContainer);
            } else {
                document.body.appendChild(this.presenceContainer);
            }
        }
    }
    
    createCursorContainer() {
        // Create container for live cursors
        this.cursorContainer = document.createElement('div');
        this.cursorContainer.className = 'collaboration-cursor-container';
        this.cursorContainer.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1003;
        `;
        
        // Add to form container or body
        const formContainer = document.querySelector('.form-container, .panel-body, main');
        if (formContainer) {
            formContainer.style.position = 'relative';
            formContainer.appendChild(this.cursorContainer);
        } else {
            document.body.appendChild(this.cursorContainer);
        }
    }
    
    setupEventListeners() {
        // Listen for user join/leave events
        if (this.collaboration.socket) {
            this.collaboration.socket.on('user_joined', (data) => {
                this.handleUserJoined(data);
            });
            
            this.collaboration.socket.on('user_left', (data) => {
                this.handleUserLeft(data);
            });
            
            this.collaboration.socket.on('user_cursor_moved', (data) => {
                this.handleCursorMove(data);
            });
            
            this.collaboration.socket.on('participants_updated', (data) => {
                this.updateParticipants(data.participants);
            });
        }
        
        // Track local cursor movement
        this.setupCursorTracking();
        
        // Track field focus/blur
        this.setupFieldTracking();
    }
    
    setupCursorTracking() {
        let cursorThrottleTimer = null;
        
        document.addEventListener('mousemove', (event) => {
            if (cursorThrottleTimer) return;
            
            cursorThrottleTimer = setTimeout(() => {
                this.broadcastCursorPosition(event.clientX, event.clientY);
                cursorThrottleTimer = null;
            }, 100); // Throttle to 10fps
        });
    }
    
    setupFieldTracking() {
        // Track field focus/blur events
        document.addEventListener('focusin', (event) => {
            const field = event.target;
            if (this.isCollaborativeField(field)) {
                this.broadcastFieldFocus(field);
            }
        });
        
        document.addEventListener('focusout', (event) => {
            const field = event.target;
            if (this.isCollaborativeField(field)) {
                this.broadcastFieldBlur(field);
            }
        });
    }
    
    isCollaborativeField(element) {
        return element.matches('input, textarea, select') &&
               !element.matches('[type="hidden"], [type="submit"], [type="button"]');
    }
    
    handleUserJoined(data) {
        const { user_id, user_info } = data;
        
        // Add participant
        this.participants.set(user_id, {
            ...user_info,
            joinedAt: Date.now(),
            color: this.getColorForUser(user_id),
            isActive: true
        });
        
        this.updatePresenceDisplay();
        this.showNotification(`${user_info.display_name || user_info.username} joined`, 'info');
        
        console.log('User joined:', user_info);
    }
    
    handleUserLeft(data) {
        const { user_id, user_info } = data;
        
        // Remove participant
        this.participants.delete(user_id);
        this.removeCursor(user_id);
        this.removeFieldHighlight(user_id);
        
        this.updatePresenceDisplay();
        this.showNotification(`${user_info.display_name || user_info.username} left`, 'info');
        
        console.log('User left:', user_info);
    }
    
    handleCursorMove(data) {
        const { user_id, x, y, field_name } = data;
        
        if (user_id === this.collaboration.currentUser.user_id) return;
        
        const participant = this.participants.get(user_id);
        if (!participant) return;
        
        this.updateCursor(user_id, x, y, participant);
        
        // Update field highlighting if cursor is over a field
        if (field_name) {
            this.highlightField(field_name, user_id, participant);
        }
    }
    
    updateParticipants(participantsList) {
        // Clear existing participants
        this.participants.clear();
        
        // Add updated participants
        participantsList.forEach(participant => {
            this.participants.set(participant.user_id, {
                ...participant,
                color: this.getColorForUser(participant.user_id),
                isActive: true
            });
        });
        
        this.updatePresenceDisplay();
    }
    
    updatePresenceDisplay() {
        if (!this.presenceContainer) return;
        
        const count = this.participants.size;
        const countText = count === 0 ? 'No active users' :
                         count === 1 ? '1 active user' : `${count} active users`;
        
        // Update count
        const countElement = this.presenceContainer.querySelector('.collaboration-presence-count');
        if (countElement) {
            countElement.textContent = countText;
        }
        
        // Remove existing avatars
        const existingAvatars = this.presenceContainer.querySelectorAll('.collaboration-user-avatar');
        existingAvatars.forEach(avatar => avatar.remove());
        
        // Add participant avatars
        this.participants.forEach((participant, userId) => {
            const avatar = document.createElement('img');
            avatar.className = 'collaboration-user-avatar';
            avatar.src = participant.avatar_url || '/static/appbuilder/img/default-avatar.png';
            avatar.alt = participant.display_name || participant.username;
            avatar.title = `${participant.display_name || participant.username} (${participant.isActive ? 'active' : 'idle'})`;
            avatar.style.borderColor = participant.color;
            
            if (participant.isActive) {
                avatar.classList.add('active');
            }
            
            this.presenceContainer.appendChild(avatar);
        });
    }
    
    updateCursor(userId, x, y, participant) {
        let cursor = this.cursors.get(userId);
        
        if (!cursor) {
            cursor = document.createElement('div');
            cursor.className = 'collaboration-cursor';
            cursor.style.color = participant.color;
            cursor.setAttribute('data-username', participant.display_name || participant.username);
            this.cursorContainer.appendChild(cursor);
            this.cursors.set(userId, cursor);
        }
        
        // Update cursor position
        cursor.style.left = x + 'px';
        cursor.style.top = y + 'px';
        
        // Hide cursor if it hasn't moved in a while
        clearTimeout(cursor.hideTimer);
        cursor.style.opacity = '1';
        cursor.hideTimer = setTimeout(() => {
            cursor.style.opacity = '0';
        }, 3000);
    }
    
    removeCursor(userId) {
        const cursor = this.cursors.get(userId);
        if (cursor) {
            cursor.remove();
            this.cursors.delete(userId);
        }
    }
    
    highlightField(fieldName, userId, participant) {
        // Remove existing highlight for this user
        this.removeFieldHighlight(userId);
        
        // Find field element
        const field = document.querySelector(`[name="${fieldName}"]`);
        if (!field) return;
        
        // Add field highlight
        field.classList.add('collaboration-field', 'being-edited', `being-edited-by-user-${this.getUserIndex(userId) + 1}`);
        
        // Add or update field label
        let label = field.parentElement.querySelector('.collaboration-field-label');
        if (!label) {
            label = document.createElement('div');
            label.className = 'collaboration-field-label';
            field.parentElement.style.position = 'relative';
            field.parentElement.appendChild(label);
        }
        
        label.textContent = `${participant.display_name || participant.username} is editing`;
        label.style.backgroundColor = participant.color;
        label.setAttribute('data-user-id', userId);
    }
    
    removeFieldHighlight(userId) {
        // Remove field highlights for this user
        const labels = document.querySelectorAll(`[data-user-id="${userId}"]`);
        labels.forEach(label => {
            const field = label.parentElement.querySelector('.collaboration-field');
            if (field) {
                field.classList.remove('being-edited', `being-edited-by-user-${this.getUserIndex(userId) + 1}`);
                if (!field.classList.contains('being-edited')) {
                    field.classList.remove('collaboration-field');
                }
            }
            label.remove();
        });
    }
    
    broadcastCursorPosition(x, y) {
        if (!this.collaboration.socket) return;
        
        // Get field under cursor
        const element = document.elementFromPoint(x, y);
        const fieldName = this.isCollaborativeField(element) ? element.name : null;
        
        this.collaboration.socket.emit('cursor_moved', {
            session_id: this.collaboration.sessionId,
            x: x,
            y: y,
            field_name: fieldName
        });
    }
    
    broadcastFieldFocus(field) {
        if (!this.collaboration.socket) return;
        
        this.collaboration.socket.emit('field_focused', {
            session_id: this.collaboration.sessionId,
            field_name: field.name,
            field_value: field.value
        });
    }
    
    broadcastFieldBlur(field) {
        if (!this.collaboration.socket) return;
        
        this.collaboration.socket.emit('field_blurred', {
            session_id: this.collaboration.sessionId,
            field_name: field.name,
            field_value: field.value
        });
    }
    
    getColorForUser(userId) {
        const index = this.getUserIndex(userId);
        return this.colors[index % this.colors.length];
    }
    
    getUserIndex(userId) {
        const userIds = Array.from(this.participants.keys()).sort();
        return userIds.indexOf(userId);
    }
    
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `collaboration-notification ${type}`;
        notification.innerHTML = `
            <div style="font-weight: 500; margin-bottom: 4px;">Collaboration</div>
            <div style="font-size: 13px;">${message}</div>
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 3 seconds
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100%)';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }
    
    // Public methods for integration
    getCurrentParticipants() {
        return Array.from(this.participants.values());
    }
    
    getParticipantById(userId) {
        return this.participants.get(userId);
    }
    
    isUserActive(userId) {
        const participant = this.participants.get(userId);
        return participant && participant.isActive;
    }
    
    destroy() {
        // Clean up cursors
        this.cursors.forEach(cursor => cursor.remove());
        this.cursors.clear();
        
        // Remove containers
        if (this.cursorContainer) {
            this.cursorContainer.remove();
        }
        
        // Remove field highlights
        this.participants.forEach((_, userId) => {
            this.removeFieldHighlight(userId);
        });
        
        // Clear participants
        this.participants.clear();
        
        console.log('Presence manager destroyed');
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PresenceManager;
}

// Global registration
window.CollaborationPresenceManager = PresenceManager;