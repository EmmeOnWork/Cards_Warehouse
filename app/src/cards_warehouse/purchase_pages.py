"""The pages of the purchases, and of the partners who share them."""

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cards_warehouse import partners, purchases
from cards_warehouse.pages import templates

router = APIRouter()


class PartnerForm(BaseModel):
    name: str = ""


class _Refused(Exception):
    """What was typed cannot be saved: the message says why."""


@router.get("/purchases")
def purchase_list(request: Request):
    with request.app.state.engine.connect() as connection:
        listed = purchases.listing(connection)
    return templates.TemplateResponse(request, "purchases.html", {"purchases": listed})


@router.get("/partners")
def partner_list(request: Request):
    return _partner_list(request)


@router.post("/partners")
def add_partner(request: Request, form: Annotated[PartnerForm, Form()]):
    try:
        name = _name(form)
        with request.app.state.engine.begin() as connection:
            if partners.add(connection, name) is None:
                raise _Refused(f"{name} c'è già.")
    except _Refused as refusal:
        return _partner_list(request, form, error=str(refusal), status_code=422)
    return RedirectResponse("/partners", status_code=303)


@router.get("/partners/{partner_id}")
def partner_page(request: Request, partner_id: int):
    return _partner_page(request, partner_id)


@router.post("/partners/{partner_id}")
def rename_partner(request: Request, partner_id: int, form: Annotated[PartnerForm, Form()]):
    try:
        name = _name(form)
        with request.app.state.engine.begin() as connection:
            if not partners.rename(connection, partner_id, name):
                raise _Refused(f"{name} c'è già.")
    except _Refused as refusal:
        return _partner_page(request, partner_id, form, error=str(refusal), status_code=422)
    return RedirectResponse("/partners", status_code=303)


def _name(form: PartnerForm) -> str:
    if not (name := form.name.strip()):
        raise _Refused("Scrivi il nome del collaboratore.")
    return name


def _partner_list(request: Request, new: PartnerForm | None = None, error: str = "", status_code: int = 200):
    with request.app.state.engine.connect() as connection:
        every = partners.every(connection)
    return templates.TemplateResponse(
        request,
        "partners.html",
        {"partners": every, "new": new or PartnerForm(), "error": error},
        status_code=status_code,
    )


def _partner_page(
    request: Request, partner_id: int, form: PartnerForm | None = None, error: str = "", status_code: int = 200
):
    with request.app.state.engine.connect() as connection:
        partner = partners.one(connection, partner_id)
    if partner is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(
        request,
        "partner.html",
        {"partner": partner, "form": form or PartnerForm(name=partner.name), "error": error},
        status_code=status_code,
    )
