# Migrations

The changes to the structure of the database, in order. `python -m cards_warehouse.migrate` applies the ones the database has not seen yet, and every release runs it before the app starts: see [the chart](../../../../chart/README.md#migrations-at-every-release).

A new migration is a new file in [versions/](versions/), written by hand:

- **Numbered by its revision.** `0002_items.py` holds `revision = "0002"` and, as `down_revision`, the one before it, `"0001"`: one line, no branches. A test in `app/tests` checks the names, and [release.sh](../../../../infra/platform/tests/release.sh) reads the last revision from them.
- **Forward only.** An applied migration is never edited, and never undone with a `git revert`: the reverted code would find in the database a revision it does not know, and its release would stop there. A change, or an undo, is a new migration.
- **Tested on a real PostgreSQL**, the version of the cluster: `make test` migrates an empty database with every file.
