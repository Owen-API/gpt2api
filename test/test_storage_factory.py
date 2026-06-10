from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from services.storage.factory import create_storage_backend


class StorageFactoryTests(unittest.TestCase):
    def test_postgres_backend_requires_database_url(self) -> None:
        old_backend = os.environ.get("STORAGE_BACKEND")
        old_database_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["STORAGE_BACKEND"] = "postgres"
            os.environ.pop("DATABASE_URL", None)

            with tempfile.TemporaryDirectory() as tmp_dir:
                with self.assertRaisesRegex(ValueError, "DATABASE_URL is required"):
                    create_storage_backend(Path(tmp_dir))
        finally:
            if old_backend is None:
                os.environ.pop("STORAGE_BACKEND", None)
            else:
                os.environ["STORAGE_BACKEND"] = old_backend
            if old_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old_database_url


if __name__ == "__main__":
    unittest.main()
