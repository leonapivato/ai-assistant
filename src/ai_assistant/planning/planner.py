r"""The model-backed planner (ADR-0047).

The production :class:`~ai_assistant.core.protocols.Planner`: it turns a
:class:`~ai_assistant.core.types.Goal` (plus assembled ``context`` and retrieved
``memories``) into a frozen :class:`~ai_assistant.core.types.ActionPlan` by
prompting an injected :class:`~ai_assistant.core.protocols.ModelProvider` for a
JSON envelope and extracting that text into ``PlanStep``\ s.

Two boundaries from ADR-0014 shape the whole module:

- A step names an **abstract capability**, not a tool. This module imports
  nothing from ``tools`` and validates a capability only as a non-blank
  identifier (ADR-0014 §2). Since ADR-0211 §1 it is *told* which capabilities are
  advertised — a tuple of strings the caller read from the registry and pushed in,
  exactly as ``context`` and ``memories`` are pushed in — which changes what the
  prompt can state and changes nothing about what this module imports or holds.
- Model output **never sets execution status** (VISION §7). The planner produces
  an ``ActionPlan`` and nothing else; ids, timestamps and every ``StepStatus``
  stay the property of deterministic code.

Step ids and the plan id are minted here from an injected id factory, never taken
from the model, so unique step ids are guaranteed structurally and the model is
kept out of the id space entirely (ADR-0047 §2).

The envelope has **two** legal shapes (ADR-0176 §1). A plan carries a non-empty
``steps`` list; a **decline** carries an empty one *together with*
``"no_capability_needed": true`` and a non-blank ``rationale``. A decline has two
grounds and one shape (ADR-0211 §5): the goal is answered from what this turn
already carries, or it requires an act that no advertised capability can perform.
Which one applies is said by the ``rationale`` and nowhere else — the marker keeps
its structural meaning, that this envelope names no capability, and is never read
as a claim that the goal needed none. The second shape is asserted
rather than merely empty, which is what tells it apart from a failure to
decompose — the objection ADR-0047 §4 raised against a bare empty list, and one
that has no purchase on a positive assertion. ``no_capability_needed`` is a key of
this prompt-level envelope only: it never reaches ``ActionPlan``, which crosses the
subsystem boundary carrying empty ``steps`` and a ``rationale`` saying why
(ADR-0176 §8).

**Since ADR-0226 the envelope has one more, optional key, and it is not a third
shape.** A plan or a decline may carry a ``read_request``: at most one ask of each
of §2's two kinds, naming one further read the planner judged this turn's supply
too thin without. It rides beside whichever shape the reply already is, it is
serviced by the loop and never here, and it is never a step — reading the owner's
own store is not an act in the world, so nothing about selection, permission or
execution touches it (§4). Three properties of this module carry the decision. The
supply is **labelled** by position, ``M1``, ``M2``, … (:func:`_label`), because §3
rules that no record identifier is rendered to a model and none is accepted from
one; the prompt asks for the request in :data:`_READ_REQUEST_GUIDANCE`, with
:data:`_ACT_RECORD_GUIDANCE` stating the one case §2 named the hop for; and
:func:`_optional_read_request` reads one back, dropping a malformed one rather than
spending a repair round or costing the plan.

**A statement of fact is a decline** (#1695). It asks for nothing, so it wants no
capability, and the prompt works that direction of ADR-0176 §4's test through
explicitly — including what the rationale should say, since on a decline the
rationale is the whole of the plan's content (ADR-0176 §3) and it is what the
composing stage renders (#1355). It is an acknowledgement and not a receipt: this
stage runs before the exchange is recorded, and that write can fail (ADR-0074 §3),
so the rationale claims nothing about retention in either direction.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, NamedTuple, assert_never

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    MAX_HOP_LABELS,
    ActionPlan,
    BeliefBand,
    EpisodicMemory,
    ExchangeDisposition,
    MemoryKind,
    Message,
    PlanStep,
    ReadAsk,
    ReadKind,
    ReadRequest,
    Role,
    band_of,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import (
        CalendarFacet,
        ContextFacet,
        CurrentContext,
        EmailFacet,
        Goal,
        MemoryRecord,
    )

_log = structlog.get_logger(__name__)

#: Total ``complete`` calls a single ``plan`` may make: one initial request plus
#: one bounded repair round (ADR-0047 §6). The constructor rejects anything < 1.
#: Named distinctly from ``execution.DEFAULT_MAX_ATTEMPTS`` (the retry ceiling),
#: which is a different bound.
DEFAULT_PLAN_ATTEMPTS = 2

#: The most decode **misses** :func:`_extract_object` tolerates in one reply before
#: giving up. A failed ``raw_decode`` costs work proportional to how far into the
#: reply it reached (``JSONDecodeError`` computes a line and column), so attempting
#: it at every brace of a brace-dense malformed reply is quadratic and blocks the
#: event loop; bounding the misses keeps the scan linear. A *decoded* object never
#: counts, so any number of valid JSON fragments may precede the envelope — only
#: unparseable braces are limited. Generous, so a conforming or lightly-wrapped
#: reply is never lost to it; only a reply burying the envelope behind more than
#: this many unparseable braces degrades to bounded repair.
_MAX_EXTRACTION_MISSES = 256

#: The event name every dropped read request is logged under (ADR-0226 §8).
#:
#: One name with a ``reason`` from a closed set of literals, so a deployment can
#: count drops without this module writing anything the model produced into a log
#: line: ADR-0004 §5 keeps content out of logs, and a query or a label is content.
#: Named rather than inlined so the test asserts the obligation rather than a
#: string spelled twice.
_READ_REQUEST_DROPPED: Final = "planner_read_request_dropped"

#: The heading the chronological conversation tail is printed under (ADR-0074 §5).
_TAIL_HEADING: Final = "Recent conversation turns, in order:"

#: The heading the relevance-retrieved group is printed under (ADR-0074 §5).
#:
#: Named rather than inlined because it is read outside this module: the benchmark
#: harness assembles the same block for its answering prompt and imports this
#: instead of spelling it a second time (#1181). It stays private — the harness
#: reads a private name knowingly, which is cheaper than widening ``planning``'s
#: public surface for a driver that is not a subsystem.
_RETRIEVED_HEADING: Final = "Relevant memories about the user:"

#: What each band's records are introduced as, for the non-episodic kinds
#: (ADR-0072 §6). One clause per band, saying whose claim the content is: the
#: user's own word, this system's own conclusion, or a connected source's report.
#: §6 fixes *what the assembler must convey* — the band and the confidence — and
#: leaves the wording here, so these are phrases a reader needs no vocabulary for,
#: unlike the ``[kind/source]`` tag they sit beside.
_STANCE: Final[Mapping[BeliefBand, str]] = {
    BeliefBand.ASSERTED: "the user stated",
    BeliefBand.DERIVED: "the assistant believes",
    BeliefBand.ATTESTED: "a source the user connected reported",
}

#: The stated-fact direction of ADR-0176 §4's test, worked through (#1695).
#:
#: A statement of fact asks for nothing, so under §4's test it wants no capability
#: — but the prompt's decline condition reads "answered from what this turn already
#: carries", and a model applying that literally to *"did you know I go to school at
#: Northeastern"* finds nothing to answer and plans a store step instead. On the
#: deployed hub it planned one; nothing carries a memory write (intake is the
#: observer's, ADR-0093, and ADR-0048 §1 declines ``remember`` in terms), so the
#: step reached ``NO_CAPABLE_TOOL`` and ADR-0170 §5's honest account made the reply
#: tell the owner it had no way to remember — false, because ADR-0074 §3 captures
#: every turn as an episode and the belief lands when the observer runs.
#:
#: This block is the decline's *rationale* as much as its shape: ADR-0176 §3 makes
#: the rationale the whole of a declined plan's content, and ``composing``'s
#: ``_render_plan`` renders it on a decline (#1355), so what this asks the model to
#: say is what reaches the composed reply.
#:
#: **It asks the model to acknowledge, never to promise retention**, and the
#: distinction is load-bearing rather than fastidious. Planning runs *before* the
#: exchange is recorded — ``Engine`` composes and only then captures — and ADR-0074
#: §3 makes that write fallible in terms: "a memory-store failure — an embedder
#: fault, a locked database — leaves a turn recorded with **no** episode … and the
#: failure is **reported on the outcome**". A rationale asserting the statement *is*
#: kept would therefore be a claim about something that has not happened yet and
#: can fail, contradicted in the same turn by the outcome that reports the failure.
#: That is the very defect this block exists to remove, pointed the other way. So
#: the rationale says the statement was heard and that taking it in wants no
#: capability — both true at planning time — and asserts nothing about what becomes
#: of it, long-term memory included, since the observer's run is not this turn's
#: (ADR-0093).
#:
#: It is a separate constant so the prompt test can assert it **reaches the model**
#: without string-matching its wording, which ADR-0176 §4 declines to demand of any
#: lane: an assertion on a sentence "fails on every rewording that improves the
#: instruction and passes on every rewording that guts it".
_STATED_FACT_GUIDANCE = """\
Telling you something is not asking you to do something. Where the user states a \
fact about themselves, corrects one, or passes on news, and asks for nothing to be \
done with it, the goal requires no act: what was said is part of the conversation \
set out in the next message, and taking it in is not work a step performs. Reply \
with a DECLINE, and let the rationale say that you heard what the user told you \
and that no capability is needed for it. Do not name a capability for storing, \
saving or remembering it: no capability does that, and a step naming one finds no \
tool, which makes the answer tell the user there is no way to remember what they \
just said — which is false and is the mistake to avoid here. Do not go the other \
way either: recording this exchange happens after you, and separately, so the \
rationale must not say that what you were told has been saved, stored, or put into \
long-term memory."""

#: The unadvertised-act direction of ADR-0211 §4's test, worked through.
#:
#: §4's third normative clause: where the decline's ground is that nothing
#: advertised can perform the act, the rationale must say what the goal would have
#: needed and that the assistant cannot do it, and "may not name a capability, a
#: tool, a product or a vendor that the stated vocabulary does not contain".
#:
#: **That prohibition is the whole point of the block, and #1772 is why.** Eight
#: rows of a live QA run came back apologising for a *fabricated referent* — "no
#: calendar tool connected", "no tool available to search contacts" — describing
#: something that was never registered, never selected and never called. The
#: honesty obligation ADR-0170 §5 puts on the composing stage was discharged
#: faithfully over a plan that had invented the thing being disclaimed. Moving the
#: sentence from "I have no calendar tool" to "I cannot look at your calendar" is
#: one sentence, once, about something true.
#:
#: A separate constant for the reason :data:`_STATED_FACT_GUIDANCE` is one: the
#: prompt test can assert it **reaches the model** without string-matching its
#: wording, which ADR-0176 §4's fourth clause declines to demand of any lane.
_UNAVAILABLE_GUIDANCE = """\
Where the goal does require an act and nothing on the list above can carry it, the \
reply is a DECLINE as well, and there the rationale is the whole of your answer to \
the user. Say in your own words what the goal would have needed and that you \
cannot do it — one sentence about the act itself. Do not name a capability, tool, \
product, service or vendor that is not on the list above, and do not say that one \
is missing, disconnected or unavailable: naming a thing that was never there tells \
the user a connection has gone wrong when nothing of the kind ever existed, which \
is the mistake to avoid here."""

#: How the advertised vocabulary is headed when the registry answered names
#: (ADR-0211 §4's first clause).
_VOCABULARY_HEADING: Final = (
    "These are the capabilities this assistant has, and the only names a plan step may carry:"
)

#: What stands in for the list when the registry advertised nothing (ADR-0211 §6).
#:
#: The empty vocabulary is a legal input and never an error, and §6 fixes what the
#: prompt then states: the list admits no step, so the decline is the only shape
#: available for this turn. It is phrased as an *empty list* rather than as the
#: absence of one so that every sentence below referring to "the list above" still
#: has a referent — including the plan shape's condition, which is then trivially
#: unsatisfiable, which is exactly §6's reading.
_EMPTY_VOCABULARY: Final = (
    "This assistant has no capabilities at all right now — the list of what it can "
    "do is empty. No plan step has a name it could carry, so the DECLINE below is "
    "the only shape available for this turn."
)


def _render_vocabulary(capabilities: Sequence[str]) -> str:
    """Render the advertised vocabulary into the block the system prompt states.

    The names are rendered **in the order they were handed**, unchanged: ADR-0016
    §5 already obliges ``ToolRegistry.capabilities()`` to answer a sorted,
    de-duplicated tuple, and ADR-0211 §1 forbids a second normalisation here on the
    ground that it would be a second authority on the vocabulary. Nothing is
    sorted, de-duplicated, folded or filtered — the value is stated as it arrived.

    Each name goes through :func:`_quoted_span` for the reason a facet's ``source``
    does: this renderer authored the surrounding block and the name did not, and a
    capability is only a :data:`~ai_assistant.core.types.VisibleIdentifier` — issue
    #62 leaves internal whitespace and control characters open — so an unquoted one
    could break the block's own line structure. Quoting is a property of the
    *rendering* and not of the value: nothing downstream sees a changed name, which
    is what keeps this clear of §1's no-canonicalisation clause.

    Args:
        capabilities: The vocabulary the registry advertised for this turn.

    Returns:
        The vocabulary block, headed, or :data:`_EMPTY_VOCABULARY` where the
        vocabulary is empty (ADR-0211 §6).
    """
    names = list(capabilities)
    if not names:
        return _EMPTY_VOCABULARY
    listed = "\n".join(f"  {_quoted_span(name)}" for name in names)
    return (
        f"{_VOCABULARY_HEADING}\n\n{listed}\n\n"
        "Take that list as the complete statement of what can be done this turn. A "
        "capability that is not on it cannot be performed, however reasonable it "
        "would be to have one."
    )


#: The prompt above the vocabulary block: the role, the reply rule, and what a step
#: names.
#:
#: **The examples are gone, and their absence is the fix** (ADR-0211, #1772). This
#: paragraph used to close with "Use short snake_case names such as `send_email`,
#: `search_calendar`, or `book_flight`" — and the calendar row of #1772 is a model
#: doing exactly as instructed on a hub whose whole vocabulary was
#: ``report_current_time``. Offering an example vocabulary beside a stated one
#: would reintroduce the defect in the same breath as the correction.
_PROMPT_OPENING: Final = """\
You are the planning stage of an AI assistant. Decide what the user's goal \
requires, then reply with exactly one of the two JSON objects below — a single \
JSON object and nothing else, no prose, no code fence.

A step names an abstract CAPABILITY — what must be done — not a specific tool, \
product, or vendor. Do not name a concrete tool or service.
"""

#: The two legal envelope shapes and the test between them (ADR-0176 §1, ADR-0211
#: §4).
#:
#: The test is stated as what the goal *requires*, judged against the vocabulary
#: above, and never as a list of request categories: the material a goal might be
#: answered from is rendered into this same prompt one message below
#: (:func:`_render_request`), so "can this be answered from what is in front of
#: me?" is a question about text the model is already holding, and a category list
#: is not (ADR-0176 §4). ADR-0211 §4 adds the second half of each side — a plan
#: needs a listed capability able to carry every step, and a goal requiring an act
#: that nothing listed can perform is the decline's second ground.
_PROMPT_SHAPES: Final = """\
Where accomplishing the goal requires the assistant to act in the world, or to \
reach for something this turn has not already given you, and a capability on the \
list above can carry each of those steps, decompose it into an ordered sequence of \
steps and reply with a PLAN:

{"rationale": "<one sentence on why these steps>",
 "steps": [
   {"intent": "<human-readable purpose of this step>",
    "capability": "<a capability from the list above>",
    "parameters": {"<name>": "<json value>"}}
 ]}

Where the goal is answered from what this turn already carries — the retrieved \
memories, the assembled context and the conversation set out in the next message \
— no capability is wanted at all, and the reply is a DECLINE:

{"rationale": "<one sentence on why you are not planning steps>",
 "steps": [],
 "no_capability_needed": true}
"""

#: The prompt below both worked-through directions: ADR-0176 §4's first clause and
#: the envelope's grammar.
#:
#: ``no_capability_needed`` keeps its spelling and its **structural** meaning
#: (ADR-0176 §1, ADR-0211 §5): it asserts that this envelope names no capability,
#: and it is neither read nor cited as an assertion that the goal needed none.
#: Which of the two grounds applies is said by the ``rationale`` and nowhere else,
#: which is why the key is set on both.
_PROMPT_CLOSING: Final = """\
A decline is an ordinary, expected outcome — not a fallback, not an error, not a \
last resort. Naming a capability for a goal that needs none, or one that is not on \
the list above, is the worse answer of the two. Judge which shape is wanted by \
what the goal requires and by what the list above holds, not by what kind of \
request it looks like.

In a plan, `steps` must be a non-empty list, and `parameters` is optional per step \
and, when present, must be a JSON object. In a decline, `steps` must be the empty \
list, `no_capability_needed` must be the JSON literal true (not 1, not "true"), \
and `rationale` must be a non-empty string. Set `no_capability_needed` on either \
kind of decline; it says that this reply names no capability, and the rationale is \
what says why. Do not include step ids; they are assigned downstream."""


#: ADR-0226's envelope, asked for in the prompt (§10's "the prompt that asks for
#: it").
#:
#: **What it asks for is a judgement, and the prompt is written not to bias it.**
#: ADR-0226 §8 makes the trigger "the planner's own judgement that this turn's
#: supply did not suffice", expressed by emitting a request and by nothing else,
#: and makes the live fire rate the instrument that judgement is measured by
#: against the replay's 13.6%. A prompt that talked the model into asking would
#: move the number this milestone exists to read. So the condition is stated as a
#: condition — the goal turns on something the memories below do not carry — and
#: the ordinary case is named as ordinary, in one sentence, rather than argued for.
#:
#: **The labels are §3's and the prohibition is the load-bearing half.** "No record
#: identifier is rendered to a model, and none is accepted from one": the model is
#: shown ``M1``, ``M2`` … in the block below and is told to name those and nothing
#: else, because the failure a fabricated identifier produces is not a crash but "a
#: system in which the model can *steer what it is shown* by naming records it
#: never saw". A label it invents is an index, and an index outside the range it
#: was shown resolves to nothing at the loop, so the widest possible abuse of the
#: mechanism is asking for something already on screen.
#:
#: **It says what the read is not**, because a model that reads "search" reaches
#: for a tool. The read is of the user's own stored memories, performed by this
#: system for this turn: no tool runs, no capability is named, nothing is sent
#: anywhere, and the request is not a step (§4). Saying so is cheaper than
#: discovering a plan that named ``search_memory`` as a capability, which is the
#: shape #1772 already cost this project once.
#:
#: A separate constant for the reason :data:`_STATED_FACT_GUIDANCE` is one: the
#: prompt test can assert it **reaches the model** without string-matching its
#: wording.
_READ_REQUEST_GUIDANCE = """\
Beside either reply you may ask for ONE more read of what this assistant already \
remembers about the user. Most turns need none: where the memories set out in the \
next message, together with the conversation and the context, already carry what \
the goal turns on, ask for nothing.

Where they do not — the goal turns on something said in an earlier conversation, \
by the user or by this assistant itself, and none of the memories below carries \
it — add a `read_request` to whichever object you are sending:

 "read_request": {"query": "<what to look for in the user's own memories>",
                  "labels": ["M3"]}

Each memory in the next message is printed with a label — `M1`, `M2`, `M3` and so \
on, in the order they appear. Both members of `read_request` are optional and you \
may send either or both, but do not send an empty object and do not send the key \
at all unless you are asking for something. `query` is matched against the user's \
stored memories. `labels` names at most TWO of the labels printed below and asks \
for the original exchanges those memories were drawn from — which is the way to \
reach a conversation whose wording you could not guess.

Name only labels that are actually printed in the next message, spelled exactly \
as they are printed there. Do not write a record id, a uuid, a date or any \
identifier of your own: anything that is not one of the labels you were shown \
reaches nothing at all.

This read is of this assistant's own memory of the user and of nothing else. No \
tool runs for it, no capability is named by it, nothing is sent anywhere, and \
nothing is looked up outside this system. It is not a step and it does not belong \
in `steps`. Asking for it does not change which of the two shapes you are \
sending, and you are still answering now from what you have."""


#: ADR-0226 §2's hop, stated as the condition it was admitted for (#1929).
#:
#: **The gap this closes is a factual misreading, not a reluctance to ask.** §8
#: makes the trigger "the planner's own judgement that this turn's supply did not
#: suffice", and the first live probe found that judgement made honestly and
#: wrongly. The supply held a distilled belief reading *"the user asked the
#: assistant to recommend one specific mortgage lender by name … the assistant
#: declined"*; the question was *"which bank did you mention to me as a starting
#: point?"*; the planner read the belief as answering it and asked for nothing. It
#: does not answer it. The belief is a summary of the exchange written afterwards,
#: and the bank's name exists only in the reply it summarises — the summary is in
#: fact wrong about that reply, which named one. §2 admits the hop for exactly
#: this case: it is "**not a search**, so the reply's vocabulary never has to match
#: anything; and it reaches the exchange by pointer, which is the only mechanism
#: that answers 'which lender did you recommend?'". A planner that cannot see the
#: case never reaches the mechanism ADR-0226 bought.
#:
#: **It states a condition and does not argue for asking.** §8 warns that "a
#: prompt that talked the model into asking would move the number this milestone
#: exists to read", and the fire rate is the instrument the milestone is read by.
#: So this block names one class of supply that does not carry one class of
#: answer, and names the neighbouring question the same supply *does* answer — the
#: condition cuts in both directions rather than adding weight to one, and a turn
#: on which the summary suffices is told so in the same breath.
#:
#: **The judgement stays the model's, at §8's one seam.** Nothing in ``planning``
#: inspects a record's text to decide this: the block describes the shape of a
#: claim, the model reads its own supply against it, and the code only reads back
#: what was emitted (:func:`_optional_read_request`). A code-side rule keyed on a
#: record's ``kind`` or on words in its ``content`` would be a second, mechanical
#: trigger beside the judged one, and §8 admits no second seam — "there is no
#: separate flag, no confidence score and no second seam".
#:
#: **It carves out the one supply that does carry the reply.** ADR-0222 §1 renders
#: a ``what the assistant replied:`` line under a **conversation-tail** record and
#: §2 gives the retrieved group none of it (:func:`_reply_lines`), so a turn from
#: this conversation arrives with the assistant's own words and a turn from an
#: earlier one arrives as a phrase. Without the carve-out this block would push a
#: hop for a reply already on the page — a read that costs §6's budget, returns
#: what the model is looking at, and inflates the very rate §8 measures. The block
#: names §1's line rather than describing it, so the model matches what it can see;
#: that couples this text to that rendering, and
#: ``test_the_carve_out_names_the_line_the_tail_actually_renders`` is what keeps
#: the two from drifting apart silently.
#:
#: **And the carve-out has its own exception, because §4's ceiling makes the line
#: a prefix.** A reply longer than :data:`_REPLY_CEILING` renders as ``what the
#: assistant replied (first N of M characters): ...``, and ADR-0222 §4 is explicit
#: that the prefix is not the reply. :func:`_reply_lines` already draws exactly
#: this line — "an unelided reply carries no marker, and that absence is what says
#: the line carries the reply whole" — so a carve-out that read the elided form as
#: complete would tell the planner a fact it cannot see is present, which is
#: #1929's own failure in a second costume: a rendering mistaken for the exchange.
#: The block names the elided shape too and says what it is worth.
#:
#: **And what it is worth is nothing a read can add, which is why the block states
#: it as a bound rather than pointing at the hop.** A tail record is written by
#: ``orchestration/conversations.py`` with no ``Provenance.evidence``, and ADR-0226
#: §2's hop resolves *the labelled record's evidence* and returns only that — the
#: labelled record's own id rides in the ``get_many`` for §3's liveness check and
#: is not among the records the hop yields. So naming an elided tail turn's label
#: fires a serviced read with a zero yield, which §8 is explicit is "precisely the
#: population … *not* evidence the trigger was wrong" and which spends §6's budget
#: for nothing. §7's deduplication closes the indirect route too: an episode
#: already in the supply is subtracted from the fourth group whichever belief cites
#: it. An earlier draft of this block said "the label is still the way to it" and
#: was wrong on all three counts.
#:
#: A separate constant for :data:`_STATED_FACT_GUIDANCE`'s reason: the prompt test
#: can assert it **reaches the model** without string-matching its wording.
_ACT_RECORD_GUIDANCE = """\
One shape of memory is easy to read as an answer it does not hold. A memory that \
says what this assistant did or said in an earlier conversation — that it \
recommended, named, suggested, quoted, explained or declined — is a summary of \
that exchange, written afterwards. It records that the exchange happened and what \
it was about. It is not a copy of what was said, and the words of the reply are \
exactly what such a summary leaves out.

So where the goal turns on the content of that act — which one was named, what \
word was used, what was actually said — a memory of that shape does not carry the \
answer, however complete an account of the exchange it sounds like. That holds \
just as much when the summary says nothing was named at all, or that the request \
was refused: "I declined" is still the summary's account of the reply and not the \
reply, and a summary written afterwards can be wrong about what was in fact said. \
Answering "there was no such bank" from a memory that says one was never named is \
answering from the summary. This is what `labels` is for: name that memory's \
label, and what comes back is the original exchange it was drawn from, in the \
wording it actually had.

None of this widens the ordinary case, and two kinds of turn are outside it. \
Where the goal turns instead on whether that exchange happened, when it was, what \
it was about, or what the user asked for, the same memory answers it as asked, and \
there is nothing to ask for — even though that exchange also had wording you \
cannot see. And where a bullet below is printed with a `what the assistant \
replied:` line under it, that line is the reply itself in the words it was sent, \
not a summary of it: a question about its content is answered from it, and asking \
for the exchange it is already showing you would buy nothing. That carve-out has a limit of \
its own, and the limit is not a second thing to ask for. A line reading `what the \
assistant replied (first 200 of 900 characters): ...` is showing you the opening \
of the reply and not the reply, so what the goal turns on may be in the part you \
cannot read. No read brings that remainder back, and naming that turn's own label \
does not: it is a bound on what you can answer from, not a reason to ask."""


def _system_prompt(capabilities: Sequence[str]) -> str:
    """Build the planning system prompt over the vocabulary advertised this turn.

    A function rather than a constant because ADR-0211 §4 makes the vocabulary part
    of what the prompt *states*: the list of names a step may carry, the test
    between the two envelope shapes judged against it, and the rationale a decline
    on its second ground owes. A prompt cannot state a vocabulary it was not given,
    which is why #1772's remedy — "state the decline test harder" — could not have
    worked on its own.

    The blocks are assembled in a fixed order, and one ordering is load-bearing
    rather than aesthetic: both worked-through directions
    (:data:`_STATED_FACT_GUIDANCE`, :data:`_UNAVAILABLE_GUIDANCE`) sit **below** the
    rendered envelopes, because a reader meeting a direction before the shape it
    belongs to has been told what to reply before being told what a reply looks
    like. :data:`_READ_REQUEST_GUIDANCE` sits last for the same reason carried one
    step further: it adds an optional key to *both* shapes and to the choice
    between them it adds nothing, so it is read after the choice has been made.
    :data:`_ACT_RECORD_GUIDANCE` sits below that block again, because it is a
    condition on the read the block has just described and says nothing a reader
    who has not met `labels` yet could use (#1929).

    **It is stated unconditionally, where the vocabulary is not.** ADR-0211 §6
    makes the empty vocabulary a case the prompt must speak to, because a list that
    admits no step changes which shape is available. An empty supply changes no
    shape: it means no label is printed below, and ADR-0226 §3's rule — name only a
    label actually printed — already says what that leaves askable, without this
    function taking a second input to say it twice.

    Args:
        capabilities: The vocabulary the registry advertised for this turn, taken
            as handed (ADR-0211 §1). Empty is legal (ADR-0211 §6).

    Returns:
        The system turn for this call.
    """
    return "\n".join(
        (
            _PROMPT_OPENING,
            _render_vocabulary(capabilities),
            "",
            _PROMPT_SHAPES,
            _STATED_FACT_GUIDANCE,
            "",
            _UNAVAILABLE_GUIDANCE,
            "",
            _PROMPT_CLOSING,
            "",
            _READ_REQUEST_GUIDANCE,
            "",
            _ACT_RECORD_GUIDANCE,
        )
    )


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _ExtractionError(Exception):
    """An internal signal that a model reply could not become an ``ActionPlan``.

    Caught within :meth:`ModelBackedPlanner.plan` to drive the bounded repair
    round; converted to :class:`PlanningError` if the attempts are exhausted. Not
    part of the public surface.

    ``declined`` says whether the failed reply **carried the decline marker** and
    failed only ADR-0176 §3's rationale condition. It selects the repair message
    (:func:`_repair_prompt`), and it is a flag on the signal rather than a string
    match on the reason because §5 splits the two failures on evidence of intent:
    only a reply carrying the marker has said what it meant, so only there may the
    repair ask the model to complete the decline. Every other malformed reply —
    a bare empty ``steps`` list included — is unclassified, and its repair presents
    both shapes without naming either as the correction.
    """

    def __init__(self, message: str, *, declined: bool = False) -> None:
        """Record the reason and whether the reply asserted a decline.

        Args:
            message: What was wrong with the reply, echoed into the repair turn.
            declined: Whether the reply carried the ``no_capability_needed``
                marker and failed only the rationale condition (ADR-0176 §5).
        """
        super().__init__(message)
        self.declined = declined


class ModelBackedPlanner:
    """A ``Planner`` that decomposes a goal into capabilities with an LLM.

    Structurally implements :class:`~ai_assistant.core.protocols.Planner`. The
    model proposes each step's ``intent``, ``capability`` and ``parameters``; this
    class mints the ids, stamps the timestamp, validates the result into a frozen
    :class:`~ai_assistant.core.types.ActionPlan`, and owns the failure handling
    (ADR-0047).
    """

    def __init__(
        self,
        model: ModelProvider,
        *,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
        max_attempts: int = DEFAULT_PLAN_ATTEMPTS,
    ) -> None:
        """Create a planner over an injected model, clock and id factory.

        Args:
            model: The model seam used to draft the plan. The only dependency on
                the LLM; no provider SDK is imported (golden rule 4).
            now: Clock for ``ActionPlan.created_at``; injectable for deterministic
                tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock` (ADR-0026 §7), so a
                non-conforming reading surfaces as ``PlanningError``.
            id_factory: Mints the plan id and every step id; injectable so tests
                assert exact ids (ADR-0047 §2). Defaults to random UUIDs.
            max_attempts: Total ``complete`` calls one ``plan`` may make — one
                request plus up to ``max_attempts - 1`` bounded repair rounds
                (ADR-0047 §6). Must be an ``int`` of at least 1.

        Raises:
            TypeError: If ``max_attempts`` is not an ``int`` (``bool`` included).
            ValueError: If ``max_attempts`` is less than 1.
        """
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            msg = f"max_attempts must be an integer, got {max_attempts!r}"
            raise TypeError(msg)
        if max_attempts < 1:
            msg = f"max_attempts must be at least 1, got {max_attempts}"
            raise ValueError(msg)
        self._model = model
        self._clock = checked_clock(now, owner="ModelBackedPlanner")
        self._id_factory = id_factory
        self._max_attempts = max_attempts

    def _now(self) -> datetime:
        """The guarded clock's reading, translated to this subsystem's error.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming one
                — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan:
        """Produce a frozen plan for ``goal`` (ADR-0047).

        Prompts the model for a JSON envelope, extracts and validates it into a
        plan, and retries once on malformed output before giving up. ``context``,
        ``memories`` and ``capabilities`` are rendered into the prompt — the
        memories are what make the plan personal (ADR-0014 §6), the vocabulary is
        what the plan is judged against (ADR-0211 §4) — and none of the three is
        ever fetched here.

        **The vocabulary is stated, not enforced** (ADR-0211 §6). It is rendered
        into the system turn and nothing downstream of the model checks a returned
        step against it: no post-parse vocabulary test lives here, and no reply is
        converted into a decline on the ground that its capability is unadvertised.
        Three reasons, and the first is decisive on its own — ADR-0053's alias layer
        resolves an emitted name onto an advertised one at *selection* time, so a
        check here would refuse ``send_mail`` on a hub advertising ``send_email``, a
        plan the layer would have resolved and the tool would have performed. This
        module cannot consult that layer either: it lives in `orchestration`, and
        `planning` importing it is an architecture violation ``lint-imports``
        fails. What an out-of-vocabulary name still gets is what it always got —
        the alias layer, then ``NO_CAPABLE_TOOL`` (ADR-0037 §1).

        ``goal`` is observed **once**, on this coroutine's first executed line and
        before the first ``await`` (ADR-0065). ``Goal`` is mutable, the model call
        is the widest suspension window in the system, and a caller that mutated
        its own instance mid-flight would otherwise get an ``ActionPlan`` whose
        frozen, auditable ``goal_id`` names a goal the model was never shown. The
        prompt, the plan's ``goal_id`` and the failure message all derive from
        that one snapshot. ``context``, ``memories`` and ``capabilities`` need no
        snapshot: each is read once, into the prompt, before the same first
        ``await`` and never again — the other discharge the clause allows.

        ``memories`` carries what the pipeline assembled for this turn, which
        ADR-0074 §5 widened from "relevant, best first" to the conversation's
        recent turns first and then the relevance-retrieved records. This planner
        renders the sequence **in the order it is handed** and reads no global
        ranking into it, which is exactly what that widening asks of a consumer
        (:meth:`~ai_assistant.core.protocols.Planner.plan`).

        Args:
            goal: The objective to plan for.
            context: The situational context assembled for this request.
            memories: The records the pipeline assembled for this turn — the
                conversation's recent turns in order, then records retrieved as
                relevant, best first within that group (ADR-0074 §5).
            capabilities: The capability vocabulary the registry advertised for
                this turn (ADR-0211 §1), rendered into the system prompt as the
                names a step may carry. Taken as handed — neither re-sorted,
                de-duplicated nor canonicalised — and read once, into the prompt,
                before the first ``await``. An empty vocabulary is legal and is
                stated as such (ADR-0211 §6); it raises nothing and drives no
                repair round.

        Returns:
            A frozen :class:`~ai_assistant.core.types.ActionPlan` for ``goal``.

        Raises:
            PlanningError: If no valid plan could be extracted within
                ``max_attempts`` model calls, or if the injected clock misreads.
            ModelError: Propagated unwrapped from the provider — a transport,
                auth, rate-limit or content-filter failure is already a typed,
                actionable error and is not flattened into ``PlanningError``
                (ADR-0047 §6).
        """
        # Deep, so nothing nested stays shared with the caller's instance; a
        # `model_copy(update=...)` here would be shallow and would not detach it.
        snapshot = goal.model_copy(deep=True)
        conversation: list[Message] = [
            Message(role=Role.SYSTEM, content=_system_prompt(capabilities)),
            Message(role=Role.USER, content=_render_request(snapshot, context, memories)),
        ]

        last_error: _ExtractionError | None = None
        for _ in range(self._max_attempts):
            reply = await self._model.complete(conversation)
            try:
                return self._build_plan(reply.content, snapshot)
            except _ExtractionError as exc:
                last_error = exc
                conversation.append(reply)
                conversation.append(
                    Message(
                        role=Role.USER,
                        content=_repair_prompt(str(exc), declined=exc.declined),
                    ),
                )

        msg = f"the model did not return a usable plan for goal {snapshot.id}: {last_error}"
        raise PlanningError(msg)

    def _build_plan(self, content: str, goal: Goal) -> ActionPlan:
        """Extract and validate one model reply into a frozen ``ActionPlan``.

        A **decline** — an empty ``steps`` list carrying the ``no_capability_needed``
        marker — is constructed by this same path with ``steps=()``, which is why
        ADR-0176 §1 keeps one envelope shape rather than two: the per-step
        validation below is vacuous over it and nothing else branches. Its
        ``rationale`` is required rather than optional (§3), because with no steps
        it is the whole of what the persisted plan says.

        The envelope's keys never reach ``model_validate``: the payload is an
        explicit six-key mapping, so ``no_capability_needed`` cannot leak into the
        durable ``ActionPlan`` (ADR-0176 §8). That is structural, not asserted, and
        it is why ADR-0226 §4's ``read_request`` is read by
        :func:`_optional_read_request` into a validated model rather than passed
        through as whatever the model wrote.

        **A malformed request never costs the plan** (:func:`_optional_read_request`
        holds the argument): it is dropped, the plan is built without one, and no
        repair round is spent on it.

        Raises:
            _ExtractionError: If the text is not one of the two legal envelopes or
                the constructed plan fails a ``core`` invariant.
        """
        envelope = _extract_object(content)
        raw_steps = _require_steps(envelope)
        rationale = _optional_rationale(envelope) if raw_steps else _require_rationale(envelope)

        step_payloads = [self._step_payload(raw, index) for index, raw in enumerate(raw_steps)]
        try:
            return ActionPlan.model_validate(
                {
                    "id": self._id_factory(),
                    "goal_id": goal.id,
                    "steps": step_payloads,
                    "created_at": self._now(),
                    "rationale": rationale,
                    "read_request": _optional_read_request(envelope),
                }
            )
        except ValidationError as exc:
            msg = f"the drafted plan is not a valid ActionPlan: {exc}"
            raise _ExtractionError(msg) from exc

    def _step_payload(self, raw: object, index: int) -> PlanStep:
        """Validate one raw step object into a ``PlanStep`` with a minted id.

        Raises:
            _ExtractionError: If the step is not an object with the required
                fields, or fails a ``PlanStep`` invariant (e.g. a blank
                capability, or non-serialisable parameters).
        """
        if not isinstance(raw, dict):
            msg = f"step {index} is not a JSON object"
            raise _ExtractionError(msg)

        intent = raw.get("intent")
        capability = raw.get("capability")
        if not isinstance(intent, str):
            msg = f"step {index} is missing a string 'intent'"
            raise _ExtractionError(msg)
        if not isinstance(capability, str):
            msg = f"step {index} is missing a string 'capability'"
            raise _ExtractionError(msg)

        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            msg = f"step {index} has non-object 'parameters'"
            raise _ExtractionError(msg)

        try:
            return PlanStep.model_validate(
                {
                    "id": self._id_factory(),
                    "intent": intent,
                    "capability": capability,
                    "parameters": parameters,
                }
            )
        except ValidationError as exc:
            msg = f"step {index} is not a valid PlanStep: {exc}"
            raise _ExtractionError(msg) from exc


def _optional_read_request(envelope: dict[str, object]) -> ReadRequest | None:
    """Read ADR-0226 §4's ``read_request`` out of one envelope, or return ``None``.

    Builds at most one ask of each kind from the two optional members the prompt
    asks for — a non-blank ``query`` becomes a ``SIGHTED_QUERY`` ask, a list of one
    or two label strings becomes a ``CITATION_HOP`` ask — and hands them to
    :class:`~ai_assistant.core.types.ReadRequest`, whose validators are the
    authority on every condition §4 states. An envelope carrying no ``read_request``,
    or one from which no ask could be built, yields ``None``, which ADR-0226 §4
    fixes as "the planner asked for no read".

    **A malformed request is dropped and never sent to bounded repair, which is a
    decision rather than leniency.** ADR-0176's own reasoning about the decline
    marker is directly on point: type-checking a key "would send a perfectly good
    plan to bounded repair over a key that decides nothing on that shape", and
    ADR-0047 §4's envelope rule is that other keys are ignored. The plan is what the
    turn needs; the request is one additive extra whose absence is exactly the
    system as it stands, so failing an otherwise-valid plan over it would trade the
    turn's whole answer for its least consequential part. Each drop is logged, so
    what is lost is visible rather than silent.

    **The honest cost is named** (ADR-0226 §8). A dropped emission is recorded as a
    turn on which the trigger did not fire, so a planner writing malformed requests
    under-reports its own fire rate. That is why the logged counter exists: §8's
    figure is read against the replay's 13.6%, and a deployment reading a low one
    can see from :data:`_READ_REQUEST_DROPPED` whether the emissions were absent or
    merely unreadable.

    **Nothing here filters a label against the supply**, and that is ADR-0226 §3
    working rather than an omission. §3 gives label resolution to the loop and rules
    that a label outside the shown set "resolves to nothing … discarded silently"
    and is "recorded in §9's audit as dropped". A planner that quietly dropped its
    own out-of-range labels would empty that audit field of the very population it
    exists to count.

    Args:
        envelope: The decoded model envelope, plan-shaped or decline-shaped.

    Returns:
        The request the planner emitted, or ``None`` where it emitted none or
        emitted one that could not be read.
    """
    raw = envelope.get("read_request")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        _log.info(_READ_REQUEST_DROPPED, reason="not_an_object")
        return None

    asks: list[ReadAsk] = []
    query = raw.get("query")
    if query is not None:
        if isinstance(query, str) and query.strip():
            asks.append(ReadAsk(kind=ReadKind.SIGHTED_QUERY, query=query))
        else:
            _log.info(_READ_REQUEST_DROPPED, reason="unusable_query")

    labels = raw.get("labels")
    if labels is not None:
        asks += _hop_ask(labels)

    if not asks:
        _log.info(_READ_REQUEST_DROPPED, reason="no_usable_ask")
        return None
    try:
        return ReadRequest(asks=tuple(asks))
    except ValidationError:
        # Belt and braces: every condition above is already the model's, so this is
        # unreachable today. It is here because a `core` invariant this module has
        # not anticipated must cost the request and never the plan.
        _log.info(_READ_REQUEST_DROPPED, reason="refused_by_core")
        return None


def _hop_ask(labels: object) -> list[ReadAsk]:
    """Build the ``CITATION_HOP`` ask from an envelope's ``labels``, or nothing.

    The labels are taken **verbatim and in the order the model named them**, which
    ADR-0226 §6 makes the order they are followed in. Their *form* is not checked
    here — §3 gives that to the loop, which resolves a label by parsing its ordinal
    and indexing the sequence it passed, and discards silently what does not
    resolve.

    Args:
        labels: The envelope's ``labels`` member, whatever the model wrote there.

    Returns:
        A one-element list holding the ask, or an empty list where the member is
        not a list of one or two strings (ADR-0226 §4, §6).
    """
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        _log.info(_READ_REQUEST_DROPPED, reason="labels_not_a_list_of_strings")
        return []
    named = [label for label in labels if isinstance(label, str)]
    if not named or len(named) > MAX_HOP_LABELS:
        _log.info(_READ_REQUEST_DROPPED, reason="label_count_out_of_bounds")
        return []
    return [ReadAsk(kind=ReadKind.CITATION_HOP, labels=tuple(named))]


def _render_request(
    goal: Goal,
    context: CurrentContext,
    memories: Sequence[MemoryRecord],
) -> str:
    """Render the goal, context and memories into the user-turn prompt.

    The memories are rendered by :func:`_render_record`, each tagged with its kind,
    its provenance source, its band and its confidence, because passing the
    retrieved user model into the prompt is what makes a plan personal rather than
    generic (ADR-0014 §6). A record is one bullet; an episode that recorded an
    outcome adds one continuation line under its own bullet, which is why the
    groups are assembled by joining rendered records rather than counted as lines.

    ``memories`` carries two groups (ADR-0074 §5) and they are headed separately,
    because one header calling both "relevant memories" tells the model a
    chronological conversation tail is a relevance cut — the strain §5 refused to
    accept in the Protocol's wording. The records are rendered **in the order they
    were handed**, unchanged; the header is inserted at the boundary, nothing is
    reordered or dropped.

    **The tail group, and only the tail group, also renders what the assistant
    replied** (ADR-0222 §1 and §2). :func:`_reply_lines` is called from the tail loop
    and from nowhere else, so the reply reaches this prompt for a record of the
    conversation the turn is *in* and never for one relevance retrieved: §2 keeps the
    retrieved group phrase-only on three independent grounds, of which the narrowest
    is that a record retrieved by content was not retrieved for a reply nothing
    embedded. It is also the group split that keeps ``benchmarks/`` still, since
    ``planner._split_conversation_tail`` over the harness's records always returns an
    empty leading run.

    **§5's counter pair is emitted here, once per assembly, and always.** One
    statement carries both integers — the records eligible to render a reply, and how
    many §4's ceiling bound on — so the denominator and the numerator of the elision
    share are observed together and lost together (ADR-0141 §6's rule for the
    duplicate share). An assembly with no eligible record reports ``0`` and ``0``
    rather than staying silent, so a missing pair is distinguishable from an empty
    one, and the statement carries **no reply text** at all (ADR-0004 §5, ADR-0221
    §11's test 14). ADR-0222 §5 states why these two counts cannot ride an
    ``OPERATION`` trace instead.

    ``context``'s facets are rendered by :func:`_render_facets` under the same
    "Current context:" heading as the four temporal scalars, and **below** them:
    the scalars are this system's own reading of its own clock, a facet is a
    source's report, and ADR-0098 §2 requires the two be distinguishable in the
    assembled prompt. A facet that is ``None`` contributes nothing at all — no
    line, no header, no mention of its source — because ADR-0096 §4 and ADR-0097
    §5 rule ``None`` the single absence that "does not distinguish unconfigured,
    disabled, never-read, ungranted, failed or empty".
    """
    lines = [
        "Goal:",
        f"  statement: {goal.statement}",
        f"  status: {goal.status.value}",
        f"  provenance: {goal.provenance.source.value}",
    ]
    if goal.deadline is not None:
        lines.append(f"  deadline: {goal.deadline.isoformat()}")

    lines += [
        "",
        "Current context:",
        f"  now: {context.now.isoformat()}",
        f"  time_of_day: {context.time_of_day.value}",
        f"  is_weekend: {context.is_weekend}",
        f"  within_working_hours: {context.within_working_hours}",
    ]
    lines += _render_facets(context)
    lines.append("")

    eligible = elided = 0
    if memories:
        turns, retrieved = _split_conversation_tail(memories)
        if turns:
            lines.append(_TAIL_HEADING)
            for ordinal, record in enumerate(turns, start=1):
                lines.append(_render_record(record, label=_label(ordinal)))
                reply = _reply_lines(record)
                lines += reply.lines
                eligible += reply.eligible
                elided += reply.elided
            if retrieved:
                lines.append("")
        if retrieved:
            lines.append(_RETRIEVED_HEADING)
            lines += [
                _render_record(record, label=_label(ordinal))
                for ordinal, record in enumerate(retrieved, start=len(turns) + 1)
            ]
    else:
        lines.append("No stored memories were retrieved for this goal.")

    _log.info("planner_tail_replies_rendered", eligible=eligible, elided=elided)
    return "\n".join(lines)


def _render_facets(context: CurrentContext) -> list[str]:
    """Render the present facets of ``context``, or nothing at all.

    ``CurrentContext``'s facets are the only part of the assembled prompt this
    system did not itself author, so the block they land in is headed as a
    *report* and each one names the source that made it. That is ADR-0096 §7's
    floor — "a surface that presents a facet's content names the facet's
    ``source``, and may not present that content as the user's own statement, as
    this system's inference, or as a reading of our own clock" — and ADR-0098 §2's
    first clause read on the same spans.

    **An absent facet renders nothing, and the header is not printed either.**
    ADR-0096 §4 fixes ``None`` as the single absence and ADR-0097 §5 adds
    ungranted to what it hides; a header printed over an empty block would be this
    renderer reporting that a source *could* have spoken, which is the "grant
    conversation conducted by a field nobody designed" both sections forbid.

    Args:
        context: The assembled context whose facets are to be rendered.

    Returns:
        The block's lines, or an empty list when every facet is ``None``.
    """
    blocks: list[list[str]] = []
    if context.calendar is not None:
        blocks.append(_render_calendar_facet(context.calendar))
    if context.email is not None:
        blocks.append(_render_email_facet(context.email))
    if not blocks:
        return []

    lines = [
        "  Reported by the sources this system read for this request — each block",
        "  below is that source's own report, not the user's words and not this",
        "  system's own conclusion:",
    ]
    for block in blocks:
        lines += block
    return lines


def _render_calendar_facet(facet: CalendarFacet) -> list[str]:
    """Render one calendar facet's stamp and payload (ADR-0096 §6).

    ``next_starts_at`` being ``None`` is rendered as what §6 says it means — the
    reading found no later occurrence **within the window it covered** — and never
    as "there is nothing next", which §6 forbids a surface from presenting. That is
    also why ``covers_until`` is rendered unconditionally: it is the field §6
    carries so that a ``None`` here means something to a consumer who does not read
    ``Settings``.
    """
    lines = _render_facet_stamp(facet)
    lines.append(f"      entries in progress at that read: {facet.entries_in_progress}")
    if facet.next_starts_at is None:
        lines.append("      no later entry began within the window this reading covered")
    else:
        lines.append(
            f"      the next entry within that window begins at: {facet.next_starts_at.isoformat()}"
        )
    lines.append(
        "      the window this reading covered ended, exclusive, at: "
        f"{facet.covers_until.isoformat()}"
    )
    return lines


def _render_email_facet(facet: EmailFacet) -> list[str]:
    """Render one email facet's stamp and payload (ADR-0140 §6).

    The count's label says *parsed from the store*, because §6 rules that
    ``arrived_in_window`` "is not a claim about the account, is never presented as
    one, and no consumer may read it as a count of mail received" — the store is
    written by a fetcher outside this system whose completeness the reader cannot
    verify. ``covers_from`` is rendered with it for ``covers_until``'s reason
    (ADR-0096 §6): a count means nothing without the interval it counted over, and
    the window's upper edge is ``read_at`` itself (ADR-0140 §3), already on the
    stamp line.
    """
    lines = _render_facet_stamp(facet)
    lines.append(
        "      messages this reader parsed from its own store, arriving since "
        f"{facet.covers_from.isoformat()}: {facet.arrived_in_window}"
    )
    return lines


def _render_facet_stamp(facet: ContextFacet) -> list[str]:
    """Render the source line every facet block opens with (ADR-0096 §2, §7).

    ``read_at`` is labelled as **this system's** read, never as the source's own
    instant, and ``as_of`` — the only instant the source itself declares — is
    rendered only when the source declared one. Where it is ``None`` the block says
    nothing whatever about when the source's picture was current, rather than
    substituting ``read_at`` for it: that substitution is exactly what ADR-0096 §7's
    second clause forbids, and for the two producers that exist ``as_of`` is always
    ``None``, so it is the live case rather than the defensive one.
    """
    lines = [
        f"    - the source {_quoted_span(facet.source)}, which this system read at "
        f"{facet.read_at.isoformat()}:"
    ]
    if facet.as_of is not None:
        lines.append(
            f"      the source says its own picture was current at: {facet.as_of.isoformat()}"
        )
    return lines


def _quoted_span(value: str) -> str:
    """Render one held string so it cannot write this renderer's own syntax.

    ADR-0098 §2 rules that a span's attribution is "not forgeable from inside the
    span" and that "an assembler that embeds a span in a syntax the serialised span
    can itself produce does not conform, whatever labels it emits". This block's
    syntax is line-oriented — a newline, an indent and a ``- the source`` bullet —
    and a facet's ``source`` is the one field of it that is free text:
    ``NonBlankEncodableText`` refuses a blank value and validates UTF-8
    encodability, and permits every newline and bracket in between.

    :func:`json.dumps` is the deterministic transform §2 admits, chosen over an
    invented one because its escaping is total for this target rather than
    plausible: at its default ``ensure_ascii=True`` the result is single-line,
    printable ASCII, delimited by quotes the value can no longer close. So no
    ``source`` — however it was constructed — can open a second bullet, forge a
    second source, or reopen the "Current context:" heading.

    :func:`_render_record` applies it too, to the two spans a memory record
    controls, reusing this function rather than inventing a second transform —
    which is the point of naming it here. ``learning/observer.py`` assembles its own
    prompt and so holds its own copy of the same construction rather than importing
    this one, which is golden rule 1 rather than an oversight.

    Args:
        value: The held string, verbatim as this system carries it.

    Returns:
        The quoted, escaped span to interpolate into a prompt line.
    """
    return json.dumps(value)


#: ADR-0222 §4's ceiling on one rendered reply, counted on the **output** of
#: :func:`_quoted_span` with its delimiters included.
#:
#: **Written out here and not imported**, which is §4's own instruction: three
#: subsystems rendering their own prompts do not reach across a boundary golden
#: rule 1 forbids them to cross, so what ``learning/observer.py``,
#: ``orchestration/composing.py`` and this module share is the ADR's number rather
#: than a module — exactly as ADR-0221 §3 has them hold three copies of one phrase
#: table. ADR-0222 §12 defers promoting it to a ``Settings`` field until §5's
#: counter pair says a deployment wants a different one.
#:
#: **On the quoted rendering, because the expansion is not uniform** (§4). At
#: ``ensure_ascii=True`` a newline costs two output characters, a BMP code point six
#: and an astral one — an emoji — twelve, because :func:`json.dumps` writes it as two
#: surrogate escapes rather than one. A ceiling on *source* characters would admit a
#: span six or twelve times this long while claiming to admit this much; counted on
#: the output there is nothing left to get wrong. 640 is roughly a hundred words of
#: English, about 105 CJK code points and about 53 emoji.
_REPLY_CEILING: Final = 640

#: The two quote characters :func:`json.dumps` puts around every span. Subtracted
#: from the ceiling in :func:`_bounded_reply` to bound the search, because a prefix
#: of *k* characters always renders to at least ``k + 2``.
_QUOTE_DELIMITERS: Final = 2


class _BoundedReply(NamedTuple):
    """One reply's quoted span, and whether ADR-0222 §4's ceiling bound on it.

    Attributes:
        span: The rendering to interpolate — at most :data:`_REPLY_CEILING`
            characters, delimiters included.
        kept: How many of the reply's **own** characters the span carries, or
            ``None`` where the whole reply fitted. ``None`` is what §5's "an
            unelided reply carries no marker" is read off, and the integer is the
            first of the two numbers §5 puts in the marker.
    """

    span: str
    kept: int | None


def _bounded_reply(reply: str) -> _BoundedReply:
    """The longest prefix of ``reply`` whose quoted rendering fits §4's ceiling.

    **The cut is taken on the source text although the ceiling is measured on the
    output** (ADR-0222 §4). Slicing the *quoted* form could split a six-character
    unicode escape, or one half of the surrogate pair an astral code point renders
    as, and produce a span that is not valid JSON at all; slicing the reply's own
    characters cannot, because a Python string holds code points and
    :data:`~ai_assistant.core.types.EncodableText` refuses a lone surrogate at the
    type boundary. So the prefix is chosen over the reply's characters and
    *measured* by rendering it.

    **A binary search, bounded by arithmetic rather than by the reply's length.**
    The quoted length is non-decreasing in the prefix length — each further
    character adds its own escape and nothing is removed — so the predicate is
    monotone. The search's upper bound is ``_REPLY_CEILING - _QUOTE_DELIMITERS``
    rather than ``len(reply)`` because every character costs at least one output
    character, so a longer prefix cannot fit whatever it is made of. That keeps this
    function's cost independent of how long the stored reply is, which matters
    because :data:`~ai_assistant.core.types.EncodableText` bounds no length.

    Args:
        reply: The stored reply, verbatim as this system holds it.

    Returns:
        The span to render, and the prefix length where the ceiling bound —
        ``kept`` is ``None`` exactly when the whole reply is rendered.
    """
    low = 0
    high = min(len(reply), _REPLY_CEILING - _QUOTE_DELIMITERS)
    while low < high:
        middle = (low + high + 1) // 2
        if len(_quoted_span(reply[:middle])) <= _REPLY_CEILING:
            low = middle
        else:
            high = middle - 1
    return _BoundedReply(_quoted_span(reply[:low]), None if low == len(reply) else low)


class _ReplyLines(NamedTuple):
    """One tail record's reply line, and ADR-0222 §5's two counts of it.

    The counts ride out of the renderer rather than being recomputed over the tail,
    because eligibility and elision are decided *here* — by reading the two fields
    and by rendering the reply — and a second walk to count them is a second
    implementation of §1's and §4's conditions to disagree with the first.

    Attributes:
        lines: The continuation line to write under the record's own bullet, or
            nothing where the record is not one §1 admits.
        eligible: ``1`` where the record was eligible to render a reply under
            ADR-0222 §1 — a conversation-tail episode carrying a ``disposition``
            **and** an ``outcome`` — and ``0`` otherwise. §5's denominator, per
            record.
        elided: ``1`` where §4's ceiling bound on that reply, ``0`` otherwise. §5's
            numerator, per record, and never greater than ``eligible``.
    """

    lines: list[str]
    eligible: int
    elided: int


def _reply_lines(record: MemoryRecord) -> _ReplyLines:
    """The reply line ADR-0222 §1 adds under one **conversation-tail** record's bullet.

    **Called by the tail assembler and never by :func:`_render_record`, and that is
    what keeps the benchmark harness still** (§1's third clause). ``benchmarks/
    memory/answer.py`` imports ``_render_record`` by name and calls it directly, so
    anything put *inside* that function would reach the harness's prompt whether or
    not the harness meant to build a tail. Emitting the line from the caller makes
    §2's "no benchmark result moves" true by construction rather than by a gate the
    harness would have to keep passing — and it is the shape
    ``composing._render_delivery`` already has for ADR-0205 §5's delivery fact, which
    "is written under the turn it is about, and only in the tail".

    **The reply is rendered beside the phrase and never instead of it** (§1). The
    ``how it turned out:`` line :func:`_render_record` emits is unchanged, is
    rendered first, and states what became of the pass — a typed fact this system
    authored about its own pipeline. This line states what the user was actually
    shown. A reply saying "I've set that up for you" beside a phrase saying the
    action was parked for confirmation is the pair a model needs; either alone is a
    half-truth, so no site is permitted to trade one for the other.

    **The retrieved group gets none of this** (§2), which is why this function is
    called from one arm of :func:`_render_request` and not from both. A retrieved
    episode was not retrieved *for* its reply — retrieval is content-addressed and
    ``outcome`` is not embedded — so rendering it there would spend budget on prose
    no part of the selection ever read.

    **The marker is held data and sits outside the quoted span** (§5, ADR-0098 §2).
    A marker written *inside* the quoted reply is a string the reply itself could
    contain, so a reply ending in this system's own elision wording would render as
    though it had been cut when it had not. Both numbers come from :func:`len` over
    held text and the wording is a literal here, so neither is reachable from the
    reply; an unelided reply carries no marker, and that absence is what says the
    line carries the reply whole.

    Args:
        record: One record of the conversation-tail group.

    Returns:
        The line to write under its bullet, and §5's two counts for this record.
    """
    if not isinstance(record, EpisodicMemory):  # pragma: no cover — the tail is episodic
        return _ReplyLines([], eligible=0, elided=0)
    if record.disposition is None or record.outcome is None:
        return _ReplyLines([], eligible=0, elided=0)
    span, kept = _bounded_reply(record.outcome)
    if kept is None:
        return _ReplyLines([f"    what the assistant replied: {span}"], eligible=1, elided=0)
    return _ReplyLines(
        [
            f"    what the assistant replied "
            f"(first {kept} of {len(record.outcome)} characters): {span}"
        ],
        eligible=1,
        elided=1,
    )


def _label(ordinal: int) -> str:
    """ADR-0226 §3's label for the record at 1-based ``ordinal`` of ``memories``.

    "The label of the record at 1-based index *n* of ``Planner.plan``'s ``memories``
    is the ASCII string ``M`` followed by *n* in decimal with no padding. That is
    the whole of the scheme: it is fixed here, it is the same on both sides of the
    seam, and no later lane substitutes another spelling, adds a prefix per group,
    or makes it configurable."

    **The ordinal is what keeps the label from becoming a private protocol between
    two subsystems** (§3). A scheme in which `planning` invented labels and
    `orchestration` resolved them would need the two to agree on an allocation
    appearing in no contract — a coordination golden rule 1 forbids and no test in
    either package would catch. Deriving the label from the position in the
    sequence the loop itself passed removes the agreement entirely: both sides read
    the same ordered value, and the loop resolves against its own copy. **So this
    function is not imported by `orchestration` and must not become shared** — §10
    forbids any value crossing the two packages other than the ``memories``
    sequence and the ``ActionPlan`` that already cross it, and the resolver writes
    its own three lines rather than reaching for these.

    **It is derived from held data and never from record content**, which is what
    makes it non-forgeable in ADR-0098 §2's sense: the ordinal is this renderer's
    own count, and a record's own spans are quoted by :func:`_quoted_span`, so no
    record can write a line claiming a label — or a second record's label — of its
    choosing.

    **The label is meaningful only within the turn that rendered it** (§3), and
    that is the correct behaviour rather than a limitation to repair: the
    resolvable set is exactly what this turn showed, and a label that outlived its
    turn would be an identifier by another name.

    Args:
        ordinal: The record's 1-based position in this call's ``memories``.

    Returns:
        The label, e.g. ``"M3"``.
    """
    return f"M{ordinal}"


def _render_record(record: MemoryRecord, *, label: str | None = None) -> str:
    """Render one memory record as a prompt bullet, whole and non-forgeably.

    Three obligations meet on this function and are discharged together (#1194,
    #672), because each of them changes the same line and two of them are about the
    spans the third adds.

    **Every span the record controls is quoted** (ADR-0098 §2, §9). This block's
    syntax is line-oriented — a two-space indent, a ``-`` bullet, a ``[kind/source]``
    label, a four-space continuation line, and the two group headings
    :func:`_render_request` prints above it — and ``content`` and ``outcome`` are
    :data:`~ai_assistant.core.types.EncodableText`, which validates UTF-8
    encodability and permits every newline and bracket in between. Left raw, a
    record whose ``content`` carried a newline and a second bullet wrote a bullet
    **claiming a source of its choosing**, ``user_asserted`` included — the concrete
    defect #672 is, and the one ADR-0098 §2's second clause names as
    non-conformance "whatever labels it emits". :func:`_quoted_span` is the
    deterministic transform §2 admits, already used one function above for a
    facet's ``source``; here it is applied to the two spans a record supplies, so
    no record can open a second bullet, forge a label, or reopen a heading. The
    label itself stays derived from held data — ``kind``, ``source``, ``band_of``
    and ``confidence`` — and never from reading the text (§2's third clause).

    **A belief states the standing it is held with** (ADR-0072 §6). "A derived
    belief that reaches a prompt is rendered as a belief, carrying its band and its
    confidence … never as a bare fact indistinguishable from what the user stated",
    and §6 leaves the phrasing to this lane. So each bullet opens with the band, the
    confidence, and a stance clause naming who the record's claim belongs to: the
    user, this system, or a source the user connected. ``[kind/source]`` alone was
    the de facto stand-in, and it is a vocabulary a reader has to already know —
    ``inferred`` and ``observed`` both mean *the assistant worked this out*, and
    neither says so.

    **An episode is rendered whole** (#1194). ``occurred_at`` and ``outcome`` are
    fields capture writes and no prompt has ever shown, so a retrieved episode
    reached the model as a timeless half-exchange: nothing in the pipeline carried
    an instant to a model, and the reply to the recorded turn was dropped. Both are
    rendered here, and the outcome line is labelled *how it turned out* — the words
    ADR-0074 §4 gives the field — rather than as the assistant's reply. It is the
    benchmark harness's ingestion that puts the other speaker's turn in ``outcome``;
    product capture writes a typed disposition beside it. One label has to be true
    of both, and §4's own is.

    **The phrase where the record carries a ``disposition``, ``outcome`` where it
    does not** (ADR-0221 §3). §1 gives ``outcome`` to the composed reply and §2 puts
    what became of the exchange in a closed enum, so this line renders
    :func:`_disposition_phrase` of that member — the very string a record captured
    before ADR-0221 carries in ``outcome``, byte for byte, so the bullet is
    identical across the two populations and the reply reaches no model. A record
    carrying no ``disposition`` — one written before that decision, or a harness row
    — renders its ``outcome`` exactly as it did.

    **The instant is this prompt's own frame, which is UTC** (#1215). ADR-0156 §2's
    local-calendar clause is scoped in terms to *the observation prompt*, and §3's
    to resolving a relative expression at
    distillation; neither reaches ``planning``, which resolves nothing and holds no
    zone — ``CurrentContext`` carries none, and taking one would be a second
    timezone source to argue (ADR-0008 §6). What this renderer can be is
    *consistent*: ``context.now``, a facet's ``read_at``, a goal's ``deadline`` and
    every other instant in this prompt are ``isoformat()`` with their offset, so an
    episode's ``occurred_at`` is too, and the model can order it against ``now``
    without converting anything. Localising this one field beside a UTC ``now``
    would manufacture, inside a single prompt, the day-boundary error §3 exists to
    prevent.

    **The label is the caller's, and its default is what keeps the benchmark
    harness still** (ADR-0226 §3). ``benchmarks/memory/answer.py`` imports this
    function by name and calls it with no label, so the block it assembles is
    byte-for-byte what it was: the harness's answering prompt carries no read
    request, so a label there would be noise the model has no use for and a
    benchmark result moved for nothing. The product's own assembler
    (:func:`_render_request`) passes one for every record, which is what §3 asks of
    a planner — the label is derived by :func:`_label` from the record's position
    in the sequence the loop passed, and it opens the bullet so that a model
    naming one is naming the first token it read.

    Args:
        record: The record to render, verbatim as this system holds it.
        label: ADR-0226 §3's label for this record's position in the turn's
            ``memories``, or ``None`` to render the bullet unlabelled. Held data,
            never anything the record supplied.

    Returns:
        The bullet — one line, plus one continuation line for an episode that
        recorded an outcome.
    """
    provenance = record.provenance
    band = band_of(provenance.source)
    standing = f"{band.value}, confidence {provenance.confidence:.2f}"
    opening = "  - " if label is None else f"  - {label} "
    tag = f"{opening}[{record.kind}/{provenance.source.value}]"
    content = _quoted_span(record.content)

    if isinstance(record, EpisodicMemory):
        lines = [
            f"{tag} ({standing}) the assistant recorded this exchange at "
            f"{record.occurred_at.isoformat()}: {content}"
        ]
        if record.disposition is not None:
            phrase = _disposition_phrase(record.disposition)
            lines.append(f"    how it turned out: {_quoted_span(phrase)}")
        elif record.outcome is not None:
            lines.append(f"    how it turned out: {_quoted_span(record.outcome)}")
        return "\n".join(lines)

    return f"{tag} ({standing}) {_STANCE[band]}: {content}"


def _disposition_phrase(disposition: ExchangeDisposition) -> str:  # noqa: C901, PLR0911, PLR0912 — one return per member, so the totality `assert_never` rests on is visible; collapsing them would hide it
    """ADR-0221 §2's phrase for one disposition, written out at this site.

    **This table is not shared and must not become shared** (ADR-0221 §3). It is one
    of three copies of the same sixteen strings — the others are in
    ``learning/observer.py`` and ``orchestration/composing.py`` — and no
    implementation extracts them into a shared module, a ``core`` mapping, a method
    on the enum or a helper any two of the three import. Golden rule 1 is the
    reason: three subsystems assembling their own prompts do not reach into one
    another, and what they share is the ADR's table rather than a module.

    Total over :class:`~ai_assistant.core.types.ExchangeDisposition` and
    mechanically so — the wildcard does nothing but ``assert_never`` — so a member
    added to that enum without a phrase here fails the gate at this site rather than
    rendering a bullet whose outcome line reads as empty.

    Args:
        disposition: The member the episode records.

    Returns:
        §2's phrase for it, byte for byte. :func:`_render_record` quotes it with
        :func:`_quoted_span`, exactly as it quotes an ``outcome``.
    """
    match disposition:
        case ExchangeDisposition.NO_ACTION_NEEDED:
            return "no action was needed"
        case ExchangeDisposition.STEP_EXECUTED:
            return "the selected tool ran"
        case ExchangeDisposition.STEP_DENIED:
            return "the action was refused by the permission policy"
        case ExchangeDisposition.STEP_AWAITING_CONFIRMATION:
            return "the action was parked for the user to confirm"
        case ExchangeDisposition.STEP_NO_CAPABLE_TOOL:
            return "no tool advertised the capability the step needed"
        case ExchangeDisposition.STEP_AMBIGUOUS_CAPABILITY:
            return "several tools advertised the capability, so none was chosen"
        case ExchangeDisposition.STEP_INVALID_PARAMETERS:
            return "the step's arguments did not fit the declared schema of any capable tool"
        case ExchangeDisposition.STEP_EGRESS_UNBINDABLE:
            return "the outbound call could not be described, so nothing was asked or sent"
        case ExchangeDisposition.ROUTED_PERFORMED:
            return "the assistant performed the operation the user asked for"
        case ExchangeDisposition.ROUTED_AWAITING_CONFIRMATION:
            return "the operation was parked for the user to confirm"
        case ExchangeDisposition.ROUTED_REFUSED:
            return "the user declined, so the operation was not performed"
        case ExchangeDisposition.ROUTED_AMBIGUOUS:
            return "more than one record matched, so nothing was performed"
        case ExchangeDisposition.ROUTED_AMBIGUOUS_TRUNCATED:
            return "more records matched than could be shown, so nothing was performed"
        case ExchangeDisposition.ROUTED_NOT_FOUND:
            return "nothing matched, so nothing was performed"
        case ExchangeDisposition.ROUTED_UNRECORDED:
            return "the decision could not be recorded, so nothing was performed"
        case ExchangeDisposition.ROUTED_FAILED:
            return "the operation was attempted and failed"
        case _:  # pragma: no cover - exhaustive
            assert_never(disposition)


def _split_conversation_tail(
    memories: Sequence[MemoryRecord],
) -> tuple[Sequence[MemoryRecord], Sequence[MemoryRecord]]:
    """Split ``memories`` into the conversation tail and the retrieved records.

    The tail is the **leading run** of episodic records, not every episodic record:
    ADR-0074 §5 puts the conversation's recent turns first and the
    relevance-retrieved records after, and a prefix split is the only reading of
    that order which cannot reorder the sequence. A partition by kind could.

    **That case has landed, and this split is what it was written to expect.**
    ADR-0158 admits an episodic *supplement* — a second relevance read, under its
    own budget, appended after the retrieved beliefs — so an episode retrieved by
    relevance now arrives after the tail and stays in the trailing group, which is
    the group it belongs to. The belief composition still excludes ``EPISODIC``
    (ADR-0074 §6), so any belief at all between the tail and the supplement is the
    separator that keeps the two apart.

    Where the belief composition is **empty** there is no separator, and this split
    would put the supplement's episodes in the tail — rendering conversations weeks
    old as this one's recent turns. ADR-0158 §4 answers that where it is decidable,
    in ``orchestration``: the supplement is dropped unless something non-``EPISODIC``
    precedes it. Nothing is owed here, and nothing here can tell the two apart —
    which is why the clause lives there and why carrying an explicit boundary
    instead would be a ``Planner`` contract change taking its own ADR.

    Args:
        memories: The records the pipeline assembled for this turn.

    Returns:
        The leading episodic run, then everything after it. Either may be empty.
    """
    boundary = 0
    for record in memories:
        # Via the enum, as `memory.policy` does: the discriminator is a `Literal`
        # str, so comparing it to a member directly is a non-overlapping check.
        if MemoryKind(record.kind) is not MemoryKind.EPISODIC:
            break
        boundary += 1
    return memories[:boundary], memories[boundary:]


def _repair_prompt(reason: str, *, declined: bool = False) -> str:
    """The user turn that asks the model to fix a malformed reply (ADR-0176 §5).

    Two messages, split on whether the reply **asserted** a decline, because the
    two failures carry different evidence of what the model meant.

    - ``declined`` — the reply carried the ``no_capability_needed`` marker and only
      its ``rationale`` was missing, null, non-string or blank. The model has said
      what it meant, so completing the decline is the right ask, and asking for
      steps here would take a correct judgement and instruct the model to invent a
      capability in the next turn — the defect #1315 records, on the reply where
      the judgement was already right.
    - otherwise — unclassified malformed output, a bare empty ``steps`` list
      included. A bare empty list is what a truncation, a template echo or a
      dropped array produces, so offering the decline there would manufacture a
      wrong decline the model never asserted. The message presents both shapes and
      the test between them and asks the model to choose by the goal, naming
      neither as the intended correction.

    Neither message asks for steps, and neither closes by requiring a non-empty
    ``steps`` list — the wording this function used to carry.

    Args:
        reason: What was wrong with the reply, echoed back so the model can see it.
        declined: Whether the reply carried the decline marker (ADR-0176 §5).

    Returns:
        The user turn to append to the conversation before the repair round.
    """
    opening = (
        f"That response could not be used: {reason}. "
        "Reply with only the JSON object described earlier — no prose, no code fence"
    )
    if declined:
        return (
            f'{opening} — keeping `"steps": []` and `"no_capability_needed": true`, '
            'and adding a `"rationale"` whose value is a non-empty string saying why '
            "no capability is needed for this goal."
        )
    return (
        f"{opening}. Either shape is a correct answer; choose between them by what "
        "the goal requires. If accomplishing it requires acting in the world, or "
        "reaching for something this turn has not already given you, send the plan "
        'shape, with `"steps"` listing those steps. If the goal is answered from '
        "what this turn already carries, send the decline shape, with "
        '`"steps": []`, `"no_capability_needed": true`, and a `"rationale"` saying '
        "why no capability is needed."
    )


def _extract_object(content: str) -> dict[str, object]:
    """Decode the JSON envelope embedded in ``content``.

    Scans each ``{`` in ``content`` left to right and attempts to decode an object
    starting there with :meth:`json.JSONDecoder.raw_decode`, which stops at the end
    of the object and ignores any trailing text (ADR-0071). This tolerates a model
    that wraps the object in prose or a Markdown code fence — the goal ADR-0047 §4
    states — including prose that itself contains a brace, which the ADR-0047 §4
    step 1 first-``{``-to-last-``}`` slice ADR-0071 supersedes misreads by spanning
    the prose brace and the envelope's closer at once (#293).

    Where more than one object decodes, the **envelope** is preferred: the first
    that is an envelope under :func:`_is_envelope` — a plan or a decline — rather
    than the leftmost object outright, so a decoy object in the prose ahead of the
    envelope is stepped over instead of planned from, including one that carries a
    ``steps`` key of the wrong type, and one whose ``steps`` is an empty list
    *without* the decline marker (either would otherwise shadow a valid envelope
    behind it). Where no decoded object is an envelope, the first decoded object
    stands in, so a single malformed one still reaches :func:`_require_steps` and
    its precise verdict rather than a generic miss. Two genuine envelopes cannot be
    told apart locally and the earlier wins **whatever their shapes** (ADR-0176 §2);
    the outcome stays bounded and is never a corrupt plan.

    **Widening the predicate here is the load-bearing half of ADR-0176.** Relaxing
    only :func:`_require_steps` and leaving this scan at "a non-empty ``steps``
    list" steps straight past a marked decline, records the decoy ahead of it as the
    fall-back, and then rejects the fall-back for carrying no marker — so a reply
    that contained a valid decline falls to bounded repair. The widening is exactly
    one shape, and it is one a decoy does not reach by accident: an empty ``steps``
    list is a plausible fragment or truncation, an empty ``steps`` list *carrying an
    affirmative boolean marker* is something only a deliberate writer produces.

    **A decoded object is advanced *past*, never re-entered:** the scan resumes at
    the object's end, so a nested object is treated as part of its parent, not as a
    separate candidate. An outer object whose ``steps`` is empty and unmarked is
    therefore still refused rather than being overridden by a non-empty ``steps``
    nested inside it. Only a brace that does *not* open a decodable object
    — a brace in the surrounding prose, or a fragment — is stepped over one
    character at a time to the next brace.

    A candidate that raises for a bounded reason that is *not* a syntax miss is a
    miss like any other: the digit-limit ``ValueError`` CPython raises for an
    over-limit integer literal and the ``RecursionError`` a pathologically nested
    payload raises are caught here, so no unhandled error escapes and the scan
    carries on to the next brace. A well-formed envelope elsewhere in the reply is
    still found; only where the whole reply yields no envelope does it fall to
    bounded repair.

    At most :data:`_MAX_EXTRACTION_MISSES` decode **misses** are tolerated before
    extraction gives up, which keeps the scan linear. A failed ``raw_decode`` is
    cheap to parse but costs work proportional to how far into the reply it reached
    (``JSONDecodeError`` computes a line and column), so attempting it at *every*
    brace of a brace-dense malformed reply is quadratic and would block the event
    loop this runs synchronously on; bounding the misses bounds that. A decoded
    object does not count as a miss and does not consume the budget, so any number
    of valid JSON fragments may precede the envelope — only unparseable braces are
    limited. The bound is generous, so a conforming reply (whose envelope is the
    first decodable object) is unaffected; a reply that buries the envelope behind
    more than :data:`_MAX_EXTRACTION_MISSES` unparseable braces degrades to bounded
    repair rather than to a stall.

    Raises:
        _ExtractionError: If no decodable object is found within the miss budget.
    """
    decoder = json.JSONDecoder()
    first: dict[str, object] | None = None
    misses = 0
    index = 0
    length = len(content)
    while index < length:
        if content[index] != "{":
            index += 1
            continue
        try:
            # raw_decode from the brace: ValueError covers JSONDecodeError (a
            # subclass) *and* the digit-limit ValueError; RecursionError a
            # pathologically nested payload.
            candidate, end = decoder.raw_decode(content, index)
        except ValueError, RecursionError:
            misses += 1
            # `> budget`, not `>=`: exactly `_MAX_EXTRACTION_MISSES` misses are
            # tolerated (the docstring's "up to"); only the miss *beyond* the budget
            # gives up. Still bounds the worst-case scan to linear time.
            if misses > _MAX_EXTRACTION_MISSES:
                break
            index += 1  # this brace opened nothing usable; try the next one
            continue
        if isinstance(candidate, dict):
            if _is_envelope(candidate):
                # A legal envelope, plan-shaped or decline-shaped — exactly what
                # `_require_steps` accepts. Preferred over an earlier decoy that
                # only looks envelope-shaped: a `steps` of the wrong type, or an
                # empty one with no marker behind it.
                return candidate
            if first is None:
                first = candidate
        index = end  # resume past the decoded object; never re-enter its interior

    if first is not None:
        return first
    msg = "no JSON object found in the model reply"
    raise _ExtractionError(msg)


def _declines(envelope: dict[str, object]) -> bool:
    """Whether ``envelope`` carries the decline marker (ADR-0176 §1).

    The marker is the JSON boolean ``true`` **and nothing else**: ``1``, ``1.0``,
    ``"true"``, ``"yes"`` and every other truthy value are not it. The identity
    check is what makes that so — Python's ``bool`` is a subclass of ``int``, so
    ``True == 1`` and ``True == 1.0``, and an equality test would silently execute
    ``{"steps": [], "no_capability_needed": 1}`` as a decline while every other
    clause of ADR-0176 still passed.

    Args:
        envelope: The decoded object to test.

    Returns:
        Whether the object positively asserts that no capability is needed.
    """
    return envelope.get("no_capability_needed") is True


def _is_envelope(candidate: dict[str, object]) -> bool:
    """Whether ``candidate`` is one of the two legal envelope shapes (ADR-0176 §1).

    A **plan envelope** carries a ``steps`` key whose value is a non-empty list
    (ADR-0047 §4 step 2, unchanged). A **decline envelope** carries a ``steps`` key
    whose value is a list of length zero *and* the marker :func:`_declines` tests
    for. Nothing else is an envelope — an object with no ``steps`` key is not one,
    which is what keeps the decline unreachable by *omitting* anything.

    **The marker is consulted only where ``steps`` is empty.** On a non-empty
    ``steps`` it is inert: the object is a plan, its steps are planned, and the
    marker's presence — at any value at all — neither changes that nor is an
    extraction failure. Type-checking the marker before looking at ``steps`` would
    send a perfectly good plan to bounded repair over a key that decides nothing on
    that shape, which ADR-0047 §4 step 2's "other envelope keys are ignored" rule is
    what makes wrong.

    Args:
        candidate: The decoded object to test.

    Returns:
        Whether the object is a plan envelope or a decline envelope.
    """
    steps = candidate.get("steps")
    if not isinstance(steps, list):
        return False
    return bool(steps) or _declines(candidate)


def _require_steps(envelope: dict[str, object]) -> list[object]:
    """Return the envelope's ``steps`` list, empty only where it declines.

    An empty ``steps`` list with no marker is **unclassified malformed output**, not
    a decline (ADR-0176 §5): it is what a truncation, a template echo or a dropped
    array produces, and the reason message says so without naming the decline, so
    the repair turn cannot invite the model to complete a decline it never asserted.

    Raises:
        _ExtractionError: If ``steps`` is missing, not a list, or empty without the
            decline marker.
    """
    steps = envelope.get("steps")
    if not isinstance(steps, list):
        msg = "the reply is not one of the two legal envelopes: it has no 'steps' list"
        raise _ExtractionError(msg)
    if not steps and not _declines(envelope):
        msg = (
            "the reply's 'steps' list is empty and it does not assert "
            "'no_capability_needed': true, so it is neither of the two legal envelopes"
        )
        raise _ExtractionError(msg)
    return steps


def _require_rationale(envelope: dict[str, object]) -> str:
    """Return a decline envelope's non-blank ``rationale`` (ADR-0176 §3).

    A decline has no steps, so ``rationale`` is the whole of what the persisted
    ``ActionPlan`` says about the decision — the sole record of *why* no capability
    was named, and what ADR-0014 §2's audit record rests on at this one shape. It is
    therefore required here where a plan leaves it optional.

    ``core`` does not supply the non-blank condition and is not assumed to:
    ``rationale`` is ``EncodableText | None``, which refuses unwritable text but
    neither refuses nor strips ``"   "``.

    **The type is checked before the value is touched.** Reaching for ``.strip()``
    ahead of the ``isinstance`` would raise ``AttributeError`` on the null case —
    neither ``PlanningError`` nor ``ModelError``, so it would escape
    :meth:`ModelBackedPlanner.plan` as something the ``Planner`` Protocol does not
    document and ADR-0047 §6's bounded repair never sees.

    Args:
        envelope: The decline envelope to read.

    Returns:
        The rationale, verbatim.

    Raises:
        _ExtractionError: If ``rationale`` is absent, null, not a string, or blank.
            Flagged ``declined``, because the reply carried the marker and so said
            what it meant: its repair asks for the rationale, never for steps.
    """
    rationale = envelope.get("rationale")
    if rationale is None:
        stated = "null" if "rationale" in envelope else "missing"
        msg = f"the decline gives no reason: its 'rationale' is {stated}"
        raise _ExtractionError(msg, declined=True)
    if not isinstance(rationale, str):
        msg = "the decline gives no reason: its 'rationale' is not a string"
        raise _ExtractionError(msg, declined=True)
    if not rationale.strip():
        msg = "the decline gives no reason: its 'rationale' is blank"
        raise _ExtractionError(msg, declined=True)
    return rationale


def _optional_rationale(envelope: dict[str, object]) -> str | None:
    """Return the envelope's ``rationale`` if it is a string, else ``None``.

    Raises:
        _ExtractionError: If ``rationale`` is present but neither a string nor
            null.
    """
    rationale = envelope.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        msg = "'rationale' must be a string or null"
        raise _ExtractionError(msg)
    return rationale


__all__ = ["DEFAULT_PLAN_ATTEMPTS", "ModelBackedPlanner"]
