"""
pgappforge/ai/__init__.py

AI subsystem for PgAppForge.

Sub-modules:
  codegen — LLM-powered module generation from natural language descriptions
"""
from pgappforge.ai.codegen import GeneratedModule, PgAppForgeCodegen

__all__ = ["PgAppForgeCodegen", "GeneratedModule"]
