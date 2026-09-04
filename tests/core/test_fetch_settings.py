"""The ``Settings`` fields ADR-0230, ADR-0232 and ADR-0234 add, and where each refuses.

Item 21 asks for "one arm per field — a zero and a negative ``fetch_listing_ttl``,
``fetch_listing_max_entries``, ``fetch_max_file_bytes`` and
``fetch_max_content_bytes`` — each refused when ``Settings`` is constructed, **before
any fetcher is built and before any filesystem call**, and each a configuration error
that stops the deployment rather than an empty listing, a ``FetchRefusal`` or a
degraded turn. This is the arm that fails on any implementation carrying an unchecked
bound through to a slice."

ADR-0232 §8 arm 15 is that item "extended by one field and asserted in its form": a zero
and a negative ``fetch_max_decoded_bytes``, refused at load for the same reason and in
the same place. Its **named default** is pinned here too, because §2 argues 1 MiB rather
than picking it — thirty-two times ``fetch_max_content_bytes`` on the legitimacy side,
and 1 MB of operators at about 6 s against 313 s at 16 MB on the cost side.

ADR-0234 §7 arm 14 extends it once more, by ``fetch_max_character_mappings`` — a figure
on a quantity that is not bytes at all, the ``/ToUnicode`` mappings an extraction
**builds**. Its named default is pinned for §5's reason: 400,000 is a **matching**
rather than a derivation, sized so that its worst case — about 1.30 s of dictionary
build at the dearest form ``pypdf`` will build a mapping from — is the worst case of the
megabyte of operators ``fetch_max_decoded_bytes``'s own default admits, "so an operator
who has accepted one has accepted the other". §2 forbids computing either from the
other, which is exactly why both are pinned by value here.

The root's own field is deliberately not in that class: its named default is unset,
and unset means the mechanism is off (§6's first clause). What it *does* owe is the
shape rule every configured local source in this tree owes — absolute, and **not**
canonicalised, because ``realpath`` would resolve the symbolic links §6 requires the
descent to refuse.

The generic domain guards ``tests/core/test_config.py`` runs over every discovered
integer and duration setting already cover the ``bool``, the string and the
out-of-range cases for these fields; what is here is what those cannot say — the
**named defaults** ADR-0230 states, and the root's own two clauses.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings


def test_the_mechanism_is_off_until_a_root_is_configured() -> None:
    """§6's first clause, which is what makes the standing cost zero.

    "A deployment with no root pays no listing read, renders no listing block, and
    cannot service the kind. That is also why §9's fire rate for this kind reads 0% in
    such a deployment, and why §9 says that is a true statement about the configuration
    rather than a reading of a trigger."
    """
    assert Settings().fetch_root_path is None


def test_the_named_defaults_are_the_ones_the_decision_names() -> None:
    """ADR-0230 §4 and §6 name four figures, ADR-0232 a fifth and ADR-0234 a sixth; a
    drift here is a drift from the ADR.

    Pinned by value because each number is argued rather than chosen: five minutes is
    §4's expiry, forty is §6's entry cap, 4 MiB bounds the **read** — and nothing else,
    ADR-0232 §1 having taken the second limb of that clause away — 32 KiB is "what
    reaches the prompt — roughly 32,000 characters of English, about 5,400 CJK code
    points or about 2,700 emoji", 1 MiB is what an extraction may **parse**, and 400,000
    is what it may **build** — a fourth quantity with a fourth consumer, the
    mapping-dictionary build, which no byte figure bounds: 65,000 mappings arrive in
    927,031 bytes of ``bfchar`` or in 178 of ``bfrange``.
    """
    settings = Settings()

    assert settings.fetch_listing_ttl == timedelta(minutes=5)
    assert settings.fetch_listing_max_entries == 40
    assert settings.fetch_max_file_bytes == 4 * 1024 * 1024
    assert settings.fetch_max_content_bytes == 32 * 1024
    assert settings.fetch_max_decoded_bytes == 1024 * 1024
    assert settings.fetch_max_character_mappings == 400_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fetch_listing_ttl", timedelta(0)),
        ("fetch_listing_ttl", timedelta(seconds=-1)),
        ("fetch_listing_max_entries", 0),
        ("fetch_listing_max_entries", -1),
        ("fetch_max_file_bytes", 0),
        ("fetch_max_file_bytes", -1),
        ("fetch_max_content_bytes", 0),
        ("fetch_max_content_bytes", -1),
        ("fetch_max_decoded_bytes", 0),
        ("fetch_max_decoded_bytes", -1),
        ("fetch_max_character_mappings", 0),
        ("fetch_max_character_mappings", -1),
    ],
)
def test_a_bound_outside_its_domain_does_not_load(field: str, value: Any) -> None:
    """§14 item 21: refused **at load**, before any fetcher and any filesystem call.

    Zero and negative are refused rather than given a meaning. "A zero entry cap is a
    mechanism that shows nothing while appearing configured, which §3 rules a listing
    may not be made to mean; and a negative one is worse than meaningless — *capped at
    -1* has no reading, while the obvious Python spelling of a cap, ``entries[:-1]``,
    quietly yields all but the last entry, so a bound would be defeated by a
    configuration value rather than enforced by one."
    """
    configured: dict[str, Any] = {field: value}

    with pytest.raises(ValidationError):
        Settings(**configured)


def test_a_relative_root_does_not_load() -> None:
    """Absoluteness is a property of the *configuration* (ADR-0093 §7's split).

    "A relative value resolves against each process's working directory, so the hub
    started at boot and a test run from a project directory would read the same setting
    and open different" directories.
    """
    with pytest.raises(ValidationError, match="absolute"):
        Settings(fetch_root_path=Path("documents"))


def test_a_root_beginning_with_a_tilde_is_expanded_and_not_canonicalised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~`` is expanded; symbolic links are **not** resolved, and that is the point.

    ``realpath`` resolves symbolic links, which is a *filesystem* question — and
    ADR-0230 §6 requires that a symbolic link at **any** component of the configured
    path refuse the construction rather than be followed. Resolving it here would
    silently answer the very question the constructor exists to refuse, which is a
    stronger reason than ``calendar_reader_path``'s and is why this arm exists beside
    that one.
    """
    real = tmp_path / "real"
    real.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (home / "documents").symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))

    settings = Settings(fetch_root_path=Path("~/documents"))

    assert settings.fetch_root_path == home / "documents"
    assert settings.fetch_root_path != real


def test_a_root_is_configurable_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The field is reachable the way a deployment actually sets it.

    ``Settings`` is the only route to configuration in this system — "never touch
    ``os.environ`` directly" — so a field nothing could set from outside would be a
    mechanism with no way to turn it on.
    """
    monkeypatch.setenv("ASSISTANT_FETCH_ROOT_PATH", str(tmp_path))

    assert Settings().fetch_root_path == tmp_path
