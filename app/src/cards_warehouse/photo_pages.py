"""The photos on the item's page: added from the phone's camera or gallery, put in order."""

import math
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from cards_warehouse import photos
from cards_warehouse.pages import templates

# A photo of a recent phone weighs 3 to 8 MB: 20 leaves room, and keeps out only the 200 MP shots and RAW files.
# Megabytes as the phone counts them. The chart sizes /tmp, where an upload waits, on this.
MAX_PHOTO_MB = 20
templates.env.globals["max_photo_mb"] = MAX_PHOTO_MB

router = APIRouter()


@router.post("/items/{item_id}/photos")
def add_photos(request: Request, item_id: int, uploaded: Annotated[list[UploadFile], File(alias="photos")]):
    # Every photo is checked before any is kept: of a batch, all go in or none.
    for photo in uploaded:
        if refusal := _refusal(photo):
            return templates.TemplateResponse(
                request, "photo_refused.html", {"reason": refusal, "item_id": item_id}, status_code=422
            )
    with request.app.state.engine.begin() as connection:
        for photo in uploaded:
            photos.attach(connection, request.app.state.photos, item_id, photo.file, photo.content_type)
    return _back_to(item_id)


@router.post("/items/{item_id}/photos/{photo_id}/move")
def move_photo(request: Request, item_id: int, photo_id: int, towards: Annotated[Literal["earlier", "later"], Form()]):
    with request.app.state.engine.begin() as connection:
        photos.move(connection, item_id, photo_id, earlier=towards == "earlier")
    return _back_to(item_id)


@router.post("/items/{item_id}/photos/{photo_id}/delete")
def delete_photo(request: Request, item_id: int, photo_id: int):
    with request.app.state.engine.begin() as connection:
        photos.remove(connection, request.app.state.photos, item_id, photo_id)
    return _back_to(item_id)


# The type is the one the phone declares: the app never opens the photo.
def _refusal(photo: UploadFile) -> str:
    if not (photo.content_type or "").startswith("image/"):
        return f"«{photo.filename}» non è una foto."
    megabytes = math.ceil(photo.size / 1_000_000)
    if megabytes > MAX_PHOTO_MB:
        return f"«{photo.filename}» pesa {megabytes} MB: il limite è {MAX_PHOTO_MB} MB per foto."
    return ""


def _back_to(item_id: int) -> RedirectResponse:
    return RedirectResponse(f"/items/{item_id}", status_code=303)
