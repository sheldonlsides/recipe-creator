-- Runs ONCE, on first container boot (when the named volume is empty).
-- langchain-postgres creates its own tables (langchain_pg_collection /
-- langchain_pg_embedding) on first write and the HNSW index is built by the
-- notebook after load, so all this file needs to do is enable the extension.
CREATE EXTENSION IF NOT EXISTS vector;
