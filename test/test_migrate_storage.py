import unittest
from typing import Any

from scripts import migrate_storage


class FakeStorage:
    def __init__(self, accounts: list[dict[str, Any]]) -> None:
        self.accounts = [dict(item) for item in accounts]

    def load_accounts(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.accounts]

    def save_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.accounts = [dict(item) for item in accounts]

    def load_auth_keys(self) -> list[dict[str, Any]]:
        return []

    def save_auth_keys(self, auth_keys: list[dict[str, Any]]) -> None:
        pass

    def health_check(self) -> dict[str, Any]:
        return {"status": "healthy"}

    def get_backend_info(self) -> dict[str, Any]:
        return {"type": "fake"}


class MigrateStorageTests(unittest.TestCase):
    def test_migration_refuses_to_replace_nonempty_target_by_default(self) -> None:
        source = FakeStorage([{"access_token": "source-token"}])
        target = FakeStorage([{"access_token": "target-token"}])
        old_create_backend = migrate_storage._create_backend
        try:
            migrate_storage._create_backend = lambda backend, database_url=None: source if backend == "json" else target

            with self.assertRaisesRegex(RuntimeError, "already has 1 accounts"):
                migrate_storage.migrate_data("json", "postgres")
        finally:
            migrate_storage._create_backend = old_create_backend


if __name__ == "__main__":
    unittest.main()
