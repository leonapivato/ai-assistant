"""ai-assistant: a model-agnostic AI operating system.

An intelligent orchestration layer that understands the user, manages long-term
context, plans tasks, coordinates tools, and continuously learns from
interactions. The underlying language model is interchangeable; the value lies
in the personalization and orchestration surrounding it.
"""

from importlib.metadata import PackageNotFoundError, version

# Imported for its side effect: installing the ADR-0004 §5 log redaction
# processor. Importing anything from this package must be enough to get the
# safety net — a redaction step that only exists once the CLI has run would
# leave every test, script, and embedding application logging unredacted.
from ai_assistant.core import logging as _logging  # noqa: F401

try:
    __version__ = version("ai-assistant")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
