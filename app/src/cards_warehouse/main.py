import hashlib
import os

from fastapi import FastAPI


def create_app() -> FastAPI:
    # Baked into the image at build time; "dev" when running outside a built image.
    app_version = os.environ.get("APP_VERSION", "dev")
    # From Infisical, through the operator and the pod's environment.
    session_secret = os.environ["SESSION_SECRET"]
    app = FastAPI(title="Cards Warehouse", version=app_version)

    @app.get("/livez")
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readiness() -> dict[str, str]:
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
