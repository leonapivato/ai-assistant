# 71. Strengthen the planner's envelope extraction to a scanning parse

- Status: Accepted
- Date: 2026-07-26
- Partially supersedes: ADR-0047 — §4 step 1's extraction *mechanism* (the "first
  `{` to last `}`" slice); the Decision below replaces it with a scanning parse.
  Every other property of §4 — its goal, steps 2–4, the never-a-corrupt-plan
  guarantee, and §6's bounded repair — stands.

## Context

ADR-0047 §4 defined the text→`ActionPlan` extraction contract and said extraction
"is deterministic and precisely this". Its **step 1** located the JSON envelope by
taking "the substring from the **first `{`** to the **last `}`** (inclusive)" and
parsing it with `json.loads`, on the stated rationale that this "tolerates a model
that wraps the object in prose or a Markdown code fence without a fragile fence
parser." The Consequences section restated it as "first-`{`-to-last-`}` slicing
absorbs prose and fences."

That slice fails **step 1's own stated tolerance goal** the moment the surrounding
prose itself contains a brace (#293). For

```text
Here is {the requested plan}:
{"steps":[{"intent":"x","capability":"do_x"}]}
```

the first `{` opens the prose and the last `}` closes the envelope, so the slice
spans both fragments; `json.loads` fails on a reply that *did* carry a valid
object, and with such a reply held constant the bounded repair round exhausts and
`plan` raises `PlanningError`. The prose tolerance §4 claims holds only for
brace-free prose. The failure is graceful and bounded — never a wrong or corrupt
plan — but the ratified claim is not true as the enumerated mechanism achieves it.

Issue #293 offered two options: narrow §4's claim to brace-free prose (docs-only),
or strengthen the extraction so the claim holds. The owner wants the capability,
so this ADR takes the second. Because ADR-0047 §4 enumerated the algorithm
"precisely this", changing it falsifies ratified ADR text; and because the change
is **behavioural** (see Consequences), ADR-0070 §1's "a reader would act
differently" test classifies it as a change to what was decided — a partial
supersession, not an in-place amendment.

## Decision

**We replace ADR-0047 §4 step 1's mechanism with a scanning parse.** Step 1 now
scans each `{` in `Message.content` left to right and attempts
`json.JSONDecoder.raw_decode` from that position — which decodes one object and
stops at its end, ignoring any trailing text:

- The first decoded object whose `steps` is a **non-empty list** is taken as the
  envelope — the shape §4 step 2 requires — so a decoy object in the prose ahead of
  the envelope is stepped over rather than planned from, including one that carries
  a `steps` key of the wrong type or an empty list (which would otherwise shadow a
  valid envelope behind it — the predicate is the envelope shape, not merely the
  presence of a `steps` key).
- If no decoded object is a well-formed envelope, the first decoded object stands
  in, so a single malformed object still reaches step 2's specific verdict (`no
  'steps' list`, or an empty plan) rather than a generic miss.
- A decoded object is advanced **past**, never re-entered: the scan resumes at the
  object's end, so a nested object is part of its parent, not a separate candidate.
  An outer envelope whose `steps` is empty is therefore rejected as an empty plan
  (§4) rather than being overridden by a non-empty `steps` nested inside it — a
  malformed decision cannot become a valid audit record by hiding a plan-shaped
  object in its metadata.
- A `{` that does not open a decodable object — a brace in the prose, a fragment —
  is stepped over instead of failing extraction. A candidate whose decode raises a
  bounded parse error that is *not* a syntax miss (the digit-limit `ValueError`
  CPython raises for an over-limit integer literal, or the `RecursionError` a
  pathologically nested payload raises) is a miss the same way, so no unhandled
  error escapes; the scan carries on and a well-formed envelope elsewhere is still
  found, and only where the whole reply yields no envelope does it fall to §6's
  bounded repair.
- At most `_MAX_EXTRACTION_MISSES` (256) decode **misses** are tolerated, which
  keeps the scan linear. A failed `raw_decode` is cheap to parse but costs work
  proportional to how far into the reply it reached (`JSONDecodeError` computes a
  line and column), so attempting it at *every* brace of a brace-dense malformed
  reply is quadratic and would block the event loop this runs synchronously on;
  bounding the misses bounds that. A decoded object is not a miss and does not
  consume the budget, so any number of *valid* JSON fragments may precede the
  envelope — only unparseable braces are limited. The bound is generous, so a
  conforming reply (envelope first) is unaffected; a reply that buries the envelope
  behind more than `_MAX_EXTRACTION_MISSES` unparseable braces degrades to bounded
  repair. This is the one narrowing of §4's prose tolerance: it holds for prose
  with up to that many unparseable brace fragments before the envelope, not
  unboundedly, the price of not stalling the loop on adversarial input.
- When no decodable object is found within the miss budget, extraction fails.

This is scoped to step 1 alone. §4 steps 2–4 (shape check, per-step validation,
`PlanStep`/`ActionPlan` construction under the injected id factory and clock) are
untouched, so every `core` invariant is still enforced on the constructed plan.
§6's bounded repair is untouched. The change is `planning`-internal: no Protocol,
no `core` type, and no import boundary moves.

## Consequences

- **§4's prose-tolerance claim becomes true, within a bound.** A model that wraps
  the envelope in prose — including prose that itself contains a brace, which #293
  showed the slice did not deliver — is now tolerated, up to the
  `_MAX_EXTRACTION_MISSES` unparseable-brace bound above. That bound is the
  deliberate price of not stalling the event loop on adversarial brace-dense input;
  it is generous and does not bite a conforming reply, whose envelope is the first
  decodable object.
- **One behavioural difference, stated honestly.** A reply whose *outer* fragment
  is malformed but which *contains* an inner valid envelope now yields a plan from
  that inner envelope, where the old slice returned a bounded `PlanningError`. This
  is the "a reader would act differently" observable that makes the change a
  decision change under ADR-0070 §1, and it is why this is ADR-0071 rather than an
  amendment inside ADR-0047. It is a *widening* of the tolerance §4 already stated,
  never a corrupt plan: steps 2–4 still validate everything they validated before,
  so a malformed decision cannot masquerade as a valid audit record.
- **The safety envelope is unchanged.** Extraction stays deterministic; a
  genuinely unparseable reply still enters bounded repair and ends in a clean
  `PlanningError`; ids, timestamps and every `StepStatus` remain the property of
  deterministic code (VISION §7, ADR-0047 §§1–2).
- **This is a partial supersession, ADR-0070's first real use.** ADR-0047's status
  carries the leading-token `Partially superseded by ADR-0071 (§4 step 1's
  extraction mechanism)` form (ADR-0070 §4); §4's body is left standing,
  append-only (ADR-0001), with a dated header note pointing here. Only step 1's
  mechanism is replaced — the authoritative extent of the replacement is this ADR
  (ADR-0070 §4's "the scope is a pointer; the superseding ADR states the extent").
- **No separate ratified-first PR.** This partial supersession changes no Protocol
  or `core` type, so ADR-0015 §5 / golden rule 5 do not apply; ADR-0070 §1 confirms
  such an ADR rides in the implementation PR and is `Accepted` on merge rather than
  ratified ahead of it. It lands in PR #405 alongside the `_extract_object` change
  it governs.
- **Harder / revisit when**: a provider offering typed/structured output lands, at
  which point the whole text-envelope extraction — scan included — could be
  replaced by a schema the provider enforces (ADR-0047 already flags this), and
  this mechanism retires with it.
