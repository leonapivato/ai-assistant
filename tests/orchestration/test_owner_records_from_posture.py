"""``owner_records`` at the five passes is the pass's posture's (ADR-0383 §10:3, §10:4).

Milestone 22's B11c, #3709's line: "no pass tells a store to give back the owner's records
without asking whose sight bounds the read". ``owner_records`` answers only whether the
pass's audience may be shown what is placed for the owner alone (ADR-0307 §6:4), and at
each of the five passes that set it to ``True`` it is made from the pass's posture by
:func:`~ai_assistant.orchestration.disclosure.admits_owner_placed`: the hub chat's turn,
the line's, an informational event's, a task's occurrence and an approval's outcome. Whose
records a pass reads is its sight's alone, which no flag here reaches (§10:2).

The one literal ``True`` left is not a pass's: the owner's own summary view
(``stories.py``'s ``_OWNER``), which the owner reads by their own act (ADR-0303 §3:9,
ADR-0304 §4:1) through a store bound to the owner's sight.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from test_phases_yes_path import _Hub
from test_planning import _recorded_trigger

from ai_assistant.orchestration.approvals import AskedFrom
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    UnboundedAudienceSupply,
    admits_owner_placed,
)
from ai_assistant.testing.parties import ASSISTANTS_WORDS

_PACKAGE: Final = Path(__file__).parents[2] / "src" / "ai_assistant" / "orchestration"

#: The five passes' working sets, each begun by one member of the phases.
_BEGINNINGS: Final = frozenset(
    {"begin", "begin_line", "begin_event", "begin_task", "begin_approval"}
)

#: Where a literal ``True`` stands: the owner's own view, which is no pass (module doc).
_THE_OWNERS_VIEW: Final = ("stories.py", "SummaryVisibility")


def _keywords() -> list[tuple[str, str, ast.expr]]:
    """Every ``owner_records=`` given to a call under ``orchestration/``: the file, the
    callee's name, and the value."""
    found: list[tuple[str, str, ast.expr]] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            found.extend(
                (path.relative_to(_PACKAGE).as_posix(), name, one.value)
                for one in node.keywords
                if one.arg == "owner_records"
            )
    return found


def _literal_true(value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and value.value is True


def test_no_pass_sets_owner_records_by_a_literal() -> None:
    """§10:3: no literal ``True`` is handed to any call under ``orchestration/``, save the
    owner's own view, which is no pass."""
    literals = [(where, name) for where, name, value in _keywords() if _literal_true(value)]
    assert literals == [_THE_OWNERS_VIEW]


def test_each_of_the_five_passes_makes_it_from_its_posture() -> None:
    """§10:3: each of the five passes is begun with ``admits_owner_placed`` of the posture
    the pass is given, the one posture the engine builds for it."""
    made = [
        (name, ast.unparse(value))
        for where, name, value in _keywords()
        if where == "engine.py" and name in _BEGINNINGS
    ]
    assert sorted(made) == sorted((name, "admits_owner_placed(supply)") for name in _BEGINNINGS)


def test_a_posture_of_unbounded_audience_would_show_nothing_placed_for_the_owner() -> None:
    """The flag is the posture's: bounded admits what is placed for the owner alone,
    unbounded does not. Every pass's posture is bounded today, so nothing a pass is shown
    changes (§10's note)."""
    assert admits_owner_placed(BoundedAudienceSupply(speakable_attested_sources=frozenset()))
    assert not admits_owner_placed(UnboundedAudienceSupply(speakable_attested_sources=frozenset()))


def test_a_task_and_an_approval_carry_the_flag_they_are_handed() -> None:
    """The two passes whose flag was set inside the phases now take it from the engine,
    which makes it from the pass's posture."""
    hub = _Hub()
    path = hub.phases(hub.harness)
    trigger = _recorded_trigger(ASSISTANTS_WORDS)
    for flag in (True, False):
        task = path.begin_task(activation_id="a-1", trigger=trigger, lineage=(), owner_records=flag)
        approval = path.begin_approval(
            activation_id="a-2",
            trigger=trigger,
            context=(),
            asked_from=AskedFrom(),
            owner_records=flag,
        )
        assert (task.owner_records, approval.owner_records) == (flag, flag)
