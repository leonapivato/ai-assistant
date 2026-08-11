"""Shared test doubles (fakes) for the ``core`` Protocols.

Canonical, contract-correct implementations that any subsystem's tests may import
instead of hand-rolling a mock or reaching into another subsystem's internals
(CLAUDE.md golden rule 1; CONTRIBUTING, "Fakes over mocks"). One shared fake per
Protocol keeps parallel work honest: two subsystems built at once depend on the
*same* stand-in, so a divergent private mock cannot hide an integration mismatch.

Each fake passes its Protocol's conformance suite. This package is for tests
only; production code must not import it (enforced by ``lint-imports``).
"""

from __future__ import annotations

from ai_assistant.testing.context import FakeContextProvider
from ai_assistant.testing.conversations import FakeConversationStore
from ai_assistant.testing.deferrals import FakeDeferralStore
from ai_assistant.testing.embeddings import FakeEmbedder
from ai_assistant.testing.engine import FakeAssistantEngine
from ai_assistant.testing.grants import (
    DEFAULT_DECIDED_AT,
    DEFAULT_GRANTED_SOURCE,
    FakeSourceGrants,
    FakeSourceGrantStore,
    revocation_of,
    source_grant,
)
from ai_assistant.testing.invoker import FakeToolImplementation, FakeToolInvoker, succeeds
from ai_assistant.testing.learning import FakeFeedbackProcessor
from ai_assistant.testing.memory import FakeMemoryStore
from ai_assistant.testing.models import FakeModelProvider, ModelCall
from ai_assistant.testing.notifications import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeNotificationWriter,
)
from ai_assistant.testing.observation import (
    DEFAULT_MAX_BATCH_SIZE,
    DEFAULT_MAX_PROPOSALS,
    FakeObserver,
    ObservationGate,
    ObservedBelief,
)
from ai_assistant.testing.permissions import FakeActionPolicy, FakeAuditTrail
from ai_assistant.testing.planning import FakePlanner, FakePlanStore
from ai_assistant.testing.policy import FakeMemoryPolicy, PolicyCall
from ai_assistant.testing.readers import (
    DEFAULT_READER_NAME,
    FakeReader,
    attested_proposal,
)
from ai_assistant.testing.secrets import (
    DEFAULT_INSTALLATION,
    OTHER_INSTALLATION,
    Disclosure,
    FakeSecrets,
    FakeSecretStore,
    SecretBacking,
    SecretMethod,
    disclosure_of,
)
from ai_assistant.testing.tools import FakeToolRegistry
from ai_assistant.testing.traces import (
    DEFAULT_OCCURRED_AT,
    TRACE_NOT_RECORDED,
    FakeTraceRetention,
    FakeTraceSink,
    FakeTraceStore,
    evaluation_trace,
)
from ai_assistant.testing.writer import FakeMemoryWriter

__all__ = [
    "DEFAULT_DECIDED_AT",
    "DEFAULT_GRANTED_SOURCE",
    "DEFAULT_INSTALLATION",
    "DEFAULT_MAX_BATCH_SIZE",
    "DEFAULT_MAX_PROPOSALS",
    "DEFAULT_OCCURRED_AT",
    "DEFAULT_READER_NAME",
    "OTHER_INSTALLATION",
    "TRACE_NOT_RECORDED",
    "Disclosure",
    "FakeActionPolicy",
    "FakeAssistantEngine",
    "FakeAuditTrail",
    "FakeContextProvider",
    "FakeConversationStore",
    "FakeDeferralStore",
    "FakeEmbedder",
    "FakeFeedbackProcessor",
    "FakeMemoryPolicy",
    "FakeMemoryStore",
    "FakeMemoryWriter",
    "FakeModelProvider",
    "FakeNotificationOutbox",
    "FakeNotificationPolicy",
    "FakeNotificationStore",
    "FakeNotificationWriter",
    "FakeObserver",
    "FakePlanStore",
    "FakePlanner",
    "FakeReader",
    "FakeSecretStore",
    "FakeSecrets",
    "FakeSourceGrantStore",
    "FakeSourceGrants",
    "FakeToolImplementation",
    "FakeToolInvoker",
    "FakeToolRegistry",
    "FakeTraceRetention",
    "FakeTraceSink",
    "FakeTraceStore",
    "ModelCall",
    "ObservationGate",
    "ObservedBelief",
    "PolicyCall",
    "SecretBacking",
    "SecretMethod",
    "attested_proposal",
    "disclosure_of",
    "evaluation_trace",
    "revocation_of",
    "source_grant",
    "succeeds",
]
