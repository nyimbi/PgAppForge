"""Optional test-generation helpers.

Every dependency here is optional (numpy for data generation, pytest for the
runner). Importing this package must never fail, because plugin modules import
the generators at import time. Each name is therefore bound only when its
module actually loaded; use ``hasattr(pgappforge.testing_framework, name)`` or
the ``available_*`` helpers to test for it.
"""

import logging

log = logging.getLogger(__name__)

__all__ = [
    "TestGenerator", "TestGenerationConfig", "TestRunner", "TestReporter",
    "RealisticDataGenerator", "ScenarioGenerator", "available", "load_all",
]


def _try(module_name: str, *names: str) -> None:
    import importlib

    try:
        module = importlib.import_module(f"{__name__}.{module_name}")
    except Exception as exc:  # optional dependency missing or broken module
        log.warning("pgappforge.testing_framework.%s unavailable: %s", module_name, exc)
        return
    for name in names:
        value = getattr(module, name, None)
        if value is not None:
            globals()[name] = value


_try("core.test_generator", "TestGenerator")
_try("core.config", "TestGenerationConfig")
_try("runner.test_runner", "TestRunner")
_try("runner.test_reporter", "TestReporter")
_try("data.realistic_data_generator", "RealisticDataGenerator")
_try("generators.scenario_generator", "ScenarioGenerator")


def available(name: str) -> bool:
    """True when an optional helper was loaded successfully."""
    return name in globals() and globals()[name] is not None


def load_all() -> dict:
    """What loaded and what did not; use for a startup log or a health check."""
    return {name: name in globals() for name in __all__ if name != "available" and name != "load_all"}
