"""The price data pydantic-ai reads is the bundled snapshot, not a fetched one.

Issue #132. ``genai-prices`` is a ``pydantic-ai-slim`` dependency reached from
``pydantic_ai.usage`` and ``pydantic_ai.messages``. It ships a bundled price
snapshot *and* an opt-in auto-updater that ``httpx``-gets
``raw.githubusercontent.com``. The updater is never started by default, so there
is no live egress today — but "today" is exactly the kind of claim
``CONTRIBUTING`` → "No state claims in living documents" says to convert into a
checked fact. This is that check: an upstream default change, or an accidental
enablement, fails the gate instead of going unnoticed.

The same shape as #89, which ADR-0024 closes for the embedding model. This is the
only other instance in the stack (``sqlite-vec`` bundles ``vec0.so``;
``tokenizers``, ``mmh3`` and ``py-rust-stemmers`` fetch nothing lazily), and it is
latent rather than live, so a test is the whole remedy.
"""

from __future__ import annotations

from genai_prices import data_snapshot


def test_the_price_snapshot_in_use_was_not_auto_updated() -> None:
    # `from_auto_update` is the library's own answer to "did these prices come
    # off the network?". False means they came out of the installed package.
    assert data_snapshot.get_snapshot().from_auto_update is False
