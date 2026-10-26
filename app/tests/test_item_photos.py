"""The photos of an item, taken or picked on the phone, kept in the private bucket and shown through short links.

Through the app's HTTP routes, on a real PostgreSQL, with the photos bucket in memory instead of S3.
"""

import html

import pytest

from tests.pages import buttons, image_labels, images

BOOSTER_BOX = {
    "kind": "sealed",
    "game": "Pokémon",
    "name": "Booster box Evoluzioni a Paldea",
    "language": "it",
    "quantity": "1",
    "total_cost": "89,90",
}
# What the phone sends is not read by the app: any bytes stand for a photo.
FRONT = b"\xff\xd8 the front of the box \xff\xd9"
BACK = b"\xff\xd8 the back of the box \xff\xd9"
SEAL = b"\xff\xd8 the seal of the box \xff\xd9"


# The input offers the camera and the gallery: either way the phone sends the photo as a file of the form.
def test_a_photo_taken_on_the_phone_is_attached_to_the_item_and_shown_on_its_page(signed_in_client, photos):
    item_page = _loaded(signed_in_client)

    _add(signed_in_client, item_page, FRONT)

    assert _shown(signed_in_client, photos, item_page) == [FRONT]


# The cover is the photo the channels show first: the first one, until Manuel moves another before it.
def test_photos_keep_the_order_they_were_added_in_and_the_first_is_the_cover(signed_in_client, photos):
    item_page = _loaded(signed_in_client)

    _add(signed_in_client, item_page, FRONT)
    _add(signed_in_client, item_page, BACK, SEAL)

    assert _shown(signed_in_client, photos, item_page) == [FRONT, BACK, SEAL]
    assert image_labels(signed_in_client.get(item_page).text) == ["Copertina", "Foto 2", "Foto 3"]


# One place at a time, with the arrows: a photo moved before the first becomes the cover.
def test_photos_move_one_place_up_or_down_and_the_one_moved_to_the_top_is_the_cover(signed_in_client, photos):
    item_page = _loaded(signed_in_client)
    _add(signed_in_client, item_page, FRONT, BACK, SEAL)

    _press(signed_in_client, item_page, "Sposta prima la foto 3")
    _press(signed_in_client, item_page, "Sposta prima la foto 2")
    _press(signed_in_client, item_page, "Sposta dopo la foto 2")

    assert _shown(signed_in_client, photos, item_page) == [SEAL, BACK, FRONT]


# Out of the bucket too, where it would be paid for nothing. Its previous version brings it back (docs/photos.md).
def test_a_deleted_photo_leaves_the_page_and_the_bucket(signed_in_client, photos):
    item_page = _loaded(signed_in_client)
    _add(signed_in_client, item_page, FRONT, BACK)

    _press(signed_in_client, item_page, "Elimina la foto 1")

    assert _shown(signed_in_client, photos, item_page) == [BACK]
    assert photos.contents() == [BACK]


# The page says the limit before the upload. Of photos picked together, none is kept if one is refused:
# Manuel picks again, without wondering which ones went in.
@pytest.mark.parametrize(
    ("refused", "reason"),
    [
        (("IMG_0002.JPG", b"\xff" * 25_000_000, "image/jpeg"), "«IMG_0002.JPG» pesa 25 MB: il limite è 20 MB per foto"),
        (("receipt.pdf", b"%PDF-1.7", "application/pdf"), "«receipt.pdf» non è una foto"),
    ],
)
def test_a_file_over_the_limit_or_not_a_photo_is_refused_with_its_reason_and_nothing_is_kept(
    signed_in_client, photos, refused, reason
):
    item_page = _loaded(signed_in_client)

    picked = [("photos", ("IMG_0001.JPG", FRONT, "image/jpeg")), ("photos", refused)]
    response = signed_in_client.post(f"{item_page}/photos", files=picked)

    assert response.status_code == 422
    assert reason in html.unescape(response.text)
    assert _shown(signed_in_client, photos, item_page) == []
    assert photos.contents() == []


def _loaded(client) -> str:
    """The page of a new item: where the load lands."""
    return client.post("/items", data=BOOSTER_BOX).url.path


def _add(client, item_page: str, *photos: bytes):
    """Photos picked together, sent in one form as the phone sends them."""
    files = [("photos", (f"IMG_{number}.JPG", photo, "image/jpeg")) for number, photo in enumerate(photos)]
    return client.post(f"{item_page}/photos", files=files)


def _press(client, item_page: str, label: str):
    """Manuel taps the button of the item's page with that label."""
    address, sent = buttons(client.get(item_page).text)[label]
    return client.post(address, data=sent)


def _shown(client, photos, item_page: str) -> list[bytes]:
    """The photos the item's page shows, in their order, as the browser opens them from their links."""
    return [photos.open(link) for link in images(client.get(item_page).text)]
