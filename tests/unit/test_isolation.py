"""The suite never touches the real data directory: tests that boot the app used to open ~/.daxagent/daxagent.db,
migrate it and close the user's open questions."""

import os
import tempfile
from pathlib import Path

from src.configs.settings import settings
from src.database import connection


def test_the_suite_does_not_resolve_the_real_database():
    real = Path.home().resolve() / ".daxagent"
    db = Path(connection._get_db_path()).resolve()
    assert db != real / "daxagent.db" and real not in db.parents
    assert Path(settings.ROOT_DIR).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
    assert os.environ["DAXAGENT_DATA_DIR"] == settings.ROOT_DIR
