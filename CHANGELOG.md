# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-06

### Added
- Multi-agent meal planner built on LangGraph/LangChain: a Chef coordinator scope-gates
  the request and plans a unique dish per meal slot, fans out one parallel Recipe worker
  per slot, then fans in to a Meal Planner barrier node.
- LangGraph fan-out / fan-in with `Send()` and an `operator.add` reducer over a shared
  `ChefState`, with a refusal short-circuit for out-of-scope requests.
- Layered prompt-injection defense: a structured `ScopeCheck` input gate, a `GUARDRAILS`
  prefix on every agent's system prompt, and web/tool output treated as untrusted data.
- pgvector RAG grounding over the OpenNutrition dataset using `langchain-postgres` v2
  (`PGVectorStore` + `PGEngine`, HNSW cosine index), with an idempotent row-count-gated
  build/load (`src/vectorstore/pgvector_backend.py`).
- Provider-agnostic model factory (`src/common/model_factory.py`): `create_model()` swaps
  between Bedrock, OpenAI, and Anthropic via env vars, fail-fast on missing config.
- Deterministic macro math and markdown rendering — every number the user sees is computed
  in Python, never by the LLM.
- Docker Compose deployment for PostgreSQL + pgvector (`deploy/`).
- Self-asserting verification cells in the notebook (scope probe, injection probe,
  determinism probe).
- CI workflow (byte-compile + notebook JSON validation), gitleaks secret scanning,
  Dependabot, and community-health files (README, LICENSE, SECURITY, CONTRIBUTING,
  CODE_OF_CONDUCT, issue/PR templates).

[Unreleased]: https://github.com/sheldonlsides/recipe-creator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sheldonlsides/recipe-creator/releases/tag/v0.1.0
