"""The calendar reader's operator recipe, held to the identifiers it names (#1022).

:mod:`ai_assistant.readers.calendar`'s module docstring is the deployment recipe for
this reader: the ``vdirsyncer`` pairing, the settings that configure the source and arm
its producer, and the three independent acts that arm unprompted contact. Nothing
asserted it, and a docstring is exactly where a rename lands without a failure — the
identifier moves, the prose keeps naming the old one, and every check this project runs
still passes.

**It is not a hypothetical.** A false claim about a duration parser shipped green in
this very docstring — it said the settings took ISO-8601 durations only, and
``00:05:00`` is accepted too — and only a review round caught it.

What is pinned here is the **mechanically checkable half**: every setting, reader
identity, notification class, grant scope and reach the recipe spells is one the code
actually defines, and the settings its arming steps turn on are still named. The
prose's *truth* — that a step does what it says — is not reachable this way and is
not attempted; ADR-0093 §7's own tests carry that. The pin is deliberately written
against the identifiers rather than against sentences, because #887 may yet move
these recipes into a docs tree and the identifiers are the half that survives intact.
"""

from __future__ import annotations

import re
from typing import Final

import pytest

from ai_assistant.core.config import Settings
from ai_assistant.core.types import NotificationReach
from ai_assistant.orchestration.upcoming import NOTIFICATION_CLASS
from ai_assistant.readers import calendar
from ai_assistant.readers.calendar import CALENDAR_READER_NAME
from ai_assistant.wire import GRANTABLE_SCOPES

#: The recipe under test. A module with no docstring is the one failure this file
#: cannot report as a missing identifier, so it is asserted before anything reads it.
RECIPE: Final = calendar.__doc__ or ""

#: The environment prefix every setting on this deployment is read under.
PREFIX: Final = str(Settings.model_config["env_prefix"])

#: The settings whose absence would leave the recipe unable to arm what it describes:
#: the file to read, the producer's cadence, its lead, and the window the lead is
#: bounded by. Named as *fields*, so a rename fails here
#: rather than being renamed in one place and left standing in the prose.
ARMED: Final = (
    "calendar_reader_path",
    "calendar_upcoming_interval",
    "calendar_upcoming_lead",
    "calendar_window_future",
)


def test_the_reader_carries_a_recipe_at_all() -> None:
    """The precondition every other case here reads through.

    A module whose docstring was emptied would pass every "names only real
    identifiers" check below vacuously, which is the one way this file could report
    a green for a recipe that had stopped existing.
    """
    assert "vdirsyncer" in RECIPE
    assert "Deploying it" in RECIPE


def test_every_setting_the_recipe_names_is_one_the_configuration_defines() -> None:
    """A renamed field must not leave an operator typing a variable nothing reads.

    An unknown ``ASSISTANT_*`` variable is not refused at load — it is simply not
    read — so a recipe naming a stale one arms nothing and reports nothing, which is
    the failure mode this direction of the check exists for.
    """
    named = sorted(set(re.findall(rf"{PREFIX}[A-Z0-9_]+", RECIPE)))
    fields = {f"{PREFIX}{field.upper()}" for field in Settings.model_fields}

    assert named, "the recipe names settings; a version that named none has lost them"
    assert set(named) <= fields, (
        f"named by the recipe and not defined: {sorted(set(named) - fields)}"
    )


@pytest.mark.parametrize("field", ARMED)
def test_the_recipe_still_names_each_setting_its_arming_steps_turn_on(field: str) -> None:
    """The other direction: a setting the recipe stopped naming is a step nobody can take.

    The producer's cadence has to be named where the operator is reading, and the
    lead and the window are the pair whose coherence rule is refused at load
    (ADR-0132 §4).
    """
    assert Settings.model_fields[field] is not None, "the roster here is over real fields"
    assert f"{PREFIX}{field.upper()}" in RECIPE


def test_the_recipe_names_the_reader_and_the_class_by_their_real_identifiers() -> None:
    """The two identifiers the recipe's acts are performed against.

    A grant keys on the reader's declared identity and never on the path (ADR-0097
    §1), and a reach is set against the producer's notification class — so both
    ``assistant grant <source>`` and ``assistant tune --class <class>`` in the recipe
    are only correct while these two words match the constants.
    """
    assert f"assistant grant {CALENDAR_READER_NAME}" in RECIPE
    assert f"assistant tune --class {NOTIFICATION_CLASS}" in RECIPE


def test_every_scope_the_recipe_offers_is_one_a_new_grant_may_name() -> None:
    """ADR-0133 §6's obligation applied to the recipe that tells an operator what to type.

    Every ``--scope`` the recipe spells has to be a use a new grant may name — a
    member of :data:`~ai_assistant.wire.GRANTABLE_SCOPES`, which since ADR-0294 §4 is
    ``GrantScope`` less ``INGEST``: a stale one is a command that fails at the door,
    and the two the recipe walks through — ``facet`` and the ``notify`` it does not
    back-fill — are the whole of what arming unprompted contact needs.
    """
    offered = set(re.findall(r"--scope (\w+)", RECIPE))
    admitted = {scope.value for scope in GRANTABLE_SCOPES}

    assert offered, "the recipe walks an operator through granting; it names scopes"
    assert offered <= admitted, f"offered and not admitted: {sorted(offered - admitted)}"


def test_every_reach_the_recipe_offers_is_a_member_of_the_type() -> None:
    """The same, for the setting that decides whether a held record ever interrupts.

    Every class ships at ``hold`` (ADR-0130 §6), so the recipe's last step is the
    raise — and a ``--reach`` naming a value the enum does not carry is a step that
    cannot be performed at all.
    """
    offered = set(re.findall(r"--reach (\w+)", RECIPE))
    admitted = {reach.value for reach in NotificationReach}

    assert offered, "the recipe's third arming act is a reach raise; it names one"
    assert offered <= admitted, f"offered and not admitted: {sorted(offered - admitted)}"
