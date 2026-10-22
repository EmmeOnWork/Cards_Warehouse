from pathlib import Path

import psycopg
import pytest
from alembic.script import ScriptDirectory
from alembic.util import CommandError

from cards_warehouse.migrate import alembic_config, migrate
from tests.acceptance.containers import conninfo
from tests.schema import head_revision, schema_revision


def test_migrate_brings_an_empty_database_to_the_last_revision(empty_database):
    migrate()

    assert schema_revision(empty_database) == head_revision()


# A `git revert` of a commit with a migration releases code older than the database. The migration must
# fail, so the release stops and the version already running stays, instead of old code on a newer schema.
def test_migrate_fails_on_a_database_newer_than_the_code(empty_database):
    with psycopg.connect(conninfo(empty_database)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES ('9999')")

    with pytest.raises(CommandError, match="9999"):
        migrate()

    assert schema_revision(empty_database) == "9999"


# infra/platform/tests/release.sh reads the revision of a commit's last migration from the file names.
def test_each_migration_file_starts_with_its_revision():
    for script in ScriptDirectory.from_config(alembic_config()).walk_revisions():
        assert Path(script.path).name.startswith(f"{script.revision}_")
