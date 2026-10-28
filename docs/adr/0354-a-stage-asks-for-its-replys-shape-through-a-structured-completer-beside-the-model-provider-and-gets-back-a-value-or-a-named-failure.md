# 354. A stage asks for its reply's shape through a structured completer beside the model provider, and gets back a value or a named failure

- Status: Proposed
- Date: 2026-10-27
- Scope: how a stage that wants one JSON object back from a model asks for it. The provider is handed the reply's schema and constrains the reply to it, and the hub reads the reply against that shape in one place. This decides the seam (§2), the shape and its schema (§3), how `models/` sends the request (§4), what comes back, including each failure (§5), retry, routing and the deadline (§6), what the diagnostic record keeps (§7), how understanding, the primary consumer, moves (§8), the follow-on consumers (§9), what each of them drops (§10), the code it binds (§11) and its lanes (§12). Milestone 17 ([#3481](https://github.com/leonapivato/ai-assistant/issues/3481), batch [#3482](https://github.com/leonapivato/ai-assistant/issues/3482)). The failures it addresses are [#3246](https://github.com/leonapivato/ai-assistant/issues/3246), [#3465](https://github.com/leonapivato/ai-assistant/issues/3465), [#3396](https://github.com/leonapivato/ai-assistant/issues/3396) and [#3090](https://github.com/leonapivato/ai-assistant/issues/3090). Planning's rounds and the follow-up question are not moved (§9:5, §9:6).
- Dependency: [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md), [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md), [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) and [ADR-0143](0143-bulk-inference-is-a-second-seam-beside-the-model-provider-and-a-batch-is-a-handle-the-caller-holds.md), as their status lines leave them. Understanding's reply shape is ADR-0353's, drafted beside this one; this decision names no field of it.
- Authorization: the owner, 2026-10-27, directing milestone 17: "why not do structured output now" (#3482). The coordinator assigned 0354. Ratifying it is the owner's, after the owner has read it (§1:1).
- **Contract-surface decision, and a breaking change under golden rule 5.** It adds a Protocol, `StructuredCompleter`, to `core/protocols.py` (§2:1), the records it returns to `core/types.py` (§5:1), and a pure `core` module holding a shape's schema, its version and the reading rule (§3:2–§3:5). No member of an existing Protocol changes. Nothing the wire carries changes, no stored record changes, and `PROTOCOL_VERSION` does not move.
- **Partially supersedes**, in the clauses §14's first table names: ADR-0276, ADR-0300, ADR-0308, ADR-0314, ADR-0337 and ADR-0339.

## Context

In this document a bare section reference, such as §4:2, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0276 §6:2.

### What happens today

Every stage that wants a structured reply asks the model for plain text and parses JSON out
of it. These facts hold on the tree this decision was written against, `c81bed5f7`:

- **Understanding** calls `ModelProvider.complete` and reads the reply with `_read` in
  `orchestration/understanding.py`. It removes one enclosing Markdown code fence, drops the
  keys the reply shape does not name (ADR-0339 §2), and validates what remains with
  `ProposedActivationUnderstanding.model_validate_json`. A reply that fails costs the one
  repair completion of ADR-0276 §6:2.
- **The digest** (`orchestration/digesting.py`), **story tidy-up**
  (`orchestration/story_tidy_up.py`) and **the matters pass**
  (`orchestration/matters_pass.py`) each strip a fence and validate a private model, each
  with its own trailing-text rules.
- **The observer**'s three calls (scout, framing and placement, in
  `orchestration/observer/stage.py`) read with `replies.parsed`. It tries the whole reply,
  then a fenced block, then the last object standing on its own in prose.
- **The memory reconciler** (`memory/_reconciler.py`) scans for an envelope object with
  `_extract_object`, under a miss budget.

That is six readers for eight calls, each tolerating a different set of ways the model fails
to write only JSON. Each tolerance was added after a failure:

- **Prose around the object.** A digest that found nothing wrote a sentence and then
  `{"evidence": []}`, and was recorded unparsable instead of as an empty answer (#3465).
- **A stray key.** Understanding was refused for a `"meaning_grounds"` nobody asked for
  (#3246, which ADR-0339 answered for understanding alone).
- **A malformed nest.** The observer's walk must not read a nested piece of a broken answer
  as the answer (#3396).

**What the tree offers instead.** pydantic-ai, installed at 2.11.0, can hand a provider the
reply's JSON schema three ways:

- **Native**: the provider's own JSON-schema output. Anthropic's `output_config.format` and
  OpenAI's `response_format` both constrain decoding to the schema. pydantic-ai's profile
  says, per model, whether it supports this (`supports_json_schema_output`). It does for
  `claude-sonnet-5`, which prefixes `Settings.default_model`'s `anthropic:claude-sonnet-5-5`.
- **Tool output**: the schema as a tool the model is forced to call. Anthropic refuses a
  forced tool choice while thinking is on, and some Anthropic models refuse it outright
  (pydantic-ai's profile key `anthropic_supports_forced_tool_choice`).
- **Prompted**: the schema written into the instructions, and the reply read as text.

`PydanticAIToolCallingCompleter` in `models/tool_calling.py` already sends through
pydantic-ai's direct request API, `model_request`. That API returns the provider's whole
response and runs no tool, retries nothing and validates nothing. It is how planning's
returned entry keeps the response with its usage (ADR-0314 §5:2).

**What the record lacks.** Understanding's returned entry keeps only the reply's text, so
its tokens, cache hits and thinking cannot be measured (#3090). `ModelProvider.complete`
returns a `Message`, which carries no usage.

### The three seams on offer

| | (a) A member on `ModelProvider` | (b) `ToolCallingCompleter` with one forced reply tool | (c) A new sibling Protocol |
| --- | --- | --- | --- |
| Existing implementations | Every structural implementation stops satisfying the Protocol: `PydanticAIProvider`, `RetryingProvider`, `RoutingProvider`, `FakeModelProvider` and the test doubles in some thirty test files. `isinstance` answers differently for each | Planning's completer. Its contract changes: a forced tool, no notes tool, validation against the schema | None |
| What it sends | Set by the new member | Always the reserved notes tool beside the reply tool (`_round_request`), thinking on by default, `allow_text_output=True` | Set by the new member |
| What it returns | Set by the new member | A `RoundResponse` whose calls are what the model proposed, deliberately unchecked against any schema (ADR-0307 §5:3) | Set by the new member |
| Its record | The stage's own | Planning's returned entry, written under `DiagnosticSource.PLANNING` | The stage's own |
| Retry, deadline and routing | The wrappers already wrap it | None: "a round's resilience is the caller's" (module docstring) | The wrappers implement it beside `complete` (§6) |
| The reply | Text | A tool call, which the repair, the follow-up and the replay would carry as a tool exchange this seam represents nowhere | Text |

ADR-0143 §1 settled the fork between (a) and (c) for bulk inference, and ADR-0307 §10 made
the same call for planning's rounds, on the same ground: a new member on a structural,
`@runtime_checkable` Protocol "silently unsatisfies every existing structural implementation
at once". The ground is the Protocol's structure, not the capability, so it holds here.
(b) would reuse a seam built for something else and change its
contract to do it, so it is a widening by another route. This decision takes (c).

### Words

A **shape** is the pydantic model class a stage wants its reply to be (§3:1). Its
**schema** is the JSON schema sent for it (§3:2), and its **version** is the digest of that
schema (§3:3). A **structured call** is one call of `StructuredCompleter.complete_structured`.
Its **reply** is the text the model wrote, and its **value** is that reply validated as the
shape. A **returned failure** is one of §5:2's four kinds. The **exchange** is what §5:3
says came back with a reply. The **mode** is native or prompted (§4:2).

## Decision

We will add `StructuredCompleter`, a sibling of `ModelProvider`, whose one member takes the
conversation and a shape and returns the shape's value or a named failure, with what came
back beside it. Its implementation in `models/` sends one request through pydantic-ai's
direct API, in the provider's native JSON-schema output where the model supports it and
with the schema in the instructions where it does not. The schema is closed and carries no
text. The retry and routing wrappers implement it beside `complete`. A stage records the
shape's version and the exchange's usage, and maps each returned failure onto the failure
path it already has. Understanding moves first. The digest, the observer, the matters pass,
story tidy-up and the memory reconciler follow, and each drops its own text-JSON reader.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having read
> it, has authorized its ratification. An assigned number or a green review alone does not
> change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is the lanes §12 sets out, cut under ADR-0137, and each
> keeps the gate green.

### 2. The seam

> **Normative.** `core/protocols.py` gains `StructuredCompleter`, a `@runtime_checkable`
> Protocol beside `ModelProvider`. No member is added to `ModelProvider` or to
> `ToolCallingCompleter`, no existing member changes signature or clause, and
> `StructuredCompleter` inherits from neither. An object may implement it with either or
> both.

> **Normative.** `StructuredCompleter` declares exactly one member: `async def
> complete_structured[T: BaseModel](self, messages: Sequence[Message], shape: type[T], *,
> model: str | None = None) -> StructuredReply[T]`. `model` is a `"provider:model"`
> override, falling back to the configured default where `None`, as it does for
> `ModelProvider.complete`.

> **Normative.** `messages` is held to `ModelProvider.complete`'s precondition (ADR-0066 §1)
> and carries no `Role.TOOL` turn. `shape` is a pydantic model class whose schema (§3:2) is a
> JSON object that can be closed: every object in it names its properties, none gives its
> further keys a schema of their own, and no position in it admits any JSON value. A call
> failing either is refused before any model is contacted with a `ModelError` carrying
> ADR-0066 §3's disposition: neither `retryable` nor `routable`.

> **Normative.** `complete_structured` observes `messages` under `core/protocols.py`'s
> input-observation clause (ADR-0065), and its conformance suite enforces that as
> `ModelProviderContract` enforces it for `complete` (ADR-0069).

> **Normative.** `complete_structured` raises only where no response came back to read: the
> malformed calls of §2:3, a failure of the exchange with the provider, or a deadline (§6:3).
> What it raises is a `ModelError`, narrowed to the most specific subclass as `complete`'s
> failures are (ADR-0063). Every response that comes back is returned, as a value or as a
> returned failure (§5).

> **Normative.** Nothing outside `models/` names pydantic-ai or a provider SDK to make or
> read a structured call. The Protocol, its records and the shape are `core` and pydantic
> alone (golden rule 4, ADR-0061).

### 3. The shape and its schema

A shape is a type the caller already owns, and `models/` treats it only through pydantic's
own API. It never imports the consumer's module, reads none of the value's fields, and
keeps nothing of either after the call. So a shape stays where its consumer keeps it today:
understanding's in `core/types.py`, the observer's beside the observer. Moving it would turn
every follow-on consumer's lane into a `core` change, for data that never crosses into
another subsystem's hands.

> **Normative.** A shape is a pydantic model class defined by its consumer, in the consumer's
> module or in `core/types.py`. `models/` uses a shape only through pydantic's public API,
> and keeps no reference to it or to its value once the call returns.

> **Normative.** The schema sent for a shape is its pydantic JSON schema in validation mode,
> with two changes and no others. Every object in it is closed, admitting no key the shape
> does not name (`"additionalProperties": false`). It carries no text: every `title`,
> `description` and `examples` keyword pydantic would write, whether from a docstring or
> from a field, is removed. A property the shape names keeps its name, whatever it is.

So what each field means is said by the stage's prompt template, which the owner may
override (ADR-0334 §3:3), and never by the schema, which is code (ADR-0334 §1:3).

**Why some shapes are refused.** Two kinds of field cannot be closed. A mapping, such as
`dict[str, int]`, names no property and gives its keys a schema; closing it leaves no key
it may hold, so a mapping that must hold one could never be produced. An open value, such
as pydantic's `JsonValue`, has the schema `{}`, which admits any JSON at all; left open, it
lets the model write keys nobody named, and closed, it holds nothing. Sending either would
send a schema that is unsatisfiable or unconstrained. So §2:3 refuses such a shape before
any model is contacted, and a consumer restates the field with named properties (§9:7). Two
of the observer's shapes hold open values today: placement's `answers` and framing's
`style` and `pin`.

> **Normative.** A shape's version is the first twelve hexadecimal digits of the SHA-256 of
> its schema (§3:2), serialised as JSON with its keys sorted and no insignificant
> whitespace. These are the digits ADR-0334 §8:1 gives a template's version.

> **Normative.** A reply is read as its shape by one rule. Remove one Markdown code fence
> enclosing the whole reply, then validate what remains with the shape's own
> `model_validate_json` under the shape's own configuration. Nothing else is done to it: no
> prose is cut away, no key is dropped and no value is repaired.

> **Normative.** The schema, the version and the reading rule are implemented once, in a
> `core` module that does no I/O. `models/`, the canonical fake (§11), and the regression
> suite's readers in `scripts/prompt_replay.py` use that module, so a stage writing its
> given entry, the seam and the suite agree on all three.

### 4. How `models/` sends it

> **Normative.** The implementation sends each structured call as exactly one request
> through pydantic-ai's direct request API, as `PydanticAIToolCallingCompleter` does. It
> never uses pydantic-ai's `Agent` output retries, and it never sends a second request to
> repair, re-ask or validate a reply. Any further completion is the stage's to decide, as
> understanding's one repair is (ADR-0276 §6:2).

> **Normative.** The request is in **native** mode, the provider's own JSON-schema output,
> where pydantic-ai's profile for the model the request goes to says the model supports
> JSON-schema output. Otherwise it is in **prompted** mode: the schema follows the
> instructions under one fixed sentence the implementation's module ships, and the reply is
> read by §3:4's rule as in native mode. The schema is never sent as a tool for the model to
> call.

> **Normative.** The mode is resolved per request, for the model that request goes to: the
> route's own model, or the call's `model` override. A route whose model lacks native
> support is sent in prompted mode while another route of the same router is native.

> **Normative.** A pydantic-ai `FallbackModel`, wrapped or not, is refused before any request
> with a bare `ModelError`. Nothing in this project builds one, and its mode could not be
> known before it answered.

> **Normative.** A structured request's settings are those `complete` sends today, with the
> schema added. It asks for no thinking setting and sets no output ceiling of its own.
> It also carries the cache marks `models/prompt_cache.py` gives the model the request goes
> to (#3077), in both modes. Nothing else in the request differs from what `complete` sends
> for the same messages.

**How the cache marks survive.** `prompt_cache_settings` marks the system prompt, and the
tools, where the model is Anthropic's. In native mode the schema travels as a request
parameter outside the system prompt, so the marked prefix is the one `complete` sends today.
In prompted mode pydantic-ai appends the schema's instruction to the system prompt as a
static block. Anthropic's adapter places the instructions mark after the last static
block, so the schema is inside the cached prefix. In both modes the schema is the same on
every call of one shape's version, so it varies nothing between one call of a stage and the
next. The marks are set as they are today, the repair's included, and a fallback model gets
none, as today.

> **Normative.** The reply is the text parts of the response, joined in order. A thinking
> part is no part of the reply and is not recorded, as for `complete` today. A response
> carrying a tool call, where none was offered, is a returned failure, `invalid`.

### 5. What comes back

> **Normative.** `core/types.py` gains `StructuredReply`, a frozen record generic in the
> shape. It holds the value or a returned failure, exactly one of the two, and the exchange,
> always. A validator refuses a record holding both or neither.

> **Normative.** A response that came back is a returned failure of the first of these four
> kinds that applies, in this order, and otherwise its reply is read as the shape (§3:4):
>
> - **`refused`**: the provider declined to answer, which pydantic-ai reports as the finish
>   reason `content_filter`;
> - **`cut`**: the response stopped at its output ceiling, the finish reason `length`;
> - **`empty`**: the reply holds nothing but whitespace once the fence is removed;
> - **`invalid`**: the reply does not validate as the shape, or the response carries a call.

> **Normative.** The exchange holds:
>
> - the reply as the model wrote it, possibly empty;
> - the `"provider:model"` that answered, as the response names it;
> - the mode;
> - the finish reason;
> - the provider's statement of a refusal and its category, where it gives them;
> - the usage: input, output, cache-read and cache-write tokens;
> - the shape's name and version.
>
> It holds nothing derived from the value.

> **Normative.** A returned failure is never raised, retried or routed, by the
> implementation or by a wrapper (§6). What the stage does with it is the stage's (§8, §9).

The four failures, side by side:

| Case | The caller receives | Its disposition |
| --- | --- | --- |
| A reply that does not match the schema | A returned failure, `invalid` (or `cut` or `empty`), with the reply's text | The stage's own: a reply that does not parse (§8:3, §9:2) |
| A refusal (Anthropic's `stop_reason` `refusal`; Sonnet 5.5's, #3414) | A returned failure, `refused`, with the provider's statement and the usage | The stage's own. Each maps it where a raised `ModelContentFilterError` lands today (§8:4, §9:2) |
| An empty reply | A returned failure, `empty` | As a reply that does not parse |
| A timeout or deadline | A raised `ModelTimeoutError` from the per-attempt deadline, retryable and routable, or the stage's own deadline as today | The wrappers' (§6:3) and the stage's, unchanged |

In native mode `invalid` is rare. The provider writes JSON matching the schema, so a
mismatch is left only where the shape validates more than its schema says: a pydantic
validator, a constraint a provider's schema dialect drops, a tool call. The reading rule
still runs on every reply, so a provider's lapse cannot reach a stage as a value.

### 6. Retry, routing and the deadline

> **Normative.** `PydanticAIProvider`, `RetryingProvider` and `RoutingProvider` each implement
> `StructuredCompleter` beside `ModelProvider`. A wrapper's `complete_structured` applies the
> per-attempt deadline, the retry policy, the route order and the `model` override handling
> its `complete` applies (ADR-0011, ADR-0013 §3–§5), over inner providers that implement
> `StructuredCompleter`. How the wrappers type that is S1's.

> **Normative.** A consumer that moves to the seam is handed, as its `StructuredCompleter`,
> the same composed object the composition root hands it today as its `ModelProvider`. Its
> route, its retry policy and its fallback order stay as they are.

> **Normative.** The per-attempt deadline raises `ModelTimeoutError`, as it does for
> `complete`. A stage's own deadline, such as understanding's (ADR-0276 §5), bounds a
> structured call exactly as it bounds a completion today.

### 7. What the record keeps

> **Normative.** Where `diagnostic_record` is true, a stage's given entry for a structured
> call also carries `reply_shape`: the shape's name and its version (§3:3). It is written
> before the call, as every given entry is (ADR-0314 §4:1).

> **Normative.** A stage's returned entry for a structured call keeps the reply as the model
> wrote it under `reply`, a string, as understanding's does today. It also carries, from
> the exchange, the model that answered, the mode, the finish reason, a refusal's statement
> and category where the provider gave them, the usage, and the returned failure's kind
> where there is one. The stage writes it from its own module, before it acts on a returned
> failure (ADR-0314 §4:1). Where no response came back, it writes the failure, as today.

> **Normative.** No log line carries a reply, a refusal's statement or a schema. A stage may
> log a returned failure's kind as a code-owned reason (ADR-0276 §6:7).

> **Normative.** No trace gains a field, a key or a kind from this decision. Usage reaches
> the diagnostic record and nothing else.

This answers #3090 for every stage that moves. The record shows each structured call's
tokens and cache hits, which model answered, and in which mode.

### 8. Understanding, the primary consumer

Understanding's reply shape is ADR-0353's, which replaces today's
`ProposedActivationUnderstanding` with a reply holding the understanding, its citations, its
unclear points with their readings, its matters, the running work it is meant for and the
relay mark. This decision names none of its fields. Whatever ADR-0353 calls it, its first
completion and its repair are structured calls with that shape.

> **Normative.** Understanding makes its first completion and its repair as structured calls
> with its reply shape, through an injected `StructuredCompleter`, which is the
> application's ordinary route as its `ModelProvider` is today (ADR-0276 §6:1, §6:2).

> **Normative.** A value is a parsed output. The label checks, the one label repair and the
> recording of a label defect run on it unchanged (ADR-0276 §6:2, §6:4, as ADR-0353 leaves
> them). Understanding's label repair is about what a label means, and this decision leaves
> it as it is.

> **Normative.** A returned `invalid`, `empty` or `cut` is an output that fails to parse
> (ADR-0276 §6:2), and costs the one repair. The repair carries the first reply's text as
> the assistant's turn, or no assistant turn where that text is empty, and then the
> code-owned statement, which names the failure's kind. The same failure on the repair's
> reply raises `UnderstandingError` (ADR-0276 §6:3).

> **Normative.** A returned `refused`, on the first call or on the repair, costs no repair.
> The stage writes its returned entry and raises `ModelContentFilterError`. The activation
> ends as a refused completion ends it today (ADR-0276 §6:6's row for a `ModelError`).

> **Normative.** A `ModelError` raised by the seam propagates unchanged (ADR-0276 §6:3).

> **Normative.** The regression suite reads an understanding reply by §3:4's rule with the
> reply shape.

> **Normative.** The replay tool sends a recorded understanding call whose given entry
> carries `reply_shape` as a structured call with the package's shape of the recorded name
> (ADR-0335 §4:6), and marks a result whose recorded version differs from the package's. A
> given entry carrying no `reply_shape`, recorded before the move, is sent as it was made,
> a plain completion, and its result is marked as sent plain. A recorded name the package
> holds no shape for fails that call, naming the defect and nothing of the call's content.

> **Normative.** A follow-up question asked of a structured call (ADR-0337 §6:3) carries the
> followed reply's text as the assistant's turn and is sent with no shape, through
> `ModelProvider.complete`. Its answer is text (ADR-0337 §6:5).

### 9. The follow-on consumers

| Consumer | Module | Its reply today | Where it lands a failure today |
| --- | --- | --- | --- |
| The digest (#3465) | `orchestration/digesting.py` | `_parsed`, one fence, `_Proposed` | `DigestFailure` `unparsable`; `raised` for a raised error |
| The observer's scout, framing and placement | `orchestration/observer/stage.py`, `replies.py` | `replies.parsed`, the candidate walk | `_Unparsed`: the attempt stays pending (ADR-0329 §16:4) |
| The matters pass | `orchestration/matters_pass.py` | `_unfenced`, `_parsed` and its trailing-text rules | Refused whole, nothing written |
| Story tidy-up | `orchestration/story_tidy_up.py` | `_parsed`, one fence | Refused whole, nothing written (ADR-0300 §5:8) |
| The memory reconciler | `memory/_reconciler.py` | `_extract_object`, the envelope scan and its miss budget | `ReconcilerOutcome.FAILED` (ADR-0164 §3) |

The observer's commit call retired with ADR-0346, which put framing and placement in its
place, so its three calls are scout, framing and placement. #1199's three envelope producers were `planning/planner.py`,
`learning/observer.py` and `memory/_reconciler.py`. The first two no longer exist, and the
reconciler is the one that is left.

> **Normative.** Each consumer the table names moves to the seam whole, with a shape of its
> own: every call it makes for that reply is a structured call. Its prompt, its checks after
> the parse, what it records and where it lands each failure stay as they are.

> **Normative.** A moved consumer lands a returned `refused` where a raised
> `ModelContentFilterError` lands today, and a returned `invalid`, `empty` or `cut` where a
> reply that does not parse lands today. A raised `ModelError` lands where it lands today.

> **Normative.** A consumer whose reply is one of several kinds, such as the matters pass's
> decisions, sends one shape whose top level is an object, holding the kinds as a
> discriminated union.

> **Normative.** A consumer moves in its group's lane (§12), and in no other.

> **Normative.** Planning's rounds do not move: they already reach the model through
> `ToolCallingCompleter`'s native tool calling.

> **Normative.** The follow-up question does not move: it answers in text (ADR-0337 §6:5),
> and what becomes of it is open on #3414.

> **Normative.** A consumer whose reply today holds a mapping or an open value restates it in
> its shape as named properties, so that the shape passes §2:3. The restated fields carry
> what the consumer's readers read today, and those readers run the checks they run today.

> **Normative.** Each moved consumer's regression-suite reader and replay follow §8:6 and
> §8:7, as understanding's do.

### 10. What each consumer drops

Once a consumer's replies come back in native mode, the text-JSON pieces it carries guard
against failures that cannot reach it. In prompted mode they still could, so they are not
dead for every model. The reading rule (§3:4) is the guard both modes share, and a reply it
refuses lands on the stage's own failure path. Keeping a second reader beside it would put
two rules on one reply. So each moved consumer drops its own:

| Consumer | What it drops | What that amends |
| --- | --- | --- |
| Understanding | `_read`'s fence removal, now §3:4's; ADR-0339's drop, `_pruned_reply` and the walk behind it; the `understanding_stray_keys` log line; `_parsed` as the suite's reader, replaced by §3:4's | ADR-0339 §2:1–§2:6 and §4:1–§4:2, for a structured reply; ADR-0276 §6:1–§6:3 in the additions §14 names |
| The digest | `_parsed` and its fence removal. #3465's prose before the object cannot occur in native mode | ADR-0308 §4:10–§4:11, in the additions §14 names |
| The observer | `replies.parsed` and its candidate walk. #3396's coverage of that walk has nothing left to cover | Nothing: no clause pins the reader |
| The matters pass | `_unfenced` and `_parsed`'s trailing-text rules | Nothing: no clause pins the reader |
| Story tidy-up | `_parsed` and its fence removal | ADR-0300 §5:1 and §5:8, in the additions §14 names |
| The memory reconciler | `_extract_object` and its miss budget. #1199's promotion has nothing left to promote | Nothing: ADR-0164 §3's outcomes stand |

> **Normative.** The lane that moves a consumer removes, in the same change, the pieces the
> table names for it. After it merges, the consumer reads its reply by §3:4's rule alone,
> and keeps no second reading of that reply's text.

> **Normative.** A shape keeps its own pydantic configuration. A lane may leave a shape's
> `extra` setting as it stands. Its schema is closed either way (§3:2), so in native mode no
> unnamed key reaches it.

### 11. The code it binds

| Code | Change |
| --- | --- |
| `StructuredCompleter` | New `core` Protocol beside `ModelProvider`, one member, `complete_structured` (§2:1–§2:2) |
| `StructuredReply` | New frozen record, generic in the shape: the value or the failure, exactly one, and the exchange (§5:1) |
| `ReplyFailure` | New closed enumeration: `refused`, `cut`, `empty`, `invalid` (§5:2) |
| `ReplyMode` | New closed enumeration: `native`, `prompted` (§4:2) |
| The exchange and its usage | New frozen records holding §5:3's fields. Exact names are S1's |
| A pure `core` module | A shape's schema (§3:2), its version (§3:3) and the reading rule (§3:4) |
| `PydanticAIProvider` | Gains `complete_structured` (§4) |
| `RetryingProvider`, `RoutingProvider` | Gain `complete_structured` (§6:1) |
| `ai_assistant.testing` | A canonical `StructuredCompleter` fake, which reads a scripted reply by §3:4's rule and returns scripted failures |
| `ModelProvider`, `ToolCallingCompleter`, `Message` | Unchanged |
| `ModelError` and its subclasses | Unchanged: no class is added |
| `PROTOCOL_VERSION`, every store's schema | Unchanged |

### 12. Delivery

The lanes, each after this decision merges `Accepted`:

1. **S1, the triad and its production implementation** (ADR-0137 §2:1, §3:1). The Protocol,
   its records and the pure `core` module (§11); its conformance suite and the canonical
   fake with its `Test…Contract`; and the implementation in `models/`, with the wrappers
   (§4, §6:1). Nothing consumes it yet: no stage moves and nothing is wired.
2. **U2, understanding** (milestone 17), briefed against merged S1 and ADR-0353's contract
   unit (ADR-0137 §4:1). Understanding's move (§8) is part of that lane's work.
3. **F1, the orchestration consumers**, briefed against merged S1: the digest, the
   observer's three, the matters pass and story tidy-up (§9, §10). They are one consumer
   group because between them they put new machinery into one subsystem alone (ADR-0137
   §4:1).
4. **F2, the memory reconciler**, briefed against merged S1 (§9, §10).

A new Protocol unsatisfies no existing implementation. S1 therefore conflicts with an open
lane only where both edit the same file: `core/protocols.py`, `core/types.py`, or the three
wrapped classes in `models/`. P1 and U1 edit `core/types.py`, so S1 is sequenced apart from
them.

> **Normative.** S1 may touch `core` (`protocols.py`, `types.py` and the new pure module),
> `ai_assistant.testing`, `models/`, and their tests, `tests/core/test_protocol_triad.py`
> included. It touches no file in `orchestration/`, `memory/`, `app/` or `scripts/`.

> **Normative.** U2 may touch, for this decision, `orchestration/understanding.py`,
> `app/composition.py` to hand understanding its `StructuredCompleter`,
> `scripts/prompt_replay.py` for understanding's replay and reader, and their tests.

> **Normative.** F1 may touch the modules §9's table names in `orchestration/`,
> `app/composition.py` to hand each its `StructuredCompleter`, `scripts/prompt_replay.py` for
> their replays and readers, and their tests.

> **Normative.** F2 may touch `memory/_reconciler.py`, `app/composition.py` for the
> reconciler's route, and their tests.

> **Normative.** S1's tests include, each failing on an implementation that meets only the
> others:
>
> - the suite's precondition cases (§2:3), refused before a model is contacted, with
>   ADR-0066 §3's disposition, a shape holding a mapping, a schema for further keys or an
>   open value among them; and its input-observation case (§2:4);
> - a reply that validates is returned as the value, with no failure;
> - each of §5:2's four kinds is returned and never raised, in §5:2's order where several
>   apply, such as a refusal that also stopped at its ceiling;
> - one call is one request, counted at the model, for a valid reply, for each returned
>   failure, and for a reply pydantic-ai's `Agent` would have retried;
> - native mode for a model whose profile supports JSON-schema output and prompted mode for
>   one that does not, with no output tool in either request;
> - the schema sent is closed at every depth and carries no `title`, `description` or
>   `examples`, though the shape's docstring and fields carry text;
> - a shape's version is stable across runs and changes when a field changes;
> - the cache marks are present on an Anthropic model's request in both modes, and absent on
>   any other model's;
> - a thinking part stays out of the reply;
> - the exchange carries the usage and the model that answered;
> - a `FallbackModel` is refused;
> - over the `anthropic` and `openai` SDKs with only the transport replaced (ADR-0061 §3):
>   the request body carries the schema in the vendor's native field, and a canned
>   `stop_reason` of `refusal` is returned `refused` with its statement;
> - `RetryingProvider` retries a raised retryable failure and returns a returned failure
>   without retrying it; `RoutingProvider` routes a raised routable failure and returns a
>   returned failure without routing it; the per-attempt deadline raises
>   `ModelTimeoutError`.

> **Normative.** U2's tests include:
>
> - a value goes to the label checks as a parsed output does today;
> - `invalid`, `empty` and `cut` each cost the one repair; an empty first reply's repair
>   carries no assistant turn; the same failure on the repair raises `UnderstandingError`;
> - `refused` raises `ModelContentFilterError` with no repair, after the returned entry is
>   written;
> - the given entry carries `reply_shape`, and the returned entry carries the reply, the
>   usage, the model, the mode and the failure's kind;
> - the regression suite's reader and the stage read one reply alike;
> - a recorded call whose given entry carries no `reply_shape` replays as a plain
>   completion, marked so;
> - ADR-0339's drop and its log line are gone.

> **Normative.** F1's and F2's tests include, for each consumer:
>
> - each returned failure lands where §9:2 puts it;
> - its shape passes §2:3's check, the observer's restated fields (§9:7) included;
> - a recording made before the move replays as a plain completion (§9:8);
> - the given entry carries `reply_shape` and the returned entry the usage, where that
>   consumer writes entries;
> - its text-JSON reader is gone (§10:1).
>
> They also include: a digest whose evidence is empty reads as an empty answer (ADR-0308
> §4:8, #3465); and an observer reply refused as `invalid` leaves its attempt pending
> (#3396).

### 13. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Thinking on a structured call | A later decision. Today's completions ask for none, and neither does this |
| Tool output as a third mode | Not needed while every configured model is native; a later decision if one is not |
| Field definitions in the schema, as #3246 suggested | Rejected here (§3:2): meaning stays in the overridable prompt. A later decision could move it |
| What a follow-up asks of a structured call, or whether it is asked | The follow-up's open question (#3414) |
| Usage in a Tier 2 trace | A later decision, under ADR-0119's discipline |
| A structured batch, through `BatchCompleter` | A later decision, if a batch consumer wants a shape |
| Streaming a structured reply | Nothing streams one today |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 14. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0276 | §6:1's *makes one completion through the injected `ModelProvider`*: one structured call with understanding's reply shape through the injected `StructuredCompleter`, on the same route. §6:2's first check, in the addition alone: a value is a parsed output, and a returned `invalid`, `empty` or `cut` is an output that fails to parse, whose text the repair carries, or no assistant turn where it is empty. §6:3's *A `ModelError` the provider stack raises*, in the addition alone: a returned `refused` raises `ModelContentFilterError`, with no repair | §8:1–§8:5 |
| ADR-0339 | §2:1–§2:6 and §4:1–§4:2, for a reply understanding receives as a structured call: nothing is dropped from it and no count is logged. The schema is closed (§3:2) and the reply is read by §3:4's rule | §3:2, §3:4, §10:1 |
| ADR-0308 | §4:10's *a plain completion, `ModelProvider.complete`* and *its reply parsed as one JSON object*, in the addition alone: or one structured call with the digest's shape, no `model` override, its value the parsed object. §4:11's *a reply does not parse*, in the addition alone: a returned `invalid`, `empty` or `cut` | §9:1–§9:2 |
| ADR-0300 | §5:1's *an injected `ModelProvider`*, in the addition alone: or an injected `StructuredCompleter`. §5:8's *fails to parse*, in the addition alone: a returned `invalid`, `empty` or `cut` | §9:1–§9:2 |
| ADR-0314 | §4's table and §4:1's *what the table gives it*, in the additions alone: a structured call's given entry also carries the reply shape's name and version, and its returned entry also carries the exchange's model, mode, finish reason, refusal, usage and the failure's kind | §7:1–§7:2 |
| ADR-0337 | §6:3's *the followed call's request as it was sent*, in the addition alone: a structured call's follow-up is sent with no shape, through `ModelProvider.complete`, the followed response being the reply's text | §8:8 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0143 §1, ADR-0307 §10 | Nothing: their sibling ground is followed, and `ToolCallingCompleter` and `ModelProvider` keep every member and clause (§2:1) |
| ADR-0011, ADR-0013 | Nothing: the wrappers apply their policy to the new member as to `complete`, retry inside routing, an explicit `model` override routing nowhere (§6:1) |
| ADR-0061 | Nothing: no SDK leaves `models/`, and the new suite runs over both vendor SDKs as `ModelProviderContract` does (§12:5) |
| ADR-0063 | Nothing: a raised failure is classified as `complete`'s are |
| ADR-0065, ADR-0066 | Nothing: the module clause and the precondition bind the new member (§2:3, §2:4) |
| ADR-0276 §6:4–§6:7 | Nothing: label defects, a successful understanding, `understanding_failed` and the logging rule stand. A returned failure's kind is a code-owned reason |
| ADR-0334 | Nothing: the schema is code and no override reaches it (§1:3); the prompt says what each field means (§3:2) |
| ADR-0335 §4:1, §4:6 | Nothing: a structured call is replayed through the model layer with its stage's settings, its shape among them (§8:7) |
| ADR-0346 §4:6 | Nothing: a returned failure is a reply that does not parse, and the scout's accounting check stands |
| ADR-0164 §3 | Nothing: a returned failure is a request that yielded no readable answer, `FAILED` |
| ADR-0314 §3 | Nothing: the record stays write-only, and nothing reads the usage back |
| ADR-0353 | Nothing: its reply shape is the shape understanding sends (§8); this decision names none of its fields |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0276, ADR-0300, ADR-0308, ADR-0314, ADR-0337 and ADR-0339,
> atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

## Consequences

**Easier.** A stage asks for a shape and gets the shape, or a named reason it did not. Prose
around the object, a stray key, a fence and a malformed nest stop being failures a stage
must anticipate, because in native mode the provider cannot write them. Six readers become
one rule in `core`. The prompt stops spending words on JSON syntax and says what each field
means. The record shows each structured call's usage, cache hits and model, so #3090's
estimate becomes a measurement. A refusal is recorded with its statement and its usage
before it ends the activation.

**Harder.** A shape's schema is now part of what a model is sent, and a change to a shape
changes its version and the request. A shape must stay inside the schema dialect each
configured provider accepts. pydantic-ai's transformers adapt most of it, and a shape a
provider refuses fails at request time with that provider's error. A model without native
support runs in prompted mode, which is today's text-JSON path with no tolerance beyond one
fence: there a stray key or a sentence of prose costs the stage's repair, or its reply,
where ADR-0339's drop would have kept it. An empty reply, which pydantic-ai's `Agent`
re-asks for and then raises as a routable `ModelResponseError`, is now the stage's to repair,
on the same route.

**Follow-on.** S1, then U2, F1 and F2 (§12). #3465, #3396 and #1199 close as their consumer
moves. #3246 closes when the last consumer moves.

**Revisit when** a configured model lacks native support and prompted mode's misses show in
the record, or a consumer wants thinking or tool output for its reply (§13).

## Alternatives considered

- **(a) A member on `ModelProvider`.** Rejected on ADR-0143 §1's ground. It unsatisfies
  every structural implementation at once: the three classes in `models/`, the canonical
  fake, and the test doubles in some thirty test files. It also changes what `isinstance`
  answers about each.
- **(b) `ToolCallingCompleter` with one forced reply tool.** Rejected. The completer always
  offers the reserved notes tool, asks for thinking, writes planning's returned entry and
  validates nothing against a schema by contract (ADR-0307 §5:3). Using it would change that
  contract, a widening by another route. A forced tool choice is refused by Anthropic while
  thinking is on, and outright by some of its models. The reply would come back as a tool
  call, which the repair, the follow-up and the replay would carry as a tool exchange no
  seam here represents. And it has no retry or routing.
- **The schema in, a JSON object out**, the caller validating it into its type. Rejected.
  Without the type, `models/` cannot tell a reply that matches the schema from one that
  validates, so every consumer would carry the second half of the reading and the record
  would show a failure the seam never saw.
- **pydantic-ai's `Agent` with an `output_type`.** Rejected. Its output retries send further
  requests nobody decided, under a budget no stage sets, and the stage's repair would then
  run on top of them (§4:1).
- **Tool output when native is missing.** Rejected for now (§13). Prompted mode keeps the
  reply as text in every mode, and tool output is the mode Anthropic restricts.
- **Raise every failure as a `ModelError`.** Rejected. A schema-invalid reply would be
  `ModelResponseError`, which is routable, so the router would send the request to the next
  route before understanding's repair saw it. The exchange, its usage among it, would reach
  the record only through an exception's attributes.
- **Field definitions in the schema's descriptions**, #3246's suggestion. Rejected (§3:2).
  The schema is code, and the owner experiments with prompts through overrides (ADR-0334).
  Meaning in the schema would put it beyond every override, and a pydantic docstring would
  reach the model unreviewed as instruction.
- **Keep ADR-0339's drop for prompted mode.** Rejected. A second reader beside §3:4's would
  put two rules on one reply, and no configured model runs prompted today.
