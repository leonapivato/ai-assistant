"""The CLI connection surface: ADR-0151 §16's client lane, clause by clause.

Four obligations on this surface are the **client's** and are unenforceable from
the hub's side (ADR-0098 §5), so ADR-0151 §16 puts them here and they can live
nowhere else: §5's display of the identity as part of the act, §4's rendering of a
``PENDING`` record, §7's report of each partial outcome as the half that landed,
and §8's two clauses about what a disconnection may be said to have done. Every
one of them is a sentence a person reads, and none of them is observable on the
wire.

Every case is deterministic rather than a timing test, which is worth saying
because "lose the answer" and "cancel mid-act" both read like flakes: the scripted
engine below *records* the call and then raises, which is the stub-hub shape one
layer in. What is under test throughout is the client's report, not the socket.
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import (
    ConnectionStoreError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    OversizedValueError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
)
from ai_assistant.core.types import SECRET_VALUE_MAX_BYTES, ProvisioningState
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine, FakeConnectionProvisioner
from ai_assistant.wire import ProtocolError, TransportError

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import SecretStr

    from ai_assistant.core.types import ConnectedAccount


# --- the subject -------------------------------------------------------------


class _ScriptedConnectionEngine(FakeAssistantEngine):
    """A hub whose connection acts can be made to fail in each way §7 names.

    The canonical fake reaches the outcomes a *store* and a *keyring* can produce
    on their own — an unknown reference, an interrupted credential write, a failed
    deletion pass. The three it cannot reach without a real race are scripted here:
    a store that fails before the first write returns, an activation that commits
    and then fails, and a displacing act. ``FakeAssistantEngine`` is otherwise
    untouched, so what the client is handed is the contract's own shape.

    It also records each supplied credential's plaintext, which is the only way to
    assert that ``--credential-stdin`` altered nothing: the canonical fake
    deliberately records a call's identity and never its credential.
    """

    def __init__(self) -> None:
        """Create the engine with nothing scripted."""
        super().__init__()
        #: Raised instead of answering ``connect_account``.
        self.connect_raises: BaseException | None = None
        #: Raised instead of answering ``reprovision_account``.
        self.reprovision_raises: BaseException | None = None
        #: Raised instead of answering ``disconnect_account``.
        self.disconnect_raises: BaseException | None = None
        #: Raised instead of answering ``connected_accounts``, so the client's
        #: "I could not read the state" branch is reachable.
        self.connected_raises: BaseException | None = None
        #: Every credential plaintext this engine was handed, in order.
        self.credentials: list[str] = []

    async def connect_account(self, *, identity: str, credential: SecretStr) -> ConnectedAccount:
        """Connect, or raise what was scripted having recorded the call."""
        self.credentials.append(credential.get_secret_value())
        if self.connect_raises is not None:
            self.calls.append(("connect_account", {"identity": identity}))
            raise self.connect_raises
        return await super().connect_account(identity=identity, credential=credential)

    async def reprovision_account(
        self, reference: str, *, identity: str, credential: SecretStr
    ) -> ConnectedAccount:
        """Re-provision, or raise what was scripted having recorded the call."""
        self.credentials.append(credential.get_secret_value())
        if self.reprovision_raises is not None:
            self.calls.append(("reprovision_account", {"reference": reference}))
            raise self.reprovision_raises
        return await super().reprovision_account(
            reference, identity=identity, credential=credential
        )

    async def disconnect_account(self, reference: str) -> ConnectedAccount | None:
        """Disconnect, or raise what was scripted having recorded the call."""
        if self.disconnect_raises is not None:
            self.calls.append(("disconnect_account", {"reference": reference}))
            raise self.disconnect_raises
        return await super().disconnect_account(reference)

    async def connected_accounts(self) -> tuple[ConnectedAccount, ...]:
        """Answer, or raise what was scripted having recorded the call."""
        if self.connected_raises is not None:
            self.calls.append(("connected_accounts", {}))
            raise self.connected_raises
        return await super().connected_accounts()


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it."""
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=100))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object, *, credential: str = "hunter2") -> None:
    """Point the connection commands' startup at ``engine`` and script the prompt.

    The seam is :func:`~ai_assistant.interfaces.cli._open_engine`, as it is for
    every other command: the CLI obtains a *client*, and the one function that
    obtains it is the one place a test substitutes (ADR-0084 §6).

    The credential reader is substituted rather than driven through the runner's
    stdin, because most cases below are about *when* it is called relative to the
    rendering, which is only observable from inside it.
    """

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)
    monkeypatch.setattr(cli, "_prompt_for_credential", lambda: credential)


def _watching(
    output: StringIO, engine: FakeAssistantEngine, seen: list[tuple[str, list[str]]]
) -> Callable[[], str]:
    """A credential reader that records what was on screen and what had been called.

    The vantage point ADR-0151 §5's ordering is only observable from: "before the
    credential is asked for" is a statement about the moment this runs.
    """

    def _read() -> str:
        seen.append((output.getvalue(), [call[0] for call in engine.calls]))
        return "hunter2"

    return _read


def _flat(rendered: str) -> str:
    """The rendering with its line wrapping removed.

    Rich wraps at the console's width, so a sentence a normative clause obliges can
    arrive split across two lines. Collapsing runs of whitespace lets a case assert
    the *sentence* rather than the width it happened to be rendered at, which is the
    thing under test — none of the clauses below says anything about a line break.
    """
    return " ".join(rendered.split())


def _pasted(rendered: str, command: str, closer: str = "'.") -> list[str]:
    """The argv a printed command hint produces when it is pasted (#984)."""
    start = rendered.index(command)
    end = rendered.index(closer, start + len(command))
    return shlex.split(rendered[start:end])


# --- §5: the identity is displayed as part of the act ------------------------


def test_connect_shows_the_identity_before_it_asks_for_the_credential(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §5: "No surface accepts an identity it does not display".

    Two things are asserted at once and the ordering is the point. The identity is
    on screen when the credential is asked for, because ADR-0149 §4's third answer
    to a credential pasted into the name field is that the value is *seen* — and a
    client that rendered it afterwards would show it once the secret had already
    been typed into the field beside it. And **nothing has been sent** at that
    moment, so a person who sees the wrong name has not yet handed over anything.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    seen: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(cli, "_prompt_for_credential", _watching(output, engine, seen))

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 0
    assert len(seen) == 1
    at_prompt, calls_so_far = seen[0]
    assert "me@example.com" in at_prompt
    assert calls_so_far == []


def test_reconnect_shows_the_identity_before_it_asks_for_the_credential(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5 binds every operation that accepts an identity, not only the first.

    An author reasons that the account was already shown when it was connected and
    skips the disclosure on the replacement — which is exactly where a rotated
    credential gets pasted into the name field of the wrong connection.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    reference = engine.connections.entries[-1].reference
    seen: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(cli, "_prompt_for_credential", _watching(output, engine, seen))
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["reconnect", reference, "--identity", "me@example.com"])
    assert result.exit_code == 0
    assert len(seen) == 1
    at_prompt, _ = seen[0]
    assert "me@example.com" in at_prompt
    assert reference in at_prompt


def test_the_identity_reaches_the_hub_byte_for_byte(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §5: no implementation normalises a caller-supplied identity.

    "Not at the surface" is the clause's own wording, and a Typer callback that
    returned ``value.strip()`` would be the surface doing it one layer before the
    annotation ADR-0151 §2 chose ``NonBlankEncodableText`` over ``Identifier`` to
    prevent. Surrounding whitespace is the case an author's ``.strip()`` eats, and
    it is admissible: two accounts differing only by case or by a leading space are
    two accounts.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "  Me@Example.COM  "])
    assert result.exit_code == 0
    assert [call for call in engine.calls if call[0] == "connect_account"] == [
        ("connect_account", {"identity": "  Me@Example.COM  "})
    ]


# --- §4: a PENDING record is never a working connection ----------------------


def _with_a_pending_record(engine: _ScriptedConnectionEngine) -> str:
    """Leave one reference with a live record that is ``PENDING``.

    ADR-0148 §6's own route to it, rather than a hand-built value: the credential
    write fails, so the act's first write has landed and its activation never does.
    Nothing repairs the state, which is the property the clause is about.
    """
    engine.connections.secrets.become_unavailable()
    return "interrupted@example.com"


def test_connections_renders_a_pending_record_as_not_connectable(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §4's client clause, and #1130's stated fix direction.

    A surface rendering a ``PENDING`` record says the reference is **not
    connectable** and that the remedy is to run the act again, and **never** that
    the connection is being established, is in progress, or will complete on its
    own. The negatives are what the clause exists for: nothing is running, the act
    that wrote the record is gone, and a spinner would be a lie about a state
    ADR-0148 §6 rules "refused rather than reconciled".
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    identity = _with_a_pending_record(engine)
    CliRunner().invoke(cli.app, ["connect", identity])
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "not connectable" in rendered
    assert "Nothing is in progress and nothing will finish it" in rendered
    assert "assistant reconnect" in rendered
    assert "being established" not in rendered
    assert "will complete on its own" not in rendered


def test_connections_lists_a_pending_reference_beside_an_active_one(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending reference is neither omitted nor presented as connected (§4).

    The listing that showed only active records would answer "what is connected"
    correctly and leave a user whose hub was killed mid-act with a reference that
    exists, is refused at every call, and appears nowhere they can see. Both rows
    are here and the two states are told apart, which is the whole of #1130's fix
    direction applied to the client that holds the clause.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "live@example.com"])
    engine.connections.secrets.become_unavailable()
    CliRunner().invoke(cli.app, ["connect", "interrupted@example.com"])
    engine.connections.secrets.become_available()
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "live@example.com" in rendered
    assert "interrupted@example.com" in rendered
    assert "connected" in rendered
    assert "not connectable" in rendered


# --- §7: every partial outcome is reported as the half that landed -----------


def test_connect_reports_an_incomplete_act_as_having_written_a_record(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §7: "No client reports the call as having changed nothing".

    An ``IncompleteProvisioningError`` asserts exactly two things — the reference it
    carries **exists**, because this act's own first write landed into an
    append-only store, and this act did not complete, so nothing it wrote is or ever
    becomes the live credential. After ``connect_account`` that reference is the
    only handle the user will ever have, because ADR-0151 §3 minted it inside the
    act and no result came back.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = IncompleteProvisioningError(
        "the credential could not be written", "conn-7"
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "did not complete" in rendered
    assert "conn-7" in rendered
    assert "exists" in rendered
    assert "did not leave things as they were" in rendered
    assert "nothing was written" not in rendered


def test_connect_resolves_a_partial_outcome_by_reading_what_is_connected(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7's resolution is a **read**, and never a second write.

    "Resolves it by reading ``connected_accounts``" is the clause, and the reason
    matters more here than on the grant surface it is transposed from: the second
    write a hopeful client would send carries a credential. So the assertion is on
    the call sequence — one provisioning act, then one read, and no second act.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = IncompleteProvisioningError("interrupted", "conn-7")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    assert [call[0] for call in engine.calls] == ["connect_account", "connected_accounts"]


def test_connect_reports_an_unknown_outcome_and_refuses_to_re_run_the_act(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: a ``ProvisioningOutcomeUnknownError`` asserts the reference exists and nothing else.

    The activation may have committed and failed before saying so, so neither
    completion nor incompletion may be asserted. The instruction not to re-run is
    the load-bearing half: running the act again on the assumption it failed would
    rotate a credential that may already be live.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = ProvisioningOutcomeUnknownError("the activation failed", "conn-9")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "not known" in rendered
    assert "conn-9" in rendered
    assert "Do not run it again" in rendered
    assert [call[0] for call in engine.calls] == ["connect_account", "connected_accounts"]


def test_reconnect_reports_a_displacement_as_not_rolled_back(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: a displacement is **not** the store having been left unchanged.

    ADR-0148 §6's "never held it and writes nothing" is scoped by its own words to
    an act whose *taking* compare-and-swap fails; the other two displacement points
    take an act that has already appended its pending entry and may already have
    written its credential. An earlier draft of §7 got this wrong, so the negative
    assertions are the point of the case.
    """
    engine = _ScriptedConnectionEngine()
    engine.reprovision_raises = DisplacedProvisioningError("another act took it over")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["reconnect", "conn-3", "--identity", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "was not performed" in rendered
    assert "Nothing was rolled back" in rendered
    assert "read what is connected first" in rendered
    assert "Do not simply run it" in rendered
    # §7's own resolution: the state is stated from a read, never from the refusal.
    assert [call[0] for call in engine.calls] == ["reprovision_account", "connected_accounts"]


def test_connect_reports_a_store_failure_as_not_known_with_no_reference(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: a ``ConnectionStoreError`` leaves the act's outcome **not known**.

    It is raised before the act's own first write returns, so whether that write
    landed cannot be asserted and a reference may or may not exist. It carries no
    reference **because there may be none to carry**, which is what distinguishes it
    from ``ProvisioningOutcomeUnknownError`` — so the client starts no read of a
    reference it does not have, and points at the listing instead.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = ConnectionStoreError("the connection store could not be written")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "not known" in rendered
    assert "I am not saying it landed" in rendered
    assert "no reference to name" in rendered
    assert [call[0] for call in engine.calls] == ["connect_account"]


def test_reconnect_reports_a_residual_credential_as_a_completed_act(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: a ``ResidualCredentialError`` means the act it was raised by **completed**.

    ADR-0148 §6's predecessor-slot deletion happens *after* the activation, so a
    keyring failure there arrives with all three writes landed and the record
    active. A client deriving the answer from the write order would report a live
    connection as pending and send the user to rotate a credential that was working
    — which is the case that made the conversion in §2a necessary at all.
    """
    engine = _ScriptedConnectionEngine()
    engine.reprovision_raises = ResidualCredentialError(
        "the predecessor's credential could not be deleted", "conn-4"
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["reconnect", "conn-4", "--identity", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "completed" in rendered
    assert "live at its new revision" in rendered
    assert "still there" in rendered
    assert "was not performed" not in rendered
    assert "did not complete" not in rendered


def test_a_cancelled_act_starts_no_call_and_lets_the_cancellation_leave(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7's cancellation clause, whose middle sentence is the load-bearing one.

    A cancelled client is still asked to report, which invites reading the state
    before reporting it — the same breach by a kinder route. ADR-0060 permits
    deferring a cancellation only while a method makes its resources safe, and a
    read performed to present a state is not that. So: the act is reported, no
    second call goes out, and the ``CancelledError`` still leaves.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = asyncio.CancelledError()
    _wire(monkeypatch, engine)

    # It reaches the caller rather than being reported and swallowed. ``CliRunner``
    # catches ``Exception`` and nothing wider, so a ``BaseException`` arriving here
    # *is* the propagation ADR-0060 requires.
    with pytest.raises(asyncio.CancelledError):
        CliRunner().invoke(cli.app, ["connect", "me@example.com"])

    rendered = _flat(output.getvalue())
    assert "not known" in rendered
    assert "cancelled" in rendered
    assert [call[0] for call in engine.calls] == ["connect_account"]


def test_an_oversized_result_is_reported_as_not_known(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ``OversizedValueError`` is a typed refusal that is nonetheless unknown.

    On a mutating call the result is measured *after* the work has committed
    (ADR-0085 §8e, #570), so an oversized result means the act landed and could not
    be reported, while an oversized argument is refused before any I/O and did not
    land. A caller cannot tell those apart from the exception, and picking one would
    be the guess ADR-0139 §4's third outcome exists to avoid. It is the ruling
    :func:`~ai_assistant.interfaces.cli._outcome_of` already applies to a grant.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = OversizedValueError(
        "the result does not fit the frame", limit=512, size=9000, field=None
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "not known" in rendered
    assert "hub_max_frame_bytes" in rendered


def test_a_partial_outcome_whose_state_cannot_be_read_says_so(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed read leaves the state **unread** rather than assumed (§7).

    The alternative is a client that says "nothing is connected" because it could
    not ask, which is the inference §7 forbids arriving through the resolution the
    same clause prescribes.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = IncompleteProvisioningError("interrupted", "conn-7")
    engine.connected_raises = ConnectionStoreError("still unreadable")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "could not read the state of conn-7" in rendered
    assert "nothing is connected" not in rendered


# --- §8: a disconnection says what was removed, and never more ---------------


def test_disconnect_reports_what_was_removed_and_never_more(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §8's fourth clause: the weaker guarantee is the true one.

    "That account can no longer be used" is the sentence a person writes and it
    promises three things ADR-0149 §5 declines to. What is true is that no live
    record names any slot for the reference — and the last of the three negatives
    closes an overclaim the acts make available together, since disconnecting
    everything is not ADR-0149 §8's purge and does not discharge the delete right.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    reference = engine.connections.entries[-1].reference
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["disconnect", reference])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "Disconnected." in rendered
    assert "no live record names any credential" in rendered
    assert "does not stop anything already in flight" in rendered
    assert "not a guarantee that my keyring holds nothing" in rendered
    assert "not the same as erasing this installation" in rendered


def test_a_none_return_is_not_presented_as_a_disconnection(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §8's second clause, which refuses three readings at once.

    A ``None`` is **not** a report of a disconnection, not a confirmation that a
    credential was deleted, and not a statement that the reference does not exist:
    the store may hold entries for it that no live record names. It says one thing
    — no live record was removed by this call — and the assertions below are that it
    says that one thing and none of the other three.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["disconnect", "conn-nothing"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "Nothing was removed" in rendered
    assert "does not say the reference is unknown" in rendered
    assert "Disconnected." not in rendered
    assert "deleted" not in rendered


def test_disconnect_reports_a_residual_credential_as_disconnected_and_incomplete(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's third clause: the removal landed and a deletion did not.

    Driven through the canonical fake's own keyring rather than a scripted raise,
    because the ordering is the substance: the removal entry is appended first and
    the slots go second (ADR-0149 §5), so a keyring that fails after the entry has
    landed leaves the reference disconnected with a credential still named by the
    store. The client reports both halves and never a failed disconnection.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    reference = engine.connections.entries[-1].reference
    engine.connections.secrets.become_unavailable()
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["disconnect", reference])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "Disconnected." in rendered
    assert "still there" in rendered
    assert "safe to repeat" in rendered
    assert "Nothing was removed" not in rendered


def test_disconnect_sends_no_read_before_the_act(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call, and the liveness pre-check is deliberately absent.

    A read before the act would be a liveness claim the client then acted on, which
    ADR-0151 §7 and §9 keep apart everywhere else on this surface — and it would
    fail for the one case a disconnection exists for, a reference whose record the
    client cannot read. What the user is told comes from the act's own answer.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    reference = engine.connections.entries[-1].reference
    engine.calls.clear()

    result = CliRunner().invoke(cli.app, ["disconnect", reference])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == ["disconnect_account"]


# --- §9: what the two listings answer, and what neither claims ---------------


def test_connections_is_one_call_and_presents_the_set_as_it_arrived(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0139 §1 through ADR-0151 §9: neither listing is derived from the other.

    The adapter does not fetch the act history to annotate the set, does not drop a
    record whose integration is not built, and does not merge two answers. A
    connection the hub can do nothing with is exactly what this command exists to
    show, and each of those moves would hide it from the disconnection that is its
    owner's only remedy.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    engine.calls.clear()

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    assert [call[0] for call in engine.calls] == ["connected_accounts"]


def test_connections_says_it_is_a_snapshot_and_not_an_authorisation(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9's snapshot clause and §12's third clause, in one rendering.

    A listing computed from one read is not a claim that stays true after it is
    computed, and no client presents it as one. And a connection is not an
    authorisation: nothing here is a list of what the assistant may do, which is
    the confusion the neighbouring grant surface makes available.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "snapshot" in rendered
    assert "not an authorisation" in rendered
    assert "assistant granted" in rendered


def test_connections_on_an_empty_store_answers_its_own_question(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty set is an answer, and it is not the grant surface's answer."""
    _wire(monkeypatch, _ScriptedConnectionEngine())

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "Nothing is connected" in rendered
    assert "assistant connect" in rendered


def test_the_connection_log_makes_no_timing_claim(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: "no client presents its order as a timing claim, an interval, or a statement".

    A connection record carries no instant — ADR-0149 §3 fixes what one holds and an
    instant is not among it — so a position on this page is where the store recorded
    the act and nothing more. The listing is also not read for liveness: it is
    bounded by ``limit``, so a reference whose latest act falls outside the page
    would be reported here by an *earlier* act.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connection-log"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "There are no times here" in rendered
    assert "says an act happened, not that it still stands" in rendered
    assert "assistant connections" in rendered


def test_the_connection_log_renders_a_removal_as_the_absence_of_an_account(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0149 §5 through ADR-0151 §4: a removal is not a third provisioning state.

    ``ConnectionAct.account`` is ``None`` exactly when the act was a disconnection,
    and that absence is what the two branches of the renderer are. An enum member
    would have invited the third state ADR-0149 §5 forbids in terms.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    reference = engine.connections.entries[-1].reference
    CliRunner().invoke(cli.app, ["disconnect", reference])
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connection-log"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "disconnected" in rendered
    assert "connected" in rendered
    assert "me@example.com" in rendered


def test_the_connection_log_never_presents_an_interrupted_act_as_a_connection(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §9: no client presents a row from this listing as live.

    A row says how far *that act* got, and an act that never activated is the case
    where the natural verb would be the forbidden claim: "connected" over an entry
    whose activation never landed states liveness in one word, on the surface §9
    says may not state it at all. §4's prohibition arrives here too — the row says
    the act never completed and never that it is still going.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    engine.connections.secrets.become_unavailable()
    CliRunner().invoke(cli.app, ["connect", "interrupted@example.com"])
    engine.connections.secrets.become_available()
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connection-log"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "tried to connect interrupted@example.com" in rendered
    assert "the act never completed" in rendered
    assert "connected interrupted@example.com" not in rendered


def test_the_connection_log_on_an_empty_store_records_nothing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty history is an answer, and it claims nothing about liveness."""
    _wire(monkeypatch, _ScriptedConnectionEngine())

    result = CliRunner().invoke(cli.app, ["connection-log"])
    assert result.exit_code == 0
    assert "Nothing recorded" in output.getvalue()


# --- §6: the credential is one argument, and never an argv one ---------------


def test_the_credential_is_never_a_command_line_argument(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secret on the command line is in a shell history and in every ``ps`` listing.

    Three durable disclosures of a Tier 0 value (ADR-0125 §1) that nothing
    downstream undoes, so the option does not exist on either provisioning command
    — asserted against the parser rather than against the help text, because a help
    string is not what a user's shell reads.
    """
    _wire(monkeypatch, _ScriptedConnectionEngine())

    for argv in (
        ["connect", "me@example.com", "--credential", "hunter2"],
        ["reconnect", "conn-1", "--identity", "me@example.com", "--credential", "hunter2"],
    ):
        assert CliRunner().invoke(cli.app, argv).exit_code == 2, argv


def test_the_credential_read_from_stdin_is_not_stripped(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0125 §3: two spellings of a secret are two different secrets.

    An integration credential is whatever the service issued, and a client that
    helpfully removed a trailing space would produce an authentication failure
    nobody could reproduce by inspection. Exactly one line terminator goes.

    ``device enrol`` used to have a reader of its own that called ``strip()``,
    defended on the ground that a hub-minted credential comes from an alphabet with
    no whitespace in it. That is an invariant of the minting alphabet rather than of
    the reader, and #1146 routed that command through this one instead.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["connect", "me@example.com", "--credential-stdin"], input=" hunter2 \n"
    )
    assert result.exit_code == 0
    assert engine.credentials == [" hunter2 "]


def test_a_credential_ending_in_a_carriage_return_reaches_the_hub_intact(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminator is matched as a unit, never stripped one character at a time.

    ``sys.stdin`` hands a **final** ``\r`` through untranslated — there is no
    following byte to make it a newline — so a chained
    ``removesuffix("\n").removesuffix("\r")`` silently shortens a credential that
    legitimately ends in one. ADR-0125 §3 is explicit that removing a trailing
    character "would produce an authentication failure nobody could reproduce by
    inspection", and this is the shape that failure takes here: the value the user
    piped in and the value the keyring receives differ by one invisible byte.

    Found by adversarial review on this branch; the two cases below are the
    unterminated one it named and the ``\r\n`` one that must still lose both.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    assert (
        CliRunner()
        .invoke(cli.app, ["connect", "a@example.com", "--credential-stdin"], input="hunter2\r")
        .exit_code
        == 0
    )
    assert (
        CliRunner()
        .invoke(cli.app, ["connect", "b@example.com", "--credential-stdin"], input="hunter2\r\n")
        .exit_code
        == 0
    )
    assert engine.credentials == ["hunter2\r", "hunter2"]


class _RecordingStdin:
    """A standard input whose reads are observable, and unbounded if asked for.

    The materialisation this pins is not visible in an end-to-end run — an
    unbounded read of a 4 KB pipe and a bounded read of the same pipe produce the
    same refusal — so the assertion has to be on the *request*. This records the
    limit it was handed and answers with exactly that many bytes, which is what a
    stream still going at that point does.
    """

    def __init__(self) -> None:
        """Create the stub with nothing recorded."""
        self.limits: list[int | None] = []
        self.buffer = self

    def readline(self, limit: int | None = None) -> bytes:
        """Record the bound this read asked for and fill it."""
        self.limits.append(limit)
        if limit is None:  # pragma: no cover — the failure this test exists to catch
            msg = "an unbounded read of standard input"
            raise AssertionError(msg)
        return b"x" * limit


def test_the_hidden_prompt_refuses_a_standard_input_that_is_not_a_terminal(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt is bounded by refusing the case where it stops being a prompt.

    ``getpass`` reaches for the controlling terminal first, and where there is none
    it falls back to :func:`~getpass.fallback_getpass`, which prints "Password
    input may be echoed" and reads ``sys.stdin.readline()`` **unbounded**. Both
    halves are wrong for a Tier 0 value: the echo is the disclosure ``hide_input``
    was asked for, and the unbounded read is the allocation the bounded path exists
    to avoid, arriving through the door that did not advertise itself as a pipe.

    Asserted through the real reader rather than the substituted one — this is the
    only case in the file that exercises
    :func:`~ai_assistant.interfaces.cli._prompt_for_credential` itself, because it
    is the only one about what that function does before it prompts.

    Found by adversarial review on this branch.
    """
    engine = _ScriptedConnectionEngine()

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"], input="hunter2\n")
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "--credential-stdin" in rendered
    assert "hunter2" not in rendered
    assert engine.calls == []


def test_the_stdin_read_is_bounded_by_the_widest_admissible_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read is bounded, so a pipe with no newline is a refusal and not an allocation.

    ``sys.stdin.readline()`` with no bound reads until a newline or EOF, so a stream
    that never supplies one is materialised whole *before* ``secret_value`` applies
    its 1024-byte bound — the check arriving after the cost it exists to avoid.
    Reading one byte past the widest admissible line makes the refusal decidable
    from what has been read, and the bound is asserted on the read itself because
    the two implementations are indistinguishable from their output.

    Found by adversarial review on this branch.
    """
    stdin = _RecordingStdin()
    monkeypatch.setattr(sys, "stdin", stdin)

    with pytest.raises(ValueError, match=str(SECRET_VALUE_MAX_BYTES)):
        cli._credential_from_stdin()

    assert stdin.limits == [SECRET_VALUE_MAX_BYTES + 2]


def test_an_unterminated_stdin_line_is_refused_naming_only_the_bound(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal names the bound and neither the value nor its length.

    ADR-0125 §6 permits naming the constant and forbids a prefix, a suffix, a
    truncation, a digest **or a length** of what was rejected — the length in
    particular, because "secret length is 4096" is what a size check naturally
    reports and it is a derivation of the secret itself.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    oversized = "x" * (SECRET_VALUE_MAX_BYTES * 4)

    result = CliRunner().invoke(
        cli.app, ["connect", "me@example.com", "--credential-stdin"], input=oversized
    )
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "cannot be used" in rendered
    assert str(SECRET_VALUE_MAX_BYTES) in rendered
    assert "xxxx" not in rendered
    assert str(len(oversized)) not in rendered
    assert engine.calls == []


def test_a_maximal_credential_with_a_full_terminator_is_still_admissible(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound is on the *secret*, and the terminator is not part of it.

    A credential at exactly ``SECRET_VALUE_MAX_BYTES`` followed by ``\r\n`` is the
    widest admissible line, and it is why the read limit is the bound **plus two**
    rather than the bound: a limit of ``SECRET_VALUE_MAX_BYTES`` would refuse a
    conforming value for the width of its own line ending.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)
    maximal = "x" * SECRET_VALUE_MAX_BYTES

    result = CliRunner().invoke(
        cli.app,
        ["connect", "me@example.com", "--credential-stdin"],
        input=f"{maximal}\r\n",
    )
    assert result.exit_code == 0
    assert engine.credentials == [maximal]


def test_a_credential_that_is_not_utf_8_is_refused_without_echoing_a_byte(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decoding is ``surrogateescape`` because a ``UnicodeDecodeError`` discloses bytes.

    It is a ``ValueError``, so a strict decode would be caught by the same handler
    that renders one — and its message carries the offending bytes, which ADR-0125
    §6 forbids any refusal on this path from doing. Decoding leniently instead
    hands ``secret_value`` an unencodable string, and its refusal is the one the
    corpus already guarantees says nothing about the value.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["connect", "me@example.com", "--credential-stdin"], input=b"\xff\xfe\n"
    )
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "UTF-8 encoding" in rendered
    assert "0xff" not in rendered
    assert "\\xff" not in rendered
    assert engine.calls == []


def test_a_blank_credential_is_refused_before_anything_is_sent(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is local, and its message names neither the value nor its length.

    ``secret_value`` is the only supported way to build one (ADR-0125 §3), and
    revalidating at the door makes the refusal happen before a frame is built. The
    message is safe to print because ADR-0125 §6 forbids that seam's exceptions from
    carrying a prefix, a suffix, a truncation, a digest or a length.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine, credential="   ")

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "cannot be used" in rendered
    assert "Nothing was sent" in rendered
    assert engine.calls == []


def test_an_identity_equal_to_the_credential_is_refused_locally(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §5: the equality comparison is made before any write, in every implementation.

    This is the refusal ADR-0149 §4 wrote for the person who pastes their token into
    the name field, and the property that matters is that no credential is sent for
    the call: the refusal is raised locally, before any I/O, so the value never
    leaves this process.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine, credential="hunter2")

    result = CliRunner().invoke(cli.app, ["connect", "hunter2"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "known not to have landed" in rendered
    assert "never left this machine" in rendered
    assert engine.connections.entries == []


def test_reconnect_on_an_unheld_reference_is_known_not_to_have_landed(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2a: ``UnknownConnectionError`` reaches ``reprovision_account`` only.

    It is the typed refusal that makes "I meant to replace a credential and created
    a second connection instead" unreachable rather than merely visible — and
    because it is refused before the first write, the state needs no read to state.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(
        cli.app, ["reconnect", "conn-absent", "--identity", "me@example.com"]
    )
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "known not to have landed" in rendered
    assert "nothing was written" in rendered
    assert [call[0] for call in engine.calls] == ["reprovision_account"]


# --- §13: the operations are not carried off the hub's own socket ------------


def test_a_transport_that_does_not_carry_the_operations_is_reported(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0151 §13 keeps these operations on ADR-0084 §1's loopback socket.

    The refusal is the wire client's — an ``AssistantEngine`` method cannot see its
    transport — and what this pins is that the CLI renders it rather than dying on
    it, and that the outcome is reported as unknown rather than as a failure that
    did not land. No credential is sent for such a call: the client refuses before
    the socket is opened.
    """
    engine = _ScriptedConnectionEngine()
    engine.connect_raises = ProtocolError("connect_account() is not carried on this transport")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "not carried on this transport" in rendered
    assert "not known" in rendered


# --- the parameter callbacks, and the hints ----------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["connect", "   "],
        ["connect", "\udce9"],
        ["reconnect", "   ", "--identity", "me@example.com"],
        ["reconnect", "conn-1", "--identity", "   "],
        ["disconnect", "   "],
        ["connection-log", "--limit", "0"],
    ],
)
def test_a_refusable_argument_is_a_usage_error_before_any_client_is_built(
    argv: list[str], output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each refusal below is a ``ValueError``, which no command's boundary catches.

    ``ValueError`` is neither an ``AssistantError`` nor a ``TransportError``, so
    without a Typer callback each of these escapes as an uncaught traceback with no
    controlled exit code — the failure ADR-0042 §7 forbids. Catching them during
    parameter parsing also means a person is not asked for a credential in order to
    be told the call was never going to be sent.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, argv).exit_code == 2
    assert engine.calls == []


def test_a_pasted_disconnect_hint_names_the_reference_it_was_printed_for(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hint has to survive being pasted (#984).

    ``DurableIdentifier`` requires encodability and nothing more, so a reference
    carrying an interior space is admissible — and unquoted it renders a line that
    is a *valid* command against the wrong argument.
    """
    engine = _ScriptedConnectionEngine()
    engine.connections = FakeConnectionProvisioner(mint_reference=lambda: "conn one")
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert _pasted(rendered, "assistant disconnect") == ["assistant", "disconnect", "conn one"]


def test_a_hint_is_withheld_where_the_reference_cannot_be_shown(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wrong command is worse than no command, and quoting does not prevent one (#1013).

    ``_safe`` *replaces* a character a terminal must not be handed, so a reference
    carrying one renders — inside perfectly correct shell quotes — as a command
    naming something that does not exist. The listing itself is never withheld; only
    the copyable line is.
    """
    engine = _ScriptedConnectionEngine()
    engine.connections = FakeConnectionProvisioner(mint_reference=lambda: "conn\x1b[2J1")
    _wire(monkeypatch, engine)
    CliRunner().invoke(cli.app, ["connect", "me@example.com"])
    output.truncate(0)
    output.seek(0)

    result = CliRunner().invoke(cli.app, ["connections"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())
    assert "assistant disconnect '" not in rendered
    assert "cannot show" in rendered
    assert "me@example.com" in rendered


def test_the_rendered_identity_is_neutralised_for_this_terminal(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0042 §4: escaping is the adapter's, per target.

    An account identity is the user's own text and is displayed by contract
    (ADR-0151 §5), which makes it exactly the value an ANSI escape rides in on — and
    §5's display happens *before* the refusal ADR-0149 §4 raises for a control
    character, so the escape is rendered whatever the act then does. That ordering
    is why the escaping has to be here rather than left to the refusal: the engine
    carries the value verbatim and this surface neutralises it for the terminal it
    is writing to, and for Rich's markup as well.
    """
    engine = _ScriptedConnectionEngine()
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["connect", "me\x1b[2J[red]@example.com"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "\x1b[2J" not in rendered
    assert "[red]" in rendered
    assert "known not to have landed" in rendered
    assert engine.connections.entries == []


def test_every_connection_command_reports_a_closed_door_rather_than_falling_back(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0084 §9: a closed door is an instruction, never a fallback.

    Each command's single error boundary (ADR-0042 §7) is asserted over all five, so
    a hub that is not running produces a controlled exit code and a rendered message
    rather than a traceback — including on the two that would otherwise have
    prompted for a credential first.
    """

    async def _closed() -> object:
        msg = "no hub is listening on that socket"
        raise TransportError(msg)

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _closed)

    for argv in (
        ["connect", "me@example.com"],
        ["reconnect", "conn-1", "--identity", "me@example.com"],
        ["disconnect", "conn-1"],
        ["connections"],
        ["connection-log"],
    ):
        result = CliRunner().invoke(cli.app, argv)
        assert result.exit_code == 1, argv
        assert result.exception is None or isinstance(result.exception, SystemExit), argv
    assert "not reachable" in output.getvalue()


def test_the_connection_state_phrase_is_total_over_the_enum() -> None:
    """A third ``ProvisioningState`` would fail the type check, not render as empty.

    ADR-0149 §5 forbids a third member and ADR-0151 §4 expresses that as a
    two-member enum; the renderer is written over it through ``assert_never`` so the
    prohibition is held by the type checker rather than by a reader's memory.
    """
    assert {cli._connection_state_phrase(state) for state in ProvisioningState} == {
        "connected",
        "not connectable — the act that wrote it never finished",
    }
