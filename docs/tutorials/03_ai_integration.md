# AI Integration Tutorial

![Implementation Status](https://img.shields.io/badge/15%20AI%20Providers-✅%20Validated-brightgreen)
![Runtime Testing](https://img.shields.io/badge/Runtime%20Testing-🔄%20Required-yellow)
![Tutorial Level](https://img.shields.io/badge/Level-Advanced-red)

This tutorial shows you how to implement and use the comprehensive AI features in PgAppForge, including multiple AI providers, speech processing, and intelligent content generation.

> **⚠️ Validation Status**: All 15 AI providers and speech processing features have been **confirmed implemented** with complete adapter classes. Tutorial examples require runtime testing with actual API keys.

## What You'll Learn

- Configure multiple AI providers (OpenAI, Anthropic, Ollama, etc.)
- Implement intelligent content generation
- Add speech-to-text and text-to-speech capabilities
- Create AI-powered data analysis and insights
- Build conversational AI interfaces
- Implement AI-assisted workflows

## Prerequisites

- Complete the [Getting Started Tutorial](01_getting_started.md)
- API keys for at least one AI provider (OpenAI, Anthropic, Groq)
- Optional: Ollama for local AI models
- Basic understanding of AI/ML concepts

## Step 1: Configure AI Providers

### Update Configuration

Add comprehensive AI configuration to `config.py`:

```python
import os

# AI Provider Configuration
ENABLE_AI_FEATURES = True
AI_DEFAULT_PROVIDER = 'openai'  # Default provider
AI_FALLBACK_PROVIDERS = ['anthropic', 'groq', 'ollama']  # Fallback order

# OpenAI Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = 'gpt-4'
OPENAI_MAX_TOKENS = 2000
OPENAI_TEMPERATURE = 0.7

# Anthropic Configuration
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
ANTHROPIC_MODEL = 'claude-3-sonnet-20240229'
ANTHROPIC_MAX_TOKENS = 2000

# Google AI Configuration
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
GOOGLE_MODEL = 'gemini-pro'

# Groq Configuration (fast inference)
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL = 'llama2-70b-4096'

# Ollama Configuration (local models)
OLLAMA_BASE_URL = 'http://localhost:11434'
OLLAMA_MODEL = 'llama2:7b'

# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY = os.environ.get('AZURE_OPENAI_API_KEY', '')
AZURE_OPENAI_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT', '')
AZURE_OPENAI_DEPLOYMENT = 'gpt-4'
AZURE_OPENAI_API_VERSION = '2024-02-15-preview'

# AI Features Configuration
AI_CONTENT_GENERATION = True
AI_DATA_ANALYSIS = True
AI_CONVERSATIONAL_INTERFACE = True
AI_WORKFLOW_ASSISTANCE = True

# Speech Configuration
ENABLE_SPEECH_FEATURES = True
SPEECH_TO_TEXT_PROVIDER = 'openai'  # openai, local_whisper, huggingface
TEXT_TO_SPEECH_PROVIDER = 'openai'  # openai, gtts, pyttsx3, huggingface

# OpenAI Speech Configuration
OPENAI_TTS_MODEL = 'tts-1'
OPENAI_TTS_VOICE = 'alloy'
OPENAI_STT_MODEL = 'whisper-1'

# Local Speech Configuration
LOCAL_WHISPER_MODEL = 'base'
TTS_VOICE_LANGUAGE = 'en'
TTS_SPEECH_RATE = 150

# Vector Store Configuration
ENABLE_VECTOR_STORE = True
FAISS_INDEX_PATH = './data/faiss_index'
VECTOR_STORE_DIMENSION = 1536  # OpenAI embedding dimension
EMBEDDING_MODEL = 'text-embedding-ada-002'

# AI Rate Limiting
AI_RATE_LIMIT_PER_MINUTE = 60
AI_RATE_LIMIT_PER_HOUR = 1000
AI_TIMEOUT_SECONDS = 60

# AI Content Policies
AI_CONTENT_FILTER = True
AI_PROFANITY_FILTER = True
AI_SAFETY_GUIDELINES = True
```

### Set Environment Variables

Create `.env` file:

```bash
# AI Service API Keys
OPENAI_API_KEY=sk-your-openai-api-key-here
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key-here
GOOGLE_API_KEY=your-google-api-key-here
GROQ_API_KEY=your-groq-api-key-here

# Azure OpenAI (if using)
AZURE_OPENAI_API_KEY=your-azure-openai-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/

# Optional: HuggingFace for open-source models
HUGGINGFACE_API_TOKEN=your-huggingface-token
```

## Step 2: Create AI-Enhanced Models

Update `models.py` with AI-specific fields:

```python
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, JSON

class AIGeneratedContent(Model, AuditMixin):
    """Store AI-generated content with metadata."""
    __tablename__ = 'ai_generated_content'

    id = Column(Integer, primary_key=True)

    # Content details
    content_type = Column(String(50), nullable=False)  # summary, analysis, suggestion
    original_content = Column(Text)
    generated_content = Column(Text, nullable=False)
    prompt_used = Column(Text)

    # AI metadata
    ai_provider = Column(String(50), nullable=False)
    ai_model = Column(String(100))
    generation_time = Column(Float)  # seconds
    token_count = Column(Integer)
    confidence_score = Column(Float)

    # Quality metrics
    user_rating = Column(Integer)  # 1-5 stars
    user_feedback = Column(Text)
    is_approved = Column(Boolean, default=False)

    # Relationships
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task', backref='ai_content')

    def __repr__(self):
        return f"AI Content: {self.content_type} ({self.ai_provider})"

class AIConversation(Model, AuditMixin):
    """Store AI conversation history."""
    __tablename__ = 'ai_conversation'

    id = Column(Integer, primary_key=True)

    # Conversation metadata
    session_id = Column(String(64), nullable=False)
    conversation_title = Column(String(200))
    is_active = Column(Boolean, default=True)

    # Context
    context_type = Column(String(50))  # task, project, general
    context_id = Column(Integer)  # Reference to context object

    # Conversation data
    messages = Column(JSON)  # Store conversation messages
    total_tokens = Column(Integer, default=0)
    ai_provider = Column(String(50))

    def __repr__(self):
        return f"AI Conversation: {self.conversation_title or self.session_id}"

class SpeechProcessing(Model, AuditMixin):
    """Store speech processing records."""
    __tablename__ = 'speech_processing'

    id = Column(Integer, primary_key=True)

    # Processing type
    processing_type = Column(String(20), nullable=False)  # stt, tts
    provider = Column(String(50), nullable=False)

    # Input/Output
    input_text = Column(Text)  # For TTS
    output_text = Column(Text)  # For STT
    audio_file_path = Column(String(500))
    audio_duration = Column(Float)  # seconds

    # Processing metadata
    language = Column(String(10), default='en')
    voice_id = Column(String(50))  # For TTS
    processing_time = Column(Float)
    success = Column(Boolean, default=True)
    error_message = Column(Text)

    # Relationships
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task', backref='speech_records')

# Extend existing Task model with AI fields
class TaskAI(Model):
    """AI-enhanced task features."""
    __tablename__ = 'task_ai'

    id = Column(Integer, primary_key=True)

    # Task reference
    task_id = Column(Integer, ForeignKey('task.id'), nullable=False)
    task = relationship('Task', backref='ai_features')

    # AI-generated content
    ai_summary = Column(Text)
    ai_priority_suggestion = Column(String(20))
    ai_time_estimate = Column(Integer)  # minutes
    ai_tags = Column(JSON)  # List of AI-generated tags
    ai_dependencies = Column(JSON)  # Suggested dependencies

    # AI analysis
    complexity_score = Column(Float)  # 0-1
    urgency_score = Column(Float)  # 0-1
    effort_estimate = Column(Float)  # hours
    risk_assessment = Column(JSON)

    # AI recommendations
    suggested_assignee = Column(String(100))
    suggested_due_date = Column(DateTime)
    optimization_suggestions = Column(JSON)

    # AI conversation
    has_ai_assistant = Column(Boolean, default=False)
    ai_conversation_id = Column(Integer, ForeignKey('ai_conversation.id'))
    ai_conversation = relationship('AIConversation')
```

## Step 3: Create AI Service Views

Create `ai_views.py`:

```python
from flask import request, render_template, jsonify, session, send_file
from pgappforge import BaseView, expose, has_access
from pgappforge.models.sqla.interface import SQLAInterface
from werkzeug.utils import secure_filename
import os
import tempfile
import uuid
from datetime import datetime

class AIContentGeneratorView(BaseView):
    """AI content generation interface."""

    default_view = 'generator'

    @expose('/generator/')
    @has_access
    def generator(self):
        """Main AI content generator interface."""
        return self.render_template('ai_generator.html')

    @expose('/api/generate/', methods=['POST'])
    @has_access
    def generate_content(self):
        """Generate content using AI."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager

            data = request.get_json()
            prompt = data.get('prompt', '')
            content_type = data.get('content_type', 'general')
            provider = data.get('provider', 'openai')
            max_tokens = data.get('max_tokens', 500)
            temperature = data.get('temperature', 0.7)

            if not prompt:
                return jsonify({'error': 'Prompt is required'}), 400

            # Initialize AI manager
            ai_manager = AIModelManager()

            # Generate content
            start_time = datetime.now()
            generated_content = ai_manager.generate_text(
                prompt=prompt,
                model_provider=provider,
                max_tokens=max_tokens,
                temperature=temperature
            )
            generation_time = (datetime.now() - start_time).total_seconds()

            # Store generated content
            from models import AIGeneratedContent
            ai_content = AIGeneratedContent(
                content_type=content_type,
                original_content=prompt,
                generated_content=generated_content,
                prompt_used=prompt,
                ai_provider=provider,
                generation_time=generation_time,
                created_by=self.appbuilder.sm.current_user
            )
            self.appbuilder.session.add(ai_content)
            self.appbuilder.session.commit()

            return jsonify({
                'success': True,
                'content': generated_content,
                'generation_time': generation_time,
                'content_id': ai_content.id
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @expose('/api/analyze-task/<int:task_id>/', methods=['POST'])
    @has_access
    def analyze_task(self, task_id):
        """Analyze a task using AI."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager
            from models import Task, TaskAI

            task = Task.query.get_or_404(task_id)
            ai_manager = AIModelManager()

            # Create analysis prompt
            prompt = f"""
            Analyze this task and provide insights:

            Title: {task.title}
            Description: {task.description or 'No description provided'}
            Priority: {task.priority}
            Status: {task.status}

            Please provide:
            1. Complexity score (0-1, where 1 is most complex)
            2. Urgency score (0-1, where 1 is most urgent)
            3. Effort estimate in hours
            4. Risk assessment
            5. Optimization suggestions
            6. Suggested tags (comma-separated)

            Format your response as JSON with these keys:
            complexity_score, urgency_score, effort_estimate, risk_assessment, suggestions, tags
            """

            # Generate analysis
            analysis_text = ai_manager.generate_text(
                prompt=prompt,
                model_provider='openai',
                max_tokens=800,
                temperature=0.3
            )

            # Try to parse JSON response (simplified - in production, use more robust parsing)
            try:
                import json
                # Extract JSON from response (simplified)
                analysis_data = json.loads(analysis_text)
            except:
                # Fallback to text analysis
                analysis_data = {
                    'complexity_score': 0.5,
                    'urgency_score': 0.5,
                    'effort_estimate': 4.0,
                    'risk_assessment': 'Analysis could not be parsed',
                    'suggestions': [analysis_text],
                    'tags': ['ai-analyzed']
                }

            # Store or update AI analysis
            task_ai = TaskAI.query.filter_by(task_id=task_id).first()
            if not task_ai:
                task_ai = TaskAI(task_id=task_id)
                self.appbuilder.session.add(task_ai)

            task_ai.complexity_score = analysis_data.get('complexity_score', 0.5)
            task_ai.urgency_score = analysis_data.get('urgency_score', 0.5)
            task_ai.effort_estimate = analysis_data.get('effort_estimate', 4.0)
            task_ai.risk_assessment = analysis_data.get('risk_assessment')
            task_ai.optimization_suggestions = analysis_data.get('suggestions', [])
            task_ai.ai_tags = analysis_data.get('tags', [])

            self.appbuilder.session.commit()

            return jsonify({
                'success': True,
                'analysis': analysis_data,
                'task_id': task_id
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500

class AIConversationView(BaseView):
    """AI conversational interface."""

    default_view = 'chat'

    @expose('/chat/')
    @has_access
    def chat(self):
        """Main chat interface."""
        # Get or create conversation session
        session_id = session.get('ai_conversation_id')
        if not session_id:
            session_id = str(uuid.uuid4())
            session['ai_conversation_id'] = session_id

        return self.render_template('ai_chat.html', session_id=session_id)

    @expose('/api/chat/', methods=['POST'])
    @has_access
    def chat_message(self):
        """Process chat message."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager
            from models import AIConversation

            data = request.get_json()
            message = data.get('message', '')
            session_id = data.get('session_id')
            context_type = data.get('context_type')
            context_id = data.get('context_id')

            if not message or not session_id:
                return jsonify({'error': 'Message and session ID required'}), 400

            # Get or create conversation
            conversation = AIConversation.query.filter_by(session_id=session_id).first()
            if not conversation:
                conversation = AIConversation(
                    session_id=session_id,
                    conversation_title=f"Chat {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    context_type=context_type,
                    context_id=context_id,
                    messages=[],
                    created_by=self.appbuilder.sm.current_user
                )
                self.appbuilder.session.add(conversation)

            # Add user message to conversation
            user_message = {
                'role': 'user',
                'content': message,
                'timestamp': datetime.now().isoformat()
            }
            conversation.messages.append(user_message)

            # Build conversation context
            conversation_context = []
            for msg in conversation.messages[-10:]:  # Last 10 messages for context
                conversation_context.append(f"{msg['role']}: {msg['content']}")

            # Create AI prompt with context
            if context_type == 'task' and context_id:
                from models import Task
                task = Task.query.get(context_id)
                system_prompt = f"""You are an AI assistant helping with task management.
                Current task context:
                - Title: {task.title if task else 'Unknown'}
                - Description: {task.description if task and task.description else 'No description'}
                - Status: {task.status if task else 'Unknown'}

                Help the user with questions about this task or general productivity advice.
                """
            else:
                system_prompt = """You are a helpful AI assistant for a task management application.
                Help users with productivity, task organization, and workflow optimization."""

            full_prompt = f"{system_prompt}\n\nConversation history:\n" + "\n".join(conversation_context)

            # Generate AI response
            ai_manager = AIModelManager()
            ai_response = ai_manager.generate_text(
                prompt=full_prompt,
                model_provider='openai',
                max_tokens=500,
                temperature=0.8
            )

            # Add AI response to conversation
            ai_message = {
                'role': 'assistant',
                'content': ai_response,
                'timestamp': datetime.now().isoformat()
            }
            conversation.messages.append(ai_message)
            conversation.total_tokens += len(message.split()) + len(ai_response.split())

            self.appbuilder.session.commit()

            return jsonify({
                'success': True,
                'response': ai_response,
                'conversation_id': conversation.id
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500

class SpeechProcessingView(BaseView):
    """Speech-to-text and text-to-speech interface."""

    default_view = 'speech'

    @expose('/speech/')
    @has_access
    def speech(self):
        """Main speech processing interface."""
        return self.render_template('speech_processing.html')

    @expose('/api/speech-to-text/', methods=['POST'])
    @has_access
    def speech_to_text(self):
        """Convert speech to text."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager

            if 'audio' not in request.files:
                return jsonify({'error': 'No audio file provided'}), 400

            audio_file = request.files['audio']
            if audio_file.filename == '':
                return jsonify({'error': 'No file selected'}), 400

            # Save uploaded file temporarily
            filename = secure_filename(audio_file.filename)
            temp_dir = tempfile.gettempdir()
            temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{filename}")
            audio_file.save(temp_path)

            try:
                # Process speech to text
                ai_manager = AIModelManager()
                transcription = ai_manager.speech_to_text(
                    audio_file_path=temp_path,
                    language='en'
                )

                # Store processing record
                from models import SpeechProcessing
                speech_record = SpeechProcessing(
                    processing_type='stt',
                    provider='openai',
                    output_text=transcription,
                    audio_file_path=temp_path,
                    language='en',
                    success=True,
                    created_by=self.appbuilder.sm.current_user
                )
                self.appbuilder.session.add(speech_record)
                self.appbuilder.session.commit()

                return jsonify({
                    'success': True,
                    'transcription': transcription,
                    'record_id': speech_record.id
                })

            finally:
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @expose('/api/text-to-speech/', methods=['POST'])
    @has_access
    def text_to_speech(self):
        """Convert text to speech."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager

            data = request.get_json()
            text = data.get('text', '')
            voice = data.get('voice', 'alloy')

            if not text:
                return jsonify({'error': 'Text is required'}), 400

            # Generate speech
            ai_manager = AIModelManager()
            audio_data = ai_manager.text_to_speech(
                text=text,
                voice=voice
            )

            # Save audio file
            temp_dir = tempfile.gettempdir()
            audio_filename = f"tts_{uuid.uuid4()}.mp3"
            audio_path = os.path.join(temp_dir, audio_filename)

            with open(audio_path, 'wb') as f:
                f.write(audio_data)

            # Store processing record
            from models import SpeechProcessing
            speech_record = SpeechProcessing(
                processing_type='tts',
                provider='openai',
                input_text=text,
                audio_file_path=audio_path,
                voice_id=voice,
                success=True,
                created_by=self.appbuilder.sm.current_user
            )
            self.appbuilder.session.add(speech_record)
            self.appbuilder.session.commit()

            return jsonify({
                'success': True,
                'audio_url': f'/api/download-audio/{speech_record.id}/',
                'record_id': speech_record.id
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @expose('/api/download-audio/<int:record_id>/')
    @has_access
    def download_audio(self, record_id):
        """Download generated audio file."""
        from models import SpeechProcessing

        speech_record = SpeechProcessing.query.get_or_404(record_id)

        # Check if user has access to this record
        if speech_record.created_by != self.appbuilder.sm.current_user:
            return jsonify({'error': 'Access denied'}), 403

        if not os.path.exists(speech_record.audio_file_path):
            return jsonify({'error': 'Audio file not found'}), 404

        return send_file(
            speech_record.audio_file_path,
            as_attachment=True,
            download_name=f"speech_{record_id}.mp3",
            mimetype='audio/mpeg'
        )

class AIAnalyticsView(BaseView):
    """AI-powered analytics and insights."""

    default_view = 'analytics'

    @expose('/analytics/')
    @has_access
    def analytics(self):
        """Main analytics dashboard."""
        return self.render_template('ai_analytics.html')

    @expose('/api/productivity-analysis/')
    @has_access
    def productivity_analysis(self):
        """Analyze user productivity patterns."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager
            from models import Task
            from sqlalchemy import func

            user_id = self.appbuilder.sm.current_user.id

            # Get user's task statistics
            task_stats = self.appbuilder.session.query(
                Task.status,
                func.count(Task.id).label('count'),
                func.avg(
                    func.extract('epoch', Task.changed_on - Task.created_on) / 3600
                ).label('avg_completion_hours')
            ).filter(Task.created_by_fk == user_id)\
             .group_by(Task.status).all()

            # Recent tasks for pattern analysis
            recent_tasks = Task.query.filter(Task.created_by_fk == user_id)\
                                   .order_by(Task.created_on.desc())\
                                   .limit(20).all()

            # Create analysis prompt
            task_data = []
            for task in recent_tasks:
                task_data.append({
                    'title': task.title,
                    'priority': task.priority,
                    'status': task.status,
                    'created': task.created_on.isoformat() if task.created_on else None,
                    'completed': task.completed
                })

            stats_data = {stat.status: {'count': stat.count, 'avg_hours': float(stat.avg_completion_hours) if stat.avg_completion_hours else 0} for stat in task_stats}

            prompt = f"""
            Analyze this user's productivity patterns and provide insights:

            Task Statistics:
            {stats_data}

            Recent Tasks:
            {task_data}

            Provide analysis in JSON format with these keys:
            - productivity_score: 0-100
            - patterns: list of observed patterns
            - strengths: list of strengths
            - improvement_areas: list of areas for improvement
            - recommendations: list of specific recommendations
            - weekly_goal: suggested goals for next week
            """

            # Generate analysis
            ai_manager = AIModelManager()
            analysis = ai_manager.generate_text(
                prompt=prompt,
                model_provider='openai',
                max_tokens=1000,
                temperature=0.5
            )

            return jsonify({
                'success': True,
                'analysis': analysis,
                'task_count': len(recent_tasks),
                'stats': stats_data
            })

        except Exception as e:
            return jsonify({'error': str(e)}), 500
```

## Step 4: Create AI Interface Templates

Create `templates/ai_generator.html`:

```html
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <h1>AI Content Generator</h1>

    <div class="row">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header">
                    <h5>Generate Content</h5>
                </div>
                <div class="card-body">
                    <form id="ai-generator-form">
                        <div class="form-group">
                            <label for="content-type">Content Type</label>
                            <select class="form-control" id="content-type" name="content_type">
                                <option value="summary">Summary</option>
                                <option value="description">Description</option>
                                <option value="analysis">Analysis</option>
                                <option value="suggestions">Suggestions</option>
                                <option value="email">Email</option>
                                <option value="report">Report</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label for="ai-provider">AI Provider</label>
                            <select class="form-control" id="ai-provider" name="provider">
                                <option value="openai">OpenAI GPT-4</option>
                                <option value="anthropic">Anthropic Claude</option>
                                <option value="groq">Groq (Fast)</option>
                                <option value="ollama">Ollama (Local)</option>
                                <option value="google">Google Gemini</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label for="prompt">Prompt</label>
                            <textarea class="form-control" id="prompt" name="prompt"
                                     rows="4" placeholder="Enter your prompt here..."
                                     required></textarea>
                        </div>

                        <div class="row">
                            <div class="col-md-6">
                                <div class="form-group">
                                    <label for="max-tokens">Max Tokens</label>
                                    <input type="number" class="form-control" id="max-tokens"
                                           name="max_tokens" value="500" min="10" max="4000">
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="form-group">
                                    <label for="temperature">Temperature (Creativity)</label>
                                    <input type="range" class="form-control-range" id="temperature"
                                           name="temperature" min="0" max="1" step="0.1" value="0.7">
                                    <small class="form-text text-muted">
                                        <span id="temperature-value">0.7</span> (0 = Focused, 1 = Creative)
                                    </small>
                                </div>
                            </div>
                        </div>

                        <button type="submit" class="btn btn-primary" id="generate-btn">
                            <i class="fa fa-magic"></i> Generate Content
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <div class="col-md-4">
            <div class="card">
                <div class="card-header">
                    <h6>Quick Prompts</h6>
                </div>
                <div class="card-body">
                    <div class="quick-prompts">
                        <button class="btn btn-outline-secondary btn-sm mb-2 quick-prompt-btn"
                                data-prompt="Summarize the following task and provide key action items:">
                            Task Summary
                        </button>
                        <button class="btn btn-outline-secondary btn-sm mb-2 quick-prompt-btn"
                                data-prompt="Analyze the project requirements and suggest implementation steps:">
                            Project Analysis
                        </button>
                        <button class="btn btn-outline-secondary btn-sm mb-2 quick-prompt-btn"
                                data-prompt="Write a professional email about:">
                            Professional Email
                        </button>
                        <button class="btn btn-outline-secondary btn-sm mb-2 quick-prompt-btn"
                                data-prompt="Create a detailed report on:">
                            Detailed Report
                        </button>
                        <button class="btn btn-outline-secondary btn-sm mb-2 quick-prompt-btn"
                                data-prompt="Suggest improvements for:">
                            Improvement Ideas
                        </button>
                    </div>
                </div>
            </div>

            <div class="card mt-3">
                <div class="card-header">
                    <h6>Generation Status</h6>
                </div>
                <div class="card-body">
                    <div id="generation-status">
                        <p class="text-muted">Ready to generate content</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Generated Content -->
    <div class="row mt-4" id="generated-content-section" style="display: none;">
        <div class="col-md-12">
            <div class="card">
                <div class="card-header d-flex justify-content-between">
                    <h5>Generated Content</h5>
                    <div>
                        <button class="btn btn-sm btn-secondary" id="copy-content-btn">
                            <i class="fa fa-copy"></i> Copy
                        </button>
                        <button class="btn btn-sm btn-success" id="save-content-btn">
                            <i class="fa fa-save"></i> Save
                        </button>
                    </div>
                </div>
                <div class="card-body">
                    <div id="generated-content" style="white-space: pre-wrap; line-height: 1.6;">
                        <!-- Generated content will appear here -->
                    </div>
                </div>
                <div class="card-footer">
                    <small class="text-muted">
                        Generated in <span id="generation-time">-</span> seconds
                        using <span id="used-provider">-</span>
                    </small>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block tail_js %}
{{ super() }}
<script>
$(document).ready(function() {
    // Temperature slider
    $('#temperature').on('input', function() {
        $('#temperature-value').text($(this).val());
    });

    // Quick prompt buttons
    $('.quick-prompt-btn').click(function() {
        const prompt = $(this).data('prompt');
        $('#prompt').val(prompt + ' ');
        $('#prompt').focus();
    });

    // Form submission
    $('#ai-generator-form').submit(function(e) {
        e.preventDefault();

        const formData = {
            prompt: $('#prompt').val(),
            content_type: $('#content-type').val(),
            provider: $('#ai-provider').val(),
            max_tokens: parseInt($('#max-tokens').val()),
            temperature: parseFloat($('#temperature').val())
        };

        // Update UI
        $('#generate-btn').prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Generating...');
        $('#generation-status').html('<p class="text-info"><i class="fa fa-spinner fa-spin"></i> Generating content...</p>');

        // Make API request
        $.ajax({
            url: '{{ url_for("AIContentGeneratorView.generate_content") }}',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(formData),
            success: function(response) {
                if (response.success) {
                    $('#generated-content').text(response.content);
                    $('#generation-time').text(response.generation_time.toFixed(2));
                    $('#used-provider').text(formData.provider);
                    $('#generated-content-section').show();
                    $('#generation-status').html('<p class="text-success"><i class="fa fa-check"></i> Content generated successfully!</p>');

                    // Store content ID for saving
                    $('#save-content-btn').data('content-id', response.content_id);
                } else {
                    $('#generation-status').html('<p class="text-danger"><i class="fa fa-exclamation-triangle"></i> Generation failed</p>');
                }
            },
            error: function(xhr) {
                const error = xhr.responseJSON ? xhr.responseJSON.error : 'Unknown error';
                $('#generation-status').html(`<p class="text-danger"><i class="fa fa-exclamation-triangle"></i> Error: ${error}</p>`);
            },
            complete: function() {
                $('#generate-btn').prop('disabled', false).html('<i class="fa fa-magic"></i> Generate Content');
            }
        });
    });

    // Copy content
    $('#copy-content-btn').click(function() {
        const content = $('#generated-content').text();
        navigator.clipboard.writeText(content).then(function() {
            $(this).html('<i class="fa fa-check"></i> Copied!');
            setTimeout(() => {
                $('#copy-content-btn').html('<i class="fa fa-copy"></i> Copy');
            }, 2000);
        });
    });

    // Save content
    $('#save-content-btn').click(function() {
        const contentId = $(this).data('content-id');
        if (contentId) {
            alert('Content saved successfully! You can find it in your AI content history.');
        }
    });
});
</script>
{% endblock %}
```

Create `templates/ai_chat.html`:

```html
{% extends "appbuilder/base.html" %}

{% block content %}
<div class="container-fluid">
    <h1>AI Assistant</h1>

    <div class="row">
        <div class="col-md-8">
            <div class="card chat-container" style="height: 600px;">
                <div class="card-header">
                    <h6>Chat with AI Assistant</h6>
                </div>
                <div class="card-body d-flex flex-column" style="height: 100%;">
                    <div id="chat-messages" class="flex-grow-1 overflow-auto mb-3"
                         style="max-height: 450px;">
                        <div class="message ai-message">
                            <div class="message-avatar">🤖</div>
                            <div class="message-content">
                                <strong>AI Assistant</strong>
                                <p>Hello! I'm your AI assistant. I can help you with task management, productivity tips, and answer questions about your work. How can I assist you today?</p>
                                <small class="text-muted">{{ moment().format('HH:mm') }}</small>
                            </div>
                        </div>
                    </div>

                    <div class="chat-input">
                        <div class="input-group">
                            <input type="text" class="form-control" id="chat-input"
                                   placeholder="Type your message..." maxlength="1000">
                            <div class="input-group-append">
                                <button class="btn btn-primary" id="send-btn" type="button">
                                    <i class="fa fa-paper-plane"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <div class="col-md-4">
            <div class="card">
                <div class="card-header">
                    <h6>Quick Actions</h6>
                </div>
                <div class="card-body">
                    <button class="btn btn-outline-primary btn-sm mb-2 quick-action"
                            data-message="Help me organize my tasks for today">
                        📅 Organize Today's Tasks
                    </button>
                    <button class="btn btn-outline-primary btn-sm mb-2 quick-action"
                            data-message="Give me productivity tips for better focus">
                        🎯 Productivity Tips
                    </button>
                    <button class="btn btn-outline-primary btn-sm mb-2 quick-action"
                            data-message="Analyze my work patterns and suggest improvements">
                        📊 Work Analysis
                    </button>
                    <button class="btn btn-outline-primary btn-sm mb-2 quick-action"
                            data-message="Help me prioritize my current tasks">
                        ⭐ Priority Help
                    </button>
                    <button class="btn btn-outline-primary btn-sm mb-2 quick-action"
                            data-message="Suggest a daily routine for better productivity">
                        🔄 Daily Routine
                    </button>
                </div>
            </div>

            <div class="card mt-3">
                <div class="card-header">
                    <h6>Context</h6>
                </div>
                <div class="card-body">
                    <select class="form-control" id="context-selector">
                        <option value="">General Chat</option>
                        <option value="productivity">Productivity Focus</option>
                        <option value="planning">Project Planning</option>
                        <option value="analysis">Data Analysis</option>
                    </select>
                </div>
            </div>
        </div>
    </div>
</div>

<style>
.chat-container {
    border: 1px solid #ddd;
}

.message {
    display: flex;
    margin-bottom: 15px;
    animation: fadeIn 0.3s ease-in;
}

.message-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-right: 10px;
    font-size: 20px;
    flex-shrink: 0;
}

.user-message .message-avatar {
    background: #007bff;
    color: white;
    order: 2;
    margin-left: 10px;
    margin-right: 0;
}

.ai-message .message-avatar {
    background: #f8f9fa;
    border: 1px solid #ddd;
}

.message-content {
    flex-grow: 1;
    background: #f8f9fa;
    border-radius: 10px;
    padding: 10px 15px;
    max-width: 80%;
}

.user-message .message-content {
    background: #007bff;
    color: white;
    margin-left: auto;
    text-align: right;
}

.user-message {
    flex-direction: row-reverse;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.typing-indicator {
    display: none;
    color: #6c757d;
    font-style: italic;
    padding: 10px;
}

.quick-action {
    width: 100%;
    text-align: left;
    margin-bottom: 5px;
}
</style>
{% endblock %}

{% block tail_js %}
{{ super() }}
<script>
$(document).ready(function() {
    const sessionId = '{{ session_id }}';
    let isTyping = false;

    // Quick action buttons
    $('.quick-action').click(function() {
        const message = $(this).data('message');
        $('#chat-input').val(message);
        sendMessage();
    });

    // Send message on Enter key
    $('#chat-input').keypress(function(e) {
        if (e.which === 13 && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Send message on button click
    $('#send-btn').click(sendMessage);

    function sendMessage() {
        const message = $('#chat-input').val().trim();
        if (!message || isTyping) return;

        // Add user message to chat
        addMessage('user', message, '{{ g.user.username if g.user else "You" }}');

        // Clear input and show typing indicator
        $('#chat-input').val('');
        showTypingIndicator();

        // Get context
        const context = $('#context-selector').val();

        // Send to AI
        $.ajax({
            url: '{{ url_for("AIConversationView.chat_message") }}',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                message: message,
                session_id: sessionId,
                context_type: context,
                context_id: null
            }),
            success: function(response) {
                hideTypingIndicator();
                if (response.success) {
                    addMessage('ai', response.response, 'AI Assistant');
                } else {
                    addMessage('ai', 'Sorry, I encountered an error. Please try again.', 'AI Assistant');
                }
            },
            error: function(xhr) {
                hideTypingIndicator();
                const error = xhr.responseJSON ? xhr.responseJSON.error : 'Network error';
                addMessage('ai', `Sorry, I encountered an error: ${error}`, 'AI Assistant');
            }
        });
    }

    function addMessage(type, content, sender) {
        const timestamp = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        const avatar = type === 'user' ? '👤' : '🤖';

        const messageHtml = `
            <div class="message ${type}-message">
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <strong>${sender}</strong>
                    <p>${content}</p>
                    <small class="text-muted">${timestamp}</small>
                </div>
            </div>
        `;

        $('#chat-messages').append(messageHtml);
        scrollToBottom();
    }

    function showTypingIndicator() {
        isTyping = true;
        const typingHtml = `
            <div class="typing-indicator" id="typing-indicator">
                <div class="message ai-message">
                    <div class="message-avatar">🤖</div>
                    <div class="message-content">
                        <em>AI Assistant is typing...</em>
                    </div>
                </div>
            </div>
        `;
        $('#chat-messages').append(typingHtml);
        $('.typing-indicator').show();
        scrollToBottom();
    }

    function hideTypingIndicator() {
        isTyping = false;
        $('#typing-indicator').remove();
    }

    function scrollToBottom() {
        const chatMessages = $('#chat-messages');
        chatMessages.scrollTop(chatMessages[0].scrollHeight);
    }
});
</script>
{% endblock %}
```

## Step 5: Testing AI Features

### 1. Basic Content Generation

```python
# Test the AI content generator
python -c "
from pgappforge.collaborative.ai.ai_models import AIModelManager
manager = AIModelManager()
result = manager.generate_text('Write a summary of project management best practices', max_tokens=200)
print(result)
"
```

### 2. Speech Processing

```python
# Test speech-to-text (requires audio file)
from pgappforge.collaborative.ai.ai_models import AIModelManager
manager = AIModelManager()

# For text-to-speech
audio_data = manager.text_to_speech("Hello, this is a test of the speech system")
with open('test_speech.mp3', 'wb') as f:
    f.write(audio_data)
```

### 3. Task Analysis

1. Create a task with detailed description
2. Use the task analysis API endpoint
3. Review AI-generated insights and recommendations

## Step 6: Advanced AI Features

### Add RAG (Retrieval-Augmented Generation)

```python
# Add to ai_views.py
@expose('/api/rag-query/', methods=['POST'])
@has_access
def rag_query(self):
    """Query using RAG (Retrieval-Augmented Generation)."""
    try:
        from pgappforge.collaborative.ai.ai_models import AIModelManager

        data = request.get_json()
        query = data.get('query', '')
        context_type = data.get('context_type', 'tasks')

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        # Get relevant context from vector store
        ai_manager = AIModelManager()

        # Retrieve relevant documents
        if context_type == 'tasks':
            from models import Task
            # Get user's tasks for context
            user_tasks = Task.query.filter(
                Task.created_by_fk == self.appbuilder.sm.current_user.id
            ).limit(20).all()

            context_docs = [f"{task.title}: {task.description or ''}" for task in user_tasks]
        else:
            context_docs = []

        # Create enhanced prompt with context
        context_text = "\n".join(context_docs)
        enhanced_prompt = f"""
        Context from user's tasks:
        {context_text}

        User query: {query}

        Based on the context above, provide a helpful and accurate response.
        """

        # Generate response
        response = ai_manager.generate_text(
            prompt=enhanced_prompt,
            model_provider='openai',
            max_tokens=800,
            temperature=0.7
        )

        return jsonify({
            'success': True,
            'response': response,
            'context_used': len(context_docs)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### Add Smart Scheduling

```python
@expose('/api/smart-schedule/', methods=['POST'])
@has_access
def smart_schedule(self):
    """AI-powered smart scheduling."""
    try:
        from pgappforge.collaborative.ai.ai_models import AIModelManager
        from models import Task
        from datetime import datetime, timedelta

        data = request.get_json()
        task_ids = data.get('task_ids', [])
        available_hours = data.get('available_hours', 8)
        start_date = data.get('start_date', datetime.now().isoformat())

        if not task_ids:
            return jsonify({'error': 'Task IDs required'}), 400

        # Get tasks
        tasks = Task.query.filter(Task.id.in_(task_ids)).all()

        # Create scheduling prompt
        task_info = []
        for task in tasks:
            task_info.append({
                'id': task.id,
                'title': task.title,
                'priority': task.priority,
                'estimated_hours': getattr(task, 'ai_features', {}).get('effort_estimate', 2.0) if hasattr(task, 'ai_features') else 2.0
            })

        prompt = f"""
        Create an optimal schedule for these tasks:
        {task_info}

        Constraints:
        - Available hours per day: {available_hours}
        - Start date: {start_date}
        - Prioritize high-priority tasks
        - Consider estimated effort

        Return a JSON schedule with tasks assigned to specific dates and time slots.
        """

        ai_manager = AIModelManager()
        schedule_response = ai_manager.generate_text(
            prompt=prompt,
            model_provider='openai',
            max_tokens=1000,
            temperature=0.3
        )

        return jsonify({
            'success': True,
            'schedule': schedule_response,
            'task_count': len(tasks)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

## Best Practices

### 1. Error Handling

- Always wrap AI calls in try-catch blocks
- Implement fallback mechanisms for provider failures
- Provide meaningful error messages to users

### 2. Performance

- Cache frequently requested AI content
- Implement rate limiting to prevent abuse
- Use streaming for long responses when possible

### 3. Security

- Validate and sanitize all user inputs
- Never expose API keys in client-side code
- Implement proper authentication for AI features

### 4. Cost Management

- Set token limits for different user tiers
- Monitor API usage and costs
- Implement intelligent caching to reduce API calls

## Troubleshooting

### Common Issues

**API Key Errors:**
```bash
# Check if API keys are set
echo $OPENAI_API_KEY
echo $ANTHROPIC_API_KEY
```

**Model Not Available:**
- Check model names in provider documentation
- Verify account access to specific models
- Use fallback models when primary is unavailable

**Rate Limiting:**
- Implement exponential backoff
- Add request queuing for high-volume scenarios
- Monitor rate limit headers

This completes the AI integration tutorial. Users can now leverage powerful AI capabilities for content generation, analysis, and workflow automation!