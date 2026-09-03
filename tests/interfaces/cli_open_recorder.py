"""One observation of the CLI's client seam, shared by the modules that need it.

Four modules under ``tests/interfaces/`` hold refusals that claim — by name, by
docstring, or both — that they land **before any client is built**: ADR-0085 §3c's
"before any I/O", which is what #728 is about. Neither of the two absences those
modules had to hand actually says it:

* **Exit 2** is equally what a command that opened a client, probed the hub, and
  refused afterwards returns. Typer's usage-error code is a property of *how* the
  command failed, not of *when*.
* **An engine with no call recorded** is the same absence one layer in. A command
  that opened a client and then refused leaves ``engine.calls == []`` behind
  exactly as a parse-time callback does, so the three sibling modules that checked
  it were checking the weaker of the two properties while claiming the stronger
  one (#1973).

The seam that does say it is
:func:`~ai_assistant.interfaces.cli._open_engine`. After ADR-0084 §6 the CLI has
no composition root to reach: it obtains a *client*, and that function is the one
place one is obtained — so a recorded open is the event "the command started doing
I/O", and an empty record is the refusal preceding it.

**What is hoisted here is the observation, not the wiring.** Each module wires
that seam its own way and has to: ``test_cli.py`` pins a clock,
``test_cli_connections.py`` substitutes the credential reader, and a module that
grew a fifth substitution tomorrow would want it in its own ``_wire`` rather than
here. :func:`wire_recording_opens` therefore takes the caller's own ``_wire`` and
layers the recorder over whatever it installed.

**Taking the wiring as an argument is the point of that signature**, not a
convenience. Every module's ``_wire`` ends by patching ``_open_engine``, so a
recorder installed *before* one would be silently overwritten — and a test whose
recorder was overwritten passes, with an empty list, through exactly the
regression the case exists to catch. Ordering the two correctly is the helper's
job here rather than each caller's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.interfaces import cli

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def wire_recording_opens(
    wire: Callable[[pytest.MonkeyPatch, object], None],
    monkeypatch: pytest.MonkeyPatch,
    engine: object,
) -> list[None]:
    """Wire ``engine`` through ``wire``, then record every open of a client.

    **Recording rather than raising, deliberately.** A stub that raised would fail
    the invocation for a second reason, and could not tell "the refusal came first"
    from "the refusal came second and the failure masked it". The returned list is
    empty exactly when no client was opened, whatever else the command did — which
    is the property a refusal's ordering claim needs and the only one it needs.

    **The absence is only evidence if the recorder would have seen the thing.** A
    module whose ``_wire`` patched some other name, or whose commands reached a
    client by some other route, would hand every refusal case an empty list for a
    reason unrelated to when the refusal happened. So each calling module pins one
    *accepted* invocation against this helper, and requires that it record exactly
    one open.

    Args:
        wire: The calling module's own wiring — run first, so that the recorder
            installed after it cannot be overwritten by it.
        monkeypatch: The patcher whose lifetime both substitutions follow.
        engine: The engine a client, if one were opened, would be. It is passed to
            ``wire`` as well, so an accepted invocation reaches the same object a
            wired one would.

    Returns:
        One entry per :func:`~ai_assistant.interfaces.cli._open_engine` awaited, in
        order.
    """
    wire(monkeypatch, engine)
    opened: list[None] = []

    async def _open() -> object:
        opened.append(None)
        return engine

    monkeypatch.setattr(cli, "_open_engine", _open)
    return opened
