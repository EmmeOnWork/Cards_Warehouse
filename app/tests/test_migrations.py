from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory
from alembic.util import CommandError

from cards_warehouse import purchases, stock
from cards_warehouse.database import create_database_engine
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


# The lots in the cluster when purchases arrived, with their cost typed by hand: their copies are still there,
# and they are all Manuel's.
def test_a_lot_loaded_before_purchases_existed_still_works_and_is_all_manuels(empty_database):
    command.upgrade(alembic_config(), "0006")
    with psycopg.connect(conninfo(empty_database)) as connection:
        item_id = connection.execute(
            "INSERT INTO items (kind, game_id, name, language) VALUES ('sealed', 1, 'Booster box', 'it') RETURNING id"
        ).fetchone()[0]
        lot_id = connection.execute(
            "INSERT INTO stock_lots (item_id, unit_cost_cents) VALUES (%s, 8990) RETURNING id", (item_id,)
        ).fetchone()[0]
        connection.execute("INSERT INTO stock_movements (lot_id, change, cause) VALUES (%s, 5, 'load')", (lot_id,))

    migrate()

    with create_database_engine().connect() as connection:
        assert stock.available(connection, item_id) == 5
        assert purchases.shares_of_lot(connection, lot_id) == {None: 100}


# infra/platform/tests/release.sh reads the revision of a commit's last migration from the file names.
def test_each_migration_file_starts_with_its_revision():
    for script in ScriptDirectory.from_config(alembic_config()).walk_revisions():
        assert Path(script.path).name.startswith(f"{script.revision}_")
