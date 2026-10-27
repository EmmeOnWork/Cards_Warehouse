"""The texts of an item's listings, edited by Manuel on the item's page."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import listing_texts
from cards_warehouse.listing_texts import Texts, TitleTooLong
from cards_warehouse.pages import templates

router = APIRouter()


class TextsForm(BaseModel):
    listing_title: str = ""
    listing_description: str = ""


@router.post("/items/{item_id}/texts")
def edit_texts(request: Request, item_id: int, form: Annotated[TextsForm, Form()]):
    # A browser ends the lines of a text box with \r\n.
    typed = Texts(form.listing_title.strip(), form.listing_description.replace("\r\n", "\n").strip())
    try:
        with request.app.state.engine.begin() as connection:
            listing_texts.edit(connection, item_id, typed)
    except TitleTooLong as refusal:
        # A page of its own, with what was typed: the item's page has much more, and needs none of it.
        reason = f"Il titolo ha {refusal.length} caratteri: su tutti i canali ne entrano al massimo {refusal.limit}."
        return templates.TemplateResponse(
            request,
            "texts_refused.html",
            {"reason": reason, "item_id": item_id, "typed": typed, "title_limit": refusal.limit},
            status_code=422,
        )
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/texts/regenerate")
def regenerate_texts(request: Request, item_id: int):
    with request.app.state.engine.begin() as connection:
        listing_texts.regenerate(connection, item_id)
    return RedirectResponse(f"/items/{item_id}", status_code=303)
