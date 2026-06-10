from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread

from fastapi import HTTPException, Request

from services.account_service import account_service
from services.auth_service import auth_service
from services.config import DATA_DIR, config

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"
ACCOUNT_REFRESH_STATUS_FILE = DATA_DIR / "account_refresh_status.json"

_account_refresh_status_lock = Lock()
_DEFAULT_ACCOUNT_REFRESH_STATUS: dict[str, object] = {
    "running": False,
    "last_status": "idle",
    "last_started_at": None,
    "last_finished_at": None,
    "last_duration_ms": None,
    "last_error": None,
    "last_total": 0,
    "last_refreshed": 0,
    "last_error_count": 0,
    "last_relogined": 0,
    "last_keepalive_total": 0,
    "last_keepalive_refreshed": 0,
    "last_keepalive_error_count": 0,
    "interval_seconds": None,
    "next_run_at": None,
}
_account_refresh_status: dict[str, object] = {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _load_account_refresh_status() -> dict[str, object]:
    status = dict(_DEFAULT_ACCOUNT_REFRESH_STATUS)
    try:
        if ACCOUNT_REFRESH_STATUS_FILE.exists():
            loaded = json.loads(ACCOUNT_REFRESH_STATUS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                status.update(loaded)
    except Exception:
        pass
    if bool(status.get("running")):
        status["running"] = False
        status["last_status"] = "interrupted"
        status["last_error"] = status.get("last_error") or "服务重启前刷新未完成"
    return status


def _save_account_refresh_status() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACCOUNT_REFRESH_STATUS_FILE.write_text(
            json.dumps(_account_refresh_status, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _update_account_refresh_status(**updates: object) -> None:
    with _account_refresh_status_lock:
        _account_refresh_status.update(updates)
        _save_account_refresh_status()


def get_account_refresh_status() -> dict[str, object]:
    with _account_refresh_status_lock:
        return dict(_account_refresh_status)


_account_refresh_status.update(_load_account_refresh_status())


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def _legacy_admin_identity(token: str) -> dict[str, object] | None:
    auth_key = str(config.auth_key or "").strip()
    if auth_key and token == auth_key:
        return {"id": "admin", "name": "管理员", "role": "admin"}
    return None


def require_identity(authorization: str | None) -> dict[str, object]:
    token = extract_bearer_token(authorization)
    identity = _legacy_admin_identity(token) or auth_service.authenticate(token)
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "密钥无效或已失效，请重新登录"})
    return identity


def require_auth_key(authorization: str | None) -> None:
    require_identity(authorization)


def require_admin(authorization: str | None) -> dict[str, object]:
    identity = require_identity(authorization)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "需要管理员权限才能执行这个操作"})
    return identity


def resolve_image_base_url(request: Request) -> str:
    return config.base_url or f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


def raise_image_quota_error(exc: Exception) -> None:
    message = str(exc)
    if "no available image quota" in message.lower():
        raise HTTPException(status_code=429, detail={"error": "no available image quota"}) from exc
    raise HTTPException(status_code=502, detail={"error": message}) from exc


def sanitize_cpa_pool(pool: dict | None) -> dict | None:
    if not isinstance(pool, dict):
        return None
    return {key: value for key, value in pool.items() if key != "secret_key"}


def sanitize_cpa_pools(pools: list[dict]) -> list[dict]:
    return [sanitized for pool in pools if (sanitized := sanitize_cpa_pool(pool)) is not None]


def sanitize_sub2api_server(server: dict | None) -> dict | None:
    if not isinstance(server, dict):
        return None
    sanitized = {key: value for key, value in server.items() if key not in {"password", "api_key"}}
    sanitized["has_api_key"] = bool(str(server.get("api_key") or "").strip())
    return sanitized


def sanitize_sub2api_servers(servers: list[dict]) -> list[dict]:
    return [sanitized for server in servers if (sanitized := sanitize_sub2api_server(server)) is not None]


def _account_refresh_interval_seconds() -> int:
    try:
        interval_minutes = int(config.refresh_account_interval_minute)
    except (TypeError, ValueError):
        interval_minutes = 5
    return max(1, interval_minutes) * 60


def start_limited_account_watcher(stop_event: Event) -> Thread:
    """按配置间隔自动刷新全量号池，并顺手维护 refresh_token。"""

    def worker() -> None:
        while not stop_event.is_set():
            interval_seconds = _account_refresh_interval_seconds()
            started_at = _utc_now()
            started_monotonic = time.monotonic()
            tokens: list[str] = []
            keepalive_tokens: list[str] = []
            _update_account_refresh_status(
                running=True,
                last_status="running",
                last_error=None,
                last_started_at=_isoformat(started_at),
                interval_seconds=interval_seconds,
                next_run_at=None,
            )
            try:
                tokens = account_service.list_tokens()
                keepalive_tokens = account_service.list_refresh_token_keepalive_tokens()
                refresh_result: dict[str, object] = {"refreshed": 0, "errors": [], "relogined": 0}
                keepalive_result: dict[str, object] = {"refreshed": 0, "errors": []}
                _update_account_refresh_status(
                    last_total=len(tokens),
                    last_keepalive_total=len(keepalive_tokens),
                )
                if tokens:
                    print(f"[account-watcher] refreshing {len(tokens)} accounts")
                    refresh_result = account_service.refresh_accounts(tokens, defer_invalid_removal=False)
                if keepalive_tokens:
                    print(f"[account-watcher] keepalive {len(keepalive_tokens)} refresh tokens")
                    keepalive_result = account_service.keepalive_refresh_tokens(keepalive_tokens)
                    if keepalive_result.get("errors"):
                        print(f"[account-watcher] keepalive errors: {keepalive_result['errors']}")
                refresh_errors = refresh_result.get("errors") if isinstance(refresh_result.get("errors"), list) else []
                keepalive_errors = keepalive_result.get("errors") if isinstance(keepalive_result.get("errors"), list) else []
                finished_at = _utc_now()
                _update_account_refresh_status(
                    running=False,
                    last_status="partial_error" if refresh_errors or keepalive_errors else "success",
                    last_finished_at=_isoformat(finished_at),
                    last_duration_ms=int((time.monotonic() - started_monotonic) * 1000),
                    last_error=None,
                    last_total=len(tokens),
                    last_refreshed=int(refresh_result.get("refreshed") or 0),
                    last_error_count=len(refresh_errors),
                    last_relogined=int(refresh_result.get("relogined") or 0),
                    last_keepalive_total=len(keepalive_tokens),
                    last_keepalive_refreshed=int(keepalive_result.get("refreshed") or 0),
                    last_keepalive_error_count=len(keepalive_errors),
                    next_run_at=_isoformat(finished_at + timedelta(seconds=interval_seconds)),
                )
            except Exception as exc:
                print(f"[account-watcher] fail {exc}")
                finished_at = _utc_now()
                _update_account_refresh_status(
                    running=False,
                    last_status="error",
                    last_finished_at=_isoformat(finished_at),
                    last_duration_ms=int((time.monotonic() - started_monotonic) * 1000),
                    last_error=str(exc),
                    last_total=len(tokens),
                    last_refreshed=0,
                    last_error_count=0,
                    last_relogined=0,
                    last_keepalive_total=len(keepalive_tokens),
                    last_keepalive_refreshed=0,
                    last_keepalive_error_count=0,
                    next_run_at=_isoformat(finished_at + timedelta(seconds=interval_seconds)),
                )
            stop_event.wait(interval_seconds)

    thread = Thread(target=worker, name="account-watcher", daemon=True)
    thread.start()
    return thread


def resolve_web_asset(requested_path: str) -> Path | None:
    if not WEB_DIST_DIR.exists():
        return None
    clean_path = requested_path.strip("/")
    base_dir = WEB_DIST_DIR.resolve()
    candidates = [base_dir / "index.html"] if not clean_path else [
        base_dir / Path(clean_path),
        base_dir / clean_path / "index.html",
        base_dir / f"{clean_path}.html",
    ]
    for candidate in candidates:
        try:
            candidate.resolve().relative_to(base_dir)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None
