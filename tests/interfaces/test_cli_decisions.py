"""The CLI audit surface: ADR-0186 §9's two commands, clause by clause.

ADR-0186 §11 puts a specific test plan on this lane, and it is written out clause
by clause rather than sampled — "a listing rendering only the deduplicated
destination set passes an origin-state test, a non-egress test and an export
round-trip", so an assertion that names the members it happens to check is exactly
the one that lets a member go unrendered. Every case below cites the clause it
discharges, and the two enumerating cases assert **every** member the clause names.

**Driven through a scripted engine rather than the canonical fake's own trail**,
for one reason and it is ADR-0184 §4's: an
:class:`~ai_assistant.core.types.OriginUnrecordedBinding` is *unproducible* through
``AuditTrail.record``, so a fake holding objects cannot be seeded with the row this
milestone exists for. What the engine hands back is under this module's control and
what is under test is the adapter's rendering of it, which is the whole of what
ADR-0186 §7 and §8 bind. The store's own read half is pinned in
``tests/permissions/test_audit.py``; the *operations*' order, refusals and legacy-row
tolerance are pinned in ``tests/orchestration/`` by the contract lane.

**§8's bars are weak tests and that is stated rather than hidden** (ADR-0186 §11).
No assertion over rendered text can prove a renderer never claims an event; what
these catch is the specific, likely regression — a status column reading "Sent"
beside an ``ALLOW`` — and the clause binds whether or not a test reaches it.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
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
    BoundAccount,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.interfaces import cli
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.wire import TransportError

if TYPE_CHECKING:
    from collections.abc import Sequence

#: When the seeded rulings were made. Fixed, so what a case asserts is the values'
#: rendering rather than the run's clock.
_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

#: A digest of the right shape. It is never expanded and never labelled as the
#: payload (ADR-0186 §8), so its only property under test is that it appears.
_DIGEST: Final = "d" * 64

_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT = "smtp://mail.example.com:587"

#: Every word for an event that ADR-0186 §8's third clause bars beside a ruling.
#: Matched on word boundaries, because "already" contains "read" and a substring
#: test would fail on prose that claims nothing.
_EVENT_WORDS: Final = ("sent", "delivered", "read", "transmitted", "emailed", "went")


# --- the subject -------------------------------------------------------------


def _tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """A declaration of the shape a recorded egress ruling embeds verbatim."""
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.LOW,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _span(  # noqa: PLR0913 — an occurrence's own members, and ADR-0186 §11 varies each
    argument: str,
    *,
    index: int | None = None,
    supplied: str | None = None,
    canonical: str | None = None,
    provenance: DiscloserProvenance = DiscloserProvenance.SYSTEM_SELECTED,
    extent: int = 13,
    tier: DataTier | None = None,
) -> EgressSpan:
    """One occurrence of the payload description, with or without a recipient."""
    destination = (
        None
        if canonical is None
        else EgressDestination(
            protocol=DestinationProtocol.SMTP,
            supplied=supplied if supplied is not None else canonical,
            canonical=canonical,
        )
    )
    return EgressSpan(
        argument=argument,
        index=index,
        provenance=provenance,
        extent=extent,
        tier=tier,
        destination=destination,
    )


def _binding(*, planned: bool, spans: Sequence[EgressSpan] | None = None) -> EgressBinding:
    """A whole binding of the shape a live ``send_email`` ruling records."""
    return EgressBinding(
        spans=tuple(spans) if spans is not None else (_span("to", canonical="a@example.com"),),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
        planned_with_external_content=planned,
    )


def _legacy_binding(spans: Sequence[EgressSpan] | None = None) -> OriginUnrecordedBinding:
    """The same three facts, from a row recorded before ADR-0181 §3 existed.

    Constructed directly, which is the *only* way to reach it in a test over a fake:
    ADR-0184 §4 makes ``AuditTrail.record`` refuse this shape and
    :meth:`PermissionDecision.from_request` unable to produce it, so it is only ever
    read out of a store — and this module's subject is the reader, not the store.
    """
    return OriginUnrecordedBinding(
        spans=tuple(spans) if spans is not None else (_span("to", canonical="a@example.com"),),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
    )


def _decision(  # noqa: PLR0913 — a record's fields, each of which some case varies
    decision_id: str,
    *,
    outcome: PermissionOutcome = PermissionOutcome.ALLOW,
    reason: str = "within policy",
    tool: ToolDefinition | None = None,
    at: datetime | None = None,
    binding: EgressBinding | OriginUnrecordedBinding | None = None,
    resolves: str | None = None,
) -> PermissionDecision:
    """One recorded ruling, built field by field.

    Hand-constructed rather than routed through
    :meth:`PermissionDecision.from_request`, because the row this milestone exists
    for cannot be produced through the factory at all (ADR-0184 §4) and building the
    other rows two different ways would make the comparison between them a
    comparison of two builders.
    """
    return PermissionDecision(
        id=decision_id,
        ruling=PermissionRuling(outcome=outcome, reason=reason),
        tool=tool if tool is not None else _tool(),
        parameters_digest=_DIGEST,
        decided_at=at if at is not None else _AT,
        egress_binding=binding,
        resolves=resolves,
    )


class _ScriptedDecisionEngine(FakeAssistantEngine):
    """A hub whose trail is whatever a case seeds, refusals included.

    ``FakeAssistantEngine`` is otherwise untouched, so what the adapter is handed is
    the contract's own shape. The two overrides do **not** re-implement ADR-0186
    §3's local refusal of ``limit``: the CLI refuses a malformed one during Typer's
    parameter parsing, before any engine exists, and the case below asserts exactly
    that by observing that no call was ever recorded.
    """

    def __init__(self, *recorded: PermissionDecision) -> None:
        """Create an engine over ``recorded``, in the order it will answer with."""
        super().__init__()
        #: The trail, already in ADR-0186 §2's order — the engine's guarantee, and
        #: not something the adapter may re-establish (golden rule 3).
        self.recorded: tuple[PermissionDecision, ...] = recorded
        #: Raised instead of answering ``recent_decisions``.
        self.listing_raises: BaseException | None = None
        #: Raised instead of answering ``export_decisions``.
        self.export_raises: BaseException | None = None

    async def recent_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """The first ``limit`` rows — §2's prefix property, held by construction."""
        self.calls.append(("recent_decisions", {"limit": limit}))
        if self.listing_raises is not None:
            raise self.listing_raises
        return self.recorded[:limit]

    async def export_decisions(self) -> tuple[PermissionDecision, ...]:
        """Every row, in the same order."""
        self.calls.append(("export_decisions", {}))
        if self.export_raises is not None:
            raise self.export_raises
        return self.recorded


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch) -> StringIO:
    """Redirect the CLI's Rich console to a buffer and return it.

    Wide, because ADR-0186 §7 obliges the *content* of a row and none of its clauses
    says anything about a line break; :func:`_flat` removes the wrapping that is
    left.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=120))
    return buffer


def _wire(monkeypatch: pytest.MonkeyPatch, engine: object) -> None:
    """Point the audit commands' startup at ``engine``.

    The seam is :func:`~ai_assistant.interfaces.cli._open_engine`, as it is for
    every other command on this surface (ADR-0084 §6).
    """

    async def _open() -> object:
        return engine

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _open)


def _flat(rendered: str) -> str:
    """The rendering with its line wrapping removed, so a case asserts sentences."""
    return " ".join(rendered.split())


def _listing(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, *recorded: PermissionDecision
) -> str:
    """Run ``assistant decisions`` over ``recorded`` and return the flattened screen."""
    _wire(monkeypatch, _ScriptedDecisionEngine(*recorded))
    result = CliRunner().invoke(cli.app, ["decisions"])
    assert result.exit_code == 0
    return _flat(output.getvalue())


# --- §9: the export is one faithful JSON document ----------------------------


def test_the_export_re_validates_and_the_legacy_row_carries_no_origin_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0186 §11's round-trip clause at the surface, both directions.

    "The JSON ``assistant export-decisions`` writes re-validates as
    ``tuple[PermissionDecision, ...]`` and compares equal to what the engine
    returned, with the legacy row's ``planned_with_external_content`` key absent in
    both directions."

    The absence *is* the state (ADR-0184 §3). An artifact carrying a friendly
    ``"origin": "not recorded"`` marker beside the members would fail this
    re-validation outright, because the models set ``extra="forbid"`` — so the
    export would no longer be an export, which is §9's deciding argument stated as a
    test rather than as prose.
    """
    rows = (
        _decision("d-1", binding=_binding(planned=True)),
        _decision("d-legacy", binding=_legacy_binding()),
        _decision("d-2", binding=None),
    )
    _wire(monkeypatch, _ScriptedDecisionEngine(*rows))

    result = CliRunner().invoke(cli.app, ["export-decisions"])
    assert result.exit_code == 0

    document = json.loads(result.stdout)
    assert [row["id"] for row in document] == ["d-1", "d-legacy", "d-2"]
    assert "planned_with_external_content" not in document[1]["egress_binding"]
    assert document[0]["egress_binding"]["planned_with_external_content"] is True

    revalidated = TypeAdapter(tuple[PermissionDecision, ...]).validate_python(document)
    assert revalidated == rows
    binding = revalidated[1].egress_binding
    assert isinstance(binding, OriginUnrecordedBinding)
    assert "planned_with_external_content" not in binding.model_dump(mode="json")


def test_the_export_writes_the_document_and_nothing_else_to_standard_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9: "one JSON document written to standard output … nothing else on that stream".

    Deliberately **without** the ``output`` fixture: what is under test is the
    stream, so the consoles are left following the runner's own ``sys.stdout`` and
    ``sys.stderr`` rather than a buffer that would make the claim true by
    construction.
    """
    _wire(monkeypatch, _ScriptedDecisionEngine(_decision("d-1", binding=_binding(planned=False))))

    result = CliRunner().invoke(cli.app, ["export-decisions"])
    assert result.exit_code == 0

    # The *whole* stream parses as one JSON document, which is the assertion §9's
    # clause reduces to: a byte of anything else on it — a heading, a progress line,
    # a warning, a stray log record — makes this raise rather than merely add noise.
    assert [row["id"] for row in json.loads(result.stdout)] == ["d-1"]
    assert result.stdout.endswith("]\n")
    assert result.stderr == ""


def test_a_failed_export_says_so_on_standard_error_and_writes_no_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9's stream clause on the failure path, which is where it earns its keep.

    A partial artifact that looked complete is the one outcome §9 rules out, and a
    diagnostic on standard output is how a helpful adapter produces one: the user's
    ``> trail.json`` would hold a sentence. Nothing reaches standard output at all,
    and the exit code says the command failed.
    """
    engine = _ScriptedDecisionEngine(_decision("d-1"))
    engine.export_raises = OversizedValueError(
        "the trail exceeds the contract limit", limit=1024, size=99999
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["export-decisions"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "the trail exceeds the contract limit" in _flat(result.stderr)


def test_an_unreachable_hub_is_reported_on_standard_error_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other error boundary: the hub the export could not even reach.

    ADR-0084 §3 keeps a transport failure legible as its own thing, and §9 keeps it
    off the artifact's stream. Both hold at once, which is what the ``to_stderr``
    parameter on the shared renderer is for.
    """

    async def _refuse() -> object:
        raise TransportError("no hub is listening")

    monkeypatch.setattr(cli, "load_settings", Settings)
    monkeypatch.setattr(cli, "configure_logging", lambda _settings: None)
    monkeypatch.setattr(cli, "_open_engine", _refuse)

    result = CliRunner().invoke(cli.app, ["export-decisions"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "not reachable" in _flat(result.stderr)


def test_an_empty_trail_exports_an_empty_array(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty record is an artifact, not an error and not an absent file."""
    _wire(monkeypatch, _ScriptedDecisionEngine())

    result = CliRunner().invoke(cli.app, ["export-decisions"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_the_bare_name_export_is_not_a_command() -> None:
    """§9's fourth clause: ``export`` is **reserved** for ADR-0004 §6's artifact.

    "No lane names a single-store export ``assistant export``" — which this ADR does
    not discharge (#1502). The reservation is only worth anything if something
    notices when it is spent, and a name is spent by being registered.
    """
    result = CliRunner().invoke(cli.app, ["export", "--help"])
    assert result.exit_code != 0


# --- §9: the listing's bound -------------------------------------------------


@pytest.mark.parametrize("bad", ["0", "-1", "9223372036854775808", "many"])
def test_a_malformed_limit_is_refused_before_any_engine_exists(
    output: StringIO, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """ADR-0186 §3, at this surface: refused **locally and before any I/O**.

    Zero is refused as well as a negative, a non-integer and ``2**63``, which is
    stricter than ADR-0085 §9's ``[0, 2**63)`` and is what ``AuditTrail.recent``
    itself requires — ADR-0186 §3 takes ``recent_grants``' warning that neither
    implementation may be silently more permissive. Asserted by observing that the
    engine recorded **no call**, which is the only way to see "before any I/O" from
    outside.
    """
    engine = _ScriptedDecisionEngine(_decision("d-1"))
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["decisions", "--limit", bad])
    assert result.exit_code == 2
    assert engine.calls == []


def test_the_listing_defaults_as_the_protocol_defaults(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: ``--limit`` "defaulting as the Protocol defaults".

    A second default in the adapter would be a paging bound the contract never
    stated, drifting the day the Protocol's moves.
    """
    engine = _ScriptedDecisionEngine(_decision("d-1"))
    _wire(monkeypatch, engine)

    assert CliRunner().invoke(cli.app, ["decisions"]).exit_code == 0
    assert engine.calls == [("recent_decisions", {"limit": DEFAULT_PAGE_SIZE})]


def test_an_empty_trail_lists_as_nothing_recorded(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty listing is an answer, and it claims nothing about liveness."""
    assert "Nothing recorded" in _listing(output, monkeypatch)


# --- §7: the three origin states ---------------------------------------------


def test_the_three_origin_states_render_as_three_distinct_things(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0186 §11: three origin states over three rows in **one** listing.

    "Asserting that the third state's rendering is distinct from the ``False``
    state's rather than merely present" — so the two lines are pulled out and
    compared, rather than each being checked for non-emptiness. A surface that
    printed the same sentence for both would pass every "is it there" assertion.

    §7 also bars the third state being rendered as ``False``, as "no", as an empty
    value or as an omission, so all three rows carry a "Planned over" line and the
    unrecorded one names the *record* rather than denying the fact.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-true", binding=_binding(planned=True)),
        _decision("d-false", binding=_binding(planned=False)),
        _decision("d-legacy", binding=_legacy_binding()),
    )
    lines = [line for line in rendered.split("Planned over:") if line][1:]
    assert len(lines) == 3

    rested, not_rested, unrecorded = (line.split("Ruled over")[0].strip() for line in lines)
    assert rested != not_rested != unrecorded
    assert unrecorded != rested
    assert "includes a record marked as resting on recorded external content" in rested
    assert "no record is marked as resting on recorded external content" in not_rested
    assert "not recorded" in unrecorded
    assert "before this assistant kept the origin of a call" in unrecorded
    assert "no record is marked" not in unrecorded


def test_the_unrecorded_state_is_never_rendered_as_the_false_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: the third state is never ``False``, "no", an empty value or an omission.

    The failure this catches is the cheap one — a renderer reaching for
    ``getattr(binding, "planned_with_external_content", False)`` — which produces a
    row indistinguishable from a genuine ``False`` and tells the user the opposite
    of the truth.
    """
    rendered = _listing(output, monkeypatch, _decision("d-legacy", binding=_legacy_binding()))
    assert "Planned over: not recorded" in rendered
    assert "no record is marked as resting on recorded external content" not in rendered
    assert "False" not in rendered


# --- §7: what a row renders, by enumeration ----------------------------------


def _rich_row() -> PermissionDecision:
    """ADR-0186 §11's enumerated fixture: **one** row carrying all four span shapes.

    "A span with a destination, a span with **none**, a span stating a ``tier``, and
    two spans naming one recipient by two arguments." ``bcc`` and ``to[0]`` are the
    two arguments naming ``alice@example.com``, so the canonical destination set
    deduplicates three destination-bearing occurrences down to two members — the
    difference between the set and the occurrences that ADR-0178 §7 renders both for.

    The spans are in the order :class:`~ai_assistant.core.types.EgressBinding`'s own
    validator requires: by argument, then by index with the indexless span first.
    """
    return _decision(
        "d-rich",
        outcome=PermissionOutcome.ALLOW,
        reason="within policy — [red]not markup[/]",
        tool=_tool("smtp-relay", capability="send_email"),
        binding=_binding(
            planned=True,
            spans=(
                _span(
                    "bcc",
                    canonical="alice@example.com",
                    supplied="Alice@Example.com",
                    provenance=DiscloserProvenance.USER_AUTHORED,
                    extent=17,
                ),
                _span("body", provenance=DiscloserProvenance.USER_AUTHORED, extent=42),
                _span("subject", extent=9, tier=DataTier.PERSONAL),
                _span(
                    "to",
                    index=0,
                    canonical="alice@example.com",
                    supplied="Alice@Example.com",
                    extent=17,
                ),
                _span("to", index=1, canonical="bob@example.com", extent=15),
            ),
        ),
    )


def test_a_row_renders_every_member_seven_names(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0186 §11's first enumerating clause, member by member.

    "It asserts, by enumeration rather than by sampling — the row's outcome, its
    reason, the instant it was decided, and the recorded ``ToolDefinition``'s
    identifier **and** its capability; the ``account_identity``; for **every** span
    its ``argument``, its ``index``, its ``provenance`` and its ``extent``, and its
    ``tier`` for the span that states one; both destination forms for the span that
    carries a destination and **neither** form for the span that does not; the
    ``core``-derived canonical set, read from the value rather than recomputed; and
    the payload description."

    The set is asserted against ``binding.canonical_destination_set`` itself rather
    than against a list written out here, because §7 requires it rendered "as `core`
    derived it" and a hand-written expectation would be this adapter's second
    derivation of the same fact wearing a test's clothes.
    """
    row = _rich_row()
    binding = row.egress_binding
    assert isinstance(binding, EgressBinding)
    rendered = _listing(output, monkeypatch, row)

    # The ruling itself: outcome, reason, instant, and the declaration's two names.
    assert "allowed" in rendered
    assert "within policy" in rendered
    assert "2026-03-01 09:00 UTC" in rendered
    assert "smtp-relay" in rendered
    assert "capability send_email" in rendered

    # The account, by identity. Never by reference (ADR-0148 §6).
    assert "work@example.com" in rendered
    assert "conn-0001" not in rendered

    # Every span: argument, index, provenance and extent, and the one tier.
    assert "bcc — to alice@example.com" in rendered
    assert "body — names no destination" in rendered
    assert "subject — names no destination" in rendered
    assert "to[0] — to alice@example.com" in rendered
    assert "to[1] — to bob@example.com" in rendered
    assert rendered.count("you composed it") == 2
    assert rendered.count("this system selected it") == 3
    for extent in (17, 42, 9, 15):
        assert f"{extent} code points" in rendered
    assert "tier personal" in rendered

    # Both forms where the occurrence carries one, and neither where it does not.
    assert rendered.count("as supplied: Alice@Example.com") == 2
    assert "as supplied: bob@example.com" in rendered
    assert "body — names no destination; you composed it; 42 code points" in rendered
    assert "subject — names no destination; this system selected it; 9 code points" in rendered

    # The canonical set as `core` derived it: two members from three occurrences.
    members = binding.canonical_destination_set
    assert len(members) == 2
    for member in members:
        assert member.canonical is not None
        assert f"{member.canonical} (smtp)" in rendered


def test_a_value_carrying_markup_is_neutralised_on_render(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7's last clause, in the opposite direction: every value is inserted as data.

    ADR-0042 §4 is target-specific, and being read from an append-only store relaxes
    nothing: ``reason`` is policy-authored text, a ``supplied`` destination form is a
    string a model produced, and ``argument`` is a caller-influenced key (ADR-0150
    §13). Markup surviving *literally* is the proof it was escaped — had Rich
    interpreted it, the tag would have vanished from the screen and taken a colour
    with it.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision(
            "d-hostile",
            reason="wipe\x1b[2J and [red]shout[/red]",
            binding=_binding(
                planned=False,
                spans=(
                    _span(
                        "[bold]to[/]",
                        supplied="[red]shout[/red]",
                        canonical="c@example.com",
                    ),
                ),
            ),
        ),
    )
    assert "[red]" in rendered  # markup is shown literally, not interpreted as colour
    assert "[bold]to[/]" in rendered
    assert "\x1b[2J" not in rendered


def test_a_non_egress_row_asserts_nothing_about_recipients(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0186 §11 and §7's fourth clause: a ``None`` binding renders none of it.

    "For a non-egress row, that no recipient, account or origin is rendered."
    ``None`` means the request was not an egress call (ADR-0150 §1) and continues to
    mean exactly that — so this is not a claim that the call transmits nothing or
    reaches nobody, and the row says nothing about recipients at all, which is what
    it is entitled to say.
    """
    rendered = _listing(output, monkeypatch, _decision("d-plain", binding=None))
    assert "allowed" in rendered
    assert "Account:" not in rendered
    assert "Planned over:" not in rendered
    assert "Ruled over these recipients" not in rendered
    assert "work@example.com" not in rendered


# --- §7: the resolution relation ---------------------------------------------


def test_an_unresolved_confirm_is_rendered_as_neither_allowed_nor_denied(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0186 §11 and §7's fifth clause, over a page holding the question alone.

    "For an unresolved ``CONFIRM``, that it is rendered as neither allowed nor
    denied." A resolution may lie outside a bounded page, so its absence is a fact
    about the **page** — and the footer says that in the one place a reader would
    otherwise infer an outcome from silence. Nothing renders it as expired or as
    awaiting anything either.
    """
    rendered = _listing(output, monkeypatch, _decision("d-ask", outcome=PermissionOutcome.CONFIRM))
    assert "asked" in rendered
    assert "a question put to you" in rendered
    assert "allowed" not in rendered
    assert "refused" not in rendered
    assert re.search(r"\bexpired\b", rendered) is None
    assert "An answer can fall outside this page" in rendered


def test_a_resolving_decision_names_the_question_it_answers(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7's fifth clause, the other half: the relation is rendered from the rows.

    "A decision whose ``resolves`` is set names the ``CONFIRM`` it answers, and a
    ``CONFIRM`` is rendered as a question that was asked." Naming requires the
    question's own id to be on screen too, which is why the row prints it.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-answer", resolves="d-ask"),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    assert "Answers the question: d-ask" in rendered
    assert "asked" in rendered


# --- §8: one test per bar ----------------------------------------------------


def test_a_row_whose_tool_and_grant_are_gone_still_renders_as_a_ruling(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's first bar: no surface derives **liveness** from history.

    "A row states that a ruling was made, never that it still stands, that a grant is
    current, that an account is connected, or that a definition is still registered
    under the identifier the row records." The tempting rendering is a permissions
    screen — a list of things the assistant "can" do — and a retired tool id is what
    makes that reading visibly false: the row keeps rendering the declaration
    ADR-0021 §1 embedded verbatim, from the row and not from a registry that no
    longer holds it.

    **Three of the four readings are refused in words rather than by a fixture**, and
    that is stated rather than papered over: a grant, a connection and a registry are
    *other stores*, and this surface reads none of them (ADR-0186 §1 — neither
    operation "reads any other store"), so no fixture available here can put a
    revoked grant or a dead connection into a row. What the surface can do about a
    reading it cannot disprove is decline to invite it, which is what the footer is
    and why each of the four is named in it separately.
    """
    engine = _ScriptedDecisionEngine(_decision("d-1", tool=_tool("retired-tool")))
    _wire(monkeypatch, engine)
    assert CliRunner().invoke(cli.app, ["decisions"]).exit_code == 0
    rendered = _flat(output.getvalue())

    assert "retired-tool" in rendered
    assert "does not say the ruling still stands" in rendered
    assert "that a grant is current" in rendered
    assert "that an account is still connected" in rendered
    assert "still registered under the identifier above" in rendered


def test_a_row_is_never_rendered_as_covering_another_request(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's second bar: no surface derives **authorisation** from history.

    "No surface computes, displays or implies ``PermissionDecision.authorises``, and
    none presents a row as a permission that covers any request other than the one it
    names." The fixture is a resolved ``ALLOW`` beside a second, differing request —
    same tool, different arguments, hence a different digest — and the assertion is
    that the adapter never asked the question: ``authorises`` takes an
    ``ActionRequest``, the adapter holds none, and nothing about the second request
    reaches the screen.
    """
    covered = _decision("d-allow", resolves="d-ask")
    other = _decision("d-other").model_copy(update={"parameters_digest": "e" * 64})
    rendered = _listing(output, monkeypatch, covered, other)

    assert _DIGEST in rendered
    assert "e" * 64 in rendered
    assert "authorises" not in rendered
    assert "covers" not in rendered
    assert "permits" not in rendered


def test_an_allow_for_a_call_that_never_ran_uses_no_event_wording(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's third bar: no surface presents a decision as a **transmission**.

    The trail bounds resolutions and not executions (ADR-0021 §4), so a resolved
    ``ALLOW`` says a call was permitted and says nothing about whether, or how many
    times, it ran. The fixture is exactly that — an ``ALLOW`` for a call that was
    never invoked — and the specific regression is a status column reading "Sent"
    beside it. #1503 carries the consequence for milestone 24's exit wording.

    Word boundaries rather than substrings, because "already" contains "read" and
    prose that claims nothing would otherwise fail.
    """
    rendered = _listing(
        output, monkeypatch, _decision("d-allow", resolves="d-ask", binding=_binding(planned=False))
    )
    assert "allowed" in rendered
    assert "does not say the call ever ran" in rendered
    for word in _EVENT_WORDS:
        assert re.search(rf"\b{word}\b", rendered, flags=re.IGNORECASE) is None, word


def test_the_digest_is_rendered_as_a_digest_and_never_as_the_payload(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's fourth bar: no surface renders content the row does not carry.

    ``parameters_digest`` "is a digest and is never rendered as, labelled as, or
    expanded into the payload". The row carries no arguments to expand — that is the
    point of a digest binding the payload without storing it (ADR-0021 §1) — so the
    failure would be a *label* claiming otherwise, and the line says in words what
    the value is and what the record does not hold.
    """
    rendered = _listing(output, monkeypatch, _decision("d-1", binding=_binding(planned=False)))
    assert f"Digest: {_DIGEST} (a digest, never the arguments)" in rendered
    assert "A digest binds the arguments a ruling was taken over" in rendered
    assert "The arguments themselves are not in this record and are not shown" in rendered


def test_a_tools_tier_reach_is_not_rendered_beside_its_recipients(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's fifth bar: ``reads``, ``writes`` and ``discloses`` are ceilings, not measures.

    The fixture is built to tempt it — a declaration whose ``discloses`` is wider
    than the recipient list the ruling was actually taken over — because a surface
    printing both would be asserting that this call transmitted ``FINANCIAL`` data
    to one address, which is the measurement ADR-0016 §3 declines to offer. The
    tiers are absent from the rendering entirely, which is the strongest available
    form of "not presented as a measurement".

    ``tier personal`` on a **span** is a different fact and stays: that one is
    per-occurrence and is ADR-0178 §7's, which is why the assertion is over the tier
    the *declaration* names and not over the word.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision(
            "d-wide",
            tool=_tool(
                discloses=(DataTier.PERSONAL, DataTier.SECRET),
                reads=(DataTier.OPERATIONAL,),
            ),
            binding=_binding(planned=False),
        ),
    )
    assert "a@example.com" in rendered
    assert "secret" not in rendered.lower()
    assert "operational" not in rendered.lower()
    assert "discloses" not in rendered.lower()
    assert "reads" not in rendered.lower()
    assert "writes" not in rendered.lower()


def test_a_true_origin_is_not_rendered_as_a_detection(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's sixth bar: the origin is not a detection, a score or a warning (ADR-0181 §7).

    "None suppresses, reorders or de-emphasises any part of §7 on the strength of
    it" — so the ``True`` row is compared against the ``False`` row it is otherwise
    identical to, and the two must render the same floor in the same order with only
    the origin sentence differing. A surface that added a warning banner, or dropped
    the recipients behind one, would pass an assertion that only looked for words.
    """
    alarming = _listing(output, monkeypatch, _decision("d-true", binding=_binding(planned=True)))
    for word in ("suspicious", "malicious", "risk", "warning", "danger", "detected", "score"):
        assert word not in alarming.lower(), word

    output.truncate(0)
    output.seek(0)
    calm = _listing(output, monkeypatch, _decision("d-true", binding=_binding(planned=False)))

    assert (
        alarming.replace(
            "which includes a record marked as resting on recorded external content",
            "in which no record is marked as resting on recorded external content",
        )
        == calm
    )


def test_a_row_carries_no_answer_control_and_composes_no_confirmation(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8's last bar: no surface renders a row as a confirmation.

    "It composes no ``Confirmation``, offers no answer or approval control on a
    history row, and routes no answer through this surface." The fixture is the one
    a card cannot even be built from — an unresolved ``CONFIRM`` whose binding
    records no origin — because ADR-0184 §8 forbids a ``ConfirmationEgress`` for an
    unrecorded origin and that model's ``planned_with_external_content`` is required
    with no default, so composing the card would demand the fabrication ADR-0184
    exists to avoid.

    Asserted against the shipped card's own wording, so a renderer that reached for
    :func:`~ai_assistant.interfaces.cli._render_confirmation` fails here rather than
    in a user's terminal, and against the runner having been given no input at all —
    a prompt would have raised rather than silently defaulted.
    """
    engine = _ScriptedDecisionEngine(
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM, binding=_legacy_binding())
    )
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["decisions"])
    assert result.exit_code == 0
    rendered = _flat(output.getvalue())

    assert "Confirmation required" not in rendered
    assert "Proceed?" not in rendered
    assert "[y/N]" not in rendered
    assert "assistant resume" not in rendered
    assert [call[0] for call in engine.calls] == ["recent_decisions"]


# --- the error boundary on the listing ---------------------------------------


def test_an_unreadable_trail_is_reported_and_no_row_is_invented(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The listing's boundary: a refusal is a refusal, never an empty page.

    ``AuditError`` reaches the user as itself. Rendering it as "Nothing recorded"
    would be the one dishonest line available here — a store that could not be
    consulted reported as a store holding nothing.
    """
    engine = _ScriptedDecisionEngine(_decision("d-1"))
    engine.listing_raises = AuditError("the trail could not be opened")
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["decisions"])
    assert result.exit_code == 1
    rendered = _flat(output.getvalue())
    assert "the trail could not be opened" in rendered
    assert "Nothing recorded" not in rendered
