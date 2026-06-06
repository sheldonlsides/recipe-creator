# pgvector backend — local setup

This directory stands up **PostgreSQL 17 + pgvector** in Docker Desktop — the
nutrition vector store for the project (~327K OpenNutrition foods,
`all-MiniLM-L6-v2`, 384-dim).

Only the **database** runs in a container. The notebook runs on your **host**
(via `uv run`) and connects to the DB at `localhost:5433`. The backend code lives
in `src/vectorstore/` and uses the `langchain-postgres` v2 API
(`PGVectorStore` + `PGEngine`).

> **Why port 5433?** The container publishes to host port **5433**, not the
> Postgres default 5432, so it coexists with any host-native Postgres you may
> already run on 5432. Inside the container Postgres still listens on 5432.

> For tuning rationale, the binary-`COPY` fast loader, and the AWS RDS production
> path, see [`../docs/pgvector-setup.md`](../docs/pgvector-setup.md).

---

## Prerequisites

- **Docker Desktop** running, with at least **4 CPU / 8 GB RAM** allocated
  (Settings → Resources). The HNSW index build is the most demanding step.
- **Port 5432 free** on the host (see [Troubleshooting](#troubleshooting) if not).
- **`uv`** installed (the project package manager).
- The source dataset **`src/data/opennutrition_foods.tsv`** present (~269 MB).
  It is gitignored (too large for GitHub), so a fresh clone won't have it —
  obtain it from the OpenNutrition dataset source and place it at that path.
- A Postgres client is handy for verification: the bundled `psql` (via
  `docker exec`), or an external client like DBeaver / TablePlus / pgAdmin.

---

## 1. Start the database

From the **repo root**:

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Watch it become ready (Ctrl-C to stop watching — the container keeps running):

```bash
docker compose -f deploy/docker-compose.yml logs -f db
```

It's ready when you see `database system is ready to accept connections` and the
healthcheck reports healthy (`docker ps` shows `(healthy)`).

---

## 2. Verify pgvector

```bash
# Extension is installed and at the expected version (expect: vector | 0.8.2)
docker exec -it recipe-pgvector psql -U dev -d appdb -c "\dx"
docker exec -it recipe-pgvector psql -U dev -d appdb \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Optional smoke test of the vector type and distance operator:

```bash
docker exec -it recipe-pgvector psql -U dev -d appdb <<'SQL'
CREATE TABLE IF NOT EXISTS _smoke (id bigserial PRIMARY KEY, e vector(3));
INSERT INTO _smoke (e) VALUES ('[1,2,3]'), ('[4,5,6]'), ('[1,1,1]');
SELECT id, e <-> '[3,1,2]' AS l2_distance FROM _smoke ORDER BY e <-> '[3,1,2]' LIMIT 5;
DROP TABLE _smoke;
SQL
```

(Distance operators: `<->` L2, `<=>` cosine, `<#>` negative inner product. The app
uses cosine, matching the L2-normalized MiniLM embeddings.)

---

## 3. Point the app at the database

In your project **`.env`**, set:

```ini
DATABASE_URL=postgresql+psycopg://dev:devpass@localhost:5433/appdb
```

- `DATABASE_URL` is required — it's the only thing pointing the app at the store.
- `localhost:5433` is correct because the notebook runs on the host and reaches
  the container through the published port (**not** the compose service name `db`,
  which would only apply from inside another container on the same network).
- `postgresql+psycopg://` selects the psycopg3 driver that `langchain-postgres`
  requires.

---

## 4. Build the index (one-time)

Run the notebook headless from the repo root:

```bash
uv run --with nbconvert -- jupyter nbconvert --to notebook --execute src/recipe_builder.ipynb
```

On the **first** run the notebook embeds all ~327K foods on CPU and loads them
into Postgres in batches (this takes **many minutes** — the embedding compute, not
the database, is the bottleneck), then builds an HNSW cosine index. Progress is
logged as `embedded X/total ...`.

Subsequent runs detect the populated table and **load instantly** — no
re-embedding.

---

## 5. Confirm the load

```bash
docker exec -it recipe-pgvector psql -U dev -d appdb \
  -c "SELECT count(*) FROM opennutrition_foods;"
```

The count should equal `MAX_ROWS` from the notebook config (full dataset:
**326,759**). You can also confirm the HNSW index exists:

```bash
docker exec -it recipe-pgvector psql -U dev -d appdb \
  -c "\di opennutrition_foods*"
```

---

## Common operations

```bash
# Stop the DB but KEEP the data (named volume persists)
docker compose -f deploy/docker-compose.yml down

# Stop and DELETE all data (drops the volume — you'll have to rebuild the index)
docker compose -f deploy/docker-compose.yml down -v

# Update to a newer pgvector image, then bump the extension inside the DB
docker compose -f deploy/docker-compose.yml pull
docker compose -f deploy/docker-compose.yml up -d
docker exec -it recipe-pgvector psql -U dev -d appdb -c "ALTER EXTENSION vector UPDATE;"

# Back up the database (custom format)
docker exec -t recipe-pgvector pg_dump -U dev -Fc appdb > appdb.dump
```

---

## Troubleshooting

**Port 5433 already in use** — the compose file already uses 5433 (not 5432) to
dodge a host-native Postgres. If 5433 is also taken, change the host side of the
mapping in `docker-compose.yml` (e.g. `"5434:5432"`) and update `DATABASE_URL` to
the matching port.

**Index build fails / `out of shared memory` or `could not resize shared memory`** —
raise `shm_size` in `docker-compose.yml` (try `'1gb'`) and/or give Docker Desktop
more RAM, then `down` and `up -d` again.

**`count(*)` returns 0 after a restart** — you likely ran `down -v`, which deletes
the volume. Re-run the build (step 4). A plain `down` preserves the data.

**Re-running the build** — re-running the notebook **skips re-embedding** once the
table is populated: a **row-count gate** short-circuits to the instant load path.
Each food keeps its stable OpenNutrition id as a TEXT primary key, so rows stay
traceable. If a **first** build was interrupted partway, the gate treats the
partial table as complete — force a clean rebuild by wiping it:

```bash
# nuke everything (simplest) — then re-run the build
docker compose -f deploy/docker-compose.yml down -v && docker compose -f deploy/docker-compose.yml up -d
# …or drop just the vector table, keeping the container/volume:
docker exec -it recipe-pgvector psql -U dev -d appdb \
  -c "DROP TABLE IF EXISTS opennutrition_foods CASCADE;"
```

**Connecting with an external client** (DBeaver / TablePlus / `psql`):

```
host=localhost  port=5433  user=dev  password=devpass  dbname=appdb
```
or the URL `postgresql://dev:devpass@localhost:5433/appdb`.

**Table name** — `PGVectorStore` stores everything in a single
`opennutrition_foods` table (public schema): content, the `vector(384)` embedding,
and the JSONB `langchain_metadata` column, keyed by a TEXT `langchain_id`.
