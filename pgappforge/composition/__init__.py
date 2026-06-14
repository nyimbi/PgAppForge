"""PgAppForge composition primitives.

Provides model mixin injection, view slot registry, and schema extension utilities.
"""
from pgappforge.composition.mixins import ModelMixinRegistry, register_mixin, apply_all_mixins, get_mixin_registry

__all__ = ['ModelMixinRegistry', 'register_mixin', 'apply_all_mixins', 'get_mixin_registry']
