-- Runs ONCE, on first container boot (when the named volume is empty).
-- PGVectorStore creates its table (opennutrition_foods) via
-- init_vectorstore_table on first build, and the HNSW index is built by the
-- notebook after load, so all this file needs to do is enable the extension.
CREATE EXTENSION IF NOT EXISTS vector;
