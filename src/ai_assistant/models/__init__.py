"""Models: the model-agnostic language-model layer.

Wraps pydantic-ai to implement :class:`ai_assistant.core.protocols.ModelProvider`.
Nothing outside this package imports a provider SDK (anthropic, openai, ...) —
that is the entire point of this seam. Swapping or adding a model provider is a
change confined to this package.

Implements: ``ModelProvider``, ``StreamingCompleter`` and ``Embedder``.

``FastEmbedEmbedder`` lives in ``ai_assistant.models.fastembed_embedder`` and is
deliberately not re-exported here, so importing this package does not pull in the
heavy ``fastembed``/ONNX runtime. Import it directly when the real embedder is
needed.

``BoundedEmbedder`` *is* re-exported: it wraps whichever ``Embedder`` the
composition root builds, so it is imported on every path including the one that
must not pay for fastembed, and it costs nothing to import (ADR-0118 §2).

The two speech implementations (``MoonshineTranscriber``, ``SupertonicSynthesizer``)
are kept out for exactly ``FastEmbedEmbedder``'s reason: importing either pulls in
``sherpa_onnx`` and, through it, a second inference runtime. Their deadline
decorators are re-exported for ``BoundedEmbedder``'s reason — the composition root
wraps whatever it built with them, and they cost nothing to import (ADR-0200 §1).
"""

from __future__ import annotations

from ai_assistant.models.bounded_embedder import BoundedEmbedder
from ai_assistant.models.bounded_speech import (
    BoundedSpeechSynthesizer,
    BoundedSpeechTranscriber,
)
from ai_assistant.models.embeddings import HashingEmbedder
from ai_assistant.models.provider import (
    PydanticAIProvider,
    ensure_credential_available,
    ensure_vendor_available,
)
from ai_assistant.models.retry import RetryingProvider
from ai_assistant.models.routing import Route, RoutingProvider
from ai_assistant.models.streaming import PydanticAIStreamingCompleter

__all__ = [
    "BoundedEmbedder",
    "BoundedSpeechSynthesizer",
    "BoundedSpeechTranscriber",
    "HashingEmbedder",
    "PydanticAIProvider",
    "PydanticAIStreamingCompleter",
    "RetryingProvider",
    "Route",
    "RoutingProvider",
    "ensure_credential_available",
    "ensure_vendor_available",
]
