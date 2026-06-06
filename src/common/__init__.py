"""Shared utilities reused across the project's modules and the notebook.

Houses the provider-agnostic model factory (`create_model`), which builds a
LangChain `BaseChatModel` for Bedrock / OpenAI / Anthropic driven by the
`LLM_PROVIDER` / `LLM_PROVIDER_MODEL` env vars, and the workflow streaming
helper (`stream_meal_plan`), which relays live progress from the meal-planner
graph. Add further cross-cutting helpers (config, logging, etc.) here as the
project grows.
"""

from .model_factory import create_model
from .streaming import StreamedPlan, stream_meal_plan

__all__ = ["create_model", "StreamedPlan", "stream_meal_plan"]
