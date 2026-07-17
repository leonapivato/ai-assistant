# 6. Embedding seam for semantic memory retrieval

- Status: Accepted
- Date: 2026-07-17

## Context

Memory retrieval today is lexical: `InMemoryMemoryStore.search` scores by
query-term overlap. That was deliberate for slices 1–2, but it is not what the
product needs — "what does the user drink?" should surface "the user likes
espresso" even though they share no words. Slice 3 of
[ADR-0005](0005-memory-model.md) (the persistent store) is where semantic
retrieval has to become real, and [ADR-0002](0002-foundational-stack-and-architecture.md)
already named `sqlite-vec` as the vector backend. Semantic search over vectors
needs an **embedding** capability, which does not exist yet. ADR-0005 explicitly
deferred that seam to its own ADR — this one.

Two forces make this more than a library pick:

1. **Embedding is a model capability, but a distinct one.** It is not chat
   completion (`ModelProvider`), and providers differ: a provider may offer
   excellent chat and no embeddings at all (e.g. Anthropic points users to a
   separate embedding provider). So it wants its own seam, not a bolt-on to
   `ModelProvider`.
2. **Embedding memory is a privacy decision.** To index memory we must embed its
   *content* — which is Tier 1 personal data ([ADR-0004](0004-privacy-and-data-handling.md)).
   Sending every memory to a cloud embedding API would ship the user's entire
   personal history off-device purely to build an index, directly contradicting
   ADR-0004's minimal-egress rule.

This is an **additive** contract change (a new Protocol), not a change to an
existing one, but it is still ADR-worthy per golden rule 5.

## Decision

### 1. A dedicated `Embedder` Protocol in `core`

Add an `Embedder` Protocol, separate from `ModelProvider`, so the embedding
backend is swappable exactly like the chat model is:

```python
class Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    async def embed(
        self, texts: Sequence[str], *, model: str | None = None
    ) -> list[Sequence[float]]: ...
```

Batch is the primitive (embedding is far cheaper amortised over a batch). A
`dimensions` property lets the store size its vector column without a probe
call. A `core` type alias `Embedding = Sequence[float]` names the return element.

### 2. On-device embedding is the default; cloud embedding is opt-in

The default `Embedder` runs a **local** model on the user's machine, so memory
content never leaves the device just to be indexed. This is the privacy-correct
default under ADR-0004 and keeps the product usable offline. A **cloud** embedder
remains available for users who want higher quality and accept the egress, but it
is opt-in and, like all egress, confined to the `models/` layer and the provider
the user configured.

The proposed default implementation is a lightweight ONNX model via `fastembed`
(no heavy `torch` dependency); the exact library is confirmed when slice 3 lands,
but "local by default" is the firm decision.

### 3. Embedders live in `models/`; vectors live in `memory/`

- `Embedder` implementations live in `models/` — it is the model/egress layer,
  and any embedding provider SDK or local-model dependency is confined there. The
  import-linter "provider SDKs are confined to the models layer" contract is
  extended to cover new embedding backends.
- The persistent store in `memory/` owns vector storage and similarity search via
  `sqlite-vec`, and receives an `Embedder` by injection. Embedding happens
  *inside* the store: on `add` it embeds the record's `content`; on `search` it
  embeds the query and ranks by vector similarity.

The `MemoryStore` Protocol is **unchanged** — `search` still takes text and
returns records. Embedding is an internal implementation detail, so the lexical
`InMemoryMemoryStore` needs no embedder and stays a valid, dependency-free
`MemoryStore` for tests and offline use.

### 4. Vectors are tagged with their model and dimension

Each stored vector records the embedding model id and its dimension. Vectors from
different models are not comparable, so a change of embedding model requires
**re-embedding** the store; storing this metadata lets the store detect a
mismatch and drive that migration rather than silently returning garbage
similarities.

### 5. Retrieval is vector similarity now, hybrid later

Semantic retrieval ranks by vector similarity. Combining it with lexical signals
(hybrid search) is a plausible later enhancement and is left out of scope here.

## Consequences

- **New dependencies when slice 3 lands:** a local embedding runtime
  (`fastembed` proposed) and `sqlite-vec`, each with a fake for tests. A
  deterministic fake `Embedder` (stable vectors per input) lets the persistent
  store be tested without models or network.
- **One new, additive Protocol** (`Embedder`) and an extended import-linter
  contract for embedding SDKs. No existing contract changes.
- **Privacy-preserving by default:** Tier 1 memory content stays on-device;
  cloud embedding is an explicit, opt-in egress consistent with ADR-0004.
- **Model changes are costly:** switching embedding models means re-embedding the
  whole store. The stored model/dimension metadata bounds the blast radius by
  making mismatches detectable.
- **Provider-agnostic embeddings:** a new embedding backend is a change confined
  to `models/`, mirroring how new chat providers already are.
- **Revisit if** local embedding quality or latency proves inadequate for the
  memory sizes we see, if we adopt hybrid retrieval, or if `sqlite-vec`'s
  similarity performance forces a different vector backend (which, thanks to the
  `MemoryStore` seam, stays confined to `memory/`).
