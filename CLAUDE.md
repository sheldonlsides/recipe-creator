# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-agent meal planner built on LangGraph/LangChain. A **Chef** coordinator scope-gates the request and plans unique dishes per meal slot, fans out one parallel **Recipe** worker per slot (web search via Tavily + nutrition grounding via a local FAISS store), then fans in to a **Meal Planner** that enforces calorie caps and renders a deterministic markdown plan. The entire implementation lives in `src/recipe_builder.ipynb`; `main.py` is an unused stub.

## Commands

Package manager is **uv** (Python 3.12). There is no test or lint tooling configured.

```bash
# Install dependencies
uv sync                          # from uv.lock (preferred)
./install_deps                   # equivalent: uv add -r ./requirements.txt

# Run the notebook headless (avoids the Anaconda kernel/dependency mismatch)
uv run --with nbconvert -- jupyter nbconvert --to notebook --execute src/recipe_builder.ipynb

# Open interactively
uv run --with nbconvert jupyter notebook src/recipe_builder.ipynb
```

Always run Python/notebooks through `uv run` so the project `.venv` (not Anaconda) is used.

## Configuration (.env)

Required by `src/model_factory.py` (fail-fast, no defaults):
- `LLM_PROVIDER` — `bedrock` | `openai` | `anthropic`
- `LLM_PROVIDER_MODEL` — model id for that provider

Provider credentials / service keys (by name): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (Bedrock uses AWS credentials), `TAVILY_API_KEY` (recipe web search), `HF_TOKEN` (embeddings), `LANGSMITH_API_KEY` / `LANGSMITH_ENDPOINT` / `LANGSMITH_PROJECT` (tracing), `USER_AGENT`.

Vector store selection (notebook):
- `VECTOR_BACKEND` — `faiss` (default, local, zero-infra) | `pgvector` (PostgreSQL + pgvector).
- `DATABASE_URL` — required **only** when `VECTOR_BACKEND=pgvector`, e.g. `postgresql+psycopg://dev:devpass@localhost:5432/appdb` (psycopg3 driver). Stand up the DB with `deploy/` (see `deploy/README.md`).

## Architecture

**`src/model_factory.py`** — `create_model(provider, max_tokens, temperature, top_p)` returns a provider-agnostic LangChain `BaseChatModel` (bedrock/openai/anthropic), reading `LLM_PROVIDER` / `LLM_PROVIDER_MODEL` from env. Each agent gets its own instance: Chef at `temperature=0.7` (creative), Recipe & Planner at `0` (deterministic). Sampling params are only forwarded when non-None.

**Nutrition vector store** — Built in-notebook from `src/data/opennutrition_foods.tsv` (~327K foods, capped to ~20K in dev) using local `sentence-transformers/all-MiniLM-L6-v2` embeddings (384-dim, normalized, no API key). Each `Document` embeds name + alternate names + description; metadata carries per-100g macros. Two interchangeable backends selected by `VECTOR_BACKEND`:
- **`faiss`** (default) — `build_or_load_index()`; persisted to `src/faiss_index/` (gitignored — regenerated on first run).
- **`pgvector`** — `build_or_load_pgvector()`; loads to a PostgreSQL `opennutrition_foods` collection via `langchain-postgres` `PGVector` (cosine, `use_jsonb=True`, HNSW index built after bulk load). Idempotent via a row-count gate (no re-embed if already populated). Provisioned by `deploy/` (Docker Compose, `pgvector/pgvector:pg17`).

Both paths share `embeddings`, `load_food_documents()`, and the 5,000-doc batched build with progress logging; a one-line dispatcher picks the backend and binds the global `vectorstore`, so `find_ingredients` / `retriever` and all downstream code are backend-agnostic. `similarity_search(query, k)` is identical across both.

**LangGraph flow** over a shared `ChefState`:
```
START → chef_plan → (route_after_chef)
   ├─ refusal → chef_summary → END
   └─ Send() fan-out → recipe_worker × N (parallel) → meal_planner → chef_summary → END
```
- `chef_plan` runs a `ScopeCheck`, parses day/meal count and any calorie range, assigns a **unique dish per slot**.
- Fan-out uses `Send("recipe_worker", RecipeTask(...))`; fan-in relies on `recipes: Annotated[list[Recipe], operator.add]` to concatenate worker results.
- `meal_planner` is the barrier: enforces per-day calorie caps by scaling portions (`_enforce_calories`), then renders markdown to `src/meal_plans/<slug>.md` (gitignored).

**Shared agent tools** (`AGENT_TOOLS`): `find_ingredients` (FAISS top-k with per-100g macros), `total_meal` (scales per-100g by grams and sums), `tavily_search` (web recipe search), `fetch_recipe_page` (fetches a recipe URL, capped at `max_chars`).

## Conventions

- **Macros are computed in code, never by the LLM.** Ingredients carry per-100g facts; meal/day/grand totals are deterministic sums scaled by gram weight. Markdown rendering is pure Python, not model output.
- **Guardrails** (`GUARDRAILS`) are prepended to every agent's system prompt and gate scope to food/nutrition; web results are treated as untrusted data, not instructions. Preserve this defense-in-depth when editing agents.
- Notebook-first: prefer extending `src/recipe_builder.ipynb`; `main.py` is not yet wired to the workflow.
