"""The ``pinned_int_str_digits`` helper pins, then restores, the ambient limit.

The helper is test-only infrastructure, but a regression in its restore leg
would leak a changed ``sys`` integer-string conversion limit into every later
test in the session — a silent, cross-test contamination that no assertion in
the refusal tests it supports would catch (they only need the limit *low*, not
restored). These tests are that guard.
"""

from __future__ import annotations

import sys

import pytest
from _int_str_digits import pinned_int_str_digits


@pytest.mark.parametrize(
    "ambient", [0, 640, 4300, 6000], ids=["unlimited", "floor", "default", "raised"]
)
def test_the_pin_forces_a_low_limit_then_restores_the_ambient_one(ambient: int) -> None:
    """Inside the block a 5001-digit int is unrenderable whatever the ambient
    setting; after it, the ambient setting — including ``0`` (unlimited) and a
    value above 5000 — is back exactly.
    """
    original = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(ambient)
    try:
        with pinned_int_str_digits(), pytest.raises(ValueError, match="conversion"):
            str(10**5000)
        assert sys.get_int_max_str_digits() == ambient
    finally:
        sys.set_int_max_str_digits(original)


def test_the_pin_restores_the_ambient_limit_even_when_the_body_raises() -> None:
    """The restore rides on ``finally``, so an assertion failure inside cannot
    leave a raised or disabled limit behind.
    """
    original = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        with pytest.raises(RuntimeError), pinned_int_str_digits():
            raise RuntimeError("boom")
        assert sys.get_int_max_str_digits() == 0
    finally:
        sys.set_int_max_str_digits(original)
