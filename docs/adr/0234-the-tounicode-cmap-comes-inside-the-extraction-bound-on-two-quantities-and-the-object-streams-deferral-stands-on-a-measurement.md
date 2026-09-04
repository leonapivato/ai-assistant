# 234. The `/ToUnicode` CMap comes inside the extraction's bound, on two quantities rather than one, and the object stream's deferral stands on a measurement

- Status: Proposed
- Date: 2026-09-04
- **Partially supersedes**
  [ADR-0232](0232-the-extractions-cost-is-bounded-on-decoded-bytes-and-the-file-bound-stays-the-files-own-size.md)
  — **its exclusion of a font's `/ToUnicode` CMap from the extraction bound, and the
  one-field shape that exclusion held up.** Four clauses move, all about the same
  question. §2's *"The decoded inputs an extraction reads **once and caches** … are **not
  bounded by this ADR**, and no implementation, lane or later ADR derives a refusal
  criterion on them from this field"* keeps its `/ObjStm` half and loses its `/ToUnicode`
  half: §1 below charges that CMap's decoded bytes to `fetch_max_decoded_bytes`, per
  parse. §3's *"Nothing else is counted, and that is a boundary rather than a gap"*
  names the CMap in its enumeration of what is not counted, and that name comes out.
  §8 arm 11's second arm requires a document whose large `/ObjStm` **and** whose large
  `/ToUnicode` CMap both sit inside `fetch_max_file_bytes` to **fetch**, *"neither
  charged"*; §8 below replaces the CMap half of that arm and keeps the `/ObjStm` half
  verbatim. And §10's fifth deferral — the once-and-cached class — loses its
  `/ToUnicode` half, which the 2026-09-04 note on that ADR already recorded as **fired**;
  §7 below re-states its `/ObjStm` half on the measurement it was missing.
  **§2's one-field decision moves too, and that is the larger half of this
  supersession**: §2 rules that `Settings` gains *"**one** field"* bounding the decoded
  bytes an extraction parses, and §2 below adds a **second**, on a quantity that is not
  bytes, because the CMap's cost is a function of two quantities and neither is a
  function of the other. **Everything else in ADR-0232 stands**, and most of it is
  load-bearing here: §1's file bound, §2's counted-per-parse rule and its 1 MiB figure,
  §3's walk and its agree-with-the-extraction standard, §4's single `TOO_LARGE` class and
  closed five-member enumeration, §5's refusal of a deadline, §6's evidence-about-a-version
  rule, §7's untouched audit, and §9's footprint. §11 below shows the working under
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
  would add *"unratified work"* to the seam. This ADR is what ratifies it. Two residuals
  Lane G stated and filed as #2043 — a font *with* a `/ToUnicode` that is unbuildable
  letting the content stream be charged — close as a consequence rather than as a
  separate repair.
- **`prepare_cm` reads a stream or synthesises a constant.** Where `/ToUnicode` resolves
  to a `StreamObject` it calls `get_data()`; otherwise it uses a fixed 43-byte literal
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
