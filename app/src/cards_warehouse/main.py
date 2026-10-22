import hashlib
import os

from fastapi import FastAPI, Response
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from cards_warehouse.database import create_database_engine


def create_app() -> FastAPI:
    # Baked into the image at build time; "dev" when running outside a built image.
    app_version = os.environ.get("APP_VERSION", "dev")
    # From Infisical, through the operator and the pod's environment.
    session_secret = os.environ["SESSION_SECRET"]
    engine = create_database_engine()
    app = FastAPI(title="Cards Warehouse", version=app_version)

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

    return app
