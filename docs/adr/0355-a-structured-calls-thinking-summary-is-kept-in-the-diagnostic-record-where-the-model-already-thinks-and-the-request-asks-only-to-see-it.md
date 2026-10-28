# 355. A structured call's thinking summary is kept in the diagnostic record where the model already thinks, and the request asks only to see it

- Status: Accepted
- Date: 2026-10-28
- Scope: what the diagnostic record keeps of the thinking a model does on a structured call (ADR-0354), and what that costs the request. This decides when it applies (§2), the one change to the request and the models it is made for (§3), what comes back (§4), where the summary goes and where it never goes (§5), which stages write it (§6), what the viewer shows (§7), its tests (§8) and its lanes (§9). It answers ADR-0354 §13's first row, "Thinking on a structured call". Milestone 17 ([#3481](https://github.com/leonapivato/ai-assistant/issues/3481)).
- Dependency: [ADR-0354](0354-a-stage-asks-for-its-replys-shape-through-a-structured-completer-beside-the-model-provider-and-gets-back-a-value-or-a-named-failure.md), [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md) and [ADR-0333](0333-the-observer-writes-diagnostic-entries-in-a-file-of-its-own-beside-the-activation-it-learned-from-and-the-viewer-shows-what-was-learned.md), as their status lines leave them.
- Authorization: the owner, 2026-10-28, reviewing understanding in the activation viewer: "Is there more we can show in the activation viewer, like the thinking or reasoning and anything else that could provide more insight in how it processed". Asked "just to be clear, this isnt changing understandings behavior at all right, its just making it more transparent rihgt", and told yes, the owner said "yes go ahead with both". The coordinator assigned 0355 and ratifies it under the owner's delegation once its reviews are green. The model list of §3:2, the configuration shape of §2 and the entry key of §5:1 are this lane's choices, not owner rulings.
- **Contract-surface decision.** `core/types.py`'s `ReplyExchange` gains one field, `thinking`, defaulting to `None` (§4:1). No Protocol member changes, so it is not a breaking change under golden rule 5. No `Settings` field is added, nothing the wire carries changes, no stored record changes, and `PROTOCOL_VERSION` does not move.
- **Partially supersedes**, in the clauses §10's first table names: ADR-0314, ADR-0333 and ADR-0354.

## Context

In this document a bare section reference, such as §3:2, is to this decision's own clauses.
Every other ADR's are written with its number, such as ADR-0354 §4:5.

### What the record keeps today

**Planning's thinking is kept.** Where the record is on, `PydanticAIToolCallingCompleter` is
handed a `DiagnosticSink`, and a round to a model with Anthropic's adaptive thinking asks for
the thinking's summarised text with `{"type": "adaptive", "display": "summarized"}`
(`_SUMMARISED_ADAPTIVE` in `models/tool_calling.py`, ADR-0314 §5:1). The returned entry keeps
the provider's whole response, thinking parts included, and the activation viewer shows each
thinking part under "Thinking (the provider's summary)".

**A structured call's thinking is not.** ADR-0354 §4:5 has a structured request ask "for no
thinking setting", and §4:6 has a thinking part be "no part of the reply" and "not recorded".
`structured_reply` in `models/structured.py` joins the text parts alone, and `ReplyExchange`
has no field a thinking part could go in. ADR-0354 §13 left "Thinking on a structured call" to
a later decision. This is that decision.

The structured consumers, on the tree this decision was written against (`267f7628f`):

| Consumer | Module | Its route | Writes a returned entry |
| --- | --- | --- | --- |
| Understanding, its first completion and its repair | `orchestration/understanding.py` | The routed provider (`_build_model_provider`) | Yes (ADR-0314 §4, source `understanding`) |
| The digest, each part | `orchestration/digesting.py` | The same routed provider | Yes (ADR-0314 §4, source `digesting`) |
| The observer's scout, framing and placement | `orchestration/observer/stage.py`, `entries.py` | Its scout route and its commit route (`_build_observer_provider`) | Yes (ADR-0333 §2, source `observer`) |
| The matters pass | `orchestration/matters_pass.py` | Consolidation's route (`_build_consolidation_provider`) | No |
| Story tidy-up | `orchestration/story_tidy_up.py` | Consolidation's route | No |
| The memory reconciler | `memory/_reconciler.py` | The reconciler's route (`_build_reconciler_provider`) | No |

Each route is its own `PydanticAIProvider` object, built per spec by the composition root, so
a setting given to one route's provider reaches no other route.

### What the vendor says

Every model the hub routes a structured call to is, by default, `anthropic:claude-sonnet-5-5`:
it is `Settings.default_model`, and the observer's, consolidation's and the reconciler's specs
each fall back to it when unset. Anthropic's documentation, read 2026-10-28, says:

- **Which models think without being asked.** The table under "Configuring thinking" on
  [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) gives, for a
  request with no `thinking` field, "Adaptive thinking" on Claude Opus 5.5, Opus 5, Sonnet 5.5,
  Sonnet 5, Haiku 5.5, Fable 5.1, Fable 5, Mythos 5.1, Mythos 5 and Mythos Preview, and
  "Thinking off" on Claude Opus 4.8, Opus 4.7, Opus 4.6, Sonnet 4.6 and every earlier model. The
  same table gives `"adaptive"` as "Adaptive thinking" on every one of the first group: on
  those models, sending `{"type": "adaptive"}` is what omitting the field already does.
- **What `display` changes.** Under "Controlling thinking display" on the same page,
  `"omitted"` is the default on every model of the first group, returning "thinking blocks
  with an empty `thinking` field", and `"summarized"` returns "a readable summary of Claude's
  reasoning". The overview says "Either way the block is billed the same".
- **What it costs.** The "Pricing" table on
  [Steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost)
  says "What you're billed for is the same regardless of the `display` setting; only what you
  see changes": the billed output tokens are "the full thinking tokens Claude generated
  internally" under either value, and summary generation is "No charge". Its "Cost control"
  section says `max_tokens` caps "thinking and response text combined", so the ceiling a
  response is cut at counts the same thinking under either value.
- **What it may cost in time.** "Controlling thinking display" says of `"omitted"`: "The
  primary benefit is faster time-to-first-text-token when streaming", and "Omitting reduces
  latency, not cost". No structured call streams, but a summarised response may take longer
  to arrive than an omitted one.

So on the hub's model the change asks the model to do nothing it does not already do, and is
billed the same. The two claims the brief for this decision rested on both hold for
`claude-sonnet-5-5`. They do **not** hold for Claude Opus 4.8, 4.7, 4.6 or Sonnet 4.6, which do
not think when the field is omitted: there, sending the configuration would turn thinking on,
which is a change of behaviour and of cost. They do not arise for a model of another vendor,
which ignores Anthropic's settings key.

**Why pydantic-ai's profile cannot tell them apart.** pydantic-ai 2.11.0's
`anthropic_supports_adaptive_thinking` is true for Opus 4.6, 4.7 and 4.8 and Sonnet 4.6, which
do not think unasked, and false for `claude-opus-5-5` and `claude-haiku-5-5`, which do. It says
whether a model *can* think adaptively. Planning may use it, because a round asks for thinking
on every model anyway (`DEFAULT_THINKING`). A structured call asks for none, so the test here is
whether the model thinks when it is not asked, and no profile key says that.

**What pydantic-ai does with the setting.** With `anthropic_thinking` set and no unified
`thinking` setting, `AnthropicModel._translate_thinking` sends the configuration as given, and
sets no `output_config.effort` (that mapping runs only from a unified thinking level). The two
other places it reads the setting, the output-tool check in `prepare_request` and
`_support_tool_forcing`, act only where tools or output tools are offered, and a structured
request offers neither (ADR-0354 §4:2). The request's `max_tokens` is the same either way.

## Decision

We will have a structured request ask Anthropic to return its thinking's summary, and change
nothing else, only where the diagnostic record is on, only on a route whose consumers write
returned entries, and only to a model Anthropic documents as thinking when the request does not
ask. The summary comes back on the exchange, and the stage writes it into its returned entry and
nowhere else.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (ADR-0015 §5).

> **Normative.** The implementation is the lanes §9 sets out, cut under ADR-0137, and each
> keeps the gate green.

> **Normative.** Nothing in this decision changes what any stage is sent, reads, decides,
> returns or writes outside the diagnostic record, or which model is asked, or how often.

### 2. When it applies

> **Normative.** `PydanticAIProvider` gains a keyword-only constructor argument,
> `thinking_summaries`, a boolean whose default is false. It bears on `complete_structured`
> alone: `complete` sends what it sends without this decision.

> **Normative.** Where `thinking_summaries` is false, `complete_structured` sends exactly the
> request it sends without this decision, and the exchange it returns holds no thinking.

> **Normative.** The composition root builds each `PydanticAIProvider` of the routed provider
> that understanding and the digest reach through, and of the observer's scout and commit
> routes, with `thinking_summaries` equal to `Settings.diagnostic_record`.

> **Normative.** The composition root builds every other `PydanticAIProvider` with
> `thinking_summaries` false, consolidation's route and the reconciler's route among them.

> **Normative.** A route built with `thinking_summaries` true is handed as a
> `StructuredCompleter` only to consumers that write a returned entry for each structured call
> they make. A consumer that writes none is handed a route built with it false.

> **Normative.** No Protocol member, no `Settings` field and no clause of `RetryingProvider` or
> `RoutingProvider` changes. The wrappers return the exchange their inner provider returned,
> as they do (ADR-0354 §6:1), and a consumer is still handed the object it was handed as its
> `ModelProvider` (ADR-0354 §6:2).

**Why at composition.** The setting lives on the object the composition root already builds per
route, which is where it knows both whether the record is on and which consumer a route serves.
A member or keyword on `complete_structured` would change the Protocol (golden rule 5). Reading
the activation `core/diagnostics.py` binds would condition a request on ambient state, and would
reach the reconciler, which writes no entry, wherever it runs inside a bound activation.

### 3. What the request changes

> **Normative.** Where `thinking_summaries` is true, a structured request to a model §3:2 names,
> where the request the same call sends with `thinking_summaries` false carries no thinking
> configuration of any kind, carries Anthropic's thinking configuration
> `{"type": "adaptive", "display": "summarized"}`, as the settings key `anthropic_thinking`. It
> differs in nothing else from the request the same call sends with `thinking_summaries` false.

> **Normative.** The models are a closed tuple in `models/structured.py`, matched exactly
> against the name of the model the request goes to, where that model is pydantic-ai's
> Anthropic model or wraps one: `claude-opus-5-5`, `claude-opus-5`, `claude-sonnet-5-5`,
> `claude-sonnet-5`, `claude-haiku-5-5`, `claude-fable-5-1`, `claude-fable-5`,
> `claude-mythos-5-1`, `claude-mythos-5` and `claude-mythos-preview`. A name is added only by a
> change that cites the vendor's statement that the model thinks adaptively when a request
> carries no `thinking` field.

> **Normative.** Which case applies is resolved per request, for the model that request goes
> to, as the mode is (ADR-0354 §4:3).

> **Normative.** A request to any other model, and to a named model where the request with
> `thinking_summaries` false would carry a thinking configuration, is the request the same call
> sends with `thinking_summaries` false. The settings that make one include the model's own
> pydantic-ai unified `thinking` and its own `anthropic_thinking`.

> **Normative.** The request asks for no effort, no budget, no other thinking field and no beta
> header of its own, and sets no output ceiling of its own (ADR-0354 §4:5).

The tuple is the models of Anthropic's table whose request without a `thinking` field runs
adaptive thinking. Matching exactly keeps a name nobody has checked, a future model's or another
platform's form of a listed one, on the unchanged request: the cost of a missing name is a
summary not kept, and the cost of a wrong one is a model asked to think that was not thinking.

### 4. What comes back

> **Normative.** `ReplyExchange` gains `thinking`, text or `None`, defaulting to `None`. Where
> the provider was built with `thinking_summaries` true, it is the text of the response's
> thinking parts, in order, those with no text left out, joined by one blank line, and made
> recordable as the reply is. It is `None` where no thinking part carries text, and always
> where the provider was built with `thinking_summaries` false.

> **Normative.** A thinking part stays no part of the reply. The reply, the value, a returned
> failure and its kind are what the same response would give with its thinking parts removed
> (ADR-0354 §4:6, §5:2).

> **Normative.** The canonical `StructuredCompleter` fake returns a thinking summary on the
> exchange where its script gives one, and `None` otherwise.

A thinking summary is derived from the response, not from the value, so ADR-0354 §5:3's "It
holds nothing derived from the value" holds of the exchange as it did.

### 5. Where the summary goes

> **Normative.** A stage that writes a returned entry for a structured call writes the
> exchange's `thinking` into that entry under the key `thinking`, a string, where it is not
> `None`, and writes no such key where it is. It is written with the rest of ADR-0354 §7:2's
> fields, before the stage acts on a returned failure.

> **Normative.** The summary reaches the stage's returned entry and nothing else. No value,
> episode, story, memory, plan, message or prompt carries it, and no later call does: not
> understanding's repair, whose assistant turn is the first reply's text (ADR-0354 §8:3), and
> not a follow-up question, whose assistant turn is the followed reply's text (ADR-0354 §8:8).

> **Normative.** No log line carries a thinking summary, and no trace gains a field, a key or a
> kind from this decision (ADR-0354 §7:3, §7:4).

> **Normative.** A stage reads the exchange's `thinking` only to write it into its returned
> entry. No decision any part of the hub makes is conditioned on it.

> **Normative.** A stage's given entry for a structured call is as it is without this decision.

A recorded summary is the provider's summary of its thinking, not the thinking itself, as
ADR-0314 §5 says of planning's. The record stays write-only (ADR-0314 §3:1): the follow-up
asker is handed the entry as it is handed every entry (ADR-0337 §8:5) and sends nothing of the
key, and `keep` makes a real case from a given entry (ADR-0337 §4:10), which holds no summary.

### 6. Which stages

| Structured call | Its returned entry carries `thinking` | Why |
| --- | --- | --- |
| Understanding's first completion and its repair | Yes | Its route is built keeping summaries (§2:3) |
| Each digest part | Yes | The same route |
| The observer's scout, framing and placement | Yes | Its two routes are built keeping summaries (§2:3) |
| The matters pass, story tidy-up | No entry is written | Consolidation's route keeps none (§2:4) |
| The memory reconciler | No entry is written | Its route keeps none (§2:4) |

> **Normative.** Understanding's first completion and repair, each digest part, and the
> observer's scout, framing and placement calls each write `thinking` by §5:1.

### 7. What the viewer shows

> **Normative.** The activation viewer shows a structured call's `thinking` on that call's step,
> under the heading planning's summary has, "Thinking (the provider's summary)", and shows
> nothing for it where the entry holds no `thinking`.

The viewer is outside the package and reads the record as files (ADR-0316). Its lane V2
(milestone 17, in flight beside this one) is briefed to render a top-level `thinking` string on
any returned entry in that way, so it needs no change of its own once §9's lanes land.

### 8. Tests

> **Normative.** T1's tests include, each failing on an implementation that meets only the
> others:
>
> - over the `anthropic` SDK with only the transport replaced (ADR-0061 §3), the request body a
>   provider built with `thinking_summaries` false sends for a structured call equals, byte for
>   byte, the body the same call sent on this decision's base tree, pinned in the test, for
>   `claude-sonnet-5-5` in native mode and for a model in prompted mode;
> - with `thinking_summaries` true, the body sent to `claude-sonnet-5-5` differs from the body
>   with it false in one key alone, `thinking`, which is
>   `{"type": "adaptive", "display": "summarized"}`, and carries no `output_config.effort`, no
>   changed `max_tokens` and no added beta header;
> - with `thinking_summaries` true, the body sent to `claude-opus-4-8` and `claude-sonnet-4-6`,
>   to a listed model whose own settings configure `anthropic_thinking`, to a listed model whose
>   own settings configure pydantic-ai's unified `thinking`, and the request to an
>   OpenAI model, each equal the request with it false;
> - a response holding thinking parts beside its text gives the same reply, value, failure and
>   failure kind as the same response without them, for a valid reply and for each of
>   ADR-0354 §5:2's four kinds;
> - the exchange's `thinking` joins the parts' text in order, leaves out a part with no text,
>   is `None` where no part has text, and is `None` with `thinking_summaries` false even where
>   a part has text;
> - `RetryingProvider` and `RoutingProvider` return the exchange's `thinking` unchanged;
> - the canonical fake returns a scripted summary, and `None` unscripted.

> **Normative.** T2's tests include:
>
> - with `diagnostic_record` true, the routed provider's and both observer routes'
>   `PydanticAIProvider`s are built with `thinking_summaries` true, and consolidation's and the
>   reconciler's with it false; with `diagnostic_record` false, every one with it false;
> - for understanding's first completion and repair, a digest part, and each of the observer's
>   three calls: the returned entry carries `thinking` where the exchange holds one, carries no
>   such key where it holds `None`, and the given entry is unchanged;
> - understanding's repair carries the first reply's text and nothing of its thinking;
> - no log line a stage writes carries a scripted summary's text;
> - a follow-up asked of a structured call that carried a summary sends nothing of it;
> - a `rerun` composes the observer's routes with `thinking_summaries` true and the
>   reconciler's with it false, and still counts every call against its bound (ADR-0335 §8:2).

### 9. Delivery

The lanes, each after this decision merges `Accepted`:

1. **T1, the field and its production implementation** (ADR-0137 §2): `ReplyExchange`'s field,
   `PydanticAIProvider`'s argument and request (§2:1, §2:2, §3), the reading of thinking parts
   (§4:1, §4:2), and the canonical fake (§4:3). Nothing is wired yet.
2. **T2, the consumers**, briefed against merged T1 (ADR-0137 §4): the composition root's
   routes (§2:3–§2:5), the three stages' returned entries (§5, §6), and the replay tool's
   counted providers, which stand in for each `PydanticAIProvider` the composition builds in a
   `rerun` and so must take the new argument and forward it. Each is an adaptation, so they are
   one consumer group.

> **Normative.** T1 may touch `core/types.py`, `models/provider.py`, `models/structured.py`,
> `ai_assistant.testing`, and their tests. It touches no file in `orchestration/`, `memory/`,
> `app/` or `scripts/`.

> **Normative.** T2 may touch `app/composition.py`, `orchestration/understanding.py`,
> `orchestration/digesting.py`, the observer's modules under `orchestration/observer/`,
> `scripts/prompt_replay.py` for `counted_models` and `CountedProvider` alone, and their tests.

> **Normative.** Where V2 merges without rendering a returned entry's `thinking` as §7:1 says,
> a lane that may touch `scripts/activation_viewer.py` and its tests alone makes it do so.

### 10. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0354 | §4:5's *It asks for no thinking setting* and *Nothing else in the request differs from what `complete` sends*, in the addition alone: where the provider keeps summaries, the thinking configuration §3:1 names, to the models §3:2 names. §4:6's *and is not recorded*, in the addition alone: where the provider keeps summaries, its text is the exchange's `thinking`, and the stage records it. §5:3's list, in the addition alone: the thinking summary. §7:2's list, in the addition alone: `thinking` | §3:1–§3:5, §4:1, §5:1 |
| ADR-0314 | §4's table, which §4:1 binds, in the addition alone: a structured call's returned entry, understanding's and a digest part's, also carries `thinking` where the provider gave a summary | §5:1, §6:1 |
| ADR-0333 | §2's table, which §2:1 binds, in the addition alone: a structured call's returned entry also carries `thinking` where the provider gave a summary | §5:1, §6:1 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0354 §13:1 | Nothing: this is the decision its first row names, and it is taken before any lane builds it |
| ADR-0354 §6:1, §6:2 | Nothing: the wrappers' policy and the object each consumer is handed stand (§2:6) |
| ADR-0354 §7:3, §7:4 | Nothing: no log line or trace carries a summary (§5:3) |
| ADR-0354 §8:3, §8:8 | Nothing: the repair and a follow-up carry the reply's text alone (§5:2) |
| ADR-0314 §3 | Nothing: the record stays write-only and nothing reads the summary back (§5:4) |
| ADR-0314 §5 | Nothing: planning's thinking is kept as it is, and this decision does for a structured call what §5:1 does for a round, on the models where it changes nothing else |
| ADR-0314 §2:1, §4:4 | Nothing: the setting follows `diagnostic_record`, and where the record is off no entry is built and every request is as it was |
| ADR-0335, ADR-0337 | Nothing: `replay` and `suite` send as they do, through providers built with `thinking_summaries` false. `rerun` composes the package over a copy with the record on (ADR-0335 §7:1), so its observer calls ask and record as the hub's do, into the copy's record. The follow-up asker and `keep` take nothing of the key (§5:2) |
| ADR-0316 | Nothing: the viewer reads the record as files and shows the key (§7:1) |
| ADR-0004 §1, §5 | Nothing: the summary is Tier 1 in the record and never logged |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0314, ADR-0333 and ADR-0354, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

### 11. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| Asking a model that does not think unasked to think on a structured call | A later decision: it changes what the model does and what it costs |
| A thinking summary from another vendor's model, such as OpenAI's reasoning summary | A later decision, if a configured route is not Anthropic's |
| Effort on a structured call | A later decision |
| A replayed or suite structured call keeping its summary | A later decision under ADR-0335 and ADR-0337 |
| Usage of the thinking tokens apart from the output tokens | A later decision, with #3090's measurements |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

## Consequences

**Easier.** The owner sees, on understanding's step, the digest's and the observer's, the
provider's summary of how the model reached its reply, as planning's already shows. A reply
that is hard to explain from its request can be read beside its reasoning.

**Harder.** With the record on, a structured response on the hub's model may take longer to
arrive, by whatever the summary adds: Anthropic says omitting it "reduces latency, not cost",
and does not say by how much. A slower response meets the per-attempt deadline and a stage's
own deadline (ADR-0354 §6:3) as any response does. Each returned entry grows by the summary's
length, inside ADR-0314 §6:3's file bound. Where the hub is routed to a model not on §3:2's
tuple, nothing is kept, and adding a model is a code change.

**Follow-on.** T1, then T2 (§9). V2 renders the key.

**Revisit when** the record shows understanding's or a digest's deadline failing more often with
the record on than off, or the hub is routed to a model the tuple does not name, or a consumer
wants thinking it does not already do (§11).

## Alternatives considered

- **A keyword on `complete_structured`, such as `keep_thinking`.** Rejected: it changes a
  Protocol member, a breaking change under golden rule 5, for a diagnostic concern every
  implementation and fake would then carry. ADR-0314 rejected passing the activation into
  `ToolCallingCompleter.respond` on the same ground.
- **Read the activation `core/diagnostics.py` binds, as the tool-calling completer does to
  write its entry.** Rejected: it conditions a request on ambient state rather than on what the
  composition root built, and would ask for summaries on the reconciler's and consolidation's
  calls wherever they run inside a bound activation, though they write no entry.
- **Key it on pydantic-ai's `anthropic_supports_adaptive_thinking`, as planning does.**
  Rejected: that key is true for Opus 4.6–4.8 and Sonnet 4.6, which do not think unasked, so a
  request to one would turn thinking on, and false for Opus 5.5 and Haiku 5.5, which do.
- **Ask for summaries on every route.** Rejected: the matters pass, the tidy-up and the
  reconciler write no entry, so the summary would reach code that keeps it nowhere.
- **A `Settings` switch of its own.** Rejected: the record is the only reader, so the record's
  own switch is the one that says whether a summary is wanted.
- **Keep the response's thinking parts whole, as planning's entry does.** Rejected: a
  structured call's returned entry keeps the exchange, not the response (ADR-0354 §7:2), and a
  summary is the one thing in a thinking part the owner can read. The signature is not
  readable and is not kept.
