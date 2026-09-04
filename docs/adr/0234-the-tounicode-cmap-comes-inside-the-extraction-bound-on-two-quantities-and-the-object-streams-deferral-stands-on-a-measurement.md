# 234. The `/ToUnicode` CMap comes inside the extraction's bound, on two quantities rather than one, and the object stream's deferral stands on a measurement

- Status: Proposed
- Date: 2026-09-04
- **Partially supersedes**
  [ADR-0232](0232-the-extractions-cost-is-bounded-on-decoded-bytes-and-the-file-bound-stays-the-files-own-size.md)
  — **its exclusion of a font's `/ToUnicode` CMap from what an extraction is bounded on,
  and the one-field shape that exclusion held up.** Six clauses move, every one of them
  about that question. §2's *"The decoded inputs an extraction reads **once and caches** …
  are **not bounded by this ADR**, and no implementation, lane or later ADR derives a
  refusal criterion on them from this field"* keeps its `/ObjStm` half and loses its
  `/ToUnicode` half: §1 below charges that CMap's decoded length to
  `fetch_max_decoded_bytes`, once per parse, for every font in a parse's resource context
  whose `/ToUnicode` resolves to a stream. §2's *"`Settings` gains **one** field"* becomes
  two — **the larger half of this supersession** — because the CMap's cost is a function
  of its decoded bytes **and** of the mappings its parse builds, and neither is a function
  of the other: 65,000 mappings arrive in 927,031 bytes of `bfchar` or in **178** of
  `bfrange`, so §2 below adds `fetch_max_character_mappings` for the second quantity, with
  its own named default and stated domain and refused at load in the same form. §3's
  *"Nothing else is counted, and that is a boundary rather than a gap"* names the CMap in
  its enumeration of what is not charged, and that name comes out while the `/ObjStm`
  stays — its separating test, the per-parse multiplier and never the cost per byte,
  unchanged and now coming out the other way. §4's *"which of the **three** bounds
  refused"* becomes any of **four**: that clause's **ruling** is extended rather than
  replaced and binds the new field entire. §8 arm 11's second arm requires a document
  whose large `/ObjStm` **and** whose large `/ToUnicode` CMap both sit inside
  `fetch_max_file_bytes` to **fetch**, *"neither charged"*; §7 below keeps the `/ObjStm`
  half verbatim and replaces the CMap half. And §10's fifth deferral — the once-and-cached
  class — loses its `/ToUnicode` half, which the 2026-09-04 note on that ADR already
  recorded as **fired**; §6 below re-states its `/ObjStm` half on the measurement it was
  missing, `PdfReader._get_object_from_stream` being entered once whatever the page count.
  **Everything else in ADR-0232 stands**, and most of it is load-bearing here: §1's file
  bound, §2's counted-per-parse rule, its 1 MiB figure and its naming and
  independent-figure clauses, §3's walk entire and the standard it is held to, §4's single
  `TOO_LARGE` class and closed five-member enumeration, §5's refusal of a deadline, §6's
  evidence-about-a-version rule, §7's untouched audit, §9's footprint and the lane it
  charges, and §11. §10 below shows the working under
  [ADR-0070](0070-adr-lifecycle-amend-supersede-status.md) §1 and
  [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §1, clause by
  clause, including the clauses a reader would most expect to have moved and which did
  not. ADR-0232's `Status` line reads `Accepted` and takes the leading token in this
  change (ADR-0082 §2). Nothing is recorded against
  [ADR-0230](0230-the-planner-names-a-file-it-was-shown-and-the-loop-fetches-it-into-the-supply.md),
  whose §6 is already partially superseded in exactly this scope.

## Context

### Where this comes from

ADR-0232 bounds what a PDF extraction **parses** — content-stream operators and, per
parse, an embedded `/Type1` font program the extraction re-parses on every page — and
says in terms what it does **not** bound. §10 defers two decoded inputs by name, a
compressed object stream and a font's `/ToUnicode` CMap, on exactly one ground:

> Each is read **once** and cached, so no per-parse multiplier acts on either — which is
> what separates them from the font program and is the *whole* of the ground for
> deferring them.

That ground is false for the CMap, and PR #2037's sixth review round found it while
implementing the ADR. `EncodedStreamObject.get_data()` caches the *decompression*, but
`PageObject._extract_text` rebuilds a stream's fonts on **every** call, so
`Font.from_font_resource` → `get_encoding` → `_parse_to_unicode` → `prepare_cm` re-runs
the whole-buffer normalisation and rebuilds the mapping dictionary once for every page.
#2042 recorded that; the 2026-09-04 note on ADR-0232 records that §10's first firing
condition — *"a measurement showing one of them re-read or re-parsed per page"* — is
therefore met for the `/ToUnicode` half, and that firing a deferral is not itself a
decision. #2050 carries this ADR.

**The note also refused the reassurance that would have made the residual small.** Its
measurement varied the dimension #2042 did not: holding the CMap near 2 MB and varying
only the number of mappings, the marginal cost per page runs 0.020 s at 1,800 mappings
to **0.354 s** at 90,000 — against **1.28 s** for a megabyte of `Tj` operators on the
same machine, which is the figure ADR-0232 §2 sized `fetch_max_decoded_bytes` against.
So at the adopted version's own mapping ceiling one page's CMap re-parse is within a
factor of about 3.6 of the instruction class this system already bounds, and ten pages
sharing that font cost 3.5 s. That is ADR-0232 §10's escalation shape reached on
measurement.

### The measurement that decides this ADR's shape, which neither #2042 nor #2050 took

Everything above varies the mapping count at a **fixed** CMap size, which leaves open
the question a bound has to answer: *is the cost a function of a quantity the walk can
charge?* The obvious charge is the CMap's decoded bytes, exactly as ADR-0232 charges the
font program's. **It is not a bound, and this is the measurement that shows it.**

`pypdf`'s `parse_bfrange` admits a range line — `<a> <b> <c>` with no bracketed list —
and builds `b - a + 1` mappings from it, checking `_check_mapping_size(entry_count +
range_size)` before the loop that builds them. So a *range* declares mappings at a rate
no byte count tracks. Built and measured on this machine, `pypdf` 6.16.2:

| CMap form | mappings | CMap bytes | mappings per byte |
| --- | --- | --- | --- |
| `bfchar`, one line per mapping | 65,000 | 927,031 | 0.07 |
| `bfrange`, range lines | 65,000 | **178** | **365** |

A factor of about **5,200**. And the cost follows the mappings, not the bytes: the
178-byte CMap costs what the 927 KB one costs, per page, to within the byte term. The
consequence for a byte charge is arithmetic. A 225-byte CMap declaring 90,000 mappings
costs **0.147 s per page**; charged as bytes, a thousand pages sharing that font is
225,000 bytes — **21%** of `fetch_max_decoded_bytes`'s 1 MiB default — and the document
costs minutes. **A byte charge on this input is the false promise ADR-0232 was written to
end**, one input over: a number that looks like a bound, is checkable, and is not a
function of the cost it claims to bound.

**The two quantities are genuinely two, and each is separately an amplification.** Holding
the mapping count at 1,800 and varying only the CMap's decoded size, the marginal cost
per page runs 0.006 s at 25 KB to **0.037 s** at 8 MB — `prepare_cm`'s whole-buffer
normalisation, linear in bytes, and re-run per page like everything else here. That term
is small per byte and, multiplied by an unbounded page count, is exactly the shape
ADR-0232 §2 already ruled on for the font program: *"Cheap per byte times an unbounded
page count is not cheap."* So the byte term must be charged **and** the mapping term
must be bounded, and neither one bounds the other.

### What the tree settles, verified against `origin/main` at `411cee4c`

- **Every font in a parse's resource context is built, whether or not any `Tf` names
  it.** `PageObject._extract_text` iterates the whole `/Font` resource dictionary and
  calls `Font.from_font_resource` on each, swallowing only `AttributeError` and
  `TypeError`, **before** it resolves the content key. So the CMap parse happens for
  every font the walk can already see, and the predicate needs no forecast of which
  fonts the operators will select.
- **The walk already calls that builder, and already stops short of the CMap on
  purpose.** `readers/_extract.py`'s `_establish_font` calls `Font.from_font_resource`
  to mirror the extraction's own font-initialisation failures, and is asked *"only of a
  font carrying no `/ToUnicode`"*, on the stated ground that the CMap parse is *"an
  input ADR-0232 §2 and §10 leave uncharged and unbounded by name"* and that asking
  would add *"unratified work"* to the seam. This ADR is what ratifies it, and #2043 —
  which records that exclusion's residual and says in terms that it *"become[s] cheap if
  #2042 is ruled and the CMap is charged"* — has its **first** residual closed as a
  consequence and its second left standing.
- **`prepare_cm` reads a stream or synthesises a constant.** Where `/ToUnicode` resolves
  to a `StreamObject` it calls `get_data()`; otherwise it uses a fixed 44-byte literal
  declaring two mappings. A `/ToUnicode` that is a name is therefore a quantity no
  document controls, and is charged nothing by either field below.
- **The object stream really is resolved once.** Instrumented on this machine, a document
  whose page font lives inside a 2 MB `/ObjStm` calls `PdfReader._get_object_from_stream`
  **once** at 1, 5, 20 and 50 pages — the count does not move with the page count,
  because `_get_object_from_stream` parses every object in the stream in one pass and
  caches each, and `get_object` consults that cache first. §7 below is that measurement
  and what it licenses.

### What this ADR is not allowed to settle

ADR-0232 §6 rules that *"A pinned dependency's own internal limit is **evidence about the
version this project resolves** and is never a bound this system relies on or states as
its own."* `pypdf` 6.16.2 caps a CMap at `MAPPING_DICTIONARY_SIZE_LIMIT` (100,000
mappings) and **raises** past it. That number is why the per-page figures above stop at
0.35 s rather than continuing, and it is recorded here for that reason and for no other.
**It is not the argument for any figure below**, it is not a bound this ADR states, and a
release that raised, lowered or removed it would change no clause here.

Nor does this ADR reopen anything ADR-0232 settled: not the file bound, not the single
`TOO_LARGE` class, not the refusal of a deadline, not the audit, and not §3's standard
that the walk agrees with the extraction about which parses happen rather than
re-implementing it. And it does not reach #2045 — the walk descending further into a
chain of Form XObjects than the interpreter's recursion limit lets the extraction
descend. That is a different class with a different residual, §10 defers it by name, and
nothing here moves it.

## Decision

We will bring a font's `/ToUnicode` CMap inside the extraction's bound, charged **once per
parse** exactly as the font program is, on **two** quantities rather than one: its decoded
bytes, which join `fetch_max_decoded_bytes`, and the **mappings its parse builds**, which
take a `Settings` field of their own because neither quantity is a function of the other.
ADR-0232 §10's **`/ObjStm`** half stands deferred, now on a measurement rather than an
assumption. Nothing else moves: no sixth `FetchRefusal` member, no deadline, no audit
field, no Protocol, and no change to what ADR-0232 §3's walk is or to the standard it is
held to — the one thing this reaches in `core/types.py` being `TOO_LARGE`'s docstring,
which enumerates that member's causes and gains a fourth.

### 1. The CMap is charged per parse, and the predicate is decided before anything is decoded

> **Normative.** For **PDF**, `fetch_max_decoded_bytes` **also** counts, for each parse,
> the decoded length of the `/ToUnicode` CMap of **every font in that parse's resource
> context whose `/ToUnicode` resolves to a stream**. It is charged **once per parse**, so a
> font meeting the predicate on forty pages is charged forty times, and the total is
> ADR-0232 §2's — running across the whole fetch, never per page.

> **Normative.** **The predicate is `/ToUnicode` present and resolving to a stream, and
> that is the whole of it.** No `/Subtype` test, no `/FontDescriptor` test, and no test of
> which fonts the operators select: `PageObject._extract_text` iterates the whole `/Font`
> resource dictionary and builds each entry **before** it resolves the content key,
> whether or not any `Tf` names it. Resolving the `/ToUnicode` entry is `get_object()`,
> which does **not** decode, so the predicate is decided from dictionaries the walk has
> already resolved — ADR-0232 §3's own standard, and the one PR #2037's rounds 3 to 5
> established is the only completable one against this library.

> **Normative.** A `/ToUnicode` that is **not** a stream is charged **nothing**, by either
> field. `prepare_cm` synthesises a fixed 44-byte literal for that case — a single
> `beginbfrange` line spanning `<0000>` to `<0001>` — declaring two mappings. It is a
> constant of the adopted version rather than a quantity a document controls, and a bound
> that counted it would be counting the library instead of the file.

> **Normative.** **The charge is per parse because the extraction re-parses the CMap per
> parse**, and the multiplier is therefore the page count — the identical argument
> ADR-0232 §3 makes for the font program, reaching this input through the same
> `from_font_resource` call. `get_data()` caches the decompression; `prepare_cm`'s
> normalisation and `_parse_to_unicode`'s dictionary build are not cached and repeat once
> for every page. **A quantity charged once when the extraction pays it many times is not
> a bound** (ADR-0232 §3), and that is true of the CMap for the same reason it is true of
> the font program.

> **Normative.** **This adds nothing to the walk's shape and no new instrument.** ADR-0232
> §3's walk already resolves each parse's inherited resources, enumerates that context's
> `/Font` dictionary and charges what the extraction will decode there. The CMap is a
> further charge at a point the walk already stands at, and every clause of §3 — the
> agree-with-the-extraction standard, the resource-inheritance rule, the two named early
> exits, the fail-closed `EXTRACTION_FAILED` branch, the per-parse counting, the
> stream-by-stream comparison — governs it unchanged.

### 2. Two quantities, two fields, because neither is a function of the other

> **Normative.** `Settings` gains **one further field**, beside `fetch_max_decoded_bytes`
> and ADR-0230 §6's four, with a named default, with a domain of **integers of at least
> 1**, and refused at **load** rather than at the first fetch — `Settings`'s own refusal,
> before any fetcher is built and before any filesystem call (ADR-0093 §5, in the form
> ADR-0230 §6 borrows it), stopping the deployment exactly as an out-of-domain
> `fetch_max_decoded_bytes` does:
>
> - **`fetch_max_character_mappings`**, default **262,144** — the `/ToUnicode` mappings
>   one fetch's extraction **builds, summed once per parse**.

> **Normative.** **The counted quantity is the mappings the parse *builds*, never the size
> of the mapping dictionary that survives it.** A CMap whose ranges send two codes to one
> dictionary key pays for both, because the cost is in the insertions;
> `pypdf._cmap._parse_to_unicode`'s accounted count — the one `_check_mapping_size`
> compares — is that quantity, and a count taken after duplicates collapse under-charges
> exactly the document that declares the most.

> **Normative.** **The name is fixed here** and is not the implementing lane's to choose,
> as ADR-0232 §2 fixes its own and ADR-0230 §6 fixes its four. It carries neither `bytes`
> nor `decoded` nor `content`: it is not a byte count, and a reader meeting a fourth
> `…_bytes` field that measures something other than bytes would have to read an
> implementation to discover it.

> **Normative.** It is an **independent figure and never a derived one.** No implementation
> computes it from `fetch_max_decoded_bytes`, from `fetch_max_content_bytes` or from
> `fetch_max_file_bytes`, and no deployment's change to any of those moves it.

> **Normative.** **For plain text and Markdown the counted quantity is zero**, and no
> implementation checks `fetch_max_character_mappings` on those formats — ADR-0232 §3's
> clause of that name, in its own words: their extraction has no decoding step, so it
> builds no mapping. A `.txt` or `.md` file is never refused on this bound.

> **Normative.** **The field is counted in the concrete extractor, per format**, on what
> that format's own decoding produces, exactly as ADR-0232 §3 requires of
> `fetch_max_decoded_bytes`. It is not a `core` concern, it adds no argument to any
> Protocol, and it reaches the extractor as a configured figure as the other four bounds
> do.

> **Normative.** **Neither field may absorb the other's quantity, and in particular no
> implementation converts mappings into notional bytes to charge them to
> `fetch_max_decoded_bytes`.** An exchange rate between the two would make an operator's
> byte figure govern a quantity that is not bytes, at a ratio no operator chose and no
> document respects.

**Why two fields, stated as the argument ADR-0232 already made and this measurement
extends.** ADR-0232 §1 reads ADR-0230 §6's two size bounds as two because *"what is read
and what reaches the prompt are different quantities with different consumers, and one
number cannot be honest about both"*, and adds a **third**: *"The bytes an extractor
parses are a **third** such quantity with a third consumer — the parser — and the same
argument that made §6 two fields makes it three."* The mappings a CMap parse builds are a
**fourth**, whose consumer is the mapping-dictionary build, and the same argument reaches
it with one difference that makes the case stronger rather than weaker: for the first
three quantities a reader could at least believe one bounds another, and here the
measurement forecloses it. 65,000 mappings arrive in 927,031 bytes of `bfchar` or in
**178** bytes of `bfrange`, a factor of about 5,200, because `parse_bfrange`'s range form
builds `b - a + 1` mappings from a twenty-byte line and checks
`_check_mapping_size(entry_count + range_size)` before the loop that builds them.

**So a byte charge on this input would be a bound in name only, and this ADR refuses to
write one.** ADR-0232 §2's test is *"whether the extraction's cost is a function of the
quantity"*. The CMap's cost per page is a function of **two** quantities, and a charge on
one of them leaves the other free: a 225-byte CMap declaring 90,000 mappings costs 0.147 s
per page, so a thousand pages sharing that font charge **225,000 bytes** — 21% of the
1 MiB default — while costing minutes. A reader of a single-field decision would hold a
number that is checkable, that looks like a bound, and that the worst document walks
straight past. That is the shape of claim ADR-0232 was written to end, and writing it one
input over would be the same mistake with a different subject.

**Why the byte half is not a third field, which is the question this section's own
argument invites.** CMap bytes are cheap against operator bytes — about 0.0045 s per
decoded MB per page against roughly 1.3 s per MB for `Tj` operators, a factor near 280 —
and a reader who has just been told that two quantities need two fields will ask why these
two do not. **Because they are one quantity.** Both are decoded bytes the extraction
parses, counted at the same point, consumed by the same parser, and differing only in what
a byte of each costs — and ADR-0232 §2 rules in terms that *"A per-byte cost is not the
test for whether a class is charged"*. It already made this exact trade for the embedded
font program, 120× cheaper per byte and charged to the same field, and §5 below inherits
the over-refusal that follows exactly as §2 did. Mappings are not bytes at all: they are
not produced by decoding, they are not visible in any byte count, and they have their own
consumer in the mapping-dictionary build. The line between one field and two is the
quantity, never the price.

**And the byte half is not decoration.** Held at 1,800 mappings, the marginal cost per
page runs 0.006 s at a 25 KB CMap to **0.037 s** at 8 MB — `prepare_cm`'s whole-buffer
normalisation, re-run per page like everything else here. Cheap per byte, and ADR-0232 §2
has already ruled on what that is worth: *"Cheap per byte times an unbounded page count is
not cheap."* Both terms are separately amplified by the page count, so both are charged,
and each to the field whose quantity it is.

### 3. Establishing the mapping count, the order of the comparisons, and the residual

> **Normative.** The mapping count is established by **the extraction's own parse of that
> CMap** — `pypdf._cmap`'s, reached as the extraction reaches it — and never by a second
> grammar over the CMap's bytes. A scan of its own that computed a range's span, counted
> `bfchar` tokens or recognised a `beginbfrange` would be exactly the re-implementation
> ADR-0232 §3 forbids for content streams, in a grammar with more shapes to get wrong: a
> multi-line range continued across lines, a bracketed destination list, a `<<` block, a
> comment, a broken line the library skips with a warning. PR #2037's rounds 3 to 5 are
> the record of what predicting this library's control flow costs — three successive
> statements of one font condition, each incomplete in one more place — and the correction
> that ended them was to ask the library instead.

> **Normative.** The walk performs that establishing parse **at most once per distinct
> `/ToUnicode` stream per fetch**, and charges the count it yields at **every** parse whose
> resource context carries a font naming that stream. The count is a property of the
> stream; the charge is per parse. An implementation that re-parsed per page would pay the
> multiplier this bound exists to refuse.

> **Normative.** **The walk likewise establishes each distinct font at most once per
> fetch**, remembering the outcome — built, swallowed, or raised — and applying it at every
> later parse whose resource context carries that font. ADR-0232's implementation
> establishes per parse, which cost nothing while the CMap was excluded and would cost the
> whole of this bound's multiplier once it is not: a font established on forty pages would
> have its CMap parsed forty times by the walk on top of the forty the extraction pays.
> **The memo is sound because the outcome is a function of the font dictionary alone** —
> the extraction builds the same font from the same bytes on every page and fails or
> succeeds identically — so a walk that asks once and remembers agrees with it exactly
> where a walk that asks every time does, at one fortieth of the cost.

> **Normative.** **The order is fixed, and it is what makes the establishing parse
> affordable.** For each font in a parse's resource context whose `/ToUnicode` resolves to
> a stream, the walk (a) decodes that stream and charges its length to
> `fetch_max_decoded_bytes`, (b) compares that total and refuses the moment it is passed,
> (c) establishes the mapping count if this stream has not been established in this fetch,
> (d) charges that count to `fetch_max_character_mappings`, and (e) compares that total and
> refuses the moment it is passed. No implementation establishes several CMaps and compares
> their sum afterwards, and none establishes one before its bytes have been compared.

> **Normative.** **The residual this leaves is one establishing parse past the bound, and
> it is stated rather than argued away.** Obtaining a CMap's mapping count requires parsing
> it, so the parse that crosses `fetch_max_character_mappings` has completed before the
> comparison that refuses it. What bounds the parses *before* it is the bound itself: every
> established CMap's count is charged to the same running total, so the mappings built
> across a whole fetch's establishing parses are at most the bound plus one CMap's. What
> bounds that one CMap is the adopted version's own `MAPPING_DICTIONARY_SIZE_LIMIT` and
> nothing this project declares — evidence about a version (ADR-0232 §6), disclosed here
> in the same posture and for the same reason §3 discloses the 75 MB per-stream decode
> ceiling behind its own residual. **The establishing parse's other half is bounded
> outright**: `prepare_cm`'s normalisation is linear in the CMap's decoded bytes, and those
> bytes were charged and compared at step (b) before the parse was entered, so the walk
> never normalises a buffer `fetch_max_decoded_bytes` has not already admitted.

> **Normative.** **Where the establishing parse raises, the fetch is refused
> `EXTRACTION_FAILED`**, under ADR-0232 §3's one fail-closed branch and adding no member:
> the walk could not establish what the extraction will parse, and a document whose CMap
> the library's own parser will not read is a document of a supported format whose text
> could not be decoded. The exceptions `PageObject._extract_text` itself swallows while
> building a font — `AttributeError` and `TypeError` — are swallowed here too, because a
> font it swallows for is a font it goes on to parse the content stream past, and the walk
> agrees with it (ADR-0232 §3).

**Charging the CMap's bytes at every parse costs one decode, not many.** `pypdf` caches a
stream's decoded bytes on the object and the walk reaches the same stream object at every
parse, so taking its length again is a read rather than a second decompression — the same
property ADR-0232 §3 already relies on for content streams, and subject to the same rule
about such properties: it is why the charge is cheap, never why it is correct.

**Why the establishing parse is not the reliance ADR-0232 §6 forbids, and why it is not
the doubling ADR-0232 §3 already priced.** §6 forbids leaning on a dependency's limit *as
a bound this system states as its own*. Nothing here does: the bound is
`fetch_max_character_mappings`, this system enforces it, and the disclosure above is a
statement about a residual rather than about a bound. Nor is this §3's second-parse price
repeated: §3 pays for parsing an admitted document's content streams twice, once by the
walk and once by the extraction. Here the walk parses each CMap **once per fetch** where
the extraction parses it once per **page**, so the walk's own work is smaller than the
extraction's by exactly the multiplier this ADR exists to bound — and on a refused
document the extraction never runs at all.

**What that buys, in the terms ADR-0232 §5 sets for honesty.** This decision does not
claim to bound the *time* a CMap parse takes. It claims that the two quantities that time
is a function of are each bounded before the extraction is entered, that the work the
walk itself performs to establish the second is bounded by that same second bound, and
that a document passing both is one whose CMap cost is a few seconds at the default rather
than the minutes the same document costs today.

### 4. The refusal is `TOO_LARGE`, no sixth member, and the establishment becomes unconditional

> **Normative.** An extraction refused on **either** field of this decision yields the
> `FetchRefusal` member **`TOO_LARGE`**. `FetchRefusal` stays **closed at five members**
> and this ADR adds none. ADR-0232 §4 governs entire and its reasoning is unchanged: the
> class does not disclose which bound refused, and a refusal names a class and carries no
> path, no name, no count, no excerpt and no message from an underlying library.

> **Normative.** ADR-0232 §4's clause that the class does not disclose *"which of the
> three bounds refused"* now reads over **four**, and ADR-0232 §7's audit is untouched by
> that: no field, no event, no key and no emission point is added, and `TOO_LARGE` was
> already reachable and already carried.

> **Normative.** **`_establish_font`'s `/ToUnicode` exclusion goes.** ADR-0232's
> implementation establishes a font by calling `Font.from_font_resource` — the extraction's
> own builder — only where the font carries **no** `/ToUnicode`, on the stated ground that
> the CMap parse is unratified work at this seam. That ground is what this ADR removes, so
> the walk establishes **every** font in a parse's resource context, and the parse it
> thereby performs is the establishing parse §3 requires. **#2043's first residual closes
> as a consequence of this decision and not as a separate repair**: a font carrying a
> `/ToUnicode` that the extraction cannot build no longer lets the content stream be
> charged, so that document stops being refused `TOO_LARGE` where the extraction alone
> answers `EXTRACTION_FAILED`, and §7 arm 8 pins the class. **#2043's second residual is
> untouched and stays open** — a font program is still charged before the font is built,
> because ADR-0232 §3 requires the comparison to precede the work it bounds, and closing
> it would mean scanning a program before charging it, which is the property that makes
> the bound a bound.
