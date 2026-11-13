"""The reports page: the margin of each month against the target, for Manuel to tell whether he keeps to his rule, and
the capital idle in the warehouse. And the sales of a period in a file, for the accountant or for Excel."""

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from cards_warehouse import channels, partners, pricing, reports
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.money import format_euros, format_percent
from cards_warehouse.pages import templates
from cards_warehouse.pricing import MarginWarning
from cards_warehouse.purchases import MANUEL

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


@router.get("/reports/sales.csv")
def sales_file(request: Request, first_day: str = "", last_day: str = ""):
    """The sales of the period, one a line, as Excel set for Italy opens them with a double click: a BOM for the
    accents, the columns split by a semicolon, the amounts in euros with a decimal comma."""
    try:
        first, last = _days(first_day, last_day)
    except _Refused as refusal:
        return PlainTextResponse(str(refusal), status_code=422)
    with request.app.state.engine.connect() as connection:
        sold = reports.sold(connection, first, last)
        people = [MANUEL, *(partner.name for partner in partners.every(connection))]
    lines = io.StringIO()
    writer = csv.writer(lines, delimiter=";")
    writer.writerow(
        [
            "Data",
            "Articolo",
            "Canale",
            "Quantità",
            "Prezzo",
            "Commissione",
            "Spedizione",
            "Costo",
            "Margine €",
            "Margine %",
            "Ha incassato",
            *(f"Parte {person}" for person in people),
        ]
    )
    for sale in sold:
        parts = dict(sale.parts.parts)
        writer.writerow(
            [
                f"{sale.at.astimezone(LOCAL_TIME):%d/%m/%Y}",
                sale.item,
                sale.channel,
                sale.quantity,
                format_euros(sale.price_cents),
                format_euros(sale.fee_cents),
                format_euros(sale.shipping_cents),
                _euros(sale.cost_cents),
                _euros(sale.margin and sale.margin.cents),
                "" if sale.margin is None else format_percent(sale.margin.percent),
                sale.parts.collected_by,
                *(_euros(parts.get(person)) for person in people),
            ]
        )
    return Response(
        "\N{BYTE ORDER MARK}" + lines.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="vendite-{first}-{last}.csv"'},
    )


@router.get("/sales")
def sales_page(request: Request, first_day: str = "", last_day: str = "", channel: str = ""):
    """The sales of a period one by one, with its totals: of the days and the channel chosen, or else of this month on
    every channel."""
    today = request.app.state.now().astimezone(LOCAL_TIME).date()
    days, error = reports.month_of(today), ""
    if first_day or last_day:
        try:
            days = _days(first_day, last_day)
        except _Refused as refusal:
            # The days come back as typed, for Manuel to fix the one he got wrong.
            days, error = (first_day, last_day), str(refusal)
    channel_id = int(channel) if channel.isdigit() else None
    with request.app.state.engine.connect() as connection:
        history = None if error else reports.history(connection, *days, channel_id)
        every = channels.every(connection)
    first, last = days
    # The periods Manuel looks at most, a tap away, on the channel he chose.
    shortcuts = {
        "Questo mese": reports.month_of(today),
        "Mese scorso": reports.month_of(today.replace(day=1) - timedelta(days=1)),
        "Quest'anno": (today.replace(month=1, day=1), today.replace(month=12, day=31)),
    }
    return templates.TemplateResponse(
        request,
        "sales.html",
        {
            "history": history,
            "channels": every,
            "shortcuts": shortcuts,
            "form": {"first_day": f"{first}", "last_day": f"{last}", "channel": "" if channel_id is None else channel},
            "error": error,
        },
        status_code=422 if error else 200,
    )


def _euros(cents: int | None) -> str:
    """An amount in a cell of the file: empty when not known, or not there, which Excel sums as nothing."""
    return "" if cents is None else format_euros(cents)


def _days(first_day: str, last_day: str) -> tuple[date, date]:
    try:
        first, last = date.fromisoformat(first_day.strip()), date.fromisoformat(last_day.strip())
    except ValueError:
        raise _Refused("Scegli il primo giorno e l'ultimo.") from None
    if first > last:
        raise _Refused("Il primo giorno viene dopo l'ultimo.")
    return first, last
