# PostgreSQL 17 + pgvector Local Setup (Docker Desktop) with Bulk Load Guide and AWS RDS Production Path

## Overview

This artifact provisions PostgreSQL 17 with the pgvector extension in Docker Desktop for local development, using a named Docker volume for data persistence. It includes a bulk loading guide tuned for vector ingestion at the 100K to 1M+ scale, and a separate final section covering eventual deployment to AWS RDS for PostgreSQL.

Versions targeted:

1. PostgreSQL 17 via the official `pgvector/pgvector:pg17` image. As of June 2026, that tag resolves to `0.8.2-pg17-trixie`. Other PG17 variants: `pg17`, `pg17-bookworm`, `0.8.2-pg17`, `0.8.2-pg17-bookworm`.
2. pgvector 0.8.2 (released 2026-02-26). 0.8.2 fixes CVE-2026-3172, a buffer overflow in parallel HNSW index builds affecting versions 0.6.0 through 0.8.1.

Source URLs:

* pgvector Docker Hub: https://hub.docker.com/r/pgvector/pgvector/tags
* pgvector 0.8.2 release: https://www.postgresql.org/about/news/pgvector-082-released-3245/
* pgvector GitHub: https://github.com/pgvector/pgvector

## Prerequisites

1. Docker Desktop installed and running (Mac, Windows, or Linux).
2. `docker compose` v2 (bundled with current Docker Desktop).
3. A Postgres client for verification: `psql` CLI, DBeaver, TablePlus, or pgAdmin.
4. Port 5432 free on the host (or change the mapping below).
5. Docker Desktop resource allocation: at least 4 CPU and 8 GB RAM for typical vector workloads. Raise to 8 CPU and 16 GB RAM for 1M+ vectors or 1536+ dim embeddings. Set in Docker Desktop, Settings, Resources.

## Project layout

```
pgvector-local/
├── docker-compose.yml
├── initdb/
│   └── 001-init-vector.sql
└── scripts/
    └── bulk_load.py
```

## Sizing and volume recommendations

These guide the compose file values below.

**Disk sizing formula (per vector table):**

```
raw_data    = N_vectors * dim * 4 bytes
hnsw_index  = raw_data * 1.3 (approx)
wal_headroom= raw_data * 0.5 during loads
total       = raw_data * 2.8  (round up generously)
```

Concrete examples (1536-dim, e.g. OpenAI `text-embedding-3-small`):

| Vector count | Raw data | With HNSW + WAL | Recommended volume headroom |
| ------------ | -------- | --------------- | --------------------------- |
| 100K         | ~0.6 GB  | ~1.7 GB         | 5 GB                        |
| 300K         | ~1.8 GB  | ~5 GB           | 10 GB                       |
| 1M           | ~6 GB    | ~17 GB          | 30 GB                       |
| 10M          | ~60 GB   | ~170 GB         | 250 GB                      |

**Memory recommendations for the container:**

| Workload                | `shared_buffers` | `maintenance_work_mem` (session) | `work_mem` | `shm_size`  |
| ----------------------- | ---------------- | -------------------------------- | ---------- | ----------- |
| Dev, <100K vectors      | 256 MB           | 512 MB                           | 16 MB      | 256 MB      |
| 300K to 1M vectors      | 1 GB             | 2 GB                             | 32 MB      | 1 GB        |
| 1M+ vectors, HNSW build | 2 GB             | 4 to 8 GB                        | 64 MB      | 2 GB        |

`maintenance_work_mem` is set per session right before `CREATE INDEX`, not globally. `shared_buffers` and `work_mem` go in the `command` block of the compose file (shown below).

## docker-compose.yml

```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    container_name: pgvector-pg17
    restart: unless-stopped
    shm_size: '1gb'
    environment:
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: devpass
      POSTGRES_DB: appdb
    ports:
      - "5432:5432"
    volumes:
      - pgvector_data:/var/lib/postgresql/data
      - ./initdb:/docker-entrypoint-initdb.d:ro
    command:
      - "postgres"
      - "-c"
      - "shared_buffers=1GB"
      - "-c"
      - "work_mem=32MB"
      - "-c"
      - "max_wal_size=4GB"
      - "-c"
      - "checkpoint_timeout=15min"
      - "-c"
      - "max_parallel_maintenance_workers=4"
      - "-c"
      - "max_parallel_workers=4"
      - "-c"
      - "effective_cache_size=4GB"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dev -d appdb"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgvector_data:
    name: pgvector_data
```

Notes on the tuning:

1. `shm_size` raised to 1 GB. The default 64 MB causes parallel HNSW builds and large hash joins to fail.
2. `shared_buffers=1GB` and `effective_cache_size=4GB` assume ~8 GB allocated to Docker Desktop. Scale up for larger workloads (rule of thumb: `shared_buffers` ≈ 25% of container memory; `effective_cache_size` ≈ 50 to 75%).
3. `max_wal_size=4GB` and `checkpoint_timeout=15min` reduce checkpoint thrash during bulk loads.
4. `max_parallel_maintenance_workers=4` lets `CREATE INDEX` parallelize the HNSW build. Match to allocated CPU.
5. `pgvector_data` is a named Docker volume (not a bind mount). Data survives `docker compose down`. It is removed only by `docker compose down -v` or `docker volume rm pgvector_data`.
6. The `initdb` directory is mounted read-only into `/docker-entrypoint-initdb.d`. Scripts there run only on first boot, when the data volume is empty.

## initdb/001-init-vector.sql

```sql
-- Runs only on first container boot (when the named volume is empty).
CREATE EXTENSION IF NOT EXISTS vector;

-- Optional smoke-test table; safe to remove.
CREATE TABLE IF NOT EXISTS items (
  id BIGSERIAL PRIMARY KEY,
  embedding vector(3)
);
```

## Start and verify

```bash
docker compose up -d
docker compose logs -f db

docker volume ls | grep pgvector_data
docker volume inspect pgvector_data

docker exec -it pgvector-pg17 psql -U dev -d appdb -c "\dx"
docker exec -it pgvector-pg17 psql -U dev -d appdb \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Expected:

```
 extname | extversion
---------+------------
 vector  | 0.8.2
```

## Smoke test pgvector

```bash
docker exec -it pgvector-pg17 psql -U dev -d appdb <<'SQL'
INSERT INTO items (embedding) VALUES ('[1,2,3]'), ('[4,5,6]'), ('[1,1,1]');
SELECT id, embedding, embedding <-> '[3,1,2]' AS l2_distance
FROM items
ORDER BY embedding <-> '[3,1,2]'
LIMIT 5;
SQL
```

Distance operators: `<->` L2, `<#>` negative inner product, `<=>` cosine.

## Connection strings

From the host:

```
postgresql://dev:devpass@localhost:5432/appdb
```

From another container on the same compose network use the service name `db`:

```
postgresql://dev:devpass@db:5432/appdb
```

For `langchain-postgres` (which requires psycopg3), use:

```
postgresql+psycopg://dev:devpass@localhost:5432/appdb
```

## Bulk loading vectors

This is the recommended path for any ingest above 10K vectors. Approximate throughput on a developer laptop (1536-dim vectors, default tuning):

| Method                                 | Rate          | 300K time |
| -------------------------------------- | ------------- | --------- |
| `INSERT` row by row                    | ~500/s        | ~10 min   |
| `executemany` batched INSERT           | ~3K/s         | ~100s     |
| LangChain `add_documents` (default)    | ~2K/s         | ~150s     |
| `COPY` binary via psycopg3             | ~30K+/s       | <15s      |

Three rules drive the speedup:

1. Use `COPY` binary, not `INSERT`. Roughly an order of magnitude faster.
2. Build the HNSW index AFTER the bulk load, not before. Inserting into an existing HNSW index is slow because each insert mutates the graph.
3. Raise `maintenance_work_mem` for the session that builds the index. Default 64 MB is far too small for HNSW on real data.

### scripts/bulk_load.py

```python
"""Bulk load vectors into pgvector using psycopg3 binary COPY.

Usage:
    pip install "psycopg[binary]" pgvector numpy
    python scripts/bulk_load.py
"""
import numpy as np
import psycopg
from pgvector.psycopg import register_vector

CONN = "postgresql://dev:devpass@localhost:5432/appdb"
DIM = 1536
TABLE = "docs"

def vector_iterator(n: int):
    """Replace with your real source (parquet, jsonl, embedding API, etc.)."""
    rng = np.random.default_rng(42)
    for i in range(n):
        yield (f"document {i}", rng.standard_normal(DIM).astype(np.float32))

def main(n_vectors: int = 300_000):
    with psycopg.connect(CONN, autocommit=False) as conn:
        register_vector(conn)

        # 1. Create table WITHOUT index for fast loading.
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id bigserial PRIMARY KEY,
                content text,
                embedding vector({DIM})
            )
        """)
        conn.execute(f"TRUNCATE {TABLE} RESTART IDENTITY")

        # 2. Speed up the load. Local dev only; do not use in prod.
        conn.execute("SET synchronous_commit = OFF")
        conn.execute("SET maintenance_work_mem = '2GB'")

        # 3. Binary COPY. Vastly faster than INSERT.
        with conn.cursor().copy(
            f"COPY {TABLE} (content, embedding) FROM STDIN WITH (FORMAT BINARY)"
        ) as copy:
            copy.set_types(["text", "vector"])
            for content, vec in vector_iterator(n_vectors):
                copy.write_row([content, vec])

        conn.commit()

        # 4. Build HNSW index AFTER the load.
        conn.execute("SET maintenance_work_mem = '2GB'")
        conn.execute("SET max_parallel_maintenance_workers = 4")
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS {TABLE}_embedding_hnsw_idx
            ON {TABLE} USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)

        # 5. Refresh planner stats.
        conn.execute(f"ANALYZE {TABLE}")
        conn.commit()

        count = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
        print(f"Loaded {count:,} vectors into {TABLE}")

if __name__ == "__main__":
    main()
```

### HNSW index tuning

| Parameter                  | Default | When to change                                                                              |
| -------------------------- | ------- | ------------------------------------------------------------------------------------------- |
| `m`                        | 16      | Increase to 32 for higher recall on hard datasets; doubles index size                       |
| `ef_construction`          | 64      | Increase to 128 or 200 for better recall; slower build                                      |
| `hnsw.ef_search` (session) | 40      | Increase at query time for better recall vs. latency tradeoff (e.g. `SET hnsw.ef_search=100`) |

Choose the operator class to match your distance metric:

* `vector_cosine_ops` for cosine (most common with OpenAI, Cohere, Voyage embeddings)
* `vector_l2_ops` for Euclidean
* `vector_ip_ops` for inner product

The query operator must match: `<=>` for cosine, `<->` for L2, `<#>` for inner product. A mismatched operator silently falls back to a sequential scan.

### Half-precision storage to cut memory in half

pgvector 0.7+ supports `halfvec` (16-bit floats). At 1536 dims this halves storage and roughly doubles cache hit rate, with negligible recall loss for most embedding models.

```sql
CREATE TABLE docs_half (
  id bigserial PRIMARY KEY,
  content text,
  embedding halfvec(1536)
);
CREATE INDEX ON docs_half USING hnsw (embedding halfvec_cosine_ops);
```

### LangChain interop

If you use `langchain-postgres` `PGVectorStore`, two options:

1. Let LangChain create its schema (table with `langchain_id`, `content`, `embedding`, JSONB metadata) and call `add_documents(batch_size=1000)`. Simpler but slower.
2. Bulk load via `COPY` into a raw table, then point `PGVectorStore` at the same table by matching its schema exactly. Faster, but you must maintain schema compatibility.

For 300K+ vectors, option 2 is worth it.

### Watch-outs during bulk loads

1. `synchronous_commit = OFF` doubles throughput but a crash mid-load can lose committed rows. Acceptable for local dev; do not use in production without understanding the tradeoff.
2. Disable triggers and foreign keys if you have them on the target table during the load, then re-enable.
3. `TRUNCATE` instead of `DELETE` when wiping a table; orders of magnitude faster and reclaims disk.
4. After large loads, run `ANALYZE` so the planner has accurate stats. `VACUUM ANALYZE` if you also did large deletes.
5. Monitor `docker stats` during the load. If memory hits the container limit you will see slow checkpoints and possible OOM kills.

## Common operations

```bash
docker compose down              # keeps the volume (data survives)
docker compose down -v           # deletes the volume (data lost)
docker compose pull && docker compose up -d   # update image
docker exec -it pgvector-pg17 pg_dump -U dev -Fc appdb > backup.dump
```

To upgrade pgvector after pulling a newer image:

```sql
ALTER EXTENSION vector UPDATE;
```

---

# Future: Deploying to AWS RDS for Production

This section is informational, for when you migrate from local Docker to AWS RDS for PostgreSQL.

## RDS engine and pgvector version

Per the AWS extension version matrix (https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html) and the RDS PG release notes (https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-versions.html):

| RDS PG17 minor | pgvector version                                                                          |
| -------------- | ----------------------------------------------------------------------------------------- |
| 17.10          | 0.8.2                                                                                     |
| 17.9           | 0.8.1                                                                                     |
| 17.8           | 0.8.1 (first introduced in 17.8: "The pgvector extension was updated to version 0.8.1")   |
| 17.1 to 17.7   | 0.8.0                                                                                     |

Provision an instance on engine version **17.10** (or later) to match the local image's pgvector 0.8.2.

## Enabling pgvector on RDS

pgvector is preinstalled in the RDS engine binary. **No parameter group change and no `shared_preload_libraries` edit is required.** You must run `CREATE EXTENSION vector;` as the master user (which holds `rds_superuser`) or as a role granted `rds_superuser`.

Steps:

1. Create an RDS for PostgreSQL 17 instance on engine version 17.10 (Console, CLI, or Terraform).
2. Place it in a VPC subnet group; security group allows TCP 5432 from your app tier only.
3. Connect with the master user:
   ```
   psql "host=<endpoint> port=5432 user=<master> dbname=<db> sslmode=require"
   ```
4. Enable the extension:
   ```sql
   CREATE EXTENSION vector;
   SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
   ```
5. (Optional, defense in depth) Restrict installable extensions via the dynamic parameter `rds.allowed_extensions` (default `*`):
   ```
   rds.allowed_extensions = 'vector,pg_stat_statements,...'
   ```

## Instance sizing for vector workloads on RDS

Rough starting points for production:

| Vector count        | Instance class        | Storage (gp3)      | Notes                                       |
| ------------------- | --------------------- | ------------------ | ------------------------------------------- |
| <500K, light QPS    | `db.t4g.large`        | 50 GB              | Burstable; fine for dev/staging             |
| 500K to 5M          | `db.m7g.xlarge`       | 200 GB, 6000 IOPS  | Graviton, good price/perf                   |
| 5M to 50M           | `db.r7g.2xlarge`      | 500 GB, 12000 IOPS | Memory-optimized; HNSW needs RAM            |
| 50M+                | `db.r7g.4xlarge`+     | 1 TB+, 16000 IOPS  | Consider Aurora PostgreSQL for read scaling |

Set `maintenance_work_mem` via a parameter group (in KB, e.g. `2097152` for 2 GB), or per session before `CREATE INDEX`. There is no `--shm-size` knob on RDS; the kernel handles shared memory automatically.

## Differences from local Docker

1. **No filesystem or OS access.** Everything goes through SQL, the AWS Console, AWS CLI, or parameter groups. No `docker exec`.
2. **No true superuser.** `rds_superuser` can `CREATE EXTENSION vector` but cannot modify `shared_preload_libraries` directly or change OS-level config.
3. **Static parameters require a reboot.** pgvector itself does not need this.
4. **Storage and HA are managed.** Multi-AZ replication is at the storage layer; the standby is not queryable. Use Multi-AZ DB Cluster if you need a readable standby.
5. **Extension version pinning.** RDS does not auto-upgrade extensions across engine upgrades. After upgrading, run `ALTER EXTENSION vector UPDATE;` per database.

## Migrating local data to RDS

```bash
# 1. Dump from the local container (custom format).
docker exec -t pgvector-pg17 pg_dump -U dev -Fc -d appdb -f /tmp/appdb.dump
docker cp pgvector-pg17:/tmp/appdb.dump ./appdb.dump

# 2. Pre-create the extension on RDS (as master user).
psql "host=<endpoint> user=<master> dbname=appdb sslmode=require" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. Restore. Use --no-owner and --no-acl to avoid role mismatches.
pg_restore --no-owner --no-acl --verbose \
  -h <endpoint> -U <master> -d appdb \
  -j 4 ./appdb.dump
```

For large or zero-downtime migrations, use AWS DMS with full-load + CDC, or pglogical-based logical replication. AWS guidance: https://aws.amazon.com/blogs/database/best-practices-for-migrating-postgresql-databases-to-amazon-rds-and-amazon-aurora/

**Tip on rebuilding indexes after restore:** `pg_restore` recreates indexes serially by default. For faster index builds, restore data first with `--data-only`, then create indexes manually with elevated `maintenance_work_mem` and parallel workers:

```sql
SET maintenance_work_mem = '8GB';
SET max_parallel_maintenance_workers = 8;
CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
```

## Verification on RDS

```sql
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
-- expect: vector | 0.8.2  (on RDS PG 17.10+)

CREATE TABLE IF NOT EXISTS rds_smoke (id bigserial PRIMARY KEY, e vector(3));
INSERT INTO rds_smoke (e) VALUES ('[1,2,3]'), ('[4,5,6]');
SELECT id, e <-> '[3,1,2]' AS d FROM rds_smoke ORDER BY d LIMIT 5;
```

## Source URLs (for verification)

* pgvector GitHub: https://github.com/pgvector/pgvector
* pgvector Docker Hub tags: https://hub.docker.com/r/pgvector/pgvector/tags
* pgvector 0.8.2 release announcement (2026-02-26): https://www.postgresql.org/about/news/pgvector-082-released-3245/
* pgvector CVE-2026-3172 issue: https://github.com/pgvector/pgvector/issues/959
* pgvector indexing and tuning docs: https://github.com/pgvector/pgvector#hnsw
* psycopg3 COPY documentation: https://www.psycopg.org/psycopg3/docs/basic/copy.html
* AWS RDS PG extension version matrix: https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html
* AWS RDS PG release notes (per minor): https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-versions.html
* AWS RDS PG extension management: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Extensions.html
* AWS RDS PG trusted extensions and `rds.allowed_extensions`: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.FeatureSupport.Extensions.html
* AWS announcement, RDS supports pgvector 0.8.0 (Nov 2024): https://aws.amazon.com/about-aws/whats-new/2024/11/amazon-rds-for-postgresql-pgvector-080/
* AWS announcement, RDS supports PG17 (Nov 2024): https://aws.amazon.com/about-aws/whats-new/2024/11/amazon-rds-postgresql-supports-version-17/
* AWS migration best practices: https://aws.amazon.com/blogs/database/best-practices-for-migrating-postgresql-databases-to-amazon-rds-and-amazon-aurora/
