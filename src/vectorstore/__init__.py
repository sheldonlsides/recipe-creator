"""Vector-store backend(s) for the nutrition index.

Houses the pgvector backend that the notebook (`src/recipe_builder.ipynb`) builds
or loads at startup. The project standardizes on PostgreSQL + pgvector via the
langchain-postgres v2 API (`PGVectorStore` + `PGEngine`); the deprecated `PGVector`
class is intentionally not used.
"""

from .pgvector_backend import build_or_load_pgvector

__all__ = ["build_or_load_pgvector"]
