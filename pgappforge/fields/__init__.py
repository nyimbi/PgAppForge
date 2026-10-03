"""WTForms field extensions for PgAppForge.

Historically these lived in ``pgappforge/fields.py``, which the
``pgappforge/fields/`` package shadowed (a directory wins over a module of the
same name), making the classes unreachable by ``from pgappforge.fields import
...``. Every field module now lives in this package and each is imported
defensively so one optional dependency cannot hide the core fields.
"""

import logging

log = logging.getLogger(__name__)

_loaded: list[str] = []

try:
    from .core_fields import *  # noqa: F401,F403
    _loaded.append("core_fields")
except Exception as exc:  # pragma: no cover - defensive
    log.warning("pgappforge.fields.core_fields unavailable: %s", exc)

for _name in ("extended_fields", "advanced_fields", "media_fields", "map_field"):
    try:
        _module = __import__(f"{__name__}.{_name}", globals(), locals(), ["*"])
        for _attr in getattr(_module, "__all__", dir(_module)):
            if not _attr.startswith("_"):
                globals()[_attr] = getattr(_module, _attr)
        _loaded.append(_name)
    except Exception as exc:
        log.warning("pgappforge.fields.%s unavailable: %s", _name, exc)

__all__ = sorted({k for k in globals() if not k.startswith("_") and k not in {"logging", "log", "annotations"}} | set(_loaded))
