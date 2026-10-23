"""Single-user access: one password opens a session, and without it nothing but the public paths answers."""

import math
from collections.abc import Callable, Iterable
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from cards_warehouse.pages import templates
from cards_warehouse.password import check_password_hash, verify_password

SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


def protect(
    app: FastAPI,
    *,
    password_hash: str,
    session_secret: str,
    public_paths: Iterable[str],
    clock: Callable[[], float],
) -> None:
    check_password_hash(password_hash)
    public_paths = frozenset(public_paths) | {"/login"}
    lockout = _Lockout(clock)

    @app.get("/login")
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html")

    # Async, so it runs on the event loop one request at a time: a burst of parallel guesses
    # cannot all pass the lock check before the first failures are counted.
    @app.post("/login")
    async def login(request: Request, password: Annotated[str, Form()]):
        if minutes := lockout.minutes_left():
            error = f"Troppi tentativi sbagliati: riprova tra {minutes} min."
            return templates.TemplateResponse(request, "login.html", {"error": error}, status_code=429)
        if not verify_password(password_hash, password):
            lockout.failed()
            return templates.TemplateResponse(request, "login.html", {"error": "Password sbagliata."}, status_code=401)
        lockout.succeeded()
        request.session["signed_in"] = True
        return RedirectResponse("/", status_code=303)

    # A form post, not a link: a browser that prefetches links cannot log you out.
    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # Denied by default: a route added later is behind the session without asking for it.
    @app.middleware("http")
    async def require_session(request: Request, call_next):
        if request.url.path in public_paths or request.session.get("signed_in"):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    # Added last, so it runs first: the session is read before the check above. The session lives in
    # the cookie, signed with the key and its time: changing SESSION_SECRET in Infisical closes them all.
    # Not Secure-only: the PC opens the app over plain HTTP, on its loopback. The phone gets HTTPS from Tailscale
    # (infra/tailscale), inside a tailnet that encrypts everything already.
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        max_age=SESSION_SECONDS,
        same_site="lax",
        https_only=False,
    )


class _Lockout:
    """Counts wrong passwords in a row, for the whole app: there is one user, and one replica.

    In memory: a restart of the pod clears it, which is no help to a guesser.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._failures = 0
        self._locked_until = 0.0

    def minutes_left(self) -> int:
        return math.ceil(max(0.0, self._locked_until - self._clock()) / 60)

    def failed(self) -> None:
        self._failures += 1
        if self._failures == MAX_FAILURES:
            self._failures = 0
            self._locked_until = self._clock() + LOCK_SECONDS

    def succeeded(self) -> None:
        self._failures = 0
