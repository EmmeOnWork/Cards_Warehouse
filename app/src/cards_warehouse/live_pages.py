"""The pages of the live inventories: what Manuel shows in a live on Tilt, and the presets he starts one from."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from cards_warehouse import items, lives
from cards_warehouse.pages import templates

router = APIRouter()


class _Refused(Exception):
    """What was typed cannot be saved: the message says why."""


@router.get("/lives")
def live_list(request: Request):
    with request.app.state.engine.connect() as connection:
        inventories = lives.inventories(connection)
        presets = lives.presets(connection)
    return templates.TemplateResponse(request, "lives.html", {"inventories": inventories, "presets": presets})


# Empty, or with the items of the preset chosen.
@router.post("/lives")
def new_inventory(request: Request, preset: Annotated[int | None, Form()] = None):
    with request.app.state.engine.begin() as connection:
        inventory_id = lives.start(connection, preset)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


# The items found by the search are offered under the inventory, to add them with a tap.
@router.get("/lives/{inventory_id}")
def inventory_page(request: Request, inventory_id: int, q: str = ""):
    return _inventory_page(request, inventory_id, q)


@router.post("/lives/{inventory_id}/items")
def add_item(request: Request, inventory_id: int, item_id: Annotated[int, Form()]):
    with request.app.state.engine.begin() as connection:
        lives.add(connection, inventory_id, item_id)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


@router.post("/lives/{inventory_id}/remove")
def remove_item(request: Request, inventory_id: int, item_id: Annotated[int, Form()]):
    with request.app.state.engine.begin() as connection:
        lives.remove(connection, inventory_id, item_id)
    return RedirectResponse(f"/lives/{inventory_id}", status_code=303)


# On the page of the lives, where the preset is offered from then on.
@router.post("/lives/{inventory_id}/preset")
def save_as_preset(request: Request, inventory_id: int, name: Annotated[str, Form()]):
    try:
        if not name.strip():
            raise _Refused("Scrivi il nome della configurazione.")
        with request.app.state.engine.begin() as connection:
            if lives.save_as_preset(connection, inventory_id, name.strip()) is None:
                raise _Refused(f"La configurazione {name.strip()} c'è già.")
    except _Refused as refusal:
        return _inventory_page(request, inventory_id, preset_name=name, error=str(refusal), status_code=422)
    return RedirectResponse("/lives", status_code=303)


def _inventory_page(
    request: Request, inventory_id: int, q: str = "", preset_name: str = "", error: str = "", status_code: int = 200
):
    with request.app.state.engine.connect() as connection:
        rows = lives.rows(connection, inventory_id)
        found = items.search(connection, q) if q.strip() else []
    return templates.TemplateResponse(
        request,
        "live.html",
        {
            "inventory_id": inventory_id,
            "rows": rows,
            "q": q,
            "found": found,
            "preset_name": preset_name,
            "error": error,
        },
        status_code=status_code,
    )
