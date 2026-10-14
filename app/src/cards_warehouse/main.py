import os

from fastapi import FastAPI


def create_app() -> FastAPI:
    # Baked into the image at build time; "dev" when running outside a built image.
    app_version = os.environ.get("APP_VERSION", "dev")
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

    return app
