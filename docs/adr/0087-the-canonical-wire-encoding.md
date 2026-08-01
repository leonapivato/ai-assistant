# 87. The canonical wire encoding, and the vectors that make it testable

- Status: Proposed
- Date: 2026-08-01
- **This is a fifth change inserted into ADR-0084 §5's four, and its position is
  *before the triad*.** That is the load-bearing claim and §6 argues it from
  ADR-0084 alone: §5's own item 3 says the triad ships a **canonical fake** and a
  **conformance suite**, so change 3 is where a second implementation arrives —
  and §4 rules that the size limit is a clause of the contract that "*every*
  implementation enforces". A limit is a byte count. Two implementations holding
  an unratified byte count can both pass a behavioural suite and still disagree
  about which calls are refused, which is the substitutability §4 exists to
  guarantee. So the bytes are ratified before change 3, by an ADR, which is
  golden rule 5 and ADR-0015 §5 applied to the one clause of this contract that
  is defined in bytes.
- **It ratifies the bytes and nothing else.** No method, no field, no type, no
  setting, no figure, no limit. **One rule does move a length**, and it is stated
  here rather than buried: §2e's duration form grows a duration of 365 days or
  more by at most **three bytes** — the bound is proved in §2e rather than
  sampled — while §2a's ordering is length-preserving and §4 normalises nothing.
  So any reserve, floor or limit computed downstream must be computed on §2's
  forms rather than the library's; §7 says who owns those numbers.
- **Written with implementation contact.** Every byte string in §5 was produced
  by running the encoding against `pydantic 2.13.4` / `pydantic-core 2.46.4` on
  CPython 3.14.6, over the shapes the tree carries at `main` @ `89e0cfe` and the
  result types ADR-0084 §4 names. Where pydantic's default output and this ADR
  disagree, §3 names the case, ratifies one, and says why.
- **It stands alone, and cites the surface ADR only as a draft.** ADR-0085 is
  `Proposed` and unmerged (#549). Nothing decided here depends on it: every
  premise is taken from ADR-0084, ADR-0021 or the tree, and §5's vectors carry
  their own inputs. Where ADR-0085's draft is quoted it is because it is the best
  statement of a problem, and it is marked as in flight each time.
- **This ADR partially supersedes ADR-0084 on two clauses, and the record lands
  in this change.** **§3's payload-encoding rule** — that a payload is
  "serialised through pydantic's JSON mode" — is replaced, because naming a
  library fixes a *form* and not a byte string, and because the three places
  §3 corrects are three places a reader of ADR-0084 would emit forbidden bytes.
  **§5's four-change enumeration** becomes five. §10 applies ADR-0070 §1's test to
  each and states the record's form; ADR-0084's `Status` line and its appended
  dated note are the whole of it (ADR-0070 §1, ADR-0082 §2), and **no ratified
  text of ADR-0084 is rewritten** — not §3's bullets, not §5's list, not a word of
  §5's reasoning, which §6 shows the insertion honours rather than strains. Nearly
  all of §3 stands and is used as given, including its envelope member-order
  sentence, which §2's payload scoping leaves true of its subject.
- **No implementation lands with it.** No `src/`, no `tests/`.

## Context

### ADR-0084 declared a limit in bytes, and answered "which bytes" by naming a library

ADR-0084 §4 ruled:

> **The size limit is part of the promoted Protocol's declared contract, not a
> property of the transport, and *every* implementation enforces it** — the
> in-process engine included. The conformance suite (§5) is what holds them to
> it.

and gave the reason: otherwise "the wire client would refuse a 17 MiB utterance
that the in-process `Engine` accepts, and the two implementations §5 makes
substitutable would diverge on a value both are handed".

**A limit in bytes is a predicate over byte strings, so something has to say
which byte string a value is, and §3 does say** — it is worth quoting exactly,
because this ADR replaces it and an ADR that replaces a clause should print it:

> - a **result** payload is a promoted `core` model (§4) serialised through
>   pydantic's JSON mode …
> - **arguments and scalars** — a `str` utterance, a flag, an optional id, a
>   `timedelta` budget — take pydantic's JSON-mode form for their type, so a
>   duration is an ISO-8601 string rather than a convention invented here;

**That is the right shape and the wrong instrument, and this ADR keeps the shape.**
The shape is: bind to an encoding that already exists rather than invent one —
§3's own closing sentence, "choosing an existing encoding rather than specifying a
new one is the whole point of this subsection". §2 does exactly that. What does
not survive is *which* existing encoding, because **naming a library does not
determine a byte string**, and three measured facts say so:

- **Pydantic's JSON mode does not make equal values encode alike.** It emits a
  `FrozenJsonMapping` in the order a caller happened to insert keys, so
  `Confirmation(parameters={"a":1,"b":2})` and `Confirmation(parameters={"b":2,"a":1})`
  are `==`, hash alike, and produce two byte strings (§4). Two implementations
  can both obey §3 to the letter and disagree about a payload's bytes.
- **A library's behaviour cannot be frozen, and §3 freezes this codec** — in the
  same subsection: "the length prefix, the UTF-8 JSON codec … keep their
  representation in every protocol version, **permanently**". A permanent
  representational commitment whose content is a third party's changelog is not
  a commitment. `pydantic-core`'s float formatter, its duration spelling and its
  `ser_json_inf_nan` default are all configuration surface, and each moves the
  limit's boundary.
- **It is silently wrong in two places.** A non-finite float becomes `null` — a
  value changed into a different value with no error — and a duration of 365 days
  or more acquires a `Y` component (`timedelta.max` is `"P2739726Y9DT23H59M59.999999S"`),
  a *nominal* unit that does not denote a fixed elapsed time and round-trips only
  because both halves privately agree a year is 365 days.

**Refusal is contract-visible behaviour**, not an implementation detail — a typed
error a caller catches and branches on. So a disagreement about the boundary is a
disagreement about the contract, and it is exactly the divergence §4 moved the
limit into the contract to prevent, one level below where §4 was watching. §10
records the supersession this ADR therefore owes ADR-0084 §3, alongside §5's.

### The gap becomes reachable at ADR-0084 §5's change 3, not change 4

The natural reading is that this can wait for the implementation, because the
transport is built in §5's change 4 — "the hub, the `wire` package, the client".
ADR-0084 §5's own item 3 refutes it:

> 3. **the triad** (`core/protocols.py`, `core/types.py`, conformance suite,
>    **canonical fake**);

A canonical fake is a second implementation of the Protocol, and the conformance
suite is a shared test both it and the concrete `Engine` must pass
(`CONTRIBUTING.md` → "Adding a Protocol"). Change 3 therefore ships two
implementations and the very suite §4 nominates as "what holds them to it" —
before change 4 exists. If the encoding is unratified at that point, the suite
cannot assert the clause it was named for: it can check that an oversized payload
is refused and that a small one is not, but not *where* the line is, because no
ratified text puts it anywhere. The clause ADR-0084 §4 calls the conformance
suite's job is the one thing the conformance suite would have to skip.

**Narrowing the suite is the honest response to an unratified encoding, and it is
a cost rather than a solution.** The lane drafting the surface ADR (ADR-0085,
`Proposed`, #549) reached exactly this conclusion and wrote the narrowing into
its §8c — the suite tests the limit's behaviour and not its boundary. That is
right, given an unratified encoding. This ADR removes the given.

### The bytes want their own ADR, and that is not a workaround

**A hand-written byte grammar inside a contract ADR about method signatures is
the unspiked seam #281 and `CONTRIBUTING.md` warn against.** The surface ADR's
lane attempted it, spent four review rounds each finding one more uncovered
corner, and withdrew it with a fifth still open. An enumeration of a space nobody
can prove they have covered is a list of the cases someone thought of, not a
specification. **That objection is correct and this ADR does not dispute it** —
§1 answers it by changing the instrument rather than by writing the enumeration
more carefully.

**So the resolution is a separate ADR, and it is ADR-0084 §5's own move applied
once more.** §5 split "the façade is promoted" from "here is the surface"
"because they answer different questions and only one of them can be answered
honestly today". *What are the bytes* is a third question of that kind: it wants
contact with a serialiser and a test suite rather than with a deployment or a
signature, and it wants a reviewer reading byte strings. Two questions that want
different evidence get different ADRs.

### This ADR does not depend on the surface ADR

The surface ADR is `Proposed` and unmerged. Every premise above is ADR-0084's;
§2's rules are over Python and JSON types; §5's vectors carry their own inputs, so
each is checkable without consulting any other document. What the surface ADR
supplies — the exact promoted field set — affects only which *composite* vectors
§5e happens to spell out, and §5e states each one's field list inline for that
reason. Where this ADR quotes the surface ADR's draft it does so because that
draft is the clearest existing statement of a problem, and it says "in flight"
every time.

### "One encoding" is two properties, and they are not the same one

The surface ADR's draft (in flight, #549 §11a) states the constraint the encoding
must satisfy, and states it as one thing:

> whether a value's bytes may depend on how the object was *constructed* rather
> than on what it is. **They may not** … two equal values must encode
> identically, or the same page lands on opposite sides of the limit depending
> on which implementation built it.

It is quoted because it is the sharpest statement of the constraint anyone has
written, not because it binds; nothing below rests on it being ratified. The
sentence names a property and then justifies it with a *different*, strictly
weaker one, and the gap matters enough to separate them:

- **Size-determinism.** Equal values have equal encoded *length*. This is what
  the limit needs, and it is the whole of what §11a's justification appeals to.
- **Byte-determinism.** Equal values have identical *bytes*. Strictly stronger.

The two come apart on real cases in this tree. Reordering an object's members
changes bytes and not length, so it violates byte-determinism alone. Emitting
`-0.0` where a value compares equal to `0.0` violates both — four bytes against
three — though §4a concludes those are two values rather than one.
A specification that only demanded size-determinism would leave the first case
open, and the first case is the one that makes a *test* impossible: a normative
vector is a byte string, so nothing can be pinned by vector unless bytes are
determined.

**This ADR ratifies byte-determinism, and the choice of instrument is what
forces it.** Vectors are how §1 answers the unspiked-seam objection, and a vector
is a byte string, so vectors require the stronger property. Size-determinism then
comes along for free, and nothing is lost by taking the stronger one.

### The corpus already has a canonical JSON form, and ADR-0084 §3 already asked for it

The encoding does not have to be invented. `core/types.py:339-353` carries
`_canonical_bytes`, ADR-0021 §1's pinned digest form, and it has been the one
encoding every digest in the memory graph hashes since ADR-0021:

```python
text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
return text.encode("utf-8")
```

Its docstring states the purpose in the words this ADR needs — "the one encoding
every digest in this module hashes, so two digests over the same facts cannot
disagree because they were spelled differently" — and its callers
(`MemoryUpdateProposal`'s fingerprint at `:917`, the decision digest at `:941`)
are the corpus's existing dependants on byte-determinism.

ADR-0084 §3 closes its own codec subsection by asking for exactly this reuse:

> Choosing an existing encoding rather than specifying a new one is the whole
> point of this subsection: binding to the encoding the stores already depend on
> is what makes #421's integer-encodability question **one** question rather
> than two.

Taking `_canonical_bytes`' form as the wire's is therefore not a convenience —
it is the instruction, followed. What the wire adds is a step in front of it:
`json.dumps` cannot render a `datetime`, a `timedelta` or a `StrEnum`, so a
pydantic JSON-mode projection runs first and produces the scalars' spellings.
§2 states the two halves; §3 states where the second half's defaults have to be
corrected, and there are exactly three places.

## Decision

### 1. The encoding is pinned by properties *and* normative vectors, not by naming a serialiser

**The specification has two parts and both are normative:**

- **Properties** (§2) — rules over the value space, which is what makes the
  specification *total* rather than a list of remembered cases;
- **Vectors** (§5) — byte strings a conforming encoder must reproduce exactly,
  which is what makes it *falsifiable* by a test rather than by whoever reads it
  next.

**The rejected alternative is naming a serialiser and its settings**, and it is
rejected as an *incumbent* rather than as a hypothetical: it is what ADR-0084 §3
decided, and this ADR replaces it (§10). The tempting form is short, is what an
implementation would reach for anyway, and cannot be got wrong by transcription.
It is rejected for three reasons, in the order they bind:

- **A dependency's defaults are not a thing that can be frozen, and ADR-0084 §3
  freezes this codec** — the same subsection that names pydantic also says "the
  length prefix, the UTF-8 JSON codec, and the connect frame's version member
  keep their representation in every protocol version, permanently". The two
  sentences cannot both hold: a permanent representational commitment defined as
  "whatever this library emits" is a commitment whose content is a third party's
  changelog. `pydantic-core`'s float formatter, its duration spelling and its
  `ser_json_inf_nan` default are all configuration surface, and each of them
  moves the limit's boundary, which is contract-visible behaviour nobody
  ratified. A vector fails at the upgrade, in CI, which is where a change of
  contract should surface.
- **The library's defaults are wrong in three places** (§3), so "name the
  serialiser" does not even describe the intended encoding — a `-0.0` it gets
  right, but a `null` for infinity and a `P1Y` for a year it does not. The
  description would have to be "the serialiser, except here, here and here", at
  which point the properties are being written anyway, with the vectors'
  checkability thrown away.
- **Naming a serialiser does not achieve determinism at all**, which is the
  reason that outranks both of the above and the one that makes this a
  replacement rather than a refinement: pydantic's JSON mode emits a
  `FrozenJsonMapping` in caller-insertion order, so two equal values get two byte
  strings (§4). A rule that names a serialiser inherits whatever
  non-determinism the serialiser has, and cannot see it.
- **Two implementations that satisfy the vectors are byte-identical without
  sharing code.** This is the payoff, and §7 turns on it: the in-process engine
  must enforce the same limit (ADR-0084 §4) while `orchestration` importing
  `wire` concretely is a golden rule 1 question. Under a specification defined by
  *output*, an engine-side encoder and a wire-side encoder that both pass the
  vectors cannot disagree, so the question is answerable either way rather than
  being forced.

**Properties alone would not do, and one measured case settles it.** "The
shortest decimal that round-trips" is the obvious property for numbers, and two
correct implementations of it disagree on this tree today:

| Value | CPython `json.dumps` | `pydantic-core` 2.46.4 |
| --- | --- | --- |
| `1e-7` | `1e-07` | `1e-7` |
| `1e-5` | `1e-05` | `0.00001` |

Both are shortest-round-tripping. They differ in exponent-digit padding and in
where the exponent threshold sits, and `Belief.confidence` is a `float` in
`[0.0, 1.0]` that a model or a heuristic can easily hand a value of `1e-7`. A
property that admits both spellings is not one encoding. The vector is what
closes it.

**The vector list is not exhaustive of the value space, and this ADR says so
rather than pretending otherwise** — that is exactly the objection Context raises
against a hand-written grammar, and it is answered by *not relying on the
enumeration for coverage*. The properties are total; the vectors are anchors on the corners
where two reasonable encoders were measured to differ, plus one per rule so each
rule has a witness. §8 states what follows: adding a vector for a case no
existing vector covers, consistent with §2, is an addition and not a change.

### 2. The encoding, as five properties

**Its subject is the payload, and only the payload.** ADR-0084 §4 puts the size
limit on the value a call passes or returns, so the payload is what has to have
determined bytes. This is where §2 **replaces** ADR-0084 §3's rule that a payload
"is serialised through pydantic's JSON mode" (§10 carries the record), and the
scoping is what keeps the replacement as narrow as it can be.

**More precisely: the payload of a `request`, `result` or `error` frame** — the
values the promoted methods pass and return. **The connect exchange is excluded**,
and that is a decision rather than an oversight: it is not a method call, its body
is the handshake ADR-0084 §2 and §3 own, and §3 freezes its representation
permanently so that a version mismatch can be *reported* rather than dropped. §8
gives the reasoning; nothing in §2 spells or orders a connect frame's members.

**The envelope is not touched either.** §3 decides the envelope's own
representation, including that its "member order is therefore not significant and
no ordering rule is needed", and nothing here changes that: an implementation
that emits envelope members in any order conforms to both ADRs, and one that
happens to sort the whole frame in a single pass conforms too, because "not
significant" permits both. What this ADR determines is the bytes of a call's
payload; it does not determine the bytes of the frame, and it does not need to.

> **The canonical wire encoding of a payload is ADR-0021 §1's canonical JSON form
> applied to that value's pydantic JSON-mode projection**, subject to the three
> corrections in §3. Concretely, and normatively:
>
> ```python
> json.dumps(
>     projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
> ).encode("utf-8")
> ```
>
> where `projection` is the value rendered into plain JSON types —
> `model_dump(mode="json")` for a promoted model, and the per-type spellings of
> §2c for a scalar.

The five properties below are the specification. The code above is how it is
obtained today, not what is ratified; an encoder that produces the same bytes by
other means conforms, and §7 says so.

#### 2a. Structure

- **No insignificant whitespace anywhere.** The separators are exactly `,` and
  `:` — one byte each, nothing around them. The empty object is `{}` and the
  empty array is `[]`.
- **Every JSON object *within the payload* has its members in ascending order of
  their names' Unicode code points.** UTF-8 byte order and code-point order
  agree, so the rule is unambiguous however it is implemented. It is
  case-sensitive and not locale-sensitive: `"Z"` (U+005A) precedes `"body"`
  (U+0062). The envelope is not a payload object and is not reached by this rule
  (above).
- **Array order is the value's own order** and is never sorted. A `tuple` field
  is ordered data; an object's member names are not.
- **The encoding is context-free.** A value's bytes are identical standalone and
  nested inside a larger structure. This is what makes measure-then-send sound,
  and the claim is exactly that and no more: **the bytes a sender measures are
  the bytes it transmits**, so measurement and transmission cannot disagree and a
  payload does not grow on its way into the envelope.

  **It does not follow that an admitted payload fits the frame**, and this ADR
  does not say so. Payload plus envelope exceeds the payload, so a payload
  admitted at exactly the frame ceiling overruns the frame by the envelope's own
  bytes. Closing that takes a **reserve** between the contract limit and
  ADR-0084 §3's prefix cap — a number, and **not this ADR's**: §7 leaves the
  limit and the envelope's member names where ADR-0084 §4 and §6 put them. What
  context-freedom guarantees is that whatever reserve is ratified is *sufficient*,
  because the payload's contribution to the frame is the number that was
  measured; without it, no reserve could be computed at all.

**Sorting rather than preserving declaration order is a decision, not an
inherited default, and the reason is a refactor nobody would flag.** A promoted
model's field order is deterministic, so declaration order would satisfy
byte-determinism too. But under it, reordering two fields in `core/types.py` —
an edit no reviewer would call a protocol change — silently changes every frame
carrying that type, and moves the boundary of a contract limit. Sorting makes
field order a private matter of the class again. It also costs nothing to state,
matches `_canonical_bytes` exactly, and is **length-preserving** — reordering an
object's members changes no byte count — so *this* rule moves no limit, no
reserve and no ceiling. (§2e's duration form does move one, by up to three bytes;
the header says so and §7 names who owns the affected figures.)

#### 2b. Strings

- **UTF-8, unescaped wherever JSON permits it.** `ensure_ascii=False`: a
  non-ASCII character is its own UTF-8 bytes, never a `\u` escape. `é` is
  `C3 A9`, not `é`.
- **`/` is not escaped.** `\/` is legal JSON and is not emitted.
- **The two-character escapes are used where they exist** — `\"`, `\\`, `\b`,
  `\f`, `\n`, `\r`, `\t` — and every other character below U+0020 takes the
  lowercase four-hex-digit form `\u00XX`.
- **Nothing at or above U+007F is escaped.** U+007F (DEL) is emitted raw; so are
  U+2028 and U+2029, which are valid in JSON strings and are only a hazard for a
  consumer that evaluates JSON as JavaScript source, which nothing here does.
- **A string with no UTF-8 encoding has no wire form and the encoder raises.** A
  lone surrogate is refused rather than substituted with U+FFFD or escaped
  through. §9 records what that leaves open.

#### 2c. Scalars

| Type | Form |
| --- | --- |
| `bool` | `true` / `false` |
| `None` | `null` |
| `int` | decimal, no sign for zero, no exponent, no width bound of this ADR's (below) |
| `float` | the grammar below — **not** "whatever `repr` does" |
| `str` / `Identifier` | §2b, on the *validated* value: `Identifier` strips, so `" x "` and `"x"` are one value and one encoding |
| `StrEnum` | the member's `value` as a string — `Disposition.EXECUTED` is `"executed"` |
| `UtcInstant` | §2d |
| `timedelta` | §2e |
| `FrozenJsonMapping` / `FrozenJsonValue` | its thawed JSON value, encoded by these same rules — so a nested mapping's keys sort too |

**The float grammar, stated without naming an implementation.** An earlier draft
of this rule said "CPython's `float.__repr__`", which is the objection §1 raises
against naming pydantic, turned on this ADR's own text: a `repr` is an
implementation's behaviour, `pyproject.toml` admits any Python `>=3.14`, and
ADR-0084 §3 freezes this representation permanently. Two conforming interpreters
could then write one value two ways.

> Let the value be finite. Among all strings of decimal digits that round-trip to
> it, take the **shortest**; where several of that length round-trip, take the one
> whose exact decimal value is **nearest** the binary value, and if two are exactly
> equidistant the one whose **last digit is even**. Call it **D**, with no leading
> and no trailing zero, and let **decpt** be the integer with
> `value = ±0.D × 10^decpt`.
>
> - **Fixed-point when `-4 < decpt ≤ 16`**, with at least one digit on each side
>   of the point: `0.0001`, `0.1`, `1.0`, `1000000000000000.0`.
> - **Exponential otherwise**: the first digit, then a point and the remaining
>   digits *only if there are any*, then `e`, the exponent's sign, and
>   `decpt − 1` in **at least two digits**: `1e-05`, `1e+16`, `1.5e+300`.
> - **Zero is `0.0`**, and negative zero is `-0.0` (§4a).
> - A negative value is a leading `-` followed by the encoding of its magnitude.

**The tie-break is not decoration, and an earlier draft asserted uniqueness
instead.** Shortest-round-tripping does not single out a string:
`-1.5670905694168155e-99` and `-1.5670905694168156e-99` are both seventeen
digits and both parse to `-0x1.b6bc406aad682p-329`, the same double. Nearest
separates them — the `…156` candidate is about 2.6e-116 from the exact value and
the `…155` candidate about 7.4e-116 — and it is what CPython picks. The
even-last-digit rule beneath it may well be unreachable, since equidistance would
need the binary value to sit exactly on a midpoint of the decimal grid; it is
stated anyway, because a grammar with a gap is not total and this one claims to
be.

**Verified rather than asserted**: this grammar reproduces CPython 3.14.6's
`repr` on every case in §5b, on both notation thresholds, on the subnormal
extremes, and on **350,000 pseudo-random doubles** drawn from raw 64-bit
patterns, with no mismatch. So an implementation may call `repr` today and
conform; what is *ratified* is the grammar, and §5b's vectors are what would
catch an interpreter that stopped agreeing with it.

**A non-finite float has no encoding and the encoder raises.** Neither of the two
things a library does by default is acceptable: `json.dumps` emits the non-JSON
tokens `NaN` and `Infinity`, and pydantic emits `null`, which turns a value into
a different value silently. `core/types.py`'s `_deep_freeze` already makes this
exact observation about `json.dumps` for `FrozenJson`, and this generalises it to
every float on the surface.

**The integer domain is deliberately *not* fixed here, and the reason is that
ADR-0084 has already ruled on it.** CPython's `sys.int_max_str_digits` is
process-global and mutable, so whether a >4300-digit integer renders is an
ambient property rather than a value's — a real portability hazard, and it is
**#421's**, not a gap this ADR opens. ADR-0084 answers it in as many words:
adopting "a fixed application-owned bound across all four paths … *reverses a
ratified design decision*" and "*needs its own ADR*", which "is not a local-API
decision"; what ADR-0084 adds instead is a deployment constraint — the reference
deployment does not set `PYTHONINTMAXSTRDIGITS`, so both halves inherit one
interpreter default. **Pinning a digit bound here would be exactly the ADR that
ruling says is owed**, written in an ADR about byte spellings and reversing a
decision ADR-0014 made. So this ADR states the integer's *form* and leaves its
*domain* where ADR-0084 left it. An earlier draft of §2c said otherwise and was
wrong to.

#### 2d. Instants

> **`YYYY-MM-DDTHH:MM:SS[.ffffff]Z`.** The UTC designator is `Z`, never
> `+00:00`. The fractional part is **absent when the microsecond field is zero**
> and otherwise **exactly six digits, trailing zeros kept**.

`UtcInstant`'s validator has already converted any offset to UTC before the
encoder sees it (`core/types.py:230-241`), so an instant constructed at
`-05:00` and the same instant constructed at UTC are one value and one byte
string. That is the encoding inheriting a property the type already enforces
rather than establishing one.

**Six digits with trailing zeros is the library's behaviour and it is ratified
rather than trimmed**, deliberately and against the symmetry with §2e. Trimming
would make `.100000Z` into `.1Z` and save five bytes on a field that appears
several times per belief; it would also make the fractional part's *width*
depend on the value, which is a second thing to get right for no benefit a
16 MiB budget can notice. Fixed width is the cheaper rule to state, to test and
to reason about at the boundary.

#### 2e. Durations

> **`[-]P[nD][T[nH][nM][n[.ffffff]S]]`** — a sign only when negative, and only
> the four components `D`, `H`, `M` (minutes) and `S`. A zero component is
> omitted; the zero duration is `PT0S`. The seconds' fractional part is present
> only when non-zero, with **trailing zeros trimmed** (`PT0.5S`, not
> `PT0.500000S`).
>
> **No nominal component is ever emitted.** `Y` and date-position `M` are
> forbidden outright.

**`"P2DT3S"` versus `"PT172803S"` is not a choice, and finding that out is what
this rule is really about.** `timedelta` normalises on construction:
`timedelta(seconds=172803)` and `timedelta(days=2, seconds=3)` are the same
object state, `==`, with the same `.days`/`.seconds`/`.microseconds`. So the two
spellings are not two encodings of one value — they are one encoding, and the
question is answered by the type rather than by a decision. It is worth recording
that it *was* asked, and by review rather than by inspection: it reads like a
live fork and is not one.
The same disposes of `timedelta(hours=24)` versus `timedelta(days=1)`. Nothing
here is at risk of construction-dependence, and the rule above simply picks the
component decomposition, which is forced once `Y` is refused.

**The nominal-component refusal is the one place this ADR overrides the library
outright, and it is the one that matters.** pydantic emits a year component
above 364 days: `timedelta(days=365)` is `"P1Y"` and `timedelta.max` is
`"P2739726Y9DT23H59M59.999999S"`. It round-trips, because both halves privately
agree that a year is 365 days. But ISO-8601's `Y` is a *nominal* component — it
does not denote a fixed elapsed time — so `"P1Y"` is a spelling the notation
cannot resolve to a `timedelta` without a convention the notation does not carry.
ADR-0084 §3 freezes this codec permanently, and a permanent freeze is the worst
possible place to embed a private convention that reads as a standard one. The
cheaper alternative — ratify `Y` and define it as exactly 365 days — was
considered and rejected for the same reason: it makes the convention public
without making it correct, and it leaves a decoder built to the standard unable
to conform.

**This is the one rule in §2 that moves a byte count, and the bound is *proved*
rather than sampled** — an earlier draft of this ADR sampled it, got two bytes,
and was wrong.

> **A duration's canonical form is at most three bytes longer than the library's,
> and never more.**

The proof is short enough to state. The time components are identical in both
spellings and cancel, as does the sign, so only the day part differs: the library
writes `P{y}Y[{r}D]` with `y = d // 365`, and §2e writes `P{d}D`. The growth is
therefore `len(str(d)) − len(str(y))` when `r` is zero, and strictly less when it
is not — a non-zero remainder only lengthens the library's form. Since
`d = 365y < 365 × 10^k` for any `y < 10^k`, `d` has at most **three** more digits
than `y`, so the growth is at most three. It is attained: `timedelta(days=1095)`
is `"P3Y"` (5 bytes) against `"P1095D"` (8), and so is
`timedelta(days=360991935)` — `"P989019Y"` (10) against `"P360991935D"` (13).

Most durations move less or not at all: `"P1Y"` → `"P365D"` is +2, `"P2Y270D"` →
`"P1000D"` is −1, `"P10Y350D"` → `"P4000D"` is −2, `timedelta.max` is unchanged
at 30 bytes, and nothing under 365 days moves. The consequence is stated rather
than left to be discovered: **a reserve or floor derived from a worst-case
payload width must be derived from §2's forms**, not from what the library emits,
and whoever sets those numbers (§7) owns that.

**The cost is one serialiser function in the wire lane**, and it is bounded: for
every duration under 365 days the library already produces the ratified form, so
the deviation is confined to a corner. That corner is not left to be discovered —
§5 pins `P365D` and `timedelta.max` as vectors, which is the whole reason the
vectors and the properties are both normative.

### 3. Where the library and this ADR disagree, listed exhaustively

**This table is also the exact extent of what ADR-0084 §3's payload clause loses**
— it named pydantic's JSON mode, so every row below is a place a reader following
that clause emits bytes this ADR forbids. §10 is the record; this is its scope,
stated as three rows rather than as prose so it can be checked.

Three cases, each measured rather than assumed. Everywhere else,
`model_dump(mode="json")` fed through `_canonical_bytes`' form already produces
the ratified bytes — which is why §2 keeps §3's *shape*, binding to an encoding
that already exists, and changes only the instrument.

**Three APIs are in play and the table names each**, because they differ exactly
where it matters: `model_dump_json()` is the one-shot serialiser ADR-0084 §3's
"pydantic's JSON mode" most naturally means; `model_dump(mode="json")` is the
*projection* §2's recipe uses, which renders scalars but leaves Python containers
and floats alone; and `json.dumps` is what §2 then runs over that projection.

| # | Case | `model_dump_json()` | `model_dump(mode="json")` → `json.dumps` default | Ratified | Why |
| --- | --- | --- | --- | --- | --- |
| 1 | member order | declaration / insertion order | same | code-point sorted | §2a — a field reorder must not be a protocol change; a `FrozenJsonMapping`'s key order must not be caller-visible (§4) |
| 2 | duration ≥ 365 days | `"P1Y"` | `"P1Y"` — the projection renders it | `"P365D"` | §2e — a nominal component on a permanently frozen codec |
| 3 | non-finite float | `null` — **silently a different value** | the projection keeps `inf`, and `json.dumps` writes the non-JSON token `Infinity` | raise | §2c — one is silent corruption, the other is not JSON |

**Row 3 is why `allow_nan=False` is in §2's recipe rather than decorative.** The
projection does *not* convert a non-finite float — `model_dump(mode="json")` on
`inf` yields the Python `inf`, not `null` — so without the flag `json.dumps`
would emit `Infinity` and produce something that is not JSON at all. With it, the
recipe raises, which is what §2c ratifies. The `null` in the first column is
`model_dump_json()`'s behaviour, and it is the one ADR-0084 §3's rule delivers,
which is why the supersession record names that clause and not this recipe.

**Negative zero is not a fourth row, and an earlier draft of this ADR got that
wrong in an instructive way.** `-0.0 == 0.0` is true and the two encode
differently — `-0.0` at four bytes, `0.0` at three — which looks like the value
space disagreeing with itself, and the draft "fixed" it by normalising the sign
away. That was a mistake, and §4a says why: `-0.0` is the *faithful* spelling of
the value handed to the encoder, the sign is observable
(`math.copysign(1.0, x)`), and it survives into a promoted `FrozenJsonMapping`
where no schema constrains it. Normalising made the wire lose a bit the
in-process engine keeps, which is ADR-0084 §4's divergence rather than a
canonicalisation. **The library is right here and this ADR ratifies it
unchanged.**

### 4. Byte-determinism, over the equivalence that keeps one datum one type

> **For any two payload values `a` and `b`, if `a` and `b` are the *same value*
> then `encode(a) == encode(b)`.** A value's bytes depend on what it is, never on
> how it was constructed.
>
> **"The same value" is *indistinguishability*, applied recursively**: scalars of
> the same Python type that no operation on that type can tell apart — for a
> `float`, equal **and** of the same sign, so `-0.0` and `0.0` are two values;
> sequences of the same length, pairwise the same; mappings with the same key
> set, pairwise the same. It is deliberately **not** Python's `==`.
>
> **The encoding therefore normalises nothing**: it never maps two values that
> this relation distinguishes, **and that can occupy the same position**, onto one
> spelling. The qualifier is load-bearing and §4b explains it.

#### 4a. Why `==` is the wrong relation, in two measured cases that answer alike

Python's `==` identifies values the encoding must keep apart, and it does so in
two independent ways. Both are measured on a promoted `FrozenJsonMapping` field —
`Confirmation.parameters`, which ADR-0084 §4 names among the types that promote —
and that holder is where they bite, because it is untyped by construction so no
schema constrains what enters it.

**Across scalar types:**

| `parameters` | Encoded | Python `==` to `{"x": 1}`? |
| --- | --- | --- |
| `{"x": 1}` | `{"x":1}` | — |
| `{"x": True}` | `{"x":true}` | **yes** (`1 == True`) |
| `{"x": 1.0}` | `{"x":1.0}` | **yes** |

**Within one scalar type**, on the sign of zero:

| `parameters` | Encoded | Python `==` to `{"x": 0.0}`? | `math.copysign(1.0, x)` |
| --- | --- | --- | --- |
| `{"x": 0.0}` | `{"x":0.0}` | — | `1.0` |
| `{"x": -0.0}` | `{"x":-0.0}` | **yes** | `-1.0` |

**Both cases have the same answer, and it is not to normalise.** `1`, `true`,
`1.0`, `0.0` and `-0.0` are five distinct JSON texts, each of which decodes back
to the Python object it came from; collapsing any of them would destroy
information rather than canonicalise it. Signed zero makes the point sharpest: a
`Confirmation` is a tool's parameters rendered for the user's consent, the sign of
a zero is observable with one call to `math.copysign`, and `_deep_freeze`
preserves it — so an implementation that normalised it would hand a wire client
different data from the one the in-process engine returns, which is precisely
ADR-0084 §4's divergence, committed in the name of preventing it.

So `==` is not a defect the encoding must work around — **it is the wrong
equivalence relation for this property.** An earlier draft of this ADR stated the
rule over `==` and then patched the consequences by normalising signed zero;
both halves of that are withdrawn, and the relation above replaces them.

**The right one is the equivalence under which one datum keeps one type from end
to end**, and the three JSON scalar types are exactly where Python's `==` loses
it. Measured: `{"x": 1}`, `{"x": True}` and `{"x": 1.0}` encode to three byte
strings, and decoding each recovers `int`, `bool` and `float` respectively.

**That recovery is worth being precise about, because it holds for a different
reason in the two halves of a payload, and a general injectivity claim would be
false.** The encoding is *not* injective over all values: `timedelta(seconds=30)`
and the string `"PT30S"` both encode to `"PT30S"`, as do a `UtcInstant` and its
formatted string, and a `StrEnum` member and its value. So JSON alone cannot say
which type produced a string, and this ADR does not claim it can.

- **Where a field is typed — every promoted field but one — decoding is
  schema-directed**, which is what a ratified type surface is *for*: the
  annotation says the member is a `timedelta`, so `"PT30S"` is parsed as one.
  Ambiguity in the JSON is not a problem because the JSON is never read without
  the schema.
- **Where there is no schema — inside `FrozenJson`, the one deliberately untyped
  holder — the JSON form itself carries the type**, because `FrozenJson`'s six
  arms (`str | int | float | bool | None | Sequence | Mapping`) map onto six
  distinct JSON productions. `1`, `true` and `1.0` are three of them. **§2c's
  rule that a `float` always carries a decimal point or an exponent is
  load-bearing here and not cosmetic**: without it `2.0` would encode as `2` and
  come back an `int`.

So type-aware equality is recoverable exactly where nothing else could recover
it, and elsewhere the schema does the work. **The one shape that would reopen
this** is a promoted field annotated as a union of `str` with a string-encoded
scalar — `str | timedelta`, say — where the schema would not disambiguate
either. No promoted field is; the constraint is recorded here rather than assumed,
because it is a property of the *surface* and this ADR does not choose it.

**And the hazard the rule exists for does not reach these cases.** The concern is
one *datum* acquiring two spellings depending on which implementation built the
object. A tool parameter that is the integer `1` is carried as `int` by
`_deep_freeze`, which preserves the type, and comes back as `int` through the
wire; nothing in the pipeline turns it into `True`. Two implementations handed
the same datum produce the same bytes. What Python `==` was reporting was two
*different* data that happen to compare equal, which is a fact about `==` and not
about the encoding.

#### 4b. What "normalises nothing" does *not* claim

**It does not claim that bytes determine a value.** §2c spells a `StrEnum` as its
member value and a `timedelta` as an ISO-8601 string, so `Disposition.EXECUTED`
and the string `"executed"` share a spelling, as do `timedelta(seconds=30)` and
`"PT30S"`. A rule saying "values that differ observably always differ in bytes"
would be false, and an earlier draft of §4 said exactly that.

**They are not counterexamples, because the colliding values cannot occupy the
same position**, and that is what makes the qualified rule both true and
sufficient:

- **A schema-typed field admits one type.** A field declared `Disposition` never
  holds a bare `str`; a field declared `timedelta` never holds one either — hand
  it `"PT30S"` and validation *makes* it a `timedelta`, so there is one value at
  that position, not two.
- **`FrozenJson` — the one position that admits an arbitrary value — has six arms
  and neither of the colliding types is among them.** `str | int | float | bool |
  None | Sequence | Mapping` admits no `timedelta`: measured, a `timedelta` is
  **refused** by the validator. A `StrEnum` *is* a `str` subclass, so it is
  admitted — and validation coerces it to `str`, so what the encoder sees is the
  string, and again there is one value at that position rather than two.

So within any position the encoding is injective on §4's relation, which is
exactly what §4a's schema-directed decoding needs and no more than this ADR can
honestly claim.

**Why it arises only here.** Every other field on the promoted surface has a
declared type, so validation fixes the Python type before the encoder sees the
value — an `int` handed to a `float` field is a `float` afterwards — §4(ii).
`FrozenJson` is the one holder that is deliberately untyped, being a JSON value
of any shape, and it is therefore the only place two Python types can occupy one
field. The rule is stated over the general equivalence anyway, because a later
untyped holder would otherwise reopen the question.

This is the constraint Context states, taken at its stronger reading. Three
concrete violations exist in the tree today; each is closed by a rule already
stated, and the point of listing them is that a conformance test can be written
directly from the list.

**(i) `FrozenJsonMapping` key order — the one that reaches a promoted DTO.**
`FrozenDict.__eq__` compares as a `dict` and `__hash__` uses a `frozenset`
(`core/types.py:1846-1852`), so key order is invisible to equality and to
hashing; but `__iter__` yields insertion order and `_thaw_json` rebuilds a `dict`
in that order, so the encoder sees it. Measured:

```text
Confirmation(parameters={"to": …, "body": …, "Z": 1})   model_dump_json → {"to":…,"body":…,"Z":1}
Confirmation(parameters={"Z": 1, "body": …, "to": …})   model_dump_json → {"Z":1,"body":…,"to":…}
                                                        equal? True    identical bytes? False
```

**This reaches the promoted surface three times over, and the count does not
depend on which field list the surface ADR settles on.** ADR-0084 §4 names
`Confirmation` among the types that promote, and `Confirmation.parameters` is a
`FrozenJsonMapping` today (`engine.py`); §4 also names `TurnOutcome`, whose
`turn` reaches `ActionPlan → PlanStep.parameters` and `ExecutionState`'s step
outputs, both `FrozenJson` holders in `core/types.py`. §2a's sort closes all
three at once, and would close any further holder the transitive closure turns
out to reach, because the rule is over the type and not over an enumerated field.

**(ii) Anything the type already normalises is *not* a violation, and saying so
bounds the list.** `Identifier` strips on validation, `UtcInstant` converts to
UTC on validation, `timedelta` normalises on construction, and pydantic coerces
an `int` handed to a `float` field to `1.0`. In each case two "differently
constructed" values are one value by the time the encoder runs, so the encoder
has nothing to do.

**And the list is one item long rather than three, which is the point.** Once the
equivalence is indistinguishability (§4a) rather than `==`, the scalar cases stop
being violations to repair and become *values to spell faithfully*, which §2c
already does. What is left is the genuine one: **a construction difference
survives validation only where the type's own `__eq__` ignores something the
encoder can see** — and in this tree that is exactly one thing, `FrozenDict`
comparing as a `dict` while iterating in insertion order. §2a closes it. A
reviewer checking this section's completeness has one predicate to apply rather
than an enumeration to trust.

### 5. The normative vectors

**Every byte string below is normative.** A conforming encoder reproduces it
exactly. They were generated by running §2's encoding on `pydantic 2.13.4` /
`pydantic-core 2.46.4` / CPython 3.14.6; the rows the library does not produce
are marked, and are exactly the three §3 corrects.

**Every vector carries its own input**, so each is checkable against this
document alone. §5a–§5d are over Python and JSON types and depend on no field
list at all; §5e's composite vectors state the field set they were built over
inline, so that a vector remains verifiable whatever the surface ADR settles —
and so that a reader can see immediately which rules a composite vector
witnesses that the scalar vectors do not.

Byte counts are given because the limit is measured in bytes and a vector whose
length a reader has to count is a vector nobody checks.

#### 5a. Strings

Inputs are given by code point where the character is not printable.

| Input | Encoded | Bytes |
| --- | --- | --- |
| `a/b` | `"a/b"` | 5 |
| `a\b` (U+005C) | `"a\\b"` | 6 |
| `say "hi"` | `"say \"hi\""` | 12 |
| `a` U+0009 `b` U+000A `c` | `"a\tb\nc"` | 9 |
| U+000D U+0008 U+000C | `"\r\b\f"` | 8 |
| U+0000 U+001F | `"\u0000\u001f"` | 14 |
| U+007F (DEL) | quote, `7F`, quote — raw, unescaped | 3 |
| `café` | `"café"` (`é` = `C3 A9`) | 7 |
| `日本語` | `"日本語"` | 11 |
| U+1F600 | `"😀"` (`F0 9F 98 80`) | 6 |
| U+2028 | quote, `E2 80 A8`, quote — raw | 5 |
| empty | `""` | 2 |
| a lone surrogate (U+D800) | **no encoding — the encoder raises** | — |

The U+0000/U+001F row fixes the escape *case*: `\u001f`, lowercase hex. The
U+007F and U+2028 rows fix that the escaping stops at U+0020 and does not resume.

#### 5b. Numbers

| Input | Encoded | Bytes |
| --- | --- | --- |
| `0.0` | `0.0` | 3 |
| `-0.0` | `-0.0` — **not normalised, §4a** | 4 |
| `1.0` | `1.0` | 3 |
| `0.1` | `0.1` | 3 |
| `0.1 + 0.2` | `0.30000000000000004` | 19 |
| `1e-4` | `0.0001` | 6 |
| `1e-5` | `1e-05` | 5 |
| `1e-7` | `1e-07` | 5 |
| `1e15` | `1000000000000000.0` | 18 |
| `1e16` | `1e+16` | 5 |
| `0` (`int`) | `0` | 1 |
| `2**63` | `9223372036854775808` | 19 |
| `-1.5670905694168156e-99` | `-1.5670905694168156e-99` — **the tie-break witness**: `…155` is equally short and round-trips too, and is not chosen | 23 |
| `inf`, `nan` | **no encoding — the encoder raises** | — |

**The five `==`-equal values that must stay apart**, taken inside a
`FrozenJsonMapping` because that is the promoted holder where all of them are
reachable and unconstrained by any schema (§4a). These are the witness that §4's
equivalence is indistinguishability and not `==`, and that the encoding
normalises nothing:

| `parameters` | Encoded | Bytes | decodes back as |
| --- | --- | --- | --- |
| `{"x": 1}` (`int`) | `{"x":1}` | 7 | `int` |
| `{"x": True}` (`bool`) | `{"x":true}` | 10 | `bool` |
| `{"x": 1.0}` (`float`) | `{"x":1.0}` | 9 | `float` |
| `{"x": 0.0}` | `{"x":0.0}` | 9 | `float`, `copysign` `+1.0` |
| `{"x": -0.0}` | `{"x":-0.0}` | 10 | `float`, `copysign` `-1.0` |

The last two are the nested-holder witness that signed zero survives to the wire
and back: `-0.0` enters a promoted `FrozenJsonMapping` with nothing to constrain
it, `_deep_freeze` preserves it, and it returns with its sign — so a wire client
and the in-process engine hand a caller the same value.

The `1e-4`/`1e-5` and `1e15`/`1e16` pairs are the two thresholds where the
exponent form begins, and the `1e-05`/`1e-07` rows fix the two-digit exponent
padding. These four are the vectors `pydantic-core`'s own formatter does not
satisfy (`0.00001`, `1e-7`), which is §1's worked example of why "shortest
round-tripping decimal" is not a specification.

#### 5c. Instants

Shown as the encoding of `{"d": <instant>}` so the member framing is visible.

| Input | Encoded | Bytes |
| --- | --- | --- |
| `2026-08-01 12:00:00+00:00` | `{"d":"2026-08-01T12:00:00Z"}` | 28 |
| the same instant given as `2026-08-01 07:00:00-05:00` | `{"d":"2026-08-01T12:00:00Z"}` | 28 |
| `…12:00:00.123456+00:00` | `{"d":"2026-08-01T12:00:00.123456Z"}` | 35 |
| `…12:00:00.100000+00:00` | `{"d":"2026-08-01T12:00:00.100000Z"}` | 35 |
| `…12:00:00.000001+00:00` | `{"d":"2026-08-01T12:00:00.000001Z"}` | 35 |

Rows 1 and 2 are the §4(ii) witness: the type normalised, so the encoder did not
have to. Rows 3–5 fix six digits with trailing zeros kept.

#### 5d. Durations

| Input | Encoded | Bytes |
| --- | --- | --- |
| `timedelta(0)` | `"PT0S"` | 6 |
| `timedelta(seconds=30)` | `"PT30S"` | 7 |
| `timedelta(days=2, seconds=3)` | `"P2DT3S"` | 8 |
| `timedelta(seconds=172803)` — the same value | `"P2DT3S"` | 8 |
| `timedelta(hours=24)` | `"P1D"` | 5 |
| `timedelta(minutes=90)` | `"PT1H30M"` | 9 |
| `timedelta(microseconds=500000)` | `"PT0.5S"` | 8 |
| `timedelta(microseconds=1)` | `"PT0.000001S"` | 13 |
| `timedelta(seconds=-30)` | `"-PT30S"` | 8 |
| `timedelta(days=365)` | `"P365D"` — **library emits `"P1Y"`, §3 row 2** | 7 |
| `timedelta(days=1095)` | `"P1095D"` — **library emits `"P3Y"`; the +3 worst case, §2e** | 8 |
| `timedelta(days=360991935)` | `"P360991935D"` — **library emits `"P989019Y"`; +3 again** | 13 |
| `timedelta.max` | `"P999999999DT23H59M59.999999S"` — **library emits `"P2739726Y9DT23H59M59.999999S"`** | 30 |

Rows 3 and 4 are §2e's point made as a vector: two spellings of one value, one
encoding, no decision needed. The last four rows are the nominal-component
correction, and they are why it cannot go unnoticed by an implementation that
reaches for `model_dump_json()`. Two of them pin §2e's proved **+3** worst case
at both ends of its range, so a reserve computed against them is computed
against the widest a duration gets.

#### 5e. Composite payloads, and the entry point for values that are not models

ADR-0084 §3 states that "payload encoding follows what the value is" and notes
that "the façade does not return models everywhere" — a `forget` returns a bare
`bool`, an optional getter returns `null`, a listing returns an array. That
observation is sometimes read as needing a separate entry point per payload
class. It does not:

> **The payload is any JSON value, encoded by §2.** There is no wrapper object,
> no envelope inside the envelope, and no distinction in the encoding between a
> model and anything else — §2 is defined over values, and a model is one. The
> envelope's payload member holds whatever it is (ADR-0084 §3).

| Payload | Encoded | Bytes |
| --- | --- | --- |
| a method returning `True` | `true` | 4 |
| an optional getter returning `None` | `null` | 4 |
| an empty page | `[]` | 2 |

A **request argument object** is a JSON object whose members are the arguments
the caller passed, named as the method's parameters are (ADR-0084 §3: "a request
payload is a JSON object whose members are the call's arguments"). Under §2a its
member order is **sorted, not the caller's keyword order** — which matters more
than it looks, because `f(b=…, a=…)` and `f(a=…, b=…)` are the same call and a
naive encoder built on a kwargs `dict` gives them different bytes. That is
construction-dependence on the *request* path, structurally identical to §4(i)
and closed by the same rule.

The three below are vectors for the encoding of the argument object; the
parameter *names* and which arguments exist are the surface ADR's, and a vector
whose names change stays a correct witness of the rule it demonstrates.

| Arguments passed | Payload |
| --- | --- |
| `utterance="hi"`, `timeout=timedelta(seconds=30)` | `{"timeout":"PT30S","utterance":"hi"}` |
| `record_id="r-1"` | `{"record_id":"r-1"}` |
| `bands=[BeliefBand.STATED]`, `limit=50` | `{"bands":["stated"],"limit":50}` |

**A belief-shaped model**, exercising nested models, an optional inside a tuple,
an enum, an instant, a float and a `null` field together. Built over the fields
`id: Identifier`, `band: BeliefBand`, `kind: MemoryKind`, `content: str`,
`confidence: float`, `last_updated: UtcInstant`, `evidence: tuple[Evidence, ...]`
and `valid_until: UtcInstant | None`, with `Evidence` carrying
`content: str | None` — the shape `orchestration/engine.py` carries at `main` @
`89e0cfe`, for the type ADR-0084 §4 names as promoting:

```text
{"band":"stated","confidence":0.9,"content":"prefers dark mode","evidence":[{"content":"said so"},{"content":null}],"id":"b-1","kind":"preference","last_updated":"2026-08-01T12:00:00Z","valid_until":null}
```

204 bytes, for `id="b-1"`, `band=STATED`, `kind=PREFERENCE`,
`content="prefers dark mode"`, `confidence=0.9`,
`last_updated=2026-08-01T12:00:00Z`, `evidence=(Evidence("said so"), Evidence())`,
`valid_until=None`. A page of them is a JSON array of exactly these bytes, comma
separated, with no whitespace — §2a's context-freedom stated as a vector.

**A confirmation-shaped model**, exercising §4(i). Built over `tool_id`,
`tool_description`, `parameters: FrozenJsonMapping`, `reason` and
`token: ContinuationToken(handle)` — again the tree's shape at `89e0cfe`, for a
type ADR-0084 §4 names:

```text
{"parameters":{"Z":1,"body":"hi","to":"a@b"},"reason":"external","token":{"handle":"h-1"},"tool_description":"send","tool_id":"t-1"}
```

Constructed with `parameters` in the order `to, body, Z` and in the order
`Z, body, to`, the two values are `==` and encode to **these same bytes**;
`model_dump_json()` gives them two different byte strings. `"Z"` sorting before
`"body"` is the code-point rule of §2a showing it is not case-insensitive.

#### 5f. What the vectors are for

They are not documentation. Each one is a line of a conformance test the wire
lane writes: encode the input, compare to the byte string, compare the length.
Together they discriminate the encoding from every near-miss measured while
writing this ADR — `model_dump_json()`, `json.dumps` without `sort_keys`,
`ensure_ascii=True`, a trimmed fractional second, a `-0.0` normalised away, and a
duration with a year component. A test suite that passes all of §5 and none of
those is what "one canonical encoding" means operationally.

### 6. Where this ADR sits in ADR-0084 §5's sequence

> **ADR-0087 is a contract change of ADR-0084 §5's kind, and it lands before the
> triad.** §5's sequence becomes: (1) ADR-0084; (2) the surface ADR; **(2b) this
> ADR**; (3) the triad; (4) the hub, the `wire` package, the client and the
> `lint-imports` edits.

**Before the triad is the load-bearing claim, and it rests on ADR-0084 alone.**
§5's item 3 names what the triad contains — "`core/protocols.py`,
`core/types.py`, conformance suite, **canonical fake**". A canonical fake is a
second implementation of the Protocol, and the suite is a shared test both it and
the concrete `Engine` must pass. §4 then rules that the size limit is a clause of
the declared contract that "*every* implementation enforces", with "the
conformance suite (§5) … what holds them to it". Put those together and change 3
is the moment two implementations are held to a limit — and a limit is a byte
count. Without a ratified encoding the suite cannot assert where the line is, so
the clause §4 hands it is the one clause it must skip. Landing the encoding
before change 3 is what lets the suite test the clause instead of around it.

**The relative order of this ADR and the surface ADR is deliberately not fixed,
and nothing here depends on it.** Both are contract changes that must precede the
triad, and neither is a prerequisite of the other: this ADR takes its premises
from ADR-0084 and its inputs from the tree (§5), and the surface ADR needs from
this one only that the limit is measured on a ratified canonical encoding —
a sentence that is true the moment this ADR merges, in either order. The "b" in
2b records that this ADR belongs to §5's contract-ADR phase, **not** that it
follows 2a.

**What the encoding did have to wait for is the contract's shape, not its field
list.** §2's rules are over the scalar types the promoted surface reaches —
`str`, `float`, `int`, `bool`, `UtcInstant`, `timedelta`, `StrEnum`,
`FrozenJsonMapping` — and those are settled by ADR-0068's `core` graph and by the
tree, not by which fields are selected from it. That is why the vectors are
groundable today and would not have been groundable before ADR-0084 §4 decided
that the result types promote as frozen pydantic models at all.

**Numbering it 2b rather than renumbering is deliberate.** ADR-0084 §5's items 3
and 4 are referred to by number across the corpus — ADR-0084 §6 itself, and
#547's open discrepancy about which of them owns the `lint-imports` edits, both
cite "change 3" or "change 4", as does the surface ADR's draft in several places.
Renumbering would silently repoint every one of those citations, including one
that is currently the subject of a filed issue.

**The insertion honours ADR-0084 §5's argument rather than straining it, and
this is worth stating because the count it changes is the visible part.** §5's
reasoning is not "there are four things"; it is *contract before implementation*,
twice over. It splits steps 1 and 2 "because they answer different questions and
only one of them can be answered honestly today" — whether the trigger has fired
is decided by reading ADR-0042 against the deployment, what the surface is wants
contact with a real client. And it puts the triad after both because "the ADR is
ratified before anything implements against it" (golden rule 5, ADR-0015 §5). A
fifth **contract** change, ratified ahead of the triad, satisfies both halves: it
answers a third question of the same kind — *what are the bytes* — which wants
its own evidence and its own reviewer, and it lands before
the first thing that implements against it. What would strain §5's argument is
the opposite move: leaving the encoding to change 4, where an implementation lane
would be the unreviewed author of a contract-visible refusal boundary. That is
the shape golden rule 5 and ADR-0015 §5 exist to prevent, and ADR-0084 §4 names
it in as many words when it refuses to let a lane choose the DTO field layouts.

**So the four changes ADR-0084 §5 names keep their content and their relative
order**, and nothing about the triad's obligation, the promotion, or the
lifecycle ruling moves. What changes is a count, and §10 records exactly that
and no more.

**Naming an ADR that is in flight is normal in this corpus** — ADR-0084 §5
itself names "the surface ADR (#281's scope)" before that ADR existed. This ADR
names it the same way and depends on it for nothing. Its position in the sequence
is stated here and recorded on ADR-0084 (§10), so the corpus carries the ordering
whether or not any other ADR repeats it; §5e's composite vectors carry their own
inputs, so they stay verifiable if a field is later selected differently. **The
one thing the surface ADR needs from this one** is that the limit it declares is
measured on the canonical encoding ratified here — a sentence that becomes true
when this change merges, and that decides nothing about sequence, so stating it
costs that ADR no amendment record.

### 7. The boundary: what the `wire` package still owns

ADR-0084 §6 gives the `wire` package "the envelope, the framing, the codec, the
error mapping, and the client". This ADR takes one thing out of that list and
leaves the rest, and the line is drawn at a property rather than at a module:

> **This ADR fixes the byte string a value serialises to. It fixes nothing about
> the object that produces it.**

| This ADR | The `wire` package (ADR-0084 §5's change 4) |
| --- | --- |
| the bytes, for every promoted type and every payload class | the encoder and decoder themselves — their API, their module, their buffering |
| that measurement and transmission use the same bytes | how a limit check is actually computed, including any cheaper test that refuses exactly the same set |
| the vectors a conformance test asserts | the test, and every other test |
| — | the length prefix, the frame reader, the connection, the socket (ADR-0084 §3) |
| — | the envelope's member names, and the limit's own number |
| — | the error mapping, the client's Protocol implementation |

**Three consequences of drawing it there, in the order they bite:**

- **A decoder is not held to this ADR.** The canonical form is an obligation on
  the *writer*. A reader accepts any JSON that ADR-0084 §3 already admits — that
  ADR's undecodable-frame list is closed ("that covers the whole class") and
  does not include "not canonically spelled", and adding a refusal to it would be
  amending ADR-0084 §3, which is not this ADR's to do. Nothing is lost: both
  halves ship from one environment (ADR-0084 §3), so a non-canonical frame is a
  bug rather than a peer to accommodate, and it is caught by the vectors on the
  side that wrote it.
- **The limit is measured on the value, on both sides, so a lenient reader costs
  nothing — provided measurement runs *after* validation.** ADR-0084 §4 puts the
  limit on the *value* rather than on the frame, and that is what makes this
  work: the sender encodes canonically and refuses before sending; the receiver
  decodes, validates into the declared type, and measures the canonical encoding
  of the validated value. Same value, same bytes, same number — which is only
  true because of §4, and is the second reason byte-determinism is load-bearing
  rather than tidy.

  > **The order is decode, then validate, then measure**, and it is fixed rather
  > than left to an implementation. A value with no canonical form (§2c) must not
  > reach the measurement step.

  **This is not fussiness — measuring first is unsatisfiable.** `1e999` is
  well-formed JSON that CPython decodes to `float("inf")`, and §2c gives a
  non-finite float no encoding, so a receiver that measured before validating
  would have to produce a size for a value that has none. Validating first
  disposes of it: `inf` fails any bounded `float` field, and inside `FrozenJson`
  it is refused structurally by `_deep_freeze`, whose docstring gives this exact
  reason — `json.dumps` "renders it to a non-JSON token (`NaN`/`Infinity`)
  instead of raising, so running the encoder would let it through". **The place a
  non-encodable value is refused is the type, not the frame**, which is also why
  this ADR adds nothing to ADR-0084 §3's closed undecodable-frame list. §9
  records what is left open where a declared type admits such a value anyway.

  The frame's own size is a separate bound with a separate subject (ADR-0084 §3's
  prefix), related to the limit by a reserve §2a and §7 both decline to set.
- **Two encoders may exist without the contract weakening.** This is §1's payoff
  and it is what makes the boundary survivable: because conformance is defined by
  output, an encoder inside `wire` and an encoder the in-process engine reaches
  for are byte-identical if both pass §5, whether or not they share a line of
  code. §9 records the open question that makes this matter.

### 8. A vector change is a protocol version bump; a new vector is not

ADR-0084 §3 makes the protocol version "a single integer exchanged in the connect
handshake and nowhere else", matched exactly, with a mismatch refusing the
connection. Three cases, and they are genuinely different:

- **Changing the bytes a ratified vector fixes requires a protocol version bump,
  and an ADR that partially supersedes this one.** The bump because the encoding
  is precisely what an exact-match version protects — a peer that spells a
  duration differently is not a peer this one can exchange frames with, and the
  boundary of a contract limit moves with it, which changes which calls are
  refused. The ADR because a vector is a ratified decision and ADR-0070 §1 is
  categorical that changing one takes a superseding ADR. Neither substitutes for
  the other: the bump makes a half-upgraded deployment legible, the ADR makes the
  change reviewable.
- **Adding a vector for a case no existing vector covers, consistent with §2,
  requires neither.** It records a consequence of an already-ratified property
  rather than changing one, and it changes no byte any conforming encoder was
  emitting. This is ADR-0083 §15's stacked addition on its own test: §1's
  sentence that the list is not exhaustive stays true and now covers one more
  case. Saying this explicitly is what stops §5 from being the closed
  enumeration Context rightly refuses to write — the list can grow without the
  corpus paying a supersession each time review finds another corner.
- **A vector that contradicts a ratified property is not an addition.** It is
  either an error in the vector or a change to the property, and it takes the
  first case's treatment.

**None of this reaches the connect exchange, because §2 does not.** §2's subject
is the payload of a `request`, `result` or `error` frame — the values the
promoted methods pass and return, which is what ADR-0084 §4's limit measures. The
connect exchange is not a method call: it is the handshake ADR-0084 §2 and §3
own, and this ADR neither spells its members nor orders them. §8's version rule
therefore applies to encoding changes on the *call* path only.

**Recorded because the temptation to extend §2 there is real, and it must be
resisted by a later ADR too.** ADR-0084 §3 freezes the connect frame's framing
and decoding "in every protocol version, permanently", precisely so that a v1 hub
can read a v2 client's connect frame far enough to report the mismatch — an
encoding change that reached the connect exchange would break the very mechanism
that reports encoding changes. So a later ADR that wanted one canonical spelling
across *all* frames would have to engage that freeze head-on and supersede it.
This ADR does not, and its silence about the handshake is a decision rather than
an omission.

**What this does *not* do is make ADR-0084 §3's exact-match rule carry more than
it says.** The rule is unchanged: one integer, matched exactly, refused at
connect. §8 adds an obligation on whoever changes an encoding, not a new
behaviour at the handshake.

### 9. What is left open, honestly

- **A declared type that admits a value with no canonical form.** §2 gives two
  values no encoding — a lone surrogate `str` (§2b) and a non-finite `float`
  (§2c) — and §7 fixes that the type is where each must be refused, before
  measurement. `FrozenJson` already does it: it refuses the non-finite float
  structurally and catches the surrogate **by running the real encoder at
  validation time** rather than by enumerating the value types that can fail,
  which is exactly what the surrogate and big-integer cases defeated when they
  were enumerated (issues #121, #127). A plain `str` or an unbounded `float` on
  the promoted surface has no such validator, so a value the in-process engine
  accepts could be one the wire cannot carry. `_freeze_json` is both the shape of
  the fix and the reason it is not made here: **the refusal belongs on the type,
  and the promoted types are the surface ADR's.** Filed rather than designed
  around.
- **The oversized integer is *not* on that list, and its absence is a ruling
  rather than an oversight** — §2c: the domain is #421's and ADR-0084 has already
  declined to bound it here, adding a deployment constraint instead. Recorded so
  that a later reader does not read the previous item as covering it.
- **Where the encoder lives, for the in-process engine.** ADR-0084 §4 obliges
  every implementation to enforce the limit — "the in-process engine included" —
  and an engine with no payload to serialise for its own sake must build one to
  do so. ADR-0084 §6 places the codec in the `wire` package, which
  `orchestration` cannot import concretely without engaging golden rule 1. §7
  shows the contract survives either resolution, because two encoders that pass
  §5 are byte-identical whether or not they share code; **which one change 4
  builds is change 4's, and filed.** This is the clearest payoff of ratifying an
  output rather than a module, and it is why §1 rejects naming a serialiser.
- **The connect exchange's spelling.** Its members are described in prose by
  ADR-0084 §2 — a version, a client identifier, a credential slot — and never
  enumerated as a schema. **This ADR deliberately does not reach them** (§8): §2
  is scoped to the call path, and ADR-0084 §3's permanent-representation freeze
  makes the handshake the one place a canonical encoding could not simply be
  extended later without superseding that clause. Whether the handshake wants one
  at all is ADR-0084 §3's question, not this ADR's.

### 10. Amendment records under ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds? §1 also
fixes the order — classify, then record.

**One record is owed, on ADR-0084 §5.**

The clause is §5's enumeration and its count:

> The sequencing is therefore **four** changes, not one … 3. **the triad** … 4.
> **the hub, the `wire` package, the client, and the `lint-imports` edits** (§6).

Both limbs of the test fail:

- **A reader would act differently.** Holding only ADR-0084, a reader who has
  ratified the surface ADR builds the triad next, and builds it against an
  unratified encoding. §6 puts a contract change ahead of the triad for a reason
  that reader has no way to reach from §5's four items: the triad ships the
  second implementation, so an unratified encoding stops being a deferral and
  becomes a divergence in the one clause §4 hands the conformance suite.
- **A clause is read more widely than it now holds.** §5's item 4 — "the hub,
  the `wire` package, the client" — is read as carrying the canonical encoding,
  and that is not a strained reading: ADR-0084 §6 gives the `wire` package "the
  codec", and the surface ADR's draft assigns the byte-level encoding to change 4
  in as many words. It no longer holds.

**ADR-0083 §15's stacked-addition carve-out does not reach it, on its own stated
test.** That rule holds where "the deferring sentence **stays true** and now has
an answer". "The sequencing is therefore four changes, not one" does not stay
true; it becomes five. This is the same reading ADR-0084 §12 applied to ADR-0042
§1 — a sentence that states a count or a refusal is not discharged by a later ADR
changing it, it is superseded by it.

**So the instrument is partial supersession**, and the record is:

- a leading `Partially superseded by ADR-0087 (§5's enumeration of the
  implementation sequence as four changes)` token on ADR-0084's `Status`, which
  is plain `Accepted` today, so there is no amendment qualifier to move
  (ADR-0082 §2);
- ADR-0070 §1's appended dated note, which under ADR-0082 §2 is where the whole
  record lives on a leading-token line;
- **no ratified text of ADR-0084 rewritten.** §5's list stays exactly as written
  and so does every word of its reasoning; the note records that its count became
  false, which decision of this ADR did it, and — at length, because it is the
  larger half — what §5 decided that does *not* move.

**Both records land in this change**, and the argument is ADR-0084 §12's own,
inherited: it wrote its records on ADR-0042, ADR-0073 and ADR-0078 in its own
change so that `main` would never carry text asserting something already false
"with nothing mechanical to detect it". Nothing detects a stale enumeration or a
superseded encoding rule. The alternative — reporting the obligation and letting a
later change discharge it — leaves a window in which ADR-0084 says four and the
corpus contains five, and the window has no natural end.

**That this ADR is `Proposed` is not an objection to writing the record, and the
corpus settles it in as many words** — recorded here because it is the question a
reader most naturally asks of a `Status` line naming an unratified ADR. ADR-0070
§1 permits "recording a supersession that has landed" and warns that this
"presupposes the superseding ADR *exists*". ADR-0083 §15 states what that
condition amounts to:

> **The existence condition is that the naming ADR ships in the same change, not
> that it has ratified** — so this record is well-formed from the moment it is
> written, and if this ADR does not land, neither does it.

That is the form ADR-0075 established, and `main` carries it on ADR-0042,
ADR-0050, ADR-0073, ADR-0074 and ADR-0078. ADR-0084's own §12 used it for the
record it wrote on ADR-0042 while ADR-0084 was itself `Proposed`: "while this one
is `Proposed` the line names a supersession that is drafted rather than ratified".
**So ADR-0084's `Status` names an ADR that exists in the same commit**, which is
the hazard ADR-0070 §1 guards against, closed. If this change does not land,
neither does the record.

**Why this ADR carries the record and the surface ADR does not.** The record
belongs where the falsifying decision is, and the decision that falsifies §5's
count is *this ADR inserting itself into the sequence*. An ADR that merely cites
this one for the encoding falsifies nothing: "the limit is measured on the
canonical encoding ADR-0087 ratifies" leaves §5's enumeration exactly as true or
false as it was, and decides nothing about order. It is the insertion, not the
citation, that a reader holding only ADR-0084 would act wrongly on — and
ADR-0070 §1's test is a test about readers.

**After this change, this record is the only thing in the corpus stating that
§5's enumeration has grown**, which is the reason §10 is written at the length it
is rather than as a status line and a sentence. The note on ADR-0084 carries the
same three parts as the analysis above: what became false, what did the
falsifying, and — the part a bare token would lose — the whole of what §5 decided
that still stands.

**A second record is owed, on ADR-0084 §3's payload-encoding clause.**

The clause is §3's third and fourth payload bullets:

> - a **result** payload is a promoted `core` model (§4) serialised through
>   **pydantic's JSON mode** …
> - **arguments and scalars** … take **pydantic's JSON-mode form** for their
>   type …

**The first limb fails, in three measured places.** A reader holding only
ADR-0084 writes an encoder that calls pydantic's JSON mode and believes it
conforms. After this ADR it does not: it emits members in declaration and
insertion order where §2a requires code-point order, `"P1Y"` for a year where
§2e requires `"P365D"`, and `null` for a non-finite float where §2c requires a
raise. §3's table above is the exhaustive scope, which is why it is written as a
table.

**The second limb fails too, and it is the sharper one.** §3's clause is read as
*determining* the payload's bytes — that is the job it was written to do, being
the subsection that makes "the framing and the codec … normative, because two
implementations that satisfy every rule above could still be unable to exchange a
frame". It does not determine them: pydantic's JSON mode emits a
`FrozenJsonMapping` in caller-insertion order, so two `==`-equal `Confirmation`
values get two byte strings (§4a). The clause holds more narrowly than it is
read — it fixes a *form* (a duration is an ISO-8601 string, not a float of
seconds) and does not fix a *byte string*.

**Stacked addition does not reach it** on ADR-0083 §15's test: "serialised
through pydantic's JSON mode" is not a deferral that stays true and gains an
answer, it is an answer, and it is replaced by a different one.

**What is not replaced is most of §3, and the note says so at length**: the
UTF-8 JSON codec, the 4-byte big-endian length prefix, the object envelope, the
duplicate-member refusal, the undecodable-frame close and its closed list, the
correlated-error boundary, the serial-connection rules, the exact-match version
and the permanent-representation freeze. §2 also keeps §3's own stated *reason* —
"choosing an existing encoding rather than specifying a new one is the whole
point of this subsection" — by binding to ADR-0021 §1's form, which is the
encoding the stores already depend on and the one §3's closing sentence points
at. **The instrument changes; the intent is the one being carried out.**

**And the envelope keeps its own rule.** §3's "member order is therefore not
significant and no ordering rule is needed" is about the envelope — its own
grammar says so, and the adjacent bullet says "in the envelope **and in payload
objects alike**" when it means both. §2 is scoped to the payload (§2's opening),
so that sentence stays true of its subject and no part of the record reaches it.

**So ADR-0084's `Status` scope names both clauses**, §5's enumeration and §3's
payload-encoding rule, in one leading `Partially superseded by` token with one
dated note beneath it (ADR-0082 §2).

**No record is owed on:**

- **ADR-0085, the surface ADR.** It is `Proposed` and unmerged, so there is no
  ratified decision to supersede and ADR-0082 §1's machinery does not engage at
  all; its own note is explicit that ratifying a `Proposed` ADR is not an
  amendment event, and the same holds a fortiori for a draft that has not landed.
  This ADR merges first and does not wait on it. What that draft names as a debt
  the wire lane inherits, this change discharges early — a debt discharged before
  the debtor expected is discharged — and what its text would need is one
  sentence saying the limit is measured on the canonical encoding ratified here.
  **One caveat on its figures, and it is small but real**: §2a's ordering is
  length-preserving and §4 normalises nothing, but §2e changes a ≥365-day
  duration by up to three bytes (§2e proves the bound). Any reserve, floor or worst-case width that ADR
  computes must be computed on §2's forms. Nothing in this ADR's own text depends
  on which numbers it picks.
- **ADR-0021.** §2 uses §1's canonical form as the form it is, for a second
  consumer. Applying a rule at its stated scope is the rule being used rather
  than changed, and ADR-0084 §3 asked for exactly this reuse by name. Nothing
  ADR-0021 decided about digests moves, and no digest's bytes change.
- **ADR-0084 §4 and §6.** §4's ruling that the limit is contract rather than
  transport is the premise this ADR serves. §6's placement of the codec in `wire`
  is untouched: §7 keeps the encoder there and takes only the *specification* of
  its output, which is the same division ADR-0084 §5 already makes between a
  contract ADR and the lane that implements it.
- **ADR-0068.** §1's frozen-model rule is what makes the promoted types
  serialisable at all. This ADR adds no model and changes no field.
- **ADR-0042, ADR-0037, ADR-0052, ADR-0083.** Untouched. This ADR names no
  method, no enum member, no lifecycle step and no setting.

## Consequences

- **The conformance suite ADR-0084 §4 nominates can test the clause it was
  nominated for.** The boundary is fixed before the triad rather than after it,
  so a suite holding two implementations to "every implementation enforces the
  limit" is no longer obliged to skip *where* the limit is. Whether it *should*
  assert a byte-exact boundary is still the triad lane's call — a
  byte-dependent assertion is brittle either way — but the option exists, and the
  reason it did not is gone.
- **The wire lane inherits a specification and a test suite, not a design task.**
  §5's vectors are the assertions; §2 is the docstring. What is left is an
  encoder, a duration serialiser (§2e) and a sort.
- **A `model_dump_json()` shortcut will not pass.** Three of §3's rows and one of
  §4's are places the obvious one-liner produces the wrong bytes. That is a cost
  — the wire lane writes ~20 lines it hoped not to — and it is the cost of the
  encoding being a ratified fact rather than a library's current behaviour.
- **The corpus now has one canonical JSON form with two consumers.** ADR-0021
  §1's digest form and the wire's encoding are the same rule over the same
  structure, which is what ADR-0084 §3 asked for and #421 wanted. A change to one
  is now visibly a change to the other, where before it would have been two
  independent decisions nobody compared.
- **ADR-0084 §5's sequence is five changes and its `Status` now says so.** The
  record lands in this change, so `main` never carries a four-change enumeration
  with a fifth change already merged beside it. What a reader of ADR-0084 gains
  is a pointer; what they keep is §5's list and its whole argument, unedited.
- **Two further contract ADRs are in flight beside this one** — the surface ADR
  (#549) and the evidence-bound ADR (#551) — and all three bear on the triad.
  This ADR constrains their order in one direction only: everything contract-side
  precedes change 3. It fixes nothing about the order among themselves, and §6
  says so explicitly so that no later reader infers one from the ADR numbers.

## Alternatives considered

- **Leave the encoding to change 4, where ADR-0084 §6's "codec" placement points.**
  Rejected on ADR-0084 §5's own item 3: the triad's canonical fake is a second
  implementation and it precedes change 4. The cost is not "the bytes are pinned
  later", it is "the conformance suite cannot assert the contract clause §4 hands
  it", which is a hole in the substitutability ADR-0084 §4 was written to
  guarantee, closed only by a lane that arrives after the suite is written.
- **Put the encoding inside the surface ADR.** Rejected. It is a byte grammar
  inside an ADR about method signatures; the two want different evidence and
  different reviewers, and merging them produced four review rounds each finding
  one more uncovered corner. Splitting them is ADR-0084 §5's own move — "whether
  the trigger has fired" and "what the surface is" are separate ADRs for the same
  reason, and this is a third question of that kind.
- **Name the serialiser and its settings** (§1). The strongest alternative, and
  rejected on three grounds: a permanently frozen codec cannot be defined as a
  dependency's defaults; the defaults are already wrong in three places, so the
  description would not be accurate anyway; and a specification defined by output
  rather than by implementation is what lets two encoders coexist without
  weakening the contract (§7, §9).
- **State properties only, no vectors.** Rejected by measurement: CPython and
  `pydantic-core` both implement "the shortest decimal that round-trips" and
  disagree on `1e-5` and `1e-7`. A property that admits two byte strings is not
  one encoding, and the only thing that closes it is a byte string.
- **Ratify `P1Y` as exactly 365 days** (§2e). Rejected: it publishes a private
  convention under a standard notation, on a codec ADR-0084 §3 freezes
  permanently, and it leaves a decoder built to ISO-8601 unable to conform. The
  alternative costs one function.
- **Encode every duration as whole seconds — `PT172803S`.** Genuinely arguable:
  it eliminates the nominal-component question by construction and is a shorter
  rule. Rejected because it makes *every* duration deviate from what the library
  emits, maximising the surface on which a `model_dump_json()` shortcut silently
  produces non-conforming bytes; the day/hour/minute form deviates only above 364
  days, and §5d pins that corner as a vector so the deviation is not invisible.
- **Preserve declaration order instead of sorting members** (§2a). Rejected
  because it makes reordering two fields in `core/types.py` a protocol change
  that no reviewer would recognise as one, and because sorting is what
  `_canonical_bytes` already does — taking the corpus's existing form unchanged
  rather than a variant of it.
- **Make canonical spelling a requirement on readers too** (§7). Rejected as
  out of scope in the strict sense: it would add a refusal to ADR-0084 §3's
  deliberately closed undecodable-frame list, which is that ADR's to change.
  Refusing there also buys nothing this ADR does not already get from the
  vectors, which catch a non-canonical encoder on the side that wrote it.
