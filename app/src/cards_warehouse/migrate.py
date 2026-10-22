"""Brings the database to the last migration: `python -m cards_warehouse.migrate`, run by each release first."""

import logging

from alembic import command
from alembic.config import Config


def alembic_config() -> Config:
    config = Config()
    # Inside the package, so the image carries the migrations without the sources.
    config.set_main_option("script_location", "cards_warehouse:migrations")
    return config


def migrate() -> None:
    command.upgrade(alembic_config(), "head")


if __name__ == "__main__":
    # Alembic names each migration it applies: the init container's log tells what a release changed.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    migrate()
