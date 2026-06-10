# gpt2api

ChatGPT2API production account-pool data must be database-first.

## Account Pool Storage Rule

- The source of truth for accounts is the active storage backend selected by `STORAGE_BACKEND`.
- In production, `STORAGE_BACKEND=postgres` with `DATABASE_URL` is the source of truth.
- Account management pages, account APIs, registration target checks, health checks, refresh-all, export, delete, and update flows must read account data through `services.account_service` and the configured storage backend.
- Do not read account-pool state from `config.json`, `register.json`, or any other config file.
- Do not treat `/app/data/accounts.json` as production account state unless `STORAGE_BACKEND=json` is explicitly active.
- `accounts.json` is allowed only for the JSON backend, migrations, imports/exports, and backup snapshots.

## Runtime Cache Rule

- In-memory account maps such as `AccountService._accounts` are runtime caches only.
- Admin/account-management reads must refresh from the storage backend before returning account data.
- Mutations must sync from storage first, apply the change, then persist through the storage backend.
- Never let a stale in-memory cache overwrite newer database rows.

## PR And Upgrade Guard

Any upstream PR, image update, or refactor touching these areas must preserve the database-first behavior:

- `services/account_service.py`
- `api/accounts.py`
- `services/register_service.py`
- `services/register/openai_register.py`
- `services/storage/*`
- Docker compose, deployment, or environment files that set `STORAGE_BACKEND` or `DATABASE_URL`

Before merging or deploying, verify:

- `GET /api/accounts` returns the same count as the active database backend.
- A direct database insert is visible in account management without restarting the service.
- A direct database delete disappears from account management without restarting the service.
- Registration success does not count as success unless the access token is persisted through the storage backend.

Do not accept PRs that move account-pool reads/writes back to config files, `accounts.json`, or startup-only memory snapshots.
