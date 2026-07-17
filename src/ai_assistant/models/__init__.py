"""Models: the model-agnostic language-model layer.

Wraps pydantic-ai to implement :class:`ai_assistant.core.protocols.ModelProvider`.
Nothing outside this package imports a provider SDK (anthropic, openai, ...) —
that is the entire point of this seam. Swapping or adding a model provider is a
change confined to this package.

Implements: ``ModelProvider``.
"""
