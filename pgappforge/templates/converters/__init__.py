"""
Domain schema converters for pgappforge template registry.

Each converter takes a domain-specific schema definition and converts it
to the pgappforge template JSON format (tables + column definitions).

Available converters:
  (Add as domain standards are implemented)

Usage::

    from pgappforge.templates.converters import convert_fhir_bundle

The converters are used by 'flask forge templates import' to process
schema definitions from their native formats.
"""
