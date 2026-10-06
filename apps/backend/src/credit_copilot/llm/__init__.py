"""LLM client: multi-provider completion (OpenAI / compatible / Bedrock).

Wraps provider SDKs into a single ``LLMClient.complete()`` and classifies failures
into the ToolError taxonomy (transient / timeout / fatal) for ``with_retry``.
"""
