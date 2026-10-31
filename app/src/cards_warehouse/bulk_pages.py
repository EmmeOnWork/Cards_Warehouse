"""The page of the capital idle in the bulk: each bulk with cards, what they cost and for how many days its oldest lot
has stood, for Manuel to tell when it is worth selling it off."""

from fastapi import APIRouter, Request

from cards_warehouse import bulk
from cards_warehouse.backups import LOCAL_TIME
from cards_warehouse.pages import templates

router = APIRouter()


@router.get("/bulk")
def idle_page(request: Request):
    with request.app.state.engine.connect() as connection:
        idle = bulk.idle(connection)
    # In days of Italy: a lot that came in yesterday evening stands since yesterday.
    today = request.app.state.now().astimezone(LOCAL_TIME).date()
    standing = [(each, (today - each.since.astimezone(LOCAL_TIME).date()).days) for each in idle]
    return templates.TemplateResponse(request, "bulk.html", {"standing": standing})
