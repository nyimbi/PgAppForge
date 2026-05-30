/**
 * Visual IDE Frontend JavaScript
 * 
 * Main JavaScript application for the Flask-AppBuilder Visual Development IDE.
 * Provides drag-and-drop interface, component management, and real-time preview.
 */

class VisualIDEApp {
    constructor() {
        this.apiBaseUrl = '/api/visual-ide';
        this.currentProject = null;
        this.currentView = null;
        this.selectedComponent = null;
        this.componentLibrary = {};
        
        // UI state
        this.isDragging = false;
        this.dragData = null;
        
        // WebSocket connection for live updates
        this.socket = null;
        
        this.init();
    }
    
    async init() {
        console.log('Initializing Visual IDE...');
        
        // Initialize WebSocket connection
        if (window.io) {
            this.initWebSocket();
        }
        
        // Load initial data
        await this.loadProject();
        await this.loadComponentLibrary();
        
        // Setup UI event handlers
        this.setupEventHandlers();
        
        // Load views list
        await this.loadViews();
        
        console.log('Visual IDE initialized successfully');
    }
    
    initWebSocket() {
        try {
            this.socket = io();
            
            this.socket.on('connect', () => {
                console.log('Connected to live preview server');
                this.updateConnectionStatus(true);
            });
            
            this.socket.on('disconnect', () => {
                console.log('Disconnected from live preview server');
                this.updateConnectionStatus(false);
            });
            
            this.socket.on('view_updated', (data) => {
                if (this.currentView && this.currentView.name === data.view_name) {
                    this.showNotification('View updated in preview', 'info');
                }
            });
            
            this.socket.on('project_updated', (data) => {
                this.showNotification('Project updated', 'info');
                this.loadViews(); // Refresh views list
            });
            
        } catch (error) {
            console.error('Failed to initialize WebSocket:', error);
        }
    }
    
    // Project Management
    async loadProject() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/project`);
            const data = await response.json();
            
            if (response.ok) {
                this.currentProject = data;
                this.updateProjectUI();
            } else {
                console.error('Failed to load project:', data.error);
            }
        } catch (error) {
            console.error('Error loading project:', error);
        }
    }
    
    updateProjectUI() {
        if (this.currentProject) {
            document.getElementById('project-name').textContent = this.currentProject.project_name || 'Untitled Project';
            document.getElementById('views-count').textContent = this.currentProject.views_count || 0;
        }
    }
    
    // Component Library Management
    async loadComponentLibrary() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/components/library`);
            const data = await response.json();
            
            if (response.ok) {
                this.componentLibrary = data.components;
                this.renderComponentPalette();
            } else {
                console.error('Failed to load component library:', data.error);
            }
        } catch (error) {
            console.error('Error loading component library:', error);
        }
    }
    
    renderComponentPalette() {
        const palette = document.getElementById('component-palette');
        if (!palette) return;
        
        // Group components by category
        const categories = {};
        for (const [type, component] of Object.entries(this.componentLibrary)) {
            const category = component.category;
            if (!categories[category]) {
                categories[category] = [];
            }
            categories[category].push({type, ...component});
        }
        
        // Render categories
        let html = '';
        for (const [categoryName, components] of Object.entries(categories)) {
            html += `
                <div class="component-category">
                    <h6 class="category-header">${categoryName}</h6>
                    <div class="component-list">
            `;
            
            for (const component of components) {
                html += `
                    <div class="component-item" draggable="true" 
                         data-component-type="${component.type}"
                         title="${component.description}">
                        <i class="fas fa-${component.icon}"></i>
                        <span>${component.name}</span>
                    </div>
                `;
            }
            
            html += '</div></div>';
        }
        
        palette.innerHTML = html;
        
        // Add drag handlers to component items
        palette.querySelectorAll('.component-item').forEach(item => {
            item.addEventListener('dragstart', this.handleComponentDragStart.bind(this));
        });
    }
    
    // View Management
    async loadViews() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/views`);
            const data = await response.json();
            
            if (response.ok) {
                this.renderViewsList(data.views);
            } else {
                console.error('Failed to load views:', data.error);
            }
        } catch (error) {
            console.error('Error loading views:', error);
        }
    }
    
    renderViewsList(views) {
        const viewsList = document.getElementById('views-list');
        if (!viewsList) return;
        
        let html = '';
        for (const [viewName, view] of Object.entries(views)) {
            html += `
                <div class="view-item" data-view-name="${viewName}">
                    <div class="view-header">
                        <strong>${view.name}</strong>
                        <span class="view-type badge badge-secondary">${view.view_type}</span>
                    </div>
                    <div class="view-info">
                        <small class="text-muted">
                            ${view.components_count} components • 
                            Modified ${new Date(view.modified_at).toLocaleDateString()}
                        </small>
                    </div>
                    <div class="view-actions">
                        <button class="btn btn-sm btn-primary" onclick="app.editView('${viewName}')">
                            <i class="fas fa-edit"></i> Edit
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="app.previewView('${viewName}')">
                            <i class="fas fa-eye"></i> Preview
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="app.deleteView('${viewName}')">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            `;
        }
        
        viewsList.innerHTML = html;
    }
    
    async createView() {
        const viewName = prompt('Enter view name:');
        if (!viewName) return;
        
        const viewType = prompt('Enter view type (ModelView/BaseView/CustomView):', 'ModelView');
        if (!viewType) return;
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    name: viewName,
                    view_type: viewType
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showNotification(`View "${viewName}" created successfully`, 'success');
                await this.loadViews();
                await this.editView(viewName);
            } else {
                this.showNotification(`Failed to create view: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error creating view:', error);
            this.showNotification('Error creating view', 'error');
        }
    }
    
    async editView(viewName) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${viewName}`);
            const data = await response.json();
            
            if (response.ok) {
                this.currentView = data.view;
                this.renderViewEditor();
                this.loadViewComponents();
            } else {
                this.showNotification(`Failed to load view: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error loading view:', error);
        }
    }
    
    async deleteView(viewName) {
        if (!confirm(`Are you sure you want to delete view "${viewName}"?`)) {
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${viewName}`, {
                method: 'DELETE'
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showNotification(`View "${viewName}" deleted successfully`, 'success');
                await this.loadViews();
                if (this.currentView && this.currentView.name === viewName) {
                    this.closeViewEditor();
                }
            } else {
                this.showNotification(`Failed to delete view: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error deleting view:', error);
            this.showNotification('Error deleting view', 'error');
        }
    }
    
    async previewView(viewName) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/preview/url?view=${viewName}`);
            const data = await response.json();
            
            if (response.ok) {
                window.open(data.url, '_blank');
            } else {
                this.showNotification(`Failed to get preview URL: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error getting preview URL:', error);
        }
    }
    
    // View Editor
    renderViewEditor() {
        if (!this.currentView) return;
        
        const editor = document.getElementById('view-editor');
        if (!editor) return;
        
        editor.style.display = 'block';
        document.getElementById('editor-view-name').textContent = this.currentView.name;
        document.getElementById('editor-view-type').textContent = this.currentView.view_type;
        
        // Setup canvas
        this.setupCanvas();
        
        // Show view properties panel
        this.renderViewProperties();
    }
    
    setupCanvas() {
        const canvas = document.getElementById('design-canvas');
        if (!canvas) return;
        
        // Clear canvas
        canvas.innerHTML = '';
        
        // Add drop zone styling
        canvas.className = 'design-canvas';
        
        // Add drop handlers
        canvas.addEventListener('dragover', this.handleCanvasDragOver.bind(this));
        canvas.addEventListener('drop', this.handleCanvasDrop.bind(this));
        
        // Add grid background
        if (this.currentView.layout.layout_type === 'grid') {
            canvas.classList.add('grid-layout');
            canvas.style.setProperty('--grid-columns', this.currentView.layout.columns);
        }
    }
    
    async loadViewComponents() {
        if (!this.currentView) return;
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components`);
            const data = await response.json();
            
            if (response.ok) {
                this.renderViewComponents(data.components, data.root_components);
            } else {
                console.error('Failed to load view components:', data.error);
            }
        } catch (error) {
            console.error('Error loading view components:', error);
        }
    }
    
    renderViewComponents(components, rootComponents) {
        const canvas = document.getElementById('design-canvas');
        if (!canvas) return;
        
        // Clear canvas
        canvas.innerHTML = '';
        
        // Render root components
        for (const componentId of rootComponents) {
            const component = components[componentId];
            if (component) {
                const element = this.createComponentElement(component);
                canvas.appendChild(element);
                
                // Render children recursively
                this.renderComponentChildren(element, component, components);
            }
        }
    }
    
    createComponentElement(component) {
        const element = document.createElement('div');
        element.className = 'design-component';
        element.dataset.componentId = component.component_id;
        element.dataset.componentType = component.component_type;
        
        // Set position
        if (this.currentView.layout.layout_type === 'grid') {
            element.style.gridRow = component.position.row + 1;
            element.style.gridColumn = `${component.position.column + 1} / span ${component.position.span}`;
        } else {
            element.style.position = 'absolute';
            element.style.left = `${component.position.x}px`;
            element.style.top = `${component.position.y}px`;
            element.style.width = `${component.position.width}px`;
            element.style.height = `${component.position.height}px`;
        }
        
        // Add component content
        element.innerHTML = `
            <div class="component-header">
                <span class="component-label">${component.label || component.component_type}</span>
                <div class="component-controls">
                    <button class="btn btn-xs btn-outline-primary" onclick="app.editComponent('${component.component_id}')">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn btn-xs btn-outline-danger" onclick="app.deleteComponent('${component.component_id}')">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
            <div class="component-content">
                ${this.getComponentPreview(component)}
            </div>
        `;
        
        // Add event handlers
        element.addEventListener('click', () => this.selectComponent(component.component_id));
        element.addEventListener('dragstart', (e) => this.handleComponentDragStart(e, component));
        element.draggable = true;
        
        return element;
    }
    
    renderComponentChildren(parentElement, parentComponent, allComponents) {
        for (const childId of parentComponent.children) {
            const childComponent = allComponents[childId];
            if (childComponent) {
                const childElement = this.createComponentElement(childComponent);
                parentElement.querySelector('.component-content').appendChild(childElement);
                
                // Recursively render children
                this.renderComponentChildren(childElement, childComponent, allComponents);
            }
        }
    }
    
    getComponentPreview(component) {
        const type = component.component_type;
        const props = component.properties || {};
        
        switch (type) {
            case 'TextField':
                return `<input type="text" class="form-control" placeholder="${component.placeholder || 'Text field'}" readonly>`;
            
            case 'TextArea':
                return `<textarea class="form-control" placeholder="${component.placeholder || 'Text area'}" readonly></textarea>`;
            
            case 'SelectField':
                return `<select class="form-control" disabled><option>${component.placeholder || 'Select option'}</option></select>`;
            
            case 'Button':
                return `<button type="button" class="btn btn-${props.variant || 'primary'}">${props.text || 'Button'}</button>`;
            
            case 'DataTable':
                return `
                    <table class="table table-sm">
                        <thead><tr><th>Sample</th><th>Data</th></tr></thead>
                        <tbody><tr><td>Row 1</td><td>Value 1</td></tr></tbody>
                    </table>
                `;
            
            case 'Chart':
                return `<div class="chart-placeholder">📊 ${props.chart_type || 'Chart'}</div>`;
            
            default:
                return `<div class="component-placeholder">${type}</div>`;
        }
    }
    
    // Component Management
    selectComponent(componentId) {
        // Remove previous selection
        document.querySelectorAll('.design-component.selected').forEach(el => {
            el.classList.remove('selected');
        });
        
        // Select new component
        const element = document.querySelector(`[data-component-id="${componentId}"]`);
        if (element) {
            element.classList.add('selected');
            this.selectedComponent = componentId;
            this.loadComponentProperties(componentId);
        }
    }
    
    async loadComponentProperties(componentId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components/${componentId}`);
            const data = await response.json();
            
            if (response.ok) {
                this.renderComponentProperties(data.component);
            } else {
                console.error('Failed to load component properties:', data.error);
            }
        } catch (error) {
            console.error('Error loading component properties:', error);
        }
    }
    
    renderComponentProperties(component) {
        const panel = document.getElementById('properties-panel');
        if (!panel) return;
        
        let html = `
            <h6>Component Properties</h6>
            <div class="form-group">
                <label>Component ID</label>
                <input type="text" class="form-control" value="${component.component_id}" readonly>
            </div>
            <div class="form-group">
                <label>Component Type</label>
                <input type="text" class="form-control" value="${component.component_type}" readonly>
            </div>
            <div class="form-group">
                <label>Label</label>
                <input type="text" class="form-control" value="${component.label || ''}" 
                       onchange="app.updateComponentProperty('${component.component_id}', 'label', this.value)">
            </div>
        `;
        
        // Add type-specific properties
        if (component.component_type === 'TextField' || component.component_type === 'TextArea') {
            html += `
                <div class="form-group">
                    <label>Placeholder</label>
                    <input type="text" class="form-control" value="${component.placeholder || ''}" 
                           onchange="app.updateComponentProperty('${component.component_id}', 'placeholder', this.value)">
                </div>
            `;
        }
        
        if (component.component_type === 'Button') {
            html += `
                <div class="form-group">
                    <label>Button Text</label>
                    <input type="text" class="form-control" value="${component.properties.text || ''}" 
                           onchange="app.updateComponentProperty('${component.component_id}', 'text', this.value)">
                </div>
                <div class="form-group">
                    <label>Button Variant</label>
                    <select class="form-control" onchange="app.updateComponentProperty('${component.component_id}', 'variant', this.value)">
                        <option value="primary" ${component.properties.variant === 'primary' ? 'selected' : ''}>Primary</option>
                        <option value="secondary" ${component.properties.variant === 'secondary' ? 'selected' : ''}>Secondary</option>
                        <option value="success" ${component.properties.variant === 'success' ? 'selected' : ''}>Success</option>
                        <option value="danger" ${component.properties.variant === 'danger' ? 'selected' : ''}>Danger</option>
                    </select>
                </div>
            `;
        }
        
        // Position properties
        html += `
            <h6 class="mt-3">Position</h6>
            <div class="row">
                <div class="col-6">
                    <div class="form-group">
                        <label>Row</label>
                        <input type="number" class="form-control" value="${component.position.row || 0}" 
                               onchange="app.updateComponentPosition('${component.component_id}', 'row', parseInt(this.value))">
                    </div>
                </div>
                <div class="col-6">
                    <div class="form-group">
                        <label>Column</label>
                        <input type="number" class="form-control" value="${component.position.column || 0}" 
                               onchange="app.updateComponentPosition('${component.component_id}', 'column', parseInt(this.value))">
                    </div>
                </div>
            </div>
            <div class="form-group">
                <label>Column Span</label>
                <input type="number" class="form-control" value="${component.position.span || 1}" min="1" 
                       onchange="app.updateComponentPosition('${component.component_id}', 'span', parseInt(this.value))">
            </div>
        `;
        
        panel.innerHTML = html;
    }
    
    async updateComponentProperty(componentId, property, value) {
        if (!this.currentView) return;
        
        const updateData = { properties: {} };
        updateData.properties[property] = value;
        
        // Special handling for direct properties
        if (['label', 'placeholder'].includes(property)) {
            updateData[property] = value;
            delete updateData.properties[property];
        }
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components/${componentId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updateData)
            });
            
            const data = await response.json();
            
            if (response.ok) {
                // Refresh component display
                await this.loadViewComponents();
                this.showNotification('Component updated', 'success');
            } else {
                this.showNotification(`Failed to update component: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error updating component:', error);
            this.showNotification('Error updating component', 'error');
        }
    }
    
    async updateComponentPosition(componentId, positionProperty, value) {
        if (!this.currentView) return;
        
        const updateData = {
            position: {}
        };
        updateData.position[positionProperty] = value;
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components/${componentId}/move`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updateData)
            });
            
            const data = await response.json();
            
            if (response.ok) {
                // Refresh component display
                await this.loadViewComponents();
                this.showNotification('Component moved', 'success');
            } else {
                this.showNotification(`Failed to move component: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error moving component:', error);
            this.showNotification('Error moving component', 'error');
        }
    }
    
    async deleteComponent(componentId) {
        if (!confirm('Are you sure you want to delete this component?')) {
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components/${componentId}`, {
                method: 'DELETE'
            });
            
            const data = await response.json();
            
            if (response.ok) {
                await this.loadViewComponents();
                this.showNotification('Component deleted', 'success');
                
                // Clear properties panel if this component was selected
                if (this.selectedComponent === componentId) {
                    this.selectedComponent = null;
                    document.getElementById('properties-panel').innerHTML = '<p class="text-muted">Select a component to edit properties</p>';
                }
            } else {
                this.showNotification(`Failed to delete component: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error deleting component:', error);
            this.showNotification('Error deleting component', 'error');
        }
    }
    
    // Drag and Drop Handlers
    handleComponentDragStart(e, component = null) {
        this.isDragging = true;
        
        if (component) {
            // Dragging existing component (move)
            this.dragData = {
                type: 'move',
                componentId: component.component_id,
                componentType: component.component_type
            };
        } else {
            // Dragging from palette (create new)
            const componentType = e.target.closest('.component-item').dataset.componentType;
            this.dragData = {
                type: 'create',
                componentType: componentType
            };
        }
        
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', ''); // Required for some browsers
    }
    
    handleCanvasDragOver(e) {
        if (!this.isDragging) return;
        
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        
        // Visual feedback
        e.currentTarget.classList.add('drag-over');
    }
    
    async handleCanvasDrop(e) {
        e.preventDefault();
        e.currentTarget.classList.remove('drag-over');
        
        if (!this.isDragging || !this.dragData) return;
        
        // Calculate drop position
        const rect = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        // Convert to grid position if using grid layout
        let position = { x, y };
        if (this.currentView.layout.layout_type === 'grid') {
            const cols = this.currentView.layout.columns;
            const cellWidth = rect.width / cols;
            const column = Math.floor(x / cellWidth);
            const row = Math.floor(y / 50); // Assuming 50px row height
            
            position = { row, column, span: 1 };
        }
        
        if (this.dragData.type === 'create') {
            await this.createComponent(this.dragData.componentType, position);
        } else if (this.dragData.type === 'move') {
            await this.moveComponent(this.dragData.componentId, position);
        }
        
        this.isDragging = false;
        this.dragData = null;
    }
    
    async createComponent(componentType, position) {
        if (!this.currentView) return;
        
        const config = {
            position: position,
            label: `New ${componentType}`
        };
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    component_type: componentType,
                    config: config
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                await this.loadViewComponents();
                this.showNotification(`${componentType} component added`, 'success');
            } else {
                this.showNotification(`Failed to add component: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error creating component:', error);
            this.showNotification('Error adding component', 'error');
        }
    }
    
    async moveComponent(componentId, position) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}/components/${componentId}/move`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ position })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                await this.loadViewComponents();
                this.showNotification('Component moved', 'success');
            } else {
                this.showNotification(`Failed to move component: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error moving component:', error);
            this.showNotification('Error moving component', 'error');
        }
    }
    
    // Code Generation
    async generateCode() {
        if (!this.currentView) {
            this.showNotification('No view selected', 'error');
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/generate/view/${this.currentView.name}`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showNotification(`Code generated: ${data.files_count} files created`, 'success');
                this.showGeneratedFiles(data.files);
            } else {
                this.showNotification(`Failed to generate code: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error generating code:', error);
            this.showNotification('Error generating code', 'error');
        }
    }
    
    async generateApplication() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/generate/application`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showNotification(`Application generated: ${data.files_count} files created`, 'success');
                this.showGeneratedFiles(data.files);
            } else {
                this.showNotification(`Failed to generate application: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error generating application:', error);
            this.showNotification('Error generating application', 'error');
        }
    }
    
    showGeneratedFiles(files) {
        const modal = document.getElementById('generated-files-modal');
        const filesList = document.getElementById('generated-files-list');
        
        if (!modal || !filesList) return;
        
        let html = '';
        for (const fileName of files) {
            html += `
                <div class="generated-file-item">
                    <i class="fas fa-file-code"></i>
                    <span>${fileName}</span>
                    <button class="btn btn-sm btn-outline-primary" onclick="app.viewGeneratedFile('${fileName}')">
                        View
                    </button>
                </div>
            `;
        }
        
        filesList.innerHTML = html;
        $(modal).modal('show');
    }
    
    async viewGeneratedFile(fileName) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/generated-files/${encodeURIComponent(fileName)}`);
            const data = await response.json();
            
            if (response.ok) {
                this.showCodeModal(fileName, data.content, data.language);
            } else {
                this.showNotification(`Failed to load file: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error loading generated file:', error);
            this.showNotification('Error loading file', 'error');
        }
    }
    
    showCodeModal(fileName, content, language) {
        const modal = document.getElementById('code-viewer-modal');
        const titleElement = document.getElementById('code-viewer-title');
        const codeElement = document.getElementById('code-viewer-content');
        
        if (!modal || !titleElement || !codeElement) return;
        
        titleElement.textContent = fileName;
        codeElement.textContent = content;
        codeElement.className = `language-${language}`;
        
        // Highlight code if Prism.js is available
        if (window.Prism) {
            Prism.highlightElement(codeElement);
        }
        
        $(modal).modal('show');
    }
    
    // Event Handlers
    setupEventHandlers() {
        // View operations
        document.getElementById('create-view-btn')?.addEventListener('click', () => this.createView());
        document.getElementById('generate-code-btn')?.addEventListener('click', () => this.generateCode());
        document.getElementById('generate-app-btn')?.addEventListener('click', () => this.generateApplication());
        
        // Close editor
        document.getElementById('close-editor-btn')?.addEventListener('click', () => this.closeViewEditor());
        
        // Preview controls
        document.getElementById('start-preview-btn')?.addEventListener('click', () => this.startPreview());
        document.getElementById('stop-preview-btn')?.addEventListener('click', () => this.stopPreview());
    }
    
    closeViewEditor() {
        document.getElementById('view-editor').style.display = 'none';
        this.currentView = null;
        this.selectedComponent = null;
        document.getElementById('properties-panel').innerHTML = '<p class="text-muted">Select a component to edit properties</p>';
    }
    
    async startPreview() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/preview/start`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ port: 5001 })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('Live preview started', 'success');
                this.updatePreviewStatus(true);
            } else {
                this.showNotification(`Failed to start preview: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error starting preview:', error);
            this.showNotification('Error starting preview', 'error');
        }
    }
    
    async stopPreview() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/preview/stop`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.showNotification('Live preview stopped', 'success');
                this.updatePreviewStatus(false);
            } else {
                this.showNotification(`Failed to stop preview: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error stopping preview:', error);
            this.showNotification('Error stopping preview', 'error');
        }
    }
    
    // UI Utilities
    updateConnectionStatus(connected) {
        const indicator = document.getElementById('connection-status');
        if (indicator) {
            indicator.className = connected ? 'status-connected' : 'status-disconnected';
            indicator.textContent = connected ? 'Connected' : 'Disconnected';
        }
    }
    
    updatePreviewStatus(running) {
        const startBtn = document.getElementById('start-preview-btn');
        const stopBtn = document.getElementById('stop-preview-btn');
        
        if (startBtn && stopBtn) {
            startBtn.disabled = running;
            stopBtn.disabled = !running;
        }
    }
    
    renderViewProperties() {
        if (!this.currentView) return;
        
        const panel = document.getElementById('view-properties-panel');
        if (!panel) return;
        
        panel.innerHTML = `
            <h6>View Properties</h6>
            <div class="form-group">
                <label>View Name</label>
                <input type="text" class="form-control" value="${this.currentView.name}" readonly>
            </div>
            <div class="form-group">
                <label>View Type</label>
                <input type="text" class="form-control" value="${this.currentView.view_type}" readonly>
            </div>
            <div class="form-group">
                <label>Description</label>
                <textarea class="form-control" rows="3" 
                          onchange="app.updateViewProperty('description', this.value)">${this.currentView.description || ''}</textarea>
            </div>
            <div class="form-group">
                <label>Layout Type</label>
                <select class="form-control" onchange="app.updateViewLayout('layout_type', this.value)">
                    <option value="grid" ${this.currentView.layout.layout_type === 'grid' ? 'selected' : ''}>Grid</option>
                    <option value="flex" ${this.currentView.layout.layout_type === 'flex' ? 'selected' : ''}>Flex</option>
                    <option value="absolute" ${this.currentView.layout.layout_type === 'absolute' ? 'selected' : ''}>Absolute</option>
                </select>
            </div>
            ${this.currentView.layout.layout_type === 'grid' ? `
                <div class="form-group">
                    <label>Grid Columns</label>
                    <input type="number" class="form-control" value="${this.currentView.layout.columns}" 
                           onchange="app.updateViewLayout('columns', parseInt(this.value))">
                </div>
            ` : ''}
        `;
    }
    
    async updateViewProperty(property, value) {
        if (!this.currentView) return;
        
        const updateData = {};
        updateData[property] = value;
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/views/${this.currentView.name}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updateData)
            });
            
            const data = await response.json();
            
            if (response.ok) {
                this.currentView[property] = value;
                this.showNotification('View updated', 'success');
            } else {
                this.showNotification(`Failed to update view: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error updating view:', error);
            this.showNotification('Error updating view', 'error');
        }
    }
    
    showNotification(message, type = 'info') {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show notification`;
        notification.innerHTML = `
            ${message}
            <button type="button" class="close" data-dismiss="alert">
                <span>&times;</span>
            </button>
        `;
        
        // Add to notifications container
        const container = document.getElementById('notifications-container') || document.body;
        container.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
    }
}

// Initialize the app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.app = new VisualIDEApp();
});