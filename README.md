# LangGraph Fan-Out, Guardrails, and pgvector RAG: A Worked Example

[![CI](https://github.com/sheldonlsides/recipe-creator/actions/workflows/ci.yml/badge.svg)](https://github.com/sheldonlsides/recipe-creator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

A single LangGraph notebook that demonstrates three production patterns for tool-using agents:

- **Fan-out / fan-in with `Send()`** and an `operator.add` reducer, joined at a barrier node that
  runs deterministic Python instead of trusting the LLM for arithmetic.
- **Layered prompt-injection defense.** A structured `ScopeCheck` gate refuses off-topic requests
  before any tool runs, a `GUARDRAILS` prefix sits on every agent's system prompt, and all web and
  tool output is treated as untrusted data.
- **pgvector RAG grounding** with `langchain-postgres` v2 (`PGVectorStore` + HNSW cosine index),
  embedded once and idempotently loaded on every subsequent run.

The vehicle is a meal planner. Give it a request like *"a 1-day high-protein, low-carb plan, 1,800
to 2,000 kcal, include snacks, allergic to shellfish"* and a team of agents plans unique dishes,
researches a real recipe for each one in parallel, grounds every ingredient in a nutrition database,
and renders a calorie-checked meal plan as markdown. Every macro number is computed in Python, not
invented by the LLM.

Everything lives in one notebook: `src/recipe_builder.ipynb`.

---

## What you get

A self-contained notebook that builds the graph end to end:

- A `StateGraph` with dynamic fan-out, a deterministic barrier, and a refusal short-circuit.
- A pgvector-backed retrieval tool over a real food database (~327K rows from OpenNutrition).
- A provider-agnostic model factory (`create_model()`) that swaps between Bedrock, OpenAI, and
  Anthropic via env vars.
- A scope gate plus guardrail prefix that blocks out-of-scope and injection-style requests before
  any tool runs.
- Deterministic markdown rendering for every meal plan, with macros recomputed in Python at every
  step.

See [`## Example output`](#example-output) for a representative generated plan.

## What you'll learn

- **LangGraph fan-out / fan-in**: dynamic parallelism with `Send(...)` and an `operator.add`
  reducer that concatenates worker results at a barrier node.
- **Scope-gating & prompt-injection defense**: a single `GUARDRAILS` block, a structured
  `ScopeCheck` gate that refuses off-topic requests *before* any tool runs, and treating all
  web/tool output as untrusted data.
- **RAG grounding with pgvector**: embedding a large dataset locally and querying it with
  `langchain-postgres` v2 (`PGVectorStore` + HNSW cosine index).
- **Keeping the math out of the model**: structured Pydantic outputs plus deterministic Python for
  every number the user sees.
- **A provider-agnostic model factory**: one `create_model()` call swaps between Bedrock, OpenAI,
  and Anthropic with no code changes.
- **A notebook that asserts its own claims**: the final cells run as a verification pass — a scope
  probe confirms the input gate refuses off-topic and jailbreak inputs before any tool runs; an
  injection probe patches the page fetch to return a poisoned page and confirms the agents ignore
  the embedded payload while the calorie barrier still holds; a determinism probe confirms rendered
  macros match a fresh `total_meal()` computation. If the notebook runs end to end, the claims hold.

## Why this exists

LLMs are not arithmetic engines. Ask one to sum a column of macros across a week of meals and the
errors compound silently. The same pattern shows up anywhere a tool-using agent has to roll up
numeric facts: invoices, financial summaries, capacity plans, anything where a small rounding error
becomes a large reporting error one node downstream.

The fix is to let the model plan and research, then let deterministic Python do the math. This
notebook shows that split end to end with a meal-planner use case. Ingredients are looked up in a
pgvector store carrying per-100g macros; portions are scaled by gram weight; meal, day, and grand
totals are sums in code. The model picks dishes, finds recipes, and estimates portion sizes. It
never adds two numbers the user sees.

The same notebook also demonstrates dynamic parallelism (one Recipe worker per meal slot, running
concurrently) and a layered defense against prompt injection. Those patterns are the reusable bits;
the meal plans are the demo.

## How it works at a glance

```
START → chef_plan → (route_after_chef)
   ├─ out of scope ─────────────────────────────→ chef_summary → END   (refusal)
   └─ Send() fan-out → recipe_worker × N (parallel) → meal_planner → chef_summary → END
```

- **`chef_plan`** *(Chef, temp 0.7)*: runs a `ScopeCheck`; if the request isn't about food it
  refuses and the whole graph short-circuits. Otherwise it parses the day/meal/snack counts and any
  calorie range, then assigns a **unique dish to every slot** (e.g. *Day 1 Breakfast → Spinach &
  Feta Egg Scramble*).
- **`route_after_chef`**: the conditional edge. On refusal it routes straight to the summary; in
  scope it emits one `Send("recipe_worker", RecipeTask(...))` per planned meal (the fan-out).
- **`recipe_worker`** *(Recipe, temp 0)*: one parallel worker per slot. It web-searches for the
  exact assigned dish (Tavily), fetches the page, grounds each ingredient in pgvector, estimates
  portion grams toward the meal's calorie budget, and emits a structured `Recipe`. Workers append to
  `recipes: Annotated[list[Recipe], operator.add]` (the fan-in).
- **`meal_planner`** *(Planner, temp 0)*: the barrier; runs once all workers finish. It enforces
  per-day calorie caps by scaling portions (`_enforce_calories`, capped at `MAX_PORTION_SCALE = 2.5`),
  asks the model only for a title + one-sentence intro, then renders the markdown deterministically
  (`_render_plan_md`) and writes it to disk.
- **`chef_summary`**: closes the loop with the saved path and calorie range (or the refusal).

State lives in one `ChefState` Pydantic model passed through every node.

## Who this is for

You're comfortable with Python and have seen an LLM agent before; you don't need prior LangGraph
experience. The notebook builds the graph step by step. If `StateGraph`, nodes, and edges are new,
skim the [LangGraph quickstart](https://langchain-ai.github.io/langgraph/) first.

This is local-first. It needs a local PostgreSQL plus pgvector database, so there's no one-click
Colab button. The Quick start below gets you running in a few commands.

## What's in the box

| Path | Purpose |
|------|---------|
| `src/recipe_builder.ipynb` | The whole thing: vector store, tools, guardrails, agents, graph, and example runs, top to bottom. |
| `src/common/model_factory.py` | `create_model()`: provider-agnostic LangChain chat model (Bedrock / OpenAI / Anthropic), fail-fast on missing config. |
| `src/vectorstore/` | The pgvector backend (`build_or_load_pgvector`): idempotent build/load of the nutrition table. |
| `deploy/` | Docker Compose for PostgreSQL + pgvector (`pgvector/pgvector:pg17`). See `deploy/README.md`. |
| `docs/pgvector-setup.md` | pgvector tuning notes and the AWS RDS path. |
| `src/data/` | Where the OpenNutrition TSV lives (≈269 MB, **gitignored**; download separately). |
| `.env.example` | Every environment variable, documented. Copy to `.env`. |

## Quick start (local)

Requires **Python 3.12** and the [uv](https://docs.astral.sh/uv/) package manager. Always run
through `uv run` so the project `.venv` is used (not a system/Anaconda Python).

```bash
# 1. Install dependencies (from the committed lockfile)
uv sync                          # or: ./install_deps

# 2. Configure secrets — copy the template and fill it in
cp .env.example .env
#    set LLM_PROVIDER + LLM_PROVIDER_MODEL, the matching provider key,
#    TAVILY_API_KEY, and DATABASE_URL (see the table below)

# 3. Stand up PostgreSQL + pgvector (Docker)
cd deploy && docker compose up -d && cd ..   # details in deploy/README.md

# 4. Drop the nutrition dataset in place
#    download opennutrition_foods.tsv into src/data/  (≈269 MB, gitignored)

# 5. Run the notebook headless ...
uv run --with nbconvert -- jupyter nbconvert --to notebook --execute src/recipe_builder.ipynb

#    ... or open it interactively
uv run --with nbconvert jupyter notebook src/recipe_builder.ipynb
```

**First run is slow, once.** Building the vector table embeds the full ~326,759-food dataset on CPU
in batches of 5,000 and builds an HNSW index (many minutes). Every run after that hits an instant,
row-count-gated load path (to rebuild, drop the table).

Generated plans land in `src/meal_plans/<slug>.md` (gitignored).

## Environment variables

Copy `.env.example` to `.env`. `create_model()` and the pgvector backend **fail fast** if their
required vars are missing.

| Variable | Required? | Used for | Notes |
|----------|-----------|----------|-------|
| `LLM_PROVIDER` | ✅ | Selects the LLM backend | `bedrock` \| `openai` \| `anthropic` |
| `LLM_PROVIDER_MODEL` | ✅ | Model id for that provider | e.g. `gpt-4o-mini`, `claude-sonnet-4-6` |
| `OPENAI_API_KEY` | if `openai` | OpenAI credentials | — |
| `ANTHROPIC_API_KEY` | if `anthropic` | Anthropic credentials | Bedrock uses AWS creds / `AWS_REGION` instead |
| `TAVILY_API_KEY` | ✅ | Web recipe search | Used by the `tavily_search` tool |
| `DATABASE_URL` | ✅ | pgvector connection | psycopg3 URL, e.g. `postgresql+psycopg://dev:devpass@localhost:5433/appdb` |
| `HF_TOKEN` | optional | Embedding model download | Only needed for gated/private HF models |
| `USER_AGENT` | optional | Outbound HTTP header for page fetches | Defaults to `recipe-creator/1.0` |
| `LANGSMITH_API_KEY` / `LANGSMITH_ENDPOINT` / `LANGSMITH_PROJECT` | optional | LangSmith tracing | — |

## Architecture notes (the bits worth knowing)

- **One state object, one reducer.** `ChefState` flows through every node. The only field with a
  reducer is `recipes: Annotated[list[Recipe], operator.add]`. That's what lets N parallel workers
  each append one recipe and have them concatenate cleanly at the barrier. Everything else is plain
  last-writer-wins.
- **Fan-out is dynamic.** `route_after_chef` returns a *list* of `Send("recipe_worker", ...)` sized
  to the plan, so a 3-meal day spawns 3 workers and a 5-meal day spawns 5. No hardcoded width.
- **The scope gate runs first and blocks everything.** An out-of-scope request never reaches a tool,
  a web search, or the filesystem. `chef_plan` returns a refusal and `route_after_chef` jumps to
  the summary. Defense-in-depth: `GUARDRAILS` is also prepended to every agent's system prompt, and
  Tavily results / fetched pages are treated as **data, never instructions**.
- **Macros are code, not model output.** `find_ingredients` returns per-100g facts from pgvector;
  `total_meal` scales by grams and sums; `_recompute_recipe_macros` and `_render_plan_md` produce
  the tables and totals. The model never adds two numbers the user sees.
- **pgvector, built once.** `build_or_load_pgvector` uses a **row-count gate** for idempotency: a
  populated table is loaded as-is and never re-embedded. The HNSW cosine index is applied *after* the
  bulk load (far cheaper than per-insert), and each row keeps its stable OpenNutrition id as the
  primary key so results stay traceable to source.
- **Per-agent temperatures, one factory.** `create_model()` is called three times: Chef at `0.7`
  (creative dish planning), Recipe and Planner at `0` (deterministic). The provider is chosen
  entirely by env vars.

## Common gotchas

- **Use `uv run` for everything.** Launching the notebook with a system/Anaconda kernel pulls in
  mismatched dependencies; the `uv run` commands above pin it to the project `.venv`.
- **`DATABASE_URL` is mandatory.** The nutrition store is pgvector-only. There is no local-file
  fallback. Stand up the DB with `deploy/` before running, and note the example port is **5433**
  (5432 is often a host-native Postgres).
- **The dataset isn't in the repo.** `opennutrition_foods.tsv` (~269 MB) exceeds GitHub's file-size
  limit and is gitignored. Download it into `src/data/` yourself.
- **The first build really is slow.** Embedding ~327K foods on CPU takes many minutes. It's
  one-time; subsequent runs load instantly. Cap `MAX_ROWS` in the config cell for a fast dev subset.
- **Dietary constraints ride in the request.** Allergies and preferences (*"allergic to shellfish"*,
  *"vegetarian"*) go in the natural-language request. The Chef parses them when planning dishes.
- **Don't trust scraped pages.** Recipe pages and search results are extracted for facts only; the
  guardrails explicitly forbid following any instructions found inside them.

## Example output

A representative generated plan from a one-day high-protein request.

```markdown
# High-Protein, Low-Carb Day

A shellfish-free day built around lean protein and non-starchy vegetables.

> **Note:** Day 1 portions scaled ×1.12 to land inside the 1,800–2,000 kcal target.

## Day 1

### Day 1 Breakfast: Spinach & Feta Egg Scramble

A quick three-egg scramble with wilted spinach and a little feta.

| Ingredient | Amount | Calories | Protein (g) | Carbs (g) | Sugars (g) | Fat (g) |
|------------|--------|---------:|------------:|----------:|-----------:|--------:|
| Eggs       | 3 (150 g) | 215   | 18.8        | 1.1       | 1.1        | 14.9    |
| Spinach    | 60 g      | 14    | 1.7         | 2.2       | 0.3        | 0.2     |
| Feta       | 30 g      | 79    | 4.3         | 1.2       | 1.2        | 6.4     |

**Meal total:** calories=308, protein=24.8g, carbs=4.5g, fat=21.5g

**Recipe** — 10 min
1. Whisk the eggs...
2. ...

_Source: https://example.com/spinach-feta-scramble_

## Final Totals

| Day   | Calories | Carbs (g) | Protein (g) | Fat (g) |
|-------|---------:|----------:|------------:|--------:|
| Day 1 |    1,932 |        58 |         148 |     118 |
```

## Library pins

Python **3.12**, dependencies locked in `uv.lock`. `torch` is pinned (`torch==2.11.0` in
`pyproject.toml`) to a known-good combination for the embedding stack on macOS. Keep the pin unless
you've tested an upgrade.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities privately.

## License

Released under the [MIT License](LICENSE).
