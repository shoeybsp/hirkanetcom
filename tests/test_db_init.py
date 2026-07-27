import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


class DatabaseInitializationTests(unittest.TestCase):
    def test_sqlite_parent_directories_are_created_on_startup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "nested" / "app.db"
            os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

            sys.modules.pop("api.app", None)
            sys.modules.pop("models", None)

            import api.app as app_module

            self.assertTrue(db_path.exists(), "SQLite database file should be created")
            self.assertEqual(
                app_module.app.config["SQLALCHEMY_DATABASE_URI"],
                f"sqlite:////{db_path.as_posix().lstrip('/')}",
            )

    def test_sqlite_url_with_three_slashes_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "app.db"
            os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

            sys.modules.pop("api.app", None)
            sys.modules.pop("models", None)

            import api.app as app_module

            self.assertEqual(
                app_module.app.config["SQLALCHEMY_DATABASE_URI"],
                f"sqlite:////{db_path.as_posix().lstrip('/')}",
            )


if __name__ == "__main__":
    unittest.main()
