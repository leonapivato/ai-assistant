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
- **One source.** The model description carries only
  `hf="qdrant/bge-small-en-v1.5-onnx-q"`. Some other fastembed models also carry
  a `storage.googleapis.com` URL and fall back to it silently; ours does not.
  The recipient is `huggingface.co`, plus whatever Xet content-addressed store
  the Hub names at transfer time in an `X-Xet-Cas-Url` response header, since
  `hf-xet` is installed and enabled by default.
- **The cache is the system temp directory** — `tempfile.gettempdir()/fastembed_cache`
  unless `FASTEMBED_CACHE_PATH` or `cache_dir` says otherwise. **So this was
  never a first-run event.** The fetch recurs whenever `/tmp` is cleared, and it
  puts 64 MiB outside the single application data directory ADR-0004 §2 requires.

### Does ADR-0004 §2 need amending?

No, and this ADR declines to amend it. Issue #89's second option proposed
widening §2 to admit an artifact-repository recipient. §2 governs sending **user
data** off-device; this request carries none. What it discloses is transport
metadata — source IP, timing, and the fact that this installation fetched this
model. Reading §2's recipient clause onto a no-user-data fetch would widen a
ratified clause by assertion, which is precisely the move ADR-0017 §5 refuses.

The counter-reading is fair and worth recording: "this install fetched this
model" is user-adjacent, so §2's *spirit* arguably reaches it. Nothing turns on
settling it, because under this ADR the runtime performs no fetch at all.

### What it costs to ship the model instead

Measured, not estimated:

| | bytes | |
|---|---:|---|
| current wheel | 124,368 | 0.1 MiB |
| artifact, raw (5 files fastembed requests) | 67,179,163 | 64.1 MiB |
| **wheel with the artifact included** | **61,262,350** | **58.4 MiB** |
| PyPI default per-file limit | 104,857,600 | 100 MiB |
| **headroom** | **43,595,250** | **41.6 MiB** |

The wheel was built to measure this, not calculated. The artifact is
int8-quantized ONNX and deflates to 91.1% of raw, so almost none of its size
compresses away — 58.4% of the limit is the honest figure, and the earlier
characterisation of the headroom as "thin" was wrong.

**What breaks at the limit is a publish-time failure.** A wheel over 100 MiB is
rejected by PyPI's upload API; the maintainer sees it, users never do, and the
remedies (request a limit increase, which PyPI grants routinely, or move to a
data-only package) are available at that point. Nothing fails at install time,
and no user-visible breakage is possible from crossing it.

## Decision

### 1. The rule

**No `ai_assistant` runtime code fetches a model artifact. The default
embedding model is a build input: pinned to an immutable revision, verified
against a recorded digest at build time, and shipped inside the wheel.**

This is a new rule about artifact egress. It amends nothing: ADR-0004 §2 and
ADR-0017 §1 continue to govern user-data egress, untouched. It is also stricter
than the rule ADR-0017 §2 left open — there is no runtime egress to authorise,
so the gap that issue #89 identified closes rather than being managed.

### 2. The artifact is pinned by revision and digest

The pin is a commit SHA and a SHA-256 per file, recorded as constants in the
repository. Both are checked at build time; a mismatch fails the build. Changing
which weights this product runs therefore requires a reviewed commit.

### 3. The artifact is not committed to git

It is fetched during the build from the pinned revision and verified before
inclusion. Git is the wrong store for a build input that is byte-identical to
something already published and content-addressed elsewhere — we already have an
exact name for it, and committing the bytes would duplicate that permanently, in
every clone, forever. ADR-0015's one-clone-per-agent model makes clone cost
recurring rather than one-off.

**This requires changing the build backend.** `uv_build` supports no build hooks
and cannot run code during a build; uv's own documentation directs projects
needing build scripts to `hatchling`. So the backend becomes `hatchling` with a
build hook that fetches, verifies, and stages the artifact.

That is a backend swap and a hook file — deliberately *not* the release pipeline
a separate data-only package would need. This ADR does not propose one.

### 4. The default embedder loads the packaged artifact, offline

`FastEmbedEmbedder` is constructed against the packaged files via fastembed's
`specific_model_path`, with `local_files_only=True`. If the artifact is absent —
a source build that skipped the hook — `embed` raises `ModelError` naming the
cause. It does not fall back to fetching.

### 5. A non-default model remains an opt-in that fetches

Only the default is vendored. Configuring a different fastembed model is an
explicit choice that re-enables fastembed's own unpinned download, and is
documented as such — the same shape as ADR-0006 §2's opt-in cloud embedder.
§1's rule governs the default path, which is what "local-first by default"
means.

### 6. What this ADR does not decide

- **It does not pin transport endpoints.** Issue #83 covers that for `models/`
  generally. Not a precondition here: a digest checked at build time makes a
  compromised endpoint a failed build rather than a bad embedding.
- **It does not resolve the licence discrepancy** — §Consequences records it as
  work that must complete before publishing.
- Issue #66 would let import-linter pin which module may hold a network client,
  making §1 mechanically checkable rather than review-checkable. Also not a
  precondition.

## Alternatives considered

**Runtime provisioning: the embedder never fetches, and an explicit user-run
step acquires the artifact.** This was this ADR's recommendation in its first
draft, on the sole ground that 67 MB in the wheel was too expensive. That ground
was withdrawn, and nothing else supported it: provisioning is strictly more code
(a provisioning entry point, `huggingface_hub` as a direct dependency, a CLI
command, a cache-location decision), it makes every user's machine re-verify
what we could verify once, and it moves a failure into the user's first session
in exchange for a wheel that is 58 MiB smaller. Its one real advantage — an
install that costs nothing for users who never embed on-device — did not survive
being weighed against a first run that simply works.

**Commit the artifact to git.** Avoids the backend change and any network at
build time. Rejected on §3's reasoning: 58 MiB of incompressible binary,
permanent in history, paid by every clone.

**Keep the fetch lazy and pin it in place.** Not available — §Context's first
bullet. It would require forking or monkeypatching fastembed's download path,
which is more code than §2 and less auditable.

**A separate data-only package behind an `[local-embeddings]` extra.** The
cleanest form, and the right answer if the wheel ever approaches the limit. It
needs a release pipeline this project does not have, and §Context's measurement
shows it is not needed yet.

## Consequences

- **First run works offline, with no fetch and no second command.** This is the
  decision's main benefit and the thing #89 was ultimately asking for.
- **The strongest case against it: the fetch is relocated, not eliminated.** A
  build from a clean checkout reaches `huggingface.co`, so someone building from
  source offline cannot. The honest claim is that the fetch now happens once, on
  a build machine, verified by us against a pin — not that it is gone. Accepted
  because the property users are owed is that *their* machine stays local-first,
  and because a build-time fetch is verified where a runtime one was not.
- **Every install pays 58.4 MiB**, including users on a cloud embedder or the
  lexical `InMemoryMemoryStore`. Accepted deliberately.
- **Licence attribution must be resolved before publishing.** Three sources
  disagree: upstream `BAAI/bge-small-en-v1.5` declares MIT, the
  `Qdrant/bge-small-en-v1.5-onnx-Q` card declares Apache-2.0, and fastembed's
  own model description says `mit`. The repo carries no `LICENSE` file. Both
  licences permit redistribution with attribution, so vendoring is permissible
  either way — but shipping the weights under our package name means shipping
  correct notices, and someone must determine which governs. This obligation
  exists **only** because we redistribute; it does not arise under a runtime
  fetch. Tracked as a release blocker, not a merge blocker.
- **The build gains a network dependency and a backend change** (`uv_build` →
  `hatchling`). CI has network; a contributor's first build will fetch 64 MiB
  once.
- **Model changes become explicit and release-bound.** ADR-0006 §4 already
  requires re-embedding the whole store when the embedding model changes, so
  this is already a coordinated migration; tying it to a release makes it
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
