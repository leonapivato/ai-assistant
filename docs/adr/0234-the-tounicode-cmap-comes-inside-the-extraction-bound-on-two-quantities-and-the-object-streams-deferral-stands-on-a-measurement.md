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

A factor of about **5,200**, and the cost follows the mappings rather than the bytes: at
50,000 mappings the 178-byte CMap costs 0.080 s per page against 0.162 s for a 713 KB
`bfchar` one, a difference of two where the byte counts differ by four thousand, and the
byte term accounts for about 0.003 s of it.

**The consequence for a byte charge is arithmetic, and it was built and run rather than
reasoned about.** A 225-byte CMap declaring 90,000 mappings costs **0.147 s per page**.
Two thousand pages sharing that font is a **568 KB** file that `extract_text` spends
**279 s** on — four and a half minutes, for a document that yields no text at all — and
its byte charge is **450,000**, under half `fetch_max_decoded_bytes`'s 1 MiB default. **A
byte charge on this input is the false promise ADR-0232 was written to end**, one input
over: a number that looks like a bound, is checkable, and is not a function of the cost it
claims to bound.

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
  declaring two mappings, and parses that literal on every font-build. Nothing is decoded
  for it — so there is no decoded length to charge — but the two mappings are built as
  often as the document asks for a font-build, which is a number the document controls
  entirely.
- **The number of font-builds is itself an amplifier, and bounding it is not this ADR's
  to do.** One font object under a thousand resource names, on fifty pages, is fifty
  thousand `Font.from_font_resource` calls from a **608 KB** file: **3.08 s** where those
  fonts carry a name-valued `/ToUnicode`, and **5.23 s** where they carry none at all and
  no `/FontFile` either — about 62 to 105 µs a build, of which the `/ToUnicode` parse is a
  small part. §1 below charges the mappings, which bounds the first class loosely; the
  second is charged nothing by ADR-0232 or by this ADR. §9 records that quantity's
  deferral as **fired by this measurement** and routes it to #2060, which is the treatment
  the 2026-09-04 note on ADR-0232 gave the `/ToUnicode` half this ADR now closes.
- **The mappings a parse builds are not the dictionary that survives it.** A CMap whose
  ranges overlap in their source codes declares more mappings than it leaves keys: 90,000
  declared through `bfrange` lines that wrap the two-byte code space builds 90,000 and
  leaves a dictionary of 65,536. `_check_mapping_size` counts the former, `Font`'s
  `character_map` carries the latter, and only the former is what the build costs.
- **`pypdf`'s own mapping ceiling is a raise that reaches this seam.** A CMap declaring
  131,072 mappings raises `LimitReachedError` out of `extract_text`, so `_extract_pdf`
  already answers `EXTRACTION_FAILED` for it. §3 below is why that matters: the walk's
  establishing parse meets the same raise and answers the same class.
- **The object stream really is resolved once.** Instrumented on this machine, a document
  whose page font lives inside a 2 MB `/ObjStm` calls `PdfReader._get_object_from_stream`
  **once** at 1, 5, 20 and 50 pages — the count does not move with the page count,
  because `_get_object_from_stream` parses every object in the stream in one pass and
  caches each, and `get_object` consults that cache first. §6 below is that measurement
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

> **Normative.** A `/ToUnicode` that is **not** a stream is charged **nothing** on
> `fetch_max_decoded_bytes` and **two mappings, per font-build,** on
> `fetch_max_character_mappings`. `prepare_cm` reads no stream for that case — it
> synthesises a fixed 44-byte literal, a single `beginbfrange` line spanning `<0000>` to
> `<0001>` — so nothing is decoded and there is no decoded length to charge. But it
> **parses** that literal and builds its two mappings on every font-build, and the number
> of font-builds is a quantity the document controls entirely: the size of the literal is
> the library's, the number of times it is parsed is the file's. §2's stated quantity is
> the mappings the extraction **builds**, and these are built.

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
> - **`fetch_max_character_mappings`**, default **400,000** — the `/ToUnicode` mappings
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
argument invites.** CMap bytes are cheap against operator bytes — about 0.004 s per
decoded MB per page against about 1.4 s per MB for `Tj` operators, a factor near 360 —
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

> **Normative.** **The count is charged once for every font-build the extraction will
> perform — per font entry, per parse — and never once per parse.**
> `PageObject._extract_text` builds **every entry** of the `/Font` resource dictionary, so
> two font dictionaries in one resource context naming the **same** `/ToUnicode` stream
> make the extraction parse that CMap **twice** on that page, and both are charged. The
> count is a property of the stream and the charge is a property of the build; an
> implementation charging one CMap once per page would disagree with the extraction about
> which parses happen, which ADR-0232 §3 forbids. The byte charge of §1 is per font entry
> per parse for the same reason and by the same reading of the same loop.

> **Normative.** **The walk parses a distinct `/ToUnicode` stream at most once for the
> count and at most once for each distinct font naming it, per fetch — and never once per
> parse.** Two memos, because two questions are being asked of the same bytes and neither
> answer serves the other: the **count** is `_parse_to_unicode`'s pre-deduplication tally,
> which `Font.from_font_resource` does not expose — it keeps only the surviving
> `character_map`, 65,536 keys where 90,000 mappings were built — and the
> **font-establishment outcome** is the whole of `from_font_resource`, of which the CMap
> parse is one step. So the walk asks `_parse_to_unicode` once per stream and
> `from_font_resource` once per font, both memoised for the fetch, and a CMap named by F
> distinct fonts is parsed by the walk at most **F + 1** times against the extraction's F
> times **per page**.

> **Normative.** **What is fixed here is the ceiling, not the instrument.** A lane that can
> obtain the font-establishment outcome and the pre-deduplication count from **one** parse
> — a later version exposing the tally, or an interface this ADR does not know of — may do
> so, and satisfies this section better. What no implementation may do is ask either
> question once per **parse** rather than once per fetch, which is the multiplier this
> bound exists to refuse.

> **Normative.** **The font-establishment memo is sound because its outcome is a function
> of the font dictionary alone** — the extraction builds the same font from the same bytes
> on every page and fails or succeeds identically — so a walk that asks once and remembers
> agrees with it exactly where a walk that asks every time does. ADR-0232's implementation
> asks per parse, which cost nothing while the CMap was excluded and would cost the whole
> of this bound's multiplier once it is not: a font established on forty pages would have
> its CMap parsed forty times by the walk on top of the forty the extraction pays.

> **Normative.** **The order is fixed, and it is what makes the walk's own parses
> affordable.** For each font **entry** in a parse's resource context whose `/ToUnicode`
> resolves to a stream, the walk (a) decodes that stream and charges its length to
> `fetch_max_decoded_bytes`, (b) compares that total and refuses the moment it is passed,
> (c) takes the mapping count, parsing the stream for it only if this fetch has not already
> counted this stream, (d) charges that count to `fetch_max_character_mappings`, (e)
> compares that total and refuses the moment it is passed, and (f) establishes the font
> itself (§4), parsing it only if this fetch has not already established this font entry.
> No implementation compares a sum over several fonts' charges afterwards, none counts a
> stream before its bytes have been compared, and none establishes a font before its
> CMap's mappings have been.

> **Normative.** **The residual this leaves is one establishing parse past the bound, and
> it is stated rather than argued away.** Obtaining a CMap's mapping count requires parsing
> it, so the parse that crosses `fetch_max_character_mappings` has completed before the
> comparison that refuses it. What bounds the parses *before* it is the bound itself: every
> font-build the walk establishes has already had its CMap's bytes and mappings charged to
> the two running totals, so across a whole fetch the walk's own establishing parses build
> at most **twice** what `fetch_max_character_mappings` admits, plus one font's worth — F
> font-establishments and one count parse over a CMap whose F charges are already inside
> the bound. The same arithmetic bounds their byte term against `fetch_max_decoded_bytes`. What
> bounds that one CMap is the adopted version's own `MAPPING_DICTIONARY_SIZE_LIMIT` and
> nothing this project declares — evidence about a version (ADR-0232 §6), disclosed here
> in the same posture and for the same reason ADR-0232 §3 discloses the 75 MB per-stream
> decode ceiling behind its own residual. On the resolved version that residual is
> **100,000 mappings, about 0.32 s**; on a version that raised the ceiling it would be
> larger, and this ADR states that rather than resting a figure on it. **The establishing parse's other half is bounded
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

> **Normative.** **A CMap over the adopted version's own mapping ceiling therefore reaches
> the same class through the walk that it reaches through the extraction, and this is
> checked rather than assumed.** `_check_mapping_size` raises `LimitReachedError`, and that
> raise **propagates out of `extract_text`** — measured here on a CMap declaring 131,072
> mappings — so `_extract_pdf`'s own `except` answers `EXTRACTION_FAILED` for that document
> today. The walk meeting the same raise answers the same class, so no document changes
> class on account of this ADR's establishing parse. This is a fact about the resolved
> version and is re-established by the lane (§8), not a bound this ADR states (ADR-0232
> §6).

**ADR-0232 §3's refusal-precedes-the-work property is kept, and the reading that says
otherwise is worth answering here rather than in a review round.** §3's clause is *"the
total is compared before the operators it counts are parsed"* — a statement about the
**extraction's** work, which is what the bound exists to refuse, and it holds exactly: a
document over either field is refused with `extract_text` never entered, so not one of the
per-page mapping builds this section counts is ever paid. What precedes a comparison is
the **walk's** own establishing parse, and walk-side work preceding its own comparison is
not a departure from §3 but the residual §3 already states for its own charge: *"Obtaining
a stream's decoded length requires decoding it … so one stream's decoded bytes are
materialised before the comparison that refuses them."* The shape is identical, one
quantity over — the count cannot be had without the parse any more than the length can be
had without the decode — and the clause above bounds this one where §3 could only disclose
its own.

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
walk and once by the extraction. Here the walk parses a CMap named by F distinct fonts at
most **F + 1** times for the whole fetch, where the extraction parses it F times **per
page** — so on a one-page document the walk pays one parse more than the extraction, and
on every longer one it pays less, by the page count. It is the multiplier this ADR exists
to bound that the walk does not pay; and on a refused document the extraction never runs
at all.

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
> answers `EXTRACTION_FAILED`, and §7 arm 9 pins the class. **#2043's second residual is
> untouched and stays open** — a font program is still charged before the font is built,
> because ADR-0232 §3 requires the comparison to precede the work it bounds, and closing
> it would mean scanning a program before charging it, which is the property that makes
> the bound a bound.

### 5. The two figures, and the ordinary documents they refuse

> **Normative.** **`fetch_max_decoded_bytes` stays at 1 MiB** and this ADR does not move
> it. ADR-0232 §2's arithmetic for that figure is untouched by anything here: it is sized
> against the instruction side, where a megabyte of operators is seconds, and a figure
> sized to admit a font input is not a bound on operators at all. §2's own measurement of
> raising it stands — 8 MiB multiplies the instruction worst case by about thirty-eight,
> and 16 MiB readmits #2022's document whole.

> **Normative.** **`fetch_max_character_mappings` is 400,000.**

**Where the mapping figure comes from, stated as arithmetic rather than as a feel.**

**The cost side is the measurement, taken across every form `pypdf` will build a mapping
from**, because the per-mapping cost differs by form and a figure has to hold for the
dearest. Fifty thousand mappings in each form, shared across pages, `pypdf` 6.16.2, best
of three:

| CMap form | bytes for 50,000 mappings | marginal s/page | per mapping |
| --- | --- | --- | --- |
| `bfchar`, one line per mapping | 713,131 | 0.162 | **3.24 µs** |
| `bfrange`, range lines | **178** | 0.080 | 1.60 µs |
| `bfrange`, bracketed destination lists | 372,131 | 0.094 | 1.87 µs |

At the dearest form, 400,000 mappings is about **1.30 s** of dictionary build — against
about **1.4 s** for the megabyte of `Tj` operators that `fetch_max_decoded_bytes`'s own
default admits — 1.41, 1.44 and 1.47 s across three separate runs on this machine,
reproducing ADR-0232 §2's *"1 MB of operators → 1.2 s"* to within the machine. **The two bounds' worst cases are matched deliberately**: an operator who has
accepted one has accepted the other, which is what makes a second figure defensible at all.
It is a matching and not a derivation — §2 above forbids computing either from the other,
and an operator who moves one moves nothing else.

**The legitimacy side is that for the form a real subset font is written in, the byte bound
binds first — so this figure refuses nothing the other admits.** A `bfchar` CMap carries
about one mapping per **14.4** bytes, so a byte total inside 1 MiB implies a mapping total
under about **73,000**, a fifth of the figure. This bound exists for the **range** form,
where 178 bytes buy 65,000 mappings and the byte total says nothing whatever about the
cost. That is the same shape of ratio ADR-0232 §2 drew against `fetch_max_content_bytes`,
computed the other way round: not what the figure admits, but what the sibling bound has
already refused before this one is consulted.

**What the two figures refuse together, measured.** Each document was built and run through
`pypdf` on this machine; the charges are what §1 and §2 above would count.

| document | on disk | byte charge | mapping charge | at the defaults | `extract_text` |
| --- | --- | --- | --- | --- | --- |
| 20 pages, one 1,000-mapping CMap | 9,949 | 287,820 | 20,000 | admitted | 0.068 s |
| 40 pages, one 1,000-mapping CMap | 15,490 | 575,640 | 40,000 | admitted | 0.134 s |
| 100 pages, one 1,000-mapping CMap | 32,323 | 1,439,100 | 100,000 | **refused** (bytes) | 0.366 s |
| 40 pages, one 3,000-mapping CMap | 24,136 | 1,716,440 | 120,000 | **refused** (bytes) | 0.388 s |
| 40 pages, two 3,000-mapping CMaps | 37,369 | 3,432,880 | 240,000 | **refused** (bytes) | 0.778 s |
| 40 pages, one 10,000-mapping CMap | 53,571 | 5,709,240 | 400,000 | **refused** (bytes) | 1.356 s |
| 300 pages, one 2,000-mapping CMap | 92,733 | 8,595,300 | 600,000 | **refused** (both) | 2.049 s |
| 2,000 pages, one 225-byte 90,000-mapping CMap | 568,376 | **450,000** | 180,000,000 | **refused** (mappings) | **279.41 s** |

**The last row is this ADR in one line.** A file of 568 KB that costs four and a half minutes charges
**450,000 bytes** — under half the byte default — and nothing but the mapping figure
catches it. Its escalation was measured across the range rather than extrapolated: **1.62 s
at 10 pages, 14.73 s at 100, 72.56 s at 500, 193.05 s at 1,000 and 279.41 s at 2,000** —
0.14 to 0.19 s a page throughout, best of three at each point. It is the page count that
carries it, and the page count is bounded by nothing but the file bound: two thousand pages
of this shape is 568 KB on disk against a 4 MiB default.

**The refused ordinary class is real, and it is chosen rather than overlooked.** A
forty-page document carrying one 3,000-mapping subset font — 24 KB on disk, an entirely
ordinary shape — is **refused**, on the **byte** figure: 43 KB of CMap charged forty times
is 1.7 MiB. Two things are true of that and both belong on the page. It is a **larger**
over-refusal than ADR-0232 §2's, because CMap bytes cost about **0.004 s per decoded MB
per page** against about 1.4 s per MB for operators — a factor near **360**, where the font
program's was 120. And it is a **smaller** one in the currency that decides whether an
over-refusal is tolerable: §2 accepted refusing a thirty-page paper that cost **37 ms**,
and this document costs **0.388 s**, ten times more. The trade is §2's, made again on the
same reasoning, with the numbers rather than a feel behind it.

**Which figure refuses that class is worth seeing, because it is an argument for the fix
§9 defers rather than against charging the bytes.** That document's cost is almost entirely
its mapping term: 120,000 mappings at 3.24 µs is 0.389 s against a measured 0.388 s, so its
byte term is under a hundredth of a second. The byte charge over-states its cost about
fifty-fold; the mapping charge tracks it to three figures. **The byte term is charged
anyway because it is separately amplifiable** — held at 1,800 mappings, a CMap's per-page
cost still runs 0.006 s at 25 KB to 0.037 s at 8 MB, and at the 75 MB a stream may decode
to it is a third of a second a page that the mapping figure never sees. A quantity that
reaches minutes on a document a file bound admits is charged, and ADR-0232 §2's *"A
per-byte cost is not the test"* is the clause that says so.

**Raising either figure was measured and is worse.** ADR-0232 §2 measured raising
`fetch_max_decoded_bytes` and rejected it, and nothing here changes that arithmetic. Raising
`fetch_max_character_mappings` buys linearly and is therefore easy to reason about — 1 M
mappings is about 3.2 s, 4 M about 13 s — which is exactly why an operator raising it should
be doing so against ADR-0230 §9's audit rather than against a lane's estimate; §9 defers
that and says what fires it.

**For a document that was going to refuse anyway, only the price changes.** The 2,000-page
row spends four and a half minutes inside `extract_text` today and yields no text at all; under these
bounds it is refused before its first page is parsed, in milliseconds, as `TOO_LARGE`.

### 6. The object stream stays uncharged, and that deferral now rests on a measurement

> **Normative.** A compressed **object stream** (`/ObjStm`) is **not** charged to
> `fetch_max_decoded_bytes`, is **not** charged to `fetch_max_character_mappings`, and no
> implementation charges it to either. ADR-0232 §10 defers it and this ADR re-states that
> deferral rather than firing it.

> **Normative.** The ground is now **measured** rather than assumed, and it is the ground
> ADR-0232 §10 stated for both halves of its class: **no per-parse multiplier acts on it.**
> `PdfReader._get_object_from_stream` parses every object in a stream in one pass and
> caches each through `cache_indirect_object`, and `get_object` consults that cache before
> it reaches the stream at all. Instrumented against `pypdf` 6.16.2 on a document whose
> page font lives inside a 2 MB `/ObjStm`, `_get_object_from_stream` is entered **once** at
> 1, 5, 20 and 50 pages — flat where the CMap's per-page cost is linear, which is the
> whole of the difference between the two halves of ADR-0232 §10's class.

> **Normative.** **The residual is stated and is unchanged from ADR-0232 §10's.** A small
> compressed `/ObjStm` can expand to tens of MiB during indirect-object resolution, before
> any per-page loop and so before any total this bound keeps exists; `fetch_max_file_bytes`
> bounds the bytes **read from disk** and does not bound that expansion, which is bounded
> at 75 MB per stream by a ranged dependency and by nothing this project declares
> (ADR-0232 §6). Once per fetch, and unbounded in size.

> **Normative.** **What fires it is unchanged, and this ADR neither widens nor narrows
> it**: a measurement showing it re-read or re-parsed per page, or per any other quantity a
> document controls; or an adopted release whose parse order changes such that it is parsed
> as instructions or is reached from inside the walk. **Not** fired by the observation that
> it exists and is decoded, and not by this ADR having fired its sibling — which is the
> reading a later lane is most likely to take, and the measurement above is why it is
> wrong.

**Why this half genuinely differs, in one sentence, so a reader does not have to trust the
symmetry breaking.** The CMap is rebuilt because `_extract_text` rebuilds a stream's fonts
on every call and nothing caches the parse; the object stream is resolved through a cache
keyed on the object number, so the second page's font lookup never reaches the decode. The
two inputs sat in one deferral because one sentence covered both, and only one of them was
ever true.

### 7. The representative-input tests this decision owes

> **Normative.** The implementing lane owes a test for each of the following, each over
> behaviour rather than over a call count, in ADR-0230 §14's form. **ADR-0232 §8's preamble
> governs every one of them**: each refusal arm asserts that the parse was not entered —
> `pypdf`'s own `PageObject.extract_text` not called for the crossing page — and **none**
> asserts a wall-clock duration. Every arm runs with the bounds it is not about set high
> enough that only the one under test can decide it.

1. **A CMap-carried amplification is refused, and the charge is per font-build.** A document of
   many content-free pages sharing **one** font with a large `/ToUnicode` CMap is refused
   `TOO_LARGE`, with `extract_text` not called for the crossing page. **This is the arm
   that fails on any implementation charging a distinct CMap a single time**, and it fails
   on any implementation charging no CMap at all. Pinned from both sides: the same document
   at one page fetches.
2. **The mapping term is bounded where the byte term cannot reach it.** A document whose
   `/ToUnicode` is a few hundred bytes, declares tens of thousands of mappings through
   `bfrange` range lines, and is shared across enough pages that the mapping total passes
   `fetch_max_character_mappings` while the byte total sits far inside
   `fetch_max_decoded_bytes`, is refused `TOO_LARGE`. **This is the arm that fails every
   byte-only implementation**, including one that charges the CMap's bytes faithfully, and
   it is the arm this ADR's second field exists for. It runs with `fetch_max_decoded_bytes`
   raised, so that only the mapping bound can decide it.
3. **The byte term is bounded where the mapping term cannot reach it.** The converse: a
   `/ToUnicode` of megabytes declaring a few thousand mappings, shared across enough pages
   that the byte total passes `fetch_max_decoded_bytes` while the mapping total sits far
   inside `fetch_max_character_mappings`, is refused `TOO_LARGE` with
   `fetch_max_character_mappings` raised. **This is the arm that fails a mappings-only
   implementation.** Arms 2 and 3 together are what pin the two fields as two.
4. **The count is the mappings built, not the dictionary that survives.** A CMap whose
   ranges overlap in their source codes, so that the mappings built exceed the surviving
   dictionary's size — 90,000 built against 65,536 kept, measured — is refused at a
   `fetch_max_character_mappings` set between the two counts. **This is the
   arm that fails an implementation taking the size of the surviving dictionary** — the
   quantity `Font.character_map` carries and the obvious thing to reach for — which
   under-charges exactly the document that declares the most.
5. **A name-valued `/ToUnicode` is charged its two mappings and no bytes, both ways.** Two
   arms. A document whose pages carry many font entries with a **name**-valued
   `/ToUnicode` — one shared font object under many resource names, so the extraction
   builds it once per name per page — is **refused** `TOO_LARGE` at a
   `fetch_max_character_mappings` just under twice its font-build count and **fetches**
   just at it, with `fetch_max_decoded_bytes` raised so only the mapping bound can decide
   it. **This is the arm that fails an implementation exempting a non-stream
   `/ToUnicode`**, and the boundary is exactly two mappings a build. And the same document
   at a raised mapping bound fetches with **nothing** charged to
   `fetch_max_decoded_bytes` for those fonts — the arm that fails an implementation
   charging the synthesised literal's bytes, which are never decoded.
6. **The predicate is `/ToUnicode` present, in both directions.** Two arms. A font carrying
   a `/ToUnicode` and a `/Subtype` that is **not** `/Type1` **is** charged — the arm that
   fails any implementation carrying ADR-0232 §3's three-key font-program predicate over to
   this input. And a font carrying **no** `/ToUnicode` is charged no CMap, its font-program
   charge unchanged, which is ADR-0232 §8 arm 10 still passing.
7. **Two fonts sharing one CMap are charged twice.** A page whose resource context carries
   two font dictionaries naming the **same** `/ToUnicode` stream is refused at a
   `fetch_max_character_mappings` set between one and two times that CMap's count, and
   **fetches** just above twice it. `PageObject._extract_text` builds every entry of the
   `/Font` dictionary, so it parses that CMap once per entry; **this is the arm that fails
   an implementation charging a CMap once per parse rather than once per font-build**,
   which under-charges by the number of fonts sharing it and is the reading §3 forbids.
8. **A font the operators never select is charged.** A page whose resource context carries
   a second font with a large CMap that no `Tf` names is refused `TOO_LARGE`. This is the
   arm that fails an implementation charging only the fonts the content stream selects,
   which would under-charge every parse: `_extract_text` builds the whole `/Font`
   dictionary before it resolves the content key.
9. **An unbuildable `/ToUnicode` font is `EXTRACTION_FAILED`, not `TOO_LARGE`.** A document
   whose font carries a `/ToUnicode` and a structure that makes the extraction's own font
   initialisation raise something it would not swallow is refused **`EXTRACTION_FAILED`**,
   with no record added and no turn failed. This is #2043's class, closed by §4's
   unconditional establishment, and the arm that fails an implementation keeping the
   `/ToUnicode` exclusion.
10. **The boundary value, both ways, for the new field.** A document whose mapping charge is
   exactly `fetch_max_character_mappings` extracts, and one mapping over is refused
   `TOO_LARGE`.
11. **A document inside every bound is unaffected.** A document of a few pages carrying an
    ordinary `/ToUnicode` CMap fetches, its text reaching the record whole and the reply
    carrying it, with no bound having refused anything.
12. **ADR-0232 §8 arm 11's `/ObjStm` half stands and its CMap half is replaced.** The
    `/ObjStm` arm is unchanged and stays a **fetch** arm: a document whose large `/ObjStm`
    sits inside `fetch_max_file_bytes` fetches, uncharged, which is §6 above. The CMap half
    becomes two arms: the same document's large `/ToUnicode` makes it **refuse** at the
    defaults, and it **fetches** with both of this ADR's figures raised — which is the
    boundary this ADR draws where ADR-0232 drew the other one, and the clause a later
    reader is most likely to widen back.
13. **The refused ordinary class is pinned, so that raising a default stays a decision and
    not a discovery.** The document §5 names as refused at the defaults is **refused**
    `TOO_LARGE`, and **fetches** at a figure §5 names. This is the arm that records the
    cost §5 accepts.
14. **An out-of-domain bound does not load.** A zero and a negative value of
    `fetch_max_character_mappings` is refused when `Settings` is constructed, before any
    fetcher is built and before any filesystem call — a configuration error that stops the
    deployment rather than an empty listing, a `FetchRefusal` or a degraded turn. This is
    ADR-0230 §14 item 21's arm, extended by one further field and asserted in its form.
15. **The enumeration did not grow.** `FetchRefusal` has five members, and the audit event
    for arm 1's turn carries `TOO_LARGE` and no field naming a bound, a count or a size.

> **Normative.** This ADR adds **no clause to the `Fetcher` conformance suite and no
> parameter to the canonical fake**, for ADR-0232 §8's own reason: the bound is enforced
> inside a concrete extraction, and a fake that performs no extraction has nothing to
> bound.

### 8. What the implementing lane owes

> **Normative.** **One lane**, briefed from this ADR's merged text, landing after
> ADR-0232's implementing lane — which merged as PR #2037 — and before milestone 29's exit
> probe runs against a configured documents root. It is a **follow-on to that lane and not
> a reopening of it**: nothing here re-decides the library, the triad, the fetcher, the
> composition, or ADR-0232 §3's walk.

> **Normative.** Its footprint is `src/ai_assistant/core/config.py` (the one field, its
> named default, its stated domain and its load-time refusal),
> `src/ai_assistant/app/composition.py` (`_build_local_file_fetcher` passing that figure to
> the fetcher beside the others — without it an operator's configured value reaches
> `readers` never, and the bound is a field nothing enforces),
> `src/ai_assistant/readers/_extract.py` (the CMap charges, the count-establishing parse
> and the two per-fetch memos §3 requires, the removal of `_establish_font`'s
> `/ToUnicode` exclusion, and
> `_extract_pdf`'s docstring, whose statement of what is charged and what is not is
> restated for this decision — ADR-0232 §6), `src/ai_assistant/readers/files.py` (threading
> the figure from the fetcher to the extraction), `src/ai_assistant/core/types.py` (**one
> docstring**, below), and tests under `tests/readers/`, `tests/core/` and `tests/app/`.
> `core/protocols.py` is untouched and neither `PROTOCOL_VERSION` nor
> `PlanExport.schema_version` moves.

> **Normative.** **The `core/types.py` change is `FetchRefusal.TOO_LARGE`'s docstring and
> nothing else.** That docstring enumerates the member's causes and counts them — *"The
> file exceeded `fetch_max_file_bytes`, its extracted text exceeded
> `fetch_max_content_bytes` (§6), or its extraction's decoded bytes exceeded
> `fetch_max_decoded_bytes`"*, and twice *"the three bounds"* / *"which of the three"* —
> and §2 above adds a fourth, so leaving it would put a false enumeration and a false count
> on the contract a consumer reads. **No member is added, no field, no validator, no
> serialised form and no annotation**, so nothing a wire, a schema or a stored document can
> see moves. This edit is golden rule 5's *"A Protocol change is a breaking change … its
> ADR is ratified and merged as its own PR before anything implements against it"*
> satisfied rather than excepted: **this** is that ADR, and the lane makes the edit under
> it.

> **Normative.** The lane **re-establishes, against the version `uv.lock` fixes**, that
> every font in a parse's resource context is built before the content key is resolved,
> that `prepare_cm` reads a stream and otherwise synthesises a constant, and that the
> object stream is resolved once per fetch (§6) — and records what it found at the code, in
> `_extract_pdf`'s docstring, as ADR-0232 §6 requires of the sets it already establishes.
> This ADR's figures are a measurement of one version and are never the establishment.

**It is one lane under ADR-0137 §1.** The substantial new machinery is in `readers/`;
`core/config.py` gains one field with its validator and `core/types.py` one docstring,
which is the *"a call site updated, an argument threaded through"* shape §1's carve-out
covers rather than a second subsystem's worth of machinery. It is the same classification
ADR-0232 §9 made for the same shape.

**The change inside `readers/` is smaller than the last one.** ADR-0232 §3's walk already
resolves each parse's inherited resources and enumerates that context's `/Font` dictionary;
this adds a charge and an establishment at a point the walk already stands at, plus the
two per-fetch memos §3 requires — one on the font, one on its CMap stream.
`_establish_font` loses a condition rather than gaining one.

### 9. Deferred, by name, each with what fires it

- **The object stream.** §6 above, with its measured ground and its unchanged firing
  conditions. This is ADR-0232 §10's fifth deferral with its `/ToUnicode` half removed and
  its `/ObjStm` half re-grounded.
- **Telling an operator which bound refused.** ADR-0232 §10's first deferral, now over
  **four** bounds rather than three, so ADR-0230 §9's per-kind refusal rate says *a* bound is set
  below this deployment's documents and not which. Its firing condition is unchanged and
  this ADR does not make it more urgent by arithmetic alone.
- **Raising either default on evidence.** ADR-0232 §10's fourth deferral, extended to
  `fetch_max_character_mappings`. Both figures are chosen from measured parse densities and
  a ratio against a bound already ratified, with **no corpus of real documents** behind
  either. Fired by ADR-0230 §9's audit showing `TOO_LARGE` on a deployment's ordinary
  documents; not by a lane's estimate of what a real PDF costs.
- **The ordinary documents these bounds refuse, and the extractor change that would
  re-admit them.** ADR-0232 §10's sixth deferral, whose subject widens from the `/Type1`
  font program to the `/ToUnicode` CMap as well, because it is the same defect through the
  same call: `_extract_text` rebuilds a stream's fonts on every call. Closing it means the
  extraction parsing each font **once per fetch** rather than once per page — a cache the
  extractor holds across a document's pages, or an adopted version that does not rebuild.
  Either removes the multiplier from **both** charges at once, at which point each falls to
  one program and one CMap per distinct font and both classes fetch at the present
  defaults. **Fired by** that audit, or by a `pypdf` release that stops rebuilding fonts
  per page. Not fired by raising a default, which §5 measures and rejects for the same
  reason ADR-0232 §2 did.
- **The number of font-builds an extraction performs — recorded here as *already fired*,
  by this ADR's own measurement, and carried by #2060.** Fifty thousand builds from a
  608 KB file cost **3.08 s** with a name-valued `/ToUnicode` and **5.23 s** with none at
  all, at 62 to 105 µs a build; most of that is not the `/ToUnicode` parse but `/Encoding`
  resolution, the width tables and the rest of `Font.from_font_resource`, which is why the
  row with no CMap is the dearer. §1's two-mapping charge bounds the first class
  **loosely** and says so — at the default it admits 200,000 builds, about 12 s, where the
  figure is sized to be worth 1.3 s — and it bounds the second **not at all**: a font with
  no `/ToUnicode` and no `/FontFile` is charged nothing by ADR-0232 §3 and nothing here,
  and its builds are limited only by `fetch_max_file_bytes`. That is a class reaching
  seconds with every field of both ADRs at zero, so **there is no firing condition left to
  write** — the condition is met on the page it would have been written on. **Firing a
  deferral is not itself a decision.** Bounding this is a **fourth quantity** —
  font-builds, whose consumer is the font builder — needing its own `Settings` field, its
  own argued default and its own arms, and it is a new refusal criterion, which ADR-0015
  puts in an ADR rather than in a lane. This ADR does not make that decision, for the same
  reason it is the one making the `/ToUnicode` decision the 2026-09-04 note on ADR-0232
  said was owed: **#2060 carries it**, with the measurement and what it has to decide.
- **A descent-depth bound for the form-invocation chain.** #2045 records that the walk
  descends further into a chain of Form XObjects than the interpreter's recursion limit
  lets the extraction descend, so between the two depths it charges forms the extraction
  does not parse — a residual in the sound direction whose closure needs a figure, a
  refusal class and its own arms. **This ADR does not reach it**: it is a property of the
  content-stream descent rather than of any font input, and nothing here moves either
  depth. Fired by what #2045 names.
- **A `fontTools` that becomes resolvable.** ADR-0232 §10's seventh deferral, unchanged.
  **This ADR's predicate does not depend on it**, which is worth stating because ADR-0232's
  font-program predicate does: `/ToUnicode` present is decided from the font dictionary
  whatever `pypdf._font.py`'s branch would do, and a resolvable `fontTools` would widen
  what ADR-0232 §3 charges without touching what §1 above charges.
- **A decoded input a later library version reads that this ADR does not charge.**
  ADR-0232 §10's eighth deferral, unchanged and now covering one input fewer: a new input
  read *once* falls to §6 above, one parsed as instructions is reached by ADR-0232 §3's
  walk, and one parsed **per page** through a route neither this ADR nor ADR-0232 names is
  what remains. Fired by a release doing it — which is why §8 above has the lane
  re-establish at the code rather than carry this ADR's findings forward.
- **Bounding the decompression this system performs**, and **an extraction run out of
  process under a kill deadline** — ADR-0232 §10's second and third deferrals, neither
  fired here and neither reached. §3's establishing-parse residual is a **parse** rather
  than a decompression and is bounded by §2's own field, so it does not fire the first.
- **A per-format decoded bound.** ADR-0232 §10's ninth deferral, unchanged; this ADR adds a
  second shared figure rather than a per-format one, and an ADR admitting a later format
  states what that format produces for **both** fields or that it produces nothing for
  either.
- **Any of ADR-0230 §15's deferrals.** None is fired here, and in particular this ADR
  admits no format, no second root, no recursion and no outward kind.

### 10. Scope, and what this records against ADR-0232

**This ADR partially supersedes ADR-0232 in one scope and records nothing against any
other ADR**, and that is a classification of this change and therefore prose rather than a
marked clause (ADR-0089 §1). What follows is the working under ADR-0070 §1's test and
ADR-0082 §1's, clause by clause.

**Why supersession and not amendment.** ADR-0070 §1 admits an in-place amendment only
where *"a reader acting on the ADR would act **identically** before and after"*. A reader
acting on ADR-0232 §2 and §3 today charges a `/ToUnicode` CMap **nothing** and is told in
terms that no later ADR may derive a refusal criterion on it from that field; after this
ADR they charge its bytes to that field and its mappings to another, and documents that
fetch today are refused. That is as direct a change to what was decided as the corpus
holds. It is **partial** because ADR-0232's other rulings survive whole, and ADR-0070 §3
makes that form first-class rather than a discouraged one. The 2026-09-04 note on ADR-0232
is not an alternative route: it fired a deferral and moved no decision, and says so — *"a
lane implementing §2 and §3 charges exactly the same bytes before this note and after
it"*.

**The clauses that move, and what moves in each.**

1. §2's *"The decoded inputs an extraction reads **once and caches** — for PDF, a
   compressed object stream and a font's `/ToUnicode` CMap — are **not bounded by this
   ADR**, and no implementation, lane or later ADR derives a refusal criterion on them from
   this field."* The `/ObjStm` half stands entire and is re-grounded in §6 above; the
   `/ToUnicode` half is replaced by §1. **The clause's premise is what failed**, not its
   reasoning: the sentence's own justification — *"What separates them from the font
   program is not their cost per byte but the absence of a per-parse multiplier"* — is the
   test this ADR applies, and it now comes out the other way for one of the two inputs.
2. §2's *"`Settings` gains **one** field"*, and with it ADR-0232's answer to the question
   its §1 poses — *"one number cannot be honest about both"*. §2 above adds a second, on a
   quantity that is not bytes. **What replaces the clause is narrower than a reader might
   expect and is stated so**: §2's field, its default, its domain, its per-parse rule, its
   naming clause and its independent-figure clause all stand and govern
   `fetch_max_decoded_bytes` unchanged; what moves is only the claim that one field is the
   whole of what this class needs.
3. §3's *"**Nothing else is counted, and that is a boundary rather than a gap.** Decoded
   inputs the extraction reads **once and caches** — for the adopted version, a compressed
   object stream and a font's `/ToUnicode` CMap — are **not** charged to this total, and no
   implementation charges them to it."* The same split: the `/ObjStm` name stays, the
   `/ToUnicode` name comes out. **The clause's ruling is not replaced but narrowed** — the
   separating property is still the per-parse multiplier and never the cost per byte, and
   §1 above charges the CMap on exactly that test rather than on how expensive its bytes
   are.
4. §8 arm 11's second arm — *"a document whose large `/ObjStm` and whose large
   `/ToUnicode` CMap sit inside `fetch_max_file_bytes` **fetches**, neither charged"*. §7
   arm 12 above keeps the `/ObjStm` half verbatim and replaces the CMap half with a
   refusal arm and a fetch arm at raised figures. Arm 11's **first** arm — the `/FontFile2`
   behind a normal `/ToUnicode` charged nothing — stands entire, and is worth saying
   because a careless reading of §1 above would take it: that arm is about the **font
   program**, which `Font.from_font_resource` resolves with `get_object()` and does not
   decode, and this ADR charges the **CMap** of exactly those fonts and still charges their
   program nothing.
5. §4's *"The class does **not** disclose which of the three bounds refused"*, whose
   enumeration becomes any of **four**. Its **ruling** is not replaced but extended, and it
   binds the new field entire: no field, no message and no second member discloses which
   bound a document passed. This is the same shape ADR-0232 recorded against ADR-0230 §6's
   *"A file over **either** bound"* clause rather than leaving it as arithmetic, and it is
   recorded here for the same reason.
6. §10's fifth deferral, the once-and-cached class, loses its `/ToUnicode` half — which the
   2026-09-04 note already recorded as fired — and its `/ObjStm` half is re-stated on a
   measurement in §6 above.

**Clauses a reader would expect to have moved, and which did not.** Each is checked
against ADR-0082 §1's test — *would a reader holding only ADR-0232 now act differently, or
read the clause more widely than it now holds?* — and each comes out **no**, so no separate
record is owed for it and stating that is the point of this paragraph.

- **§2's *"the counted quantity is bytes parsed, never bytes decoded"*.** It governs the
  CMap's byte charge exactly as it governs the font program's: a CMap parsed on forty pages
  is charged forty times. Nothing in it becomes false, and §1 above is an application of it
  rather than an exception to it.
- **§2's *"A per-byte cost is not the test"* clause.** It is the clause this ADR leans on
  hardest. The CMap's bytes are cheap — 0.037 s per page at 8 MB — and are charged anyway,
  because the test is whether the cost is a function of the quantity and the page count is
  the multiplier. Reading §1 above as a per-byte-cost judgement would get it exactly
  backwards.
- **§2's 1 MiB figure and its arithmetic.** §5 above does not move it, for the reason §2
  gives: it is sized against the instruction side, and a figure sized for a font input is
  not a bound on operators.
- **§3 entire, apart from the one clause above.** The walk, the agree-with-the-extraction
  standard, the resource-inheritance rule, the two named early exits, the `(Do)`-in-a-string
  clause, the stream-by-stream comparison, the running total, the fail-closed
  `EXTRACTION_FAILED` branch and the plain-text-counts-zero clause all govern this charge
  unchanged, and §1 and §3 above are stated inside them.
- **§4's other clauses.** `TOO_LARGE` rather than `EXTRACTION_FAILED`, no sixth member,
  the every-member-is-reachable ground and the disclosure posture behind it: none becomes
  false, and only the enumeration above moves.
- **§5 entire.** No deadline. §3 above's establishing parse is bounded by a byte and a
  mapping figure, not by a clock, and the determinism §5 rests on is untouched — the same
  document yields the same counts on any machine.
- **§6 entire.** Its normative clause is what forbids this ADR from arguing from
  `MAPPING_DICTIONARY_SIZE_LIMIT`, and Context above records that limit as evidence and
  argues from none of it. §6's *prose* explanation that the CMap is left uncharged because
  it is read once and cached is the false premise the 2026-09-04 note already corrected in
  place; it is unmarked text under ADR-0089 §3 and supplies no obligation, so nothing
  further is owed for it here.
- **§7 entire.** No audit field, no event, no key, no emission point.
- **§9 entire.** It charges a lane that has merged. §8 above charges a different lane, in
  the ADR that makes it — ADR-0082 §1's **stacked addition**, recorded here and nowhere
  else.
- **§11 entire.** Its working against ADR-0230 is a true account of what ADR-0232 did.

**Nothing is recorded against ADR-0230, and that is a judgement rather than an omission.**
ADR-0230 §6's *"**Two** size bounds"* clause and its four-field enumeration are the
sentences a fourth `Settings` field would make over-wide — and they are already inside the
scope ADR-0230's `Status` line records as partially superseded by ADR-0232, *"§6's account
of what bounds an extraction's cost"*. A reader resolving that clause is already sent to
ADR-0232, and from ADR-0232's own `Status` line to this ADR; the chain resolves, and a
second token on ADR-0230's line would name the same scope twice. **Nor is ADR-0232's
parenthesis on that line edited**, though it says the count *"becomes three"*: that text is
ADR-0232's account of ADR-0232's own change, it stays a true account of it, and rewriting
one supersession's record to reflect a later one would make the line a running total rather
than a record. ADR-0230 §4's *"Every
bound is re-applied at `fetch` and none is carried from the listing"* governs the new field
as it governs the other four and becomes neither false nor over-wide.

**Nothing is recorded against ADR-0093, ADR-0024, ADR-0015, ADR-0089 or ADR-0137.** Each is
cited for what it rules and none of their sentences becomes false: ADR-0093 §5 is applied
in the borrowed form ADR-0230 §6 already borrowed it; ADR-0024 §3 is cited for the
distinction it draws and is not extended to `pypdf`; ADR-0137 §1 classifies §8's lane and
is unaffected by the classification.

**Where the record lives.** ADR-0232's `Status` line reads `Accepted`, so it takes the
leading `Partially superseded by` token and the scope in the parenthesis, which is
ADR-0001's mechanism and the template's. **No appended dated note accompanies it**:
ADR-0070 §1's dated note is the append-only form of an **amendment**, and this is a
supersession — the same treatment ADR-0232 §11 gave ADR-0230, and the corpus's practice.
ADR-0232's own `Amended: 2026-09-04` note stays where it is and is untouched by this
change; it recorded a firing, and this ADR is what the firing said was owed.

**Milestone numbering.** #1908's milestones were renumbered globally on 2026-09-03
(*"1→27, 2→28, 3→29, 4→30"*), and this ADR uses **29** as ADR-0230 and ADR-0232 do.

**The charter caution (#1908) applies and is met.** Nothing here is justified by a
memory-benchmark number: the exits are task-shaped, and what this ADR buys is that a
document the loop is asked to read either fetches in bounded time or is refused as a class
an operator can act on.

## Consequences

**The claim ADR-0232 makes about a PDF extraction's cost becomes true of one more input,
and the input it is now false about is named.** A reader of ADR-0232 today is told the
CMap is unbounded because no per-parse multiplier acts on it; that sentence was wrong when
it was written, the 2026-09-04 note said so, and this ADR is what makes the corpus say
something true instead. What is left unbounded — the object stream, once per fetch and up
to a ranged dependency's 75 MB — is stated with a measurement behind it rather than an
assumption.

**A deployment gains a second figure to get wrong, and that is a real cost.** Four bounds
on a fetch is one more thing an operator has to understand, and §4's single `TOO_LARGE`
class means the audit still cannot tell them which one refused. The alternative was a
figure that does not bound what it claims to, and the deferral that would tell them which
bound refused is unchanged and named.

**Some documents that fetch today will be refused**, which is the whole point and is also
the harm. §5 names the class and measures it; §7 arm 13 pins it, so raising a default stays
a decision an operator makes rather than a discovery a lane makes.

**The walk gets cheaper for the documents it already handled, not more expensive.**
Establishing a font once per fetch rather than once per parse is a strict improvement on
what ADR-0232's implementation does, and it is forced by this ADR rather than optional
under it. The establishing CMap parse the walk now performs is one per distinct font per
fetch, against the extraction's one per page.

**#2043's first residual closes and its second does not**, so a document that is both
malformed in its `/ToUnicode` and over the bound stops being reported as a size refusal.
Nothing is owed for the second, which is untouched.

**Milestone 29's exit probe is not reached until this is implemented**, on the same
reasoning #2022's ruling applied to ADR-0232: a bound that is stated and not enforced is a
disclosure rather than a mechanism.

## Alternatives considered

**Charge the CMap's decoded bytes and nothing else.** The obvious reading of #2050, and the
one this ADR spent its first measurement on. It is refused because 65,000 mappings arrive
in 178 bytes as readily as in 927,031, so a byte charge admits the worst per-page CMap at
essentially no cost: a thousand pages of a 225-byte, 90,000-mapping font charge 21% of the
default and cost minutes. A number that looks like a bound and is not one is what ADR-0232
was written to end.

**One field, on notional units of work, with an exchange rate between bytes and mappings.**
Honest about the total, and refused on ADR-0232 §1's own ground: a bound is chosen by an
operator who has to be able to predict what it admits, and *work units* are visible
nowhere — not in a listing, not in a file manager, not in any field of any type — where
bytes are at least reasoned about. The exchange rate would also be a constant measured on
one machine, written into a contract, and wrong on the next one; §6's evidence-about-a-
version posture is the same objection one layer down.

**Establish the mapping count with a scan of the CMap's bytes rather than the library's
parse.** Cheaper, and it would remove §3's residual entirely. Refused as the
re-implementation ADR-0232 §3 forbids for content streams, in a grammar with more shapes
to get wrong than that one: PR #2037's rounds 3 to 5 are three successive attempts to
state one of this library's conditions from outside, each incomplete in one more place,
and the correction that ended them was to ask the library instead.

**Leave the deferral standing and fix the extraction instead.** Removing the per-page
rebuild is the end state — it would drop both this ADR's charges *and* ADR-0232's font
program charge to one per distinct font per fetch, and re-admit both refused classes at the
present defaults. It is not available here: `PageObject._extract_text` rebuilds a stream's
fonts inside a call this seam does not own, and a cache across that call means
re-implementing the extraction. §9 keeps it as the deferral with the largest payoff, with
what fires it.

**Lean on `MAPPING_DICTIONARY_SIZE_LIMIT` and charge nothing.** The per-page CMap cost
really is capped at about a third of a second by the adopted version, and about ten pages
of it is the 3.5 s the note measures. ADR-0232 §6 forbids exactly this, and forbade it once
already: an earlier draft of §3 used this same constant as the reason the walk need not
count a `/ToUnicode` stream, and the round that found it wrong is why §6 exists in the
shape it does.

**A per-page mapping bound.** Refused for ADR-0232 §3's reason, unchanged: it admits an
unbounded document made of bounded pages.
