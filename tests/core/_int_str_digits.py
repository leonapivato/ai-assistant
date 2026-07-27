"""A context manager pinning ``sys``'s integer-string conversion limit.

Imported into each ``core.types`` test module that asserts an oversized integer
has no JSON encoding. It is a plain helper module rather than a ``conftest.py``
so it carries a unique module name: the suite has one ``conftest`` (``tests/``)
and mypy resolves test modules by basename, so a second ``conftest`` would
collide. A context manager rather than a fixture keeps the pin explicit at the
one assertion that needs it, with no fixture-name plumbing.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

#: The interpreter's default integer-string conversion limit (CPython 3.11+).
#: A literal with more digits than this has no ``str()`` and so no JSON
#: encoding; a literal with fewer always renders.
_DEFAULT_INT_STR_DIGITS = 4300


@contextmanager
def pinned_int_str_digits() -> Iterator[None]:
    """Pin ``sys``'s integer-string conversion limit to the default in this block.

    The oversized-integer refusal tests assert that a 5001-digit literal has no
    JSON encoding, which only holds while the limit is below 5001. The default
    is 4300, but ``PYTHONINTMAXSTRDIGITS=0`` (unlimited) — or any raise past
    5000 — makes the literal renderable, so the refusal never fires and the test
    fails though the validator is correct (#406). Pin the limit here so the
    assertion holds whatever the ambient setting is, and restore it afterwards.
    """
    original = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(_DEFAULT_INT_STR_DIGITS)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(original)
