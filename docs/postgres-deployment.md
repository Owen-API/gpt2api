# PostgreSQL deployment

This repo treats PostgreSQL as the production source of truth for the
ChatGPT2API account pool. The app can still read JSON, SQLite, and Git storage,
but production servers should set `STORAGE_BACKEND=postgres`.

## Production environment

Create `.env` on each server:

```bash
CHATGPT2API_AUTH_KEY=change_me
CHATGPT2API_BASE_URL=https://api.example.com
STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://chatgpt2api:change_me@postgres-host:5432/chatgpt2api
```

Do not commit real `.env` files or database passwords.

Start the app:

```bash
docker compose up -d --build
```

The production `docker-compose.yml` builds the local image and requires
`DATABASE_URL`. This keeps AWS, Alibaba Cloud, and future servers on the same
deployment shape.

## Migrating existing SQLite data

Back up the SQLite database first:

```bash
cp data/accounts.db "data/accounts.$(date +%Y%m%d-%H%M%S).db"
```

Run the migration from a shell where dependencies are installed:

```bash
uv run python scripts/migrate_storage.py \
  --from sqlite \
  --from-url sqlite:////app/data/accounts.db \
  --to postgres \
  --to-url "$DATABASE_URL" \
  --include-auth-keys
```

For a host path outside the container, use a matching SQLite URL, for example:

```bash
uv run python scripts/migrate_storage.py \
  --from sqlite \
  --from-url sqlite:////opt/chatgpt2api/data/accounts.db \
  --to postgres \
  --to-url "$DATABASE_URL" \
  --include-auth-keys
```

## Migrating JSON snapshots

```bash
uv run python scripts/migrate_storage.py \
  --from json \
  --to postgres \
  --to-url "$DATABASE_URL"
```

## Verification

Check the storage backend health from the API or logs, then verify account
counts:

```bash
docker compose exec app python - <<'PY'
from services.config import config
storage = config.get_storage_backend()
print(storage.get_backend_info())
print(storage.health_check())
PY
```

Then confirm the service is live:

```bash
curl -sS -H "Authorization: Bearer $CHATGPT2API_AUTH_KEY" \
  http://127.0.0.1:3000/v1/models
```

## Account retention policy

Production account history is preserved. Invalid or banned tokens are marked
`异常` with zero quota. Rate-limited accounts are marked `限流`. Neither path
auto-deletes records from PostgreSQL, even if old config keys such as
`auto_remove_invalid_accounts` or `auto_remove_rate_limited_accounts` are set.
