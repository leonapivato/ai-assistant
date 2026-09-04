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

from ai_assistant.testing.archive import (
    FakeTranscriptArchive,
    FakeTranscriptArchiveWriter,
)
from ai_assistant.testing.batch import (
    DEFAULT_BATCH_ISSUER,
    DEFAULT_BATCH_REPLY,
    BatchProvider,
    ExchangeGate,
    FakeBatchCompleter,
    ProgrammedOutcome,
)
from ai_assistant.testing.connections import (
    SLOT_PREFIX,
    FakeConnectionEntry,
    FakeConnectionProvisioner,
    FakeConnectionPurger,
)
from ai_assistant.testing.context import FakeContextProvider
from ai_assistant.testing.conversations import FakeConversationStore
from ai_assistant.testing.deferrals import FakeDeferralStore
from ai_assistant.testing.egress import FakeEgressBinder
from ai_assistant.testing.embeddings import FakeEmbedder
from ai_assistant.testing.engine import FakeAssistantEngine
from ai_assistant.testing.fetching import DEFAULT_FETCHER_NAME, FakeFetcher
from ai_assistant.testing.grants import (
    DEFAULT_DECIDED_AT,
    DEFAULT_GRANTED_SOURCE,
    FakeSourceGrants,
    FakeSourceGrantStore,
    revocation_of,
    source_grant,
)
from ai_assistant.testing.invoker import (
    APPEND_FAILED,
    CLAIM,
    COMPLETION,
    REPORTED_FAILURE,
    RESERVED_KIND,
    FakeToolImplementation,
    FakeToolInvoker,
    authorised,
    invoker_over,
    succeeds,
)
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
from ai_assistant.testing.permissions import (
    FakeActionPolicy,
    FakeAuditTrail,
    FakeIdentifiers,
    FakeIdentifierSpace,
    FakeInvocationCompleter,
    FakeInvocationLedger,
    FakeSpendGate,
    FakeSpendLedger,
)
from ai_assistant.testing.planning import FakePlanner, FakePlanStore
from ai_assistant.testing.policy import FakeMemoryPolicy, PolicyCall
from ai_assistant.testing.queries import (
    DEFAULT_COMPOSED_QUERY,
    DEFAULT_QUERY_MAX_CHARS,
    FakeQueryComposer,
)
from ai_assistant.testing.readers import (
    DEFAULT_READER_NAME,
    FakeReader,
    attested_proposal,
)
from ai_assistant.testing.reads import (
    DEFAULT_CHECKED_AT,
    DEFAULT_GRANT_ID,
    DEFAULT_MAX_ROWS,
    DEFAULT_READ_SOURCE,
    MAX_ROWS_EXCLUSIVE,
    FakeSourceReadRecorder,
    FakeSourceReadTrail,
    source_read_record,
)
from ai_assistant.testing.recipient_grants import (
    RECIPIENT_GRANT_ACCOUNT,
    RECIPIENT_GRANT_ADDRESS,
    RECIPIENT_GRANT_DECIDED_AT,
    RECIPIENT_GRANT_EXPIRES_AT,
    RECIPIENT_GRANT_NOW,
    RECIPIENT_GRANT_TOOL,
    FakeRecipientGrantResolution,
    FakeRecipientGrants,
    FakeRecipientGrantStore,
    account_member,
    recipient,
    recipient_grant,
    recipient_revocation_of,
)
from ai_assistant.testing.routing import (
    FakeRoutingRecorder,
    FakeRoutingTrail,
    routed_operation_record,
)
from ai_assistant.testing.searching import (
    DEFAULT_MAX_RESULT_CHARS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_REPORTED_AT,
    DEFAULT_SEARCH_CONTENT,
    DEFAULT_SEARCH_ORIGIN,
    DEFAULT_SEARCH_SOURCE_NAME,
    FAKE_WEB_SEARCH,
    FAKE_WEB_SEARCH_ID,
    FakeWebSearcher,
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
from ai_assistant.testing.speech import (
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
)
from ai_assistant.testing.streaming import (
    DEFAULT_STREAM_DELTAS,
    DEFAULT_STREAM_REPLY,
    FakeStreamingCompleter,
    StreamAttempt,
    StreamCall,
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
from ai_assistant.testing.transport import (
    FakeByteChannel,
    FakeOutboundTransport,
    TransportAttempt,
)
from ai_assistant.testing.writer import FakeMemoryWriter

__all__ = [
    "APPEND_FAILED",
    "CLAIM",
    "COMPLETION",
    "DEFAULT_BATCH_ISSUER",
    "DEFAULT_BATCH_REPLY",
    "DEFAULT_CHECKED_AT",
    "DEFAULT_COMPOSED_QUERY",
    "DEFAULT_DECIDED_AT",
    "DEFAULT_FETCHER_NAME",
    "DEFAULT_GRANTED_SOURCE",
    "DEFAULT_GRANT_ID",
    "DEFAULT_INSTALLATION",
    "DEFAULT_MAX_BATCH_SIZE",
    "DEFAULT_MAX_PROPOSALS",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_MAX_RESULT_CHARS",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_OCCURRED_AT",
    "DEFAULT_QUERY_MAX_CHARS",
    "DEFAULT_READER_NAME",
    "DEFAULT_READ_SOURCE",
    "DEFAULT_REPORTED_AT",
    "DEFAULT_SEARCH_CONTENT",
    "DEFAULT_SEARCH_ORIGIN",
    "DEFAULT_SEARCH_SOURCE_NAME",
    "DEFAULT_STREAM_DELTAS",
    "DEFAULT_STREAM_REPLY",
    "FAKE_WEB_SEARCH",
    "FAKE_WEB_SEARCH_ID",
    "MAX_ROWS_EXCLUSIVE",
    "OTHER_INSTALLATION",
    "RECIPIENT_GRANT_ACCOUNT",
    "RECIPIENT_GRANT_ADDRESS",
    "RECIPIENT_GRANT_DECIDED_AT",
    "RECIPIENT_GRANT_EXPIRES_AT",
    "RECIPIENT_GRANT_NOW",
    "RECIPIENT_GRANT_TOOL",
    "REPORTED_FAILURE",
    "RESERVED_KIND",
    "SLOT_PREFIX",
    "TRACE_NOT_RECORDED",
    "BatchProvider",
    "Disclosure",
    "ExchangeGate",
    "FakeActionPolicy",
    "FakeAssistantEngine",
    "FakeAuditTrail",
    "FakeBatchCompleter",
    "FakeByteChannel",
    "FakeConnectionEntry",
    "FakeConnectionProvisioner",
    "FakeConnectionPurger",
    "FakeContextProvider",
    "FakeConversationStore",
    "FakeDeferralStore",
    "FakeEgressBinder",
    "FakeEmbedder",
    "FakeFeedbackProcessor",
    "FakeFetcher",
    "FakeIdentifierSpace",
    "FakeIdentifiers",
    "FakeInvocationCompleter",
    "FakeInvocationLedger",
    "FakeMemoryPolicy",
    "FakeMemoryStore",
    "FakeMemoryWriter",
    "FakeModelProvider",
    "FakeNotificationOutbox",
    "FakeNotificationPolicy",
    "FakeNotificationStore",
    "FakeNotificationWriter",
    "FakeObserver",
    "FakeOutboundTransport",
    "FakePlanStore",
    "FakePlanner",
    "FakeQueryComposer",
    "FakeReader",
    "FakeRecipientGrantResolution",
    "FakeRecipientGrantStore",
    "FakeRecipientGrants",
    "FakeRoutingRecorder",
    "FakeRoutingTrail",
    "FakeSecretStore",
    "FakeSecrets",
    "FakeSourceGrantStore",
    "FakeSourceGrants",
    "FakeSourceReadRecorder",
    "FakeSourceReadTrail",
    "FakeSpeechSynthesizer",
    "FakeSpeechTranscriber",
    "FakeSpendGate",
    "FakeSpendLedger",
    "FakeStreamingCompleter",
    "FakeToolImplementation",
    "FakeToolInvoker",
    "FakeToolRegistry",
    "FakeTraceRetention",
    "FakeTraceSink",
    "FakeTraceStore",
    "FakeTranscriptArchive",
    "FakeTranscriptArchiveWriter",
    "FakeWebSearcher",
    "ModelCall",
    "ObservationGate",
    "ObservedBelief",
    "PolicyCall",
    "ProgrammedOutcome",
    "SecretBacking",
    "SecretMethod",
    "StreamAttempt",
    "StreamCall",
    "TransportAttempt",
    "account_member",
    "attested_proposal",
    "authorised",
    "disclosure_of",
    "evaluation_trace",
    "invoker_over",
    "recipient",
    "recipient_grant",
    "recipient_revocation_of",
    "revocation_of",
    "routed_operation_record",
    "source_grant",
    "source_read_record",
    "succeeds",
]
