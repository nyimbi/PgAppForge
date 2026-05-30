"""
Main Collaboration Manager

Central coordinator for all collaboration features, integrating WebSocket management,
session handling, conflict resolution, and data synchronization.
"""

import logging
from typing import Optional, Dict, Any
from flask import Flask

from .websocket_manager import create_websocket_manager
from .session_manager import CollaborationSessionManager
from .sync_engine import RealtimeDataSyncEngine
from .conflict_resolver import ConflictResolutionEngine
from .security_integration import CollaborationSecurityManager

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

log = logging.getLogger(__name__)


class CollaborationManager:
    """
    Central manager coordinating all real-time collaboration features.
    
    Integrates WebSocket communication, session management, data synchronization,
    and conflict resolution into a cohesive collaboration system.
    """
    
    def __init__(self, app: Optional[Flask] = None, db_session=None, security_manager=None):
        self.app = app
        self.db = db_session
        self.security_manager = security_manager
        
        # Core components
        self.websocket_manager = None
        self.session_manager = None
        self.sync_engine = None
        self.conflict_resolver = None
        self.security_integration = None
        
        # Redis client for scaling
        self.redis_client = None
        
        # Configuration
        self.config = {}
        
        if app:
            self.init_app(app)
            
    def init_app(self, app: Flask):
        """Initialize collaboration system with Flask application"""
        try:
            self.app = app
            
            # Load configuration
            self.config = {
                'COLLABORATION_ENABLED': app.config.get('COLLABORATION_ENABLED', True),
                'COLLABORATION_WEBSOCKET_URL': app.config.get('COLLABORATION_WEBSOCKET_URL', '/collaboration'),
                'COLLABORATION_SESSION_TIMEOUT': app.config.get('COLLABORATION_SESSION_TIMEOUT', 3600),
                'COLLABORATION_AUTO_RESOLVE_THRESHOLD': app.config.get('COLLABORATION_AUTO_RESOLVE_THRESHOLD', 0.8),
                'COLLABORATION_MAX_PARTICIPANTS': app.config.get('COLLABORATION_MAX_PARTICIPANTS', 50),
                'COLLABORATION_REDIS_URL': app.config.get('COLLABORATION_REDIS_URL', 'redis://localhost:6379'),
                'COLLABORATION_CONFLICT_STRATEGY': app.config.get('COLLABORATION_CONFLICT_STRATEGY', 'auto')
            }
            
            if not self.config['COLLABORATION_ENABLED']:
                log.info("Collaboration features disabled by configuration")
                return
                
            # Initialize Redis client if available
            self._init_redis()
            
            # Initialize security integration first
            self._init_security_integration()
            
            # Initialize core components
            self._init_websocket_manager()
            self._init_session_manager()
            self._init_sync_engine()
            self._init_conflict_resolver()
            
            # Set up component integration
            self._integrate_components()
            
            # Register Flask routes
            self._register_routes()
            
            log.info("Collaboration manager initialized successfully")
            
        except Exception as e:
            log.error(f"Error initializing collaboration manager: {e}")
            self.config['COLLABORATION_ENABLED'] = False
            
    def _init_redis(self):
        """Initialize Redis client for scaling and caching"""
        try:
            if REDIS_AVAILABLE and self.config.get('COLLABORATION_REDIS_URL'):
                self.redis_client = redis.from_url(self.config['COLLABORATION_REDIS_URL'])
                # Test connection
                self.redis_client.ping()
                log.info("Redis client initialized for collaboration")
            else:
                log.warning("Redis not available - collaboration will use in-memory storage")
                
        except Exception as e:
            log.error(f"Error initializing Redis client: {e}")
            self.redis_client = None
            
    def _init_security_integration(self):
        """Initialize security integration"""
        try:
            if self.security_manager:
                self.security_integration = CollaborationSecurityManager(
                    security_manager=self.security_manager,
                    db_session=self.db
                )
                
                # Create default roles and permissions
                self.security_integration.create_default_roles()
                log.info("Security integration initialized")
            else:
                log.warning("No security manager available - collaboration security disabled")
                
        except Exception as e:
            log.error(f"Error initializing security integration: {e}")
            self.security_integration = None
            
    def _init_websocket_manager(self):
        """Initialize WebSocket manager"""
        try:
            self.websocket_manager = create_websocket_manager(
                app=self.app,
                security_manager=self.security_manager
            )
            log.info("WebSocket manager initialized")
            
        except Exception as e:
            log.error(f"Error initializing WebSocket manager: {e}")
            
    def _init_session_manager(self):
        """Initialize session manager"""
        try:
            self.session_manager = CollaborationSessionManager(
                db_session=self.db,
                redis_client=self.redis_client,
                websocket_manager=self.websocket_manager
            )
            log.info("Session manager initialized")
            
        except Exception as e:
            log.error(f"Error initializing session manager: {e}")
            
    def _init_sync_engine(self):
        """Initialize data synchronization engine"""
        try:
            self.sync_engine = RealtimeDataSyncEngine(
                websocket_manager=self.websocket_manager,
                session_manager=self.session_manager,
                db_session=self.db
            )
            log.info("Sync engine initialized")
            
        except Exception as e:
            log.error(f"Error initializing sync engine: {e}")
            
    def _init_conflict_resolver(self):
        """Initialize conflict resolution engine"""
        try:
            self.conflict_resolver = ConflictResolutionEngine(
                session_manager=self.session_manager,
                db_session=self.db,
                websocket_manager=self.websocket_manager
            )
            log.info("Conflict resolver initialized")
            
        except Exception as e:
            log.error(f"Error initializing conflict resolver: {e}")
            
    def _integrate_components(self):
        """Set up integration between components"""
        try:
            # Connect sync engine to conflict resolver
            if self.sync_engine and self.conflict_resolver:
                self.sync_engine.register_event_handler('conflict_detected', 
                    lambda event: self._handle_sync_conflict(event))
                    
            # Connect WebSocket events to session management
            if self.websocket_manager and self.session_manager:
                self.websocket_manager.register_event_handler('user_disconnected',
                    lambda user_id: self._handle_user_disconnect(user_id))
                    
            log.info("Component integration completed")
            
        except Exception as e:
            log.error(f"Error integrating components: {e}")
            
    def _register_routes(self):
        """Register Flask routes for collaboration API"""
        try:
            if not self.app:
                return
                
            from flask import Blueprint, request, jsonify, g
            from functools import wraps
            
            def require_collaboration_permission(permission_name):
                """Decorator to check collaboration permissions"""
                def decorator(f):
                    @wraps(f)
                    def decorated_function(*args, **kwargs):
                        if not self.security_integration:
                            return jsonify({'error': 'Security not available'}), 503
                        
                        if not hasattr(g, 'user') or not g.user:
                            return jsonify({'error': 'Authentication required'}), 401
                        
                        if not self.security_integration.check_collaboration_permission(permission_name):
                            return jsonify({'error': 'Permission denied'}), 403
                        
                        return f(*args, **kwargs)
                    return decorated_function
                return decorator
            
            # Create collaboration blueprint
            collab_bp = Blueprint('collaboration', __name__, url_prefix='/api/collaboration')
            
            @collab_bp.route('/status')
            @require_collaboration_permission('can_collaborate')
            def collaboration_status():
                """Get overall collaboration system status"""
                user_info = self.security_integration.get_user_collaboration_info() if self.security_integration else {}
                
                return jsonify({
                    'enabled': self.config.get('COLLABORATION_ENABLED', False),
                    'websocket_url': self.config.get('COLLABORATION_WEBSOCKET_URL'),
                    'user_info': user_info,
                    'components': {
                        'websocket_manager': self.websocket_manager is not None,
                        'session_manager': self.session_manager is not None,
                        'sync_engine': self.sync_engine is not None,
                        'conflict_resolver': self.conflict_resolver is not None,
                        'security_integration': self.security_integration is not None,
                        'redis_client': self.redis_client is not None
                    },
                    'stats': self._get_system_stats()
                })
                
            @collab_bp.route('/sessions/active')
            @require_collaboration_permission('can_view_participants')
            def get_active_sessions():
                """Get list of active collaboration sessions"""
                try:
                    if not self.security_integration:
                        return jsonify({'error': 'Security not available'}), 503
                    
                    # Get user's accessible sessions
                    user_info = self.security_integration.get_user_collaboration_info()
                    active_sessions = user_info.get('active_sessions', [])
                    
                    # Get detailed session information
                    sessions_data = []
                    for session_id in active_sessions:
                        session_context = self.security_integration.get_session_security_context(session_id)
                        if session_context:
                            sessions_data.append(session_context)
                    
                    return jsonify({
                        'active_sessions': sessions_data,
                        'total_sessions': len(sessions_data),
                        'user_permissions': user_info.get('permissions', [])
                    })
                except Exception as e:
                    log.error(f"Error getting active sessions: {e}")
                    return jsonify({'error': str(e)}), 500
            
            @collab_bp.route('/sessions/create', methods=['POST'])
            @require_collaboration_permission('can_create_session')
            def create_collaboration_session():
                """Create a new collaboration session"""
                try:
                    if not self.security_integration:
                        return jsonify({'error': 'Security not available'}), 503
                    
                    data = request.get_json() or {}
                    model_name = data.get('model_name')
                    record_id = data.get('record_id')
                    permissions_required = data.get('permissions_required', [])
                    max_participants = data.get('max_participants', 10)
                    
                    if not model_name:
                        return jsonify({'error': 'model_name is required'}), 400
                    
                    # Create secure session
                    session_id = self.security_integration.create_secure_session(
                        model_name=model_name,
                        record_id=record_id,
                        permissions_required=permissions_required,
                        max_participants=max_participants
                    )
                    
                    if not session_id:
                        return jsonify({'error': 'Failed to create session'}), 500
                    
                    # Get session context
                    session_context = self.security_integration.get_session_security_context(session_id)
                    
                    return jsonify({
                        'session_id': session_id,
                        'session_info': session_context,
                        'websocket_url': self.get_websocket_url()
                    })
                    
                except Exception as e:
                    log.error(f"Error creating collaboration session: {e}")
                    return jsonify({'error': str(e)}), 500
            
            @collab_bp.route('/sessions/<session_id>/join', methods=['POST'])
            @require_collaboration_permission('can_join_session')
            def join_collaboration_session(session_id):
                """Join a collaboration session"""
                try:
                    if not self.security_integration:
                        return jsonify({'error': 'Security not available'}), 503
                    
                    # Validate session access
                    access_info = self.security_integration.validate_session_access(session_id)
                    
                    if not access_info.get('can_join'):
                        return jsonify({'error': 'Cannot join session'}), 403
                    
                    return jsonify({
                        'session_id': session_id,
                        'access_granted': True,
                        'user_role': access_info.get('user_role'),
                        'permissions': access_info.get('permissions', []),
                        'session_info': access_info.get('session_info'),
                        'websocket_url': self.get_websocket_url()
                    })
                    
                except Exception as e:
                    log.error(f"Error joining collaboration session: {e}")
                    return jsonify({'error': str(e)}), 500
                    
            @collab_bp.route('/health')
            def health_check():
                """Health check endpoint for collaboration services"""
                try:
                    health_status = {
                        'status': 'healthy',
                        'components': {}
                    }
                    
                    # Check WebSocket manager
                    if self.websocket_manager:
                        stats = self.websocket_manager.get_connection_stats()
                        health_status['components']['websocket'] = {
                            'status': 'healthy',
                            'connections': stats.get('total_connections', 0)
                        }
                    else:
                        health_status['components']['websocket'] = {'status': 'unavailable'}
                        
                    # Check Redis
                    if self.redis_client:
                        try:
                            self.redis_client.ping()
                            health_status['components']['redis'] = {'status': 'healthy'}
                        except:
                            health_status['components']['redis'] = {'status': 'unhealthy'}
                    else:
                        health_status['components']['redis'] = {'status': 'unavailable'}
                        
                    return jsonify(health_status)
                    
                except Exception as e:
                    return jsonify({
                        'status': 'unhealthy',
                        'error': str(e)
                    }), 500
            
            # Register blueprint
            self.app.register_blueprint(collab_bp)
            log.info("Collaboration API routes registered")
            
        except Exception as e:
            log.error(f"Error registering collaboration routes: {e}")
            
    def _handle_sync_conflict(self, event_data: Dict[str, Any]):
        """Handle conflict detected by sync engine"""
        try:
            if not self.conflict_resolver:
                return
                
            session_id = event_data.get('session_id')
            field_name = event_data.get('field_name')
            local_change = event_data.get('local_change')
            remote_change = event_data.get('remote_change')
            
            if all([session_id, field_name, local_change, remote_change]):
                # Attempt automatic conflict resolution
                resolution = self.conflict_resolver.resolve_conflict(
                    session_id=session_id,
                    field_name=field_name,
                    local_change=local_change,
                    remote_change=remote_change,
                    strategy=self.config.get('COLLABORATION_CONFLICT_STRATEGY', 'auto')
                )
                
                log.info(f"Resolved conflict in session {session_id}, field {field_name}: {resolution.get('method', 'unknown')}")
                
        except Exception as e:
            log.error(f"Error handling sync conflict: {e}")
            
    def _handle_user_disconnect(self, user_id: str):
        """Handle user disconnection cleanup"""
        try:
            if self.session_manager:
                # Clean up user from all sessions
                # This would be implemented in the session manager
                log.info(f"Cleaned up user {user_id} from collaboration sessions")
                
        except Exception as e:
            log.error(f"Error handling user disconnect: {e}")
            
    def _get_system_stats(self) -> Dict[str, Any]:
        """Get system-wide collaboration statistics"""
        try:
            stats = {
                'total_sessions': 0,
                'active_participants': 0,
                'total_conflicts': 0,
                'auto_resolution_rate': 0.0
            }
            
            # WebSocket stats
            if self.websocket_manager:
                ws_stats = self.websocket_manager.get_connection_stats()
                stats.update({
                    'websocket_connections': ws_stats.get('total_connections', 0),
                    'active_rooms': ws_stats.get('active_rooms', 0)
                })
                
            # Conflict resolution stats  
            if self.conflict_resolver:
                conflict_stats = self.conflict_resolver.get_resolution_stats()
                stats.update({
                    'total_conflicts': conflict_stats.get('total_conflicts', 0),
                    'auto_resolution_rate': conflict_stats.get('auto_resolution_rate', 0.0)
                })
                
            # Sync engine stats
            if self.sync_engine:
                sync_stats = self.sync_engine.get_sync_stats()
                stats.update({
                    'registered_models': sync_stats.get('registered_models', 0),
                    'sync_queue_size': sync_stats.get('queue_size', 0)
                })
                
            return stats
            
        except Exception as e:
            log.error(f"Error getting system stats: {e}")
            return {}
            
    def is_enabled(self) -> bool:
        """Check if collaboration is enabled"""
        return self.config.get('COLLABORATION_ENABLED', False)
        
    def get_websocket_url(self) -> str:
        """Get WebSocket URL for clients"""
        return self.config.get('COLLABORATION_WEBSOCKET_URL', '/collaboration')
        
    def shutdown(self):
        """Shutdown collaboration system gracefully"""
        try:
            # Cleanup sessions
            if self.session_manager:
                self.session_manager.cleanup_expired_sessions()
                
            # Close Redis connection
            if self.redis_client:
                self.redis_client.close()
                
            log.info("Collaboration system shut down gracefully")
            
        except Exception as e:
            log.error(f"Error during collaboration shutdown: {e}")
            
    def __del__(self):
        """Destructor to ensure cleanup"""
        try:
            self.shutdown()
        except:
            pass  # Ignore errors during cleanup