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
from ai_assistant.testing.conversations import FakeConversationStore
from ai_assistant.testing.diagnostics import (
    FakeDiagnosticRetention,
    FakeDiagnosticSink,
    diagnostic_entry,
)
from ai_assistant.testing.egress import FakeEgressBinder
from ai_assistant.testing.embeddings import FakeEmbedder
from ai_assistant.testing.engine import FakeAssistantEngine
from ai_assistant.testing.fetching import DEFAULT_FETCHER_NAME, FakeFetcher
from ai_assistant.testing.forecasting import (
    DEFAULT_FORECAST_DAYS,
    DEFAULT_FORECAST_LATITUDE,
    DEFAULT_FORECAST_LONGITUDE,
    DEFAULT_FORECAST_ORIGIN,
    DEFAULT_FORECAST_REPORTED_AT,
    DEFAULT_FORECAST_SOURCE_NAME,
    DEFAULT_MAX_DAY_CHARS,
    DEFAULT_MAX_FORECAST_DAYS,
    FAKE_FORECAST_ID,
    FAKE_FORECAST_READ,
    FakeForecaster,
    ScriptedDay,
    forecast_day,
)
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
from ai_assistant.testing.memory import FakeMemoryStore
from ai_assistant.testing.models import FakeModelProvider, ModelCall
from ai_assistant.testing.notifications import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeNotificationWriter,
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
from ai_assistant.testing.person_model import DEFAULT_PROFILE_FIELD_CHARS, FakePersonModelStore
from ai_assistant.testing.planning import FakePlanStore
from ai_assistant.testing.policy import FakeMemoryPolicy, PolicyCall
from ai_assistant.testing.prompts import (
    default_prompt,
    default_renderings,
    flag_combinations,
    prompt_from,
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
from ai_assistant.testing.stories import FakeStoryStore
from ai_assistant.testing.structured import (
    DEFAULT_STRUCTURED_MODEL,
    FakeStructuredCompleter,
    ScriptedReply,
    StructuredCall,
)
from ai_assistant.testing.telegram import (
    DEFAULT_TELEGRAM_CHAT_ID,
    FakeTelegramBotClient,
    TelegramCall,
)
from ai_assistant.testing.telegram_intake import FakeTelegramIntakeRecord
from ai_assistant.testing.tool_calling import (
    DEFAULT_ROUND_TEXT,
    FakeToolCallingCompleter,
    RoundCall,
)
from ai_assistant.testing.tools import FakeToolRegistry, with_phase_declaration
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
    "DEFAULT_DECIDED_AT",
    "DEFAULT_FETCHER_NAME",
    "DEFAULT_FORECAST_DAYS",
    "DEFAULT_FORECAST_LATITUDE",
    "DEFAULT_FORECAST_LONGITUDE",
    "DEFAULT_FORECAST_ORIGIN",
    "DEFAULT_FORECAST_REPORTED_AT",
    "DEFAULT_FORECAST_SOURCE_NAME",
    "DEFAULT_GRANTED_SOURCE",
    "DEFAULT_GRANT_ID",
    "DEFAULT_INSTALLATION",
    "DEFAULT_MAX_DAY_CHARS",
    "DEFAULT_MAX_FORECAST_DAYS",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_MAX_RESULT_CHARS",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_OCCURRED_AT",
    "DEFAULT_PROFILE_FIELD_CHARS",
    "DEFAULT_READER_NAME",
    "DEFAULT_READ_SOURCE",
    "DEFAULT_REPORTED_AT",
    "DEFAULT_ROUND_TEXT",
    "DEFAULT_SEARCH_CONTENT",
    "DEFAULT_SEARCH_ORIGIN",
    "DEFAULT_SEARCH_SOURCE_NAME",
    "DEFAULT_STRUCTURED_MODEL",
    "DEFAULT_TELEGRAM_CHAT_ID",
    "FAKE_FORECAST_ID",
    "FAKE_FORECAST_READ",
    "FAKE_WEB_SEARCH",
    "FAKE_WEB_SEARCH_ID",
    "MAX_ROWS_EXCLUSIVE",
    "OTHER_INSTALLATION",
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
    "FakeConversationStore",
    "FakeDiagnosticRetention",
    "FakeDiagnosticSink",
    "FakeEgressBinder",
    "FakeEmbedder",
    "FakeFetcher",
    "FakeForecaster",
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
    "FakeOutboundTransport",
    "FakePersonModelStore",
    "FakePlanStore",
    "FakeReader",
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
    "FakeStoryStore",
    "FakeStructuredCompleter",
    "FakeTelegramBotClient",
    "FakeTelegramIntakeRecord",
    "FakeToolCallingCompleter",
    "FakeToolImplementation",
    "FakeToolInvoker",
    "FakeToolRegistry",
    "FakeTraceRetention",
    "FakeTraceSink",
    "FakeTraceStore",
    "FakeWebSearcher",
    "ModelCall",
    "PolicyCall",
    "ProgrammedOutcome",
    "RoundCall",
    "ScriptedDay",
    "ScriptedReply",
    "SecretBacking",
    "SecretMethod",
    "StructuredCall",
    "TelegramCall",
    "TransportAttempt",
    "attested_proposal",
    "authorised",
    "default_prompt",
    "default_renderings",
    "diagnostic_entry",
    "disclosure_of",
    "evaluation_trace",
    "flag_combinations",
    "forecast_day",
    "invoker_over",
    "prompt_from",
    "revocation_of",
    "source_grant",
    "source_read_record",
    "succeeds",
    "with_phase_declaration",
]
