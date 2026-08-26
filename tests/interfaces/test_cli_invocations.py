"""The CLI invocation surface: ADR-0192 §4's rendering floor and its bars, clause by clause.

The direct model is ``test_cli_reads.py``, which is itself ``test_cli_decisions.py``
one store over — this is the third pair on the same trail, so a door that differed
would be a difference the contract does not have. What is *not* mirrored is what
this row kind adds: two row kinds rather than one, an outcome, a failure kind that
may be absent **and is stated as absent**, an incurred cost that may be unknown and
is likewise stated, and the hardest half of ADR-0192 §4 — a list of sentences the
renderer must never write.

**Driven through a scripted engine rather than the canonical fake's own trail** for
``test_cli_reads.py``'s reason: what is under test is the adapter's rendering of
what the operation hands back, and the order is the *engine's* guarantee (golden
rule 3). The operations' order, prefix property and local refusals are pinned in
``tests/orchestration/assistant_engine_contract.py`` by the same lane, over all
three implementations at once.

**One case is not scripted, deliberately.** ADR-0192 §9 requires "an end-to-end test
through it that lists and exports rows a seeded trail holds, so the adapter
obligations below are not discharged by an empty set", and a scripted engine cannot
discharge that — it hands the adapter rows nothing appended. So
:func:`test_the_adapter_lists_and_exports_rows_a_real_trail_holds` drives the two
commands over a ``FakeAssistantEngine`` reading a ``FakeAuditTrail`` the case filled
through the ledger, which is the only path a row exists on (ADR-0192 §2).

**The bars are asserted as claims and not as letters**, which ADR-0192 §9 requires
in terms: "They are **not** a substring search over the whole rendering, and a suite
written as one is wrong rather than strict." What makes the scan below a claim test
is the *fixture*: every value the rows carry is inert, so everything left on screen
is a phrase this module's renderer chose. The control that proves it is the case
below over a tool identifier carrying one of the barred words — ``read_email``, the
example the ADR itself names.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import TypeAdapter
from rich.console import Console
from typer.testing import CliRunner

from ai_assistant.core.config import Settings
from ai_assistant.core.errors import AuditError, OversizedValueError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    ActionRequest,
    CostBasis,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordedInvocation,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine, FakeAuditTrail
from ai_assistant.wire import TransportError

if TYPE_CHECKING:
    from collections.abc import Iterator

#: When the seeded rows were recorded. Fixed, so what a case asserts is the value's
#: rendering rather than the run's clock.
_AT = datetime(2026, 3, 3, 11, 0, tzinfo=UTC)

#: The six claims ADR-0192 §4 bars a surface from making, on any row, in any state:
#: *sent*, and then *read*, *received*, *delivered*, *seen* and *acted on* by any
#: recipient. Matched on **word boundaries** over a rendering whose every carried
#: value is inert, which is what makes this an assertion about the sentences this
#: module authors rather than the substring search §9 calls wrong.
_BARRED_CLAIMS: Final = ("sent", "read", "received", "delivered", "seen", "acted on")

#: The verbs in which a **row** would assert that the call executed — the claim
#: ADR-0192 §4 bars alongside its six: "A row saying 'this ran' would be asserting a
#: fact no row carries, which is the same fact ADR-0034 §1 declines to mint and #234
#: owns."
#:
#: **A row's vocabulary and not the whole surface's**, which is the distinction an
#: earlier version of this constant lost. §4 licenses one execution statement — a
#: ``SUCCEEDED`` completion "is the tool reporting an outcome back through the seam,
#: which is unreachable without the callable" — and ``assistant invocations --help``
#: makes exactly that statement, scoped to that case, in the words "which it could
#: not do without having run". So the bar belongs on the rows, where no such scoping
#: is available and every kind shares one renderer; the help is held to a
#: **contextual** assertion instead, in
#: :func:`test_the_help_describes_the_ruling_a_row_names`.
#:
#: **Bare rather than phrase-matched**, on ``_BARRED_CLAIMS``' terms: the fixtures
#: carry inert values, so a word left on screen is one this module's renderer chose,
#: and the renderer has no legitimate use for any of them — it states the *opposite*
#: in words, and the positive half of that is asserted beside the negative below.
#: ``running`` is deliberately out of reach: the footer's "anything is still
#: running" is a liveness disclaimer, and ``\brun\b`` does not match inside it.
_EXECUTION_CLAIMS: Final = ("ran", "run", "executed")

#: What the opener writes to standard output when a case asks it to. Recognisable
#: rather than plausible, so an assertion that it reached standard error is about
#: this line and not about something the command legitimately printed.
_NOISE: Final = "a-diagnostic-that-must-not-reach-the-artifact"

#: The four things §4 forbids naming on an invocation row. Asserted over the
#: **structured** half as well — the export's keys — because that is where a lane
#: would add one and no prose assertion would notice.
_BARRED_SUBJECTS: Final = ("recipient", "account", "endpoint", "destination")


# --- the rows ----------------------------------------------------------------


def _claim(
    row_id: str = "i-1", *, egress_call: bool = False, at: datetime | None = None
) -> RecordedInvocation:
    """One claim, joined to its decision as the store joins it (ADR-0192 §2)."""
    return RecordedInvocation(
        invocation=ToolInvocation(
            id=row_id, decision_id="d-1", recorded_at=at if at is not None else _AT
        ),
        tool="t-1",
        capability="c-1",
        egress_call=egress_call,
    )


def _completion(  # noqa: PLR0913 — one keyword per shape §2 admits, each varied by a case
    row_id: str = "i-2",
    *,
    outcome: ToolOutcome = ToolOutcome.FAILED,
    failure_kind: ToolFailureKind | None = None,
    cost: ToolCost | None = None,
    egress_call: bool = False,
    at: datetime | None = None,
) -> RecordedInvocation:
    """One completion, joined the same way.

    ``cost`` defaults to an **unknown** basis rather than to free, because free is
    the answer a helpful default would quietly supply for the state ADR-0192 §5
    exists to keep distinct — and a case that means *free* should have to say so.
    """
    return RecordedInvocation(
        invocation=ToolInvocation(
            id=row_id,
            decision_id="d-1",
            recorded_at=at if at is not None else _AT,
            completes="i-1",
            outcome=outcome,
            incurred_cost=cost if cost is not None else ToolCost(basis=CostBasis.UNKNOWN),
            failure_kind=failure_kind,
        ),
        tool="t-1",
        capability="c-1",
        egress_call=egress_call,
    )


#: **Every completion shape ADR-0192 §2 admits**, which ADR-0192 §9 enumerates and
#: requires every adapter case to run over: "a renderer that branches on ``FAILED``
#: passes a ``FAILED``-only test and then crashes or silently drops a kind on the
#: others". Six rather than three, because ``ToolOutcome`` has three members and the
#: shapes are more — the kind is present or absent independently on the two failing
#: outcomes, and ``SUCCEEDED`` carries none at all on either value of
#: ``egress_call``.
_COMPLETION_SHAPES: Final[tuple[tuple[str, RecordedInvocation], ...]] = (
    ("failed with no kind", _completion(outcome=ToolOutcome.FAILED)),
    ("indeterminate with no kind", _completion(outcome=ToolOutcome.INDETERMINATE)),
    (
        "indeterminate with a reported kind",
        _completion(outcome=ToolOutcome.INDETERMINATE, failure_kind=ToolFailureKind.TIMED_OUT),
    ),
    (
        "failed with a reported kind",
        _completion(outcome=ToolOutcome.FAILED, failure_kind=ToolFailureKind.UNAVAILABLE),
    ),
    (
        "succeeded on an egress call",
        _completion(
            outcome=ToolOutcome.SUCCEEDED,
            egress_call=True,
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.02"), currency="USD"),
        ),
    ),
    (
        "succeeded on a local call",
        _completion(
            outcome=ToolOutcome.SUCCEEDED,
            egress_call=False,
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.02"), currency="USD"),
        ),
    ),
)

#: Every shape a row can take, the two claims included — ADR-0192 §9 rides the
#: negatives "across the claim row on both values of ``egress_call``, and across
#: every completion shape §2 admits".
_EVERY_SHAPE: Final[tuple[tuple[str, RecordedInvocation], ...]] = (
    ("a claim on an egress call", _claim(egress_call=True)),
    ("a claim on a local call", _claim(egress_call=False)),
    *_COMPLETION_SHAPES,
)


# --- the subject -------------------------------------------------------------


class _ScriptedInvocationEngine(FakeAssistantEngine):
    """A hub whose invocation trail is whatever a case seeds, in the order it answers.

    ``FakeAssistantEngine`` is otherwise untouched, so what the adapter is handed is
    the contract's own shape. The two overrides do **not** re-implement ADR-0192
    §4's local refusal of ``limit``: the CLI refuses a malformed one during Typer's
    parameter parsing, before any engine exists, and the case below asserts exactly
    that by observing that no call was ever recorded.
    """

    def __init__(self, *recorded: RecordedInvocation) -> None:
        """Create an engine over ``recorded``, in the order it will answer with."""
        super().__init__()
        #: The trail, already in the operation's order — the engine's guarantee and
        #: not something the adapter may re-establish (golden rule 3, ADR-0192 §4).
        self.recorded: tuple[RecordedInvocation, ...] = recorded
        #: Raised instead of answering ``recent_invocations``.
        self.listing_raises: BaseException | None = None
        #: Raised instead of answering ``export_invocations``.
        self.export_raises: BaseException | None = None

    async def recent_invocations(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecordedInvocation, ...]:
        """The first ``limit`` rows — the prefix property, held by construction."""
        self.calls.append(("recent_invocations", {"limit": limit}))
        if self.listing_raises is not None:
            raise self.listing_raises
        return self.recorded[:limit]

    async def export_invocations(self) -> tuple[RecordedInvocation, ...]:
        """Every row the trail holds, in the same order."""
        self.calls.append(("export_invocations", {}))
        if self.export_raises is not None:
            raise self.export_raises
        return self.recorded


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it.

    **Wide enough that nothing wraps**, so a case asserting what one row's line
    carries cannot be defeated by a line break. :func:`_flat` is still what the
    prose cases assert through.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object, *, noise: str = "") -> None:
    """Point the invocation commands' startup at ``engine``.

    The seam is :func:`~ai_assistant.interfaces.cli._open_engine`, as it is for
    every other command on this surface (ADR-0084 §6).

    Args:
        engine: What the commands are handed.
        noise: Written to ``sys.stdout`` by the opener, before the engine is
            returned. **Not decoration**: ADR-0186 §9's stream clause is about the
            *stream* rather than about this adapter's own politeness, so an export
            case run over a silent opener would stay green with
            ``contextlib.redirect_stdout`` deleted — and the first log line emitted
            anywhere on the client path would then land in the middle of a user's
            artifact. ``structlog``'s ``PrintLoggerFactory`` defaults to
            ``sys.stdout``, so this is the state the redirect exists against rather
            than a hypothetical one.
    """

    async def _open() -> object:
        if noise:
            print(noise)
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


def _flat(rendered: str) -> str:
    """The rendering with its line wrapping removed, so a case asserts sentences."""
    return " ".join(rendered.split())


def _listing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, *recorded: RecordedInvocation
) -> str:
    """Run ``assistant invocations`` over ``recorded`` and return the flattened screen."""
    _wire(monkeypatch, _ScriptedInvocationEngine(*recorded))
    result = CliRunner().invoke(cli.app, ["invocations"])
    assert result.exit_code == 0
    return _flat(output.getvalue())


def _rows_only(rendered: str) -> str:
    """The row block alone, with the page's own footer cut off.

    The footer names both kinds on purpose — a reader who has just met "call begun"
    and "call finished" needs the sentence saying they are two rows of one attempt —
    so a count of either label over the whole page counts one footer mention too. A
    case about **how many rows carry a kind** has to ask the rows, and bending the
    footer's wording to make a naive count work would be trading a sentence the user
    needs for an assertion that is easier to write.
    """
    return rendered.split("One attempt is up to two rows", maxsplit=1)[0]


def _claims(rendered: str) -> Iterator[str]:
    """Every barred claim this rendering makes, matched on word boundaries."""
    for barred in _BARRED_CLAIMS:
        if re.search(rf"\b{barred}\b", rendered, flags=re.IGNORECASE):
            yield barred


# --- §4: the rendering floor, on every shape §2 admits ------------------------


@pytest.mark.parametrize(
    ("shape", "row"), _COMPLETION_SHAPES, ids=[s for s, _ in _COMPLETION_SHAPES]
)
def test_every_completion_shape_renders_the_whole_floor(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, shape: str, row: RecordedInvocation
) -> None:
    """ADR-0192 §4's floor, on each of the six shapes §2 admits (§9).

    **The parametrisation is the case**, not decoration. §9 says so in terms: "a
    renderer that branches on ``FAILED`` passes a ``FAILED``-only test and then
    crashes or silently drops a kind on the others", and it names ``SUCCEEDED`` as
    the shape an earlier enumeration left out — a completion carrying no kind at
    all, which is exactly the branch a kind-first renderer falls off.

    What the floor requires of every row is the kind, the instant, the tool
    identifier and the capability; of a completion also the outcome and the incurred
    cost. Each is asserted here rather than left to the shape-specific cases below,
    because "renders fewer rows rather than partial ones" is a claim about the
    *whole* row and a suite that checked one field per case would never make it.
    """
    rendered = _listing(output, monkeypatch, row)

    assert "call finished" in rendered, shape
    assert "2026-03-03 11:00:00.000000" in rendered, shape
    assert "Tool: t-1" in rendered, shape
    assert "capability c-1" in rendered, shape
    assert f"ended: {row.invocation.outcome}" in rendered.lower(), shape
    assert "Cost:" in rendered, shape


@pytest.mark.parametrize(
    "outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE], ids=["failed", "indeterminate"]
)
def test_a_completion_with_no_reported_kind_says_that_none_was_reported(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, outcome: ToolOutcome
) -> None:
    """ADR-0192 §4: the floor is met by rendering **that no kind was reported**.

    The cancellation-derived completion §2 permits and forbids any lane to fill. A
    surface "renders neither a kind it chose nor a blank, and it does not drop the
    row or the field", so all four failures are asserted at once: the field is
    present, it says the absence in words, no member of the enum has been
    substituted, and the row itself is still on screen.
    """
    rendered = _listing(output, monkeypatch, _completion(outcome=outcome))

    assert "Failure kind: none was reported" in rendered
    assert "call finished" in rendered, "the row is not dropped"
    for kind in ToolFailureKind:
        assert f"Failure kind: {kind.value}" not in rendered, "a kind was substituted"


@pytest.mark.parametrize(
    "kind",
    [ToolFailureKind.TIMED_OUT, ToolFailureKind.UNAVAILABLE],
    ids=["timed_out", "unavailable"],
)
def test_a_completion_carrying_a_kind_renders_that_kind_exactly(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, kind: ToolFailureKind
) -> None:
    """ADR-0192 §4: "the failure kind where the row **carries one**", substituting nothing.

    **The word is the enum's own**, so what a user sees on screen and what an
    exported row carries are the same word and a reader comparing the two needs no
    glossary between them.
    """
    rendered = _listing(
        output, monkeypatch, _completion(outcome=ToolOutcome.INDETERMINATE, failure_kind=kind)
    )

    assert f"Failure kind: {kind.value}" in rendered
    assert "none was reported" not in rendered


def test_the_successful_pair_renders_its_cost_and_says_the_egress_sentence_once(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §9's ``SUCCEEDED`` pair, all three of its clauses at once.

    "On the ``SUCCEEDED`` pair the adapter renders the cost the row carries, says
    **attempted and reported success** on the egress one and says it on the other
    **nowhere**, and raises on neither." The pair is rendered in **one listing** so
    that the negative is a statement about a page holding both rows: an adapter
    deciding the sentence from the outcome alone would put it on the local call
    here, where a two-listing case would let it decide from whichever row it saw.
    """
    egress = _completion(
        "i-2",
        outcome=ToolOutcome.SUCCEEDED,
        egress_call=True,
        cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.02"), currency="USD"),
    )
    local = _completion(
        "i-3",
        outcome=ToolOutcome.SUCCEEDED,
        egress_call=False,
        cost=ToolCost(basis=CostBasis.FREE),
    )

    rendered = _listing(output, monkeypatch, egress, local)

    assert rendered.count("attempted and reported success") == 1
    assert "Cost: 0.02 USD" in rendered
    assert "Cost: free" in rendered


def test_the_egress_sentence_is_said_on_no_other_row_or_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §4: "It says this on no other row and in no other state."

    ``SUCCEEDED`` is the one state establishing the callable was entered — it is the
    tool reporting an outcome back through the seam — so a claim, a failure and an
    indeterminate outcome each carry the egress boolean and none of them licenses
    the sentence. Asserted over a page holding **every** shape but the successful
    egress one, which is the arrangement in which a renderer keying on
    ``egress_call`` alone fails.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _claim("i-1", egress_call=True),
        _completion("i-2", outcome=ToolOutcome.FAILED, egress_call=True),
        _completion("i-3", outcome=ToolOutcome.INDETERMINATE, egress_call=True),
    )

    assert "attempted and reported success" not in rendered


@pytest.mark.parametrize(
    ("basis", "expected"),
    [
        (ToolCost(basis=CostBasis.UNKNOWN), "Cost: not known"),
        (ToolCost(basis=CostBasis.FREE), "Cost: free"),
        (
            ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("1.50"), currency="EUR"),
            "Cost: 1.50 EUR",
        ),
    ],
    ids=["unknown", "free", "per_call"],
)
def test_the_incurred_cost_is_rendered_including_that_it_is_unknown(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, basis: ToolCost, expected: str
) -> None:
    """ADR-0192 §4: the cost "**including that the cost is unknown**".

    The three bases, and the unknown one is what the clause exists for. *Free* and
    *unknown* are the distinction ``ToolCost`` keeps apart everywhere else — the
    first a fact a running total can add, the second an absence a ceiling must fail
    closed on (ADR-0016 §4, ADR-0194) — and a surface folding them would undo at the
    last inch what the type protects. So the unknown row is asserted **not** to
    render as free, as a zero, or as nothing at all.
    """
    rendered = _listing(output, monkeypatch, _completion(cost=basis))

    assert expected in rendered
    if basis.basis is CostBasis.UNKNOWN:
        assert "Cost: free" not in rendered
        assert "Cost: 0" not in rendered


# --- §4: what the renderer must never say ------------------------------------


@pytest.mark.parametrize(("shape", "row"), _EVERY_SHAPE, ids=[s for s, _ in _EVERY_SHAPE])
def test_no_shape_makes_a_barred_claim_in_the_adapter_s_own_words(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, shape: str, row: RecordedInvocation
) -> None:
    """ADR-0192 §4's six bars, over every row in every state (§9).

    §4 bars *sent*, *read*, *received*, *delivered*, *seen* and *acted on*, and §9
    requires the assertion over **every** barred claim on **every** row rather than
    over one word on one row: "a renderer emitting 'attempted and reported success;
    delivered to alice@example.com' satisfies an assertion about *sent* alone while
    breaking both the truthfulness rule and the Tier 1 disclosure one."

    **What makes this a claim test rather than the substring search §9 calls wrong
    is the fixture.** Every value these rows carry is inert — ``i-1``, ``d-1``,
    ``t-1``, ``c-1`` — so every word left on screen is one this module's renderer
    chose, and the scan is over the adapter's own sentences by construction. The
    control that proves it is
    :func:`test_a_barred_word_inside_a_value_the_row_carries_is_not_a_barred_claim`.

    **The bars hold even where a truthful sentence would be tempting.** ``sent`` is
    the sharp one: on a successful egress completion the row is as close to a
    transmission as this record ever gets, and ADR-0031 §4 still bounds
    ``SUCCEEDED`` to a validated callable return, an unexpired deadline and no
    increase in the cancellation count — none of which is a transmission.
    """
    rendered = _listing(output, monkeypatch, row)

    assert list(_claims(rendered)) == [], shape


@pytest.mark.parametrize(("shape", "row"), _EVERY_SHAPE, ids=[s for s, _ in _EVERY_SHAPE])
def test_no_shape_names_a_recipient_an_account_an_endpoint_or_a_destination(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, shape: str, row: RecordedInvocation
) -> None:
    """ADR-0192 §4: none of the four is named on an invocation row, in any state.

    ``egress_call`` "states that the call was an egress call and states nothing
    about whose bytes went where"; the recipients are ``assistant decisions``' to
    render under ADR-0186 §7's floor, from the binding itself. The row carries none
    of the four to render even if this adapter wanted to (ADR-0192 §2), which is
    what makes the bar cheap here and load-bearing anyway: a helpful lane resolving
    the decision id to fetch them would be making the second read §4 forbids.
    """
    rendered = _listing(output, monkeypatch, row)

    for subject in _BARRED_SUBJECTS:
        assert not re.search(rf"\b{subject}s?\b", rendered, flags=re.IGNORECASE), (
            f"{shape} named a {subject}"
        )


@pytest.mark.parametrize(("shape", "row"), _EVERY_SHAPE, ids=[s for s, _ in _EVERY_SHAPE])
def test_no_shape_asserts_that_the_call_ran(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, shape: str, row: RecordedInvocation
) -> None:
    """ADR-0192 §4: a row is an act **begun**, never a statement that the callable ran.

    "A surface renders an invocation row as an act the system began on that
    authorisation — a call it claimed and then attempted — and **not** as a
    statement that the tool callable was entered", because the claim is written
    *before* the callable and §1's cancellation clause has a path where the claim
    lands, its completion is written, and the callable is provably never entered.

    **The claim row is the sharp case and the completion rows are not exempt.** Even
    on ``SUCCEEDED``, where entry *is* established, §4 bounds what may be said to
    *attempted and reported success* — so no row here says the call ran, and the
    renderer has no wording that would.

    **The positive half is asserted beside the negative**, because a surface can
    avoid a word and still leave the inference standing: the claim row states in
    terms that it does not say the tool was entered, which is what makes the silence
    a statement rather than an omission (ADR-0184's positively-read absence).
    """
    rendered = _listing(output, monkeypatch, row)

    for asserted in _EXECUTION_CLAIMS:
        assert not re.search(rf"\b{asserted}\b", rendered, flags=re.IGNORECASE), (
            f"{shape} asserted that the call {asserted}"
        )
    if row.invocation.completes is None:
        assert "It does not say the tool itself was entered" in rendered


#: One ANSI SGR sequence. ``tests/interfaces/test_cli.py``'s pattern, for its
#: reason: Typer renders ``--help`` through a Rich console this module does not own,
#: and that console decides its own colour and width from the environment.
_SGR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _help_text(rendered: str) -> str:
    """Help output as flowing words: no colour, no borders, no wrapping.

    Lifted from ``tests/interfaces/test_cli_reads.py``'s helper of the same name.
    Rich pads every line of a description with SGR codes, so a paragraph that wraps
    puts ``\x1b[0m`` between two words of one sentence — and a phrase asserted
    across that break is absent from the string while plainly present on the
    screen. Normalising rather than pinning ``COLUMNS`` makes the assertion true at
    every width instead of at one agreed width.
    """
    return " ".join(_SGR.sub("", rendered).replace("│", " ").split())


@pytest.mark.parametrize(
    ("command", "anchor"),
    [
        ("invocations", "Show what I did on the authorisations you gave me"),
        ("export-invocations", "Write every act I recorded on an authorisation"),
    ],
    ids=str,
)
def test_the_help_describes_the_ruling_a_row_names(command: str, anchor: str) -> None:
    """ADR-0192 §4's bars reach the help text, not only the rows.

    **The help is adapter-authored prose about this row kind**, and a user reads it
    before they read a row — so a command whose description said a row records what
    "ran under" a ruling would teach the inference §4 forbids and then render rows
    that carefully avoid it. The two sites are one claim, and only one of them was
    caught by a case over the rendering.

    **Contextual rather than a verb scan, and a verb scan is the wrong instrument
    here.** §4 licenses exactly one execution statement — a ``SUCCEEDED`` completion
    is the tool reporting an outcome back through the seam, "which is unreachable
    without the callable" — and this help makes it, scoped to that case. A scan
    barring the verb outright would forbid conforming prose while proving nothing
    about the sentence that actually went wrong, which is ADR-0192 §9's own
    objection to substring tests one register up. So what is asserted is the
    **claim**: the barred phrasing is absent and the correct one is present, in the
    one place the two compete.

    **The positive anchor is not decoration.** Typer renders help through its own
    console, and a failure there yields an empty page on which every negative
    assertion above passes vacuously. The exit code and a stable sentence from each
    page are what make the negatives mean anything at all.
    """
    result = CliRunner().invoke(cli.app, [command, "--help"])
    rendered = _help_text(result.stdout)

    assert result.exit_code == 0
    assert anchor in rendered, "the help did not render, so the negatives below are vacuous"

    assert list(_claims(rendered)) == []
    assert "ran under" not in rendered
    assert "runs under" not in rendered


def test_the_listing_help_names_the_ruling_rather_than_asserting_execution() -> None:
    """The positive half of the clause above, on the one command that states it.

    ``export-invocations`` describes an artifact and has no occasion to mention the
    ruling at all, so asserting the phrase over both would pin a sentence one of
    them has no reason to carry. This is the page where the wording was wrong.
    """
    rendered = _help_text(CliRunner().invoke(cli.app, ["invocations", "--help"]).stdout)

    # Typer renders the docstring verbatim rather than as markup, so the emphasis
    # markers are part of the page a user sees and part of the string asserted here.
    assert "A row says whether the ruling it **names** was for an outbound call" in rendered


def test_a_barred_word_inside_a_value_the_row_carries_is_not_a_barred_claim(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §9: "What is barred is the **claim** that something was read, not the letters."

    **The control for the two scans above**, and the ADR names the example: §4
    requires the tool identifier and the capability to be rendered, and
    ``VisibleIdentifier`` admits ``read_email``. "An assertion rejecting that row
    would forbid conforming output while proving nothing", so this asserts the
    opposite direction — the row renders, the letters appear, and they appear
    because the row carries them rather than because this module wrote a sentence.
    """
    carrying = RecordedInvocation(
        invocation=ToolInvocation(id="i-1", decision_id="d-1", recorded_at=_AT),
        tool="read_email",
        capability="read_inbox",
        egress_call=False,
    )

    rendered = _listing(output, monkeypatch, carrying)

    assert "Tool: read_email" in rendered
    assert "capability read_inbox" in rendered


@pytest.mark.parametrize("egress_call", [True, False], ids=["egress", "local"])
def test_a_claim_is_never_rendered_as_pending_open_or_in_flight(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, egress_call: bool
) -> None:
    """ADR-0192 §4: a claim is a call **begun**, and no row carries the other fact.

    "It does not render a claim as *pending*, *open*, *in flight* or *awaiting an
    outcome*, because no row carries that fact and the clause above forbids the join
    that would establish it." The last spelling is the one an earlier draft of the
    ADR allowed and then withdrew — "has no completion yet" is that same inference
    wearing different words — so it is asserted here beside the other four.
    """
    rendered = _listing(output, monkeypatch, _claim(egress_call=egress_call))

    assert "call begun" in rendered
    for inferred in ("pending", "in flight", "awaiting", "no completion yet", "still waiting"):
        assert inferred not in rendered.lower()
    assert not re.search(r"\bopen\b", rendered, flags=re.IGNORECASE)


def test_a_page_holding_both_kinds_states_each_row_s_kind(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §4: both kinds together, each stated, neither in the other's vocabulary.

    "One attempt appears as **up to two rows**, and a surface presents them as the
    two rows they are." The page below holds a claim and a completion of a different
    attempt, which is the arrangement that tempts an adapter into pairing them: an
    implementation that folded the two into one record would fail the count here,
    and one that rendered the claim in the completion's vocabulary would fail the
    kind assertions.
    """
    rendered = _listing(
        output, monkeypatch, _claim("i-1"), _completion("i-2", outcome=ToolOutcome.FAILED)
    )
    rows = _rows_only(rendered)

    assert rows.count("call begun") == 1
    assert rows.count("call finished") == 1
    assert "2 row(s)" in rendered


def test_an_empty_page_is_not_a_claim_that_nothing_ever_ran(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §4: a page's silence is a fact about the page.

    ADR-0192 §1's cancellation clause and §3's commit-state clause both admit paths
    where an attempt leaves fewer rows than a reader expects, so the one thing this
    surface must not do is turn an empty page into the statement the record declines
    to make. ``test_cli_reads.py`` holds the same line one store over, for
    ADR-0185 §7's version of the reason.

    The sentence says *attempted* rather than *ran*, which is not a nicety: an
    attempt is what the record holds, and the disclaimer would otherwise be denying
    a fact no row asserts in the first place — see :data:`_EXECUTION_CLAIMS`.
    """
    rendered = _listing(output, monkeypatch)

    assert "Nothing recorded." in rendered
    assert "not a claim that nothing was ever attempted" in rendered


def test_a_full_page_says_it_is_one_and_derives_no_count(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §4: "No surface derives a count of calls … from anything but the rows".

    The footer states the bound rather than a total, and it names the export as the
    way past it. A count of calls *attempted* — halving the row count, say, on the
    theory that an attempt is two rows — is exactly the derivation §4 bars, and this
    page is arranged so that it would be wrong anyway: three rows, one of which has
    no partner here.
    """
    rows = tuple(
        _claim(f"i-{index}", at=_AT - timedelta(seconds=index))
        for index in range(DEFAULT_PAGE_SIZE)
    )
    rendered = _listing(output, monkeypatch, *rows)

    assert f"Showing {DEFAULT_PAGE_SIZE}." in rendered
    assert "there is no total count" in rendered
    assert "export-invocations" in rendered


def test_a_row_with_no_partner_on_the_page_is_said_to_be_a_fact_about_the_page(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §4: the absence of a completion, or of a claim, is about the bound.

    Printed rather than assumed, because the reader who most needs it is the one
    treating a lone *call begun* as a call that is still running — the inference §4
    forbids the renderer from making and which a page cannot stop a reader making
    unless it says so.
    """
    rendered = _listing(output, monkeypatch, _claim("i-1"))

    assert "a fact about the page" in rendered
    assert "the other half may be further back" in rendered


# --- §4: the export is one faithful JSON document ----------------------------


def test_the_export_re_validates_and_carries_no_annotation_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0192 §4's faithful-copy clause, in both directions.

    The thing a helpful adapter would annotate here is the **absent failure kind**:
    a ``"failure_kind": "none reported"`` marker beside the members, or a wrapper
    naming the state in words. Either would fail this re-validation outright,
    because the models set ``extra="forbid"`` and the field is an enum — so the
    export would stop being an export. The *words* for that state are
    ``_invocation_failure_kind``'s job on the listing, exactly as ADR-0186 §9 puts
    the words for an unrecorded origin on ``assistant decisions`` rather than in the
    artifact.
    """
    rows = (
        _claim("i-1", egress_call=True),
        _completion("i-2", outcome=ToolOutcome.FAILED),
        _completion(
            "i-3",
            outcome=ToolOutcome.SUCCEEDED,
            egress_call=True,
            cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.02"), currency="USD"),
        ),
    )
    _wire(monkeypatch, _ScriptedInvocationEngine(*rows))

    result = CliRunner().invoke(cli.app, ["export-invocations"])
    assert result.exit_code == 0

    document = json.loads(result.stdout)
    assert [row["invocation"]["id"] for row in document] == ["i-1", "i-2", "i-3"]
    # Every member of the join and no member of anything else. A document that grew
    # one key would re-validate only if the key were a field; one that lost a key
    # would lose a fact ADR-0004 §6's portability right is over.
    assert set(document[0]) == {"invocation", "tool", "capability", "egress_call"}
    assert set(document[0]["invocation"]) == {
        "id",
        "decision_id",
        "recorded_at",
        "completes",
        "outcome",
        "incurred_cost",
        "failure_kind",
    }
    assert document[1]["invocation"]["failure_kind"] is None, "the absence is rendered as one"

    revalidated = TypeAdapter(tuple[RecordedInvocation, ...]).validate_python(document)
    assert revalidated == rows


def test_the_exported_document_carries_no_recipient_account_endpoint_or_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0192 §9: the negatives reach "the **structured fields** it emits".

    The prose half is asserted over the listing; this is the other half, and it is
    the one a lane would break — a key is added by a model change nobody reads as a
    disclosure. ADR-0192 §2 keeps all four off the row by construction ("no account,
    no transport endpoint and no destination"), so what this pins is that the
    adapter emits the row's own keys and adds none of its own.
    """
    _wire(monkeypatch, _ScriptedInvocationEngine(_completion(egress_call=True)))

    result = CliRunner().invoke(cli.app, ["export-invocations"])
    assert result.exit_code == 0

    document = json.loads(result.stdout)
    keys = {key for row in document for key in row} | {
        key for row in document for key in row["invocation"]
    }
    for subject in _BARRED_SUBJECTS:
        assert not any(subject in key for key in keys), f"a {subject} key reached the document"


def test_the_export_writes_the_document_and_nothing_else_to_standard_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0186 §9's stream clause, over the third pair.

    Deliberately **without** the ``output`` fixture: what is under test is the
    stream, so the consoles are left following the runner's own ``sys.stdout`` and
    anything this command printed for a person would land in the artifact if the
    redirect were not there. ``json.loads`` over the whole of standard output is the
    assertion — a stray diagnostic makes the document unparseable rather than merely
    untidy, which is the failure mode the clause exists against.

    **The opener really writes to standard output here**, and that is what makes
    this a test of the redirect rather than of a silent fixture: over an opener that
    printed nothing, deleting ``contextlib.redirect_stdout`` from
    ``_export_invocations`` would leave the case green while a real client path's
    first log line corrupted a user's artifact. The sentinel is asserted **on
    standard error**, because §9's clause is that the diagnostics still reach a
    person — a redirect to nowhere would satisfy the stdout half and lose the
    message.
    """
    _wire(monkeypatch, _ScriptedInvocationEngine(_claim("i-1")), noise=_NOISE)

    result = CliRunner().invoke(cli.app, ["export-invocations"])

    assert result.exit_code == 0
    assert _NOISE in result.stderr, "the diagnostic was redirected to nowhere"
    assert json.loads(result.stdout) == [
        {
            "invocation": {
                "id": "i-1",
                "decision_id": "d-1",
                "recorded_at": "2026-03-03T11:00:00Z",
                "completes": None,
                "outcome": None,
                "incurred_cost": None,
                "failure_kind": None,
            },
            "tool": "t-1",
            "capability": "c-1",
            "egress_call": False,
        }
    ]


def test_an_export_the_engine_refuses_writes_no_document_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0192 §4: refused whole, never truncated, and never a partial artifact.

    ``export_invocations`` raises rather than truncating when the trail outgrows the
    contract limit (ADR-0085 §8c), and the adapter's job is to write **nothing** and
    say so on standard error. A partial artifact that looked complete is the one
    outcome ruled out, and it is the one a helpful adapter would produce.
    """
    engine = _ScriptedInvocationEngine(_claim("i-1"))
    refusal = OversizedValueError(
        "the invocation trail exceeds the contract limit", limit=10, size=99, field="result"
    )
    engine.export_raises = refusal
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["export-invocations"])

    assert result.exit_code != 0
    assert result.stdout == ""
    # Caught and said, rather than merely fatal: an uncaught exception also empties
    # standard output and also exits non-zero, and it leaves the user with a
    # traceback where the refusal's own words — the limit and the measured size —
    # are what tell them which knob to turn (ADR-0042 §7, ADR-0192 §4).
    assert result.exception is not refusal
    assert "the invocation trail exceeds the contract limit" in _flat(result.stderr)


# --- the error boundary, and the refusal that never reaches the engine -------


@pytest.mark.parametrize(
    "failure",
    [AuditError("the trail is not readable"), TransportError("the hub is not running")],
    ids=["audit", "transport"],
)
def test_a_listing_the_engine_cannot_answer_is_rendered_as_an_error(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    """The surface's usual boundary, over both classes this call can raise.

    **What it forecloses is a plausible kindness**: an adapter that rendered an
    unreadable trail as an empty listing would tell a user nothing ever ran, which
    is the one wrong answer this surface can give — ADR-0192 §4's page-silence
    clause is about a *bound*, not about a store that failed to answer.

    **A non-zero exit is not the assertion, and on its own it is barely one.**
    ``CliRunner`` reports a non-zero code for an *uncaught* exception too, so a
    driver with no ``except`` at all satisfies "the command failed" while the user
    meets a traceback instead of the rendered error and the controlled exit ADR-0042
    §7 requires. What separates the two is that the failure was **caught**: the
    message is on screen in this module's own rendering, and the injected exception
    did not escape the driver.
    """
    engine = _ScriptedInvocationEngine(_claim("i-1"))
    engine.listing_raises = failure
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["invocations"])
    rendered = _flat(output.getvalue())

    assert result.exit_code != 0
    assert result.exception is not failure, "the failure escaped the driver uncaught"
    assert str(failure) in rendered, "the failure was not rendered for the user"
    assert "Nothing recorded." not in rendered


@pytest.mark.parametrize("bad", ["0", "-1", "1.5", "x"], ids=["zero", "negative", "float", "text"])
def test_a_malformed_limit_is_refused_before_the_engine_is_reached(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """ADR-0192 §4: refused "locally and before any I/O".

    Refused during Typer's parameter parsing, so the assertion is that **no call was
    recorded** — the same negative control the conformance suite takes from the
    store's read log, expressed here as an engine nothing reached. A client shipping
    ``limit=0`` to the hub would be exactly the silently more permissive
    implementation ADR-0085 §9 forbids.
    """
    engine = _ScriptedInvocationEngine(_claim("i-1"))
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["invocations", "--limit", bad])

    assert result.exit_code != 0
    assert engine.calls == []


# --- §9: the end-to-end case, over rows a trail really holds -----------------


def _tool() -> ToolDefinition:
    """The declaration the seeded ruling is recorded over.

    Side-effecting with ``Idempotency.NONE``, which is what
    :data:`~tests.orchestration.assistant_engine_contract._RULED_TOOL` is and what
    makes ADR-0192 §1's consume admit exactly one claim under one authorisation —
    so the seeding below needs two rulings for two attempts, which is the shape the
    ADR is about rather than a limit on the fixture.
    """
    return ToolDefinition(
        id="smtp",
        capability="send_email",
        description="Send an email.",
        risk_level=RiskLevel.LOW,
        reversibility=Reversibility.REVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(),
        cost=ToolCost(basis=CostBasis.FREE),
        idempotency=Idempotency.NONE,
    )


def _allowed(decision_id: str) -> PermissionDecision:
    """One recorded ``ALLOW``, built through the sanctioned construction path."""
    return PermissionDecision.from_request(
        ActionRequest(tool=_tool(), parameters={"to": "a@example.com"}, step_id="step-1"),
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="within policy"),
        id=decision_id,
        decided_at=_AT,
    )


async def _seeded_trail() -> FakeAuditTrail:
    """A trail holding one open claim and one completed attempt, appended through the ledger.

    **Through the ledger and never by writing rows in**, because the id and the
    instant are the store's to mint and stamp (ADR-0192 §2) and a fixture reaching
    past that would be seeding a shape no conforming store can produce. Which is the
    point of this case: everything else in this module hands the adapter rows a test
    built, and ADR-0192 §9 requires one that hands it rows a trail holds.
    """
    trail = FakeAuditTrail()
    for decision_id in ("d-1", "d-2"):
        await trail.record(_allowed(decision_id))
    for decision_id in ("d-1", "d-2"):
        stored = await trail.get(decision_id)
        assert stored is not None
        claim = await trail.claim_invocation(decision=stored)
        if decision_id == "d-2":
            await trail.complete_invocation(
                claim_id=claim.id,
                outcome=ToolOutcome.SUCCEEDED,
                incurred_cost=ToolCost(basis=CostBasis.UNKNOWN),
            )
    return trail


async def test_the_adapter_lists_and_exports_rows_a_real_trail_holds(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0192 §9: the end-to-end case, "not discharged by an empty set".

    The clause is explicit that the surface group owes "an end-to-end test through
    it that lists and exports rows a seeded trail holds", and the reason is that
    every other case in this module scripts the engine — a renderer that dropped
    every row would pass an empty-set case and fail a user. So this one drives the
    real ``FakeAssistantEngine`` over a ``FakeAuditTrail`` filled through the ledger,
    which is the only path an invocation row exists on (ADR-0192 §2).

    **Both operations, over one trail**, because the pair is what discharges
    ADR-0004 §6's portability right: a listing a person reads and an artifact a
    program does.

    **Driven at the adapter's own two drivers rather than through ``CliRunner``**,
    and the reason is the trail rather than a preference. Seeding it needs an event
    loop, the commands call ``asyncio.run`` and so need a loop of their own, and the
    fake's ``SuspendableResource`` holds an ``asyncio.Lock`` that binds to the first
    loop it is used in — so a runner invocation over a trail seeded in another loop
    fails on the lock rather than on anything this module is about. What the Typer
    layer adds above these drivers is the parameter parsing and the exit code, and
    both are asserted by the scripted cases above; what is under test here is that
    the rendering and the artifact are over rows a store really produced.
    """
    trail = await _seeded_trail()
    engine = FakeAssistantEngine()
    engine.trail = trail
    monkeypatch.setattr(cli, "console", Console(file=output, force_terminal=False, width=400))

    assert await cli._drive_invocations(engine, limit=DEFAULT_PAGE_SIZE) == 0
    rendered = _flat(output.getvalue())
    rows = _rows_only(rendered)

    assert "3 row(s)" in rendered
    assert rows.count("call begun") == 2
    assert rows.count("call finished") == 1
    assert "Tool: smtp" in rendered
    assert "capability send_email" in rendered
    assert "Ended: succeeded" in rendered
    assert "Cost: not known" in rendered
    assert list(_claims(rendered)) == [], "the bars hold over rows a real trail produced"

    artifact = StringIO()
    assert await cli._drive_export_invocations(engine, artifact=artifact) == 0

    document = json.loads(artifact.getvalue())
    assert len(document) == 3
    revalidated = TypeAdapter(tuple[RecordedInvocation, ...]).validate_python(document)
    assert revalidated == await engine.export_invocations()
