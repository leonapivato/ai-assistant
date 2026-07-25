# 61. Model-agnosticism is a tested property, not a design intention

- Status: Accepted, §2's one-route caveat retired by ADR-0062
- Date: 2026-07-24

## Context

"Model-agnostic" is the first clause of this project's own description and the
load-bearing half of [VISION](../../VISION.md)'s thesis: the underlying LLM is
interchangeable, and the value is the orchestration around it. Every
architectural mechanism that claim needs was already built and is genuinely
sound — the `ModelProvider` Protocol (ADR-0011), the `retryable`/`routable`
taxonomy and `RoutingProvider` (ADR-0013), a `default_model` that is a bare
`"provider:model"` string rather than a closed enum, and an import-linter
contract confining provider SDKs to `models/`.

`docs/review/architecture-validation-2026-07-24.md` (C6) nevertheless returned
**ASPIRATIONAL**, and the three facts it rested on were all true:

1. `pyproject.toml` installed `pydantic-ai-slim[anthropic]` — one extra, one
   vendor.
2. `RoutingProvider` was constructed nowhere in `app/composition.py`. The
   fallback mechanism existed in `models/` and was unreachable from any running
   assistant.
3. Every provider test drove pydantic-ai's own `TestModel`/`FunctionModel`
   doubles, which stand *in place of* a vendor SDK — so no second vendor's error
   shapes, and no vendor's wire format at all, had ever been exercised.

The two available responses were to narrow the claim or to verify it. The claim
is the product thesis, so narrowing it is not a documentation edit; it is a
change of what this project is. We verify it.

One consequence of (1) deserves stating plainly, because it makes the gap
concrete rather than theoretical. pydantic-ai resolves a model spec **lazily, at
the first completion**, and `PydanticAIProvider` deliberately constructs with
`defer_model_check=True` so wiring stays offline. With only the `anthropic`
extra installed, a deployment setting `ASSISTANT_DEFAULT_MODEL=openai:gpt-5`
therefore starts cleanly, passes configuration validation, and fails at the
first user request with a bare, non-retryable `ModelError` wrapping
`ImportError: Please install the openai package`. The seam was agnostic; the
installed artifact was not.

## Decision

We will make model-agnosticism something the gate checks, in three parts.

### 1. Ship two vendor extras

`pydantic-ai-slim[anthropic,openai]`. A second extra is what makes the claim true
of an **installed artifact** rather than of the source: any `"provider:model"`
string an operator can legitimately set now resolves, for two vendors, without a
reinstall.

It is a runtime dependency, not a dev one, and that is the point — a dev-only
extra would test a stack no user has. The cost is install weight (`openai` and
its tokenizer, `tiktoken`) for users who will only ever use one vendor. We accept
it: an operating system whose stated moat is model-independence should not ship
able to talk to exactly one vendor.

Two, not three or all: two is what turns "provider-shaped" from an assertion into
a comparison, and each further vendor costs install weight for a decreasing
return. The set is revisited when a third vendor is actually configured by
someone.

### 2. The composition root builds the router, retry inside routing

`app/composition.py` now hands the planner a `RoutingProvider` whose routes are
each a `RetryingProvider` over a `PydanticAIProvider` — the order ADR-0013 §3
recommends and which **nothing in `models/` can enforce**, since enforcing it
would mean a wrapper knowing what wraps it. It is a wiring decision, and this is
the layer that owns wiring decisions.

Route construction is split into two functions on purpose:

- `_model_specs(settings)` answers *what to route over*. It returns a sequence
  and, today, that sequence has exactly **one** element, because `Settings`
  carries exactly one model spec (`default_model`).
- `_build_model_provider(settings, specs)` answers *how to compose it*, for any
  number of specs.

**We deliberately do not invent a second model setting here.** A fallback model
list is an operator-facing configuration surface — its name, its parsing, its
validation, its interaction with `default_model` — and the composition root reads
configuration rather than defining it. That is `core/config.py`'s decision to
make, and is filed as follow-up work.

So the honest statement of what this ADR changes, and what it does not:

- **Changed:** the fallback mechanism is on the production path. The route loop,
  the routable/non-routable branch, `_classify`'s taxonomy mapping and the
  exhaustion log all execute on a real failure of a real deployment. Adding a
  second route is now a change to one function returning one more string, not a
  restructuring of the seam.
- **Not changed:** with one route, no fallback can occur. The behaviour delta
  against the previous wiring is exactly one additional Tier 2 warning on a
  routable failure; the exception a caller sees is identical, by construction
  (ADR-0013 §5 re-raises the last failure untouched).

That the composed router *does* fall back correctly when given more than one spec
is asserted directly against the object `_build_model_provider` returns, so the
one-route configuration is a configuration fact rather than an untested code
path.

### 3. Run the shared conformance suite against two real vendor SDKs, offline

The `ModelProviderContract` suite now runs three bindings: pydantic-ai's
`TestModel` (as before), the real `anthropic` SDK, and the real `openai` SDK.

Both vendor bindings are the real stack down to the socket —
`PydanticAIProvider` → pydantic-ai's `AnthropicModel`/`OpenAIChatModel` → the
real vendor client → `httpx` — with **only the transport replaced**, by
`httpx.MockTransport`. Each vendor SDK really serialises our message history into
its own wire format, really parses a canned response with its own models, and
really raises its own exception type for a canned HTTP status.

Three alternatives were considered and rejected:

- **A live API key in CI.** Rejected outright: it makes the gate depend on two
  vendors' uptime, quota and billing, and puts two long-lived credentials in CI
  to test something that is not about either vendor's availability.
- **Recorded responses (cassettes).** Closer, but they record a *past* API. A
  cassette recorded against one SDK version keeps passing after that SDK changes
  how it maps messages or raises errors — which is precisely the class of change
  this suite exists to catch. They also need re-recording against a live key, so
  the credential problem returns on the maintenance path.
- **A construction-level test with no HTTP at all** (assert `_classify` maps a
  hand-built vendor exception). This tests our dispatch against *our belief* about
  the vendor's exception hierarchy. The belief is the untested thing.

Mocking the transport is the smallest replacement that leaves every layer whose
provider-independence is in question actually running. What it does **not**
prove, and does not claim to, is that a vendor's live API behaves as its SDK
expects — a different question, and not one a gate should ask.

**No credentials are read.** Each client is built with a literal dummy key rather
than allowed to fall back to the environment, so a developer's real key can never
be picked up; and every test in the module runs inside `network_denied()`
(`tests/models/network_guard.py`), which turns "offline" from an assumption into
an assertion.

`max_retries=0` on both clients, because each vendor SDK retries 429s and 5xx
*internally* by default: a canned failure would otherwise arrive as three
requests and the classification under test would be of the SDK's last attempt
rather than of the failure. These tests assert **classification only** —
`RetryingProvider` is deliberately not in this path, and our own retry semantics
are exercised separately, over a fake, in `tests/models/test_retry.py`. So the
vendor's retry behaviour is *removed* here, not measured.

### 4. Vendor divergence in message mapping is asserted, not discovered

The suite pins what each vendor actually puts on the wire for the same
`Message` list. Two divergences are now regression-tested:

| Our input | Anthropic sends | OpenAI sends |
| --- | --- | --- |
| A **leading** `Role.SYSTEM` | a top-level `system` field, outside `messages` | a fourth `messages` entry with `role: "system"` |
| A `Role.SYSTEM` **after** an assistant turn | the text inlined into the next *user* turn, wrapped in literal `<system>…</system>` tags | a real `role: "system"` message, in place |

The second is the sharp one. Anthropic's API has exactly one system slot and it
is at the top, so a mid-conversation system instruction cannot go there:
pydantic-ai demotes it into the following user turn. The instruction survives as
text but **loses its privileged role**, landing in the same channel as
user-supplied content. Same input, same `_to_model_messages` output, materially
different prompt semantics.

We assert this rather than fix it. `ModelProvider.complete` promises neither
behaviour, no caller builds such a history today (`ModelBackedPlanner` always
leads with its system prompt and always ends on a user turn), and choosing one
behaviour for both vendors would mean this layer overriding a vendor adapter's
own mapping — a much larger decision than this ADR. What the assertions buy is
that the divergence is *visible*: a change to either vendor adapter that silently
moves where a system instruction lands now fails the gate.

## Consequences

**What this settles.** The C6 finding's central worry — that a second SDK's
exceptions might not land in pydantic-ai's `ModelHTTPError`/`ModelAPIError`
hierarchy the way Anthropic's do, silently under-classifying errors — is now
tested and **did not reproduce**. Both vendors produce byte-identical
classification across 401, 403, 408, 429, 500, 503, a 400, and a transport-level
connection failure. `_classify` and `_classify_status` are confirmed
provider-shaped, and any regression is a gate failure rather than a production
surprise. The retry semantics in `models/retry.py` sit above the seam entirely
and never touch a vendor type, so they were never at risk.

**What breaks first on a third provider** is now a much shorter list, and none of
it is error classification:

- **Message mapping**, per §4 — every vendor decides for itself what a
  non-leading system instruction means, and the seam neither normalises nor
  reports it.
- **`Role.TOOL` is refused unconditionally** (`provider.py`), a capability gap
  belonging to our seam, not to any vendor — both tested vendors support tool
  results. Pinned per vendor so it reads as a debt we owe rather than one
  vendor's restriction.
- **A non-JSON response body** escapes pydantic-ai's exception hierarchy
  entirely (a bare `json.JSONDecodeError`) and is classified as a non-retryable
  `ModelError` — so a gateway returning an HTML error page is treated as
  permanent. Identical on both vendors, so it is a general classification gap
  rather than an agnosticism one; filed as follow-up.

**What gets harder.** Installs carry a second vendor SDK. The test suite now
depends on two vendors' request/response *schemas* being stable enough for a
hand-written canned response to parse — a real maintenance surface, and the
deliberate trade against cassettes, which would have hidden exactly that drift.

**What triggers revisiting.** A third vendor being configured in earnest (does
the two-vendor comparison still generalise, or does the suite need to be
parametrised over a registry?); a fallback-model setting landing in
`core/config.py`, which retires §2's one-route caveat; or `Role.TOOL` support,
which would give the mapping tests a second dimension.
