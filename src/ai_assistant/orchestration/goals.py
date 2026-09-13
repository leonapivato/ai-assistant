"""Association, focus, engagement and a raised question's subject (ADR-0250).

ADR-0250 §19's **M3** threads that decision through ``orchestration``, and this
module holds the parts of the threading that are **pure functions of typed
values**: the focus derivation (§1), the candidacy projection and its labels (§3,
§4), the resolution of a verdict's label back to the goal it names (§3), the
deterministic reply an undecided turn composes (§5), the engagement facts and the
one sentence a reply announces them in (§5), and the resolution of a raised
question's subject (§7).

**Why a module of its own rather than methods on** ``Engine`` **or**
``LearningLoop``. Every value below is
computed from arguments and reaches no store, no model and no clock, so a reader
checking ADR-0250 §16's writer clauses — *"``orchestration`` writes every value
this decision adds, and no model writes any of them"* — can check the whole of the
derivation in one file. The two consumers are genuinely both: the **loop** resolves
a question's subject and its materiality because it holds the planner's proposal
and the registry, and the **engine** resolves the association and builds the
engagement because it holds the store. A helper each would be two statements of
one rule.

**Nothing here reads a clock, a store, a model or a setting.** The instants, the
identifiers and the dispositions are stamped by the callers, which is §16's
division: *"each stamped by the loop from the injected clock, the injected id
factory and typed outcomes"*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    AssociationVerdict,
    CandidateGoal,
    EngagementDisposition,
    Goal,
    GoalAssociation,
    GoalCandidacy,
    GoalCandidates,
    GoalDisambiguation,
    GoalElement,
    GoalEngagement,
    GoalInterpretation,
    GoalStatus,
    ProposedElement,
    ProposedQuestion,
    ProposedUnderstanding,
)
from ai_assistant.orchestration.interpretation import resolved_ordinal

if TYPE_CHECKING:
    from collections.abc import Mapping

#: The two :class:`~ai_assistant.core.types.GoalStatus` members ADR-0250 §1 calls
#: **open**, stated once so no reader spells the test a second way.
#:
#: *"A goal is **open** where its ``GoalStatus`` is ``ACTIVE`` or ``BLOCKED``, and
#: **closed** where it is ``ACHIEVED`` or ``ABANDONED``. No lane reads a third state
#: off the status, and **``BLOCKED`` is open** because ADR-0249 §4 defines it as
#: 'this objective cannot **currently** be achieved' — a goal nobody has given up on
#: and the kind a user most often comes back to."*
OPEN_GOAL_STATUSES: Final[frozenset[GoalStatus]] = frozenset(
    {GoalStatus.ACTIVE, GoalStatus.BLOCKED}
)

#: The one letter ADR-0250 §3's label scheme spells a candidate with.
#:
#: *"The label of the candidate at 1-based index *n* of the candidacy is the ASCII
#: string ``G`` followed by *n* in decimal with no padding."* It is ADR-0226 §3's
#: scheme applied to a fourth sequence, and ``G`` collides with none of ``M``
#: (ADR-0226 §3) or ``C``/``S``/``D`` (ADR-0249 §9).
CANDIDATE_LABEL_PREFIX: Final[str] = "G"

#: ADR-0249 §9's three element labels, in the order the tuples are declared, mapped
#: to the attribute each spells. Read over a
#: :class:`~ai_assistant.core.types.ProposedUnderstanding` rather than over a brief,
#: which is ADR-0250 §7's own scoping: *"A question is raised **about the
#: understanding the planner is proposing**"*.
_SUBJECT_TUPLES: Final[dict[str, str]] = {"C": "constraints", "S": "criteria", "D": "conditions"}

#: The two tuples ADR-0250 §6's first materiality limb calls material **by kind**.
#:
#: *"The subject is the interpretation's **outcome**, or an element of its
#: ``criteria`` or its ``conditions``."* ``constraints`` is deliberately absent: *"A
#: subject that is an element of ``constraints`` on a turn proposing no
#: side-effecting step is **not** material, and the question is dropped."*
_MATERIAL_BY_KIND: Final[frozenset[str]] = frozenset({"criteria", "conditions"})


def is_open(goal: Goal) -> bool:
    """Whether ADR-0250 §1 calls this goal **open**.

    Args:
        goal: The goal to test.

    Returns:
        ``True`` where its status is ``ACTIVE`` or ``BLOCKED``.
    """
    return goal.status in OPEN_GOAL_STATUSES


def label_of(index: int) -> str:
    """Spell ADR-0250 §3's label for the candidate at 1-based ``index``.

    Args:
        index: The candidate's 1-based position in the candidacy.

    Returns:
        ``G`` followed by the index in decimal with no padding.
    """
    return f"{CANDIDATE_LABEL_PREFIX}{index}"


def focused_index(candidates: tuple[Goal, ...]) -> int | None:
    """The 0-based position of the conversation's **focused** goal (ADR-0250 §1).

    *"The **focused goal of a conversation** is the open goal of that conversation's
    candidate set (§2) with the **greatest ``last_engaged_at``**, with the
    **``goal_id`` ascending as the tie-break**, and a goal whose ``last_engaged_at``
    is absent sorts **after** every goal carrying one and is never the focused goal
    while another candidate is open. A conversation whose candidate set holds no open
    goal **has no focused goal**, and no lane substitutes a closed one."*

    **The order is the store's and is not recomputed here.**
    :meth:`~ai_assistant.core.protocols.PlanStore.candidates_for` answers *"§2's set
    for that conversation, in §1's order"*, so the focused goal is the **first open
    goal of that tuple** — a second sort here would be a second authority over one
    total order, which is the shape ADR-0074 §2 refuses in terms.

    **Focus is derived on every read and is stored nowhere** (§1): no field, no row,
    no column and no in-process value names it.

    Args:
        candidates: The conversation's candidate set, in §1's order.

    Returns:
        The position of the focused goal, or ``None`` where no candidate is open.
    """
    for index, goal in enumerate(candidates):
        if is_open(goal):
            return index
    return None


def candidacy_of(request: str, candidates: GoalCandidates) -> GoalCandidacy | None:
    """Project a conversation's candidate set onto what the associator is shown (§4).

    **The projection is the containment.** A
    :class:`~ai_assistant.core.types.GoalCandidacy` *"carries no identifier of any
    kind — no ``goal_id``, no ``conversation_id``, no attempt id, no evidence id, no
    record id — and no instant, no revision number, no element, no ground, no plan,
    no effort figure and no authority"*, so this function reads exactly two fields of
    each goal and the count the store reported. ADR-0228 §8's namer rule is then a
    property of the type rather than a rule this projection is trusted to keep.

    **``focused`` is a label and never an id** (§4), resolved on the way back in by
    :func:`resolve` against the very tuple this call rendered.

    Args:
        request: The turn's own request, as ADR-0248 §1 carries it.
        candidates: The conversation's candidate set, in §1's order.

    Returns:
        The candidacy to hand the associator, or ``None`` where the candidate set is
        empty — which is ADR-0250 §3's second step, *"An empty candidate set opens a
        new goal, and costs no model call"*, and is why the type refuses an empty
        ``candidates`` tuple rather than admitting a degenerate call.
    """
    if not candidates.goals:
        return None
    focused = focused_index(candidates.goals)
    return GoalCandidacy(
        request=request,
        candidates=tuple(
            CandidateGoal(outcome=goal.statement, status=goal.status) for goal in candidates.goals
        ),
        elided=candidates.elided,
        focused=None if focused is None else label_of(focused + 1),
    )


@dataclass(frozen=True, slots=True)
class GoalFacts:
    """The two facts about this turn's goal that reach the composing stage (§10, §14).

    **Facts told to composing, not prose stitched onto a composed reply**, which is
    the shape ADR-0228 §10, ADR-0240 §8 and ADR-0242 §7 each already use at that seam.
    Both are `orchestration`'s own — neither is a model's judgement, neither is
    derived from the other, and on a turn given neither the assembled prompt is
    byte-identical to what it is without ADR-0250.

    Attributes:
        clarification: The text of the question this turn raised (§10), where the
            store accepted one, so that the turn's *"answer **is** the question"*.
            ``None`` on every turn that raised none and on every turn whose
            ``record_question`` refused — *"a lane that reported a question it did not
            write would tell the user to answer a question nothing holds"*.
        elided: Whether §2's cap dropped goals **and** this turn opened one (§14).
            *"Where ``elided`` is non-zero the reply states that older goals were not
            considered and that one may be named directly, on every turn whose
            disposition is ``OPENED``"* — and **not** on a ``CONTINUED``, a ``RESUMED``
            or a ``REOPENED``, where *"a goal was found, and reciting what was not
            looked at would be noise on the turns the mechanism worked"*.
    """

    clarification: str | None = None
    elided: bool = False


@dataclass(frozen=True, slots=True)
class Resolution:
    """What ADR-0250 §3's four dispositions came to, resolved against the candidacy.

    Attributes:
        goal: The goal the turn associates to, or ``None`` where it opens one or asks.
        opens: Whether the turn opens a new goal — a ``FRESH`` verdict, or a
            ``CONTINUES`` over a conversation with no focused goal.
        asks: Whether the turn asks which goal it is about (``UNDECIDED``).
        asked_about: The goals the ask names, in candidacy order, empty where the
            turn does not ask. Never read where :attr:`asks` is ``False``.
    """

    goal: Goal | None = None
    opens: bool = False
    asks: bool = False
    asked_about: tuple[Goal, ...] = ()


def resolve(association: GoalAssociation, candidates: tuple[Goal, ...]) -> Resolution:
    """Take exactly one of ADR-0250 §3's four dispositions, and never a fifth.

    - **``ASSOCIATES`` whose one label resolves** → the turn associates to that goal.
    - **``FRESH``** → the turn opens a new goal (ADR-0249 §3).
    - **``CONTINUES``** → the turn associates to the **focused** goal (§1). Where the
      conversation has no focused goal the turn opens a new goal instead.
    - **``UNDECIDED``** → the turn **asks which goal it is about** and associates to
      none.

    **A label that resolves to nothing is ``UNDECIDED`` and never a pick.** *"A string
    that does not match the form, an *n* below 1 or beyond the candidacy's length, and
    an ``ASSOCIATES`` carrying other than exactly one label are each treated as
    ``UNDECIDED`` and the turn asks. **No implementation falls back to the focused
    goal, to the first candidate, to the most recent one, or to any tie-break at
    all**, because every one of those picks a goal the model did not name."*

    **Which goals the ask names, in both of ``UNDECIDED``'s shapes** (§5). Where two
    or more labels resolve, exactly those; where **fewer than two** resolve — a
    decline, an unparseable answer, or a single label outside the range — the system
    has no subset to ask about, so **every** candidate, in candidacy order.

    Args:
        association: What the associator answered.
        candidates: The very tuple the candidacy was rendered from, in its order.

    Returns:
        The disposition, resolved.
    """
    resolved = tuple(candidates[index] for index in _indices(association.labels, len(candidates)))
    if association.verdict is AssociationVerdict.ASSOCIATES and len(resolved) == 1:
        return Resolution(goal=resolved[0])
    if association.verdict is AssociationVerdict.FRESH:
        return Resolution(opens=True)
    if association.verdict is AssociationVerdict.CONTINUES:
        focused = focused_index(candidates)
        if focused is None:
            return Resolution(opens=True)
        return Resolution(goal=candidates[focused])
    # `UNDECIDED`, and every ill-formed `ASSOCIATES` falling through to it. The ask
    # names the resolved subset where there are two or more, and the whole candidacy
    # otherwise (§5) — never an invented candidate and never the one label it has.
    return Resolution(asks=True, asked_about=resolved if len(resolved) > 1 else candidates)


def _indices(labels: tuple[str, ...], length: int) -> tuple[int, ...]:
    """Resolve ADR-0250 §3's labels to 0-based positions, dropping what resolves to nothing.

    **``orchestration`` resolves every label and the implementation resolves none**
    (§4): *"the loop resolves a label by parsing *n* and indexing **the very tuple it
    passed on this call**. No mapping, table or identifier crosses between
    ``planning`` and ``orchestration``"*.

    A label is dropped where it does not match the form, where *n* is below 1 or
    beyond ``length``, and where it repeats a position already resolved — a repeat
    would make one candidate two, which is a set the user never has.

    **The positions come back in candidacy order and never in the order the labels
    named them**, which is §5's clause for both of ``UNDECIDED``'s shapes: *"``candidates``
    holds exactly those goals' outcome statements, **in candidacy order**"*, and the
    whole candidacy *"in candidacy order"* otherwise. The model's labels are an answer
    about a set and carry no ordering of their own — a ``("G2", "G1")`` that reordered
    the ask would make the question the user reads depend on which way round the model
    happened to list two goals, and §2's candidacy order is what the set was rendered in.

    Args:
        labels: The labels the associator named, verbatim.
        length: How many candidates the candidacy carried.

    Returns:
        The positions, ascending, without repeats.
    """
    seen: set[int] = set()
    for label in labels:
        # **The same parser ADR-0249 §9's own labels are read by** — one refusal for one
        # scheme, so a zero-padded ordinal, a Unicode decimal, an ordinal below 1 and one
        # beyond the sequence's length are all refused here exactly as they are there.
        index = resolved_ordinal(label, CANDIDATE_LABEL_PREFIX, length)
        if index is not None:
            seen.add(index)
    return tuple(sorted(seen))


def disambiguation_of(asked_about: tuple[Goal, ...], *, elided: int) -> GoalDisambiguation:
    """Build what an ``UNDECIDED`` turn asks about (ADR-0250 §5).

    *"``candidates`` … holding the **outcome statements** of the goals the turn is
    asking about … **It carries no identifier, no label, no status and no
    instant**."*

    Args:
        asked_about: The goals the ask names, in candidacy order.
        elided: How many goals the candidate-set cap dropped (§2).

    Returns:
        The typed value the reply is composed from and the outcome carries.
    """
    return GoalDisambiguation(
        candidates=tuple(goal.statement for goal in asked_about), elided=elided
    )


def _quoted(text: str) -> str:
    """One statement, in quotation marks, ready to sit inside a composed sentence.

    **``ensure_ascii=False``**: this string is read by a person, not parsed by one.
    The quoting is here to put the statement in quotation marks and to escape a quote
    or a backslash inside it; escaping every non-ASCII character as well would render
    a goal the user stated in their own language as escape sequences, which is
    ADR-0250 §5's deterministic prose made unreadable by an encoding default.

    Args:
        text: The statement to render.

    Returns:
        It, quoted.
    """
    return json.dumps(text, ensure_ascii=False)


def _listed(texts: tuple[str, ...], *, joiner: str) -> str:
    """Several statements, quoted and read out as a list.

    One renderer for both of ADR-0250 §5's composed replies — the undecided turn's
    ask and the engagement announcement — so the two cannot drift apart in how they
    quote a statement the user gave. What differs between them is the last
    conjunction, which is why it is an argument rather than a literal.

    Args:
        texts: The statements, in the order they are to be read. Never empty.
        joiner: The word before the last one — ``"or"`` for a question between
            candidates, ``"and"`` for a list of what moved.

    Returns:
        Them, quoted and joined.
    """
    quoted = [_quoted(text) for text in texts]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + f" {joiner} {quoted[-1]}"


def disambiguation_reply(disambiguation: GoalDisambiguation) -> str:
    """Compose the ``UNDECIDED`` turn's reply, deterministically (ADR-0250 §5).

    *"The reply is composed by ``orchestration`` from the typed value, and no model
    writes it. The turn made no model call it could compose from — it took no
    relevance read, no episodic supplement and no ``Planner.plan`` call, because
    association precedes all three — so the sentence is deterministic, is built from
    ``candidates`` and ``elided``, and **cannot disagree with the member beside
    it**."*

    **Carrying a reply rather than leaving it absent is what keeps every channel
    working.** ADR-0200 §4 makes ``spoken`` *"the rendering of ``outcome.reply`` and
    of nothing else"*, so an undecided turn with no reply would answer a spoken
    request with silence while waiting for an answer it never asked for out loud.

    **One candidate is a well-formed question and not a degraded one** (§5): *"is this
    about that, or is it something new?"*.

    **The elision is disclosed here** (§14): *"Where ``elided`` is non-zero the reply
    states that older goals were not considered and that one may be named directly …
    on every turn that returned a ``disambiguation``."* No dropped goal is rendered
    and no count of them is either — a count is a magnitude about goals the user
    cannot see, and §15's bar keeps a figure out of a rendered statement.

    Args:
        disambiguation: The typed value the outcome carries.

    Returns:
        The reply, which is non-blank because ``candidates`` is non-empty.
    """
    if len(disambiguation.candidates) == 1:
        sentence = (
            f"I am not sure whether this continues something you already asked for: "
            f"{_quoted(disambiguation.candidates[0])}. Is it about that, or is it "
            f"something new?"
        )
    else:
        listed = _listed(disambiguation.candidates, joiner="or")
        sentence = (
            f"I am not sure which of these this is about: {listed}. "
            f"Which one is it — or is it something new?"
        )
    if disambiguation.elided:
        sentence += (
            " Older objectives were not considered here; you can name one directly if"
            " this is about one of those."
        )
    return sentence


#: What ADR-0250 §14 says on a turn whose disposition is ``OPENED`` and whose
#: candidate set was capped.
#:
#: *"Where ``elided`` is non-zero the reply states that older goals were not
#: considered and that one may be named directly, on every turn whose disposition is
#: **``OPENED``** … **On a ``CONTINUED``, a ``RESUMED`` or a ``REOPENED`` the elision
#: is not mentioned**: a goal was found, and reciting what was not looked at would be
#: noise on the turns the mechanism worked."*
#:
#: It is a clause appended to the composing stage's instruction rather than a
#: sentence stitched onto a composed reply, which is the shape ADR-0228 §10,
#: ADR-0240 §8 and ADR-0242 §7 each already use at that seam: the model says it in
#: the register of the answer it is writing, and nothing here competes with the prose
#: beside it.
ELISION_PROMPT: Final[str] = (
    "This request started a new objective, and older objectives of this conversation "
    "were not considered when deciding that. Say so in one short sentence, and say "
    "that they can name an earlier objective directly if this was about one of them. "
    "Do not guess at what those objectives were and do not say how many there are."
)

#: What ADR-0250 §10 tells the composing stage on a turn that raised a question.
#:
#: *"The turn that raises a question does not park. It composes, its answer **is** the
#: question, and it returns."* The question's own text is rendered to the stage beside
#: this clause, so the model puts it to the user in the register of the channel rather
#: than this module stitching a sentence onto prose it did not write.
CLARIFICATION_PROMPT: Final[str] = (
    "This turn could not settle what the request means, so its answer is the question "
    "quoted below and nothing else is being done about the request yet. Put that "
    "question to them, in your own register and without changing what it asks. Do not "
    "answer it yourself, do not guess at the answer, and do not say that anything has "
    "been started or booked."
)


def engagement_of(
    goal: Goal,
    *,
    disposition: EngagementDisposition,
    recorded: tuple[GoalInterpretation, ...],
) -> GoalEngagement:
    """Say what this turn did with the goal it engaged (ADR-0250 §5).

    **``revised`` says a revision was recorded, and nothing more.** *"It is ``True``
    exactly where this turn recorded a
    :class:`~ai_assistant.core.types.GoalInterpretation` through
    ``PlanStore.record_interpretation``, and it is **not** a claim that any text
    moved."* ``recorded`` is
    :attr:`~ai_assistant.orchestration.loop.RecordedGoal.revisions`, which ADR-0249
    §11 makes exactly the revisions that take that route: a goal this turn **opened**
    reaches the store through ``save_goal`` carrying its whole chain, so its
    ``recorded`` is empty and ``revised`` is ``False`` — which is also why an
    ``OPENED`` turn announces nothing (§5's decision-6 rule).

    **``added`` and ``removed`` are computed by comparing the two revisions and never
    by a model** (§5), *"in the tuple order ``constraints``, ``criteria``,
    ``conditions``"*, byte for byte, *"and an element retained by label (ADR-0249 §7)
    appears in neither"* — which falls out of comparing texts rather than needing a
    rule, because a retained element's text is copied forward unchanged.

    **Which two revisions, where a turn recorded more than one.** The **new** revision
    is the last this turn recorded; the **previous** is the one that stood **before
    this turn**, which is the element preceding the *first* revision this turn
    recorded. Where a turn recorded exactly one — every arm §20 states, and the
    ordinary case — the two readings coincide. Where it recorded two, taking the
    immediate predecessor of the last would hide what the first one moved, and §5's
    own reason for the member forbids exactly that: *"a turn that dropped an element
    and said nothing would be the silent rewrite §3 and §5 exist to forbid"*.

    Args:
        goal: The goal as it now stands, with this turn's revisions appended.
        disposition: What this turn did with it.
        recorded: The revisions this turn recorded through ``record_interpretation``,
            in the order it recorded them.

    Returns:
        The typed value the outcome carries and a surface renders its sentence from.
    """
    if not recorded:
        return GoalEngagement(disposition=disposition, outcome=goal.statement)
    chain = goal.interpretation
    new = recorded[-1]
    previous = _preceding(chain, recorded[0])
    if previous is None:
        # Unreachable on a goal the store already holds — a recorded revision always
        # follows one — and stated rather than assumed: with no baseline there is
        # nothing to compare, so nothing is claimed to have moved beyond the revision
        # itself, which is a shape `GoalEngagement`'s own validator admits.
        return GoalEngagement(disposition=disposition, outcome=goal.statement, revised=True)
    return GoalEngagement(
        disposition=disposition,
        outcome=goal.statement,
        revised=True,
        outcome_changed=new.outcome != previous.outcome,
        added=_difference(new, previous),
        removed=_difference(previous, new),
    )


def _preceding(
    chain: tuple[GoalInterpretation, ...], revision: GoalInterpretation
) -> GoalInterpretation | None:
    """The revision standing immediately before ``revision`` in the goal's history.

    Args:
        chain: The goal's revisions, oldest first.
        revision: The revision to look behind.

    Returns:
        Its predecessor, or ``None`` where it is the oldest the chain still holds.
    """
    for index, held in enumerate(chain):
        if held.revision == revision.revision:
            return chain[index - 1] if index else None
    return None


def _difference(one: GoalInterpretation, other: GoalInterpretation) -> tuple[str, ...]:
    """Every element text ``one`` carries in a tuple that ``other`` does not (§5).

    *"``added`` carries the ``text`` of every element of the **new** revision that the
    previous revision did not carry in the **same** tuple, byte for byte … Both are in
    the tuple order ``constraints``, ``criteria``, ``conditions``."*

    Args:
        one: The revision whose elements are reported.
        other: The revision they are compared against.

    Returns:
        The texts, in the tuple order §5 states and within each tuple in its own.
    """
    moved: list[str] = []
    for name in ("constraints", "criteria", "conditions"):
        held = {element.text for element in _elements(other, name)}
        moved.extend(element.text for element in _elements(one, name) if element.text not in held)
    return tuple(moved)


def _elements(revision: GoalInterpretation, name: str) -> tuple[GoalElement, ...]:
    """One of an interpretation's three element tuples, by name.

    Args:
        revision: The revision to read.
        name: ``constraints``, ``criteria`` or ``conditions``.

    Returns:
        That tuple.
    """
    elements: tuple[GoalElement, ...] = getattr(revision, name)
    return elements


#: The lead clause of ADR-0250 §5's announcement, per disposition that owes one on
#: the **engagement** limb — *"the ``disposition`` is ``RESUMED`` or ``REOPENED``"*.
#:
#: A disposition absent here owes a sentence only where a revision moved a word, and
#: takes :data:`_REVISED_LEAD` instead. The goal is named **once** in either case
#: (§14): one clause, one quoted outcome statement, and no second mention of it.
_ENGAGED_LEADS: Final[dict[EngagementDisposition, str]] = {
    EngagementDisposition.RESUMED: "Picking up what you asked for earlier",
    EngagementDisposition.REOPENED: "Going back to something you had finished with",
}

#: The lead clause where the sentence is owed on the **revision** limb alone — a
#: turn whose disposition is ``OPENED`` or ``CONTINUED`` that moved a word.
_REVISED_LEAD: Final[str] = "I have changed what I understand you are asking for"

#: What is added to an engagement lead where a revision moved a word on the **same**
#: turn, so that a resumption which also revised states both facts in one sentence.
_ALSO_REVISED: Final[str] = ", which I now understand as"


def announcement_of(engagement: GoalEngagement | None) -> str | None:
    """ADR-0250 §5's announcement, composed from the typed value (§5, §16).

    > *"A reply carries one sentence naming the goal it is about where, and only
    > where, the ``disposition`` is ``RESUMED`` or ``REOPENED``, or ``revised`` is
    > ``True`` **and** at least one of ``outcome_changed``, ``added`` and ``removed``
    > says something moved."*

    **The whole of §5's rule is this function**, so that the condition a reviewer
    checks and the condition the reply is composed under are one statement rather
    than two. A turn whose disposition is ``OPENED`` or ``CONTINUED`` and which moved
    no word gets ``None`` — *"an ordinary topic change and an ordinary continuation
    each need neither an announcement nor a confirmation"* — and so does a
    **grounding-only** revision, where *"what moved is the record of who said it,
    which the goal's own interpretation chain carries and which no reply states"*.

    **What it states, where it is owed on the revision limb** (§5): the goal's
    ``outcome`` *"as this turn recorded it, **every text in ``added``**, and **every
    text in ``removed``** as something no longer held — never merely that something
    changed, and never the outcome alone where either tuple is non-empty"*. Both
    tuples are read out in full and neither is summarised, counted or truncated: the
    sentence is *"the real safeguard against a wrong association"*, and a user who is
    told only that something changed cannot tell whether it changed to what they
    meant.

    **And no model's decision reaches it** (§16). Every word but the statements
    themselves is a literal of this module, and the statements are the goal's own
    outcome and element texts as the store holds them — so the sentence cannot
    disagree with the :class:`~ai_assistant.core.types.GoalEngagement` beside it in
    the outcome, which is the property ADR-0242 §9's rendering-is-presentation ground
    rests on.

    **Nothing is confirmed and nothing is asked** (§5). The value returned is a
    statement, placed in a reply the turn was composing anyway; no caller turns it
    into a question, a park or a second turn, and no turn waits for it to be
    acknowledged.

    Args:
        engagement: What this turn did with its goal, or ``None`` where it engaged
            none — a routed operation, a restated settled binding and the
            ``UNDECIDED`` turn, none of which has a goal to name.

    Returns:
        The sentence, or ``None`` where §5 owes none.
    """
    if engagement is None:
        return None
    # §5's two limbs, as one boolean each. `revised` alone is **not** the test: it
    # "says a revision was recorded, and nothing more", so the conjunction with
    # something having moved is what keeps a grounding-only revision silent.
    moved = engagement.revised and bool(
        engagement.outcome_changed or engagement.added or engagement.removed
    )
    lead = _ENGAGED_LEADS.get(engagement.disposition)
    if lead is None:
        if not moved:
            return None
        lead = _REVISED_LEAD
    elif moved:
        lead += _ALSO_REVISED
    # The two tuples, each read out entire, as clauses of the **same** sentence: §5
    # says "A reply carries **one** sentence naming the goal it is about", and that
    # same sentence "states the goal's `outcome` as this turn recorded it, **every
    # text in `added`**, and **every text in `removed`** as something no longer
    # held". They come after the outcome because each is a change to it, and
    # `removed` last because "no longer holding" reads as a qualification of what now
    # stands.
    moves: list[str] = []
    if engagement.added:
        moves.append(f"adding {_listed(engagement.added, joiner='and')}")
    if engagement.removed:
        moves.append(f"no longer holding {_listed(engagement.removed, joiner='and')}")
    stated = "" if not moves else f", {' and '.join(moves)}"
    return f"{lead}: {_quoted(engagement.outcome)}{stated}."


@dataclass(frozen=True, slots=True)
class RaisedSubject:
    """A :class:`~ai_assistant.core.types.ProposedQuestion` whose subject resolved.

    Attributes:
        text: The question as the user would read it, the planner's own.
        about: The **subject's own text**, taken from the revision this turn
            recorded — never the proposed element's ``text``, which a retaining
            element does not have (ADR-0250 §7).
        tuple_name: Which of the three tuples the subject sits in, or ``None`` where
            the subject is the outcome. Read by the materiality test alone.
    """

    text: str
    about: str
    tuple_name: str | None


def subject_of(
    question: ProposedQuestion,
    *,
    proposal: ProposedUnderstanding,
    recorded: GoalInterpretation,
    positions: Mapping[str, tuple[int | None, ...]],
) -> RaisedSubject | None:
    """Resolve what a raised question is about, or drop it (ADR-0250 §7).

    *"``orchestration`` resolves ``about`` to the **position** it names in the
    ``ProposedUnderstanding``'s own tuple, and then records the ``text`` of the
    **``GoalElement`` that position produced in the revision this turn recorded** —
    which is the newly grounded element where the proposal stated one, and the element
    **retention copied forward** where the proposal carried a ``retains`` and nothing
    else (ADR-0249 §7). Where ``about`` is ``None`` it records the recorded revision's
    **outcome**."*

    **A label outside the proposal's own tuples resolves to nothing and the question
    is dropped** — silently, without failing the turn — and *"A label of a tuple other
    than the one it spells likewise resolves to nothing: the label space is per
    tuple."*

    **Resolution happens over the proposal as it was received, before any element is
    dropped by ADR-0249 §7's ground resolution.** *"A question about an element whose
    ground did not resolve is itself **dropped**, because the element it is about is
    not in the recorded revision and a question about nothing is not a question."*
    That is why the position is read from the proposal and the **text** from the
    recorded revision: a proposal tuple longer than the revision's is exactly a tuple
    an element was dropped from, and the position then names nothing.

    Args:
        question: What the planner raised.
        proposal: The understanding it raised it about, as received.
        recorded: The revision this turn recorded from that proposal.
        positions: Which position of the **recorded** tuple each proposed position
            produced, or ``None`` where its ground did not resolve
            (:class:`~ai_assistant.orchestration.interpretation.RecordedUnderstanding`).
            **A sibling's failure drops that sibling and nothing else**: §7 drops a
            question exactly where *"the element it is about is not in the recorded
            revision"*, and reading a length difference instead would drop a question
            about a surviving element because a neighbour's ground did not resolve.

    Returns:
        The subject, or ``None`` where the label resolves to nothing.
    """
    if question.about is None:
        return RaisedSubject(text=question.text, about=recorded.outcome, tuple_name=None)
    label = question.about
    name = _SUBJECT_TUPLES.get(label[:1])
    if name is None:
        return None
    proposed: tuple[ProposedElement, ...] = getattr(proposal, name)
    # **ADR-0249 §9's own parser, read over the proposal's tuple rather than the
    # brief's** — one refusal for one scheme, so a zero-padded ordinal is refused here
    # exactly as it is where the brief's labels are read.
    index = resolved_ordinal(label, label[:1], len(proposed))
    if index is None:
        return None
    produced = positions.get(name, ())
    if index >= len(produced):  # pragma: no cover — one entry per proposed position
        return None
    kept = produced[index]
    if kept is None:
        return None
    return RaisedSubject(
        text=question.text, about=_elements(recorded, name)[kept].text, tuple_name=name
    )


def is_material(subject: RaisedSubject, *, side_effecting: bool) -> bool:
    """ADR-0250 §6's materiality test, which is the whole of it.

    - **By kind.** *"The subject is the interpretation's **outcome**, or an element of
      its ``criteria`` or its ``conditions``. A success criterion is what decides
      whether the goal was met and a condition is what decides whether to act at all,
      so an ambiguity in either changes the answer to a question the system will have
      to answer."*
    - **By consequence.** *"The ``ActionPlan`` the **same** ``PlannerOutput`` carries
      proposes at least one step whose capability the ``ToolRegistry`` declares
      ``ToolDefinition.side_effecting``. A turn about to change something outside
      itself is a turn whose every understood element is material."*

    *"A subject that is an element of ``constraints`` on a turn proposing no
    side-effecting step is **not** material, and the question is dropped."*

    **It is code's and is never taken on the model's word** (§6): both limbs read
    tuple membership and a **declaration**, and neither reads a confidence figure, a
    risk level, a reversibility, a tier reach or a policy ruling. **No permission is
    consulted, cleared or implied by this test.**

    Args:
        subject: The resolved subject.
        side_effecting: Whether the plan this call returned proposes at least one step
            whose capability the registry declares side-effecting.

    Returns:
        Whether a question about it is put to the user.
    """
    return side_effecting or subject.tuple_name is None or subject.tuple_name in _MATERIAL_BY_KIND


def taken_question(
    proposal: ProposedUnderstanding,
    *,
    recorded: GoalInterpretation,
    positions: Mapping[str, tuple[int | None, ...]],
    side_effecting: bool,
) -> RaisedSubject | None:
    """Take at most one question from a planner call (ADR-0250 §7, §6).

    *"**At most one question is taken from a call.** Where several come back, the loop
    takes the **first in tuple order** whose ``about`` resolves and whose subject is
    material (§6), and drops every other, silently. The order is the tuple's and there
    is no ranking, no scoring and no second call to choose between them."*

    Args:
        proposal: The understanding the planner proposed, as received.
        recorded: The revision this turn recorded from it.
        positions: The proposal-to-revision correspondence (:func:`subject_of`).
        side_effecting: §6's second materiality limb, read by the caller that holds
            the registry.

    Returns:
        The question to raise, or ``None`` where none resolved and was material.
    """
    for question in proposal.questions:
        subject = subject_of(question, proposal=proposal, recorded=recorded, positions=positions)
        if subject is not None and is_material(subject, side_effecting=side_effecting):
            return subject
    return None


__all__ = [
    "CANDIDATE_LABEL_PREFIX",
    "CLARIFICATION_PROMPT",
    "ELISION_PROMPT",
    "MAX_ASSOCIATION_CANDIDATES",
    "OPEN_GOAL_STATUSES",
    "GoalFacts",
    "RaisedSubject",
    "Resolution",
    "announcement_of",
    "candidacy_of",
    "disambiguation_of",
    "disambiguation_reply",
    "engagement_of",
    "focused_index",
    "is_material",
    "is_open",
    "label_of",
    "resolve",
    "subject_of",
    "taken_question",
]
