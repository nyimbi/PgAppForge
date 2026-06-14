"""GraphQL federation support for PgAppForge.

Extends the existing Strawberry GraphQL schema (pgappforge/graphql/) with
Apollo Federation v2 directives so independently deployed plugins can be
queried as a unified GraphQL supergraph.

Pattern
-------
Each plugin exposes its domain entities as federated types. The gateway
(Apollo Router, Cosmo, or Hive) merges them into a single API.

    # In finance/ar plugin:
    from pgappforge.graphql.federation import federated_type, key_field

    @federated_type(key='id')
    class ARInvoice:
        id: str
        tenant_id: str
        total_amount_cents: int
        status: str

    # In CRM plugin:
    @federated_type(key='id')
    class Customer:
        id: str
        name: str
        # Extend ARInvoice reference:
        invoices: list['ARInvoice']

Usage — register types with the federation registry:
    from pgappforge.graphql.federation import FederationRegistry, get_federation_registry

    registry = get_federation_registry()
    registry.register('ARInvoice', ARInvoice, plugin='finance.ar')
    schema = registry.build_schema()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class FederatedTypeEntry:
	"""Metadata about a type registered for federation."""
	name:       str
	cls:        type
	plugin:     str
	key_fields: list[str]
	description: str = ''


class FederationRegistry:
	"""Registry of federated GraphQL types across all plugins.

	Each plugin registers its domain entities. The registry builds a
	combined schema with proper @key directives for federation.
	"""

	def __init__(self) -> None:
		self._types: dict[str, FederatedTypeEntry] = {}

	def register(
		self,
		type_name: str,
		cls: type,
		plugin: str,
		key_fields: list[str] | None = None,
		description: str = '',
	) -> None:
		"""Register *cls* as a federated GraphQL type named *type_name*."""
		if type_name in self._types:
			log.warning(
				"FederationRegistry: overwriting type %r (was from plugin %r)",
				type_name, self._types[type_name].plugin,
			)
		self._types[type_name] = FederatedTypeEntry(
			name=type_name,
			cls=cls,
			plugin=plugin,
			key_fields=key_fields or ['id'],
			description=description,
		)
		log.debug("FederationRegistry: registered %s from %s (key=%s)", type_name, plugin, key_fields)

	def list_types(self) -> list[FederatedTypeEntry]:
		return list(self._types.values())

	def list_by_plugin(self, plugin: str) -> list[FederatedTypeEntry]:
		return [t for t in self._types.values() if t.plugin == plugin]

	def get(self, type_name: str) -> FederatedTypeEntry | None:
		return self._types.get(type_name)

	def build_schema_sdl(self) -> str:
		"""Generate Apollo Federation v2 SDL for all registered types.

		Returns a string of GraphQL SDL with @key directives that can be
		uploaded to Apollo Studio or used with Cosmo/Hive.
		"""
		lines = [
			'extend schema @link(url: "https://specs.apollo.dev/federation/v2.0", import: ["@key", "@shareable", "@external"])',
			'',
		]
		for entry in self._types.values():
			if entry.description:
				lines.append(f'"""')
				lines.append(entry.description)
				lines.append(f'"""')
			key_str = ' '.join(f'@key(fields: "{f}")' for f in entry.key_fields)
			lines.append(f'type {entry.name} {key_str} {{')
			# Introspect class annotations for field declarations
			annotations = getattr(entry.cls, '__annotations__', {})
			for field_name, field_type in annotations.items():
				if field_name.startswith('_'):
					continue
				gql_type = _python_to_gql_type(field_type)
				lines.append(f'    {field_name}: {gql_type}')
			if not annotations:
				lines.append('    id: ID!')
			lines.append('}')
			lines.append('')
		return '\n'.join(lines)

	def build_strawberry_schema(self) -> Any:
		"""Build a Strawberry federation schema from registered types.

		Returns the Strawberry schema object or None if strawberry is not installed.
		"""
		try:
			import strawberry
			from strawberry.federation.schema import Schema as FedSchema
		except ImportError:
			log.warning("FederationRegistry.build_strawberry_schema: strawberry not installed")
			return None

		# Collect all registered types and wrap them as Strawberry federation types
		fed_types = []
		for entry in self._types.values():
			keys = entry.key_fields
			# Decorate the class as a strawberry federation type with @key
			try:
				decorated = strawberry.federation.type(entry.cls, keys=keys, description=entry.description)
				fed_types.append(decorated)
			except Exception as exc:
				log.warning("FederationRegistry: cannot decorate %s — %s", entry.name, exc)

		if not fed_types:
			return None

		@strawberry.type
		class Query:
			@strawberry.field
			def _service(self) -> str:
				return "PgAppForge GraphQL Federation"

		try:
			return FedSchema(query=Query, types=fed_types, enable_federation_2=True)
		except Exception as exc:
			log.warning("FederationRegistry.build_strawberry_schema: %s", exc)
			return None


def _python_to_gql_type(python_type: Any) -> str:
	"""Best-effort conversion of Python type annotation to GraphQL type string."""
	type_map = {
		'str': 'String!', 'int': 'Int!', 'float': 'Float!',
		'bool': 'Boolean!', 'Any': 'String',
	}
	name = getattr(python_type, '__name__', None) or str(python_type)
	# Handle Optional[X] → X
	origin = getattr(python_type, '__origin__', None)
	if origin is not None:
		import typing
		if origin is typing.Union:
			args = [a for a in python_type.__args__ if a is not type(None)]
			inner = _python_to_gql_type(args[0]) if args else 'String'
			return inner.rstrip('!')  # nullable
	return type_map.get(name, 'String!')


def federated_type(key: str | list[str] = 'id', plugin: str = '') -> Callable:
	"""Class decorator: mark a class as a federated GraphQL type.

	Example::

		@federated_type(key='id', plugin='finance.ar')
		class ARInvoice:
			id: str
			total_amount_cents: int
			status: str
	"""
	keys = [key] if isinstance(key, str) else key

	def decorator(cls: type) -> type:
		cls._federation_key = keys
		cls._federation_plugin = plugin
		get_federation_registry().register(
			cls.__name__, cls, plugin=plugin, key_fields=keys,
			description=cls.__doc__ or '',
		)
		return cls
	return decorator


def key_field(name: str) -> str:
	"""Return a GraphQL @key field reference string."""
	return name


# Module singleton
_registry: FederationRegistry | None = None


def get_federation_registry() -> FederationRegistry:
	global _registry
	if _registry is None:
		_registry = FederationRegistry()
	return _registry


__all__ = [
	'FederationRegistry', 'FederatedTypeEntry', 'get_federation_registry',
	'federated_type', 'key_field',
]
