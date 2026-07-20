# 24. The embedding model ships in the wheel, pinned and verified at build time

- Status: Proposed
- Date: 2026-07-20

## Context

[ADR-0006](0006-embedding-seam.md) §2 makes on-device embedding the default so
that "memory content never leaves the device just to be indexed". That claim is
true and this ADR does not disturb it — *on-device* describes where inference
runs. It says nothing about where the model came from, and the model comes over
the network.

[ADR-0017](0017-egress-boundaries.md) §2 **declares** that fetch as something
`models/` transmits, and deliberately declines to authorise it (issue #89).
Nothing has covered it since. This ADR is the rule.

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

No, and this ADR declines to amend it. Issue #89's second option proposed
widening §2 to admit an artifact-repository recipient. §2 governs sending **user
data** off-device; this request carries none — only transport metadata (source
IP, timing, the fact of the fetch). Reading §2's recipient clause onto a
no-user-data fetch would widen a ratified clause by assertion, the move ADR-0017
§5 refuses. The counter-reading — that "this install fetched this model" is
user-adjacent, so §2's *spirit* reaches it — is fair, but little turns on it:
the default path performs no runtime fetch at all, and the one path that still
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
weights (no quantization operators, size matching fp16 arithmetic to within
graph overhead — 66,465,124 actual against 66,425,856 predicted, despite the
source repo being named `…-onnx-Q`) and deflates to 91.1% of raw, so almost none
of it compresses away. 58.4% of the limit is the honest figure; "thin" was
wrong.

**Crossing the limit is a publish-time failure — but not a harmless one, because
a release is not atomic.** A wheel over 100 MiB is rejected by PyPI's upload API
(remedy: a limit increase, granted routinely, or a data-only package). But files
upload one at a time, so an sdist accepted before the oversized wheel is rejected
leaves a release with no wheel, and `pip` falls back to the sdist and runs the
build — and its fetch — on the user's machine, failing if they are offline. The
release procedure must therefore check the built wheel against the limit *before*
uploading anything. With 41.6 MiB of headroom that is a tripwire, not a live
risk — but the categorical "no user-visible breakage" claim was wrong.

## Decision

### 1. The rule

**On the default embedding path, no `ai_assistant` runtime code fetches a model
artifact. The default model is a build input: pinned to an immutable revision,
verified against a recorded digest at build time, and shipped inside the wheel.**

Scoped to the default path deliberately. Selecting a non-default model (§6) is
an explicit opt-in that leaves this rule's scope and re-enables fastembed's own
download; an unscoped "nothing ever fetches" would be a rule this ADR's own §6
breaks.

It amends nothing: ADR-0004 §2 and ADR-0017 §1 continue to govern user-data
egress, untouched. It is stricter than the rule ADR-0017 §2 left open — on the
default path there is no runtime egress to authorise, so the gap issue #89
identified closes rather than being managed.

### 2. The pin is part of the embedding space

The pin is a commit SHA and a SHA-256 per file, recorded as constants in the
repository. Both are checked at build time; a mismatch fails the build. Changing
which weights this product runs therefore requires a reviewed commit.

**`model_id` incorporates the pinned revision, not just the model name.** This
is the one identity change the pin forces, and its scope is exactly the pin.
ADR-0006 §4 requires a store to detect a model change and re-embed; a `model_id`
of `BAAI/bge-small-en-v1.5` cannot, because bumping the pin changes the weights
while the name and the 384 dimensions stay identical, so `SqliteMemoryStore`
would rank existing vectors against queries from new weights — silently, the
corruption §4 exists to prevent. Folding the revision into `model_id` closes
that. It is an implementation change within the existing `Embedder.model_id`
contract, not a Protocol change.

**It does not claim to fully fingerprint the embedding space, and this ADR does
not try to.** On `main`, `model_id` is the bare model name and captures *no*
runtime-stack version — not the tokenizer's, not fastembed's — so a dependency
change that alters vectors is already undetectable by the store. That is a
pre-existing ADR-0006 §4 gap, independent of how the model is provisioned, and
wants a behavioural fingerprint rather than a pile of version strings. Filed as
**issue #136**; out of scope here. This ADR closes only the revision axis, and
only for the vendored default.

### 3. fastembed is pinned, not ranged

`fastembed>=0.7.0` is too loose to carry this decision — the offline load in §5
leans on `specific_model_path` and the on-disk layout (no stable pre-1.0
contract), and fastembed's source shows a *preprocessing* change with no outward
signal: 0.6 moved several models from CLS to mean pooling, an embedding-space
change from a version bump alone, identical weights and digest.

The defence is to **pin the dependency, not detect the change after the fact.**
The committed lockfile already fixes `fastembed==0.8.0` (and `tokenizers`,
`onnxruntime`) for a `uv sync` install; this ADR additionally tightens the
published runtime specifier to a tested floor and ceiling so a wheel install
cannot silently resolve an unreviewed version. A fastembed bump is then a
reviewed change tied to a release — what "release-bound" means — not an open
range. The residual preprocessing-fingerprint risk is the same #136 gap.

### 4. The artifact is not committed to git

It is fetched during the build from the pinned revision and verified before
inclusion. Git is the wrong store for a build input already published and
content-addressed elsewhere: committing 58 MiB of incompressible binary would
duplicate it permanently in every clone, and ADR-0015's one-clone-per-agent
model makes that a recurring cost.

**This requires changing the build backend.** `uv_build` supports no build hooks
and cannot run code during a build; uv's own documentation directs projects
needing build scripts to `hatchling`. So the backend becomes `hatchling` with a
hook that fetches, verifies, and stages the artifact. That is a backend swap and
a hook file — *not* the release pipeline a data-only package would need — but it
changes project packaging rather than `models/`, so its blast radius is wider
than the rest of this decision, and it is the part most worth challenging.

§1 governs the installed runtime, not builds: a `py3-none-any` wheel unpacks and
fetches nothing, while a from-sdist build runs the hook — and its fetch — on the
user's own machine, under the same pin.

### 5. The default embedder loads the packaged artifact, offline

`FastEmbedEmbedder` is constructed against the packaged files via fastembed's
`specific_model_path`, with `local_files_only=True`. If the artifact is absent —
a source build that skipped the hook — `embed` raises `ModelError` naming the
cause. It does not fall back to fetching.

### 6. A non-default model remains an opt-in that fetches

Only the default is vendored. Configuring a different fastembed model re-enables
fastembed's own unpinned download, with none of §2's guarantees — the same shape
as ADR-0006 §2's opt-in cloud embedder, and documented as such. "Local-first by
default" is a claim about the default.

That opt-in path carries the pre-existing identity gap in full: an unpinned
download resolves whatever the default branch holds, and with `model_id` the
bare name (#136), a store indexed under revision A then re-fetched at B mixes
vectors silently. This ADR does **not** introduce that — it is today's *default*
behaviour, which §2 fixes for the vendored model and cannot fix here, because
fastembed's API takes no revision (§Context). The path exists because ADR-0006
§2 contemplates model choice; a persistent store on a non-default model is
subject to #136 until that gap closes.

### 7. What this ADR does not decide

- **It does not pin transport endpoints** (#83). Not a precondition: a digest
  checked at build time makes a compromised endpoint a failed build rather than
  a bad embedding. Nor is #66, which would let import-linter pin which module
  may hold a network client, making §1 mechanically rather than review-checkable.
- **It does not resolve the licence discrepancy** — Consequences records it as
  work that must complete before publishing.
- **It does not give `model_id` a full behavioural fingerprint** (#136). It
  closes only the revision axis, for the vendored default; the tokenizer and
  preprocessing axes are a pre-existing ADR-0006 §4 gap.

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

**Keep the fetch lazy and pin it in place.** Not available — §Context's first
bullet. It would require forking or monkeypatching fastembed's download path,
more code than §2 and less auditable.

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
- **The build gains a network dependency and a backend change** (`uv_build` →
  `hatchling`). CI has network; a contributor's first build will fetch 64 MiB
  once.
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
