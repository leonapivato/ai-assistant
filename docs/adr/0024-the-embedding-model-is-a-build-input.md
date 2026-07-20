# 24. The embedding model ships in the wheel, pinned and verified at build time

- Status: Proposed
- Date: 2026-07-20
- Supersedes: ADR-0002's build-backend clause only (`uv_build` → `hatchling`,
  §4); its other stack decisions are unchanged. On acceptance, following the
  ADR-0017 §7 precedent, ADR-0002's `Status` line becomes `Accepted, partially
  superseded by ADR-0024 (build-backend clause)` and a dated note is appended to
  it identifying the replaced clause — the status change ADR-0001 requires, not
  merely a note.

## Context

[ADR-0006](0006-embedding-seam.md) §2 makes on-device embedding the default so
that "memory content never leaves the device just to be indexed". True, and this
ADR does not disturb it — *on-device* describes where inference runs, not where
the model came from, and the model comes over the network.
[ADR-0017](0017-egress-boundaries.md) §2 **declares** that fetch as `models/`
transmission and declines to authorise it (issue #89). Nothing has covered it
since. This ADR is the rule.

### What actually happens today

Verified against the installed `fastembed` 0.8.0, for the default model
`BAAI/bge-small-en-v1.5`:

- **The pin cannot be supplied from outside.** `OnnxTextEmbedding.__init__`
  calls `self.download_model(desc, cache_dir, local_files_only=...,
  specific_model_path=...)` and drops `**kwargs` on the way. There is no
  supported path for a caller to pass `revision` through `TextEmbedding`. This
  closes an option empirically rather than by argument, and it is the single
  most important fact in this document.
- **No revision or integrity pin.** `snapshot_download` is called with no
  `revision`, so every install takes whatever the repo's default branch holds;
  verification compares file *size* and HF's `blob_id`, both from the same host
  in the same session — self-consistency with what the server just said, not a
  known-good digest. None is pinned anywhere.
- **One source, but not one host.** The description carries only
  `hf="qdrant/bge-small-en-v1.5-onnx-q"`, so the recipient is `huggingface.co`
  *plus* whatever Xet store the Hub names at transfer time (`hf-xet` is enabled by
  default).
- **The cache is the system temp directory** (`tempfile.gettempdir()`), not the
  application data directory ADR-0004 §2 requires. **So this was never a
  first-run event** — the 64 MiB fetch recurs whenever `/tmp` is cleared.

### Does ADR-0004 §2 need amending?

No. Issue #89's second option proposed widening §2 to admit an artifact-repository
recipient, but §2 governs sending **user data** off-device and this request
carries none — only transport metadata (source IP, timing, the fact of the
fetch). Reading §2's recipient clause onto a no-user-data fetch would widen a
ratified clause by assertion, the move ADR-0017 §5 refuses. The counter-reading —
that "this install fetched this model" is user-adjacent — is fair, but nothing
turns on it under this ADR: no runtime artifact fetch happens at all (§1, §6).

### What it costs to ship the model instead

Measured, not estimated:

| | bytes | |
|---|---:|---|
| current wheel | 124,368 | 0.1 MiB |
| artifact, raw (5 files fastembed requests) | 67,179,163 | 64.1 MiB |
| **wheel with the artifact included** | **61,262,350** | **58.4 MiB** |
| PyPI default per-file limit | 104,857,600 | 100 MiB |
| **headroom** | **43,595,250** | **41.6 MiB** |

The wheel was built to measure this, not calculated. The artifact is fp16 ONNX
weights (no quantization operators, and its size matches fp16 arithmetic to
within graph overhead — despite the source repo being named `…-onnx-Q`) and
deflates to only 91.1% of raw, so almost none of it compresses away. 58.4% of the
limit is the honest figure; "thin" was wrong.

**Crossing the limit is a publish-time failure.** A file over 100 MiB is rejected
by PyPI's upload API (remedy: a limit increase, granted routinely, or a data-only
package); at 58.4 MiB, with the sdist carrying the same artifact (§4), both
published files sit well under it. The release procedure size-checks each before
uploading. Because both files carry the model, no partial release can resolve to
a fetching install — which is the failure the earlier categorical "no
user-visible breakage" claim missed, now closed rather than merely mitigated.

## Decision

### 1. The rule

**No `ai_assistant` runtime code fetches a model artifact. The on-device
embedding model is a build input: pinned to an immutable revision, verified
against a recorded digest at build time, and shipped inside the wheel.**

There is no arbitrary-model escape hatch: `FastEmbedEmbedder` serves only the
vendored model (§6), so the rule is unconditional rather than scoped to a
"default" among many. It amends nothing — ADR-0004 §2 and ADR-0017 §1 still
govern user-data egress — but is stricter than what ADR-0017 §2 left open: there
is no runtime artifact egress to authorise, so the #89 gap closes rather than
being managed.

### 2. The pin is part of the embedding space

The pin is a commit SHA and a SHA-256 per file, recorded as constants in the
repository. Both are checked at build time; a mismatch fails the build. Changing
which weights this product runs therefore requires a reviewed commit.

**`model_id` incorporates a digest of the verified artifact manifest, not just
the model name.** ADR-0006 §4 requires a store to detect a model change and
re-embed; a `model_id` of `BAAI/bge-small-en-v1.5` cannot, because changing the
weights leaves the name and 384 dimensions identical, so `SqliteMemoryStore`
would rank existing vectors against queries from new weights — silently, the
corruption §4 exists to prevent. The identity component is a deterministic digest
over the recorded SHA-256 manifest — the *actual bytes shipped* — rather than the
repository revision, which is a separate constant that can drift from the manifest
(a re-pin that changes the digests must change `model_id`, not merely the commit).
This is an implementation change within the existing `Embedder.model_id`
contract, not a Protocol change.

The manifest digest alone is still not a complete key, because §3 makes the
behaviour-affecting dependency stack a *release-bound* variable: a persisted
store that survives an upgrade bumping that stack under unchanged weights (same
manifest) would keep the same `model_id` while its space moved — silent mixing
across the upgrade. So `model_id` also incorporates an identity over the audited
behaviour-affecting versions (§3), advancing whenever any of them does, across
installs *and* across a store's upgrade. Over-triggering a re-embed on a no-op
patch bump is the safe direction; under-triggering is the corruption.

What this still cannot self-certify — that the audit names *every*
behaviour-affecting package (an earlier draft of §3 missed NumPy) — is the
residual, and it is **issue #136**: a behavioural fingerprint measures outputs
instead of enumerating inputs, and generalises to non-fastembed embedders. §4
needs no amendment; on `main` `model_id` is the bare name and detects only name
and dimension, so this is a strict improvement, and gating it on #136's general
solution inverts scope.

Changing `model_id`'s composition owes no new migration contract. `SqliteMemoryStore`
already raises "re-embedding is required" on any `model_id` mismatch (existing §4
behaviour, records intact in the file), and pre-1.0 no released store exists to
migrate (`CONTRIBUTING`: anything may change between minors). A dev store trips
that existing signal and is re-created; automating the re-embed is §4's, not
this ADR's.

### 3. The behaviour-affecting stack is exact-pinned, not ranged

`fastembed>=0.7.0` is too loose to carry this decision — the offline load in §5
leans on `specific_model_path` and the on-disk layout (no stable pre-1.0
contract), and fastembed's source shows a *preprocessing* change with no outward
signal: 0.6 moved several models from CLS to mean pooling, an embedding-space
change from a version bump alone, identical weights and digest.

Pinning fastembed alone is still not enough: it ranges its own behaviour-affecting
dependencies, so a *published wheel* install resolves them fresh and two installs
can produce different vectors under the same weights and `model_id`. The audited
set is `fastembed`, `tokenizers` (preprocessing), `onnxruntime` (inference
kernels) and `numpy` (fastembed normalises the default model's output with
`np.linalg.norm`) — the *published* specifiers exact-pin each to the version the
lockfile already fixes for `uv sync`, so nothing in the space floats within a
release, and a bump to any is a reviewed, release-bound change. This same audited
set feeds §2's `model_id` identity, so a release that bumps it re-embeds.

Pinning *prevents* drift within a release; the `model_id` identity *detects* it
across one. The residual — proving the audit is complete, and a fingerprint
robust to version-vs-behaviour mismatch — is #136.

### 4. The artifact is not committed to git

It is fetched during the build from the pinned revision and verified before
inclusion. Git is the wrong store for a build input already published and
content-addressed elsewhere: committing 58 MiB of incompressible binary would
duplicate it permanently in every clone, and ADR-0015's one-clone-per-agent
model makes that a recurring cost.

**Acquisition stays owned by `models/`; only the trigger moves.** ADR-0006 §3
confines every local-model dependency to `models/`, and `huggingface_hub` is one
— so fetch-and-verify is a `models/`-owned seam, with the import-linter contract
extended to forbid `huggingface_hub` outside `models/` (issue #66's shape) so it
is enforced, not asserted. A thin build-time adapter invokes that seam instead of
`embed` doing so on first use. The egress stays `models/`-owned; only its timing
moves, which reconciles the runtime fetch ADR-0017 §2 recorded without touching
ADR-0017's rule.

**This requires changing the build backend** (the header supersedes ADR-0002's
choice). `uv_build` supports no build hooks; uv's own docs direct projects
needing build scripts to `hatchling`, whose custom hook is the thin adapter
above. That swap changes project packaging, so its blast radius is wider than the
rest of this decision and is the part most worth challenging.

**The release sdist ships the verified artifact too, so no PyPI install path
fetches on a user's machine** — the wheel unpacks it, and a `--no-binary` sdist
build finds it present and skips the fetch. The only build that fetches is one
from a *git checkout* (§4 keeps the artifact out of the tree): a contributor
building the software, whose transport metadata is the same exposure as fetching
any build dependency — not the stored Tier 1 user data ADR-0004 §1 classifies or
§2 governs.

### 5. The default embedder loads the packaged artifact, offline

`FastEmbedEmbedder` is constructed against the packaged files via fastembed's
`specific_model_path`, with `local_files_only=True`. On a *non-empty* batch with
the artifact absent, `embed` raises `ModelError` naming the cause and does not
fetch; `embed([])` stays offline and returns `[]`, preserving the empty-batch
contract, which is checked before any artifact-presence check.

**The existing tests stub the backend and never build or install a
distribution**, so a hook that verifies the wrong bytes, requests the wrong
revision, packages the wrong path, or configures only the wheel ships green. The
implementation PR must add acceptance tests a hook or wiring mistake cannot pass —
at minimum:

- the acquisition seam requests the *recorded commit*, and a moved default branch
  does not change the build; a digest mismatch fails it, leaving nothing staged;
- the wheel **and the sdist** each carry the artifact with every file's SHA-256
  matching the recorded manifest (the verified bytes shipped, not merely *some*
  valid ONNX), and a wheel built from the sdist embeds with the network denied;
- the wheel METADATA carries all four exact pins, and changing any audited
  version *or* any manifest digest independently moves `model_id`;
- a missing artifact raises `ModelError` on a non-empty batch without a socket,
  while `embed([])` returns `[]`.

### 6. The fastembed embedder serves only the vendored model

There is no arbitrary-fastembed-model path. `FastEmbedEmbedder` is bound to the
one vendored, verified model; it does not accept an arbitrary `model` name that
would re-enable fastembed's unpinned download. That is the direct consequence of
"the embedding model is a build input" — there is one build input, not a family.

This is a decision, not a deferral, and it is what closes the path the review
rounds kept flagging. An arbitrary fastembed model reintroduces every problem
this ADR removes at once: an unpinned runtime fetch (§1), no verified digest
(§2), and — because fastembed's API takes no revision — no pinnable weights
identity, so `model_id` cannot be made truthful for it by pinning, only by
*deriving* identity from downloaded content, which is **issue #136**. Rather than
carry a path that fails §1, §2 and ADR-0006 §4, this ADR does not offer one.

A *different* embedding backend remains available where it has a real identity:
the cloud opt-in of ADR-0006 §2, whose provider versions its model. Restoring
multiple *local* models is future work, gated on #136 giving an arbitrary model a
truthful identifier and on a provisioning path that pins it.

### 7. What this ADR does not decide

- **It does not pin transport endpoints** (#83). Not a precondition: a digest
  checked at build time makes a compromised endpoint a failed build rather than
  a bad embedding. Nor is #66, which would let import-linter pin which module
  may hold a network client, making §1 mechanically rather than review-checkable.
- **It does not resolve the licence discrepancy** — Consequences records it as
  work that must complete before publishing.
- **It does not give `model_id` a full behavioural fingerprint** (§2, #136), nor
  restore multiple local models (§6).

## Alternatives considered

**Runtime provisioning: the embedder never fetches; an explicit user step
acquires the artifact.** This ADR's first-draft recommendation, on the sole
ground that 67 MB in the wheel was too expensive. That ground was withdrawn, and
nothing else supported it: provisioning is strictly more code, re-verifies on
every machine what we can verify once, and buys a smaller wheel with a failure in
the user's first session. Its one advantage — costing nothing for users who never
embed on-device — did not outweigh a first run that just works.

**Commit the artifact to git.** Rejected on §4's reasoning: 58 MiB of
incompressible binary permanent in every clone.

**Keep the fetch lazy and pin it in place.** Not available (§Context's first
bullet): it would mean forking or monkeypatching fastembed's download path.

**A separate data-only package behind an `[local-embeddings]` extra.** The
cleanest form, and the right answer if the wheel nears the limit — but it needs a
release pipeline this project does not have, and the measurement shows it is not
needed yet.

## Consequences

- **First run works offline, with no fetch and no second command.** This is the
  decision's main benefit and the thing #89 was ultimately asking for.
- **The strongest case against it: the fetch is relocated, not eliminated.** No
  PyPI install path fetches (wheel and sdist both carry the artifact), but a build
  from a *git checkout* does — so the honest claim is "once per source build,
  never for an install", not "gone". Accepted because that fetch is a contributor
  building the software, verified against a pin, where the eliminated one was an
  unverified runtime fetch on every user's machine.
- **Every install pays 58.4 MiB** (both wheel and sdist), including users on a
  cloud embedder or the lexical `InMemoryMemoryStore`. Accepted deliberately.
- **Licence attribution must be resolved before publishing.** Three sources
  disagree — upstream `BAAI/bge-small-en-v1.5` says MIT, the
  `Qdrant/bge-small-en-v1.5-onnx-Q` card says Apache-2.0, fastembed's metadata
  says `mit` — and that artifact repo carries no `LICENSE` file (our own root
  `LICENSE` is unrelated). Both permit redistribution with attribution, so
  vendoring is permissible, but shipping the weights under our package name means
  shipping correct notices, and someone must determine which governs. This exists
  **only** because we redistribute. A release blocker, not a merge blocker.
- **Model changes become explicit and release-bound.** ADR-0006 §4 already
  requires re-embedding when the model changes; tying that to a release makes it
  visible rather than ambient.
- **Nothing else in the stack has this shape** (checked, per #89's last line):
  `sqlite-vec` bundles `vec0.so`; `tokenizers`, `mmh3`, `py-rust-stemmers` fetch
  nothing lazily; `genai-prices` ships a bundled snapshot (`from_auto_update=False`)
  with an opt-in updater never started by default — latent, filed as #132.
- **Revisit if** the wheel approaches the 100 MiB limit (move to the data-only
  package), if fastembed gains a supported way to pass a revision, or if the
  install-size cost proves to matter more than first-run friction did.
