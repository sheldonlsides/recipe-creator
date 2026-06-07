"""Provider-agnostic LLM factory for LangChain/LangGraph agents.

Ported from the Strands `model_factory.py` (agentcore_travel), keeping the same
env-var contract and fail-fast behavior, but returning a LangChain
`BaseChatModel` instead of a Strands `Model`.

Two env vars drive everything and are BOTH REQUIRED (no silent defaults):
  LLM_PROVIDER       = bedrock | openai | anthropic
  LLM_PROVIDER_MODEL = the model id for that provider, e.g.
                       bedrock   -> us.anthropic.claude-haiku-4-5-20251001-v1:0
                       openai    -> gpt-4o-mini
                       anthropic -> claude-sonnet-4-6

Credentials per provider (validated up-front in create_model()):
  bedrock   -> AWS credentials / AWS_REGION   (no API key)
  openai    -> OPENAI_API_KEY
  anthropic -> ANTHROPIC_API_KEY

create_model() fails fast with a clear EnvironmentError if required configuration
is missing, rather than blowing up later inside the SDK.

Adding a provider = write a `_builder(model_id, max_tokens, temperature, top_p)`
returning a BaseChatModel, register it in _PROVIDERS, and add its API-key env var
(or None) to _PROVIDER_API_KEY_ENV.

Sampling params (temperature, top_p) and max_tokens are all OPTIONAL: when a caller
leaves one None it is simply not passed to the SDK, so the provider's own default
applies. Each chat-model class exposes these slightly differently, so the builders
map them to the right constructor surface:
  bedrock   -> temperature / top_p / max_tokens go in `model_kwargs`.
  anthropic -> max_tokens / temperature / top_p are direct ChatAnthropic kwargs.
  openai    -> temperature / top_p / max_tokens are direct ChatOpenAI kwargs.

Prompt caching: unlike the Strands factory there is no `cache_config` knob here.
LangChain handles caching differently (server-side for OpenAI; per-request
`cache_control` blocks for Anthropic/Bedrock), so it is intentionally omitted.
"""

import os

from langchain_core.language_models import BaseChatModel


def _bedrock(
    model_id: str,
    max_tokens: int | None,
    temperature: float | None,
    top_p: float | None,
) -> BaseChatModel:
    from langchain_aws import ChatBedrock

    kwargs = {"model_id": model_id}
    region = os.getenv("AWS_REGION")

    if region:
        kwargs["region_name"] = region

    # ChatBedrock routes inference params through model_kwargs; pass each only when
    # set so the provider default applies otherwise.
    model_kwargs = {}

    if max_tokens is not None:
        model_kwargs["max_tokens"] = max_tokens

    if temperature is not None:
        model_kwargs["temperature"] = temperature

    if top_p is not None:
        model_kwargs["top_p"] = top_p

    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs

    return ChatBedrock(**kwargs)


def _openai(
    model_id: str,
    max_tokens: int | None,
    temperature: float | None,
    top_p: float | None,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    kwargs = {"model": model_id, "api_key": os.environ["OPENAI_API_KEY"]}

    # ChatOpenAI takes these as direct kwargs; pass only the ones the caller set.
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if temperature is not None:
        kwargs["temperature"] = temperature

    if top_p is not None:
        kwargs["top_p"] = top_p

    return ChatOpenAI(**kwargs)


def _anthropic(
    model_id: str,
    max_tokens: int | None,
    temperature: float | None,
    top_p: float | None,
) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    kwargs = {
        "model": model_id,
        "api_key": os.environ["ANTHROPIC_API_KEY"],
        # Anthropic requires max_tokens; default to 4096 when the caller doesn't specify one.
        "max_tokens": max_tokens if max_tokens is not None else 4096,
    }

    if temperature is not None:
        kwargs["temperature"] = temperature

    if top_p is not None:
        kwargs["top_p"] = top_p

    return ChatAnthropic(**kwargs)


_PROVIDERS = {
    "bedrock": _bedrock,
    "openai": _openai,
    "anthropic": _anthropic,
}

# API-key env var each provider requires. bedrock uses AWS creds, so it needs none.
_PROVIDER_API_KEY_ENV = {
    "bedrock": None,
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def _require_env(name: str) -> str:
    """Return the env var value, or raise a clear error if it is unset/empty."""

    value = os.environ.get(name)

    if not value:
        raise EnvironmentError(
            f"Required environment variable {name!r} is not set. "
            f"Set it in your .env (or runtime env vars) before calling create_model()."
        )

    return value


def create_model(
    provider: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> BaseChatModel:
    """Return a configured LangChain chat model.

    Args:
        provider: the model provider (bedrock | openai | anthropic). When omitted,
            it is read from the required LLM_PROVIDER env var.
        max_tokens: optional cap on the model's output tokens. When omitted, the
            provider's default is used (anthropic -> 4096; bedrock/openai -> SDK default).
        temperature: optional sampling temperature. When omitted, the provider default applies.
        top_p: optional nucleus-sampling top_p. When omitted, the provider default applies.

    The sampling params are passed to the SDK ONLY when not None, so leaving them unset
    keeps the provider's own defaults (no hardcoded temperature/top_p here).

    Fails fast with EnvironmentError unless the required configuration is present:
      - LLM_PROVIDER       (when `provider` arg is not given)
      - LLM_PROVIDER_MODEL  (always)
      - the provider's API key: OPENAI_API_KEY (openai) / ANTHROPIC_API_KEY (anthropic).
        bedrock requires no API key (AWS credentials / AWS_REGION).
    """

    provider = (provider or _require_env("LLM_PROVIDER")).strip().lower()

    try:
        builder = _PROVIDERS[provider]
    except KeyError:
        raise ValueError(
            f"Unknown provider={provider!r}; expected one of {sorted(_PROVIDERS)}"
        )

    # Model id is always required — no silent fallback.
    model_id = _require_env("LLM_PROVIDER_MODEL")

    # Validate the provider's credentials up-front (bedrock uses AWS creds, no key).
    key_env = _PROVIDER_API_KEY_ENV[provider]

    if key_env:
        _require_env(key_env)

    # Show only the sampling params the caller actually set (None ones are omitted).
    parts = [
        f"{name}={value}"
        for name, value in (
            ("max_tokens", max_tokens),
            ("temperature", temperature),
            ("top_p", top_p),
        )
        if value is not None
    ]
    suffix = f" ({', '.join(parts)})" if parts else ""
    print(f"✅ Using {provider} model: {model_id}{suffix}")

    return builder(model_id, max_tokens, temperature, top_p)
