"""Where a test database stands in the history of migrations."""

import psycopg
from alembic.script import ScriptDirectory

from cards_warehouse.migrate import alembic_config
from tests.acceptance.containers import conninfo


def schema_revision(database: dict[str, str]) -> str:
    with psycopg.connect(conninfo(database)) as connection:
        return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


# The last migration of this version of the code.
def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()
