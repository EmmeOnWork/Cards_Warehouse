"""The page of the daily check: what the last one found, and when, with the check run by hand from there and the
thresholds it judges by."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import daily_check
from cards_warehouse.daily_check import Thresholds
from cards_warehouse.pages import templates

router = APIRouter()


class ThresholdsForm(BaseModel):
    """The thresholds as typed: they go back into the page when one must be fixed."""

    stale_action_days: str = ""
    unsold_item_days: str = ""


@router.get("/check")
def check_page(request: Request):
    return _page(request)


# The same check the CronJob runs, at once: after fixing what it found, Manuel sees it gone.
@router.post("/check")
def check_now(request: Request):
    with request.app.state.engine.begin() as connection:
        daily_check.run(connection, request.app.state.now())
    return RedirectResponse("/check", status_code=303)


@router.post("/check/thresholds")
def change_thresholds(request: Request, form: Annotated[ThresholdsForm, Form()]):
    try:
        days = Thresholds(_days(form.stale_action_days), _days(form.unsold_item_days))
    except ValueError:
        return _page(request, form, error="Le soglie sono giorni interi, almeno 1.", status_code=422)
    with request.app.state.engine.begin() as connection:
        daily_check.change_thresholds(connection, days)
    return RedirectResponse("/check", status_code=303)


def _days(text: str) -> int:
    days = int(text)
    if days < 1:
        raise ValueError(f"a threshold is at least a day, not {days}")
    return days


def _page(request: Request, typed: ThresholdsForm | None = None, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        outcome = daily_check.last(connection)
        if typed is None:
            in_force = daily_check.thresholds(connection)
            typed = ThresholdsForm(
                stale_action_days=str(in_force.stale_action_days), unsold_item_days=str(in_force.unsold_item_days)
            )
    freshness = daily_check.freshness(outcome, request.app.state.now())
    return templates.TemplateResponse(
        request,
        "daily_check.html",
        {"outcome": outcome, "freshness": freshness, "thresholds": typed, "error": error},
        status_code=status_code,
    )
