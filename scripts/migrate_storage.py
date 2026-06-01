#!/usr/bin/env python3
"""
存储后端数据迁移脚本

用法：
  python scripts/migrate_storage.py --from json --to postgres --to-url postgresql://...
  python scripts/migrate_storage.py --from sqlite --from-url sqlite:////app/data/accounts.db --to postgres --to-url postgresql://...
  python scripts/migrate_storage.py --from postgres --from-url postgresql://... --to git
  python scripts/migrate_storage.py --export accounts.json
  python scripts/migrate_storage.py --import accounts.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

from services.storage.factory import create_storage_backend


_DATABASE_URL_UNSET = object()


def _with_storage_env(backend: str, database_url: object = _DATABASE_URL_UNSET):
    class StorageEnv:
        def __enter__(self):
            self.original_backend = os.environ.get("STORAGE_BACKEND")
            self.original_database_url = os.environ.get("DATABASE_URL")
            os.environ["STORAGE_BACKEND"] = backend
            if database_url is not _DATABASE_URL_UNSET:
                os.environ["DATABASE_URL"] = database_url
            return self

        def __exit__(self, exc_type, exc, tb):
            if self.original_backend is None:
                os.environ.pop("STORAGE_BACKEND", None)
            else:
                os.environ["STORAGE_BACKEND"] = self.original_backend
            if self.original_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = self.original_database_url

    return StorageEnv()


def _create_backend(backend: str, database_url: str | None = None):
    url = database_url if database_url is not None else _DATABASE_URL_UNSET
    with _with_storage_env(backend, url):
        return create_storage_backend(DATA_DIR)


def export_to_json(output_file: str):
    """导出当前存储后端的数据到 JSON 文件"""
    print(f"[migrate] Exporting data to {output_file}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage = create_storage_backend(DATA_DIR)
    accounts = storage.load_accounts()
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(accounts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    
    print(f"[migrate] Exported {len(accounts)} accounts to {output_file}")


def import_from_json(input_file: str):
    """从 JSON 文件导入数据到当前存储后端"""
    print(f"[migrate] Importing data from {input_file}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"[migrate] Error: File not found: {input_file}")
        sys.exit(1)
    
    try:
        accounts = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(accounts, list):
            print(f"[migrate] Error: Invalid JSON format, expected array")
            sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"[migrate] Error: Invalid JSON: {e}")
        sys.exit(1)
    
    storage = create_storage_backend(DATA_DIR)
    storage.save_accounts(accounts)
    
    print(f"[migrate] Imported {len(accounts)} accounts")


def migrate_data(
    from_backend: str,
    to_backend: str,
    from_url: str | None = None,
    to_url: str | None = None,
    include_auth_keys: bool = False,
):
    """从一个存储后端迁移到另一个"""
    print(f"[migrate] Migrating from {from_backend} to {to_backend}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    from_storage = _create_backend(from_backend, from_url)
    accounts = from_storage.load_accounts()
    auth_keys = from_storage.load_auth_keys() if include_auth_keys else []
    print(f"[migrate] Loaded {len(accounts)} accounts from {from_backend}")
    if include_auth_keys:
        print(f"[migrate] Loaded {len(auth_keys)} auth keys from {from_backend}")

    to_storage = _create_backend(to_backend, to_url)
    to_storage.save_accounts(accounts)
    print(f"[migrate] Saved {len(accounts)} accounts to {to_backend}")
    if include_auth_keys:
        to_storage.save_auth_keys(auth_keys)
        print(f"[migrate] Saved {len(auth_keys)} auth keys to {to_backend}")

    print("[migrate] Migration completed successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="ChatGPT2API 存储后端数据迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从 JSON 迁移到 PostgreSQL
  python scripts/migrate_storage.py --from json --to postgres --to-url postgresql://user:password@host:5432/chatgpt2api

  # 从 SQLite 迁移到 PostgreSQL
  python scripts/migrate_storage.py --from sqlite --from-url sqlite:////app/data/accounts.db --to postgres --to-url postgresql://user:password@host:5432/chatgpt2api --include-auth-keys
  
  # 从 PostgreSQL 迁移到 Git
  python scripts/migrate_storage.py --from postgres --from-url postgresql://user:password@host:5432/chatgpt2api --to git
  
  # 导出当前数据到 JSON 文件
  python scripts/migrate_storage.py --export backup.json
  
  # 从 JSON 文件导入数据
  python scripts/migrate_storage.py --import backup.json

环境变量:
  STORAGE_BACKEND  - 存储后端类型 (json, sqlite, postgres, git)
  DATABASE_URL     - 数据库连接字符串
  GIT_REPO_URL     - Git 仓库地址
  GIT_TOKEN        - Git 访问令牌
        """
    )
    
    parser.add_argument(
        "--from",
        dest="from_backend",
        choices=["json", "sqlite", "postgres", "git"],
        help="源存储后端",
    )
    parser.add_argument(
        "--to",
        dest="to_backend",
        choices=["json", "sqlite", "postgres", "git"],
        help="目标存储后端",
    )
    parser.add_argument(
        "--from-url",
        dest="from_url",
        help="源数据库连接字符串；迁移 sqlite/postgres 时建议显式指定",
    )
    parser.add_argument(
        "--to-url",
        dest="to_url",
        help="目标数据库连接字符串；迁移到 postgres/sqlite 时建议显式指定",
    )
    parser.add_argument(
        "--include-auth-keys",
        action="store_true",
        help="同时迁移 auth_keys",
    )
    parser.add_argument(
        "--export",
        dest="export_file",
        metavar="FILE",
        help="导出数据到 JSON 文件",
    )
    parser.add_argument(
        "--import",
        dest="import_file",
        metavar="FILE",
        help="从 JSON 文件导入数据",
    )
    
    args = parser.parse_args()
    
    # 检查参数
    if args.from_backend and args.to_backend:
        migrate_data(
            args.from_backend,
            args.to_backend,
            from_url=args.from_url,
            to_url=args.to_url,
            include_auth_keys=args.include_auth_keys,
        )
    elif args.export_file:
        export_to_json(args.export_file)
    elif args.import_file:
        import_from_json(args.import_file)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
