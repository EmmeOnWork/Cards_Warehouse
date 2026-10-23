"""The connection to PostgreSQL, the same for the app and for the migrations."""

from sqlalchemy import Engine, MetaData, create_engine

# The tables as the code reads and writes them, each declared by the module that owns it, with only the
# columns the code uses. Their whole structure, and its history, is in migrations/.
metadata = MetaData()


def create_database_engine() -> Engine:
    # No address in the code: libpq reads PGHOST, PGPORT, PGUSER, PGPASSWORD and PGDATABASE from the environment,
    # set by the chart in the cluster and by the fixtures in the tests.
    return create_engine(
        "postgresql+psycopg://",
        # A database that does not answer fails a request within 2 s, instead of holding it for minutes.
        connect_args={"connect_timeout": 2},
        # After PostgreSQL restarts, the pooled connections are dead: each one is checked before use.
        pool_pre_ping=True,
    )
