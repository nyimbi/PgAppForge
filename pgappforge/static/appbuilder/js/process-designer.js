/**
 * Process Designer - Visual Workflow Builder
 * 
 * Provides drag-and-drop interface for creating business process workflows
 * with node creation, connection management, and property editing.
 */

class ProcessDesigner {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        this.svg = document.getElementById('canvas-svg');
        this.propertiesPanel = document.getElementById('properties-panel');
        
        this.options = {
            definitionId: null,
            initialGraph: { nodes: [], edges: [] },
            saveUrl: null,
            validateUrl: null,
            gridSize: 20,
            ...options
        };
        
        // State management
        this.nodes = new Map();
        this.edges = new Map();
        this.selectedNode = null;
        this.draggedNode = null;
        this.connecting = false;
        this.connectionStart = null;
        this.nextNodeId = 1;
        this.nextEdgeId = 1;
        
        // History management
        this.history = [];
        this.historyIndex = -1;
        this.maxHistorySize = 50;
        
        // Advanced features
        this.clipboard = null;
        this.multiSelection = [];
        this.snapToGrid = true;
        this.showGrid = true;
        this.zoomLevel = 1.0;
        this.minZoom = 0.25;
        this.maxZoom = 3.0;
        this.autoLayout = false;
        
        // Search and filter
        this.searchQuery = '';
        this.visibilityFilters = {
            pools: true,
            lanes: true,
            tasks: true,
            gateways: true,
            events: true,
            approvals: true,
            subprocesses: true
        };
        
        // Additional advanced features
        this.undoStack = [];
        this.redoStack = [];
        this.maxUndoStack = 50;
        this.contextMenu = null;
        this.isGroupSelecting = false;
        this.selectionBox = null;
        this.animationFrameId = null;
        this.validationErrors = [];
        this.validationWarnings = [];
        
        // Collaboration features
        this.collaborators = new Map();
        this.liveUpdates = false;
        this.conflictResolution = 'latest_wins';
        
        // Event handlers
        this.handlers = {
            mousedown: this.onMouseDown.bind(this),
            mousemove: this.onMouseMove.bind(this),
            mouseup: this.onMouseUp.bind(this),
            click: this.onClick.bind(this),
            contextmenu: this.onContextMenu.bind(this)
        };
        
        // Enhanced node type configurations with modern design
        this.nodeTypes = {
            task: {
                width: 120,
                height: 80,
                color: '#007bff',
                bgColor: '#f8f9ff',
                borderColor: '#007bff',
                icon: 'fa-tasks',
                shape: 'rounded-rectangle',
                shadowColor: 'rgba(0, 123, 255, 0.2)',
                hoverColor: '#0056b3',
                subtypes: ['user', 'service', 'script', 'manual', 'send', 'receive']
            },
            gateway: {
                width: 80,
                height: 80,
                color: '#ffc107',
                bgColor: '#fffdf0',
                borderColor: '#ffc107',
                icon: 'fa-diamond',
                shape: 'diamond',
                shadowColor: 'rgba(255, 193, 7, 0.3)',
                hoverColor: '#e0a800',
                subtypes: ['exclusive', 'parallel', 'inclusive', 'complex', 'event']
            },
            event: {
                width: 60,
                height: 60,
                color: '#28a745',
                bgColor: '#f8fff9',
                borderColor: '#28a745',
                icon: 'fa-circle',
                shape: 'circle',
                shadowColor: 'rgba(40, 167, 69, 0.2)',
                hoverColor: '#1e7e34',
                subtypes: ['start', 'end', 'intermediate', 'boundary', 'timer', 'message', 'signal']
            },
            approval: {
                width: 120,
                height: 80,
                color: '#dc3545',
                bgColor: '#fff8f8',
                borderColor: '#dc3545',
                icon: 'fa-check-square',
                shape: 'rounded-rectangle',
                shadowColor: 'rgba(220, 53, 69, 0.2)',
                hoverColor: '#c82333',
                subtypes: ['single', 'multi', 'sequential', 'parallel', 'escalating']
            },
            subprocess: {
                width: 160,
                height: 100,
                color: '#6f42c1',
                bgColor: '#faf9fc',
                borderColor: '#6f42c1',
                icon: 'fa-sitemap',
                shape: 'rounded-rectangle',
                shadowColor: 'rgba(111, 66, 193, 0.2)',
                hoverColor: '#5a32a3',
                container: true,
                resizable: true,
                subtypes: ['embedded', 'call_activity', 'event'],
                indicators: {
                    embedded: '□',
                    call_activity: '◊',
                    event: '◉'
                }
            },
            pool: {
                width: 500,
                height: 250,
                color: '#17a2b8',
                bgColor: 'rgba(23, 162, 184, 0.05)',
                borderColor: '#17a2b8',
                headerColor: '#17a2b8',
                headerBg: 'rgba(23, 162, 184, 0.1)',
                icon: 'fa-layer-group',
                shape: 'container',
                shadowColor: 'rgba(23, 162, 184, 0.15)',
                hoverColor: '#138496',
                container: true,
                resizable: true,
                draggable: true,
                subtypes: ['participant', 'blackbox', 'collapsed'],
                minWidth: 400,
                minHeight: 200,
                headerHeight: 30,
                padding: 10
            },
            lane: {
                width: 450,
                height: 100,
                color: '#28a745',
                bgColor: 'rgba(40, 167, 69, 0.03)',
                borderColor: '#28a745',
                headerColor: '#28a745',
                headerBg: 'rgba(40, 167, 69, 0.1)',
                icon: 'fa-bars',
                shape: 'container',
                shadowColor: 'rgba(40, 167, 69, 0.1)',
                hoverColor: '#218838',
                container: true,
                resizable: true,
                draggable: true,
                subtypes: ['role', 'department', 'system', 'automated'],
                minWidth: 350,
                minHeight: 80,
                headerHeight: 25,
                padding: 5
            }
        };
        
        // Enhanced visual themes
        this.themes = {
            default: {
                name: 'Default',
                gridColor: '#e0e0e0',
                backgroundColor: '#fafafa',
                selectionColor: '#007bff',
                connectionColor: '#6c757d'
            },
            dark: {
                name: 'Dark',
                gridColor: '#404040',
                backgroundColor: '#2c2c2c',
                selectionColor: '#0d6efd',
                connectionColor: '#6c757d'
            },
            modern: {
                name: 'Modern',
                gridColor: '#f0f0f0',
                backgroundColor: '#ffffff',
                selectionColor: '#6f42c1',
                connectionColor: '#495057'
            },
            blueprint: {
                name: 'Blueprint',
                gridColor: '#1e88e5',
                backgroundColor: '#0d47a1',
                selectionColor: '#ffffff',
                connectionColor: '#bbdefb'
            }
        };
        
        this.currentTheme = this.themes.default;
    
    initialize() {
        this.setupEventListeners();
        this.setupPalette();
        this.loadGraph(this.options.initialGraph);
        this.saveState();
    }
    
    setupEventListeners() {
        // Canvas event listeners
        Object.entries(this.handlers).forEach(([event, handler]) => {
            this.canvas.addEventListener(event, handler);
        });
        
        // Prevent context menu on canvas
        this.canvas.addEventListener('contextmenu', e => e.preventDefault());
        
        // Keyboard shortcuts
        document.addEventListener('keydown', this.onKeyDown.bind(this));
    }
    
    setupPalette() {
        const paletteNodes = document.querySelectorAll('.palette-node');
        
        paletteNodes.forEach(node => {
            node.addEventListener('dragstart', this.onPaletteDragStart.bind(this));
            node.addEventListener('dragend', this.onPaletteDragEnd.bind(this));
            node.draggable = true;
        });
        
        // Make canvas a drop zone
        this.canvas.addEventListener('dragover', e => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });
        
        this.canvas.addEventListener('drop', this.onCanvasDrop.bind(this));
    }
    
    onPaletteDragStart(e) {
        const nodeType = e.target.dataset.nodeType;
        const nodeSubtype = e.target.dataset.nodeSubtype;
        
        e.dataTransfer.setData('text/plain', JSON.stringify({
            type: nodeType,
            subtype: nodeSubtype
        }));
        
        e.target.classList.add('dragging');
    }
    
    onPaletteDragEnd(e) {
        e.target.classList.remove('dragging');
    }
    
    onCanvasDrop(e) {
        e.preventDefault();
        
        try {
            const data = JSON.parse(e.dataTransfer.getData('text/plain'));
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            this.createNode(data.type, data.subtype, x, y);
        } catch (error) {
            console.error('Error dropping node:', error);
        }
    }
    
    createNode(type, subtype, x, y, data = {}) {
        const nodeId = `node_${this.nextNodeId++}`;
        const config = this.nodeTypes[type];
        
        // Snap to grid
        x = Math.round(x / this.options.gridSize) * this.options.gridSize;
        y = Math.round(y / this.options.gridSize) * this.options.gridSize;
        
        const nodeData = {
            id: nodeId,
            type: type,
            subtype: subtype,
            x: x,
            y: y,
            width: config.width,
            height: config.height,
            label: data.label || this.getDefaultLabel(type, subtype),
            properties: data.properties || this.getDefaultProperties(type, subtype),
            inputs: [],
            outputs: []
        };
        
        this.nodes.set(nodeId, nodeData);
        this.renderNode(nodeData);
        this.saveState();
        
        return nodeData;
    }
    
    renderNode(node) {
        const config = this.nodeTypes[node.type];
        const element = document.createElement('div');
        
        element.className = `canvas-node ${node.type}`;
        if (node.subtype) {
            element.classList.add(node.subtype);
        }
        element.id = node.id;
        element.style.left = `${node.x}px`;
        element.style.top = `${node.y}px`;
        element.style.width = `${node.width}px`;
        element.style.height = `${node.height}px`;
        element.style.borderColor = config.color;
        
        // Handle container types with special rendering
        if (config.container) {
            this.renderContainerNode(element, node, config);
        } else {
            this.renderStandardNode(element, node, config);
        }
        
        // Add event listeners
        element.addEventListener('mousedown', this.onNodeMouseDown.bind(this));
        element.addEventListener('click', this.onNodeClick.bind(this));
        
        this.canvas.appendChild(element);
    }
    
    renderStandardNode(element, node, config) {
        // Add shape-specific styles
        if (config.shape === 'circle') {
            element.style.borderRadius = '50%';
        } else if (config.shape === 'diamond') {
            element.style.borderRadius = '50%';
            element.style.transform = 'rotate(45deg)';
        }
        
        // Standard node content
        let content = `
            <div class="node-title">${node.label}</div>
            <div class="node-type">${node.subtype}</div>
            <div class="connection-point input" data-direction="input"></div>
            <div class="connection-point output" data-direction="output"></div>
        `;
        
        // Add subprocess indicator
        if (node.type === 'subprocess') {
            content += `<div class="subprocess-indicator">+</div>`;
        }
        
        element.innerHTML = content;
        
        // Add connection point listeners
        const connectionPoints = element.querySelectorAll('.connection-point');
        connectionPoints.forEach(point => {
            point.addEventListener('mousedown', this.onConnectionMouseDown.bind(this));
        });
    }
    
    renderContainerNode(element, node, config) {
        // Container-specific rendering
        if (node.type === 'pool') {
            element.innerHTML = `
                <div class="pool-header">${node.label}</div>
                <div class="pool-swimlanes" id="${node.id}-swimlanes"></div>
                ${config.resizable ? this.getResizeHandles() : ''}
            `;
            
            // Create default lanes if none exist
            if (!node.lanes || node.lanes.length === 0) {
                node.lanes = [{
                    id: `${node.id}-lane-1`,
                    name: 'Default Lane',
                    role: node.properties?.default_role || ''
                }];
            }
            
            // Render lanes within pool
            this.renderPoolLanes(node);
            
        } else if (node.type === 'lane') {
            element.innerHTML = `
                <div class="lane-header">${node.label}</div>
                <div class="lane-role-indicator">${node.properties?.assigned_role || 'No Role'}</div>
                <div class="connection-point input" data-direction="input"></div>
                <div class="connection-point output" data-direction="output"></div>
                ${config.resizable ? this.getResizeHandles() : ''}
            `;
            
            // Add connection point listeners
            const connectionPoints = element.querySelectorAll('.connection-point');
            connectionPoints.forEach(point => {
                point.addEventListener('mousedown', this.onConnectionMouseDown.bind(this));
            });
            
        } else if (node.type === 'subprocess') {
            element.innerHTML = `
                <div class="subprocess-container">
                    <div class="node-title">${node.label}</div>
                    <div class="node-type">${node.subtype.replace('_', ' ').toUpperCase()}</div>
                    <div class="subprocess-indicator">
                        ${node.subtype === 'embedded' ? '□' : node.subtype === 'call_activity' ? '◊' : '◉'}
                    </div>
                </div>
                <div class="connection-point input" data-direction="input"></div>
                <div class="connection-point output" data-direction="output"></div>
                ${config.resizable ? this.getResizeHandles() : ''}
            `;
            
            // Add connection point listeners
            const connectionPoints = element.querySelectorAll('.connection-point');
            connectionPoints.forEach(point => {
                point.addEventListener('mousedown', this.onConnectionMouseDown.bind(this));
            });
        }
        
        // Add resize handlers if resizable
        if (config.resizable) {
            this.addResizeHandlers(element, node);
        }
    }
    
    renderPoolLanes(poolNode) {
        const swimlanesContainer = document.getElementById(`${poolNode.id}-swimlanes`);
        if (!swimlanesContainer) return;
        
        swimlanesContainer.innerHTML = '';
        
        poolNode.lanes?.forEach((lane, index) => {
            const laneElement = document.createElement('div');
            laneElement.className = 'swimlane';
            laneElement.id = `${poolNode.id}-lane-${index}`;
            laneElement.innerHTML = `
                <div class="lane-header">${lane.name}</div>
                <div class="lane-role-indicator">${lane.role || 'No Role'}</div>
            `;
            
            // Make lane a drop zone for tasks
            laneElement.addEventListener('dragover', this.onLaneDragOver.bind(this));
            laneElement.addEventListener('drop', this.onLaneDrop.bind(this));
            
            swimlanesContainer.appendChild(laneElement);
        });
    }
    
    getResizeHandles() {
        return `
            <div class="resize-handle se" data-direction="se"></div>
            <div class="resize-handle e" data-direction="e"></div>
            <div class="resize-handle s" data-direction="s"></div>
        `;
    }
    
    addResizeHandlers(element, node) {
        const handles = element.querySelectorAll('.resize-handle');
        handles.forEach(handle => {
            handle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                this.startResize(e, element, node, handle.dataset.direction);
            });
        });
    }
    
    startResize(e, element, node, direction) {
        e.preventDefault();
        
        const startX = e.clientX;
        const startY = e.clientY;
        const startWidth = node.width;
        const startHeight = node.height;
        
        const handleMouseMove = (e) => {
            const deltaX = e.clientX - startX;
            const deltaY = e.clientY - startY;
            
            if (direction.includes('e')) {
                node.width = Math.max(100, startWidth + deltaX);
            }
            if (direction.includes('s')) {
                node.height = Math.max(80, startHeight + deltaY);
            }
            
            element.style.width = `${node.width}px`;
            element.style.height = `${node.height}px`;
            
            // Re-render pool lanes if resizing a pool
            if (node.type === 'pool') {
                this.renderPoolLanes(node);
            }
        };
        
        const handleMouseUp = () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            this.saveState();
        };
        
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    }
    
    onLaneDragOver(e) {
        e.preventDefault();
        e.currentTarget.classList.add('drop-zone', 'active');
    }
    
    onLaneDrop(e) {
        e.preventDefault();
        e.currentTarget.classList.remove('drop-zone', 'active');
        
        // Handle dropping tasks into lanes
        const laneElement = e.currentTarget;
        const poolElement = laneElement.closest('.canvas-node.pool');
        
        if (poolElement) {
            const poolNode = this.nodes.get(poolElement.id);
            const laneIndex = Array.from(laneElement.parentNode.children).indexOf(laneElement);
            
            // Set the dropped task's lane assignment
            if (this.draggedNode) {
                this.draggedNode.properties = this.draggedNode.properties || {};
                this.draggedNode.properties.assigned_lane = poolNode.lanes[laneIndex]?.id;
                this.draggedNode.properties.assigned_role = poolNode.lanes[laneIndex]?.role;
            }
        }
    }
    
    onNodeMouseDown(e) {
        if (e.target.classList.contains('connection-point')) {
            return; // Let connection handler deal with it
        }
        
        e.stopPropagation();
        const nodeId = e.currentTarget.id;
        const node = this.nodes.get(nodeId);
        
        if (!node) return;
        
        this.draggedNode = {
            node: node,
            startX: e.clientX - node.x,
            startY: e.clientY - node.y
        };
        
        this.selectNode(nodeId);
    }
    
    onNodeClick(e) {
        e.stopPropagation();
        const nodeId = e.currentTarget.id;
        this.selectNode(nodeId);
    }
    
    onConnectionMouseDown(e) {
        e.stopPropagation();
        
        const nodeElement = e.target.closest('.canvas-node');
        const nodeId = nodeElement.id;
        const direction = e.target.dataset.direction;
        
        this.connecting = true;
        this.connectionStart = {
            nodeId: nodeId,
            direction: direction,
            element: e.target
        };
        
        // Create temporary connection line
        this.createTempConnectionLine(e.clientX, e.clientY);
    }
    
    onMouseMove(e) {
        if (this.draggedNode) {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left - this.draggedNode.startX;
            const y = e.clientY - rect.top - this.draggedNode.startY;
            
            // Snap to grid
            const snapX = Math.round(x / this.options.gridSize) * this.options.gridSize;
            const snapY = Math.round(y / this.options.gridSize) * this.options.gridSize;
            
            this.moveNode(this.draggedNode.node.id, snapX, snapY);
        }
        
        if (this.connecting && this.tempLine) {
            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            this.updateTempConnectionLine(x, y);
        }
    }
    
    onMouseUp(e) {
        if (this.draggedNode) {
            this.saveState();
            this.draggedNode = null;
        }
        
        if (this.connecting) {
            const target = e.target;
            
            if (target.classList.contains('connection-point')) {
                const targetNode = target.closest('.canvas-node');
                const targetDirection = target.dataset.direction;
                
                this.createConnection(
                    this.connectionStart.nodeId,
                    this.connectionStart.direction,
                    targetNode.id,
                    targetDirection
                );
            }
            
            this.connecting = false;
            this.connectionStart = null;
            this.removeTempConnectionLine();
        }
    }
    
    onClick(e) {
        // Deselect node if clicking on empty canvas
        if (e.target === this.canvas) {
            this.deselectNode();
        }
    }
    
    onContextMenu(e) {
        if (e.target.classList.contains('canvas-node')) {
            this.showContextMenu(e, e.target.id);
        }
    }
    
    onKeyDown(e) {
        switch (e.key) {
            case 'Delete':
            case 'Backspace':
                if (this.selectedNode) {
                    this.deleteNode(this.selectedNode);
                }
                break;
            case 'z':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    if (e.shiftKey) {
                        this.redo();
                    } else {
                        this.undo();
                    }
                }
                break;
            case 's':
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    this.saveProcess();
                }
                break;
        }
    }
    
    moveNode(nodeId, x, y) {
        const node = this.nodes.get(nodeId);
        if (!node) return;
        
        node.x = x;
        node.y = y;
        
        const element = document.getElementById(nodeId);
        if (element) {
            element.style.left = `${x}px`;
            element.style.top = `${y}px`;
        }
        
        // Update connected edges
        this.updateNodeConnections(nodeId);
    }
    
    selectNode(nodeId) {
        this.deselectNode();
        
        const element = document.getElementById(nodeId);
        const node = this.nodes.get(nodeId);
        
        if (element && node) {
            element.classList.add('selected');
            this.selectedNode = nodeId;
            this.showNodeProperties(node);
        }
    }
    
    deselectNode() {
        if (this.selectedNode) {
            const element = document.getElementById(this.selectedNode);
            if (element) {
                element.classList.remove('selected');
            }
            this.selectedNode = null;
            this.hideNodeProperties();
        }
    }
    
    deleteNode(nodeId) {
        const node = this.nodes.get(nodeId);
        if (!node) return;
        
        // Remove connected edges
        const connectedEdges = Array.from(this.edges.values()).filter(
            edge => edge.source === nodeId || edge.target === nodeId
        );
        
        connectedEdges.forEach(edge => {
            this.deleteEdge(edge.id);
        });
        
        // Remove node
        this.nodes.delete(nodeId);
        const element = document.getElementById(nodeId);
        if (element) {
            element.remove();
        }
        
        if (this.selectedNode === nodeId) {
            this.deselectNode();
        }
        
        this.saveState();
    }
    
    createConnection(sourceId, sourceDir, targetId, targetDir) {
        // Validate connection
        if (sourceId === targetId) return; // Can't connect to self
        if (sourceDir === 'input' && targetDir === 'input') return; // Invalid connection
        if (sourceDir === 'output' && targetDir === 'output') return; // Invalid connection
        
        // Check for existing connection
        const existing = Array.from(this.edges.values()).find(
            edge => (edge.source === sourceId && edge.target === targetId) ||
                   (edge.source === targetId && edge.target === sourceId)
        );
        
        if (existing) return; // Connection already exists
        
        const edgeId = `edge_${this.nextEdgeId++}`;
        const edge = {
            id: edgeId,
            source: sourceDir === 'output' ? sourceId : targetId,
            target: sourceDir === 'output' ? targetId : sourceId,
            label: '',
            properties: {}
        };
        
        this.edges.set(edgeId, edge);
        this.renderEdge(edge);
        this.saveState();
        
        return edge;
    }
    
    renderEdge(edge) {
        const sourceNode = this.nodes.get(edge.source);
        const targetNode = this.nodes.get(edge.target);
        
        if (!sourceNode || !targetNode) return;
        
        const path = this.createConnectionPath(sourceNode, targetNode);
        const pathElement = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        
        pathElement.setAttribute('id', edge.id);
        pathElement.setAttribute('d', path);
        pathElement.setAttribute('class', 'connection-line');
        
        // Add click handler for edge selection
        pathElement.addEventListener('click', () => {
            this.selectEdge(edge.id);
        });
        
        this.svg.appendChild(pathElement);
    }
    
    createConnectionPath(sourceNode, targetNode) {
        const sourceX = sourceNode.x + sourceNode.width;
        const sourceY = sourceNode.y + sourceNode.height / 2;
        const targetX = targetNode.x;
        const targetY = targetNode.y + targetNode.height / 2;
        
        // Create curved path
        const controlOffset = Math.abs(targetX - sourceX) / 3;
        const controlX1 = sourceX + controlOffset;
        const controlY1 = sourceY;
        const controlX2 = targetX - controlOffset;
        const controlY2 = targetY;
        
        return `M ${sourceX} ${sourceY} C ${controlX1} ${controlY1}, ${controlX2} ${controlY2}, ${targetX} ${targetY}`;
    }
    
    updateNodeConnections(nodeId) {
        const connectedEdges = Array.from(this.edges.values()).filter(
            edge => edge.source === nodeId || edge.target === nodeId
        );
        
        connectedEdges.forEach(edge => {
            const pathElement = document.getElementById(edge.id);
            if (pathElement) {
                const sourceNode = this.nodes.get(edge.source);
                const targetNode = this.nodes.get(edge.target);
                const path = this.createConnectionPath(sourceNode, targetNode);
                pathElement.setAttribute('d', path);
            }
        });
    }
    
    createTempConnectionLine(x, y) {
        this.tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        this.tempLine.setAttribute('class', 'temp-connection');
        this.tempLine.setAttribute('stroke', '#007bff');
        this.tempLine.setAttribute('stroke-width', '2');
        this.tempLine.setAttribute('stroke-dasharray', '5,5');
        
        const startPoint = this.connectionStart.element.getBoundingClientRect();
        const canvasRect = this.canvas.getBoundingClientRect();
        
        this.tempLine.setAttribute('x1', startPoint.left - canvasRect.left + 5);
        this.tempLine.setAttribute('y1', startPoint.top - canvasRect.top + 5);
        this.tempLine.setAttribute('x2', x);
        this.tempLine.setAttribute('y2', y);
        
        this.svg.appendChild(this.tempLine);
    }
    
    updateTempConnectionLine(x, y) {
        if (this.tempLine) {
            this.tempLine.setAttribute('x2', x);
            this.tempLine.setAttribute('y2', y);
        }
    }
    
    removeTempConnectionLine() {
        if (this.tempLine) {
            this.tempLine.remove();
            this.tempLine = null;
        }
    }
    
    showNodeProperties(node) {
        const propertiesHtml = this.generatePropertiesForm(node);
        document.getElementById('node-properties').innerHTML = propertiesHtml;
        
        // Bind property change handlers
        this.bindPropertyHandlers(node);
    }
    
    hideNodeProperties() {
        document.getElementById('node-properties').innerHTML = 
            '<p class="text-muted">Select a node to edit its properties</p>';
    }
    
    generatePropertiesForm(node) {
        const config = this.nodeTypes[node.type];
        
        let html = `
            <div class="form-group">
                <label for="node-label">Label</label>
                <input type="text" id="node-label" class="form-control" value="${node.label}">
            </div>
        `;
        
        // Add type-specific properties
        switch (node.type) {
            case 'task':
                html += this.getTaskProperties(node);
                break;
            case 'gateway':
                html += this.getGatewayProperties(node);
                break;
            case 'event':
                html += this.getEventProperties(node);
                break;
            case 'approval':
                html += this.getApprovalProperties(node);
                break;
        }
        
        html += `
            <div class="form-group">
                <button type="button" class="btn btn-sm btn-danger" onclick="designer.deleteSelectedNode()">
                    <i class="fa fa-trash"></i> Delete Node
                </button>
            </div>
        `;
        
        return html;
    }
    
    getTaskProperties(node) {
        const props = node.properties;
        
        return `
            <div class="form-group">
                <label for="task-assignee">Assignee</label>
                <input type="text" id="task-assignee" class="form-control" 
                       value="${props.assignee || ''}" placeholder="User or role">
            </div>
            <div class="form-group">
                <label for="task-form">Form Key</label>
                <input type="text" id="task-form" class="form-control" 
                       value="${props.form_key || ''}" placeholder="Form identifier">
            </div>
            <div class="form-group">
                <label for="task-due-date">Due Date Expression</label>
                <input type="text" id="task-due-date" class="form-control" 
                       value="${props.due_date || ''}" placeholder="PT1H, P1D, etc.">
            </div>
        `;
    }
    
    getGatewayProperties(node) {
        const props = node.properties;
        
        return `
            <div class="form-group">
                <label for="gateway-condition">Default Condition</label>
                <textarea id="gateway-condition" class="form-control" rows="3" 
                         placeholder="JavaScript expression">${props.condition || ''}</textarea>
            </div>
        `;
    }
    
    getEventProperties(node) {
        const props = node.properties;
        
        if (node.subtype === 'timer') {
            return `
                <div class="form-group">
                    <label for="timer-duration">Duration</label>
                    <input type="text" id="timer-duration" class="form-control" 
                           value="${props.duration || ''}" placeholder="PT5M, PT1H, P1D">
                </div>
            `;
        }
        
        return '';
    }
    
    getApprovalProperties(node) {
        const props = node.properties;
        
        return `
            <div class="form-group">
                <label for="approval-approvers">Approvers</label>
                <textarea id="approval-approvers" class="form-control" rows="3" 
                         placeholder="Comma-separated list of users or roles">${props.approvers || ''}</textarea>
            </div>
            <div class="form-group">
                <label for="approval-threshold">Approval Threshold</label>
                <input type="number" id="approval-threshold" class="form-control" 
                       value="${props.threshold || 1}" min="1">
            </div>
        `;
    }
    
    bindPropertyHandlers(node) {
        // Label change handler
        const labelInput = document.getElementById('node-label');
        if (labelInput) {
            labelInput.addEventListener('input', () => {
                node.label = labelInput.value;
                this.updateNodeLabel(node.id, labelInput.value);
            });
        }
        
        // Type-specific handlers
        const propertyInputs = document.querySelectorAll('#node-properties input, #node-properties textarea');
        propertyInputs.forEach(input => {
            if (input.id === 'node-label') return; // Already handled
            
            input.addEventListener('input', () => {
                const propertyName = input.id.split('-').slice(1).join('_');
                node.properties[propertyName] = input.value;
            });
        });
    }
    
    updateNodeLabel(nodeId, label) {
        const element = document.getElementById(nodeId);
        if (element) {
            const titleElement = element.querySelector('.node-title');
            if (titleElement) {
                titleElement.textContent = label;
            }
        }
    }
    
    getDefaultLabel(type, subtype) {
        const labels = {
            task: {
                user: 'User Task',
                service: 'Service Task',
                script: 'Script Task',
                manual: 'Manual Task'
            },
            gateway: {
                exclusive: 'Exclusive Gateway',
                parallel: 'Parallel Gateway',
                inclusive: 'Inclusive Gateway'
            },
            event: {
                start: 'Start',
                end: 'End',
                timer: 'Timer',
                message: 'Message'
            },
            approval: {
                single: 'Single Approval',
                multi: 'Multi Approval'
            }
        };
        
        return labels[type]?.[subtype] || 'New Node';
    }
    
    getDefaultProperties(type, subtype) {
        const properties = {
            task: {
                assignee: '',
                form_key: '',
                due_date: ''
            },
            gateway: {
                condition: ''
            },
            event: {
                duration: ''
            },
            approval: {
                approvers: '',
                threshold: 1
            }
        };
        
        return properties[type] || {};
    }
    
    saveState() {
        const state = this.getProcessGraph();
        
        // Remove future states if we're not at the end
        this.history.splice(this.historyIndex + 1);
        
        this.history.push(JSON.parse(JSON.stringify(state)));
        this.historyIndex = this.history.length - 1;
        
        // Limit history size
        if (this.history.length > 50) {
            this.history.shift();
            this.historyIndex--;
        }
    }
    
    undo() {
        if (this.historyIndex > 0) {
            this.historyIndex--;
            this.loadGraph(this.history[this.historyIndex]);
        }
    }
    
    redo() {
        if (this.historyIndex < this.history.length - 1) {
            this.historyIndex++;
            this.loadGraph(this.history[this.historyIndex]);
        }
    }
    
    getProcessGraph() {
        const nodes = Array.from(this.nodes.values());
        const edges = Array.from(this.edges.values());
        
        return {
            nodes: nodes,
            edges: edges
        };
    }
    
    loadGraph(graph) {
        // Clear existing
        this.clearCanvas();
        this.nodes.clear();
        this.edges.clear();
        
        // Load nodes
        if (graph.nodes) {
            graph.nodes.forEach(nodeData => {
                this.nodes.set(nodeData.id, nodeData);
                this.renderNode(nodeData);
                
                // Update next ID counter
                const idNum = parseInt(nodeData.id.split('_')[1]);
                if (idNum >= this.nextNodeId) {
                    this.nextNodeId = idNum + 1;
                }
            });
        }
        
        // Load edges
        if (graph.edges) {
            graph.edges.forEach(edgeData => {
                this.edges.set(edgeData.id, edgeData);
                this.renderEdge(edgeData);
                
                // Update next ID counter
                const idNum = parseInt(edgeData.id.split('_')[1]);
                if (idNum >= this.nextEdgeId) {
                    this.nextEdgeId = idNum + 1;
                }
            });
        }
    }
    
    clearCanvas() {
        // Remove all nodes
        const nodeElements = this.canvas.querySelectorAll('.canvas-node');
        nodeElements.forEach(element => element.remove());
        
        // Remove all edges
        const edgeElements = this.svg.querySelectorAll('path');
        edgeElements.forEach(element => element.remove());
        
        this.deselectNode();
    }
    
    validateProcess() {
        const graph = this.getProcessGraph();
        const errors = [];
        
        // Check for start node
        const startNodes = graph.nodes.filter(node => 
            node.type === 'event' && node.subtype === 'start'
        );
        
        if (startNodes.length === 0) {
            errors.push('Process must have a start event');
        } else if (startNodes.length > 1) {
            errors.push('Process can only have one start event');
        }
        
        // Check for end node
        const endNodes = graph.nodes.filter(node => 
            node.type === 'event' && node.subtype === 'end'
        );
        
        if (endNodes.length === 0) {
            errors.push('Process must have at least one end event');
        }
        
        // Check for disconnected nodes
        graph.nodes.forEach(node => {
            const hasIncoming = graph.edges.some(edge => edge.target === node.id);
            const hasOutgoing = graph.edges.some(edge => edge.source === node.id);
            
            if (!hasIncoming && node.type !== 'event') {
                errors.push(`Node "${node.label}" has no incoming connections`);
            }
            
            if (!hasOutgoing && node.subtype !== 'end') {
                errors.push(`Node "${node.label}" has no outgoing connections`);
            }
        });
        
        // Show validation results
        if (errors.length === 0) {
            this.showMessage('Process validation passed!', 'success');
        } else {
            this.showMessage(`Validation failed:\n${errors.join('\n')}`, 'error');
        }
        
        return errors.length === 0;
    }
    
    saveProcess() {
        if (!this.options.saveUrl) {
            this.showMessage('Save URL not configured', 'error');
            return;
        }
        
        const graph = this.getProcessGraph();
        
        fetch(this.options.saveUrl, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({
                process_graph: graph
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.result) {
                this.showMessage('Process saved successfully!', 'success');
            } else {
                this.showMessage('Failed to save process', 'error');
            }
        })
        .catch(error => {
            console.error('Save error:', error);
            this.showMessage('Error saving process', 'error');
        });
    }
    
    showMessage(message, type) {
        // Create and show toast notification
        const toast = document.createElement('div');
        toast.className = `alert alert-${type === 'success' ? 'success' : 'danger'} designer-toast`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            min-width: 300px;
            opacity: 0;
            transition: opacity 0.3s;
        `;
        
        document.body.appendChild(toast);
        
        // Animate in
        setTimeout(() => {
            toast.style.opacity = '1';
        }, 100);
        
        // Remove after 3 seconds
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
            }, 300);
        }, 3000);
    }
    
    getCSRFToken() {
        const tokenElement = document.querySelector('meta[name=csrf-token]');
        return tokenElement ? tokenElement.getAttribute('content') : '';
    }
    
    deleteSelectedNode() {
        if (this.selectedNode) {
            this.deleteNode(this.selectedNode);
        }
    }
    
    zoomToFit() {
        // Calculate bounds of all nodes
        const nodes = Array.from(this.nodes.values());
        if (nodes.length === 0) return;
        
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        
        nodes.forEach(node => {
            minX = Math.min(minX, node.x);
            minY = Math.min(minY, node.y);
            maxX = Math.max(maxX, node.x + node.width);
            maxY = Math.max(maxY, node.y + node.height);
        });
        
        // Add padding
        const padding = 50;
        minX -= padding;
        minY -= padding;
        maxX += padding;
        maxY += padding;
        
        // Calculate scale and offset
        const canvasRect = this.canvas.getBoundingClientRect();
        const contentWidth = maxX - minX;
        const contentHeight = maxY - minY;
        const scale = Math.min(
            canvasRect.width / contentWidth,
            canvasRect.height / contentHeight,
            1
        );
        
        // Apply transform (simplified version - real implementation would need proper pan/zoom)
        this.canvas.style.transform = `scale(${scale})`;
        this.canvas.style.transformOrigin = `${minX}px ${minY}px`;
    }
    
    // Advanced keyboard shortcuts
    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            
            switch (e.key) {
                case 'Delete':
                case 'Backspace':
                    e.preventDefault();
                    this.deleteSelected();
                    break;
                case 'z':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        if (e.shiftKey) {
                            this.redo();
                        } else {
                            this.undo();
                        }
                    }
                    break;
                case 'c':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.copy();
                    }
                    break;
                case 'v':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.paste();
                    }
                    break;
                case 'a':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.selectAll();
                    }
                    break;
                case 'Escape':
                    this.clearSelection();
                    this.hideContextMenu();
                    break;
                case '+':
                case '=':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.zoomIn();
                    }
                    break;
                case '-':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.zoomOut();
                    }
                    break;
                case '0':
                    if (e.ctrlKey || e.metaKey) {
                        e.preventDefault();
                        this.resetZoom();
                    }
                    break;
            }
        });
    }
    
    // Enhanced Undo/Redo system
    saveState() {
        const state = {
            nodes: new Map(this.nodes),
            edges: new Map(this.edges),
            timestamp: Date.now()
        };
        
        this.undoStack.push(state);
        if (this.undoStack.length > this.maxUndoStack) {
            this.undoStack.shift();
        }
        
        // Clear redo stack when new action is performed
        this.redoStack = [];
        
        this.updateUndoRedoButtons();
    }
    
    undo() {
        if (this.undoStack.length === 0) return;
        
        // Save current state to redo stack
        const currentState = {
            nodes: new Map(this.nodes),
            edges: new Map(this.edges),
            timestamp: Date.now()
        };
        this.redoStack.push(currentState);
        
        // Restore previous state
        const previousState = this.undoStack.pop();
        this.nodes = new Map(previousState.nodes);
        this.edges = new Map(previousState.edges);
        
        this.render();
        this.updateUndoRedoButtons();
        this.showMessage('Undo successful', 'info');
    }
    
    redo() {
        if (this.redoStack.length === 0) return;
        
        // Save current state to undo stack
        const currentState = {
            nodes: new Map(this.nodes),
            edges: new Map(this.edges),
            timestamp: Date.now()
        };
        this.undoStack.push(currentState);
        
        // Restore next state
        const nextState = this.redoStack.pop();
        this.nodes = new Map(nextState.nodes);
        this.edges = new Map(nextState.edges);
        
        this.render();
        this.updateUndoRedoButtons();
        this.showMessage('Redo successful', 'info');
    }
    
    updateUndoRedoButtons() {
        const undoBtn = document.querySelector('[data-action="undo"]');
        const redoBtn = document.querySelector('[data-action="redo"]');
        
        if (undoBtn) {
            undoBtn.disabled = this.undoStack.length === 0;
        }
        if (redoBtn) {
            redoBtn.disabled = this.redoStack.length === 0;
        }
    }
    
    // Enhanced selection management
    selectAll() {
        this.multiSelection = Array.from(this.nodes.keys());
        this.updateSelectionDisplay();
    }
    
    clearSelection() {
        this.selectedNode = null;
        this.selectedEdge = null;
        this.multiSelection = [];
        this.updateSelectionDisplay();
    }
    
    updateSelectionDisplay() {
        // Remove previous selection styles
        document.querySelectorAll('.canvas-node.selected, .connection-line.selected').forEach(el => {
            el.classList.remove('selected', 'primary-selection');
        });
        
        // Apply selection styles
        this.multiSelection.forEach(nodeId => {
            const element = document.getElementById(nodeId);
            if (element) element.classList.add('selected');
        });
        
        if (this.selectedNode) {
            const element = document.getElementById(this.selectedNode);
            if (element) element.classList.add('selected', 'primary-selection');
        }
        
        if (this.selectedEdge) {
            const element = document.getElementById(this.selectedEdge);
            if (element) element.classList.add('selected');
        }
    }
    
    // Advanced copy/paste functionality
    copy() {
        if (this.multiSelection.length > 0 || this.selectedNode) {
            const selectedNodes = this.multiSelection.length > 0 ? 
                this.multiSelection : [this.selectedNode];
            
            this.clipboard = {
                nodes: selectedNodes.map(nodeId => {
                    const node = this.nodes.get(nodeId);
                    return { ...node };
                }),
                timestamp: Date.now()
            };
            
            this.showMessage(`Copied ${selectedNodes.length} node(s)`, 'success');
        }
    }
    
    paste() {
        if (!this.clipboard || !this.clipboard.nodes) return;
        
        const pastedNodes = [];
        const offset = 50; // Offset pasted nodes
        
        this.clipboard.nodes.forEach((nodeToCopy, index) => {
            const newNode = {
                ...nodeToCopy,
                id: `node_${this.nextNodeId++}`,
                x: nodeToCopy.x + offset,
                y: nodeToCopy.y + offset,
                label: `${nodeToCopy.label} (Copy)`
            };
            
            this.nodes.set(newNode.id, newNode);
            pastedNodes.push(newNode.id);
        });
        
        // Select pasted nodes
        this.multiSelection = pastedNodes;
        this.selectedNode = pastedNodes[0];
        
        this.render();
        this.saveState();
        this.showMessage(`Pasted ${pastedNodes.length} node(s)`, 'success');
    }
    
    // Context menu system
    showContextMenu(e, nodeId = null) {
        e.preventDefault();
        this.hideContextMenu();
        
        const menu = document.createElement('div');
        menu.className = 'context-menu';
        menu.style.cssText = `
            position: fixed;
            left: ${e.clientX}px;
            top: ${e.clientY}px;
            background: white;
            border: 1px solid #ccc;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10000;
            min-width: 180px;
            font-size: 14px;
        `;
        
        const actions = nodeId ? this.getNodeContextActions(nodeId) : this.getCanvasContextActions();
        
        actions.forEach((action, index) => {
            const item = document.createElement('div');
            item.className = 'context-menu-item';
            item.innerHTML = `
                <span class="context-icon">${action.icon || '•'}</span>
                <span class="context-label">${action.label}</span>
                ${action.shortcut ? `<span class="context-shortcut">${action.shortcut}</span>` : ''}
            `;
            item.style.cssText = `
                padding: 10px 15px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: space-between;
                transition: background 0.2s;
                ${index < actions.length - 1 ? 'border-bottom: 1px solid #f0f0f0;' : ''}
            `;
            
            item.addEventListener('mouseenter', () => {
                item.style.background = '#f8f9fa';
            });
            
            item.addEventListener('mouseleave', () => {
                item.style.background = 'white';
            });
            
            item.addEventListener('click', () => {
                action.action();
                this.hideContextMenu();
            });
            
            menu.appendChild(item);
        });
        
        document.body.appendChild(menu);
        this.contextMenu = menu;
        
        // Hide menu when clicking outside
        setTimeout(() => {
            document.addEventListener('click', this.hideContextMenu.bind(this), { once: true });
        }, 100);
    }
    
    hideContextMenu() {
        if (this.contextMenu) {
            this.contextMenu.remove();
            this.contextMenu = null;
        }
    }
    
    getNodeContextActions(nodeId) {
        const node = this.nodes.get(nodeId);
        const actions = [
            { label: 'Edit Properties', icon: '⚙️', action: () => this.editNodeProperties(nodeId), shortcut: 'Enter' },
            { label: 'Copy', icon: '📋', action: () => { this.selectedNode = nodeId; this.copy(); }, shortcut: 'Ctrl+C' },
            { label: 'Delete', icon: '🗑️', action: () => this.deleteNode(nodeId), shortcut: 'Del' },
        ];
        
        if (node.type === 'pool') {
            actions.splice(1, 0, 
                { label: 'Add Lane', icon: '➕', action: () => this.addLaneToPool(nodeId) },
                { label: 'Configure Pool', icon: '🏊‍♂️', action: () => this.configurePool(nodeId) }
            );
        }
        
        if (node.type === 'subprocess') {
            actions.splice(1, 0,
                { label: 'Edit Subprocess', icon: '📝', action: () => this.editSubprocess(nodeId) },
                { label: 'Configure Execution', icon: '⚡', action: () => this.configureSubprocessExecution(nodeId) }
            );
        }
        
        return actions;
    }
    
    getCanvasContextActions() {
        return [
            { label: 'Paste', icon: '📋', action: () => this.paste(), shortcut: 'Ctrl+V' },
            { label: 'Select All', icon: '🔘', action: () => this.selectAll(), shortcut: 'Ctrl+A' },
            { label: 'Auto Layout', icon: '📐', action: () => this.performAutoLayout() },
            { label: 'Zoom to Fit', icon: '🔍', action: () => this.zoomToFit() },
            { label: 'Validate Process', icon: '✅', action: () => this.validateAndShowResults() },
        ];
    }
    
    // Enhanced Pool/Lane management with beautiful dialogs
    configurePool(poolId) {
        const pool = this.nodes.get(poolId);
        if (!pool || pool.type !== 'pool') return;
        
        this.showPoolConfigDialog(pool);
    }
    
    showPoolConfigDialog(pool) {
        const dialog = document.createElement('div');
        dialog.className = 'pool-config-dialog';
        dialog.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: white;
            padding: 0;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.12);
            z-index: 10001;
            min-width: 500px;
            max-height: 80vh;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        `;
        
        dialog.innerHTML = `
            <div class="dialog-header" style="
                background: linear-gradient(135deg, #007bff, #0056b3);
                color: white;
                padding: 20px;
                margin: 0;
            ">
                <h3 style="margin: 0; font-size: 18px; font-weight: 600;">
                    🏊‍♂️ Configure Pool: ${pool.label}
                </h3>
            </div>
            <div class="dialog-body" style="padding: 20px; max-height: 60vh; overflow-y: auto;">
                <div class="form-group" style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 500; color: #333;">Pool Name:</label>
                    <input type="text" class="form-control" value="${pool.label}" id="pool-name" style="
                        width: 100%;
                        padding: 12px;
                        border: 2px solid #e9ecef;
                        border-radius: 8px;
                        font-size: 14px;
                        transition: border-color 0.3s;
                    ">
                </div>
                <div class="form-group" style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 500; color: #333;">Organization:</label>
                    <input type="text" class="form-control" value="${pool.properties?.organization || ''}" id="pool-org" style="
                        width: 100%;
                        padding: 12px;
                        border: 2px solid #e9ecef;
                        border-radius: 8px;
                        font-size: 14px;
                        transition: border-color 0.3s;
                    ">
                </div>
                <div class="form-group" style="margin-bottom: 20px;">
                    <label style="display: block; margin-bottom: 8px; font-weight: 500; color: #333;">Pool Type:</label>
                    <select class="form-control" id="pool-type" style="
                        width: 100%;
                        padding: 12px;
                        border: 2px solid #e9ecef;
                        border-radius: 8px;
                        font-size: 14px;
                        background: white;
                    ">
                        <option value="participant" ${pool.properties?.pool_type === 'participant' ? 'selected' : ''}>👤 Participant</option>
                        <option value="system" ${pool.properties?.pool_type === 'system' ? 'selected' : ''}>🖥️ System</option>
                    </select>
                </div>
                <div class="form-group">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <h4 style="margin: 0; color: #333; font-size: 16px; font-weight: 600;">🏊‍♂️ Lanes</h4>
                        <button type="button" class="btn btn-sm btn-outline-primary" id="add-lane" style="
                            padding: 6px 12px;
                            border: 2px solid #007bff;
                            background: transparent;
                            color: #007bff;
                            border-radius: 6px;
                            font-size: 12px;
                            cursor: pointer;
                            transition: all 0.3s;
                        ">➕ Add Lane</button>
                    </div>
                    <div id="lanes-list" style="max-height: 200px; overflow-y: auto;"></div>
                </div>
            </div>
            <div class="dialog-footer" style="
                padding: 20px;
                border-top: 1px solid #e9ecef;
                display: flex;
                justify-content: flex-end;
                gap: 12px;
                background: #f8f9fa;
                margin: 0;
            ">
                <button type="button" class="btn btn-secondary" id="cancel-pool" style="
                    padding: 10px 20px;
                    border: none;
                    background: #6c757d;
                    color: white;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: background 0.3s;
                ">Cancel</button>
                <button type="button" class="btn btn-primary" id="save-pool" style="
                    padding: 10px 20px;
                    border: none;
                    background: #007bff;
                    color: white;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: background 0.3s;
                ">💾 Save Pool</button>
            </div>
        `;
        
        // Render lanes list with enhanced styling
        const lanesList = dialog.querySelector('#lanes-list');
        (pool.lanes || []).forEach((lane, index) => {
            const laneDiv = document.createElement('div');
            laneDiv.className = 'lane-config';
            laneDiv.style.cssText = `
                background: #f8f9fa;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 12px;
                transition: border-color 0.3s;
            `;
            laneDiv.innerHTML = `
                <div class="form-row" style="display: flex; gap: 12px; align-items: center;">
                    <input type="text" placeholder="Lane Name" value="${lane.name}" data-lane="${index}" data-field="name" style="
                        flex: 1;
                        padding: 8px 12px;
                        border: 1px solid #dee2e6;
                        border-radius: 6px;
                        font-size: 13px;
                    ">
                    <input type="text" placeholder="Role" value="${lane.role || ''}" data-lane="${index}" data-field="role" style="
                        flex: 1;
                        padding: 8px 12px;
                        border: 1px solid #dee2e6;
                        border-radius: 6px;
                        font-size: 13px;
                    ">
                    <button type="button" class="btn btn-sm btn-danger" data-action="delete-lane" data-lane="${index}" style="
                        padding: 6px 10px;
                        border: none;
                        background: #dc3545;
                        color: white;
                        border-radius: 4px;
                        cursor: pointer;
                        font-size: 12px;
                    ">🗑️</button>
                </div>
            `;
            lanesList.appendChild(laneDiv);
        });
        
        // Enhanced event handlers
        dialog.querySelector('#add-lane').addEventListener('click', () => {
            this.addLaneToPoolConfig(lanesList, (pool.lanes || []).length);
        });
        
        dialog.querySelector('#save-pool').addEventListener('click', () => {
            this.savePoolConfig(dialog, pool);
        });
        
        dialog.querySelector('#cancel-pool').addEventListener('click', () => {
            dialog.remove();
        });
        
        // Input focus effects
        dialog.querySelectorAll('input, select').forEach(input => {
            input.addEventListener('focus', () => {
                input.style.borderColor = '#007bff';
                input.style.boxShadow = '0 0 0 3px rgba(0, 123, 255, 0.1)';
            });
            input.addEventListener('blur', () => {
                input.style.borderColor = '#e9ecef';
                input.style.boxShadow = 'none';
            });
        });
        
        // Button hover effects
        dialog.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('mouseenter', () => {
                btn.style.transform = 'translateY(-1px)';
                btn.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
            });
            btn.addEventListener('mouseleave', () => {
                btn.style.transform = 'translateY(0)';
                btn.style.boxShadow = 'none';
            });
        });
        
        document.body.appendChild(dialog);
        
        // Focus first input
        setTimeout(() => {
            dialog.querySelector('#pool-name').focus();
        }, 100);
    }
    
    addLaneToPoolConfig(container, index) {
        const laneDiv = document.createElement('div');
        laneDiv.className = 'lane-config';
        laneDiv.style.cssText = `
            background: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 12px;
            transition: border-color 0.3s;
            opacity: 0;
            transform: translateY(-10px);
        `;
        laneDiv.innerHTML = `
            <div class="form-row" style="display: flex; gap: 12px; align-items: center;">
                <input type="text" placeholder="Lane Name" value="Lane ${index + 1}" data-lane="${index}" data-field="name" style="
                    flex: 1;
                    padding: 8px 12px;
                    border: 1px solid #dee2e6;
                    border-radius: 6px;
                    font-size: 13px;
                ">
                <input type="text" placeholder="Role" value="" data-lane="${index}" data-field="role" style="
                    flex: 1;
                    padding: 8px 12px;
                    border: 1px solid #dee2e6;
                    border-radius: 6px;
                    font-size: 13px;
                ">
                <button type="button" class="btn btn-sm btn-danger" data-action="delete-lane" data-lane="${index}" style="
                    padding: 6px 10px;
                    border: none;
                    background: #dc3545;
                    color: white;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 12px;
                ">🗑️</button>
            </div>
        `;
        
        container.appendChild(laneDiv);
        
        // Animate in
        setTimeout(() => {
            laneDiv.style.opacity = '1';
            laneDiv.style.transform = 'translateY(0)';
        }, 10);
        
        // Focus first input
        setTimeout(() => {
            laneDiv.querySelector('input').focus();
        }, 100);
    }
    
    savePoolConfig(dialog, pool) {
        // Update pool properties
        pool.label = dialog.querySelector('#pool-name').value;
        pool.properties = pool.properties || {};
        pool.properties.organization = dialog.querySelector('#pool-org').value;
        pool.properties.pool_type = dialog.querySelector('#pool-type').value;
        
        // Update lanes
        const laneInputs = dialog.querySelectorAll('[data-lane]');
        const lanes = {};
        
        laneInputs.forEach(input => {
            const laneIndex = input.dataset.lane;
            const field = input.dataset.field;
            
            if (!lanes[laneIndex]) {
                lanes[laneIndex] = { id: `lane_${pool.id}_${laneIndex}` };
            }
            
            lanes[laneIndex][field] = input.value;
        });
        
        pool.lanes = Object.values(lanes);
        
        // Re-render and save
        this.renderNode(pool);
        this.renderPoolLanes(pool);
        this.saveState();
        
        dialog.remove();
        this.showMessage('🎉 Pool configuration saved successfully!', 'success');
    }
    
    // Enhanced validation with beautiful results dialog
    validateAndShowResults() {
        const validation = this.validateProcess();
        this.showValidationResults(validation.errors, validation.warnings);
    }
    
    validateProcess() {
        const errors = [];
        const warnings = [];
        
        // Check for start/end nodes
        const startNodes = Array.from(this.nodes.values()).filter(n => n.type === 'start');
        const endNodes = Array.from(this.nodes.values()).filter(n => n.type === 'end');
        
        if (startNodes.length === 0) {
            errors.push('Process must have at least one start event');
        }
        if (endNodes.length === 0) {
            warnings.push('Process should have at least one end event');
        }
        
        // Check node connections
        this.nodes.forEach((node, nodeId) => {
            const incomingEdges = Array.from(this.edges.values()).filter(e => e.target === nodeId);
            const outgoingEdges = Array.from(this.edges.values()).filter(e => e.source === nodeId);
            
            if (node.type === 'start' && incomingEdges.length > 0) {
                errors.push(`Start event '${node.label}' cannot have incoming connections`);
            }
            
            if (node.type === 'end' && outgoingEdges.length > 0) {
                errors.push(`End event '${node.label}' cannot have outgoing connections`);
            }
            
            if (node.type === 'task' && incomingEdges.length === 0 && startNodes.every(s => s.id !== nodeId)) {
                warnings.push(`Task '${node.label}' has no incoming connections`);
            }
            
            if (node.type === 'gateway' && (incomingEdges.length === 0 || outgoingEdges.length < 2)) {
                warnings.push(`Gateway '${node.label}' should have incoming and multiple outgoing connections`);
            }
        });
        
        // Check subprocess configurations
        this.nodes.forEach((node, nodeId) => {
            if (node.type === 'subprocess') {
                if (!node.properties?.target_definition_id && node.subtype === 'call_activity') {
                    errors.push(`Call Activity '${node.label}' must reference a target process definition`);
                }
            }
        });
        
        // Check pool/lane assignments
        this.nodes.forEach((node, nodeId) => {
            if (node.type === 'pool') {
                if (!node.lanes || node.lanes.length === 0) {
                    warnings.push(`Pool '${node.label}' has no lanes defined`);
                } else {
                    node.lanes.forEach((lane, index) => {
                        if (!lane.role) {
                            warnings.push(`Lane ${index + 1} in pool '${node.label}' has no role assigned`);
                        }
                    });
                }
            }
        });
        
        this.validationErrors = errors;
        this.validationWarnings = warnings;
        
        return { errors, warnings };
    }
    
    showValidationResults(errors, warnings) {
        const dialog = document.createElement('div');
        dialog.className = 'validation-dialog';
        dialog.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: white;
            padding: 0;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.12);
            z-index: 10001;
            max-width: 600px;
            max-height: 80vh;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        `;
        
        const hasIssues = errors.length > 0 || warnings.length > 0;
        const headerColor = errors.length > 0 ? '#dc3545' : warnings.length > 0 ? '#ffc107' : '#28a745';
        const headerIcon = errors.length > 0 ? '❌' : warnings.length > 0 ? '⚠️' : '✅';
        
        let content = `
            <div class="dialog-header" style="
                background: linear-gradient(135deg, ${headerColor}, ${headerColor}dd);
                color: white;
                padding: 20px;
                margin: 0;
            ">
                <h3 style="margin: 0; font-size: 18px; font-weight: 600;">
                    ${headerIcon} Process Validation Results
                </h3>
            </div>
            <div class="dialog-body" style="padding: 20px; max-height: 50vh; overflow-y: auto;">
        `;
        
        if (errors.length > 0) {
            content += `
                <div class="validation-errors" style="margin-bottom: 20px;">
                    <h4 style="color: #dc3545; font-size: 16px; font-weight: 600; margin-bottom: 12px;">
                        🚨 Errors (${errors.length})
                    </h4>
                    <ul style="margin: 0; padding-left: 20px; color: #dc3545;">
            `;
            errors.forEach(error => {
                content += `<li style="margin-bottom: 8px; line-height: 1.4;">${error}</li>`;
            });
            content += '</ul></div>';
        }
        
        if (warnings.length > 0) {
            content += `
                <div class="validation-warnings">
                    <h4 style="color: #ffc107; font-size: 16px; font-weight: 600; margin-bottom: 12px;">
                        ⚠️ Warnings (${warnings.length})
                    </h4>
                    <ul style="margin: 0; padding-left: 20px; color: #856404;">
            `;
            warnings.forEach(warning => {
                content += `<li style="margin-bottom: 8px; line-height: 1.4;">${warning}</li>`;
            });
            content += '</ul></div>';
        }
        
        if (!hasIssues) {
            content += `
                <div style="text-align: center; color: #28a745; padding: 20px;">
                    <div style="font-size: 48px; margin-bottom: 16px;">🎉</div>
                    <h4 style="margin-bottom: 8px; font-size: 18px;">Process validation passed!</h4>
                    <p style="margin: 0; color: #6c757d;">No errors or warnings found. Your process is ready to deploy.</p>
                </div>
            `;
        }
        
        content += `
            </div>
            <div class="dialog-footer" style="
                padding: 20px;
                border-top: 1px solid #e9ecef;
                display: flex;
                justify-content: flex-end;
                gap: 12px;
                background: #f8f9fa;
                margin: 0;
            ">
                <button type="button" class="btn btn-primary" id="close-validation" style="
                    padding: 10px 20px;
                    border: none;
                    background: #007bff;
                    color: white;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    transition: all 0.3s;
                ">✓ Close</button>
            </div>
        `;
        
        dialog.innerHTML = content;
        
        dialog.querySelector('#close-validation').addEventListener('click', () => {
            dialog.remove();
        });
        
        // Button hover effects
        dialog.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('mouseenter', () => {
                btn.style.transform = 'translateY(-1px)';
                btn.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
            });
            btn.addEventListener('mouseleave', () => {
                btn.style.transform = 'translateY(0)';
                btn.style.boxShadow = 'none';
            });
        });
        
        document.body.appendChild(dialog);
    }
    
    // Enhanced initialization
    init() {
        this.setupCanvas();
        this.setupKeyboardShortcuts();
        this.setupContextMenu();
        this.setupAdvancedFeatures();
        this.render();
        this.updateUndoRedoButtons();
        
        // Show welcome message
        setTimeout(() => {
            this.showMessage('🎨 Enhanced Process Designer loaded successfully!', 'success');
        }, 500);
    }
    
    setupContextMenu() {
        // Right-click context menu
        this.canvas.addEventListener('contextmenu', (e) => {
            const nodeElement = e.target.closest('.canvas-node');
            if (nodeElement) {
                this.showContextMenu(e, nodeElement.id);
            } else {
                this.showContextMenu(e);
            }
        });
    }
    
    setupAdvancedFeatures() {
        // Enhanced zoom controls
        this.canvas.addEventListener('wheel', (e) => {
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                this.zoomLevel = Math.min(Math.max(this.zoomLevel * delta, this.minZoom), this.maxZoom);
                this.applyZoom();
            }
        });
        
        // Auto-save functionality
        setInterval(() => {
            if (this.options.autoSave && this.hasUnsavedChanges) {
                this.saveProcess();
                this.hasUnsavedChanges = false;
            }
        }, 30000); // Auto-save every 30 seconds
    }
    
    deleteSelected() {
        if (this.multiSelection.length > 0) {
            this.multiSelection.forEach(nodeId => this.deleteNode(nodeId));
            this.multiSelection = [];
        } else if (this.selectedNode) {
            this.deleteNode(this.selectedNode);
            this.selectedNode = null;
        } else if (this.selectedEdge) {
            this.deleteEdge(this.selectedEdge);
            this.selectedEdge = null;
        }
        this.updateSelectionDisplay();
        this.saveState();
    }
    
    // Enhanced zoom controls
    zoomIn() {
        this.zoomLevel = Math.min(this.zoomLevel * 1.2, this.maxZoom);
        this.applyZoom();
    }
    
    zoomOut() {
        this.zoomLevel = Math.max(this.zoomLevel / 1.2, this.minZoom);
        this.applyZoom();
    }
    
    resetZoom() {
        this.zoomLevel = 1.0;
        this.applyZoom();
    }
    
    applyZoom() {
        this.canvas.style.transform = `scale(${this.zoomLevel})`;
        this.canvas.style.transformOrigin = 'center center';
        
        // Update zoom display if exists
        const zoomDisplay = document.querySelector('.zoom-display');
        if (zoomDisplay) {
            zoomDisplay.textContent = `${Math.round(this.zoomLevel * 100)}%`;
        }
    }
    
    // Auto-layout algorithm (enhanced)
    performAutoLayout() {
        const nodes = Array.from(this.nodes.values());
        if (nodes.length === 0) return;
        
        // More sophisticated hierarchical layout
        const levels = this.calculateNodeLevels();
        const levelWidth = 250;
        const levelHeight = 150;
        const padding = 100;
        
        Object.keys(levels).forEach(level => {
            const nodesInLevel = levels[level];
            const levelY = parseInt(level) * levelHeight + padding;
            const totalWidth = (nodesInLevel.length - 1) * levelWidth;
            const startX = -totalWidth / 2 + 400; // Center horizontally
            
            nodesInLevel.forEach((nodeId, index) => {
                const node = this.nodes.get(nodeId);
                if (node) {
                    node.x = startX + (index * levelWidth);
                    node.y = levelY;
                }
            });
        });
        
        this.render();
        this.saveState();
        this.showMessage('✨ Auto layout applied with enhanced positioning!', 'success');
    }
    
    calculateNodeLevels() {
        const levels = { 0: [] };
        const visited = new Set();
        const nodeConnections = new Map();
        
        // Build connection map
        this.edges.forEach(edge => {
            if (!nodeConnections.has(edge.source)) {
                nodeConnections.set(edge.source, []);
            }
            nodeConnections.get(edge.source).push(edge.target);
        });
        
        // Find start nodes (nodes with no incoming edges)
        const incomingEdges = new Set();
        this.edges.forEach(edge => incomingEdges.add(edge.target));
        
        const startNodes = Array.from(this.nodes.keys()).filter(id => !incomingEdges.has(id));
        
        if (startNodes.length === 0 && this.nodes.size > 0) {
            // If no clear start, use first node
            startNodes.push(Array.from(this.nodes.keys())[0]);
        }
        
        // Assign levels using BFS
        const queue = startNodes.map(id => ({ id, level: 0 }));
        startNodes.forEach(id => levels[0].push(id));
        
        while (queue.length > 0) {
            const { id, level } = queue.shift();
            
            if (visited.has(id)) continue;
            visited.add(id);
            
            const connections = nodeConnections.get(id) || [];
            connections.forEach(targetId => {
                if (!visited.has(targetId)) {
                    const targetLevel = level + 1;
                    if (!levels[targetLevel]) {
                        levels[targetLevel] = [];
                    }
                    if (!levels[targetLevel].includes(targetId)) {
                        levels[targetLevel].push(targetId);
                        queue.push({ id: targetId, level: targetLevel });
                    }
                }
            });
        }
        
        // Add any remaining nodes to level 0
        Array.from(this.nodes.keys()).forEach(id => {
            if (!visited.has(id)) {
                levels[0].push(id);
            }
        });
        
        return levels;
    }
}

// Make ProcessDesigner globally available
window.ProcessDesigner = ProcessDesigner;