"""
Python types mapping Apache AGE graph primitives.

AGE stores vertices and edges as PostgreSQL agtype (a JSON superset).
These dataclasses provide a clean Python interface to AGE results.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Vertex:
	"""An AGE graph vertex (node)."""
	id: int
	label: str
	properties: dict[str, Any] = field(default_factory=dict)

	@classmethod
	def from_agtype(cls, raw: dict) -> "Vertex":
		return cls(
			id=raw.get("id", 0),
			label=raw.get("label", ""),
			properties=raw.get("properties", {}),
		)

	def __getitem__(self, key: str) -> Any:
		return self.properties[key]

	def get(self, key: str, default=None) -> Any:
		return self.properties.get(key, default)


@dataclass
class Edge:
	"""An AGE graph edge (relationship)."""
	id: int
	label: str
	start_id: int
	end_id: int
	properties: dict[str, Any] = field(default_factory=dict)

	@classmethod
	def from_agtype(cls, raw: dict) -> "Edge":
		return cls(
			id=raw.get("id", 0),
			label=raw.get("label", ""),
			start_id=raw.get("start_id", 0),
			end_id=raw.get("end_id", 0),
			properties=raw.get("properties", {}),
		)

	def __getitem__(self, key: str) -> Any:
		return self.properties[key]


@dataclass
class Path:
	"""An AGE path — alternating vertices and edges."""
	vertices: list[Vertex] = field(default_factory=list)
	edges: list[Edge] = field(default_factory=list)

	@property
	def length(self) -> int:
		return len(self.edges)

	@property
	def start(self) -> Vertex | None:
		return self.vertices[0] if self.vertices else None

	@property
	def end(self) -> Vertex | None:
		return self.vertices[-1] if self.vertices else None
