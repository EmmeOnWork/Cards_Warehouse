"""The pages of the listings: an item put on sale on the channels Manuel chooses, and the actions the manual channels
leave to him, grouped by channel, with what he copies into each channel's app."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import exposure, items, listing_texts, manual_channels, photos
from cards_warehouse.exposure import NoPrice, NothingToSell, Status
from cards_warehouse.manual_channels import ActionKind
from cards_warehouse.pages import templates

# What the pages call the state of a listing, and what an action asks of Manuel.
templates.env.globals["listing_states"] = {Status.TO_PUBLISH: "da pubblicare", Status.ACTIVE: "attivo"}
templates.env.globals["action_kinds"] = {ActionKind.PUBLISH: "Pubblica"}

router = APIRouter()


class PutOnSaleForm(BaseModel):
    channel: list[int] = []


class DoneForm(BaseModel):
    link: str = ""


@router.post("/items/{item_id}/listings")
def put_on_sale(request: Request, item_id: int, form: Annotated[PutOnSaleForm, Form()]):
    try:
        with request.app.state.engine.begin() as connection:
            exposure.put_on_sale(connection, item_id, form.channel, manual_channels.MANUAL)
    except NothingToSell:
        reason = "Non ci sono copie disponibili da mettere in vendita."
    except NoPrice:
        reason = "Il costo è sconosciuto e non c'è un prezzo fissato: fissa il prezzo, poi mettilo in vendita."
    else:
        return RedirectResponse(f"/items/{item_id}", status_code=303)
    return templates.TemplateResponse(
        request, "listing_refused.html", {"reason": reason, "item_id": item_id}, status_code=422
    )


@router.get("/actions")
def action_list(request: Request):
    with request.app.state.engine.connect() as connection:
        by_channel = manual_channels.pending(connection)
        names = {
            action.listing.item_id: items.get(connection, action.listing.item_id).name
            for actions in by_channel.values()
            for action in actions
        }
    return templates.TemplateResponse(request, "actions.html", {"by_channel": by_channel, "names": names})


@router.get("/actions/{action_id}")
def action_page(request: Request, action_id: int):
    return _action_page(request, action_id)


@router.post("/actions/{action_id}/done")
def action_done(request: Request, action_id: int, form: Annotated[DoneForm, Form()]):
    link = form.link.strip()
    if not _is_link(link):
        reason = "Incolla il link dell'annuncio pubblicato: comincia con https://"
        return _action_page(request, action_id, typed_link=form.link, error=reason, status_code=422)
    with request.app.state.engine.begin() as connection:
        manual_channels.done(connection, action_id, link)
    return RedirectResponse("/actions", status_code=303)


def _is_link(text: str) -> bool:
    parts = urlsplit(text)
    return parts.scheme in ("https", "http") and bool(parts.netloc)


def _action_page(request: Request, action_id: int, typed_link: str = "", error: str = "", status_code: int = 200):
    """What Manuel needs to do the action in the channel's app: the texts and the price to copy, and the photos."""
    with request.app.state.engine.connect() as connection:
        action = manual_channels.action(connection, action_id)
        if action is None:
            raise HTTPException(status_code=404)
        item_id = action.listing.item_id
        name = items.get(connection, item_id).name
        texts = listing_texts.of_item(connection, item_id).texts
        shown = photos.of_item(connection, request.app.state.photos, item_id)
    return templates.TemplateResponse(
        request,
        "action.html",
        {"action": action, "name": name, "texts": texts, "photos": shown, "typed_link": typed_link, "error": error},
        status_code=status_code,
    )
