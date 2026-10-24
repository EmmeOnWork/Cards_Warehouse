import hashlib
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Response
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from cards_warehouse import access, backups, ebay, item_pages, pages
from cards_warehouse.database import create_database_engine


# uvicorn calls it with no arguments; the tests pass clocks they control, the backups Velero would list,
# and a client whose requests reach a fake eBay.
def create_app(
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    read_backups: Callable[[], list[dict]] = backups.read_from_velero,
    ebay_http: httpx.Client | None = None,
) -> FastAPI:
    # Baked into the image at build time; "dev" when running outside a built image.
    app_version = os.environ.get("APP_VERSION", "dev")
    # From Infisical, through the operator and the pod's environment.
    session_secret = os.environ["SESSION_SECRET"]
    password_hash = os.environ["PASSWORD_HASH"]
    engine = create_database_engine()
    app = FastAPI(title="Cards Warehouse", version=app_version)
    # For the pages, which each open their own connection or transaction.
    app.state.engine = engine

    @app.get("/livez")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readiness(response: Response) -> dict[str, str]:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except OperationalError:
            response.status_code = 503
            return {"status": "database unreachable"}
        return {"status": "ok"}

    @app.get("/version")
    def version() -> dict[str, str]:
        return {"version": app_version}

    # Tells which key the app runs with, so a rotation can be checked, without revealing it:
    # the key is random, and a hash of it cannot be turned back into it.
    @app.get("/session-key")
    def session_key() -> dict[str, str]:
        return {"fingerprint": hashlib.sha256(session_secret.encode()).hexdigest()[:16]}

    # Read at every visit of the home page: a backup that just finished shows at once.
    app.state.backup_outcome = lambda: backups.last_outcome(read_backups, now())
    # A slow eBay delays the eBay page by 10 s at most.
    ebay_account = ebay.account_from_environment(ebay_http or httpx.Client(timeout=10), clock)
    app.state.ebay_status = lambda: ebay.status(ebay_account)
    app.include_router(pages.router)
    app.include_router(item_pages.router)
    access.protect(
        app,
        password_hash=password_hash,
        session_secret=session_secret,
        public_paths={"/livez", "/readyz", "/version", "/session-key"},
        clock=clock,
    )
    return app
