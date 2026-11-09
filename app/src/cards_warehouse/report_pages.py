"""The reports page: the margin of each month against the target, for Manuel to tell whether he keeps to his rule, and
the capital idle in the warehouse."""

from datetime import date

from fastapi import APIRouter, Request

from cards_warehouse import channels, pricing, reports
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.pages import templates
from cards_warehouse.pricing import MarginWarning

MONTHS = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
templates.env.filters["month"] = lambda day: f"{MONTHS[day.month - 1]} {day.year}"
templates.env.filters["days"] = lambda period: f"{period.first_day:%d/%m/%Y} – {period.last_day:%d/%m/%Y}"

router = APIRouter()


class _Refused(Exception):
    """The days typed make no period: the message tells Manuel why."""


@router.get("/reports")
def reports_page(request: Request, first_day: str = "", last_day: str = ""):
    # Another period, when Manuel chose one.
    days, error = None, ""
    if first_day or last_day:
        try:
            days = _days(first_day, last_day)
        except _Refused as refusal:
            error = str(refusal)
    # The months of Italy: a sale of the night of the first is of the new month.
    today = request.app.state.now().astimezone(LOCAL_TIME).date()
    with request.app.state.engine.connect() as connection:
        months = reports.monthly_margins(connection, today)
        period = days and reports.margin(connection, *days)
        target = channels.target_margin(connection)
        capital = reports.capital(connection)

    # Against the target of today: the app does not keep the ones before.
    def warned(period: reports.PeriodMargin) -> tuple[reports.PeriodMargin, MarginWarning | None]:
        return period, period.margin and pricing.warning(period.margin, target)

    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "months": [warned(month) for month in months],
            "target": target,
            "period": period and warned(period),
            "form": {"first_day": first_day, "last_day": last_day},
            "error": error,
            "capital": capital,
        },
        status_code=422 if error else 200,
    )


def _days(first_day: str, last_day: str) -> tuple[date, date]:
    try:
        first, last = date.fromisoformat(first_day.strip()), date.fromisoformat(last_day.strip())
    except ValueError:
        raise _Refused("Scegli il primo giorno e l'ultimo.") from None
    if first > last:
        raise _Refused("Il primo giorno viene dopo l'ultimo.")
    return first, last
