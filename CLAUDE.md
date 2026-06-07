# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-agent meal planner built on LangGraph/LangChain. A **Chef** coordinator scope-gates the request and plans unique dishes per meal slot, fans out one parallel **Recipe** worker per slot (web search via Tavily + nutrition grounding via a PostgreSQL + pgvector store), then fans in to a **Meal Planner** that enforces calorie caps and renders a deterministic markdown plan. The entire implementation lives in `src/recipe_builder.ipynb`; `main.py` is an unused stub.

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

Required by `src/common/model_factory.py` (fail-fast, no defaults):
- `LLM_PROVIDER` — `bedrock` | `openai` | `anthropic`
- `LLM_PROVIDER_MODEL` — model id for that provider

Provider credentials / service keys (by name): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (Bedrock uses AWS credentials), `TAVILY_API_KEY` (recipe web search), `HF_TOKEN` (embeddings), `LANGSMITH_API_KEY` / `LANGSMITH_ENDPOINT` / `LANGSMITH_PROJECT` (tracing), `USER_AGENT`.

Vector store (notebook):
- `DATABASE_URL` — **always required**; the nutrition store is PostgreSQL + pgvector, e.g. `postgresql+psycopg://dev:devpass@localhost:5432/appdb` (psycopg3 driver). Stand up the DB with `deploy/` (see `deploy/README.md`).

## Architecture

**`src/common/model_factory.py`** — `create_model(provider, max_tokens, temperature, top_p)` returns a provider-agnostic LangChain `BaseChatModel` (bedrock/openai/anthropic), reading `LLM_PROVIDER` / `LLM_PROVIDER_MODEL` from env. Each agent gets its own instance: Chef at `temperature=0.7` (creative), Recipe & Planner at `0` (deterministic). Sampling params are only forwarded when non-None.

**Nutrition vector store** — PostgreSQL + pgvector, built from `src/data/opennutrition_foods.tsv` (~327K foods, capped to ~20K in dev) using local `sentence-transformers/all-MiniLM-L6-v2` embeddings (384-dim, normalized, no API key). Each `Document` embeds name + alternate names + description; metadata carries per-100g macros.

The backend lives in its own package, **`src/vectorstore/`** (`pgvector_backend.py`), built on the `langchain-postgres` **v2 API — `PGVectorStore` + `PGEngine`** (the deprecated `PGVector` class is intentionally not used). `build_or_load_pgvector(embeddings, load_documents, *, table_name, embed_dim, batch_size, …)` embeds in 5,000-doc batches with progress logging, loads into the `opennutrition_foods` table (one row per food; JSONB `langchain_metadata`, cosine distance, stable OpenNutrition id as a TEXT primary key), then builds an HNSW index via `store.apply_vector_index(...)`. Idempotent via a row-count gate (no re-embed if the table is already populated; drop the table to rebuild). Provisioned by `deploy/` (Docker Compose, `pgvector/pgvector:pg17`).

The notebook keeps `embeddings` and `load_food_documents()` inline and **injects** them into `build_or_load_pgvector`, which binds the global `vectorstore`. `similarity_search(query, k)` and the consumption layer (`find_ingredients` / `retriever`) are unchanged.

**LangGraph flow** over a shared `ChefState`:
```
START → chef_plan → (route_after_chef)
   ├─ refusal → chef_summary → END
   └─ Send() fan-out → recipe_worker × N (parallel) → meal_planner → chef_summary → END
```
- `chef_plan` runs a `ScopeCheck`, parses day/meal count and any calorie range, assigns a **unique dish per slot**.
- Fan-out uses `Send("recipe_worker", RecipeTask(...))`; fan-in relies on `recipes: Annotated[list[Recipe], operator.add]` to concatenate worker results.
- `meal_planner` is the barrier: enforces per-day calorie caps by scaling portions (`_enforce_calories`), then renders markdown to `src/meal_plans/<slug>.md` (gitignored).

**Shared agent tools** (`AGENT_TOOLS`): `find_ingredients` (pgvector top-k with per-100g macros), `total_meal` (scales per-100g by grams and sums), `tavily_search` (web recipe search), `fetch_recipe_page` (fetches a recipe URL, capped at `max_chars`).

## Conventions

- **Macros are computed in code, never by the LLM.** Ingredients carry per-100g facts; meal/day/grand totals are deterministic sums scaled by gram weight. Markdown rendering is pure Python, not model output.
- **Guardrails** (`GUARDRAILS`) are prepended to every agent's system prompt and gate scope to food/nutrition; web results are treated as untrusted data, not instructions. Preserve this defense-in-depth when editing agents.
- Notebook-first: prefer extending `src/recipe_builder.ipynb`; `main.py` is not yet wired to the workflow.

## Git workflow

Coding work is checked in by **merging a worktree branch into `main` — no pull requests.**

1. **Create an isolated worktree before any coding task.** Use the `EnterWorktree` tool (or the `superpowers:using-git-worktrees` skill); it branches off `main`. Do all the work for the task there, not on the shared checkout.
2. **Work and verify in the worktree** — follow the Dev Tracker workflow below (`start_work`, the `code-quality-reviewer` pass, `complete_work`).
3. **Merge into `main` directly when done — do NOT open a PR:**
   ```bash
   git checkout main && git merge <worktree-branch> && git push origin main
   ```
   Then remove the worktree/branch.
4. **One-time prerequisite:** `main` is GitHub branch-protected by default (a required `build` check + review block direct pushes). Direct pushes only succeed once that protection is **disabled** — an admin step done outside this flow.
5. **Caution:** never `git reset --hard` while there are uncommitted working-tree changes you didn't author — it silently and unrecoverably discards them.

## Dev Tracker workflow (MCP)

The **Dev Tracker** MCP server is the primary system of record for tasks, memories, and references. Every agent (including subagents and the general-purpose agent) must use it:

1. **Search memories before starting a task.** Before beginning any task, call `search_memories` (and skim `list_memories`) for prior decisions, conventions, fixes, or solutions related to the task — apply what you find instead of rediscovering it.
2. **Create a worktree, then a task, before coding.** First create an isolated worktree (see `## Git workflow`), then `add_task` and `start_work`. Before `complete_work`, dispatch the **`code-quality-reviewer`** agent to review the changed files and address any HIGH findings; then call `complete_work` and **merge the worktree branch into `main` (no PR)**. (For docs/config-only tasks the reviewer returns a quick PASS.)
3. **Save documentation links as references.** When given (or when you find) a documentation URL/link, save it with `add_reference` using the right category (`documentation` | `api` | `dashboard` | `tool` | `article` | `general`).
4. **Record memories in Dev Tracker first.** When capturing a learning, use `add_memory` (primary) with the right category (`convention` | `debugging` | `decision` | `general` | `preference` | `solution`), then **mirror it to the local `memory/` files + `MEMORY.md`** to keep both stores in sync.
5. **Review and capture knowledge.** Proactively record design patterns, conventions, fixes, preferences, and decisions as memories — don't let hard-won context evaporate at the end of a session.
