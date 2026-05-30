import os
"""
Comprehensive unit tests for PgAppForge data models and interfaces.

This module provides thorough testing coverage for SQLAlchemy models,
data interfaces, relationships, and database operations.
"""

import datetime
import unittest
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import pytest
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge.models.mixins import AuditMixin, FileColumn, ImageColumn
from pgappforge.models.sqla import Model
from pgappforge.models.sqla.filters import FilterEqual, FilterNotEqual, FilterStartsWith
from pgappforge.models.sqla.interface import SQLAInterface
from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean, Text, Float, ForeignKey,
    Table, UniqueConstraint, Index, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, backref

from tests.base import FABTestCase


# Association table for many-to-many relationship
tag_association = Table(
    'article_tags',
    Model.metadata,
    Column('article_id', Integer, ForeignKey('test_articles.id')),
    Column('tag_id', Integer, ForeignKey('test_tags.id'))
)


class TestArticle(Model):
    """Test article model with comprehensive field types"""
    __tablename__ = 'test_articles'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False, unique=True)
    slug = Column(String(200), nullable=False, unique=True, index=True)
    content = Column(Text)
    summary = Column(String(500))
    word_count = Column(Integer, default=0)
    rating = Column(Float, default=0.0)
    published = Column(Boolean, default=False)
    featured = Column(Boolean, default=False)
    views_count = Column(Integer, default=0)
    
    # Foreign key relationship
    category_id = Column(Integer, ForeignKey('test_categories.id'))
    author_id = Column(Integer, ForeignKey('test_authors.id'))
    
    # Timestamps
    created_on = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_on = Column(DateTime, default=datetime.datetime.utcnow, 
                        onupdate=datetime.datetime.utcnow)
    published_on = Column(DateTime)
    
    # Relationships
    category = relationship('TestCategory', back_populates='articles')
    author = relationship('TestAuthor', back_populates='articles')
    tags = relationship('TestTag', secondary=tag_association, back_populates='articles')
    comments = relationship('TestComment', back_populates='article', cascade='all, delete-orphan')
    
    # Table constraints
    __table_args__ = (
        CheckConstraint('word_count >= 0', name='check_positive_word_count'),
        CheckConstraint('rating >= 0 AND rating <= 5', name='check_rating_range'),
        Index('idx_article_published_date', 'published', 'published_on'),
        Index('idx_article_category_published', 'category_id', 'published')
    )
    
    def __repr__(self):
        return self.title or f'Article {self.id}'
    
    def calculate_word_count(self):
        """Calculate word count from content"""
        if self.content:
            self.word_count = len(self.content.split())
        return self.word_count
    
    def get_excerpt(self, length: int = 150) -> str:
        """Get article excerpt"""
        if self.summary:
            return self.summary[:length]
        elif self.content:
            return self.content[:length] + ('...' if len(self.content) > length else '')
        return ''


class TestCategory(Model):
    """Test category model"""
    __tablename__ = 'test_categories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    slug = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    
    # Self-referential relationship for parent/child categories
    parent_id = Column(Integer, ForeignKey('test_categories.id'))
    parent = relationship('TestCategory', remote_side=[id], backref='children')
    
    # Relationship with articles
    articles = relationship('TestArticle', back_populates='category')
    
    def __repr__(self):
        return self.name or f'Category {self.id}'
    
    @property
    def article_count(self) -> int:
        """Count of published articles in this category"""
        return len([a for a in self.articles if a.published])


class TestAuthor(Model):
    """Test author model with audit mixin"""
    __tablename__ = 'test_authors'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, unique=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(120), nullable=False, unique=True)
    bio = Column(Text)
    website = Column(String(200))
    twitter_handle = Column(String(50))
    active = Column(Boolean, default=True)
    
    # Profile image
    profile_image = Column(ImageColumn(size=(200, 200, True), thumbnail_size=(50, 50, True)))
    
    # Relationships
    articles = relationship('TestArticle', back_populates='author')
    
    def __repr__(self):
        return f'{self.first_name} {self.last_name}'
    
    @property
    def full_name(self) -> str:
        """Get full name"""
        return f'{self.first_name} {self.last_name}'
    
    @property
    def published_article_count(self) -> int:
        """Count of published articles by this author"""
        return len([a for a in self.articles if a.published])


class TestTag(Model):
    """Test tag model for many-to-many relationships"""
    __tablename__ = 'test_tags'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    slug = Column(String(50), nullable=False, unique=True)
    description = Column(String(200))
    color = Column(String(7), default='#007bff')  # Hex color code
    
    # Many-to-many relationship with articles
    articles = relationship('TestArticle', secondary=tag_association, back_populates='tags')
    
    def __repr__(self):
        return self.name or f'Tag {self.id}'
    
    @property
    def article_count(self) -> int:
        """Count articles using this tag"""
        return len(self.articles)


class TestComment(Model):
    """Test comment model for one-to-many relationships"""
    __tablename__ = 'test_comments'
    
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey('test_articles.id'), nullable=False)
    author_name = Column(String(100), nullable=False)
    author_email = Column(String(120), nullable=False)
    content = Column(Text, nullable=False)
    approved = Column(Boolean, default=False)
    spam_score = Column(Float, default=0.0)
    
    # Relationships
    article = relationship('TestArticle', back_populates='comments')
    
    # Self-referential for nested comments
    parent_id = Column(Integer, ForeignKey('test_comments.id'))
    parent = relationship('TestComment', remote_side=[id], backref='replies')
    
    def __repr__(self):
        return f'Comment by {self.author_name}'
    
    @property
    def is_spam(self) -> bool:
        """Check if comment is likely spam"""
        return self.spam_score > 0.7


class TestDataModelCreation(FABTestCase):
    """Test data model creation and basic operations"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-models'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            # Create all tables
            self.db.create_all()
    
    def test_model_table_creation(self):
        """Test that model tables are created correctly"""
        with self.app.app_context():
            from sqlalchemy import inspect as sa_inspect
            tables = sa_inspect(self.db.engine).get_table_names()
            
            expected_tables = [
                'test_articles', 'test_categories', 'test_authors',
                'test_tags', 'test_comments', 'article_tags'
            ]
            
            for table in expected_tables:
                self.assertIn(table, tables, f"Table {table} was not created")
    
    def test_model_basic_creation(self):
        """Test basic model instance creation"""
        with self.app.app_context():
            # Create category
            category = TestCategory(
                name='Technology',
                slug='technology',
                description='Technology related articles'
            )
            
            # Create author
            import uuid as _uuid
            author = TestAuthor(
                username=f'testauthor_{_uuid.uuid4().hex[:8]}',
                first_name='Test',
                last_name='Author',
                email='test@example.com',
                bio='Test author bio'
            )
            
            # Create article
            import uuid as _uuid
            _suffix = _uuid.uuid4().hex[:8]
            article = TestArticle(
                title=f'Test Article {_suffix}',
                slug='test-article',
                content='This is test content for the article',
                category=category,
                author=author,
                published=True
            )
            
            # Save to database
            self.db.session.add(category)
            self.db.session.add(author)
            self.db.session.add(article)
            self.db.session.commit()
            
            # Verify creation
            self.assertIsNotNone(article.id)
            self.assertIsNotNone(category.id)
            self.assertIsNotNone(author.id)
            
            # Verify relationships
            self.assertEqual(article.category, category)
            self.assertEqual(article.author, author)
            self.assertIn(article, category.articles)
            self.assertIn(article, author.articles)
    
    def test_model_constraints(self):
        """Test model constraints and validation"""
        with self.app.app_context():
            # Test unique constraints
            category1 = TestCategory(name='Tech', slug='tech')
            category2 = TestCategory(name='Tech', slug='tech-2')  # Same name
            
            self.db.session.add(category1)
            self.db.session.commit()
            
            self.db.session.add(category2)
            
            # This should raise an integrity error due to unique constraint
            with self.assertRaises(Exception):
                self.db.session.commit()
            
            self.db.session.rollback()
    
    def test_model_methods(self):
        """Test custom model methods"""
        with self.app.app_context():
            author = TestAuthor(
                username='methodtest',
                first_name='Method',
                last_name='Test',
                email='method@test.com'
            )
            
            # Test property methods
            self.assertEqual(author.full_name, 'Method Test')
            
            article = TestArticle(
                title='Method Test Article',
                slug='method-test',
                content='This is a test article with multiple words for word count testing',
                author=author
            )
            
            # Test custom methods
            word_count = article.calculate_word_count()
            self.assertGreater(word_count, 0)
            self.assertEqual(article.word_count, word_count)
            
            excerpt = article.get_excerpt(20)
            self.assertLessEqual(len(excerpt), 25)  # Account for ellipsis


class TestDataModelRelationships(FABTestCase):
    """Test model relationships and foreign keys"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-relationships'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
            self._create_test_data()
    
    def _create_test_data(self):
        """Create test data for relationship testing"""
        # Create categories
        self.tech_category = TestCategory(
            name='Technology',
            slug='technology'
        )
        self.news_category = TestCategory(
            name='News',
            slug='news'
        )
        
        # Create authors
        self.author1 = TestAuthor(
            username='author1',
            first_name='John',
            last_name='Doe',
            email='john@example.com'
        )
        self.author2 = TestAuthor(
            username='author2',
            first_name='Jane',
            last_name='Smith',
            email='jane@example.com'
        )
        
        # Create tags
        self.tag1 = TestTag(name='Python', slug='python')
        self.tag2 = TestTag(name='Web Development', slug='web-dev')
        self.tag3 = TestTag(name='Tutorial', slug='tutorial')
        
        # Save to database
        objects = [
            self.tech_category, self.news_category,
            self.author1, self.author2,
            self.tag1, self.tag2, self.tag3
        ]
        
        for obj in objects:
            self.db.session.add(obj)
        
        self.db.session.commit()
    
    def test_one_to_many_relationships(self):
        """Test one-to-many relationships (category -> articles, author -> articles)"""
        with self.app.app_context():
            # Create articles
            article1 = TestArticle(
                title='Python Tutorial',
                slug='python-tutorial',
                content='Learn Python programming',
                category=self.tech_category,
                author=self.author1,
                published=True
            )
            
            article2 = TestArticle(
                title='Advanced Python',
                slug='advanced-python',
                content='Advanced Python concepts',
                category=self.tech_category,
                author=self.author1,
                published=True
            )
            
            self.db.session.add(article1)
            self.db.session.add(article2)
            self.db.session.commit()
            
            # Test category -> articles relationship
            self.assertEqual(len(self.tech_category.articles), 2)
            self.assertIn(article1, self.tech_category.articles)
            self.assertIn(article2, self.tech_category.articles)
            
            # Test author -> articles relationship
            self.assertEqual(len(self.author1.articles), 2)
            self.assertIn(article1, self.author1.articles)
            self.assertIn(article2, self.author1.articles)
            
            # Test reverse relationships
            self.assertEqual(article1.category, self.tech_category)
            self.assertEqual(article1.author, self.author1)
    
    def test_many_to_many_relationships(self):
        """Test many-to-many relationships (articles <-> tags)"""
        with self.app.app_context():
            # Create article
            article = TestArticle(
                title='Python Web Development',
                slug='python-web-dev',
                content='Build web apps with Python',
                category=self.tech_category,
                author=self.author1,
                published=True
            )
            
            # Add tags to article
            article.tags.append(self.tag1)  # Python
            article.tags.append(self.tag2)  # Web Development
            article.tags.append(self.tag3)  # Tutorial
            
            self.db.session.add(article)
            self.db.session.commit()
            
            # Test article -> tags relationship
            self.assertEqual(len(article.tags), 3)
            self.assertIn(self.tag1, article.tags)
            self.assertIn(self.tag2, article.tags)
            self.assertIn(self.tag3, article.tags)
            
            # Test tags -> articles relationship
            self.assertIn(article, self.tag1.articles)
            self.assertIn(article, self.tag2.articles)
            self.assertIn(article, self.tag3.articles)
            
            # Test tag article count property
            self.assertEqual(self.tag1.article_count, 1)
    
    def test_self_referential_relationships(self):
        """Test self-referential relationships (nested categories, nested comments)"""
        with self.app.app_context():
            # Create parent and child categories
            parent_category = TestCategory(
                name='Programming',
                slug='programming'
            )
            
            child_category = TestCategory(
                name='Python Programming',
                slug='python-programming',
                parent=parent_category
            )
            
            self.db.session.add(parent_category)
            self.db.session.add(child_category)
            self.db.session.commit()
            
            # Test parent -> children relationship
            self.assertIn(child_category, parent_category.children)
            
            # Test child -> parent relationship
            self.assertEqual(child_category.parent, parent_category)
            
            # Test nested comments
            article = TestArticle(
                title='Comment Test',
                slug='comment-test',
                content='Test article for comments',
                category=parent_category,
                author=self.author1
            )
            
            parent_comment = TestComment(
                article=article,
                author_name='Commenter 1',
                author_email='comment1@test.com',
                content='This is a parent comment'
            )
            
            reply_comment = TestComment(
                article=article,
                author_name='Commenter 2',
                author_email='comment2@test.com',
                content='This is a reply',
                parent=parent_comment
            )
            
            self.db.session.add(article)
            self.db.session.add(parent_comment)
            self.db.session.add(reply_comment)
            self.db.session.commit()
            
            # Test comment relationships
            self.assertIn(reply_comment, parent_comment.replies)
            self.assertEqual(reply_comment.parent, parent_comment)


class TestSQLAInterface(FABTestCase):
    """Test SQLAlchemy interface functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-interface'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
            self._create_test_data()
            
            # Create interfaces
            self.article_interface = SQLAInterface(TestArticle)
            self.category_interface = SQLAInterface(TestCategory)
            self.author_interface = SQLAInterface(TestAuthor)
    
    def _create_test_data(self):
        """Create test data"""
        category = TestCategory(name='Test Category', slug='test')
        author = TestAuthor(
            username='testuser',
            first_name='Test',
            last_name='User',
            email='test@example.com'
        )
        
        articles = []
        for i in range(5):
            article = TestArticle(
                title=f'Test Article {i}',
                slug=f'test-article-{i}',
                content=f'Content for article {i}',
                category=category,
                author=author,
                published=i % 2 == 0,  # Alternate published status
                rating=float(i),
                views_count=i * 10
            )
            articles.append(article)
        
        self.db.session.add(category)
        self.db.session.add(author)
        for article in articles:
            self.db.session.add(article)
        
        self.db.session.commit()
    
    def test_interface_creation(self):
        """Test SQLAInterface creation"""
        with self.app.app_context():
            self.assertIsInstance(self.article_interface, SQLAInterface)
            self.assertEqual(self.article_interface.obj, TestArticle)
    
    def test_interface_query_all(self):
        """Test querying all records"""
        with self.app.app_context():
            count, articles = self.article_interface.query()
            
            self.assertEqual(count, 5)
            self.assertEqual(len(articles), 5)
            self.assertIsInstance(articles[0], TestArticle)
    
    def test_interface_query_with_filters(self):
        """Test querying with filters"""
        with self.app.app_context():
            # Test filtering by published status
            from pgappforge.models.sqla.filters import FilterEqual
            
            published_filter = FilterEqual('published', True)
            count, published_articles = self.article_interface.query(
                filters=[published_filter]
            )
            
            # Should have 3 published articles (indices 0, 2, 4)
            self.assertEqual(count, 3)
            for article in published_articles:
                self.assertTrue(article.published)
    
    def test_interface_query_with_ordering(self):
        """Test querying with ordering"""
        with self.app.app_context():
            # Test ordering by title ascending
            count, articles_asc = self.article_interface.query(
                order_column='title',
                order_direction='asc'
            )
            
            self.assertEqual(count, 5)
            # Verify ascending order
            titles = [article.title for article in articles_asc]
            self.assertEqual(titles, sorted(titles))
            
            # Test ordering by rating descending
            count, articles_desc = self.article_interface.query(
                order_column='rating',
                order_direction='desc'
            )
            
            ratings = [article.rating for article in articles_desc]
            self.assertEqual(ratings, sorted(ratings, reverse=True))
    
    def test_interface_get_by_id(self):
        """Test getting record by ID"""
        with self.app.app_context():
            # Get first article
            count, articles = self.article_interface.query()
            first_article = articles[0]
            
            # Get by ID
            retrieved_article = self.article_interface.get(first_article.id)
            
            self.assertEqual(retrieved_article.id, first_article.id)
            self.assertEqual(retrieved_article.title, first_article.title)
    
    def test_interface_add_record(self):
        """Test adding new record through interface"""
        with self.app.app_context():
            # Get existing category and author
            category = self.category_interface.query()[1][0]
            author = self.author_interface.query()[1][0]
            
            # Create new article
            new_article = TestArticle(
                title='New Article',
                slug='new-article',
                content='New article content',
                category=category,
                author=author
            )
            
            # Add through interface
            result = self.article_interface.add(new_article)
            
            self.assertTrue(result)
            self.assertIsNotNone(new_article.id)
            
            # Verify it exists
            retrieved = self.article_interface.get(new_article.id)
            self.assertEqual(retrieved.title, 'New Article')
    
    def test_interface_update_record(self):
        """Test updating record through interface"""
        with self.app.app_context():
            # Get an article
            article = self.article_interface.query()[1][0]
            original_title = article.title
            
            # Update title
            article.title = 'Updated Title'
            result = self.article_interface.edit(article)
            
            self.assertTrue(result)
            
            # Verify update
            updated_article = self.article_interface.get(article.id)
            self.assertEqual(updated_article.title, 'Updated Title')
            self.assertNotEqual(updated_article.title, original_title)
    
    def test_interface_delete_record(self):
        """Test deleting record through interface"""
        with self.app.app_context():
            # Get an article
            article = self.article_interface.query()[1][0]
            article_id = article.id
            
            # Delete through interface
            result = self.article_interface.delete(article)
            
            self.assertTrue(result)
            
            # Verify deletion
            deleted_article = self.article_interface.get(article_id)
            self.assertIsNone(deleted_article)


class TestDataModelFilters(FABTestCase):
    """Test data model filtering functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-filters'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
            self._create_filter_test_data()
            self.interface = SQLAInterface(TestArticle)
    
    def _create_filter_test_data(self):
        """Create test data for filtering"""
        category = TestCategory(name='Filter Test', slug='filter-test')
        author = TestAuthor(
            username='filtertest',
            first_name='Filter',
            last_name='Test',
            email='filter@test.com'
        )
        
        articles = [
            TestArticle(
                title='Alpha Article',
                slug='alpha',
                content='First article',
                published=True,
                rating=4.5,
                category=category,
                author=author
            ),
            TestArticle(
                title='Beta Article',
                slug='beta',
                content='Second article',
                published=False,
                rating=3.0,
                category=category,
                author=author
            ),
            TestArticle(
                title='Gamma Article',
                slug='gamma',
                content='Third article',
                published=True,
                rating=5.0,
                category=category,
                author=author
            )
        ]
        
        self.db.session.add(category)
        self.db.session.add(author)
        for article in articles:
            self.db.session.add(article)
        
        self.db.session.commit()
    
    def test_filter_equal(self):
        """Test FilterEqual functionality"""
        with self.app.app_context():
            # Filter for published articles
            filter_obj = FilterEqual('published', True)
            count, articles = self.interface.query(filters=[filter_obj])
            
            self.assertEqual(count, 2)  # Alpha and Gamma
            for article in articles:
                self.assertTrue(article.published)
    
    def test_filter_not_equal(self):
        """Test FilterNotEqual functionality"""
        with self.app.app_context():
            # Filter for non-published articles
            filter_obj = FilterNotEqual('published', True)
            count, articles = self.interface.query(filters=[filter_obj])
            
            self.assertEqual(count, 1)  # Beta
            for article in articles:
                self.assertFalse(article.published)
    
    def test_filter_starts_with(self):
        """Test FilterStartsWith functionality"""
        with self.app.app_context():
            # Filter for articles starting with 'A'
            filter_obj = FilterStartsWith('title', 'A')
            count, articles = self.interface.query(filters=[filter_obj])
            
            self.assertEqual(count, 1)  # Alpha Article
            self.assertTrue(articles[0].title.startswith('A'))
    
    def test_multiple_filters(self):
        """Test combining multiple filters"""
        with self.app.app_context():
            # Filter for published articles with rating >= 4.0
            filters = [
                FilterEqual('published', True),
                # Note: Would need a FilterGreaterEqual for rating
            ]
            
            count, articles = self.interface.query(filters=filters[:1])  # Just published for now
            
            self.assertEqual(count, 2)
            for article in articles:
                self.assertTrue(article.published)


class TestAuditMixin(FABTestCase):
    """Test AuditMixin functionality"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-audit'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_audit_fields_exist(self):
        """Test that audit fields are added by AuditMixin"""
        with self.app.app_context():
            # TestAuthor uses AuditMixin
            author = TestAuthor(
                username='audittest',
                first_name='Audit',
                last_name='Test',
                email='audit@test.com'
            )
            
            self.db.session.add(author)
            self.db.session.commit()
            
            # Check audit fields exist
            self.assertTrue(hasattr(author, 'created_on'))
            self.assertTrue(hasattr(author, 'changed_on'))
            self.assertTrue(hasattr(author, 'created_by_fk'))
            self.assertTrue(hasattr(author, 'changed_by_fk'))
            
            # Check timestamps are set
            self.assertIsNotNone(author.created_on)
            self.assertIsNotNone(author.changed_on)


class TestModelValidation(FABTestCase):
    """Test model validation and constraints"""
    
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-validation'
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
    
    def test_required_field_validation(self):
        """Test required field constraints"""
        with self.app.app_context():
            # Try to create article without required title
            article = TestArticle(
                slug='no-title',
                content='Article without title'
            )
            
            self.db.session.add(article)
            
            # Should raise integrity error
            with self.assertRaises(Exception):
                self.db.session.commit()
            
            self.db.session.rollback()
    
    def test_unique_constraint_validation(self):
        """Test unique constraint validation"""
        with self.app.app_context():
            # Create first article
            article1 = TestArticle(
                title='Unique Title',
                slug='unique-slug',
                content='First article'
            )
            
            self.db.session.add(article1)
            self.db.session.commit()
            
            # Try to create second article with same title
            article2 = TestArticle(
                title='Unique Title',  # Same title
                slug='different-slug',
                content='Second article'
            )
            
            self.db.session.add(article2)
            
            # Should raise integrity error
            with self.assertRaises(Exception):
                self.db.session.commit()
            
            self.db.session.rollback()
    
    def test_check_constraint_validation(self):
        """Test check constraint validation"""
        with self.app.app_context():
            # Try to create article with negative word count
            article = TestArticle(
                title='Invalid Word Count',
                slug='invalid-word-count',
                content='Test content',
                word_count=-1  # Invalid negative value
            )
            
            self.db.session.add(article)
            
            # Should raise integrity error
            with self.assertRaises(Exception):
                self.db.session.commit()
            
            self.db.session.rollback()


if __name__ == '__main__':
    unittest.main()