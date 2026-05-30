"""
View Classes for PgAppForge Getting Started Tutorial

This module defines the view classes for the task management application,
including enhanced ModelViews with AI capabilities and custom dashboard views.
"""

from flask import request, flash, redirect, url_for, g
from pgappforge import ModelView, BaseView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.widgets import ListWidget, ShowWidget
from pgappforge.actions import action
from pgappforge.security.decorators import has_access
from flask_babel import lazy_gettext, gettext
from wtforms import TextAreaField, SelectField, IntegerField
from wtforms.validators import DataRequired, Optional, NumberRange
from sqlalchemy import func, and_, or_
from datetime import datetime, date, timedelta

from models import Task, TaskCategory, TaskHistory, Priority, Status


class TaskCategoryModelView(ModelView):
    """
    Task category management view with enhanced features.
    """
    datamodel = SQLAInterface(TaskCategory)

    # List view configuration
    list_columns = ['name', 'description', 'color', 'is_active', 'task_count', 'completion_rate']
    show_columns = ['name', 'description', 'color', 'is_active', 'sort_order', 
                   'task_count', 'completion_rate', 'created_by', 'created_on']
    add_columns = ['name', 'description', 'color', 'is_active', 'sort_order']
    edit_columns = ['name', 'description', 'color', 'is_active', 'sort_order']

    # Search and filters
    search_columns = ['name', 'description']
    list_filters = ['is_active', 'created_by']

    # Order and pagination
    base_order = ('sort_order', 'asc')
    page_size = 20

    # Custom labels
    label_columns = {
        'is_active': 'Active',
        'sort_order': 'Sort Order',
        'task_count': 'Tasks',
        'completion_rate': 'Completion %',
        'created_by': 'Created By',
        'created_on': 'Created On'
    }

    # Form field descriptions
    description_columns = {
        'name': 'Category name (must be unique)',
        'description': 'Optional description of this category',
        'color': 'Hex color code for visual identification (e.g., #007bff)',
        'is_active': 'Whether this category is available for new tasks',
        'sort_order': 'Display order (lower numbers appear first)'
    }

    # Form customization
    add_form_extra_fields = {
        'color': TextAreaField(
            'Color Code',
            description='Hex color code (e.g., #007bff)',
            validators=[DataRequired()],
            default='#007bff'
        ),
        'sort_order': IntegerField(
            'Sort Order',
            description='Display order (lower numbers first)',
            validators=[Optional(), NumberRange(min=0)],
            default=0
        )
    }
    edit_form_extra_fields = add_form_extra_fields

    def pre_add(self, item):
        """Process before adding new category."""
        # Ensure color starts with #
        if item.color and not item.color.startswith('#'):
            item.color = f'#{item.color}'
        
        # Set default sort order if not provided
        if item.sort_order is None:
            max_order = self.datamodel.session.query(
                func.max(TaskCategory.sort_order)
            ).scalar() or 0
            item.sort_order = max_order + 1

    def pre_update(self, item):
        """Process before updating category."""
        self.pre_add(item)  # Same validation logic


class TaskModelView(ModelView):
    """
    Enhanced Task view with AI capabilities and advanced features.
    """
    datamodel = SQLAInterface(Task)

    # List view configuration
    list_columns = [
        'title', 'category', 'priority', 'status', 'assigned_to', 
        'due_date', 'progress_percentage', 'is_overdue', 'created_by'
    ]
    show_columns = [
        'title', 'description', 'category', 'priority', 'status',
        'due_date', 'start_date', 'completed_date', 'progress_percentage',
        'estimated_hours', 'actual_hours', 'assigned_to', 'tags',
        'ai_summary', 'ai_tags', 'ai_insights', 'notes',
        'created_by', 'created_on', 'changed_by', 'changed_on'
    ]
    add_columns = [
        'title', 'description', 'category', 'priority', 'status',
        'due_date', 'start_date', 'estimated_hours', 'assigned_to', 'tags'
    ]
    edit_columns = [
        'title', 'description', 'category', 'priority', 'status',
        'due_date', 'start_date', 'completed_date', 'progress_percentage',
        'estimated_hours', 'actual_hours', 'completed', 'assigned_to', 
        'tags', 'notes'
    ]

    # Search and filters
    search_columns = ['title', 'description', 'ai_tags', 'tags']
    list_filters = [
        'category', 'priority', 'status', 'assigned_to', 'created_by',
        'completed', 'due_date', 'created_on'
    ]

    # Order and pagination
    base_order = ('created_on', 'desc')
    page_size = 25

    # Custom labels
    label_columns = {
        'ai_summary': 'AI Summary',
        'ai_tags': 'AI Tags',
        'ai_insights': 'AI Insights',
        'created_by': 'Created By',
        'changed_by': 'Last Modified By',
        'due_date': 'Due Date',
        'start_date': 'Start Date',
        'completed_date': 'Completed Date',
        'progress_percentage': 'Progress %',
        'estimated_hours': 'Est. Hours',
        'actual_hours': 'Actual Hours',
        'is_overdue': 'Overdue'
    }

    # Form field descriptions
    description_columns = {
        'title': 'Brief, descriptive title for the task',
        'description': 'Detailed description of what needs to be done',
        'ai_summary': 'AI-generated summary of the task',
        'ai_tags': 'AI-generated tags for task categorization',
        'ai_insights': 'AI-generated insights and recommendations',
        'priority': 'Task priority level (affects scheduling and notifications)',
        'status': 'Current task status',
        'progress_percentage': 'Completion percentage (0-100)',
        'estimated_hours': 'Estimated time to complete (in hours)',
        'actual_hours': 'Actual time spent (in hours)',
        'tags': 'User-defined tags (comma-separated)'
    }

    # Form customization
    add_form_extra_fields = {
        'generate_ai_content': SelectField(
            'Generate AI Content',
            choices=[
                ('none', 'No AI Generation'),
                ('summary', 'Generate Summary'),
                ('tags', 'Generate Tags'),
                ('both', 'Generate Summary & Tags'),
                ('insights', 'Generate Insights'),
                ('all', 'Generate All AI Content')
            ],
            default='none',
            description='Automatically generate AI content when saving'
        ),
        'progress_percentage': IntegerField(
            'Progress %',
            validators=[Optional(), NumberRange(min=0, max=100)],
            default=0,
            description='Task completion percentage (0-100)'
        )
    }

    # Actions for bulk operations
    @action("generate_ai_summary", "Generate AI Summary",
           "Generate AI summary for selected tasks", "fa-magic")
    def generate_ai_summary(self, items):
        """Generate AI summaries for selected tasks."""
        if not self._check_ai_availability():
            return redirect(self.get_redirect())

        success_count = 0
        ai_manager = self._get_ai_manager()

        for task in items:
            if task.description:
                try:
                    prompt = self._create_summary_prompt(task)
                    summary = ai_manager.generate_text(
                        prompt=prompt,
                        max_tokens=150,
                        temperature=0.3
                    )
                    task.ai_summary = summary.strip()
                    self._log_task_change(task, 'ai_summary', None, task.ai_summary)
                    success_count += 1
                except Exception as e:
                    flash(f'AI generation failed for task "{task.title}": {str(e)}', 'error')

        if success_count > 0:
            self.datamodel.session.commit()
            flash(f'AI summaries generated for {success_count} tasks', 'success')

        return redirect(self.get_redirect())

    @action("generate_ai_tags", "Generate AI Tags",
           "Generate AI tags for selected tasks", "fa-tags")
    def generate_ai_tags(self, items):
        """Generate AI tags for selected tasks."""
        if not self._check_ai_availability():
            return redirect(self.get_redirect())

        success_count = 0
        ai_manager = self._get_ai_manager()

        for task in items:
            if task.description or task.title:
                try:
                    prompt = self._create_tags_prompt(task)
                    tags = ai_manager.generate_text(
                        prompt=prompt,
                        max_tokens=100,
                        temperature=0.5
                    )
                    task.ai_tags = tags.strip()
                    self._log_task_change(task, 'ai_tags', None, task.ai_tags)
                    success_count += 1
                except Exception as e:
                    flash(f'AI tag generation failed for task "{task.title}": {str(e)}', 'error')

        if success_count > 0:
            self.datamodel.session.commit()
            flash(f'AI tags generated for {success_count} tasks', 'success')

        return redirect(self.get_redirect())

    @action("generate_ai_insights", "Generate AI Insights",
           "Generate AI insights for selected tasks", "fa-lightbulb-o")
    def generate_ai_insights(self, items):
        """Generate AI insights for selected tasks."""
        if not self._check_ai_availability():
            return redirect(self.get_redirect())

        success_count = 0
        ai_manager = self._get_ai_manager()

        for task in items:
            if task.description or task.title:
                try:
                    prompt = self._create_insights_prompt(task)
                    insights = ai_manager.generate_text(
                        prompt=prompt,
                        max_tokens=200,
                        temperature=0.7
                    )
                    task.add_ai_insight(insights.strip())
                    self._log_task_change(task, 'ai_insights', None, insights.strip())
                    success_count += 1
                except Exception as e:
                    flash(f'AI insights generation failed for task "{task.title}": {str(e)}', 'error')

        if success_count > 0:
            self.datamodel.session.commit()
            flash(f'AI insights generated for {success_count} tasks', 'success')

        return redirect(self.get_redirect())

    @action("mark_completed", "Mark Completed",
           "Mark selected tasks as completed", "fa-check")
    def mark_completed(self, items):
        """Mark selected tasks as completed."""
        success_count = 0
        
        for task in items:
            if not task.completed:
                old_status = task.status.value if task.status else None
                task.mark_completed()
                self._log_task_change(task, 'status', old_status, task.status.value)
                success_count += 1

        if success_count > 0:
            self.datamodel.session.commit()
            flash(f'{success_count} tasks marked as completed', 'success')
        else:
            flash('No tasks were updated (already completed)', 'warning')

        return redirect(self.get_redirect())

    def pre_add(self, item):
        """Process AI generation and validation before adding item."""
        # Generate AI content if requested
        if hasattr(request, 'form') and 'generate_ai_content' in request.form:
            ai_option = request.form.get('generate_ai_content')
            if ai_option != 'none' and self._check_ai_availability(show_flash=False):
                self._generate_ai_content(item, ai_option)

        # Set default values
        if not item.start_date and item.status == Status.IN_PROGRESS:
            item.start_date = date.today()

        # Update progress based on status
        if item.status == Status.COMPLETED and not item.completed:
            item.mark_completed()
        elif item.status == Status.IN_PROGRESS and item.progress_percentage == 0:
            item.progress_percentage = 10

    def pre_update(self, item):
        """Process before updating item."""
        # Track status changes
        if item.status == Status.COMPLETED and not item.completed:
            item.mark_completed()
        elif item.status != Status.COMPLETED and item.completed:
            item.completed = False
            item.completed_date = None

        # Update start date
        if item.status == Status.IN_PROGRESS and not item.start_date:
            item.start_date = date.today()

    def post_add(self, item):
        """Process after adding item."""
        self._log_task_change(item, 'created', None, 'Task created')

    def post_update(self, item):
        """Process after updating item."""
        self._log_task_change(item, 'updated', None, 'Task updated')

    # Helper methods
    def _check_ai_availability(self, show_flash=True):
        """Check if AI features are available."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager
            return True
        except ImportError:
            if show_flash:
                flash('AI features not available. Please check your configuration.', 'warning')
            return False

    def _get_ai_manager(self):
        """Get AI manager instance."""
        from pgappforge.collaborative.ai.ai_models import AIModelManager
        return AIModelManager()

    def _generate_ai_content(self, item, ai_option):
        """Generate AI content based on option."""
        try:
            ai_manager = self._get_ai_manager()
            
            if ai_option in ['summary', 'both', 'all'] and item.description:
                prompt = self._create_summary_prompt(item)
                item.ai_summary = ai_manager.generate_text(
                    prompt=prompt, max_tokens=150, temperature=0.3
                ).strip()

            if ai_option in ['tags', 'both', 'all'] and (item.description or item.title):
                prompt = self._create_tags_prompt(item)
                item.ai_tags = ai_manager.generate_text(
                    prompt=prompt, max_tokens=100, temperature=0.5
                ).strip()

            if ai_option in ['insights', 'all'] and (item.description or item.title):
                prompt = self._create_insights_prompt(item)
                insights = ai_manager.generate_text(
                    prompt=prompt, max_tokens=200, temperature=0.7
                ).strip()
                item.add_ai_insight(insights)

            flash('AI content generated successfully!', 'success')

        except Exception as e:
            flash(f'AI generation failed: {str(e)}', 'error')

    def _create_summary_prompt(self, task):
        """Create prompt for AI summary generation."""
        context = f"Title: {task.title}\n"
        if task.description:
            context += f"Description: {task.description}\n"
        if task.category:
            context += f"Category: {task.category.name}\n"
        
        return f"""Summarize this task in 1-2 clear, concise sentences:

{context}

Focus on the main objective and key deliverables."""

    def _create_tags_prompt(self, task):
        """Create prompt for AI tags generation."""
        context = f"Title: {task.title}\n"
        if task.description:
            context += f"Description: {task.description}\n"
        if task.category:
            context += f"Category: {task.category.name}\n"
        
        return f"""Generate 3-5 relevant tags for this task. Return only the tags separated by commas:

{context}

Tags should be short, relevant keywords that help categorize and find this task."""

    def _create_insights_prompt(self, task):
        """Create prompt for AI insights generation."""
        context = f"Title: {task.title}\n"
        if task.description:
            context += f"Description: {task.description}\n"
        if task.category:
            context += f"Category: {task.category.name}\n"
        if task.priority:
            context += f"Priority: {task.priority.value}\n"
        if task.due_date:
            context += f"Due Date: {task.due_date}\n"
        
        return f"""Analyze this task and provide helpful insights:

{context}

Provide insights about:
1. Potential challenges or considerations
2. Suggested approach or breakdown
3. Dependencies or prerequisites
4. Success criteria or completion indicators

Keep insights practical and actionable."""

    def _log_task_change(self, task, field_name, old_value, new_value):
        """Log task changes for audit trail."""
        try:
            history = TaskHistory(
                task_id=task.id,
                field_name=field_name,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                change_type='update',
                user_agent=request.headers.get('User-Agent', ''),
                ip_address=request.remote_addr
            )
            self.datamodel.session.add(history)
        except Exception as e:
            # Don't fail the main operation if logging fails
            print(f"Failed to log task change: {e}")


class TaskDashboardView(BaseView):
    """
    Dashboard view showing task statistics and AI insights.
    """
    default_view = 'dashboard'

    @expose('/dashboard/')
    @has_access
    def dashboard(self):
        """Show task dashboard with comprehensive statistics."""
        # Get task statistics
        stats = Task.get_statistics(self.appbuilder.session)
        
        # Get recent tasks
        recent_tasks = self.appbuilder.session.query(Task)\
                         .order_by(Task.created_on.desc())\
                         .limit(5).all()
        
        # Get overdue tasks
        overdue_tasks = self.appbuilder.session.query(Task)\
                          .filter(
                              Task.due_date < date.today(),
                              Task.completed == False
                          )\
                          .order_by(Task.due_date.asc())\
                          .limit(5).all()
        
        # Get upcoming tasks (due in next 7 days)
        upcoming_tasks = self.appbuilder.session.query(Task)\
                           .filter(
                               and_(
                                   Task.due_date >= date.today(),
                                   Task.due_date <= date.today() + timedelta(days=7),
                                   Task.completed == False
                               )
                           )\
                           .order_by(Task.due_date.asc())\
                           .limit(5).all()
        
        # Category statistics
        category_stats = self.appbuilder.session.query(
            TaskCategory.name, 
            func.count(Task.id).label('task_count'),
            func.sum(func.case([(Task.completed == True, 1)], else_=0)).label('completed_count')
        ).outerjoin(Task)\
         .group_by(TaskCategory.name)\
         .all()

        # User productivity (if multi-user)
        user_stats = self.appbuilder.session.query(
            Task.created_by_fk,
            func.count(Task.id).label('total_tasks'),
            func.sum(func.case([(Task.completed == True, 1)], else_=0)).label('completed_tasks')
        ).group_by(Task.created_by_fk)\
         .all()

        dashboard_data = {
            'stats': stats,
            'recent_tasks': recent_tasks,
            'overdue_tasks': overdue_tasks,
            'upcoming_tasks': upcoming_tasks,
            'category_stats': category_stats,
            'user_stats': user_stats
        }

        return self.render_template('dashboard.html', **dashboard_data)

    @expose('/ai-insights/')
    @has_access
    def ai_insights(self):
        """Show AI-generated insights about tasks and productivity."""
        try:
            from pgappforge.collaborative.ai.ai_models import AIModelManager
            ai_manager = AIModelManager()

            # Get recent tasks for analysis
            recent_tasks = self.appbuilder.session.query(Task)\
                          .filter(Task.created_on >= datetime.now() - timedelta(days=30))\
                          .order_by(Task.created_on.desc())\
                          .limit(20).all()

            if recent_tasks:
                # Prepare task data for analysis
                task_data = []
                for task in recent_tasks:
                    task_info = f"""
Title: {task.title}
Category: {task.category.name if task.category else 'None'}
Priority: {task.priority.value if task.priority else 'None'}
Status: {task.status.value if task.status else 'None'}
Description: {task.description[:200] if task.description else 'No description'}...
"""
                    task_data.append(task_info.strip())

                # Generate comprehensive insights
                prompt = f"""Analyze these recent tasks and provide productivity insights:

{chr(10).join(task_data)}

Provide analysis on:
1. **Workflow Patterns**: Common themes, task types, and work patterns
2. **Productivity Insights**: Efficiency observations and bottlenecks
3. **Priority Management**: How well priorities are distributed and managed
4. **Recommendations**: Specific actionable suggestions for improvement
5. **Focus Areas**: What areas need attention or optimization

Format your response in clear sections with actionable insights."""

                insights = ai_manager.generate_text(
                    prompt=prompt,
                    max_tokens=800,
                    temperature=0.7
                )

                # Get task statistics for context
                stats = Task.get_statistics(self.appbuilder.session)

                return self.render_template(
                    'ai_insights.html',
                    insights=insights,
                    task_count=len(recent_tasks),
                    stats=stats
                )
            else:
                return self.render_template(
                    'ai_insights.html',
                    insights="No recent tasks available for analysis. Create some tasks first!",
                    task_count=0,
                    stats={}
                )

        except ImportError:
            flash('AI features not available. Please configure AI providers.', 'warning')
            return redirect(url_for('TaskDashboardView.dashboard'))
        except Exception as e:
            flash(f'AI analysis failed: {str(e)}', 'error')
            return redirect(url_for('TaskDashboardView.dashboard'))

    @expose('/reports/')
    @has_access
    def reports(self):
        """Show detailed reports and analytics."""
        # Time-based statistics
        today = date.today()
        this_week = today - timedelta(days=today.weekday())
        this_month = today.replace(day=1)
        
        # Tasks created this week/month
        tasks_this_week = self.appbuilder.session.query(Task)\
                            .filter(Task.created_on >= this_week)\
                            .count()
        
        tasks_this_month = self.appbuilder.session.query(Task)\
                             .filter(Task.created_on >= this_month)\
                             .count()
        
        # Completion trends
        completed_this_week = self.appbuilder.session.query(Task)\
                                .filter(
                                    Task.completed_date >= this_week,
                                    Task.completed == True
                                )\
                                .count()
        
        # Average completion time
        completed_tasks = self.appbuilder.session.query(Task)\
                            .filter(Task.completed == True)\
                            .filter(Task.start_date.isnot(None))\
                            .filter(Task.completed_date.isnot(None))\
                            .all()
        
        avg_completion_days = 0
        if completed_tasks:
            total_days = sum([
                (task.completed_date.date() - task.start_date).days 
                for task in completed_tasks 
                if task.start_date and task.completed_date
            ])
            avg_completion_days = total_days / len(completed_tasks) if completed_tasks else 0

        report_data = {
            'tasks_this_week': tasks_this_week,
            'tasks_this_month': tasks_this_month,
            'completed_this_week': completed_this_week,
            'avg_completion_days': round(avg_completion_days, 1),
            'total_completed': len(completed_tasks)
        }

        return self.render_template('reports.html', **report_data)


class TaskHistoryModelView(ModelView):
    """
    View for task change history and audit trail.
    """
    datamodel = SQLAInterface(TaskHistory)

    # List view configuration
    list_columns = [
        'task', 'field_name', 'old_value', 'new_value', 
        'change_type', 'changed_by', 'changed_on'
    ]
    show_columns = [
        'task', 'field_name', 'old_value', 'new_value', 
        'change_type', 'change_reason', 'user_agent', 
        'ip_address', 'changed_by', 'changed_on'
    ]

    # Make read-only
    add_columns = []
    edit_columns = []
    can_create = False
    can_edit = False
    can_delete = False

    # Search and filters
    search_columns = ['field_name', 'old_value', 'new_value']
    list_filters = ['task', 'field_name', 'change_type', 'changed_by', 'changed_on']

    # Order by most recent
    base_order = ('changed_on', 'desc')
    page_size = 50

    # Custom labels
    label_columns = {
        'field_name': 'Field Changed',
        'old_value': 'Previous Value',
        'new_value': 'New Value',
        'change_type': 'Change Type',
        'change_reason': 'Reason',
        'user_agent': 'Browser',
        'ip_address': 'IP Address',
        'changed_by': 'Changed By',
        'changed_on': 'Changed On'
    }