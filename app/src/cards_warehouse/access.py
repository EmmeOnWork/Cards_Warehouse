"""Single-user access: one password opens a session, and without it nothing but the public paths answers."""

import math
from collections.abc import Callable, Iterable
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from cards_warehouse.pages import templates
from cards_warehouse.password import StoredPassword

SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
# NIST's floor for a password the user chooses. templates/password.html asks the same.
MIN_PASSWORD_LENGTH = 8


def protect(
    app: FastAPI,
    *,
    stored_password: StoredPassword,
    session_secret: str,
    public_paths: Iterable[str],
    clock: Callable[[], float],
) -> None:
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
        if not stored_password.verify(password):
            lockout.failed()
            return templates.TemplateResponse(request, "login.html", {"error": "Password sbagliata."}, status_code=401)
        lockout.succeeded()
        request.session["signed_in"] = True
        return RedirectResponse("/", status_code=303)

    @app.get("/password")
    def password_page(request: Request):
        return templates.TemplateResponse(request, "password.html")

    # Async for the same reason as the login. A wrong current password counts as a wrong login:
    # this page is no way round the lock to guess it.
    @app.post("/password")
    async def change_password(
        request: Request,
        current: Annotated[str, Form()],
        new: Annotated[str, Form()],
        again: Annotated[str, Form()],
    ):
        if minutes := lockout.minutes_left():
            return _password_page(request, f"Troppi tentativi sbagliati: riprova tra {minutes} min.", 429)
        if not stored_password.verify(current):
            lockout.failed()
            return _password_page(request, "La password attuale è sbagliata.", 401)
        lockout.succeeded()
        if new != again:
            return _password_page(request, "Le due password nuove sono diverse.", 422)
        if len(new) < MIN_PASSWORD_LENGTH:
            return _password_page(request, f"La nuova password ha almeno {MIN_PASSWORD_LENGTH} caratteri.", 422)
        stored_password.change(new)
        done = "Password cambiata: da ora si entra con quella nuova."
        return templates.TemplateResponse(request, "password.html", {"done": done})

    def _password_page(request: Request, error: str, status_code: int):
        return templates.TemplateResponse(request, "password.html", {"error": error}, status_code=status_code)

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
