"""``search_query_max_chars``: the one bound this lane configures (ADR-0231 §5).

ADR-0231 §5 adds four ``Settings`` fields, "each with the named default, stated
domain and load-time refusal ADR-0230 §6 requires of its own". This is the first —
the bound the **composer** enforces — and it lands with the composer, because a bound
nothing reads is a figure an operator can set and watch do nothing. The other three
are the searcher's and its transport's, and arrive with those lanes.

The generic domain guards ``tests/core/test_config.py`` runs over every discovered
integer setting already cover the ``bool``, the string and the out-of-range cases;
what is here is what those cannot say — the **named default** ADR-0231 states, and
that a deployment can actually set it.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings


def test_the_named_default_is_the_one_the_decision_names() -> None:
    """256 is ADR-0231 §5's figure; a drift here is a drift from the ADR."""
    assert Settings().search_query_max_chars == 256


@pytest.mark.parametrize("value", [0, -1])
def test_a_bound_outside_its_domain_does_not_load(value: Any) -> None:
    """Refused **at load**, before any composer is built and before any model call.

    Zero and negative are refused rather than given a meaning: a bound of zero refuses
    every composition while appearing configured, which is a mechanism turned off by
    a number rather than by an operator, and a negative one has no reading at all.
    """
    with pytest.raises(ValidationError):
        Settings(search_query_max_chars=value)


def test_the_bound_is_configurable_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Settings`` is the only route to configuration in this system.

    Reached the way a deployment actually sets it — "never touch ``os.environ``
    directly" — since a figure no operator could set would be a bound with nobody
    behind it.
    """
    monkeypatch.setenv("ASSISTANT_SEARCH_QUERY_MAX_CHARS", "64")

    assert Settings().search_query_max_chars == 64
