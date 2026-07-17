"""ai-assistant: a model-agnostic AI operating system.

An intelligent orchestration layer that understands the user, manages long-term
context, plans tasks, coordinates tools, and continuously learns from
interactions. The underlying language model is interchangeable; the value lies
in the personalization and orchestration surrounding it.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ai-assistant")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
