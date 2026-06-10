#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

from sqlalchemy import create_engine, text


def _mask_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"


def _api_accounts(api_url: str, auth_key: str, timeout: float) -> list[dict]:
    url = api_url.rstrip("/") + "/api/accounts"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {auth_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed with HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise RuntimeError(f"GET {url} did not return an items list")
    return [item for item in items if isinstance(item, dict)]


def _contains_token(items: list[dict], token: str) -> bool:
    return any(str(item.get("access_token") or "") == token for item in items)


def _insert_sentinel(database_url: str, token: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    data = {
        "access_token": token,
        "type": "sentinel",
        "status": "sentinel",
        "quota": 0,
        "email": "postgres-sentinel@example.invalid",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_type": "postgres-sentinel",
    }
    statement = text(
        """
        INSERT INTO accounts (access_token, data)
        VALUES (:access_token, :data)
        ON CONFLICT (access_token) DO UPDATE SET data = EXCLUDED.data
        """
    )
    with engine.begin() as connection:
        connection.execute(statement, {"access_token": token, "data": json.dumps(data, ensure_ascii=False)})


def _delete_sentinel(database_url: str, token: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM accounts WHERE access_token = :access_token"), {"access_token": token})


def verify(database_url: str, api_url: str, auth_key: str, timeout: float, token: str) -> None:
    if "postgres" not in database_url.lower():
        raise RuntimeError("DATABASE_URL must point to PostgreSQL for this sentinel verification")

    print(f"[sentinel] database={_mask_url(database_url)}")
    print(f"[sentinel] api={api_url.rstrip('/')}")
    print(f"[sentinel] token={token}")

    _delete_sentinel(database_url, token)
    try:
        before = _api_accounts(api_url, auth_key, timeout)
        if _contains_token(before, token):
            raise RuntimeError("sentinel token is visible before direct DB insert")

        _insert_sentinel(database_url, token)
        after_insert = _api_accounts(api_url, auth_key, timeout)
        if not _contains_token(after_insert, token):
            raise RuntimeError("direct DB insert was not visible through /api/accounts")
        print("[sentinel] direct DB insert is visible through /api/accounts")

        _delete_sentinel(database_url, token)
        after_delete = _api_accounts(api_url, auth_key, timeout)
        if _contains_token(after_delete, token):
            raise RuntimeError("direct DB delete is still visible through /api/accounts")
        print("[sentinel] direct DB delete disappeared from /api/accounts")
    finally:
        _delete_sentinel(database_url, token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that account management reads live PostgreSQL rows, not startup memory or accounts.json.",
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""), help="PostgreSQL DATABASE_URL")
    parser.add_argument("--api-url", default=os.getenv("CHATGPT2API_API_URL", "http://127.0.0.1:3000"))
    parser.add_argument("--auth-key", default=os.getenv("CHATGPT2API_AUTH_KEY", ""))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--token", default=f"postgres-sentinel-{uuid4().hex}")
    args = parser.parse_args()

    if not args.database_url:
        print("[sentinel] DATABASE_URL is required", file=sys.stderr)
        return 2
    if not args.auth_key:
        print("[sentinel] CHATGPT2API_AUTH_KEY or --auth-key is required", file=sys.stderr)
        return 2

    try:
        verify(args.database_url, args.api_url, args.auth_key, args.timeout, args.token)
    except Exception as exc:
        print(f"[sentinel] FAILED: {exc}", file=sys.stderr)
        return 1
    print("[sentinel] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
