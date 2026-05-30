"""
Root conftest.py — sets SQLALCHEMY_DATABASE_URI for all tests that don't
use a config file, so none fall back to SQLite (PostgreSQL-only project).
"""
import os
import pytest

# Ensure every test that creates a Flask app gets PostgreSQL by default
_DEFAULT_DB = (
    os.environ.get("SQLALCHEMY_DATABASE_URI")
    or os.environ.get("PGAPPFORGE_DB")
    or "postgresql:///pgaf_test"
)
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", _DEFAULT_DB)
