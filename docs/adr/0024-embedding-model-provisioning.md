# 24. The default embedder is provisioned, not self-downloading

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

- **One source.** Its description carries only `hf="qdrant/bge-small-en-v1.5-onnx-q"`
  (~67 MB, `model_optimized.onnx`). Some other fastembed models also carry a
  `storage.googleapis.com` URL and fall back to it silently; ours does not, so
  the recipient is `huggingface.co` — plus whatever Xet content-addressed store
  the Hub names at transfer time in an `X-Xet-Cas-Url` response header, since
  `hf-xet` is installed and enabled by default.
- **No revision pin.** `ModelManagement.download_files_from_huggingface` calls
  `snapshot_download` with no `revision`. It resolves `model_info(...).sha`, but
  uses it only for the tree listing. Every install takes whatever that repo's
  default branch holds at that moment.
- **No integrity pin.** Verification compares file *size* and HF's `blob_id`,
  both obtained from the same host in the same session — self-consistency with
  what the server just said, not agreement with a known-good value. Re-checking
  a warm cache compares size alone. No digest is pinned anywhere.
- **The pin cannot be supplied from outside.** `OnnxTextEmbedding.__init__`
  calls `self.download_model(desc, cache_dir, local_files_only=...,
  specific_model_path=...)` and drops `**kwargs` on the way. There is no
  supported path for a caller to pass `revision` through `TextEmbedding`.
- **The cache is the system temp directory** — `tempfile.gettempdir()/fastembed_cache`
  unless `FASTEMBED_CACHE_PATH` or `cache_dir` says otherwise. So the fetch is
  not a one-time first-run event: it recurs whenever `/tmp` is cleared, and it
  puts 67 MB outside the single application data directory ADR-0004 §2 requires.

Three usable levers do exist: `cache_dir` / `FASTEMBED_CACHE_PATH`,
`local_files_only` / `HF_HUB_OFFLINE`, and `specific_model_path`, which bypasses
the download entirely.

The fourth bullet is the one that decides this ADR. "Keep the fetch, pin and
verify it" cannot be built on fastembed's public API. Pinning requires either
forking fastembed or doing the fetch ourselves — and once we are doing the fetch
ourselves, the question is no longer *how to pin fastembed's download* but *when
the download should happen at all*.

### Does ADR-0004 §2 need amending?

No, and this ADR declines to amend it. Issue #89's second option proposed
widening §2 to admit an artifact-repository recipient. §2 governs sending **user
data** off-device; this request carries none. What it discloses is transport
metadata — source IP, timing, and the fact that this installation fetched this
model. Reading §2's recipient clause onto a no-user-data fetch would widen a
ratified clause by assertion, which is precisely the move ADR-0017 §5 refuses.

The counter-reading is fair and worth recording: "this install fetched this
model" is user-adjacent, so §2's *spirit* arguably reaches it. Nothing turns on
settling that, because the rule in §1 is strict enough to satisfy either
reading — under it the fetch is user-initiated, so consent is explicit whether
or not §2 formally applies.

## Decision

### 1. The rule

**`models/` may fetch a model artifact carrying no user data, and only when the
fetch is explicitly initiated by the user, pinned to an immutable revision, and
verified against a digest recorded in this repository before use. An artifact
fetch that happens as a side effect of ordinary operation is a bug.**

This is a new rule about artifact egress. It amends nothing: ADR-0004 §2 and
ADR-0017 §1 continue to govern user-data egress, untouched.

### 2. The default embedder never opens a socket

`FastEmbedEmbedder` is constructed offline-only — `local_files_only=True`, with
`cache_dir` under the application data directory ADR-0004 §2 requires (resolved
by `platformdirs`, which that ADR already names), not the system temp directory.

If the model is absent, `embed` raises `ModelError` naming the provisioning step.
It does not fall back to fetching. A loud, actionable failure is the correct
behaviour for a local-first product; a silent network call is not.

Constructing the embedder and reading `dimensions` stay offline, as they already
are — those resolve from fastembed's in-package metadata.

### 3. Provisioning is a separate, explicit, verified step

A provisioning entry point in `models/` acquires the artifact:

1. `huggingface_hub.snapshot_download(repo_id=..., revision=<pinned commit>)` —
   called directly, because fastembed cannot forward the revision. An immutable
   commit SHA, never a branch name.
2. Verify each downloaded file against a **SHA-256 recorded as a constant in
   `models/`**. A mismatch is a hard failure that leaves no usable cache behind.
3. Only then is the artifact available to the offline embedder.

The pinned revision and digests live in code and change only by a reviewed diff.
That is what makes "pinned and verified" checkable rather than an intention:
changing which weights this product runs requires a commit.

`huggingface_hub` becomes a **direct** runtime dependency. It is already present
transitively via `fastembed`; declaring it is honesty about what we import, and
it is imported only inside `models/`, so golden rule 4 holds.

### 4. First-run behaviour is documented

`README.md` states that on-device embedding requires a one-time model download,
which host serves it, how large it is, that it is user-initiated, and that
everything else in the product works without it.

### 5. What this ADR does not decide

- **It does not vendor the artifact.** See the alternative below.
- **It does not expose the provisioning step as a CLI command.** The entry point
  is a `models/` function; surfacing it in `interfaces/` is a separate change
  (issue #131), so this decision's implementation stays inside one subsystem.
- **It does not pin transport endpoints.** Issue #83 covers that for `models/`
  generally and applies here too. This ADR does not depend on #83 being resolved
  first: a digest pin makes endpoint compromise detectable at use, which is the
  property that matters for an artifact. Issue #66 would let import-linter pin
  which module may hold a network client, making §1 mechanically checkable
  rather than review-checkable; also not a precondition.

## Alternatives considered

**Vendor or preinstall the artifact.** Issue #89 calls this the strongest
option, and on the properties it optimises it is: no runtime fetch at all, an
install that is deterministic and works offline from the first command, and no
new egress rule to write.

It is rejected **for now**, on distribution rather than on principle. Shipping
67 MB of third-party weights inside our wheel makes every `uv sync` — including
for users on a cloud embedder or the lexical `InMemoryMemoryStore` — pay for a
capability they may not use, leaves little headroom under PyPI's default 100 MB
per-file limit, and makes us the redistributor, owning re-release whenever the
model changes. The clean form is a separate data-only package behind an extra
(`ai-assistant[local-embeddings]`), which needs a release pipeline this project
does not have.

**Revisit when there is one.** §3's pinned digest is the same value such a
package would ship, so this decision is a step toward vendoring rather than away
from it.

**Keep the fetch lazy and pin it in place.** Not available: §Context's fourth
bullet. It would require forking or monkeypatching fastembed's download path,
which is more code than §3 and less auditable.

## Consequences

- **First use of memory can fail where it previously worked**, until the user
  provisions the model. This is the real cost of the decision and the strongest
  argument for vendoring instead. It is accepted because the failure is loud,
  names its remedy, and is one command — against a silent 67 MB download that
  currently repeats whenever `/tmp` is cleared.
- **The default embedder becomes offline-deterministic.** Its behaviour no
  longer depends on a repository's mutable default branch, which is what
  "whoever serves the artifact chooses what the embedder computes" meant.
- **Model changes become explicit.** Bumping the pin is a reviewed commit that
  changes the embedding space, which ADR-0006 §4 already requires re-embedding
  for. The pin makes that transition visible instead of ambient.
- **New direct dependency:** `huggingface_hub`, already transitive, confined to
  `models/`, needed because fastembed cannot forward a revision.
- **The cache moves** out of the system temp directory into the application data
  directory, bringing it under ADR-0004 §2's residency clause.
- **Nothing else in the stack has this shape.** Checked, per #89's last line:
  `sqlite-vec` bundles `vec0.so` in its wheel; `tokenizers`, `mmh3` and
  `py-rust-stemmers` fetch nothing lazily; `genai-prices` (via `pydantic-ai`)
  ships a bundled price snapshot and returns it with `from_auto_update=False` —
  its updater reaches `raw.githubusercontent.com` but is opt-in and never
  started by default. That last one is a latent instance of the same shape and
  has an issue against keeping it off.
- **Revisit if** a release pipeline makes the vendored package practical, if
  fastembed gains a supported way to pass a revision (which would let §3 shrink
  back to a kwarg), or if provisioning friction measurably costs adoption.
