"""A database written by SwiftDrop 1.0.0 opens unchanged and gains the new setting's default."""

import sqlite3
from dataclasses import fields
from pathlib import Path

from swiftdrop import settings as settings_module
from swiftdrop.paths import AppPaths
from swiftdrop.platform import NullPlatform
from swiftdrop.service import AppService

FIXTURE = Path(__file__).parent / "fixtures" / "swiftdrop_1_0_0.sql"


def test_migration_from_1_0_0_db(tmp_path):
    paths = AppPaths(data_dir=tmp_path / "data", logs_dir=tmp_path / "logs", partial_dir=tmp_path / "partial").ensure()
    conn = sqlite3.connect(paths.database)
    conn.executescript(FIXTURE.read_text())
    conn.close()
    service = AppService(paths, NullPlatform())
    try:
        service.start()
        assert service.search_history("", "all", "all", 50, 0)["total"] == 3
        assert {job["id"] for job in service.queue.jobs_public()} == {"job-a", "job-b"}
        current = service.settings.get()
        assert current.connections_per_download == 4
        assert current.max_concurrent == 2 and current.theme == "dark"  # old values survive
        assert set(settings_module._VALIDATORS) == {f.name for f in fields(settings_module.Settings)}
    finally:
        service.shutdown()
