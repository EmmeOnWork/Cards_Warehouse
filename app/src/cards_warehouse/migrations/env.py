from alembic import context

from cards_warehouse.database import create_database_engine

# One transaction for the whole run: PostgreSQL changes its structure inside transactions too,
# so a migration that fails leaves the database as it was before the release.
with create_database_engine().connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
