"""Live progress streaming for the meal-planner LangGraph workflow.

Wraps ``app.stream(..., stream_mode="updates")`` so callers (the notebook or a
script) get one progress line per node as the multi-agent graph runs, plus a
structured result at the end. The graph's objects (``PlannedMeal``, ``Recipe``)
are consumed by duck-typed attribute access, so this module stays decoupled from
the notebook's Pydantic definitions.
"""

from dataclasses import dataclass
from typing import Any, Callable

# LangGraph node names emitted by the meal-planner graph (see recipe_builder.ipynb).
_CHEF_PLAN = "chef_plan"
_RECIPE_WORKER = "recipe_worker"
_MEAL_PLANNER = "meal_planner"
_CHEF_SUMMARY = "chef_summary"

# Default cap on parallel recipe workers (one is spawned per meal slot).
DEFAULT_MAX_CONCURRENCY = 4


@dataclass
class StreamedPlan:
    """Final artifacts collected while streaming the workflow.

    Attributes:
        meal_plan_md: Rendered markdown meal plan (empty if the request was refused).
        meal_plan_path: Path the plan was written to, or "" if none was produced.
        summary: The Chef's closing summary line.
    """

    meal_plan_md: str = ""
    meal_plan_path: str = ""
    summary: str = ""


def stream_meal_plan(
    app: Any,
    initial_state: Any,
    *,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    printer: Callable[[str], None] = print,
) -> StreamedPlan:
    """Stream the meal-planner graph, relaying live progress and returning results.

    Runs ``app.stream(initial_state, stream_mode="updates")`` and emits one line
    per node as it finishes: the Chef's planned slots, each recipe as its worker
    returns, the saved-plan path, and the final summary. All macro/markdown
    content is produced by the graph in code — this function only relays it.

    Args:
        app: Compiled LangGraph application (the meal-planner workflow).
        initial_state: Initial graph state to stream, e.g. ``ChefState(request=...)``.
        max_concurrency: Cap on parallel recipe workers (one per meal slot).
        printer: Sink for progress lines; defaults to ``print`` for notebook output.
            Inject a no-op to silence, or a collector to capture the lines.

    Returns:
        A ``StreamedPlan`` with the rendered markdown, its file path, and the summary.
    """

    result = StreamedPlan()

    stream = app.stream(
        initial_state,
        stream_mode="updates",
        config={"max_concurrency": max_concurrency},
    )

    for chunk in stream:
        for node, update in chunk.items():
            _relay_update(node, update, result, printer)

    return result


def _relay_update(
    node: str,
    update: dict[str, Any],
    result: StreamedPlan,
    printer: Callable[[str], None],
) -> None:
    """Print one node's update and fold its artifacts into ``result`` in place."""

    if node == _CHEF_PLAN and update.get("planned"):
        planned = update["planned"]
        printer(f"👩‍🍳 chef planned {len(planned)} unique meal(s):")
        for meal in planned:
            printer(f"   • {meal.slot}: {meal.dish}")

    elif node == _RECIPE_WORKER and update.get("recipes"):
        recipe = update["recipes"][0]
        printer(f"   🍽 recipe ready — {recipe.slot}: {recipe.title}")

    elif node == _MEAL_PLANNER:
        result.meal_plan_md = update.get("meal_plan_md", "")
        result.meal_plan_path = update.get("meal_plan_path", "")
        printer(f"📝 meal plan saved → {result.meal_plan_path}")

    elif node == _CHEF_SUMMARY:
        result.summary = update.get("summary", "")
        printer(f"✅ {result.summary}")
