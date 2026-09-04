# 232. The extraction's cost is bounded on decoded bytes, and the file bound stays the file's own size

- Status: Proposed
- Date: 2026-09-03
- **Partially supersedes**
  [ADR-0230](0230-the-planner-names-a-file-it-was-shown-and-the-loop-fetches-it-into-the-supply.md)
  — **§6's account of what bounds an extraction's cost, in one scope and no wider.**
  Three sentences move, all in §6 and all about the same question. Its size-bound clause
  reads *"`fetch_max_file_bytes`, the file's size on disk, default **4 MiB**, which
  bounds the read **and the extraction's cost**"*, and the second limb is replaced: that
  field bounds the read, and §2 below adds **one** `Settings` field bounding the decoded
  bytes an extraction parses **as content-stream instructions** — the superlinear
  quantity #2022 is filed about, measured at about 5 s per decoded MB. What replaces the
  limb is that narrower claim and no wider one: this ADR does **not** bound the decoded
  classes an extraction reads *linearly* — a compressed object stream, a `/ToUnicode`
  CMap, an embedded font program, each about 0.04 s per decoded MB — and §10 defers those
  **by name** with what fires them. The same clause
  opens *"**Two** size bounds"*, and the count becomes three. And the refuse-never-truncate
  clause reads *"A file over **either** bound yields a refusal and no record"*, whose
  enumeration becomes any of the three — its **ruling** is not replaced but extended, and
  it binds the new bound entire.
  **Everything else in §6 stands**, and most of it is load-bearing here: the one
  configured root and its unset default, the two-stage fail-closed eligibility, the
  listing's ordering, cap and type allow-list, `NOT_FOUND` for a type the rung does not
  read, `fetch_max_file_bytes` at 4 MiB as the file's size on disk bounding the read,
  `fetch_max_content_bytes` at 32 KiB counted on the quoted rendering while extracting,
  the stated-domain-and-load-time-refusal clause over the four fields ADR-0230 adds,
  refusing rather than truncating, the **closed five-member `FetchRefusal`** and its
  every-member-is-reachable clause, the resolved-outcome clause, the shape §6 fixes for
  the PDF adoption — in-process, no network, **deterministic for a given file**,
  `EXTRACTION_FAILED` rather than a raise — and off-until-configured. **§§1–5 and 7–16
  are untouched**, and §4's *"Every bound is re-applied at `fetch` and none is carried
  from the listing"* governs the new bound as it governs the other two. §11 below shows
  the working under [ADR-0070](0070-adr-lifecycle-amend-supersede-status.md) §1 and
  [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §1, clause by
  clause, including the clauses a reader would most expect to have moved and which did
  not. ADR-0230's `Status` line reads `Accepted` and takes the leading token in this
  change (ADR-0082 §2).

## Context

### Where this comes from

ADR-0230 §6 states two things about `fetch_max_file_bytes` in one sentence: that it is
*"the file's size on disk"* and that it *"bounds the read **and** the extraction's
cost"*. For an uncompressed format those are one number. For a compressed one they are
not, and **no implementation can make both true** — which is
[#2022](https://github.com/leonapivato/ai-assistant/issues/2022), filed out of
ADR-0230's own Lane C1 (PR #2014) after both required review lenses had
ruled on it from opposite sides on one round.

A PDF page's content stream arrives Flate compressed, and a run of one repeated
operator compresses about 340:1. Lane C1 measured what that buys an adversary, at §6's
own defaults — `fetch_max_file_bytes` 4 MiB, `fetch_max_content_bytes` 32 KiB:

| document on disk | decoded content stream | outcome | elapsed | `tracemalloc` peak |
| --- | --- | --- | --- | --- |
| 3.5 KB | 1 MB of operators | refused on the text bound | 6.0 s | 16 MB |
| 12 KB | 4 MB of operators | refused on the text bound | 28 s | 65 MB |
| 47 KB | 16 MB of operators | refused on the text bound | **313 s** | **261 MB** (737 MB RSS) |

Every one of those refusals is **correct**; what is wrong is that it costs minutes of a
worker thread to reach. The file bound is satisfied by the *compressed* bytes and never
sees the stream; `fetch_max_content_bytes` is counted on extracted *text*, which exists
only once the whole stream has been parsed into operators. So the one bound §6 says
covers the extraction's cost cannot see the cost, and the one that can is checked after
it has been paid. The shape is superlinear in the stream's size, so the exposure grows
faster than the file does.

**One figure is the whole design constraint and it is a measurement rather than an
estimate**: the 47 KB document is a **single page**, so the 313 s is spent inside one
uninterruptible `extract_text()` call. Nothing outside that call can refuse partway
through it. §5 below is what that fact decides.

**The measurements are Lane C1's, on one machine, and the orders of magnitude are the
finding rather than the seconds.** They are recorded on #2022 and at the code, in
`src/ai_assistant/readers/_extract.py`'s `_extract_pdf` docstring, which C1 merged
carrying the whole disclosure.

### The content stream is not the only amplified input, which this ADR's own review found

`/Contents` is where Lane C1 looked, and a bound counting only `/Contents` is bypassed
twice over. Adversarial review of this ADR's round 1 named the first; measuring it found
the second. Both were built and timed against the adopted `pypdf` 6.16.2, and both are
**smaller on disk** than the document #2022 is filed about:

| document on disk | `/Contents` decoded | what carries the operators | `extract_text()` |
| --- | --- | --- | --- |
| 12,453 B | **10 B** | one Form XObject holding 4 MB of operators | **33.9 s** |
| 1,173 B | 5,500 B | one 100 KB Form XObject invoked **500 times** | **126.6 s** |

`extract_text` **descends into Form XObjects**: `PageObject._extract_text__xform` follows
each `Do` operator into the named form and parses it as a content stream of its own. So
the first document's `/Contents` decodes to ten bytes and the parse is somewhere else
entirely. And the descent is **per invocation** rather than per form — the adopted
version's cycle guard (`known_ids`) refuses only a *re-entrant* form, so five hundred
sequential `Do`s of one form are five hundred parses of it. A count over distinct decoded
bytes sees 105 KB and admits two minutes of parsing.

**This is why §3 counts bytes *per parse* over the invocation graph** rather than the
page's own stream, and why §8 owes an arm for each of these three documents rather than
for #2022's alone.

### The extraction reads other decoded streams too, and this ADR does not bound them

`extract_text` decodes more than content streams. It reads each font's `/ToUnicode` CMap
and its **embedded font program**, and a compressed **object stream** (`/ObjStm`) is
decoded whole during ordinary indirect-object resolution. All three are decoded streams of
a size the file bound does not see. Built and timed the same way:

| document on disk | decoded resource stream | `extract_text()` | peak |
| --- | --- | --- | --- |
| 16,411 B | an 8 MB `/FontFile` | **3.19 s** | 51.7 MB |
| 40 pages, 13,008 B | one 1 MB `/FontFile`, **re-read per page** | 1.66 s | — |

**They cost two orders of magnitude less per byte than operators do, and that is the
finding rather than an aside**: about **0.04 s per decoded MB** for a font program against
about **5 s per decoded MB** for content-stream operators, a factor of roughly **120**.
The second row is why: the adopted extraction rebuilds a stream's fonts on **every**
`_extract_text` call, so a font is read once per page and once per form invocation — one
page 0.04 s, ten 0.43 s, forty 1.66 s, exactly **linear**. Linear in decoded bytes is what
the file bound was already a proxy for; superlinear is what it never was, and #2022 is
filed about the superlinear one.

**An earlier draft of this ADR bounded both, with a second `Settings` field, and both
review lenses refused it from opposite sides on one round.** The pair is worth recording
because it is the reason §2 has one field and not two, and because the two findings are
the same clause failing in two directions:

- **Too narrow.** `PdfReader._get_object_from_stream` calls `obj_stm.get_data()` — decoding
  the **whole** `/ObjStm` — and parses every object in it in one pass, *during ordinary
  indirect-object resolution*. That happens while the catalog, the page tree and the
  resource dictionaries are resolved, which is **before** any per-page loop and therefore
  before any total exists to compare. A Flate-compressed `/ObjStm` inside
  `fetch_max_file_bytes` is decoded and parsed with every new total still at zero, so a
  clause claiming every decoded byte falls under one of the bounds was simply false.
- **Too wide.** `Font.from_font_resource` resolves `/FontFile*` with `get_object()`, which
  does **not** decode. The decode is `get_data()`, reached in `_font.py` only under
  `HAS_FONTTOOLS and font_file and isinstance(self.encoding, str)`, and in
  `_cmap._type1_alternative` only when `/ToUnicode` is **absent** and `/Subtype` is
  `/Type1`. So a document with a normal `/ToUnicode` and a large `/FontFile2` is extracted
  without that program ever being decoded — and a bound counting it would refuse on bytes
  the extraction never reads.

**Three successive enumerations were falsified in three successive rounds** — `/Contents`
only, then plus forms, then plus CMaps and font programs — which is the shape of a
formulation that is wrong rather than one that is incomplete. **Predicting which streams a
library will decode is not a stable contract**: part of the set is conditional at several
points, and part of it happens before the extraction the bound sits in begins. So this ADR
narrows what it claims instead of lengthening the list. It bounds the class it can
establish soundly, because §3's walk decides membership with **the extraction's own
parser** rather than by predicting the library's behaviour — and it says in terms that the
linear classes are unbounded here, deferring them by name in §10 with what fires them.

**Two figures of the adopted library appear in this ADR and neither is leant on** (§6): a
`/ToUnicode` CMap raises at `MAPPING_DICTIONARY_SIZE_LIMIT` (100,000 mappings), and form
invocations are capped in aggregate at `MAX_XFORM_INVOCATIONS_PER_EXTRACTION` (5,000).
Both are recorded as evidence about a resolved version; §6 is why neither is a bound this
system states as its own, and §10's deferral of the linear class is not discharged by
either.

### Both lenses were right, and the text is what is wrong

PR #2014 wrote two repairs and could keep neither, and the pair is why this is an ADR's
question and not a lane's.

1. **`extract_text(visitor_text=…)`, refusing as fragments are produced.** Measured and
   **does not work.** `pypdf` calls the visitor once per *text-block flush* —
   `BT`/`ET`/`cm`/`Tf` — not per operator, so one `BT … ET` block holding 90,909 `Tj`
   operators calls it exactly twice, and both calls come after the parse the cost is in.
   With the guard in place the 47 KB document's numbers did not move.
2. **A running total of decoded content bytes, refused against `fetch_max_file_bytes`.**
   Works — the same document then refuses in **0.01 s** — and was **removed at review
   round 9** as an unratified refusal criterion. §6 defines that field as the file's
   size on disk and its refuse-never-truncate clause names *"either bound"*, and a 4 MiB
   PDF of vector artwork sits inside both while carrying far more than 4 MiB of
   operators. Refusing it changes the `Fetcher` **outcome** contract, which ADR-0015
   puts in an ADR and not in an implementation.

Adversarial was right that the hole is real; architecture was right that closing it
against a field defined as size on disk is a refusal no ADR ratifies. Neither lens was
mistaken about the text. **The text is what is wrong**, and this ADR is the instrument
ADR-0015 requires for changing it.

### What the tree settles, verified against `origin/main` at `41d75b9f`

- **ADR-0230 read `Status: Accepted`** on `origin/main` when this ADR was written — this
  change is what puts the leading token on that line — and its §6 carries all three
  sentences quoted in this ADR's header, verbatim.
- **`readers/_extract.py` is on `main`**: ADR-0230 Lane C1 merged as PR #2014 while this
  ADR was being written. `_extract_pdf` extracts a page at a time with a running total of
  the *rendered text* checked after each page, and its docstring carries #2022's
  disclosure entire. `SUPPORTED_SUFFIXES` is `{".txt", ".md", ".markdown", ".pdf"}`;
  `_TEXT_SUFFIXES` is the first three, decoded strictly as UTF-8 in one call.
- **`core/config.py` carries four `fetch_*` bounds** — `fetch_listing_ttl`,
  `fetch_listing_max_entries`, `fetch_max_file_bytes` (4 MiB) and
  `fetch_max_content_bytes` (32 KiB) — each with `ge=1` (or `gt=timedelta(0)`) and
  `lt=2**63`, refused when `Settings` is constructed. `fetch_root_path` defaults unset.
- **`core/types.py`'s `FetchRefusal` has exactly five members**, and `FetchOutcome`
  carries a record or a refusal and never both or neither. This ADR adds **no member, no
  field and no Protocol**, and leaves `core/protocols.py` untouched; what it does reach in
  `core/types.py` is one docstring, `TOO_LARGE`'s, which enumerates that member's causes
  and gains a third (§9).
- **`app/composition.py`'s `_build_local_file_fetcher` passes each bound explicitly** —
  `max_file_bytes=settings.fetch_max_file_bytes` and the three beside it — so a new
  `Settings` field reaches `readers` only if that call site is edited too (§9).
- **`pypdf` is adopted ranged, `>=6.16`**, outside ADR-0024 §3's exact-pinned set, with
  `uv.lock` fixing 6.16.2. §6 below turns on that.
- **The repair is on `main`'s history and not at the sha #2022 names.** #2022 and the
  ruling on it both point at `36501bb4`, which is a reachable object in no clone: PR
  #2014 was rebased before it merged and rebase-merged when it did. The commit that
  landed is **`edb2345f`**, *"fix(readers): a compressed content stream is bounded before
  it is parsed"*, and the commit that removed the criterion again is **`41d75b9f`**.
  `edb2345f` is what §9 below tells the implementing lane to lift, and both are on `main`
  rather than on a branch that will be deleted.
- **The fixture the lane needs was removed with the repair.** `41d75b9f` took
  `amplified_content_stream_pdf` out of `tests/readers/pdf_fixtures.py` along with the
  criterion; the file on `main` keeps `minimal_pdf`, `extracted_text_of` and
  `amplified_page_tree_pdf` and not that one. It is in `edb2345f`'s diff and §9 names
  it.

### What this ADR is not allowed to settle

It changes no Protocol and the shape of no `core` value — no member, no field, no
annotation, nothing a wire or a schema can see — so golden rule 5 is satisfied by this
ADR being merged ahead of its lane rather than excepted, and the one `core/types.py`
edit the lane makes is `TOO_LARGE`'s docstring (§9). It admits no format to §6's first
rung and re-opens no library evaluation: ADR-0230 §13 charged Lane C1 with that, C1
discharged it, and §6 below cites the adopted library's own limits as **evidence** and
never as a bound this system may rely on. It decides nothing about the web (ADR-0230
§15, #1996 Lane B), nothing about the egress seam (ADR-0154 §7), and nothing about
retention (ADR-0230 §10, §15). It does not reopen ADR-0230 §6's refusal enumeration,
which stays closed at five.

## Decision

We will keep `fetch_max_file_bytes` as **the file's size on disk**, bounding the read and
nothing else, and add **one `Settings` bound** on the decoded bytes an extraction parses
**as content-stream instructions** — the superlinear quantity, about 5 s per decoded MB.
It is counted **while** extracting, compared before each decoded stream is parsed, and
refused as **`TOO_LARGE`**. It does **not** bound the decoded classes the extraction reads
linearly at about 0.04 s per decoded MB — object streams, `/ToUnicode` CMaps, embedded
font programs — and §10 defers that class by name, with what fires it. There is no sixth
`FetchRefusal` member, no deadline, and no change to
any Protocol, to any `core` value's shape, to the conformance suite, to the canonical fake
or to ADR-0230 §9's audit — the one thing this reaches in `core/types.py` being
`TOO_LARGE`'s docstring, which enumerates that member's causes and gains a third.

### 1. The file bound stays the file's size on disk, and it bounds the read alone

> **Normative.** `fetch_max_file_bytes` is the file's **size on disk** and bounds the
> **read**: an implementation reads at most that many bytes plus one from the open
> object and refuses `TOO_LARGE` where the object supplies more (ADR-0230 §4). It is
> **not** a bound on what an extraction decodes or parses, and no implementation, lane
> or later ADR derives a refusal criterion on decoded or extracted bytes from it.

**Which of §6's two sentences stands is decided by what an operator can predict, and
that is not a tie.** A size on disk is visible in a directory listing, in a file
manager, in a mail client's attachment column and in ADR-0230 §3's own rendering of
`ShownFile.size_bytes` — an operator setting 4 MiB knows exactly which of their
documents that admits, and can check. A decoded size is visible **nowhere**: nothing in
any listing shows it, no field of any type carries it, and for a PDF it is a property
of whichever encoder produced the file. Redefining `fetch_max_file_bytes` onto consumed
bytes would leave the mechanism's most visible number governing a quantity the operator
cannot inspect — which is the defect §6 already names in its own domain clause, where a
zero entry cap is refused because it is *"a mechanism that shows nothing while appearing
configured"*.

**And the read needs a bound of its own regardless, so the redefinition does not save a
field.** ADR-0230 §4 rules that the acquiring read is itself bounded — *"An
implementation reads at most `fetch_max_file_bytes` plus one byte from the open object
and refuses as `TOO_LARGE` where the object supplies more; it does not decide the bound
from a size it observed earlier and then read to end of file"* — and that clause is what
refuses a file that **grows** between the listing and the fetch (§14 item 4's second
arm). Point the field at consumed bytes and that clause has no figure left: the read
becomes unbounded exactly where §4 spent a clause bounding it, and a second field has to
be invented for the read. That is this section plus §2 with the names swapped, and with
every deployment's configured value silently changed underneath it.

**§6's own structure already answers this.** It carries two fields rather than one
because *what is read* and *what reaches the prompt* are different quantities with
different consumers, and one number cannot be honest about both. The bytes an extractor
parses are a **third** such quantity with a third consumer — the parser — and the same
argument that made §6 two fields makes it three. The alternative is a field whose name
and whose stated domain are both false, which is the state §6 is in today.

### 2. One bound, on the decoded bytes parsed as instructions

> **Normative.** `Settings` gains **one** field, a bound on decoded bytes summed over one
> fetch, with a named default, with a domain of **integers of at least
> 1**, and refused at **load** rather than at the first fetch — `Settings`'s own
> refusal, before any fetcher is built and before any filesystem call (ADR-0093 §5, in the
> form ADR-0230 §6 borrows it), stopping the deployment exactly as an out-of-domain
> `fetch_max_file_bytes` does:
>
> - **`fetch_max_decoded_bytes`**, default **1 MiB** (1,048,576) — the decoded bytes the
>   extraction parses **as instructions**. For PDF, content-stream operators.

> **Normative.** **This bound is on the instruction class alone, and this ADR states in
> terms that it bounds nothing else.** The decoded classes an extraction reads *linearly*
> — for PDF, a compressed object stream, a font's `/ToUnicode` CMap and its embedded font
> program — are **not bounded by this ADR**, and no implementation, lane or later ADR
> derives a refusal criterion on them from this field. §10 defers that class by name, with
> what fires the deferral.

> **Normative.** **The narrowing is the decision and not an omission**, and its ground is
> a measured ratio rather than a preference. Content-stream operators parse at about
> **5 s per decoded MB** (8.5 s/MB for the form-carried document, 2.5 s/MB for the
> repeated-form one) and the parse is **superlinear** in the stream's size — 1 MB → 6 s,
> 4 MB → 28 s, 16 MB → 313 s. An embedded font program reads at about **0.04 s per decoded
> MB**, linear, a factor of roughly **120** cheaper. #2022 is filed about the superlinear
> quantity; a linear one at that price is bounded well enough by the file bound and the
> read it governs, and charging it into this figure would refuse an ordinary forty-page
> document with an embedded font while charging it into a second figure requires
> predicting a set of streams §6 and Context show cannot be predicted stably.

> **Normative.** The **name is fixed here** and is not the implementing lane's to
> choose, as ADR-0230 §6 fixes the four it adds. It does not carry the word *content*, which
> `fetch_max_content_bytes` already holds for the extracted **text**: a reader meeting a
> second `content` bound, measuring a different quantity at a different point, would have
> to guess which is which.

> **Normative.** It is an **independent figure and never a derived one.** No
> implementation computes it from `fetch_max_content_bytes` or from
> `fetch_max_file_bytes`, and no deployment's change to either moves it.

**Where the figure comes from, stated as arithmetic rather than as a feel.** It
has to clear every legitimate document and refuse the amplified one, and both sides are
checkable.

- **The legitimacy side is a ratio against a bound that is already ratified.** A
  document that fetches at all must render its extracted text inside
  `fetch_max_content_bytes`, 32 KiB. 1 MiB is exactly **thirty-two times** that. So this
  bound refuses only a document whose extraction parses **more than thirty-two bytes of
  operators per byte of text it yields** — a document that is overwhelmingly not text. An
  ordinary text page's stream carries its text plus its positioning and font operators, a
  few times over, not thirty-two.
- **The cost side is the measurement.** At the adversarial density Lane C1 built — a
  stream of nothing but repeated `Tj` — 1 MB of operators parsed in **6 s**, against
  313 s at 16 MB, and the form-carried documents of Context measure in the same regime
  (4 MB of operators in a Form XObject, 33.9 s). So the default admits a worst case of a
  few seconds of parse on input chosen to be as expensive as PDF operators get, where
  today it admits minutes and is bounded by nothing.

**An operator raising it buys superlinearly more, and that is worth writing down**
rather than discovering: 1 MB → 6 s, 4 MB → 28 s, 16 MB → 313 s on Lane C1's machine.
Doubling the figure does not double the worst case.

**And an ordinary document's fonts do not enter the figure at all**, which is what the
narrowing buys the legitimacy side. The adopted extraction rebuilds a page's fonts on each
`_extract_text` call, so a forty-page document embedding a 200 KB font reads **8 MB** of
font bytes across its parses — eight times this bound, and an entirely ordinary document.
None of it is counted here. What is counted is the operators, and an ordinary page's are a
few times its text rather than thirty-two. A single figure asked to cover both would have
had to clear that 8 MB, and would then have admitted #2022's 16 MB of operators.

**For a document that was going to refuse anyway, only the price changes.** A 300-page
report carries far more than 32 KiB of text and refuses on `fetch_max_content_bytes`
today; under this bound it refuses earlier and cheaply, with the same class. What
changes **outcome** is a document parsing more than thirty-two bytes of operators per byte
of text it yields — the amplified ones, pages of vector artwork, and a document whose
per-page graphics are parsed on every page. The last of those is a legitimate document
refused, which is the direction ADR-0230 §6 chooses for its own bounds and which §10
defers raising the figure for, on evidence rather than on an estimate.

### 3. What is counted, per format, and where the comparison sits

> **Normative.** The bound is counted **in the concrete extractor, per format**, on
> the bytes that format's own decoding produces. It is not a `core` concern, it adds
> no argument to any Protocol, and it reaches the extractor as a configured figure
> exactly as the other two bounds do.

> **Normative.** For **PDF**, `fetch_max_decoded_bytes` counts the decoded length of
> **every content stream the extraction parses, once per parse** — a page's own, and every
> Form XObject stream reached from it, once for each `Do` that invokes it. A count over
> `/Contents` alone does not satisfy it, and neither does one charging a repeatedly
> invoked form a single time.

> **Normative.** **Nothing else is counted, and that is a boundary rather than a gap.**
> Decoded streams the extraction reads but does not parse as instructions — for the
> adopted version, a compressed object stream, a font's `/ToUnicode` CMap and its embedded
> font program — are **not** charged to this total, and no implementation charges them to
> it. They are also not bounded elsewhere by this ADR: §10 defers the class by name.

> **Normative.** **The counted set is decided by the extraction's own parse and not by a
> prediction of what the library decodes**, which is what makes it establishable at all. A
> stream is counted exactly where the walk below reaches it through the extraction's own
> content-stream parser. An implementation may not extend the total to a stream it
> *expects* the library to decode, and may not omit one the walk reaches on the ground that
> some other mechanism bounds it — §6 is why the second half of that holds: what a
> dependency's own limit does is evidence about a version.

> **Normative.** **What the walk treats as an invocation, and what it resolves that
> invocation against, are the adopted extraction's own answers and never a second
> grammar.** A `Do` is an invocation exactly where the extraction would descend on it — so
> the two bytes `Do` inside a string literal are not one — and its operand is resolved
> against the **inherited `/Resources`** of the object whose stream is being walked: a
> page's for a page's content stream, a form's own for a form's. An implementation that
> re-implements either and diverges does not satisfy this bound, in whichever direction it
> diverges.

> **Normative.** **An operand that resolves to no Form XObject adds nothing, and that is
> soundness rather than optimism.** The walk resolves in the context the extraction
> resolves in, so a name the walk cannot resolve to a form is a name the extraction cannot
> resolve either, and a descent that will not happen costs nothing to charge for. The same
> symmetry is why the walk skips a form already on the current path: the adopted version
> refuses a re-entrant form and parses it not at all.

> **Normative.** **Where the walk cannot establish what the extraction will parse, the
> fetch is refused `EXTRACTION_FAILED` and never extracted on the hope** — a stream the
> library's own parser will not read, a resource dictionary that cannot be resolved, a
> structure the walk does not recognise. This is the one fail-closed branch, it names its
> class, and that class is ADR-0230 §6's own for a supported format whose text could not
> be decoded: no member is added, and a document refused here is one the extraction was
> about to spend an unknown amount on.

> **Normative.** **The property is required and no construction is**, in ADR-0230 §6's
> own form — and it is named **achievable** rather than aspirational, because a
> requirement no implementation is known to satisfy would be a deferral wearing a
> decision's clothes. A walk of the **invocation graph** satisfies it: begin at the page's
> decoded content stream; add each stream's decoded length to the total and
> compare it **before** that stream is parsed;
> then parse the stream **with the adopted library's own content-stream parser**, take the
> `Do` operations it reports, resolve each against the inherited resources above, and
> recurse — refusing the moment the total passes the bound.

> **Normative.** For **plain text and Markdown** the counted quantity is **zero**,
> and no implementation checks the bound on those formats. Their extraction has no
> decoding step: the extractor parses the file's own bytes, which `fetch_max_file_bytes`
> bounds at the read, so there is no ratio between bytes read and bytes parsed for the
> bound to refuse. A `.txt` file larger than `fetch_max_decoded_bytes` and inside
> `fetch_max_file_bytes` is therefore **fetched**, not refused.

> **Normative.** The total is **running across the whole fetch** and never per page. A
> per-page bound would admit an unbounded document made of bounded pages, which is the
> defect `fetch_max_content_bytes` is already summed to avoid.

> **Normative.** The comparison is made **after each decoded stream and before the next
> is decoded**, and the extraction is refused the moment the total passes the bound. No
> implementation decodes several streams — a page's content array, a page's forms, or both
> together — and compares their sum afterwards.

> **Normative.** The refusal precedes the work it bounds: **the total is compared
> before the operators it counts are parsed**, which is the property ADR-0230 §6 claimed
> for `fetch_max_file_bytes` and did not have.

> **Normative.** The bound is **re-applied at every `fetch` and carried from no
> listing**, under ADR-0230 §4's clause of that name, and is decided against the object
> the fetch has open. Nothing about it is read off a `SourceListingEntry`.

> **Normative.** An ADR admitting a **later format** to ADR-0230 §6's rung states what
> that format's decoding step produces for this bound, or that it produces
> nothing for it. ADR-0230 §6
> already requires such an ADR to state what its extraction is; this adds the one figure
> a decoding format cannot be admitted without.

**The stream-by-stream comparison is not a refinement of the lifted repair; it closes a
hole the repair had.** A PDF page's `/Contents` may be an **array** of streams, and
`edb2345f` summed a page's streams before comparing —
`sum(len(part.get_object().get_data()) for part in parts)` — so every stream of that
page is decoded and materialised before anything is refused. At the adopted library's
own per-stream ceiling that is 75 MB **times the number of streams on the page**, and
zlib's maximum ratio puts a 4 MiB file's total decoded size in the gigabytes. Comparing
after each stream bounds what can be materialised before a refusal at **one** stream's
decoded length.

**The residual that leaves is stated rather than hidden**, because a bound whose own
input is unbounded is not one. Obtaining a stream's decoded length requires decoding it,
and the adopted library's interface decodes whole streams; so one stream's decoded bytes
are materialised before the comparison that refuses them. What bounds *that* is the
library's own ceiling and not this system — §6 below is why that is disclosed as
evidence and §10 defers closing it, with what fires the deferral.

**Measuring the length costs the extraction nothing**, which is why the comparison can
sit before the parse rather than being a second decode. `pypdf` caches a stream's
decoded bytes on the object, so the `extract_text()` that follows reads the same bytes
rather than decompressing again. That is a property of the adopted version, and §6's
rule about such properties applies to it too: it is why the check is cheap, never why it
is correct.

**Using the library's own parser costs the admitted document a second parse, and that is
the price of agreement.** A document that passes is parsed twice — once by the walk and
once by the extraction — so the worst admitted case is twice a few seconds rather than
once. The alternative is a second grammar for content streams, which is exactly where the
`(Do) Tj` case and the resource-inheritance case above would be got wrong, and a walk that
disagrees with the extraction is unsound in one direction and over-refuses in the other. A
lane that can **establish** agreement with a cheaper scan may use one; what is fixed is
the agreement, not the instrument. The doubling is bounded by the bound, which is what
makes it affordable to state as the default.

**Whether the whole of a page's count is established before `extract_text` is entered is
not this ADR's to choose, because the descent leaves no other point.** The extraction
follows a `Do` into a form and parses it inside the same call; there is no seam between
that form's decode and its parse for an implementation to sit in. So a page's counted
quantity — its own stream plus every parse the walk reaches from it — is established
**before** the page's extraction begins, and the stream-by-stream comparison above
applies to the walk's own decodes. That is the same shape as the page loop one level up,
and it is why the bound is a bound on an *input* rather than an observation of work in
progress (§5).

**Counting per parse rather than per distinct stream is what the second measured document
forces**, and it is the clause an implementation will be tempted to drop as
double-counting. A form invoked five hundred times is parsed five hundred times, is 105 KB
of distinct decoded bytes, and cost 126.6 s. Charged once it sits comfortably inside any
figure this ADR could pick; charged per parse it is 50 MB and is refused immediately. The
adopted library's aggregate cap of 5,000 invocations is what made the *unfixed* worst case
five thousand times one form rather than unbounded; it is not something this bound leans
on, because the walk charges every invocation and refuses long before the cap is reached
(§6).

### 4. The refusal is `TOO_LARGE`, and there is no sixth member

> **Normative.** An extraction refused on `fetch_max_decoded_bytes` yields the
> `FetchRefusal` member **`TOO_LARGE`**.
> `FetchRefusal` stays **closed at five members** and this ADR adds none.

> **Normative.** The class does **not** disclose which of the three bounds refused, and no
> implementation adds a field, a message or a second member that would. A refusal
> *"names a **class** and carries no path, no name, no excerpt and no message from an
> underlying library"* (ADR-0230 §6), and which of three bounds a document passed is a
> fact about that document's contents.

**`TOO_LARGE` and not `EXTRACTION_FAILED`, and the difference is what an operator does
next.** `EXTRACTION_FAILED` means a file of a supported format whose text could not be
decoded — a **malformed** document. An amplified one is perfectly well formed and is
refused for its size. ADR-0230 §9 says in terms what the audit's refusal class is for:
it is *"how a deployment learns that its size bound is set below its documents, or that
its root holds formats the rung does not read"*. Report a size refusal as an extraction
failure and that operator goes looking for corrupt files. `TOO_LARGE` sends them to the
bounds, which is where the answer is.

**No sixth member, on ADR-0230 §6's own two grounds.** The first is its
every-member-is-reachable clause — a member is carried only where a real filesystem can
produce it from an authentic entry, and §14 item 9 asserts the five arm for arm; a sixth
would have to earn its arm and would then be a class distinguishable from outside. The
second is the disclosure posture that clause exists to protect: §6 declines an
`UNSUPPORTED_TYPE` member because a distinct class *"would answer* a file of that name
is there, and it is a `.docx` *to a caller holding nothing but a guess"*. A member
meaning *your file was small on disk and large once decompressed* is the same
disclosure about the same file, one property over.

**The cost of the coarse class is real and is named** rather than argued away: with
three bounds all reporting `TOO_LARGE`, §9's per-kind refusal rate tells an operator
that **a** bound is set below their documents and not **which**. §10 defers the finer
statement and says what fires it.

### 5. There is no deadline, and a byte bound is the only bound available here

> **Normative.** No implementation bounds an extraction by **elapsed time**. This seam
> takes no deadline, no timeout and no clock; no lane adds one, and ADR-0026's clock
> seam is not wired into the extractor.

**A deadline has no enforcement point this bound does not already have, which is a
measured fact and not a prediction.** The 313 s is spent inside a single
`extract_text()` call on a **single-page** document. Nothing checks a clock during it —
CPython cannot interrupt it, and Lane C1 measured the one interface that looked like it
could: `visitor_text` fires per text-block flush, so that document calls it twice, both
times after the parse. A deadline could therefore only be read at the same points a
decoded-byte total is read — between units — where it refuses nothing the byte bound
does not, later and having already paid.

**And it would cost a ratified property to buy that nothing.** ADR-0230 §6 fixes the
shape the PDF adoption must satisfy: the extraction *"runs in-process, reaches no
network, is **deterministic for a given file**, and converts a failure into
`EXTRACTION_FAILED`"*. A deadline makes the outcome a function of machine load — the
same document fetches on an idle hub and refuses on a busy one, and a turn's supply
stops being reproducible from its inputs. A byte bound is a function of the file alone
and keeps that property exactly.

**What a deadline could genuinely reach, only a different mechanism reaches**: killing
the work partway through means running the extraction out of process and killing the
process. That is new machinery in `readers/`, an inter-process path carrying file
content, and a lifecycle the composition root would own — none of which any ADR asks
for, and all of it for a case this bound already refuses at its input. §10 defers it by
name and says what would fire it.

**Bounding the input of an uninterruptible unit is the bound that exists**, and stating
it that way is what keeps this ADR honest where §6 was not. This decision does not claim
to bound the *time* an extraction takes. It claims to bound the *quantity* whose parse
that time is superlinear in, before the parse begins, and to choose the figure from the
measurement of what that costs.

### 6. What the adopted library bounds is evidence about a version, never this system's bound

> **Normative.** A pinned dependency's own internal limit is **evidence about the
> version this project resolves** and is never a bound this system relies on or states as
> its own. Where this system requires a bound, this system enforces it; where it declines
> to require one, it says so in terms and defers it by name (§10), and neither the saying
> nor the deferral is discharged by a limit the dependency happens to carry.

**`pypdf` 6.16.2 caps a Flate decode at `ZLIB_MAX_OUTPUT_LENGTH` (75,000,000 bytes) and
raises past it**, with the same 75 MB ceiling on `LZW`, `RunLength`, `JBIG2` and the
array-based path, and each raise lands in `_extract_pdf`'s own `except` as
`EXTRACTION_FAILED`. That is worth knowing and is why §3's residual is 75 MB rather than
unbounded. **It is not a bound on the parse**, which is where the 313 s went, and it is
not aggregate — it is per stream, and a document has many.

**It is not the only such limit, and the round that found this section's first draft
wrong is why they are listed rather than leant on.** Measured against the same version: a
`/ToUnicode` CMap is capped at `MAPPING_DICTIONARY_SIZE_LIMIT` (100,000 mappings) and
raises past it; form invocations are capped in aggregate at
`MAX_XFORM_INVOCATIONS_PER_EXTRACTION` (5,000); and the page tree carries the three guards
Lane C1 pinned. An earlier draft of §3 used the first of those as the reason the walk need
not count a `/ToUnicode` stream, which is the reliance the clause above forbids. **The
narrowed claim does not restore that reliance and must not be read as doing so.** §2 does
not bound the CMap or the font program *because they are cheap and measured linear*, and
§10 defers them on that ground, with what fires the deferral; the library's cap is
recorded here as evidence and is not the reason. Nor is the invocation cap leant on: the
walk charges every invocation and refuses long before 5,000 is reached.

> **Normative.** The implementing lane **establishes, against the version `uv.lock`
> fixes, which streams the extraction parses as content-stream instructions**, so that
> §3's walk reaches exactly those. It records what it found at the code, in
> `_extract_pdf`'s docstring, as Lane C1 recorded #2022's disclosure there — **including
> the decoded classes it found that this bound does not count**, so a reader at the code
> meets the boundary §2 draws and not only the total.

**What that record is for, and what it is not.** It is not an enumeration this ADR relies
on for soundness: §3's counted set is decided by the extraction's own parse rather than by
a prediction, so a release that decoded a further stream kind *outside* the instruction
class changes nothing this bound claims. The record exists so a later reader can see which
classes were measured linear when the claim was narrowed, and can tell whether §10's
deferral has been fired. That difference — a claim whose soundness does not rest on a
list — is the difference between this ADR and the clause of ADR-0230 §6 it replaces, and
it is the correction three falsified enumerations bought (Context).

**And it is not carried by anything this project declares.** Lane C1 adopted `pypdf`
**ranged**, `>=6.16`, deliberately outside ADR-0024 §3's exact-pinned set — §3 pins the
behaviour-affecting stack exactly because *"a **published wheel** install resolves them
fresh"*, and a ranged dependency is one this project has said it does not need pinned.
A future 6.x may raise that ceiling, lower it, or spell it differently, and nothing in
`pyproject.toml` would notice. So the ceiling is a fact about a resolution and not a
term of this decision — the same distinction Lane C1 drew when it **pinned** the page-tree
guards with a test rather than asserting them in prose.

### 7. The audit is unchanged, and that is a decision rather than an omission

> **Normative.** This ADR adds **no audit field, no event, no key and no emission
> point**. ADR-0230 §9 binds entire and unchanged: one `INFO`-level structured event per
> turn under the one fixed key, carrying the `FetchRefusal` class where a fetch resolved
> to one and the ambient correlation identifier and no other.

> **Normative.** §9's no-address rule binds this refusal without qualification. No path,
> no name, no extension, no size, **no decoded byte count**, no excerpt and no message
> from an extraction library appears in the event. The count is a measurement of the
> file's contents and is Tier 1 by §9's own reasoning about a file name.

**Nothing has to move, because the field §9 added is a class and the class already
exists.** A refusal on the new bound is a `TOO_LARGE`, which §9's one field already carries
and which §6's enumeration already closes. That is the test §9 sets for itself — *"the
fields milestone 2 raises rather than replaces"* is ADR-0226 §9's clause and §9 inherits
it — and this addition renames nothing, drops nothing and starts no second audit.

### 8. The representative-input tests this decision owes

> **Normative.** The implementing lane owes a test for each of the following, each over
> behaviour rather than over a call count, in ADR-0230 §14's form.

> **Normative.** **Every refusal arm below asserts that the parse was not entered, and
> none asserts a wall-clock duration.** The observation is `pypdf`'s own
> `PageObject.extract_text` — not called for a page the bound refuses — which is
> deterministic, independent of the machine the suite runs on, and proves exactly the
> property the arm is about. A wall-clock threshold proves less and flakes: tight enough
> to catch the regression it would fail a descheduled worker, loose enough not to it would
> pass a regression spending seconds again. That is the nondeterminism §5 refuses in
> production, and it is not admitted into the suite instead. It is available here and was
> not in ADR-0230 §14 item 4's fourth arm because that arm's failure is a **hang**, which
> returns nothing to assert over; these return a refusal.

1. **The amplified content stream is refused before it is parsed.** Lane C1's
   document — about 47 KB on disk, one page, 16 MB of decoded operators in its own
   `/Contents` — is refused `TOO_LARGE`, `extract_text` is not called for that page, no
   record is added, no turn fails, and no prefix of its text reaches the supply, the
   record or the reply.
2. **A form-carried amplification is refused, and the count is not `/Contents`.** A page
   whose `/Contents` decodes to a handful of bytes and whose single Form XObject carries
   megabytes of operators — about 12 KB on disk, measured at 33.9 s unbounded — is refused
   `TOO_LARGE` with `extract_text` not called. **This is the arm that fails on any
   implementation counting `/Contents` alone**, which passes arm 1 whole.
3. **A repeatedly invoked form is charged per invocation.** A page invoking one 100 KB
   Form XObject several hundred times — about 1.2 KB on disk, roughly 105 KB of *distinct*
   decoded bytes, measured at 126.6 s unbounded — is refused `TOO_LARGE` with
   `extract_text` not called. **This is the arm that fails on any implementation counting
   distinct streams once**, which passes arms 1 and 2 whole.
4. **A document that uses forms legitimately is not refused.** A page invoking a small
   Form XObject a few times, whose whole counted quantity is well inside the bound,
   fetches, and the text the form contributes reaches the record. Two further arms at the
   same seam, each of which an over-approximating or a re-implemented walk fails while
   passing this one: a page whose content stream carries the **literal text `(Do)`** and
   invokes no form at all fetches, its counted quantity being its own stream and nothing
   else — the arm that fails on any walk scanning bytes rather than deciding by the
   extraction's grammar; and a page whose form is named in **resources it inherits through
   the page tree** rather than in a dictionary of its own fetches, with the form's text in
   the record — the arm that fails on any walk resolving an operand somewhere other than
   where the extraction resolves it.
5. **The bound is a running total, and refuses at the page that crosses it.** A document
   whose pages are each well inside the bound and whose sum passes it is refused
   `TOO_LARGE`, with `extract_text` not called for the crossing page or for any after it.
   This is the arm that fails on any implementation applying the bound per page.
6. **The comparison sits between decoded streams, not after a page's.** A single page
   whose `/Contents` is an **array** of streams whose sum passes the bound is refused
   after the stream that crosses it and **before the next is decoded**, asserted on what
   was decoded rather than on elapsed time. This is the arm that fails on `edb2345f` as
   written, which summed a page's streams before comparing.
7. **The boundary value, both ways.** A document whose counted
   quantity is exactly `fetch_max_decoded_bytes` extracts and one byte over is refused
   `TOO_LARGE`. **Every arm runs
   with the other two bounds set high enough that only the one under test can decide
   it** — an amplified stream yields far more text than 32 KiB, so an arm left at the
   defaults asserts nothing about the bound it names.
8. **A document inside every bound is unaffected.** Its text reaches the record whole and
   the reply carries it, with no bound having refused anything.
9. **A plain-text file over the decoded bound is fetched.** A `.txt` or `.md` file larger
   than `fetch_max_decoded_bytes` and inside `fetch_max_file_bytes` fetches, with
   `fetch_max_content_bytes` raised so the text bound does not decide the arm. This is
   the arm that fails on any implementation applying a decoded bound to a format with no
   decoding step.
10. **The bound counts instructions and nothing else, which is pinned rather than only
    stated.** A forty-page document embedding a font of ordinary size, whose font bytes
    across its parses far exceed `fetch_max_decoded_bytes` while its content streams sit
    well inside it, **fetches**, with its text reaching the record. **This is the arm that
    fails on any implementation charging decoded resource streams into this total** — the
    boundary §2 and §3 draw, and the one clause of this ADR that a later reader is most
    likely to widen back. It is a *fetch* arm rather than a refusal arm because what is
    being asserted is the absence of a bound, so no refusal exists to observe.
11. **An out-of-domain bound does not load.** A zero and a negative value of
    `fetch_max_decoded_bytes` is refused when
    `Settings` is constructed, before any fetcher is built and before any filesystem call,
    and each is a configuration error that stops the deployment rather than an empty
    listing, a `FetchRefusal` or a degraded turn. This is ADR-0230 §14 item 21's arm,
    extended by one field and asserted in its form.
12. **The enumeration did not grow.** `FetchRefusal` has five members, and the audit event
    for arm 1's turn carries `TOO_LARGE` and no field naming a bound, a count or a size.

> **Normative.** This ADR adds **no clause to the `Fetcher` conformance suite and no
> parameter to the canonical fake.** The bound is enforced inside a concrete extraction,
> and ADR-0230 §13's own rule is that a suite cannot make an arbitrary fetcher's source
> behave — *"those are the concrete fetcher's tests"*. A fake that performs no extraction
> has nothing to bound.

### 9. What the implementing lane owes

> **Normative.** **One lane**, briefed from this ADR's merged text, landing after
> ADR-0230 Lane C1 — which merged as PR #2014 — and before milestone 29's exit probe
> runs against a configured documents root. It is a **follow-on to Lane C1 and not a
> reopening of it**: §13's C1 charge is discharged by C1's merge, and nothing here
> re-decides the library, the triad, the fetcher or the composition.

> **Normative.** Its footprint is `src/ai_assistant/core/config.py` (the one field,
> its named default, its stated domain and its load-time refusal),
> `src/ai_assistant/app/composition.py` (`_build_local_file_fetcher` passes that figure
> to the fetcher beside the other four — without it an operator's configured value reaches
> `readers` never, and the bound is a field nothing enforces),
> `src/ai_assistant/readers/_extract.py` (the walk, the comparison, and the
> `_extract_pdf` docstring, whose #2022 disclosure becomes a statement of the bound **and
> of the classes it does not bound**, §6), `src/ai_assistant/readers/files.py` (threading
> that figure from the fetcher to the
> extraction), `src/ai_assistant/core/types.py` (**one docstring**, below), and tests
> under `tests/readers/`, `tests/core/` and `tests/app/`. `core/protocols.py` is untouched
> and neither `PROTOCOL_VERSION` nor `PlanExport.schema_version` moves.

> **Normative.** **The `core/types.py` change is `FetchRefusal.TOO_LARGE`'s docstring and
> nothing else.** That docstring enumerates the member's causes — *"The file exceeded
> `fetch_max_file_bytes`, or its extracted text exceeded `fetch_max_content_bytes`"* — and
> §4 above adds a third, so leaving it would put a false enumeration on the contract a
> consumer reads. **No member is added, no field, no validator, no serialised form and no
> annotation**, so nothing a wire, a schema or a stored document can see moves — which is
> why `PROTOCOL_VERSION` does not. This edit is golden rule 5's *"A Protocol change is a
> breaking change … its ADR is ratified and merged as its own PR before anything
> implements against it"* satisfied rather than excepted: **this** is that ADR, and the
> lane makes the edit under it.

> **Normative.** The lane **starts from `edb2345f` rather than from nothing** — its
> `_decoded_content_bytes` helper, its check point in `_extract_pdf`'s page loop, and the
> `amplified_content_stream_pdf` fixture `41d75b9f` removed with it — and reshapes each
> to this ADR. What it may **not** do is lift that commit as it stands: it counted
> `/Contents` alone, compared a page's several streams only after summing them, and
> refused against `fetch_max_file_bytes`. §3 is what it is reshaped to, and §8's arms 2
> and 3 are the two documents that pass it unchanged.

**It is one lane under ADR-0137 §1** — the substantial new machinery is in `readers/`,
and `core/config.py` gains one field with its validator, which is the *"a call site
updated, an argument threaded through"* shape §1's carve-out covers rather than a second
subsystem's worth of machinery.

**The walk is the largest thing in it, and it is smaller than it sounds.** It decodes a
stream, adds its length, scans it for `Do` occurrences, resolves each against the stream's
own resources, recurses, and stops the moment the total passes the bound — so its cost is
bounded by the bound and its state is a running total and a path set. §3 fixes what it
must count and §8's arms 2, 3, 4 and 10 fix where it must not be wrong — 10 being the one
that fails an implementation counting *more* than §3 does; the spelling is the lane's.

**Independent of Lanes C2 and C3**, which touch `planning/` and `orchestration/` and
share no file with it. Its ordering constraint is C1 alone, and #2022's ruling — that
milestone 29's disk clause is not probed until this is closed — is why it does not wait
on either.

### 10. Deferred, by name, each with what fires it

- **Telling an operator which bound refused.** §4 keeps one class for three bounds, so
  §9's refusal rate says *a* bound is set below this deployment's documents and not
  which. Fired by §9's audit showing a `TOO_LARGE` rate an operator cannot act on — never
  by a lane finding the coarse class unhelpful in the abstract, and never by adding a
  sixth `FetchRefusal` member, which §4 refuses on grounds a deferral does not reach.
- **Bounding the decompression this system performs, rather than inheriting the adopted
  library's per-stream ceiling.** §3's residual is one stream's decoded bytes,
  materialised before the comparison that refuses them, bounded at 75 MB by a ranged
  dependency and by nothing this project declares (§6). Closing it means a bounded or
  incremental decode this seam performs itself. Fired by a `pypdf` release dropping or
  raising that ceiling, or by a measurement showing the **decompression** rather than the
  parse is where the cost is.
- **An extraction run out of process under a kill deadline.** §5 refuses a deadline
  because it has no enforcement point and costs §6's determinism. A separate process has
  one. Fired by a measured case where the parse of a stream **inside** the bound is
  itself too slow for a turn — never by a preference for a wall-clock guard over a byte
  one.
- **Raising the default on evidence.** 1 MiB is chosen from measured
  parse densities and a ratio against the text bound (§2), with no corpus of real
  documents behind it. A legitimate document over it is **refused** until an operator
  raises that figure — the fail-closed direction ADR-0230 §6 takes for its own bounds, and
  visible in §9's audit rather than silent. Fired by that audit showing `TOO_LARGE` on a
  deployment's ordinary documents; not by a lane's estimate of what a real PDF costs.
- **The linear decoded classes, which this ADR does not bound at all.** Named, for the
  adopted version: a compressed **object stream** (`/ObjStm`), decoded whole by
  `PdfReader._get_object_from_stream` during ordinary indirect-object resolution — before
  any per-page loop, so before any total this ADR keeps exists; a font's **`/ToUnicode`
  CMap**; and an **embedded font program** (`/FontFile`, `/FontFile2`, `/FontFile3`),
  whose decode is reached conditionally, in `_font.py` under
  `HAS_FONTTOOLS and font_file and isinstance(self.encoding, str)` and in
  `_cmap._type1_alternative` only when `/ToUnicode` is absent and `/Subtype` is `/Type1`.
  Each is **linear** in its decoded bytes at about **0.04 s per decoded MB**, a factor of
  roughly 120 below the instruction class, which is why the fail-closed direction is not
  taken here and the class is left to the file bound and the read it governs.
  **Fired by either of two things and by nothing else**: a measurement showing one of
  these classes costing what the instruction class costs — per decoded byte, on a document
  inside `fetch_max_file_bytes` — or an adopted release whose **parse order** changes such
  that one of them is parsed as instructions or is reached from inside the walk. Not fired
  by an enumeration argument that the classes exist, which is the ground on which this
  ADR's own earlier draft added a second field and both review lenses refused it, from
  opposite sides, on one round.
- **A decoded stream a later library version reads that §3's walk does not count** (§6).
  This is a narrower residual than it was before the claim was narrowed, because §3's
  counted set is decided by the extraction's own parse rather than by a prediction: a new
  stream kind read *outside* the instruction class is already covered by the deferral
  above, and one parsed as instructions is reached by the walk. What remains is a release
  that parses instructions by a path the walk cannot follow, and §3's fail-closed
  `EXTRACTION_FAILED` is what that meets. Fired by a release doing it — which is why the
  lane records at the code the set it established rather than only here.
- **A per-format decoded bound.** One figure covers every format this rung reads, which
  is right while one format decodes and two do not. Fired by the ADR admitting a format
  whose amplification profile the shared figure serves badly, which §3 already obliges to
  state its decoding step.
- **Any of ADR-0230 §15's deferrals.** None is fired here, and in particular this ADR
  admits no format, no second root, no recursion and no outward kind.

### 11. Scope, and what this records against ADR-0230

**This ADR partially supersedes ADR-0230 in one scope and records nothing against any
other ADR**, and that is a classification of this change and therefore prose rather than
a marked clause (ADR-0089 §1). What follows is the working under ADR-0070 §1's test and
ADR-0082 §1's, clause by clause.

**Why supersession and not amendment.** ADR-0070 §1 admits an in-place amendment only
where *"a reader acting on the ADR would act **identically** before and after"*, and
reconciling an ADR *"with its own text — an internal contradiction"* is named as a case
where they would. §6 **is** internally inconsistent, so the amendment reading is
available on its face and is nonetheless wrong here, on two counts. First, a reader
acting on §6 today is told the file bound covers the extraction's cost, and PR #2014's
round 1 acted on exactly that sentence to justify a page ceiling; after this ADR they
build to the new bound instead. Second, the resolution is not a choice between two
readings already in the text — **neither** limb, kept alone, is what this ADR decides: the
file bound keeps only the first, and the second's job moves, narrowed, to a field ADR-0230
does not have.
That is a change to what was decided, which ADR-0070 §1 sends to a superseding ADR. It is
**partial** because §6's other rulings survive whole, and ADR-0070 §3 makes that form
first-class rather than a discouraged one.

**And the corpus's own precedent does not license the softer label.** ADR-0230 amended
ADR-0226 §2's membership sentence when it added a third `ReadKind`, and could, because
ADR-0226 §1 says in terms that *"A later kind is an **additive entry** to this
enumeration"* — the earlier ADR provided for the addition, so its reader was never led to
refuse it. §6 says no such thing about its bounds. It says *"**Two** size bounds"* and
enumerates four `Settings` fields by name, and both review lenses of PR #2014 read that
as closing the set — round 2 refused a fifth bound on it and round 9 refused a repair on
it. A reader who acted on §6 as written refused what this ADR requires.

**The three sentences that move, and what moves in each.**

1. *"`fetch_max_file_bytes`, the file's size on disk, default **4 MiB**, which bounds the
   read **and the extraction's cost**"* — the second limb is replaced by §2's one field.
   The rest of the sentence is not merely intact but is §1's holding: the figure, the
   default and *the file's size on disk* all stand.
   **What replaces the limb is narrower than the limb, and that is the substance of this
   supersession rather than a shortfall in it.** ADR-0230 §6 claimed a bound on *the
   extraction's cost* entire and had none; this ADR claims one on the superlinear part of
   that cost, holds it, and says in terms (§2, §10) that the linear part is unbounded here
   and why. A reader is left with a smaller claim that is true in place of a larger one
   that was not, which is what ADR-0070 §1's *change to what was decided* looks like when
   the change is a retreat to what can be established.
2. *"**Two** size bounds, both `Settings` fields with named defaults, both refused at
   load rather than at the first fetch"* — the count becomes three. The **rulings** in
   that sentence are not replaced and govern the new field: it is a `Settings` field,
   it has a named default, and it is refused at load (§2).
3. *"A file over **either** bound yields a refusal and no record"* — the enumeration
   becomes any of three. Its ruling — **a bound is enforced by refusing, never by
   truncating** — is not replaced but extended, and §2's bound is subject to it entire:
   no prefix, no first page, no first *n* bytes, no abridgement, no truncation flag.

**Clauses a reader would expect to have moved, and which did not.** Each is checked
against ADR-0082 §1's test — *would a reader holding only ADR-0230 now act differently,
or read the clause more widely than it now holds?* — and each comes out **no**, so no
record is owed for it and stating that is the point of this paragraph.

- **§6's stated-domain clause.** It reads *"**Every `Settings` field this ADR adds** has
  a stated domain"* and names the four. That sentence is about the fields **ADR-0230
  adds**; `fetch_max_decoded_bytes` is not one, and §2 above states its own domain in the
  same form and refuses it at the same point. Nothing in the clause becomes false or
  over-wide.
- **§6's `FetchRefusal` closure.** *"The enumeration is closed and no lane adds a sixth
  without the ADR that decides it"* — §4 adds none, and the every-member-is-reachable
  clause is unaffected because `TOO_LARGE` was already reachable.
- **§6's PDF paragraph.** The shape it fixes for the adoption is untouched and is
  load-bearing: §5 rests on *deterministic for a given file* to refuse a deadline, and §6
  rests on the adoption being this system's to bound.
- **§4 entire.** Its bounded-read clause is what §1 keeps `fetch_max_file_bytes` for; its
  *"Every bound is re-applied at `fetch` and none is carried from the listing"* governs
  the new bound and is cited in §3; its `fetch_max_content_bytes` clause is unchanged.
- **§9 entire** (§7 above), and §§1, 2, 3, 5, 7, 8, 10, 11, 12, 15 and 16, none of which
  says anything about what bounds an extraction.
- **§13 and §14 are stacked additions, not amendments.** §13 says *"Three lanes, in
  order, each briefed from **this ADR's** merged text"* — a true statement about
  ADR-0230's lanes, which §9 above does not join; the lane §9 charges is briefed from
  **this** ADR's text and named here. §14 says *"The implementing lanes owe tests for each
  of the following"* — every item stays owed, and §8 above adds items in the ADR that
  makes them. Neither sentence becomes false or over-wide, which is ADR-0082 §1's
  *stacked addition*: recorded in the ADR that makes it and nowhere else.

**Where the record lives, and why no dated note is written on ADR-0230.** ADR-0230's
`Status` line reads `Accepted`, so it takes the leading `Partially superseded by` token
and the scope in the parenthesis, which is ADR-0001's mechanism and the template's. No
appended dated note accompanies it: ADR-0070 §1's dated note is the append-only form of
an **amendment** — *"A permitted amendment is append-only in mechanism, too. It is
recorded as an appended, dated note"* — and ADR-0082 §1's *"and in its appended dated
note"* is stated inside that frame, its own subject being a later ADR that *"amends a
named clause"*. This is a supersession, and the corpus's own practice is the same: when
ADR-0230 partially superseded ADR-0092 §3 it wrote the `Status` line and no note, while
its **amendments** of ADR-0226 and ADR-0228 each wrote one. ADR-0082 §1 also says where
the judgement belongs — *"The judgement is made in the later ADR's text, which is where
it is reviewed"* — and that is this section.

**Nothing is recorded against ADR-0093, ADR-0024, ADR-0026, ADR-0015, ADR-0137 or
ADR-0089.** Each is cited for what it rules and none of their sentences becomes false:
ADR-0093 §5 is applied in the borrowed form ADR-0230 §6 already borrowed it; ADR-0024 §3
is cited for the distinction it draws and is not extended to `pypdf`; ADR-0026 is
declined a seam rather than changed; ADR-0137 §1 classifies §9's lane and is unaffected
by the classification.

**Milestone numbering.** #1908's milestones were renumbered globally on 2026-09-03
(*"1→27, 2→28, 3→29, 4→30"*), and this ADR uses **29** as ADR-0230 does.

## Consequences

**The mechanism's most visible number goes on meaning what it says.** An operator who
sets `fetch_max_file_bytes` to 4 MiB admits files of 4 MiB, checkable in a directory
listing, and the claim that this bounds the extraction's cost is gone from the corpus
rather than left standing and false.

**A fetch's worst case on the amplified quantity becomes a number chosen from a
measurement.** It was minutes, bounded by nothing this system owns; it becomes a few
seconds at the default, and the superlinearity is written down so an operator raising the
figure knows what they buy.

**The audit gets coarser in one respect and this is the price.** Three bounds report one
class, so a deployment learns that a bound is set below its documents without learning
which. §10 defers the finer statement and names what would fire it.

**One `Settings` field is added to a mechanism that is off by default**, so no
deployment's behaviour changes until a root is configured. A configured one sees no change
unless a document parses more than thirty-two bytes of operators per byte of text.

**The linear decoded classes are left unbounded, and that is the honest half of this
ADR.** An object stream, a `/ToUnicode` CMap and an embedded font program are still
decoded without a figure of this system's own governing them; what governs them is
`fetch_max_file_bytes` and the read it bounds, and their measured cost of about 0.04 s per
decoded MB is why that is tolerable rather than why it is complete. An earlier draft
bounded them with a second field and could not state the set soundly — one class is
decoded before any extraction loop exists, another only under conditions the extraction
often does not meet — so what this ADR carries instead is a claim it can hold plus a
deferral naming exactly what would fire it (§10). **That trade is the point of the ADR,
not a residue of it**: a smaller true claim beats the larger false one ADR-0230 §6 made.

**Two files outside `readers/` move, and both are load-bearing.**
`app/composition.py` passes the figure to the fetcher — without which the field exists
and enforces nothing — and `core/types.py`'s `TOO_LARGE` docstring gains its third cause,
without which the contract a consumer reads carries a false enumeration. Neither changes a
shape, so nothing versioned moves.

**The extractor gains a walk, which is the largest thing this decision costs.** Counting
what an extraction *will* parse means following the invocation graph rather than reading
one field, and §3 requires it because two measured documents defeat everything simpler:
the count cannot be `/Contents`, and it cannot charge a repeatedly invoked form once. The
walk is bounded by the bound, so it does not become a second unbounded traversal, and
§8's arms 2, 3, 4 and 10 are what fail an implementation that skips it, that
over-approximates it, or that charges a resource stream into it.

**A legitimate document can now be refused, and that direction is chosen.** A report
whose per-page graphics push its instruction total over 1 MiB is refused with 20 KB of
text, and the operator raises that figure. ADR-0230 §6 takes that direction for its own
bounds — *"a legitimate local configuration refused until the lane can establish it — a
configuration error a deployment can see and fix"* — and §9's audit is where a deployment
sees it. §10 defers raising the default until there is evidence rather than an estimate.

**One more thing has to be stated by any ADR admitting a format** — what its decoding
step produces for this bound. That is a small standing cost on a future
decision, taken deliberately, because the alternative is a format admitted with no figure
and a bound that silently does not apply to it.

**Two residuals are disclosed rather than closed.** One stream's decoded bytes are still
materialised before the bound refuses them, at a ceiling a ranged dependency owns — one
stream instead of a page's worth or a document's, and memory rather than time. And a
release that parsed instructions by a path §3's walk cannot follow would be a hole the
walk does not see, which §3's fail-closed branch meets and §10 carries. The general answer
to both, and to the deferred linear class, is the out-of-process extraction §10 defers,
which bounds the work rather than its inputs.

## Alternatives considered

**Redefine `fetch_max_file_bytes` as a bound on the bytes the extractor consumes.**
Rejected on four grounds, in §1: an operator can see a size on disk and cannot see a
decoded size; ADR-0230 §4's bounded-read clause would be left with no figure, so a second
field has to be invented anyway; every configured deployment's value would silently
change meaning; and the field's own name and stated domain would become false, which is
the state this ADR exists to leave.

**A deadline on the extraction, instead of or beside the byte bound.** Rejected in §5. It
has no enforcement point the byte bound lacks — the 313 s is one uninterruptible call on
a single-page document, and the one library interface that looked like a way in was
measured not to be — and it would trade ADR-0230 §6's *deterministic for a given file*
for that nothing.

**A second decoded bound, on the resource streams — which an earlier draft of this ADR
decided and both required review lenses then refused, from opposite sides, on one round.**
Rejected, and recorded here rather than dropped, because the reason is the whole of why §2
has one field. A second bound has to enumerate the streams the extraction reads, and that
enumeration is not stable in either direction: a compressed `/ObjStm` is decoded whole
during ordinary indirect-object resolution — before any per-page loop, so **before any
total exists to compare it against** — while an embedded font program is decoded only
under conditions (`HAS_FONTTOOLS`, a string encoding, or an absent `/ToUnicode` on a
`/Type1` font) that an ordinary document often does not meet, so the bound would refuse on
bytes never read. Three successive rounds falsified three successive enumerations. And the
prize is small: the class is linear at about 0.04 s per decoded MB, a factor of roughly
120 below the operators. So the class is **deferred by name** in §10 with what fires it,
rather than bounded by a clause that cannot be stated truly.

**Count at the decode itself rather than predicting it** — a counting seam at
`EncodedStreamObject.get_data()`, through which `pypdf` funnels every stream decode.
Rejected here and **not** rejected on the merits, which is worth the distinction. It would
count exactly what the process decodes, in order, including `/ObjStm` and including only
the conditional font reads that actually happen — dissolving both directions of the
problem above. But `get_data()` **caches**, so it counts one decode per stream and misses
every *re-parse* of already-decoded bytes: the repeated-form document (126.6 s on 105 KB
of distinct bytes) and the per-page font re-read are exactly that, and they are the cases
§3 exists for. Making it sound needs a second counter at the parse seam — the walk again —
plus a seam the library does not obviously offer without reaching into internals. It is a
larger change than this ADR's question, and §10's out-of-process deferral is the general
answer to the class it would serve.

**A sixth `FetchRefusal` member for the decoded case.** Rejected in §4 on ADR-0230 §6's
own two grounds: the enumeration is closed and each member owes a reachability arm, and a
class meaning *small on disk, large decoded* discloses a property of the file's contents
to a caller who is owed a class and nothing more.

**Derive the bound from `fetch_max_content_bytes` — a multiplier rather than a field.**
Rejected in §2. The relation is the *working* for the default and not the rule: an
operator raising the text bound to fit longer documents would silently multiply what an
extraction may decode, and an operator who wanted the second without the first could not
have it. ADR-0230 §6's shape is a named default per field, and this follows it.

**A ceiling on the page count.** Rejected before this ADR: it is PR #2014's round-1
repair, which both required lenses refused at round 2 as an unratified fifth bound with a
number of its own. It is also the wrong quantity — the measured document has **one**
page — and #2015 recorded and closed the page-tree question separately, on the adopted
library's own three traversal guards, which Lane C1 pinned with a test.

**Count the page's `/Contents` and stop there** — the lifted repair's own accounting.
Rejected on measurement, in Context and §3: a 12 KB document whose `/Contents` decodes to
ten bytes puts 4 MB of operators in a Form XObject and costs 33.9 s, because
`extract_text` descends into forms. This is the shape a bound is most likely to be
implemented as, which is why §8 arm 2 exists rather than a sentence saying not to.

**Count each distinct decoded stream once.** Rejected on measurement, in §3: a 1.2 KB
document invoking one 100 KB form five hundred times has 105 KB of distinct decoded bytes
and costs 126.6 s, because the adopted version's cycle guard refuses a *re-entrant* form
and not a repeated one. The counted quantity is bytes **parsed**, and a form parsed five
hundred times is charged five hundred times.

**Enforce `fetch_max_content_bytes` per text-block flush instead, through
`extract_text(visitor_text=…)`.** Rejected, and Lane C1's measurement is half the reason:
a single `BT … ET` block holding 90,909 `Tj` operators calls the visitor twice, both after
the parse, so the visitor cannot reach #2022's document at all. The other half is that a
form carrying no text emits no flush, so a page invoking such a form five hundred times
would pass a text-flush guard while parsing 50 MB. A guard that two of the three measured
documents walk straight past is not a bound.

**Have the walk lex content streams itself, rather than using the library's parser.**
Rejected in §3, at the cost of a second parse of the admitted document. A page may carry
the literal text `(Do)` with no form anywhere, and a form may be named in resources the
page inherits through the page tree rather than in a dictionary of its own; both are
ordinary documents, and a walk that answered either differently from the extraction would
over-refuse the first and under-count the second. Two grammars for one question is the
drift `scripts/adr_status.py` exists to end one directory over, and the review round that
found this ADR's first draft of the clause found exactly those two cases.

**Rely on `pypdf`'s `ZLIB_MAX_OUTPUT_LENGTH` and call the seam bounded.** Rejected in §6.
It bounds memory and not time, per stream and not in aggregate, and it is carried by a
resolution rather than by anything this project declares — `pypdf` is adopted ranged,
outside ADR-0024 §3's exact-pinned set.

**Leave §6 alone and fix nothing, on the ground that the fetcher is off by default.**
Rejected. It is true that `fetch_root_path` defaults unset and that a merged Lane C1 is
*"a fetcher nothing calls"* (ADR-0230 §13), which is why C1 could merge with the defect
disclosed. It stops being true the moment a deployment configures a documents root — and
a documents root is exactly where a PDF that arrived by email lands, which is the case
#1908's milestone 29 exists to serve.
