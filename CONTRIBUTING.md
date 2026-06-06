# Contributing to recipe-creator

Thanks for your interest in contributing! This guide explains how to set up the project, propose
changes, and get them merged.

## Getting started

1. Fork the repository and clone your fork.
2. Install dependencies with [uv](https://docs.astral.sh/uv/) (Python 3.12):
   ```bash
   uv sync
   ```
3. Copy `.env.example` to `.env` and fill in the required values (see the README's
   *Configuration* section).
4. Create a branch off `main`: `git checkout -b my-change`.

## Project layout

This is a **notebook-first** project: the full workflow lives in `src/recipe_builder.ipynb`.
Prefer extending the notebook over adding new modules. `src/model_factory.py` is the one
standalone module (the provider-agnostic model factory); `main.py` is an unused stub.

## Making changes

- Keep each pull request focused on one logical change.
- Follow the existing code style and conventions in the repo (see `CLAUDE.md` for the
  architecture and conventions).
- **Macros and nutrition totals are computed in code, never produced by the LLM** — preserve this
  when editing agents or tools.
- Keep the `GUARDRAILS` defense-in-depth in place: they gate scope to food/nutrition and treat
  web results as untrusted data.
- Update documentation (README, docstrings) when behavior or usage changes.

## Running checks locally

Run the notebook headless to confirm it still executes end to end before opening a PR:

```bash
uv run --with nbconvert -- jupyter nbconvert --to notebook --execute src/recipe_builder.ipynb
```

Always run Python/notebooks through `uv run` so the project `.venv` (not Anaconda) is used.

## Submitting a pull request

1. Push your branch to your fork.
2. Open a pull request against `main` and fill out the PR template.
3. Describe what changed and why, and link any related issues.
4. A maintainer will review; please respond to feedback and keep the branch up to date.

## Reporting bugs and requesting features

Open an issue using the provided templates. Include steps to reproduce, expected vs. actual
behavior, and your environment for bugs; a clear use case and motivation for feature requests.

## Code of conduct

By participating, you agree to abide by the project's [Code of Conduct](CODE_OF_CONDUCT.md).
