import hashlib
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Response
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from cards_warehouse import (
    access,
    backups,
    channel_pages,
    ebay,
    grading_pages,
    item_pages,
    listing_pages,
    listing_text_pages,
    live_pages,
    movement_pages,
    opening_pages,
    pages,
    photo_pages,
    photos,
    price_pages,
    purchase_pages,
)
from cards_warehouse.database import create_database_engine
from cards_warehouse.password import StoredPassword


# uvicorn calls it with no arguments; the tests pass clocks they control, the backups Velero would list,
# a client whose requests reach a fake eBay, and a photos bucket in memory.
def create_app(
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    read_backups: Callable[[], list[dict]] = backups.read_from_velero,
    ebay_http: httpx.Client | None = None,
    photo_store: photos.Store | None = None,
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
    # The private bucket of the foundations, with the scoped key from Infisical. Nothing is asked to AWS here.
    app.state.photos = photo_store or photos.S3Store.from_environment()
    app.include_router(pages.router)
    app.include_router(item_pages.router)
    app.include_router(channel_pages.router)
    app.include_router(photo_pages.router)
    app.include_router(movement_pages.router)
    app.include_router(listing_text_pages.router)
    app.include_router(price_pages.router)
    app.include_router(opening_pages.router)
    app.include_router(grading_pages.router)
    app.include_router(purchase_pages.router)
    app.include_router(live_pages.router)
    app.include_router(listing_pages.router)
    access.protect(
        app,
        stored_password=StoredPassword(engine, infisical_hash=password_hash),
        session_secret=session_secret,
        public_paths={"/livez", "/readyz", "/version", "/session-key"},
        clock=clock,
    )
    return app
