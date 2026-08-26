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
    authorised_by: str | None = None,
) -> PermissionDecision:
    """One recorded ruling, built field by field.

    Hand-constructed rather than routed through
    :meth:`PermissionDecision.from_request`, because the row this milestone exists
    for cannot be produced through the factory at all (ADR-0184 §4) and building the
    other rows two different ways would make the comparison between them a
    comparison of two builders.

    ``authorised_by`` is a plain keyword here for the same reason, and it is what
    lets ADR-0193 §11's cases seed each of the three states *and* the combination
    ``AuditTrail.record`` refuses but the type still validates. Constructing that
    one through the store is impossible by design; constructing it here is the whole
    point, because this module's subject is a renderer handed rows over the wire by
    a hub it does not own.
    """
    return PermissionDecision(
        id=decision_id,
        ruling=PermissionRuling(outcome=outcome, reason=reason, authorised_by=authorised_by),
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

    **Wide enough that nothing wraps**, which is not merely convenient: ADR-0186
    §11's enumerating clause is about what one *span's* line carries, and a wrapped
    line cannot be told from two lines. :func:`_flat` is still what the prose cases
    assert through, because none of §7's clauses says anything about a line break.
    """
    buffer = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=buffer, force_terminal=False, width=400))
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


def test_an_explicit_limit_is_forwarded_and_bounds_the_page(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§9: ``assistant decisions`` "taking ``--limit``" — the value, not just its shape.

    The refusal case and the default case together leave one hole open: a command
    that parsed ``--limit`` and then passed ``DEFAULT_PAGE_SIZE`` regardless passes
    both, and silently hands the user a page they did not ask for. So this asserts
    the *value* reaching the operation and the page it produced, over a trail with
    more rows than the bound — a full page, which is also the one that has to say it
    is one, since a bound with no way to tell it was reached is a truncation the
    reader cannot see.
    """
    engine = _ScriptedDecisionEngine(_decision("d-new"), _decision("d-old"))
    _wire(monkeypatch, engine)

    result = CliRunner().invoke(cli.app, ["decisions", "--limit", "1"])
    assert result.exit_code == 0
    assert engine.calls == [("recent_decisions", {"limit": 1})]

    rendered = _flat(output.getvalue())
    assert "1 ruling(s)" in rendered
    assert "d-new" in rendered
    assert "d-old" not in rendered
    assert "Showing 1. Ask for more with --limit" in rendered
    assert "there is no total count" in rendered


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
    assert "2026-03-01 09:00:00.000000 UTC" in rendered
    assert "smtp-relay" in rendered
    assert "capability send_email" in rendered

    # The account, by identity. Never by reference (ADR-0148 §6).
    assert "work@example.com" in rendered
    assert "conn-0001" not in rendered

    # Every span, member by member and **on that span's own line**. Asserted per
    # line rather than per screen because two spans may legitimately agree on a
    # member — `bcc` and `to[0]` both describe a 17-code-point occurrence of one
    # recipient — so a whole-screen `"17 code points" in rendered` is satisfied by
    # either of them and passes while the other's extent goes unrendered.
    lines = [line.strip() for line in output.getvalue().splitlines()]
    # **Both** destination forms are named per span rather than accepted as "one of
    # the recipients on screen": a renderer that carried each span's supplied form
    # through but canonicalised every one of them to Alice would leave `to[1]`
    # reading "to alice@example.com … as supplied: bob@example.com", and a
    # whole-screen check still finds Bob in the canonical set and passes.
    for key, members in (
        (
            "bcc",
            (
                "to alice@example.com (smtp)",
                "as supplied: Alice@Example.com",
                "you composed it",
                "17 code points",
            ),
        ),
        ("body", ("names no destination", "you composed it", "42 code points")),
        (
            "subject",
            ("names no destination", "this system selected it", "9 code points", "tier personal"),
        ),
        (
            "to[0]",
            (
                "to alice@example.com (smtp)",
                "as supplied: Alice@Example.com",
                "this system selected it",
                "17 code points",
            ),
        ),
        (
            "to[1]",
            (
                "to bob@example.com (smtp)",
                "as supplied: bob@example.com",
                "this system selected it",
                "15 code points",
            ),
        ),
    ):
        matching = [line for line in lines if line.startswith(f"{key} — ")]
        assert len(matching) == 1, key
        for member in members:
            assert member in matching[0], (key, member)

        # **Neither** form on a span that carries no destination — checked on the
        # line, so a stray recipient leaking onto it fails rather than being absorbed
        # by the screen's other four.
        if "names no destination" in matching[0]:
            assert "as supplied" not in matching[0], key
            assert "@example.com" not in matching[0], key

    # One line per span and no sixth, and the tier on the one span that states one.
    assert len([line for line in lines if "code points" in line]) == len(binding.spans)
    assert [line for line in lines if "tier " in line] == [
        line for line in lines if line.startswith("subject — ")
    ]

    # The canonical set as `core` derived it: two members from three occurrences.
    derived = binding.canonical_destination_set
    assert len(derived) == 2
    for recipient in derived:
        assert recipient.canonical is not None
        assert f"{recipient.canonical} (smtp)" in rendered


def test_two_rulings_a_second_apart_render_as_two_instants(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: "the instant it was decided", and §7's bar on truncating part of a row.

    The rest of this surface renders an instant to the minute, which is the right
    grain for context — when a belief was last revised, when a question stops being
    answerable. A **record** cannot afford it, and the pair this catches is the one a
    reader most needs told apart: a ``CONFIRM`` and the ``ALLOW`` answering it are
    typically seconds apart, so at ``%H:%M`` the two rows carry one instant printed
    twice. That is a history internally consistent and chronologically false, which
    is the reading ADR-0021 §4 wrote its ordering rule against, and it hides
    ADR-0186 §2's own ordering key.

    Three rows, pairwise distinct at three different grains — a minute apart, a
    second apart, and a microsecond apart — so a renderer that keeps seconds but
    drops the fraction fails here too rather than passing a coarser version of the
    same case.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-3", at=_AT.replace(second=59, microsecond=500_000)),
        _decision("d-2", at=_AT.replace(second=59)),
        _decision("d-1", at=_AT.replace(second=1)),
    )
    stamps = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6} UTC", rendered)
    assert len(stamps) == 3
    assert len(set(stamps)) == 3
    assert "2026-03-01 09:00:59.500000 UTC" in stamps
    assert "2026-03-01 09:00:59.000000 UTC" in stamps
    assert "2026-03-01 09:00:01.000000 UTC" in stamps


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


# --- ADR-0193 §11: what authorised an ALLOW, in three states ------------------

#: Every claim ADR-0193 §11's third clause bars the second state from making about
#: the grant it names — that it exists, is held by the store, is live, is unrevoked,
#: has not expired, was validated, or covers anything now — plus the near-synonyms a
#: renderer reaches for first. Matched on word boundaries, and asserted over the
#: **line** rather than the screen: the listing's footer legitimately says a row does
#: not claim "that a grant is current", so a screen-wide search would be answered by
#: the disclaimer and would stop testing the assertion.
_BARRED_OF_A_NAMED_GRANT: Final = (
    "exists",
    "existing",
    "held",
    "holds",
    "live",
    "unrevoked",
    "revoked",
    "expired",
    "expires",
    "validated",
    "valid",
    "verified",
    "checked",
    "covers",
    "covering",
    "current",
    "active",
    "still",
    "in force",
)


def _basis_lines(output: StringIO) -> list[str]:
    """Every ``Authorised by:`` line on screen, unwrapped, in the order rendered.

    The line rather than the screen is what §11's clauses are stated over, and the
    ``output`` fixture is 400 columns wide precisely so that one rendered line is one
    line of text.
    """
    return [_flat(line) for line in output.getvalue().splitlines() if "Authorised by:" in line]


def _basis_line(output: StringIO) -> str:
    """The one ``Authorised by:`` line on a single-row screen."""
    lines = _basis_lines(output)
    assert len(lines) == 1, lines
    return lines[0]


def test_an_allow_resting_on_the_users_own_answer_names_that_decision(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's first state: a decision of the user about *that* call.

    ``resolves`` set with ``authorised_by`` equal to it is ADR-0193 §6's route (a),
    "which keeps its existing shape exactly", and the row is entitled to say the
    user decided this call — because the confirmation it names *is* about this call
    (``AuditTrail.record`` compares the tool, the digest and the step before it will
    hold the pair).
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-answer", resolves="d-ask", authorised_by="d-ask"),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    assert "Authorised by: a decision you took about this call, recorded as d-ask" in rendered
    assert "standing authorisation" not in rendered
    assert "the policy's own rules" not in rendered


def test_an_allow_naming_a_standing_authorisation_says_that_and_nothing_more(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's second state, asserted as an equality because the clause is about *more*.

    "The second state asserts exactly what the row says and nothing more: that this
    decision names a standing authorisation." A containment assertion would pass on
    a line that said this **and** something further, which is the only failure the
    clause is about, so the whole line is pinned.
    """
    _listing(
        output, monkeypatch, _decision("d-1", authorised_by="g-1", binding=_binding(planned=False))
    )
    assert _basis_line(output) == (
        "Authorised by: a standing authorisation this ruling names, recorded as g-1 "
        "(what the row names, and no more)"
    )


def test_the_second_state_claims_nothing_about_the_grant_it_names(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's third clause, one assertion per barred claim.

    No surface states or implies that the named grant exists, is held by the store,
    is live, is unrevoked, has not expired, was validated, or covers anything now —
    ADR-0186 §8's first clause, which names a grant in terms, read on this fact. The
    bar on "was validated" holds even though ADR-0193 §6 makes ``record`` validate
    every route-(b) row it writes: a surface cannot tell a row written before that
    implementation from one written after, and what §6 makes true of the system is
    not a claim a renderer may make about the row in front of it.
    """
    _listing(
        output, monkeypatch, _decision("d-1", authorised_by="g-1", binding=_binding(planned=False))
    )
    line = _basis_line(output)
    for claim in _BARRED_OF_A_NAMED_GRANT:
        assert re.search(rf"\b{claim}\b", line, flags=re.IGNORECASE) is None, claim


def test_a_policy_granted_allow_states_the_policys_own_rules(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's third state: the policy's own rules, resting on no user decision.

    ADR-0021 §5's floor bars an auto-granted ``ALLOW`` only for a **non-empty**
    ``discloses``, so this row — a non-disclosing, known-cost action — is conforming
    and ordinary rather than a residual or an error, and forcing it into either
    other state would assert a user decision that was never taken.
    """
    _listing(output, monkeypatch, _decision("d-1", binding=_binding(planned=False)))
    assert _basis_line(output) == (
        "Authorised by: the policy's own rules, resting on no decision of yours"
    )


def test_the_third_state_is_rendered_as_a_fact_and_never_as_an_absence(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's eighth clause: never an omission, a blank, or a failure to record.

    ADR-0186 §7's three-origin-state discipline read on a second three-state fact,
    and the failure it names is a rendering a reader could mistake for either of the
    first two — a dash, an empty value, or a line saying nothing was written down.
    The row *was* recorded; what it records is that no decision of the user is what
    authorised the call.
    """
    _listing(output, monkeypatch, _decision("d-1", binding=_binding(planned=False)))
    line = _basis_line(output).lower()
    for absence in (
        "(none)",
        "(unknown)",
        "n/a",
        "\u2014",
        "not recorded",
        "no record",
        "unrecorded",
        "missing",
        "unset",
        "blank",
    ):
        assert absence not in line, absence


def test_a_refusal_and_a_question_say_nothing_about_what_authorised_them(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11 is scoped to an ``ALLOW``, and every other row renders exactly as before.

    That scope is also ``PermissionRuling``'s own rule: "a refusal rests on no
    authorisation, and a ``DENY`` — or a ``CONFIRM``, which is a question rather than
    an answer — citing one is incoherent". A basis line on either would be answering
    a question the row does not pose.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-deny", outcome=PermissionOutcome.DENY, reason="outside policy"),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    assert "Authorised by:" not in rendered
    assert _basis_lines(output) == []
    assert "refused" in rendered
    assert "asked" in rendered


def test_the_three_states_are_distinct_and_none_is_rendered_as_another(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's first clause: "each distinct from the other two and none rendered as any other".

    Asserted over one screen holding all three, because that is where the failure
    lives: two states that read alike are a distinction a reader cannot make, and a
    per-state case would pass on a pair of lines differing only in an id.
    """
    _listing(
        output,
        monkeypatch,
        _decision("d-answer", resolves="d-ask", authorised_by="d-ask"),
        _decision("d-standing", authorised_by="g-1", binding=_binding(planned=False)),
        _decision("d-policy", binding=_binding(planned=False)),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    lines = _basis_lines(output)
    assert len(lines) == 3
    assert len(set(lines)) == 3
    prose = [line.split(", recorded as ")[0] for line in lines]
    assert len(set(prose)) == 3, prose


def test_a_row_naming_an_authorisation_other_than_its_own_question_gets_no_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one combination the type admits, no trail can hold, and no state fits.

    ``AuditTrail.record`` refuses a *resolving* ``ALLOW`` whose ``authorised_by`` is
    not its own ``resolves``, which is what makes §11's three states total over every
    row a trail can return — the totality the section claims when it says "the
    discriminator is total because ``authorised_by`` and ``resolves`` are". The types
    alone are looser: this row validates, and the surface renders whatever the
    operation hands it, over the wire, from a hub the adapter does not own.

    **No state's claim is true of it**, so it is assigned none. It answers a
    confirmation about this call and rests on something that is not that
    confirmation, so the first state's claim is false; the second is conditioned on
    ``resolves`` unset, and widening it to cover this row would assign a state §11
    does not define for it; the third is false outright, because ``authorised_by`` is
    set. §11 rejects "no statement at all" for a *non-egress* ``ALLOW`` expressly
    because "the record already determines the answer" there — here it does not, and
    the line says so and names neither value as the basis.
    """
    _listing(
        output,
        monkeypatch,
        _decision("d-odd", resolves="d-ask", authorised_by="g-1"),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    assert _basis_line(output) == (
        "Authorised by: this row does not say — it answers one decision and names a "
        "different one as what authorised it, and nothing here guesses between them"
    )


def test_no_state_is_assigned_to_a_row_none_of_the_three_conditions_reaches(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the case above: none of §11's three renderings appears.

    An equality on the line pins what *is* said; this pins that none of the three
    states is said, which is the failure the clause is actually about — "each
    distinct from the other two and none rendered as any other" is unsatisfiable for
    a row the discriminator does not reach, and the repair is to render none of them
    rather than to pick the least wrong.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-odd", resolves="d-ask", authorised_by="g-1"),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    for state in (
        "a decision you took about this call",
        "a standing authorisation this ruling names",
        "the policy's own rules",
    ):
        assert state not in rendered, state
    assert "Answers the question: d-ask" in rendered


def test_a_resolving_row_carrying_no_authorisation_is_the_third_state(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11's third state is stated over ``authorised_by`` alone, and so is this row.

    The other combination ``AuditTrail.record`` refuses and the type admits. §11
    conditions the third state on "``authorised_by`` unset" and on nothing else, so
    the row's own letter puts it here — and the resolution relation it *does* carry
    is still rendered, by ADR-0186 §7's fifth clause, on its own line.
    """
    rendered = _listing(
        output,
        monkeypatch,
        _decision("d-answer", resolves="d-ask"),
        _decision("d-ask", outcome=PermissionOutcome.CONFIRM),
    )
    assert "Answers the question: d-ask" in rendered
    assert _basis_line(output) == (
        "Authorised by: the policy's own rules, resting on no decision of yours"
    )


def test_the_named_authorisation_is_neutralised_for_this_terminal(
    output: StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0186 §7's last clause over the one value this line interpolates.

    A :data:`~ai_assistant.core.types.DurableIdentifier` is non-blank, stripped and
    encodable and is constrained no further — issue #62 still holds the canonical
    syntax question — so an id reaching this adapter may carry Rich markup and
    control characters, and the line it lands in is adapter-authored text with a
    label sharing it. Escaping the markup and replacing the control character is
    what keeps the row a rendering of the record rather than a second line the
    record forged.
    """
    _listing(output, monkeypatch, _decision("d-1", authorised_by="g-1[red]\x1b[2Jwiped"))
    raw = output.getvalue()
    assert "\x1b" not in raw
    line = _basis_line(output)
    assert "g-1[red]" in line, (
        "unescaped markup is a style Rich consumes, leaving nothing on screen"
    )
    assert "\ufffd" in line


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
