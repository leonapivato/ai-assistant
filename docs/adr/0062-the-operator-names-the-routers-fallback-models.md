# 62. The operator names the router's fallback models

- Status: Accepted
- Date: 2026-07-24

## Context

[ADR-0061](0061-model-agnosticism-is-a-tested-property.md) §2 put `RoutingProvider`
on the production path: `app/composition.py` now hands the planner
`RoutingProvider([Route(RetryingProvider(PydanticAIProvider(spec)))])`, and the
composed router is asserted to fall back correctly when given more than one spec.
It also recorded, plainly, what that did **not** buy: `_model_specs(settings)`
could only ever return one spec, because `Settings` carried one model
(`default_model`). The mechanism was reachable and correct, and in production it
had nothing to fall back to. ADR-0061 §2 deliberately stopped there — a fallback
list is an operator-facing configuration surface, and the composition root reads
configuration rather than defining it.

This is that configuration surface. It is the remaining half of the C6 finding in
`docs/review/architecture-validation-2026-07-24.md` (#353).

Four things had to be decided, and one fact about the model seam bears on all of
them. **A model spec that cannot be resolved produces a non-routable failure.**
pydantic-ai resolves a spec lazily, at the first completion; a bad one raises
`ValueError: Unknown provider` or `ImportError: Please install the ... package`,
neither of which is in pydantic-ai's `ModelHTTPError`/`ModelAPIError` hierarchy,
so `_classify` maps it to a bare `ModelError` — `retryable = False`,
`routable = False`. `RoutingProvider` re-raises a non-routable failure
immediately, without trying the next route (ADR-0013 §5). So a single
unresolvable spec does not degrade the router; it **truncates** it:

- an unresolvable **primary** means the router never reaches route 2 at all — the
  entire configured fallback order is dead, on every request;
- an unresolvable **fallback** means the order stops there — routes behind it are
  never tried either.

That is worse than the "one bad route out of N" intuition the shape of the config
invites, and it is why validation is worth paying for.

## Decision

### 1. `ASSISTANT_FALLBACK_MODELS`, comma-separated, not JSON

`Settings` gains `fallback_models: tuple[str, ...]`, defaulting to empty, and
`_model_specs` returns `(default_model, *fallback_models)`. `default_model` always
leads; the fallbacks follow in the order they were written. An unset deployment
therefore keeps ADR-0061 §2's single route exactly.

The form is the decision. **pydantic-settings parses a list- or tuple-typed field
as JSON**, and it does so in the settings *source*, not in validation — verified,
not assumed: `ASSISTANT_FALLBACK_MODELS=openai:gpt-5,anthropic:claude-x` fails
with `SettingsError: error parsing value for field "fallback_models" from source
"EnvSettingsSource"`, and the operator's recourse is
`ASSISTANT_FALLBACK_MODELS='["openai:gpt-5","anthropic:claude-x"]'`. Quoting,
brackets, and a diagnostic that names JSON rather than the mistake, for a setting
whose whole content is two model names.

Because the JSON decode happens in the source, **a `BeforeValidator` alone does
not fix it** — the value never reaches validation. `NoDecode` on the field is
pydantic-settings' own documented hook for exactly this: it disables complex
decoding for that field so the raw string arrives at our `BeforeValidator`, which
splits on commas, strips whitespace and drops empty segments. Source **precedence
is untouched** — environment still beats `.env` still beats the default, because
only the *decoding* of the resolved value changes, not how it is resolved. That
was checked against both sources, and against direct construction: a tuple passed
in Python falls through the splitter unchanged.

Consequences worth stating: an empty or all-whitespace value now means "no
fallbacks", the same as omitting the variable, which is how an operator switches
the feature off without changing the deployment's shape; and a JSON array is no
longer accepted for this field, because it is no longer decoded as one — it is
refused as a malformed spec (§2), naming the spec rather than the syntax.

The name mirrors `default_model` rather than inventing a vocabulary. It is a
*model* list, not a *provider* list: two entries may name the same vendor.

### 2. A malformed spec fails at load. An **uninstalled vendor** still fails at first completion — and that is a gap, not a judgement

Two failure modes hide under "a bad model spec", and this ADR closes one of them.

**Form is validated at load.** Every spec — `default_model` and each fallback —
must match `provider:model`: a non-empty provider, a non-empty model, and no
whitespace or stray punctuation. `ASSISTANT_FALLBACK_MODELS=openai-gpt-5` is now a
`ConfigurationError` at startup rather than a `ModelError` on some user's request
weeks later.

The pattern is grounded rather than invented: it accepts all **602** colon-bearing
names in pydantic-ai's own `known_model_names()`, including the shapes that look
unusual (`bedrock:us.anthropic.claude-3-5-sonnet-20240620-v1:0`, colons in the
model half; `gateway/openai:gpt-5`, a slash in the provider half;
`huggingface:Qwen/Qwen3-235B-A22B`). The one thing it rejects that pydantic-ai
accepts is the literal `test` — the only colon-less name pydantic-ai knows, its
in-memory dummy. That is not a production configuration, and
`PydanticAIProvider` already takes a pydantic-ai `Model` **instance** for the
test path, which every test in this repository uses. We accept losing it.

Applying the rule to `default_model` as well as to the fallbacks is deliberate.
The asymmetry — "the primary may be malformed but a fallback may not" — would be
indefensible on its own terms, and per the Context above an unresolvable primary
is the *worse* of the two cases, since it disables the whole order rather than the
tail of it.

**Installedness is not validated at load, and should be.** A spec naming a vendor
whose extra is not installed (`groq:llama-3`) is well-formed, passes this
validation, and fails at first completion with a bare `ModelError` wrapping
`ImportError` — exactly the state ADR-0061's Context described. The argument for
closing this is strong and we accept it: a fallback is only ever exercised once
the primary has already failed, so a misconfigured one converts a degraded state
into an outage at the precise moment it was being relied on, and the operator's
chance to discover it in advance is removed. A fallback that only fails when you
need it is worse than no fallback.

We do not close it **here**, and the reason is a boundary, not a disagreement:

- **Flipping `defer_model_check` is not viable.** `PydanticAIProvider` passes
  `defer_model_check=True` on purpose (ADR-0061). Flipping it calls
  `models.infer_model(spec)` at construction, which constructs the vendor
  *provider*, which reads the vendor's API key: verified — with no credentials in
  the environment, `infer_model("anthropic:claude-x")` raises
  `UserError: Set the ANTHROPIC_API_KEY environment variable`. That would make
  `build_engine` require live credentials and would take the whole composition
  test suite offline-hostile. It converts a wiring step into a credential check.
- **The right primitive exists, and it is not reachable from here.**
  `pydantic_ai.models.infer_provider_class(name)` performs precisely the import
  under test and **needs no credential** — verified: it returns
  `AnthropicProvider`/`OpenAIProvider`, raises `ImportError` for a known vendor
  whose extra is missing, and `ValueError: Unknown provider` for one pydantic-ai
  does not know. It lives behind `pydantic_ai`, which the import contract forbids
  to `ai_assistant.core` **and** to `ai_assistant.app` (golden rule 4). So the
  check belongs in `models/`, called from the composition root — a third
  subsystem, outside this change's scope.
- **The alternative that would have fit in `core` is worse than the gap.**
  `core/config.py` could carry a provider→package table and use
  `importlib.util.find_spec`. It imports no SDK, so `lint-imports` would pass —
  and that is the trap. pydantic-ai ships **22** provider prefixes, so the table
  is either an allowlist that refuses a vendor an operator legitimately installed,
  or a mirror of pydantic-ai's registry that goes stale silently on the next
  release. Either way it puts vendor knowledge in `core`, which is the exact thing
  golden rule 4 exists to prevent, to buy a check that `models/` can do exactly.
  Mechanical compliance with the contract while defeating its purpose is not a
  cheaper version of the right answer.

So: **decided in principle, deferred in mechanism**, filed as follow-up. This ADR
records the decision so the follow-up is an implementation rather than a fresh
argument. Nothing regresses in the meantime — the gap is `default_model`'s today,
and the fallback list is opt-in.

### 3. A fallback may not repeat a route already in the order

A fallback that repeats `default_model`, or an earlier fallback, is refused at
load, naming the offender and the position it repeats.

The operational case for refusing is stronger than "it buys nothing". Routing
moves to the next route only after the previous one failed **routably** — the
provider is down, throttled, or refusing our credentials — and every one of those
is a property of the provider, not of the individual request. A repeated route
therefore re-sends the same prompt to the same place, pays for it, and fails the
same way. It cannot succeed in the state that causes it to be reached.

Deduplicating silently was the alternative and is the worse one: it leaves the
operator believing they configured a fallback they do not have, which is the same
class of harm as the uninstalled-vendor gap in §2. The cost is one loop in a
`model_validator`. The rule is on the *spec*, not the vendor — `openai:gpt-5` with
`openai:gpt-4o` behind it is a legitimate and useful order, and stays expressible.

### 4. `Route.model` stays a code-level capability

ADR-0013 §2 lets one provider appear as several routes with a per-route `model`
override — a cheap model ahead of a stronger one. It is **not** made configurable
here.

Expressing it needs configuration to name a *route* rather than a model: a
provider, a model, and their pairing, per entry. That is a structured value, which
puts the JSON-versus-readable-string problem of §1 back on the table in a form no
comma-separated string solves; and it is a second way to say something §1 already
says, so the two would have to define precedence over each other. Nobody has asked
for it. If it is wanted it is its own decision, with its own ADR, and this one
does not prejudge it — `_model_specs` returning a flat sequence of specs is
extendable to a richer route description without disturbing anything downstream.

## Consequences

**What this settles.** ADR-0061 §2's one-route caveat is retired: a deployment can
now configure a router that genuinely falls back, and the mechanism ADR-0013 built
and ADR-0061 wired is reachable end to end from configuration. ADR-0061's own
"what triggers revisiting" list named exactly this. C6's remaining half is closed.

**What an operator gets that they did not have.** Three configuration mistakes
that used to surface as a `ModelError` mid-request now surface as a
`ConfigurationError` at startup, naming the setting: a malformed spec, a spec in
the wrong syntax, and a duplicated route. The count of mistakes that still surface
late is one — naming a vendor whose extra is not installed (§2).

**What is still not true.** The two-vendor install (ADR-0061 §1) bounds what a
fallback can usefully name to `anthropic` and `openai` without a reinstall, and
nothing at load says so (§2). Preference order remains **static**: the first
healthy route always wins, a persistently dead primary is re-tried on every
request, and there is no health tracking or circuit breaking — the VISION §6
ambition of ranking by latency, cost or observed reliability needs state and is
still a later slice. And with a configured fallback, a request that previously
failed fast now costs the primary's full retry budget before the fallback is
tried; that is the point of the wrapper order (ADR-0013 §3), but it is a latency
change an operator opts into.

**What gets harder.** `core/config.py` now knows the *shape* of a pydantic-ai
model spec. That is a small piece of coupling to an external convention, and the
regex will need revisiting if pydantic-ai adopts a character it does not permit —
a gate failure in the config tests, not a production surprise, because the pattern
is tested against the shapes pydantic-ai actually ships.

**What triggers revisiting.** The installedness check landing in `models/`, which
closes §2's gap; a third vendor extra, which changes what a fallback can usefully
name; or a real request for per-route model overrides, which is §4's own ADR.
