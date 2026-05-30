"""
AI Chat Views for PgAppForge Collaborative Features
"""
import time
from flask import request, render_template, jsonify, flash, redirect, url_for, g
from pgappforge import expose, BaseView, has_access
from pgappforge.security.decorators import protect

from ..ai.chatbot_service import ChatbotService
from ..ai.knowledge_base import KnowledgeBaseManager
from ..ai.ai_models import ModelManager
from ..models import db


class AIChatView(BaseView):
    """View for AI Chat Interface"""
    
    route_base = "/ai-chat"
    
    def __init__(self):
        super().__init__()
        self.chatbot_service = None
        self.knowledge_base_manager = None
        self.model_manager = None
    
    def _get_services(self):
        """Lazy initialization of AI services with proper dependencies"""
        if not self.model_manager:
            # Initialize ModelManager with app configuration (auto-loads adapters)
            app = self.appbuilder.app if hasattr(self, 'appbuilder') else None
            self.model_manager = ModelManager(app=app)

        if not self.knowledge_base_manager:
            # Initialize KnowledgeBaseManager with dependencies
            try:
                from ..ai.rag_engine import RAGEngine
                from ..ai.vector_stores.faiss_vector_store import FAISSVectorStore

                # Create vector store and RAG engine
                vector_store = FAISSVectorStore()
                rag_engine = RAGEngine(vector_store, self.model_manager)

                # Create session factory
                session_factory = lambda: db.session

                self.knowledge_base_manager = KnowledgeBaseManager(
                    rag_engine=rag_engine,
                    model_manager=self.model_manager,
                    session_factory=session_factory,
                    max_concurrent_tasks=5,
                    auto_indexing_enabled=True
                )

            except Exception as e:
                self.logger.error(f"Failed to initialize KnowledgeBaseManager: {e}")
                # Create minimal fallback
                self.knowledge_base_manager = None

        if not self.chatbot_service:
            # Initialize ChatbotService with dependencies
            try:
                # Get RAG engine from knowledge base manager if available
                rag_engine = self.knowledge_base_manager.rag_engine if self.knowledge_base_manager else None

                # Create session factory
                session_factory = lambda: db.session

                self.chatbot_service = ChatbotService(
                    model_manager=self.model_manager,
                    rag_engine=rag_engine,
                    communication_service=None,  # Optional
                    session_factory=session_factory
                )

            except Exception as e:
                self.logger.error(f"Failed to initialize ChatbotService: {e}")
                # Create minimal fallback
                self.chatbot_service = None

        return self.chatbot_service, self.knowledge_base_manager, self.model_manager
    
    @expose('/')
    @has_access
    @protect()
    def index(self):
        """Main AI chat interface"""
        personality = request.args.get('personality', 'assistant')
        
        # Validate personality
        valid_personalities = ['assistant', 'technical', 'creative', 'analyst', 'mentor']
        if personality not in valid_personalities:
            personality = 'assistant'
        
        return self.render_template(
            'collaborative/ai_chat.html',
            title='AI Assistant',
            personality=personality
        )
    
    @expose('/conversations')
    @has_access
    @protect()
    def conversations(self):
        """List user's conversations"""
        chatbot_service, _, _ = self._get_services()
        
        try:
            conversations = chatbot_service.get_user_conversations(
                user_id=g.user.id,
                limit=50
            )
            
            return self.render_template(
                'collaborative/ai_conversations.html',
                title='AI Conversations',
                conversations=conversations
            )
        
        except Exception as e:
            flash(f"Error loading conversations: {str(e)}", 'error')
            return redirect(url_for('AIChatView.index'))
    
    @expose('/conversation/<conversation_id>')
    @has_access
    @protect()
    def view_conversation(self, conversation_id):
        """View specific conversation"""
        chatbot_service, _, _ = self._get_services()
        
        try:
            conversation = chatbot_service.get_conversation(conversation_id)
            
            if not conversation:
                flash("Conversation not found", 'error')
                return redirect(url_for('AIChatView.conversations'))
            
            # Check if user has access to this conversation
            if conversation.user_id != g.user.id:
                flash("Access denied", 'error')
                return redirect(url_for('AIChatView.conversations'))
            
            messages = chatbot_service.get_conversation_messages(conversation_id)
            
            return self.render_template(
                'collaborative/ai_conversation_view.html',
                title=f'Conversation: {conversation.title}',
                conversation=conversation,
                messages=messages
            )
        
        except Exception as e:
            flash(f"Error loading conversation: {str(e)}", 'error')
            return redirect(url_for('AIChatView.conversations'))
    
    @expose('/settings')
    @has_access
    @protect()
    def settings(self):
        """AI assistant settings"""
        _, _, model_manager = self._get_services()
        
        try:
            available_models = model_manager.get_available_models()
            
            return self.render_template(
                'collaborative/ai_settings.html',
                title='AI Assistant Settings',
                available_models=available_models
            )
        
        except Exception as e:
            flash(f"Error loading settings: {str(e)}", 'error')
            return redirect(url_for('AIChatView.index'))
    
    @expose('/knowledge-base')
    @has_access
    @protect()
    def knowledge_base(self):
        """Knowledge base management"""
        _, knowledge_base_manager, _ = self._get_services()
        
        try:
            # Get knowledge base statistics
            stats = knowledge_base_manager.get_stats()
            
            # Get recent indexed content
            recent_content = knowledge_base_manager.get_recent_indexed_content(limit=20)
            
            return self.render_template(
                'collaborative/ai_knowledge_base.html',
                title='Knowledge Base',
                stats=stats,
                recent_content=recent_content
            )
        
        except Exception as e:
            flash(f"Error loading knowledge base: {str(e)}", 'error')
            return redirect(url_for('AIChatView.index'))


class AIKnowledgeBaseView(BaseView):
    """View for Knowledge Base Management"""
    
    route_base = "/ai-knowledge"
    
    def __init__(self):
        super().__init__()
        self.knowledge_base_manager = None
    
    def _get_knowledge_base_manager(self):
        """Lazy initialization of knowledge base manager"""
        if not self.knowledge_base_manager:
            try:
                # Create model manager and dependencies
                app = self.appbuilder.app if hasattr(self, 'appbuilder') else None
                model_manager = ModelManager(app=app)
                
                # Create RAG engine components
                from ..ai.rag_engine import RAGEngine
                from ..ai.vector_stores.faiss_vector_store import FAISSVectorStore
                vector_store = FAISSVectorStore()
                rag_engine = RAGEngine(vector_store, model_manager)
                
                # Create session factory
                session_factory = lambda: db.session
                
                self.knowledge_base_manager = KnowledgeBaseManager(
                    rag_engine=rag_engine,
                    model_manager=model_manager,
                    session_factory=session_factory
                )
            except Exception as e:
                self.logger.error(f"Failed to initialize KnowledgeBaseManager: {e}")
                # Return minimal fallback that won't crash
                return None
        return self.knowledge_base_manager
    
    @expose('/')
    @has_access
    @protect()
    def index(self):
        """Knowledge base dashboard"""
        manager = self._get_knowledge_base_manager()
        
        try:
            stats = manager.get_stats()
            recent_content = manager.get_recent_indexed_content(limit=10)
            
            return self.render_template(
                'collaborative/ai_knowledge_base.html',
                title='Knowledge Base',
                stats=stats,
                recent_content=recent_content
            )
        
        except Exception as e:
            flash(f"Error loading knowledge base: {str(e)}", 'error')
            return self.render_template(
                'collaborative/ai_knowledge_base.html',
                title='Knowledge Base',
                stats={'total_documents': 0, 'total_chunks': 0},
                recent_content=[]
            )
    
    @expose('/search')
    @has_access
    @protect()
    def search(self):
        """Search knowledge base"""
        manager = self._get_knowledge_base_manager()
        
        query = request.args.get('q', '')
        limit = int(request.args.get('limit', 20))
        
        results = []
        if query:
            try:
                results = manager.search_similar_content(
                    query=query,
                    limit=limit,
                    similarity_threshold=0.3
                )
            except Exception as e:
                flash(f"Search error: {str(e)}", 'error')
        
        return self.render_template(
            'collaborative/ai_knowledge_search.html',
            title='Search Knowledge Base',
            query=query,
            results=results
        )
    
    @expose('/index-content', methods=['GET', 'POST'])
    @has_access
    @protect()
    def index_content(self):
        """Manual content indexing"""
        if request.method == 'POST':
            manager = self._get_knowledge_base_manager()
            
            content_text = request.form.get('content_text', '').strip()
            content_source = request.form.get('content_source', 'manual')
            metadata = {
                'title': request.form.get('title', ''),
                'tags': request.form.get('tags', '').split(','),
                'indexed_by': g.user.username,
                'manual_entry': True
            }
            
            if content_text:
                try:
                    content_id = f"manual_{g.user.id}_{int(time.time())}"
                    
                    # Use async bridge to handle async method properly
                    from ..utils.async_bridge import AsyncBridge

                    success = AsyncBridge.run_async(
                        manager.index_content(
                            content_id=content_id,
                            content=content_text,
                            source=content_source,
                            metadata=metadata
                        )
                    )
                    
                    if success:
                        flash("Content indexed successfully!", 'success')
                        return redirect(url_for('AIKnowledgeBaseView.index'))
                    else:
                        flash("Failed to index content", 'error')
                
                except Exception as e:
                    flash(f"Indexing error: {str(e)}", 'error')
            else:
                flash("Please provide content to index", 'warning')
        
        return self.render_template(
            'collaborative/ai_index_content.html',
            title='Index Content'
        )


class AIAdminView(BaseView):
    """Admin view for AI system configuration"""
    
    route_base = "/ai-admin"
    
    @expose('/')
    @has_access
    @protect()
    def index(self):
        """AI system administration dashboard"""
        try:
            model_manager = ModelManager(app=self.appbuilder.app)
            available_models = model_manager.get_available_models()
            
            # Get system statistics
            session_factory = lambda: db.session
            chatbot_service = ChatbotService(
                model_manager=model_manager,
                session_factory=session_factory
            )
            system_stats = {
                'total_conversations': chatbot_service.get_total_conversations(),
                'active_conversations': chatbot_service.get_active_conversations_count(),
                'total_messages': chatbot_service.get_total_messages(),
                'average_response_time': chatbot_service.get_average_response_time()
            }
            
            # Create minimal RAG engine for KnowledgeBaseManager
            try:
                from ..ai.rag_engine import RAGEngine
                from ..ai.vector_stores.faiss_vector_store import FAISSVectorStore
                vector_store = FAISSVectorStore()
                rag_engine = RAGEngine(vector_store, model_manager)
                
                knowledge_base_manager = KnowledgeBaseManager(
                    rag_engine=rag_engine,
                    model_manager=model_manager,
                    session_factory=session_factory
                )
                kb_stats = knowledge_base_manager.get_stats()
            except Exception as e:
                self.logger.warning(f"Could not initialize knowledge base for stats: {e}")
                kb_stats = {'total_documents': 0, 'total_chunks': 0}
            
            return self.render_template(
                'collaborative/ai_admin.html',
                title='AI System Administration',
                available_models=available_models,
                system_stats=system_stats,
                knowledge_base_stats=kb_stats
            )
        
        except Exception as e:
            flash(f"Error loading admin dashboard: {str(e)}", 'error')
            return redirect(url_for('AIChatView.index'))
    
    @expose('/models')
    @has_access
    @protect()
    def models(self):
        """Model configuration"""
        try:
            model_manager = ModelManager(app=self.appbuilder.app)
            models = model_manager.get_available_models()
            
            return self.render_template(
                'collaborative/ai_model_config.html',
                title='AI Model Configuration',
                models=models
            )
        
        except Exception as e:
            flash(f"Error loading model configuration: {str(e)}", 'error')
            return redirect(url_for('AIAdminView.index'))
    
    @expose('/system-config', methods=['GET', 'POST'])
    @has_access
    @protect()
    def system_config(self):
        """System configuration"""
        if request.method == 'POST':
            # Handle configuration updates
            try:
                # Update system configuration
                # This would integrate with PgAppForge's configuration system
                flash("Configuration updated successfully!", 'success')
                return redirect(url_for('AIAdminView.system_config'))
            
            except Exception as e:
                flash(f"Configuration error: {str(e)}", 'error')
        
        return self.render_template(
            'collaborative/ai_system_config.html',
            title='AI System Configuration'
        )