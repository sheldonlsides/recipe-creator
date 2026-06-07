"""pgvector backend for the nutrition vector store.

Builds (or loads) a PostgreSQL + pgvector table of OpenNutrition foods using the
langchain-postgres v2 API: a `PGVectorStore` driven by a `PGEngine`. The older
`PGVector` class is deprecated, so this module deliberately uses the v2 path.

Design notes:
  * Cosine distance is the default and matches the normalized MiniLM embeddings.
  * Metadata is stored as a single JSONB `langchain_metadata` column.
  * Idempotency is a row-count gate: a populated table is loaded as-is and never
    re-embedded. To rebuild, drop the table first.
  * Each food keeps its stable OpenNutrition id (``metadata["id"]``) as the row
    primary key via a TEXT id column, so rows stay traceable to their source
    instead of being opaque UUIDs.

Dependencies (the embedding model and the document loader) are injected by the
caller rather than imported here, which keeps this module decoupled from the
notebook and easy to test.
"""

import logging
import os
import time
from typing import Callable, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import Column, PGEngine, PGVectorStore
from langchain_postgres.v2.indexes import HNSWIndex
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# pgvector HNSW defaults: graph connectivity and build-time candidate-list size.
DEFAULT_HNSW_M = 16
DEFAULT_HNSW_EF_CONSTRUCTION = 64

# Suffix for the HNSW index name. Postgres index names are unique per schema (not
# per table), so the name is derived from the table to avoid colliding with any
# other vector table in the same database.
HNSW_INDEX_SUFFIX = "_hnsw_idx"

# TEXT id column lets the OpenNutrition string ids serve as primary keys
# (PGVectorStore's default id column is UUID).
ID_COLUMN = "langchain_id"


def _require_database_url(database_url: Optional[str]) -> str:
    """Resolve the database URL, failing fast when it is missing.

    Args:
        database_url: An explicit URL, or None to read ``DATABASE_URL`` from the
            environment.

    Returns:
        A psycopg3 SQLAlchemy URL, e.g.
        ``postgresql+psycopg://dev:devpass@localhost:5432/appdb``.

    Raises:
        EnvironmentError: If no URL is given and ``DATABASE_URL`` is unset.
    """

    url = database_url or os.getenv("DATABASE_URL")

    if not url:
        raise EnvironmentError(
            "The pgvector backend requires DATABASE_URL in your .env, e.g. "
            "postgresql+psycopg://dev:devpass@localhost:5432/appdb (see deploy/README.md)."
        )

    return url


def _table_row_count(database_url: str, table: str) -> int:
    """Count rows already loaded in the PGVectorStore table.

    Uses a short-lived synchronous SQLAlchemy engine because ``PGEngine`` exposes
    no generic count helper. ``table`` is an internal constant, never user input.

    Args:
        database_url: psycopg3 SQLAlchemy URL.
        table: The PGVectorStore table name to count.

    Returns:
        The row count, or 0 if the table does not exist yet.
    """

    engine = create_engine(database_url)

    try:
        with engine.connect() as conn:
            return conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
    except Exception as exc:
        # The table is created on first build; before that the count is just 0.
        logger.debug("Row-count gate: table %r not counted (%s)", table, exc)

        return 0
    finally:
        engine.dispose()


def build_or_load_pgvector(
    embeddings: Embeddings,
    load_documents: Callable[[], list[Document]],
    *,
    table_name: str,
    embed_dim: int,
    batch_size: int,
    database_url: Optional[str] = None,
    hnsw_m: int = DEFAULT_HNSW_M,
    hnsw_ef_construction: int = DEFAULT_HNSW_EF_CONSTRUCTION,
) -> PGVectorStore:
    """Load the pgvector table if populated, else embed + load + index it.

    The first full (~327K-row) build embeds every food on CPU and takes many
    minutes, so it runs in batches and logs ``embedded X/total`` progress, then
    builds an HNSW index for fast cosine search. Later runs hit the instant,
    count-gated load path.

    Args:
        embeddings: Embedding model used to vectorize foods (e.g. MiniLM).
        load_documents: Zero-arg callable returning the food Documents to embed.
            Called only on the first build, so the load path stays instant.
        table_name: PGVectorStore table name (public schema).
        embed_dim: Embedding dimension; pins the vector column to ``vector(N)``.
        batch_size: Foods embedded per ``add_documents`` call during the build.
        database_url: Override URL; defaults to ``$DATABASE_URL`` (fail-fast if
            unset).
        hnsw_m: HNSW graph connectivity.
        hnsw_ef_construction: HNSW build-time candidate-list size.

    Returns:
        A ready-to-query ``PGVectorStore`` bound to ``table_name``.
    """

    url = _require_database_url(database_url)
    engine = PGEngine.from_connection_string(url)
    existing = _table_row_count(url, table_name)

    if not existing:
        # Create (or replace an empty/partial) table before create_sync, which
        # requires the table to already exist. The TEXT id column keeps the
        # stable OpenNutrition ids as primary keys.
        engine.init_vectorstore_table(
            table_name,
            embed_dim,
            id_column=Column(ID_COLUMN, "TEXT"),
            overwrite_existing=True,
        )

    store = PGVectorStore.create_sync(engine, embeddings, table_name)

    if existing:
        logger.info(
            "Loaded pgvector table %r (%d foods) from %s",
            table_name, existing, url.rsplit("@", 1)[-1],
        )

        return store

    docs = load_documents()
    total = len(docs)
    
    logger.info(
        "Building pgvector table %r: %d foods in batches of %d "
        "(one-time; may take many minutes) ...",
        table_name, total, batch_size,
    )

    start_time = time.time()

    for start in range(0, total, batch_size):
        chunk = docs[start:start + batch_size]
        
        # Stable per-food ids keep rows traceable to their OpenNutrition source.
        ids = [doc.metadata["id"] for doc in chunk]
        store.add_documents(chunk, ids=ids)
        done = min(start + batch_size, total)

        logger.info(
            "  embedded %d/%d (%d%%) - %.0fs elapsed",
            done, total, done * 100 // total, time.time() - start_time,
        )

    # Build the HNSW cosine index AFTER the bulk load (far cheaper than per-insert).
    store.apply_vector_index(HNSWIndex(
        name=f"{table_name}{HNSW_INDEX_SUFFIX}",
        m=hnsw_m,
        ef_construction=hnsw_ef_construction,
    ))

    logger.info(
        "Built pgvector table: %d foods in %.0fs (HNSW index ready)",
        total, time.time() - start_time,
    )

    return store
