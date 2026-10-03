"""UUIDv7 helpers.

Historically imported from the third-party ``uuid_extensions`` package, which is
not a declared dependency. Every module now imports ``uuid7str`` from here so
time-sortable identifiers (audit rows, event ids) work everywhere. Uses the
``uuid6`` package when available and falls back to a stdlib implementation
otherwise.
"""

from __future__ import annotations

import os
import time

try:  # declared dependency
	from uuid6 import uuid7 as _uuid7
except ImportError:  # pragma: no cover - fallback
	import uuid as _uuid

	def _uuid7() -> _uuid.UUID:
		"""RFC 9562 layout: 48-bit millisecond timestamp, version 7, random."""
		ms = int(time.time() * 1000) & ((1 << 48) - 1)
		rand = os.urandom(10)
		raw = bytearray(16)
		raw[0:6] = ms.to_bytes(6, "big")
		raw[6] = (0x70 | (rand[0] & 0x0F))  # version 7
		raw[7] = rand[1]
		raw[8] = (0x80 | (rand[2] & 0x3F))  # variant 10x
		raw[9:16] = rand[3:10]
		return _uuid.UUID(bytes=bytes(raw))


def uuid7str() -> str:
	"""Time-sortable UUIDv7 as a string."""
	return str(_uuid7())


def uuid7() -> "object":
	"""Time-sortable UUIDv7 instance."""
	return _uuid7()


__all__ = ["uuid7", "uuid7str"]
