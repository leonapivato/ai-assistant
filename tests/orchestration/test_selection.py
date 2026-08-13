"""The selection rule itself: the ordering, the filter, and the snapshot (ADR-0144).

ADR-0144 §8 is the obligations list this file discharges, and it is written the
way it is because the ADR's own review found the failure it names: key 3 was
ordered *"under `DataTier`'s declaration order"* by symmetry with keys 1 and 2,
which inverted the disclosure comparison **in the safety direction**. So the
tests here pin *directions*, not merely shapes — a test that only asserted "the
tiers are compared" would have passed against the wrong one.

What is here is everything observable without a pipeline: the six keys deciding
in isolation, the lexicographic composition, the eligibility filter that binds
ahead of all of them, and the construction-time snapshot. What can only be seen
by running the stage — that nothing is committed, that no ruling is requested —
is in ``test_runner.py``, which is where the durable half of ADR-0145 §13's
evidence lives.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.orchestration.selection import (
    _COST_ORDER,
    _TIER_ORDER,
    Preference,
    eligible_candidates,
    select,
    selection_key,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

CAPABILITY = "send_email"

#: A schema the two-field parameter mapping below satisfies, and which refuses
#: an argument it does not name — so a candidate declaring it is eligible for
#: ``FITTING`` and ineligible for anything else.
STRICT_SCHEMA = {
    "type": "object",
    "properties": {"to": {"type": "string"}},
    "required": ["to"],
    "additionalProperties": False,
}

FITTING = {"to": "someone@example.com"}


def tool(tool_id: str = "smtp", **overrides: object) -> ToolDefinition:
    """The neutral declaration every test here perturbs one field of.

    Least severe on every key, so a candidate built by overriding exactly one
    field differs from this one on exactly that key — which is what makes "the
    key decides in isolation" a property the test actually holds constant rather
    than one it hopes for.
    """
    fields: dict[str, object] = {
        "id": tool_id,
        "capability": CAPABILITY,
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


def preferred(*candidates: ToolDefinition, preference: Sequence[str] | Preference = ()) -> str:
    """The id ``select`` returns for ``candidates``, asserting it chose one."""
    snapshot = preference if isinstance(preference, Preference) else Preference(preference)
    chosen = select(candidates, snapshot).tool
    assert chosen is not None, "expected a unique minimum, got a tie"
    return chosen.id


# --- the two order tables ------------------------------------------------


def test_the_tier_table_runs_least_sensitive_first() -> None:
    """Key 3's direction, pinned by name (ADR-0144 §2, §8).

    The table is *derived* from ``DataTier``'s declaration order so that a member
    inserted in the middle cannot be given a contradicting rank; this is what
    pins the derivation to the direction ADR-0144 §2 actually decided, which is
    the **reverse** of that declaration order. Asserting the reversal as well as
    the literal makes the test fail for the right reason if ``DataTier`` is ever
    reordered.
    """
    assert _TIER_ORDER == (DataTier.OPERATIONAL, DataTier.PERSONAL, DataTier.SECRET)
    assert tuple(reversed(tuple(DataTier))) == _TIER_ORDER
    assert frozenset(_TIER_ORDER) == frozenset(DataTier)


def test_the_cost_table_runs_free_then_per_call_then_unknown() -> None:
    """Key 4's order, and that it covers the enum (ADR-0144 §2).

    Coverage is asserted because the ranking looks a member up in this tuple: a
    ``CostBasis`` member missing from it would raise rather than rank, on a path
    every tool call takes.
    """
    assert _COST_ORDER == (CostBasis.FREE, CostBasis.PER_CALL, CostBasis.UNKNOWN)
    assert frozenset(_COST_ORDER) == frozenset(CostBasis)


# --- each key, deciding in isolation (ADR-0144 §8) -----------------------


def test_key_1_prefers_the_lower_risk_level() -> None:
    """Risk leads, ascending under ``RiskLevel``'s declaration order."""
    assert preferred(tool("risky", risk_level=RiskLevel.HIGH), tool("safe")) == "safe"


def test_key_2_prefers_the_more_reversible_candidate() -> None:
    """Reversibility second, with everything above it equal."""
    assert (
        preferred(tool("permanent", reversibility=Reversibility.IRREVERSIBLE), tool("undoable"))
        == "undoable"
    )


def test_key_3_prefers_disclosing_nothing() -> None:
    """The empty tuple is least of all (ADR-0144 §2)."""
    assert preferred(tool("leaky", discloses=(DataTier.OPERATIONAL,)), tool("sealed")) == "sealed"


def test_key_3_prefers_the_less_sensitive_tier_which_is_the_reverse_of_the_stored_order() -> None:
    """``(OPERATIONAL,)`` < ``(PERSONAL,)`` < ``(SECRET,)`` — the **direction** (§8).

    This is the assertion ADR-0144 §8 singles out, and the one an implementation
    taken "by symmetry with keys 1 and 2" fails: ``DataTier`` is declared
    most-sensitive-first (ADR-0016 §3), so reading key 3 off the declaration order
    selects the ``SECRET``-disclosing candidate. Each pair is asserted separately
    rather than through one three-way race, so a partial inversion cannot hide
    behind a transitive answer.
    """
    operational = tool("ops", discloses=(DataTier.OPERATIONAL,))
    personal = tool("pii", discloses=(DataTier.PERSONAL,))
    secret = tool("vault", discloses=(DataTier.SECRET,))

    assert preferred(operational, personal) == "ops"
    assert preferred(personal, secret) == "pii"
    assert preferred(operational, secret) == "ops"
    # And the stored order really is the other way round, which is what makes the
    # three assertions above a statement about direction rather than about luck:
    # a key taken off the declaration order would have selected `vault`.
    declaration = tuple(DataTier)
    assert declaration.index(DataTier.SECRET) < declaration.index(DataTier.OPERATIONAL)


def test_key_3_prefers_a_proper_prefix_over_its_own_extension() -> None:
    """A shorter reach wins against the same reach plus one more tier (§2).

    ``discloses`` is stored most-sensitive-first and de-duplicated (ADR-0016 §3),
    so ``(PERSONAL, OPERATIONAL)`` is the canonical form of the wider reach and
    ``(PERSONAL,)`` is a proper prefix of it under the comparison key.
    """
    narrow = tool("narrow", discloses=(DataTier.PERSONAL,))
    wide = tool("wide", discloses=(DataTier.PERSONAL, DataTier.OPERATIONAL))

    assert preferred(narrow, wide) == "narrow"


def test_key_3_lets_the_most_sensitive_tier_dominate_a_longer_but_tamer_reach() -> None:
    """``(SECRET,)`` loses to ``(PERSONAL, OPERATIONAL)`` (§2).

    Elementwise comparison makes the first tier decide, which is the other of the
    two readings of "discloses less" — and the two together are why the key is a
    sequence comparison rather than a count.
    """
    one_secret = tool("vault", discloses=(DataTier.SECRET,))
    two_tamer = tool("broad", discloses=(DataTier.PERSONAL, DataTier.OPERATIONAL))

    assert preferred(one_secret, two_tamer) == "broad"


def test_key_4_prefers_free_then_per_call_then_unknown() -> None:
    """Cost basis fourth, each step asserted (ADR-0144 §2)."""
    free = tool("free")
    metered = tool(
        "metered", cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(1), currency="USD")
    )
    opaque = tool("opaque", cost=ToolCost(basis=CostBasis.UNKNOWN))

    assert preferred(free, metered) == "free"
    assert preferred(metered, opaque) == "metered"
    assert preferred(free, opaque) == "free"


def test_key_4_never_compares_amounts_across_or_within_a_currency() -> None:
    """Two ``PER_CALL`` candidates are equal whatever they cost (ADR-0144 §2, §8).

    Comparing amounts is the obvious refinement and it cannot be made total —
    ADR-0016 §4 rules cross-currency comparison out of scope, so an amount key
    could rank only within a currency, which is the partial comparison §1 forbids
    and whose transitivity failure would surface as name-order dependence.
    """
    cheap = tool(
        "cheap", cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(1), currency="USD")
    )
    dear = tool(
        "dear", cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(9999), currency="USD")
    )
    foreign = tool(
        "foreign", cost=ToolCost(basis=CostBasis.PER_CALL, amount=Decimal(3), currency="EUR")
    )

    assert selection_key(cheap, Preference()) == selection_key(dear, Preference())
    assert selection_key(cheap, Preference()) == selection_key(foreign, Preference())
    # Equal under the whole key with an empty preference, so it is a tie and not
    # a silent win for whichever was listed first.
    assert select((cheap, dear, foreign), Preference()).tied == ("cheap", "dear", "foreign")


def test_key_5_prefers_the_lower_declared_latency() -> None:
    """Latency fifth, ascending among candidates that declare one (ADR-0144 §3)."""
    quick = tool("quick", latency=timedelta(milliseconds=10))
    slow = tool("slow", latency=timedelta(seconds=5))

    assert preferred(quick, slow) == "quick"


def test_key_5_sorts_an_undeclared_latency_after_every_declared_one() -> None:
    """Absence sorts **last**, not first and not incomparably (ADR-0144 §3, §8).

    First would reward omission — an author who declared nothing would outrank
    one who declared a real number — which inverts the incentive ADR-0016 §1
    built the type around. Incomparable is forbidden outright by §1, because a
    key that declines to compare some pairs makes the composed ordering
    non-transitive.
    """
    silent = tool("silent")
    assert silent.latency is None
    for declared in (timedelta(microseconds=1), timedelta(days=365)):
        assert preferred(tool("stated", latency=declared), silent) == "stated"


def test_key_6_orders_by_position_in_the_preference_sequence() -> None:
    """The deployment's sequence breaks a tie keys 1-5 left (ADR-0144 §4)."""
    assert preferred(tool("a"), tool("b"), preference=("b", "a")) == "b"
    assert preferred(tool("a"), tool("b"), preference=("a", "b")) == "a"


def test_key_6_sorts_an_unnamed_candidate_after_every_named_one() -> None:
    """A candidate the sequence does not name loses to one it does (ADR-0144 §4)."""
    assert preferred(tool("named"), tool("unnamed"), preference=("named",)) == "named"


# --- the lexicographic composition (ADR-0144 §1, §8) ---------------------


def test_an_earlier_key_overrides_every_later_one_that_disagrees() -> None:
    """Risk settles it however loudly latency, cost and preference object.

    The candidate the severity block prefers is worse on **every** key below it
    and is named nowhere in the preference sequence, and it still wins. This is
    what "applied lexicographically" means and it is the property a scoring
    implementation — weights summed rather than keys compared — would lose.
    """
    safe_but_slow = tool(
        "safe",
        risk_level=RiskLevel.LOW,
        cost=ToolCost(basis=CostBasis.UNKNOWN),
    )
    risky_and_quick = tool(
        "risky",
        risk_level=RiskLevel.HIGH,
        cost=ToolCost(basis=CostBasis.FREE),
        latency=timedelta(milliseconds=1),
    )

    assert preferred(safe_but_slow, risky_and_quick, preference=("risky",)) == "safe"


def test_a_later_key_decides_when_every_earlier_one_ties() -> None:
    """Latency decides between two candidates equal on the severity block."""
    quick = tool("quick", latency=timedelta(seconds=1))
    slow = tool("slow", latency=timedelta(seconds=2))

    assert preferred(quick, slow) == "quick"


def test_the_preference_cannot_promote_a_candidate_the_severity_block_ranks_lower() -> None:
    """Key 6 is consulted **only** at key 6 (ADR-0144 §4, §8).

    This is the clause that makes the knob safe rather than a ranker in
    disguise: every candidate the preference can select is equal to every other
    on keys 1 through 3 — precisely the axes ADR-0021 §5 constrains a conforming
    policy over — so no value of the sequence moves a candidate past one the
    ordering prefers on severity.
    """
    tame = tool("tame")
    severe = tool("severe", risk_level=RiskLevel.CRITICAL, discloses=(DataTier.SECRET,))

    assert preferred(tame, severe, preference=("severe", "tame")) == "tame"
    assert preferred(tame, severe, preference=("severe",)) == "tame"


# --- order independence and ties (ADR-0144 §1, §6, §8) -------------------


def test_the_same_candidate_is_selected_from_every_presentation_of_the_set() -> None:
    """Transitivity, which §8 names as the guarantee most easily lost.

    ``find``'s own ordering is by ``id`` and means nothing (ADR-0016 §5), so a
    rule whose answer moved with the presentation would be a rule ordering by
    name — the thing ADR-0037 §1 refused. The set below is deliberately spread
    across four different keys, so a non-transitive composition has somewhere to
    show.
    """
    candidates = (
        tool("a", risk_level=RiskLevel.MEDIUM),
        tool("b", discloses=(DataTier.OPERATIONAL,)),
        tool("c", latency=timedelta(seconds=3)),
        tool("d", cost=ToolCost(basis=CostBasis.UNKNOWN)),
        tool("e", latency=timedelta(seconds=1)),
    )
    presentations = (
        candidates,
        tuple(reversed(candidates)),
        (candidates[2], candidates[4], candidates[0], candidates[3], candidates[1]),
        (candidates[3], candidates[1], candidates[4], candidates[2], candidates[0]),
    )

    chosen = {preferred(*presentation) for presentation in presentations}

    assert chosen == {"e"}


def test_a_tie_selects_nothing_and_names_the_tied_candidates() -> None:
    """The minimum must be *unique*, not merely first (ADR-0144 §1, §6).

    "Take the first minimum found" would hand the answer to whichever order
    ``find`` listed, which is by ``id`` — the alphabetical accident ADR-0037 §1
    refused to decide side effects on.
    """
    outcome = select((tool("b-sender"), tool("a-sender"), tool("c-sender")), Preference())

    assert outcome.tool is None
    assert outcome.tied == ("a-sender", "b-sender", "c-sender")


def test_a_tie_names_only_the_candidates_that_actually_tied() -> None:
    """A candidate the ordering ranked below the tie is not reported as tied."""
    outcome = select((tool("a"), tool("b"), tool("worse", risk_level=RiskLevel.HIGH)), Preference())

    assert outcome.tool is None
    assert outcome.tied == ("a", "b")


def test_a_preference_naming_one_tied_candidate_resolves_the_tie() -> None:
    """§6's residue is what is left when the user has expressed no preference."""
    tied = (tool("alpha"), tool("beta"))

    assert select(tied, Preference()).tool is None
    assert preferred(*tied, preference=("beta",)) == "beta"


def test_selecting_from_an_empty_set_is_the_callers_to_dispose_of() -> None:
    """Emptiness means two different things and only the caller knows which.

    ``find`` returning nothing is ``NO_CAPABLE_TOOL``; the fit filter emptying a
    non-empty set is ``INVALID_PARAMETERS`` (ADR-0145 §4). Answering "no
    selection" for both would let the runner report the falsehood ADR-0014 §4's
    legal-skip table exists to prevent.
    """
    with pytest.raises(ValueError, match="at least one candidate"):
        select((), Preference())


# --- the preference snapshot (ADR-0144 §4, §8) ---------------------------


def test_a_duplicated_id_is_refused_where_the_sequence_is_supplied() -> None:
    """``(a, a, b)`` is refused rather than resolved (ADR-0144 §4, §8).

    Taking the first occurrence and taking the last are both conforming readings
    that select different tools from one candidate set, which is the
    order-dependence §1 forbids. Defining one would close it; refusing closes it
    better, on ADR-0016 §1's posture that a malformed declaration does not load.
    """
    with pytest.raises(ValueError, match="more than once"):
        Preference(("tool-a", "tool-a", "tool-b"))


def test_an_unregistered_id_is_accepted_and_matches_nothing() -> None:
    """A sequence is not a second registration manifest (ADR-0144 §4, §8).

    A registry is populated at startup from whatever registers (ADR-0016 §6), so
    an id may name a tool this run does not hold. Refusing on that would fail a
    deployment for naming a preference it turned out not to need.
    """
    snapshot = Preference(("absent", "present"))

    assert snapshot.ids == ("absent", "present")
    assert preferred(tool("present"), tool("other"), preference=snapshot) == "present"
    # The absent id contributes no position to anything registered.
    assert select((tool("other"), tool("elsewhere")), snapshot).tool is None


def test_the_snapshot_answers_key_6_from_a_lookup_rather_than_a_scan() -> None:
    """``rank`` is the position, and an unnamed id ranks after every named one.

    The positions are held as a mapping rather than searched for per candidate:
    a scan would make selection cost the product of the candidate count and the
    sequence length, with no ``await`` between the first comparison and the last,
    which is a synchronous stall on the path every tool call takes. The mapping
    is exact rather than approximate precisely because a duplicate is refused —
    with each id appearing at most once, its position in the mapping *is* its
    index in the sequence, which is what ``ids`` round-tripping shows.
    """
    snapshot = Preference(["gamma", "alpha", "beta"])

    assert snapshot.ids == ("gamma", "alpha", "beta")
    assert [snapshot.rank(one) for one in snapshot.ids] == [0, 1, 2]
    assert snapshot.rank("unnamed") == 3
    assert Preference().rank("anything") == 0  # an empty sequence ranks all equal


def test_mutating_the_sequence_after_construction_changes_no_later_selection() -> None:
    """The snapshot is taken at construction and never re-read (ADR-0144 §4, §8).

    A caller that could mutate what it passed would hand the stage a sequence
    nothing validated — the duplicate check would be a check that did not stay
    checked — and two selections over one candidate set could then differ with
    nothing in the declarations having changed.
    """
    supplied = ["alpha"]
    snapshot = Preference(supplied)

    supplied.append("beta")
    supplied.append("beta")

    assert snapshot.ids == ("alpha",)
    assert preferred(tool("alpha"), tool("beta"), preference=snapshot) == "alpha"


# --- the eligibility filter (ADR-0144 §7, ADR-0145 §2) -------------------


def test_a_candidate_the_arguments_do_not_fit_is_removed_before_any_key() -> None:
    """Fit is eligibility, never a term the ordering could outweigh (ADR-0144 §7).

    The ineligible candidate here is the one the *ordering* prefers — least
    severe, free, quick — so a fit term folded in as a penalty would have to
    outweigh every key to get the right answer, and a rule that let it outrank
    would be answering an eligibility question with a ranking.
    """
    unfitting = tool("strict", parameters_schema=STRICT_SCHEMA, latency=timedelta(seconds=1))
    fitting = tool("lax", risk_level=RiskLevel.HIGH)

    outcome = eligible_candidates({"unexpected": "value"}, (unfitting, fitting))

    assert [candidate.id for candidate in outcome.eligible] == ["lax"]
    assert outcome.failure is None
    assert outcome.violations  # what the arguments missed, for the caller to report


def test_every_candidate_fitting_leaves_the_whole_set_and_reports_nothing() -> None:
    """The ordinary path: the filter is transparent when the arguments fit."""
    candidates = (tool("strict", parameters_schema=STRICT_SCHEMA), tool("lax"))

    outcome = eligible_candidates(FITTING, candidates)

    assert [candidate.id for candidate in outcome.eligible] == ["strict", "lax"]
    assert outcome.violations == ()
    assert outcome.failure is None


def test_an_empty_schema_declares_no_constraint_so_every_mapping_fits() -> None:
    """ADR-0145 §9's default, seen from the stage's side.

    An absent schema is not an error and is not a claim that the arguments were
    checked — it is today's behaviour for a tool that declares nothing.
    """
    lax = tool("lax")
    assert lax.parameters_schema == {}

    outcome = eligible_candidates({"anything": [1, 2, 3]}, (lax,))

    assert outcome.eligible == (lax,)
    assert outcome.violations == ()


def test_the_filter_reports_each_distinct_violation_once_across_candidates() -> None:
    """Two candidates declaring one schema do not report the same miss twice."""
    outcome = eligible_candidates(
        {"unexpected": "value"},
        (
            tool("one", parameters_schema=STRICT_SCHEMA),
            tool("two", parameters_schema=STRICT_SCHEMA),
        ),
    )

    assert outcome.eligible == ()
    assert len(outcome.violations) == len(set(outcome.violations))


def test_an_evaluation_that_raises_stops_the_walk_and_names_only_the_type() -> None:
    """A raise refuses the **step**, not the candidate that raised (ADR-0145 §7).

    Ineligibility is a statement that the parameters *do not satisfy* a schema,
    and a raise establishes no such fact — so continuing over the remainder would
    be selecting under an unknown. The type is all that may be carried: a
    ``ValidationError``'s text holds the instance fragments the walk was holding,
    so a schema that raises on demand would otherwise be the one path on which an
    untrusted document makes the argument values arrive in a log (§7, §8).

    The evaluator is patched rather than injected because ADR-0145 §2 forbids a
    consumer substituting its own — a seam for this would breach the clause the
    test exists to prove — and because no *constructible* schema raises: every
    route to one is refused at ``ToolDefinition`` construction by §6.
    """
    leaked = "alice@example.com"

    def exploding(*_args: object, **_kwargs: object) -> tuple[()]:
        raise RuntimeError(leaked)

    monkey = pytest.MonkeyPatch()
    with monkey.context() as patched:
        patched.setattr("ai_assistant.orchestration.selection.parameter_violations", exploding)
        outcome = eligible_candidates(FITTING, (tool("first"), tool("second")))

    assert outcome.failure == "RuntimeError"
    assert outcome.eligible == ()
    assert outcome.violations == ()  # none, rather than partial (§7)
    assert leaked not in outcome.failure
