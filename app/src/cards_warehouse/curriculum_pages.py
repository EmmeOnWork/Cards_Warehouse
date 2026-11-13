"""The page of the numbers of the curriculum: what the app handled in a period, each number with how it is counted,
for Manuel to write them in his curriculum and record them in the repository."""

import json

from fastapi import APIRouter, Request, Response

from cards_warehouse import curriculum
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.pages import templates

# The days of a period are read as on the reports page, with its refusals.
from cards_warehouse.report_pages import _days, _Refused

# Each number, by its field: its name, and how it is counted. The one text for the page and for the file.
NUMBERS = {
    "items": (
        "Articoli gestiti",
        "Gli articoli con almeno una copia in magazzino in qualche momento del periodo: c'erano già il primo giorno, "
        "oppure nel periodo sono stati caricati, venduti, aperti o rettificati. Un bulk conta come un articolo.",
    ),
    "sales": (
        "Vendite",
        "Le vendite del periodo, per giorno di vendita, una per ordine anche se di più copie. Non contano le vendite "
        "annullate né le doppie vendite: di un ordine in parte doppio conta la parte delle copie che c'erano.",
    ),
    "channels": (
        "Canali con almeno una vendita",
        "I canali con almeno una delle vendite contate, nell'ordine in cui sono stati aggiunti.",
    ),
    "through_api": (
        "Canali sincronizzati via API",
        "Tra i canali con una vendita, quelli con almeno una vendita del periodo che l'app ha letto dall'API del "
        "canale e registrato da sola.",
    ),
    "doubles": (
        "Doppie vendite",
        "Gli ordini arrivati su copie già vendute altrove, per giorno della vendita: registrati come doppia vendita, o "
        "annullati con questa causa. Ogni ordine conta una volta, anche se poi è stato annullato.",
    ),
}

router = APIRouter()


@router.get("/reports/numbers")
def numbers_page(request: Request, first_day: str = "", last_day: str = ""):
    today = request.app.state.now().astimezone(LOCAL_TIME).date()
    numbers, error = None, ""
    with request.app.state.engine.connect() as connection:
        if first_day or last_day:
            try:
                numbers = curriculum.numbers(connection, *_days(first_day, last_day))
            except _Refused as refusal:
                error = str(refusal)
        else:
            # From the first day of use to today, unless Manuel chose another period.
            numbers = curriculum.numbers(connection, curriculum.first_day(connection) or today, today)
            first_day, last_day = f"{numbers.first_day}", f"{numbers.last_day}"
    return templates.TemplateResponse(
        request,
        "curriculum.html",
        {
            "numbers": numbers,
            "described": NUMBERS,
            "form": {"first_day": first_day, "last_day": last_day},
            "error": error,
        },
        status_code=422 if error else 200,
    )


@router.get("/reports/numbers.json")
def numbers_file(request: Request, first_day: str = "", last_day: str = ""):
    """The numbers of the period in a file to record in the repository: when they were counted, by which version of the
    app, and how each is counted. Indented, for a diff to read."""
    counted_at = request.app.state.now().astimezone(LOCAL_TIME)
    with request.app.state.engine.connect() as connection:
        numbers = curriculum.numbers(connection, *_days(first_day, last_day))
    recorded = {
        "first_day": f"{numbers.first_day}",
        "last_day": f"{numbers.last_day}",
        "counted_at": counted_at.isoformat(),
        "version": request.app.version,
        **{field: getattr(numbers, field) for field in NUMBERS},
        "how": {field: how for field, (_, how) in NUMBERS.items()},
    }
    return Response(
        json.dumps(recorded, ensure_ascii=False, indent=2) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="numeri-{numbers.first_day}-{numbers.last_day}.json"'},
    )
