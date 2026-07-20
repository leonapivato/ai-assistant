# 24. The embedding model ships in the wheel, pinned and verified at build time

- Status: Proposed
- Date: 2026-07-20
- Supersedes: ADR-0002's build-backend choice only (`uv_build` → `hatchling`,
  §4). ADR-0002's stack decisions are otherwise unchanged; its status note is
  appended on acceptance.

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
- **No revision pin.** Consequently `snapshot_download` is called with no
  `revision`. `model_info(...).sha` is resolved, but used only for the tree
  listing. Every install takes whatever that repo's default branch holds at
  that moment.
- **No integrity pin.** Verification compares file *size* and HF's `blob_id`,
  both obtained from the same host in the same session — self-consistency with
  what the server just said, not agreement with a known-good value. Re-checking
  a warm cache compares size alone. No digest is pinned anywhere.
- **One source, but not one host.** The description carries only
  `hf="qdrant/bge-small-en-v1.5-onnx-q"`, so the recipient is `huggingface.co`
  *plus* whatever Xet content-addressed store the Hub names at transfer time in
  an `X-Xet-Cas-Url` header (`hf-xet` is installed and enabled by default).
- **The cache is the system temp directory** (`tempfile.gettempdir()`), not the
  application data directory ADR-0004 §2 requires. **So this was never a
  first-run event** — the 64 MiB fetch recurs whenever `/tmp` is cleared.

### Does ADR-0004 §2 need amending?

No. Issue #89's second option proposed widening §2 to admit an artifact-repository
recipient, but §2 governs sending **user data** off-device and this request
carries none — only transport metadata (source IP, timing, the fact of the
fetch). Reading §2's recipient clause onto a no-user-data fetch would widen a
ratified clause by assertion, the move ADR-0017 §5 refuses. The counter-reading —
that "this install fetched this model" is user-adjacent — is fair, but little
turns on it: the default path performs no runtime fetch, and the one that still
does (§6) is reached only by a user who asked for it.

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

**Crossing the limit is a publish-time failure — but not a harmless one, because
a release is not atomic.** A wheel over 100 MiB is rejected by PyPI's upload API
(remedy: a limit increase, granted routinely, or a data-only package). But files
upload one at a time, so an sdist accepted before the wheel fails — rejected for
size *or* lost to a transient upload error — leaves a release with no wheel, and
`pip` falls back to the sdist and runs the build (and its fetch) on the user's
machine, failing if they are offline. The release procedure must therefore
size-check the wheel first *and* upload it before the sdist, so no partial
release can resolve to a fetching sdist. With 41.6 MiB of headroom the size limit
is a tripwire, not a live risk — but the categorical "no user-visible breakage"
claim was wrong.

## Decision

### 1. The rule

**On the default embedding path, no `ai_assistant` runtime code fetches a model
artifact. The default model is a build input: pinned to an immutable revision,
verified against a recorded digest at build time, and shipped inside the wheel.**

Scoped to the default path deliberately: a non-default model (§6) is an opt-in
that re-enables fastembed's own download, so an unscoped "nothing ever fetches"
would be a rule §6 breaks. It amends nothing — ADR-0004 §2 and ADR-0017 §1 still
govern user-data egress — but is stricter than what ADR-0017 §2 left open: on the
default path there is no runtime egress to authorise, so the #89 gap closes
rather than being managed.

### 2. The pin is part of the embedding space

The pin is a commit SHA and a SHA-256 per file, recorded as constants in the
repository. Both are checked at build time; a mismatch fails the build. Changing
which weights this product runs therefore requires a reviewed commit.

**`model_id` incorporates the pinned revision, not just the model name.**
ADR-0006 §4 requires a store to detect a model change and re-embed; a `model_id`
of `BAAI/bge-small-en-v1.5` cannot, because bumping the pin changes the weights
while the name and 384 dimensions stay identical, so `SqliteMemoryStore` would
rank existing vectors against queries from new weights — silently, the corruption
§4 exists to prevent. Folding the revision in closes that: an implementation
change within the existing `Embedder.model_id` contract, not a Protocol change.

**It does not claim to fully fingerprint the embedding space.** On `main`,
`model_id` is the bare model name and captures *no* runtime-stack version — not
the tokenizer's, not fastembed's — so a vector-altering dependency change is
already undetectable, on every provisioning path. That pre-existing ADR-0006 §4
gap wants a behavioural fingerprint and is filed as **issue #136**. It needs no
amendment from this ADR: §4 gives the store a *detection* mechanism, not a
perfect fingerprint, and on `main` detects only name and dimension — so adding
the revision is a strict improvement, never a regression, and completing §4's
detection is #136's work.

### 3. fastembed is pinned, not ranged

`fastembed>=0.7.0` is too loose to carry this decision — the offline load in §5
leans on `specific_model_path` and the on-disk layout (no stable pre-1.0
contract), and fastembed's source shows a *preprocessing* change with no outward
signal: 0.6 moved several models from CLS to mean pooling, an embedding-space
change from a version bump alone, identical weights and digest.

The defence is to **pin the dependency, not detect the change after the fact.**
The committed lockfile already fixes `fastembed==0.8.0` (and `tokenizers`,
`onnxruntime`) for a `uv sync` install; this ADR additionally makes the
*published* specifier the exact pin `fastembed==0.8.0`, not a `<0.9` range — a
range lets a resolver prefer a later 0.8.x that changes preprocessing under an
unchanged `model_id`, which is the whole failure this section is about. A
fastembed bump is then a reviewed change to that constant, tied to a release —
what "release-bound" means. The residual preprocessing-fingerprint risk is the
same #136 gap.

### 4. The artifact is not committed to git

It is fetched during the build from the pinned revision and verified before
inclusion. Git is the wrong store for a build input already published and
content-addressed elsewhere: committing 58 MiB of incompressible binary would
duplicate it permanently in every clone, and ADR-0015's one-clone-per-agent
model makes that a recurring cost.

**Acquisition stays owned by `models/`; only the trigger moves.** ADR-0006 §3
confines every local-model dependency to `models/`, and the fetch client
(`huggingface_hub`) is one — so the fetch-and-verify logic is a `models/`-owned
seam, and the import-linter contract is extended to forbid `huggingface_hub`
outside `models/` (issue #66's shape) so this is enforced, not merely stated.
What changes is *when* that seam runs: a thin build-time adapter invokes it
instead of `embed` doing so on first use. This also updates the fact ADR-0017 §2
recorded — the default backend's *runtime* first-use fetch — without touching
ADR-0017's rule: the egress is still `models/`-owned, it just happens at build.

**This requires changing the build backend** (the header supersedes ADR-0002's
choice). `uv_build` supports no build hooks; uv's own docs direct projects
needing build scripts to `hatchling`, whose custom hook is the thin adapter
above. That swap changes project packaging, so its blast radius is wider than the
rest of this decision and is the part most worth challenging.

§1 governs the installed runtime, not builds: a `py3-none-any` wheel unpacks and
fetches nothing, while a from-sdist build runs the hook — and its fetch — on the
user's own machine, under the same pin.

### 5. The default embedder loads the packaged artifact, offline

`FastEmbedEmbedder` is constructed against the packaged files via fastembed's
`specific_model_path`, with `local_files_only=True`. If the artifact is absent —
a source build that skipped the hook — `embed` raises `ModelError` naming the
cause. It does not fall back to fetching.

**The existing tests stub the backend and never build or install a
distribution**, so a hook that verifies the wrong bytes or packages the wrong
path ships green. The implementation PR must add acceptance tests a hook mistake
cannot pass: a digest mismatch fails the build leaving nothing staged, the built
wheel contains the artifact at the expected path, the real default embedder
embeds with the network denied, and a missing artifact raises `ModelError`
without opening a socket.

### 6. A non-default model remains an opt-in that fetches

Only the default is vendored. Configuring a different fastembed model re-enables
fastembed's own unpinned download, with none of §2's guarantees — the same shape
as ADR-0006 §2's opt-in cloud embedder, and documented as such. "Local-first by
default" is a claim about the default.

That opt-in path carries the identity gap in full — an unpinned download can
serve different weights under an unchanged `model_id`, mixing vectors silently.
This ADR does **not** introduce it: that is today's *default* behaviour, which §2
fixes for the vendored model and cannot fix here (fastembed's API takes no
revision). A persistent store on a non-default model is subject to #136.

### 7. What this ADR does not decide

- **It does not pin transport endpoints** (#83). Not a precondition: a digest
  checked at build time makes a compromised endpoint a failed build rather than
  a bad embedding. Nor is #66, which would let import-linter pin which module
  may hold a network client, making §1 mechanically rather than review-checkable.
- **It does not resolve the licence discrepancy** — Consequences records it as
  work that must complete before publishing.
- **It does not give `model_id` a full behavioural fingerprint** (§2, #136).

## Alternatives considered

**Runtime provisioning: the embedder never fetches, and an explicit user-run
step acquires the artifact.** This ADR's recommendation in its first draft, on
the sole ground that 67 MB in the wheel was too expensive. That ground was
withdrawn, and nothing else supported it: provisioning is strictly more code (an
entry point, `huggingface_hub` as a direct dependency, a CLI command, a
cache-location decision), it makes every user's machine re-verify what we can
verify once, and it buys a 58 MiB-smaller wheel with a failure in the user's
first session. Its one real advantage — costing nothing for users who never
embed on-device — did not survive being weighed against a first run that works.

**Commit the artifact to git.** Avoids the backend change and build-time
network, but rejected on §4's reasoning: 58 MiB of incompressible binary
permanent in every clone.

**Keep the fetch lazy and pin it in place.** Not available (§Context's first
bullet): it would mean forking or monkeypatching fastembed's download path.

**A separate data-only package behind an `[local-embeddings]` extra.** The
cleanest form, and the right answer if the wheel ever approaches the limit. It
needs a release pipeline this project does not have, and §Context's measurement
shows it is not needed yet.

## Consequences

- **First run works offline, with no fetch and no second command.** This is the
  decision's main benefit and the thing #89 was ultimately asking for.
- **The strongest case against it: the fetch is relocated, not eliminated.** A
  wheel install fetches nothing, but a from-sdist build runs the hook on the
  user's own machine. The honest claim is that the fetch happens once per build
  and never for a wheel install — not that it is gone. Accepted because
  `py3-none-any` means every user who does not deliberately opt out gets the
  wheel, and because a build-time fetch is verified where a runtime one was not.
- **Every install pays 58.4 MiB**, including users on a cloud embedder or the
  lexical `InMemoryMemoryStore`. Accepted deliberately.
- **Licence attribution must be resolved before publishing.** Three sources
  disagree: upstream `BAAI/bge-small-en-v1.5` declares MIT, the
  `Qdrant/bge-small-en-v1.5-onnx-Q` card declares Apache-2.0, fastembed's model
  description says `mit`. That artifact repository carries no `LICENSE` file (only
  the card field), and this project's own root `LICENSE` is unrelated and does
  not discharge the obligation. Both permit redistribution with attribution, so
  vendoring is permissible either way, but shipping the weights under our package
  name means shipping correct notices and someone must determine which governs.
  This obligation exists **only** because we redistribute. A release blocker, not
  a merge blocker.
- **A contributor's first build fetches 64 MiB** once (CI has network).
- **Model changes become explicit and release-bound.** ADR-0006 §4 already
  requires re-embedding when the model changes; tying that to a release makes it
  visible rather than ambient.
- **Nothing else in the stack has this shape.** Checked, per #89's last line:
  `sqlite-vec` bundles `vec0.so` in its wheel; `tokenizers`, `mmh3` and
  `py-rust-stemmers` fetch nothing lazily; `genai-prices` (via `pydantic-ai`)
  ships a bundled price snapshot and returns it with `from_auto_update=False` —
  its updater reaches `raw.githubusercontent.com` but is opt-in and never
  started by default. That last one is a latent instance and has issue #132.
- **Revisit if** the wheel approaches the 100 MiB limit (move to the data-only
  package), if fastembed gains a supported way to pass a revision, or if the
  install-size cost proves to matter more than first-run friction did.
