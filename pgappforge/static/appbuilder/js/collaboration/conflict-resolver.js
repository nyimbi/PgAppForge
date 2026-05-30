/**
 * Conflict Resolution UI for Flask-AppBuilder Collaboration
 * 
 * Handles conflict detection, resolution strategies, and user interface for merging changes
 */

class ConflictResolver {
    constructor(collaborationManager) {
        this.collaboration = collaborationManager;
        this.activeConflicts = new Map();
        this.resolutionModal = null;
        this.isInitialized = false;
        
        this.resolutionStrategies = [
            {
                id: 'local',
                name: 'Keep My Version',
                description: 'Use your changes and discard the other version',
                icon: '👤'
            },
            {
                id: 'remote',
                name: 'Use Their Version',
                description: 'Accept the other user\'s changes',
                icon: '👥'
            },
            {
                id: 'merge_auto',
                name: 'Auto-Merge',
                description: 'Automatically combine both versions',
                icon: '🔄'
            },
            {
                id: 'merge_manual',
                name: 'Manual Merge',
                description: 'Create a custom merged version',
                icon: '✏️'
            }
        ];
        
        this.init();
    }
    
    init() {
        try {
            this.setupEventListeners();
            this.isInitialized = true;
            console.log('Conflict resolver initialized');
        } catch (error) {
            console.error('Error initializing conflict resolver:', error);
        }
    }
    
    setupEventListeners() {
        if (this.collaboration.socket) {
            this.collaboration.socket.on('conflict_detected', (data) => {
                this.handleConflictDetected(data);
            });
            
            this.collaboration.socket.on('conflict_resolved', (data) => {
                this.handleConflictResolved(data);
            });
            
            this.collaboration.socket.on('conflict_resolution_failed', (data) => {
                this.handleResolutionFailed(data);
            });
        }
        
        // Listen for ESC key to close conflict modal
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && this.resolutionModal) {
                this.closeConflictModal();
            }
        });
    }
    
    handleConflictDetected(conflictData) {
        const {
            conflict_id,
            session_id,
            field_name,
            local_change,
            remote_change,
            base_value,
            local_user,
            remote_user,
            timestamp
        } = conflictData;
        
        console.log('Conflict detected:', conflictData);
        
        // Store conflict data
        this.activeConflicts.set(conflict_id, {
            ...conflictData,
            detectedAt: Date.now()
        });
        
        // Show conflict resolution modal
        this.showConflictModal(conflictData);
        
        // Highlight the conflicted field
        this.highlightConflictedField(field_name);
        
        // Show notification
        this.showNotification(
            `Conflict detected in ${field_name} with ${remote_user.display_name || remote_user.username}`,
            'warning'
        );
    }
    
    handleConflictResolved(data) {
        const { conflict_id, resolution, resolved_value } = data;
        
        const conflict = this.activeConflicts.get(conflict_id);
        if (!conflict) return;
        
        console.log('Conflict resolved:', data);
        
        // Update field with resolved value
        this.applyResolvedValue(conflict.field_name, resolved_value);
        
        // Remove conflict from active list
        this.activeConflicts.delete(conflict_id);
        
        // Close modal if it's for this conflict
        if (this.resolutionModal && this.resolutionModal.dataset.conflictId === conflict_id) {
            this.closeConflictModal();
        }
        
        // Remove field highlight
        this.removeConflictHighlight(conflict.field_name);
        
        // Show success notification
        this.showNotification(
            `Conflict resolved using ${this.getStrategyName(resolution.method)}`,
            'success'
        );
    }
    
    handleResolutionFailed(data) {
        const { conflict_id, error } = data;
        
        console.error('Conflict resolution failed:', data);
        
        // Show error notification
        this.showNotification(`Failed to resolve conflict: ${error}`, 'error');
        
        // Keep the conflict modal open for retry
    }
    
    showConflictModal(conflictData) {
        // Close existing modal
        this.closeConflictModal();
        
        const {
            conflict_id,
            field_name,
            local_change,
            remote_change,
            base_value,
            local_user,
            remote_user
        } = conflictData;
        
        // Create modal element
        this.resolutionModal = document.createElement('div');
        this.resolutionModal.className = 'collaboration-conflict-modal';
        this.resolutionModal.dataset.conflictId = conflict_id;
        
        this.resolutionModal.innerHTML = `
            <div class="collaboration-conflict-content">
                <div class="collaboration-conflict-header">
                    <span class="collaboration-conflict-icon">⚠️</span>
                    <h3 class="collaboration-conflict-title">Merge Conflict in "${field_name}"</h3>
                </div>
                
                <div class="collaboration-conflict-description">
                    Both you and ${remote_user.display_name || remote_user.username} modified this field at the same time.
                    Choose how to resolve the conflict:
                </div>
                
                <div class="collaboration-conflict-versions">
                    <div class="collaboration-conflict-version" data-version="local">
                        <div class="collaboration-conflict-version-header">
                            👤 Your Version (${local_user.display_name || local_user.username})
                        </div>
                        <div class="collaboration-conflict-version-content">
                            <textarea readonly class="conflict-version-text">${local_change.new_value || ''}</textarea>
                        </div>
                    </div>
                    
                    <div class="collaboration-conflict-version" data-version="remote">
                        <div class="collaboration-conflict-version-header">
                            👥 Their Version (${remote_user.display_name || remote_user.username})
                        </div>
                        <div class="collaboration-conflict-version-content">
                            <textarea readonly class="conflict-version-text">${remote_change.new_value || ''}</textarea>
                        </div>
                    </div>
                </div>
                
                <div class="collaboration-conflict-strategies">
                    <h4>Resolution Strategy:</h4>
                    <div class="collaboration-strategy-options">
                        ${this.renderStrategyOptions()}
                    </div>
                </div>
                
                <div class="collaboration-manual-merge" style="display: none;">
                    <h4>Custom Merge:</h4>
                    <textarea class="collaboration-merge-text" placeholder="Create your custom merged version here...">${base_value || ''}</textarea>
                </div>
                
                <div class="collaboration-conflict-actions">
                    <button class="cancel-btn" onclick="collaborationConflictResolver.closeConflictModal()">
                        Cancel
                    </button>
                    <button class="primary resolve-btn" onclick="collaborationConflictResolver.resolveConflict()">
                        Resolve Conflict
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(this.resolutionModal);
        
        // Setup modal interactions
        this.setupModalInteractions();
        
        // Focus first strategy option
        const firstOption = this.resolutionModal.querySelector('.strategy-option');
        if (firstOption) {
            firstOption.click();
        }
        
        // Store global reference for onclick handlers
        window.collaborationConflictResolver = this;
    }
    
    renderStrategyOptions() {
        return this.resolutionStrategies.map(strategy => `
            <div class="strategy-option" data-strategy="${strategy.id}">
                <div class="strategy-icon">${strategy.icon}</div>
                <div class="strategy-info">
                    <div class="strategy-name">${strategy.name}</div>
                    <div class="strategy-description">${strategy.description}</div>
                </div>
            </div>
        `).join('');
    }
    
    setupModalInteractions() {
        if (!this.resolutionModal) return;
        
        // Strategy selection
        const strategyOptions = this.resolutionModal.querySelectorAll('.strategy-option');
        strategyOptions.forEach(option => {
            option.addEventListener('click', () => {
                // Remove previous selection
                strategyOptions.forEach(opt => opt.classList.remove('selected'));
                
                // Select current option
                option.classList.add('selected');
                
                // Show/hide manual merge textarea
                const manualMerge = this.resolutionModal.querySelector('.collaboration-manual-merge');
                const strategy = option.dataset.strategy;
                
                if (strategy === 'merge_manual') {
                    manualMerge.style.display = 'block';
                    manualMerge.querySelector('textarea').focus();
                } else {
                    manualMerge.style.display = 'none';
                }
            });
        });
        
        // Version selection for quick resolution
        const versionOptions = this.resolutionModal.querySelectorAll('.collaboration-conflict-version');
        versionOptions.forEach(version => {
            version.addEventListener('click', () => {
                // Remove previous selection
                versionOptions.forEach(v => v.classList.remove('selected'));
                
                // Select current version
                version.classList.add('selected');
                
                // Auto-select corresponding strategy
                const versionType = version.dataset.version;
                const strategyId = versionType === 'local' ? 'local' : 'remote';
                const strategyOption = this.resolutionModal.querySelector(`[data-strategy="${strategyId}"]`);
                
                if (strategyOption) {
                    strategyOptions.forEach(opt => opt.classList.remove('selected'));
                    strategyOption.classList.add('selected');
                }
            });
        });
        
        // Click outside to close
        this.resolutionModal.addEventListener('click', (event) => {
            if (event.target === this.resolutionModal) {
                this.closeConflictModal();
            }
        });
    }
    
    resolveConflict() {
        if (!this.resolutionModal) return;
        
        const conflictId = this.resolutionModal.dataset.conflictId;
        const conflict = this.activeConflicts.get(conflictId);
        
        if (!conflict) {
            console.error('Conflict not found:', conflictId);
            return;
        }
        
        // Get selected strategy
        const selectedStrategy = this.resolutionModal.querySelector('.strategy-option.selected');
        if (!selectedStrategy) {
            this.showNotification('Please select a resolution strategy', 'warning');
            return;
        }
        
        const strategy = selectedStrategy.dataset.strategy;
        let resolvedValue;
        
        // Determine resolved value based on strategy
        switch (strategy) {
            case 'local':
                resolvedValue = conflict.local_change.new_value;
                break;
                
            case 'remote':
                resolvedValue = conflict.remote_change.new_value;
                break;
                
            case 'merge_auto':
                resolvedValue = this.performAutoMerge(conflict);
                break;
                
            case 'merge_manual':
                const mergeText = this.resolutionModal.querySelector('.collaboration-merge-text');
                if (!mergeText || !mergeText.value.trim()) {
                    this.showNotification('Please provide a custom merged version', 'warning');
                    return;
                }
                resolvedValue = mergeText.value;
                break;
                
            default:
                console.error('Unknown resolution strategy:', strategy);
                return;
        }
        
        // Send resolution to server
        this.sendResolution(conflictId, strategy, resolvedValue);
        
        console.log('Resolving conflict:', {
            conflictId,
            strategy,
            resolvedValue
        });
    }
    
    performAutoMerge(conflict) {
        const localValue = conflict.local_change.new_value || '';
        const remoteValue = conflict.remote_change.new_value || '';
        const baseValue = conflict.base_value || '';
        
        // Simple auto-merge logic
        if (localValue === baseValue) {
            return remoteValue;
        } else if (remoteValue === baseValue) {
            return localValue;
        } else {
            // For text fields, try to merge both changes
            if (typeof localValue === 'string' && typeof remoteValue === 'string') {
                // If one is a subset of the other, use the longer one
                if (localValue.includes(remoteValue)) {
                    return localValue;
                } else if (remoteValue.includes(localValue)) {
                    return remoteValue;
                } else {
                    // Simple concatenation with separator
                    return `${localValue}\n${remoteValue}`;
                }
            } else {
                // For non-text values, prefer the most recent change
                return conflict.remote_change.timestamp > conflict.local_change.timestamp 
                    ? remoteValue : localValue;
            }
        }
    }
    
    sendResolution(conflictId, strategy, resolvedValue) {
        if (!this.collaboration.socket) {
            console.error('WebSocket not available');
            return;
        }
        
        this.collaboration.socket.emit('resolve_conflict', {
            conflict_id: conflictId,
            resolution_strategy: strategy,
            resolved_value: resolvedValue,
            timestamp: Date.now()
        });
    }
    
    closeConflictModal() {
        if (this.resolutionModal) {
            this.resolutionModal.remove();
            this.resolutionModal = null;
        }
        
        // Clean up global reference
        if (window.collaborationConflictResolver === this) {
            delete window.collaborationConflictResolver;
        }
    }
    
    applyResolvedValue(fieldName, resolvedValue) {
        const field = document.querySelector(`[name="${fieldName}"]`);
        if (field) {
            field.value = resolvedValue;
            
            // Trigger change event
            const changeEvent = new Event('change', { bubbles: true });
            field.dispatchEvent(changeEvent);
            
            // Flash the field to indicate update
            this.flashField(field);
        }
    }
    
    highlightConflictedField(fieldName) {
        const field = document.querySelector(`[name="${fieldName}"]`);
        if (field) {
            field.classList.add('collaboration-field', 'conflict-detected');
            field.style.borderColor = '#dc3545';
            field.style.boxShadow = '0 0 8px rgba(220, 53, 69, 0.3)';
            
            // Add conflict indicator
            let indicator = field.parentElement.querySelector('.conflict-indicator');
            if (!indicator) {
                indicator = document.createElement('div');
                indicator.className = 'conflict-indicator';
                indicator.innerHTML = '⚠️ Conflict';
                indicator.style.cssText = `
                    position: absolute;
                    top: -20px;
                    right: 0;
                    background: #dc3545;
                    color: white;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 11px;
                    z-index: 1002;
                `;
                
                field.parentElement.style.position = 'relative';
                field.parentElement.appendChild(indicator);
            }
        }
    }
    
    removeConflictHighlight(fieldName) {
        const field = document.querySelector(`[name="${fieldName}"]`);
        if (field) {
            field.classList.remove('conflict-detected');
            field.style.borderColor = '';
            field.style.boxShadow = '';
            
            // Remove conflict indicator
            const indicator = field.parentElement.querySelector('.conflict-indicator');
            if (indicator) {
                indicator.remove();
            }
        }
    }
    
    flashField(field) {
        field.style.transition = 'background-color 0.3s ease';
        field.style.backgroundColor = '#d4edda';
        
        setTimeout(() => {
            field.style.backgroundColor = '';
        }, 1000);
    }
    
    getStrategyName(strategyId) {
        const strategy = this.resolutionStrategies.find(s => s.id === strategyId);
        return strategy ? strategy.name : strategyId;
    }
    
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `collaboration-notification ${type}`;
        notification.innerHTML = `
            <div style="font-weight: 500; margin-bottom: 4px;">Conflict Resolution</div>
            <div style="font-size: 13px;">${message}</div>
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 4 seconds
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transform = 'translateX(100%)';
            setTimeout(() => notification.remove(), 300);
        }, 4000);
    }
    
    // Public methods for integration
    getActiveConflicts() {
        return Array.from(this.activeConflicts.values());
    }
    
    hasActiveConflicts() {
        return this.activeConflicts.size > 0;
    }
    
    getConflictById(conflictId) {
        return this.activeConflicts.get(conflictId);
    }
    
    destroy() {
        // Close any open modal
        this.closeConflictModal();
        
        // Clear active conflicts
        this.activeConflicts.clear();
        
        // Remove conflict highlights
        document.querySelectorAll('.conflict-detected').forEach(field => {
            field.classList.remove('conflict-detected');
            field.style.borderColor = '';
            field.style.boxShadow = '';
        });
        
        document.querySelectorAll('.conflict-indicator').forEach(indicator => {
            indicator.remove();
        });
        
        console.log('Conflict resolver destroyed');
    }
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ConflictResolver;
}

// Global registration
window.CollaborationConflictResolver = ConflictResolver;

// Add CSS for strategy options if not already included
if (!document.querySelector('#collaboration-conflict-resolver-styles')) {
    const styles = document.createElement('style');
    styles.id = 'collaboration-conflict-resolver-styles';
    styles.textContent = `
        .collaboration-strategy-options {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin: 15px 0;
        }
        
        .strategy-option {
            display: flex;
            align-items: center;
            padding: 12px;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .strategy-option:hover {
            background: #f8f9fa;
            border-color: #adb5bd;
        }
        
        .strategy-option.selected {
            background: #e3f2fd;
            border-color: #2196f3;
            box-shadow: 0 0 0 2px rgba(33, 150, 243, 0.2);
        }
        
        .strategy-icon {
            font-size: 20px;
            margin-right: 12px;
        }
        
        .strategy-info {
            flex: 1;
        }
        
        .strategy-name {
            font-weight: 500;
            margin-bottom: 2px;
        }
        
        .strategy-description {
            font-size: 13px;
            color: #6c757d;
        }
        
        .conflict-version-text {
            width: 100%;
            min-height: 80px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            padding: 8px;
            font-family: monospace;
            font-size: 13px;
            background: #f8f9fa;
        }
        
        .collaboration-merge-text {
            width: 100%;
            min-height: 100px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            padding: 12px;
            font-family: monospace;
            font-size: 13px;
            resize: vertical;
        }
        
        .collaboration-conflict-description {
            color: #495057;
            margin: 15px 0;
            line-height: 1.4;
        }
    `;
    document.head.appendChild(styles);
}