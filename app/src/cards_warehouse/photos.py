"""The photos of the items, kept in the private S3 bucket of the foundations (infra/foundations).

The database knows each photo's key in the bucket and its place in the item's order. The bucket is a thin part
with no logic of its own: put, delete and link. The tests swap it for one in memory.
"""

import mimetypes
import os
import uuid
from dataclasses import dataclass
from typing import BinaryIO, Protocol

import boto3
from botocore.config import Config
from sqlalchemy import Column, Connection, Integer, Table, Text, delete, func, insert, select, update

from cards_warehouse.database import metadata

# Enough to open a page and look at its photos. A link copied elsewhere stops working soon after.
LINK_SECONDS = 5 * 60

item_photos = Table(
    "item_photos",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("item_id", Integer),
    Column("key", Text),
    Column("position", Integer),
)


class Store(Protocol):
    def put(self, key: str, photo: BinaryIO, content_type: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def link(self, key: str) -> str: ...


@dataclass(frozen=True)
class Shown:
    id: int
    link: str


def attach(connection: Connection, store: Store, item_id: int, photo: BinaryIO, content_type: str) -> None:
    """The photo goes last among the item's photos."""
    # A new key for every photo: nothing in the bucket is ever overwritten. With the extension, a photo
    # downloaded from its link keeps its type.
    key = f"items/{item_id}/{uuid.uuid4().hex}{mimetypes.guess_extension(content_type) or ''}"
    store.put(key, photo, content_type)
    last = select(func.coalesce(func.max(item_photos.c.position), 0)).where(item_photos.c.item_id == item_id)
    connection.execute(insert(item_photos).values(item_id=item_id, key=key, position=last.scalar_subquery() + 1))


def of_item(connection: Connection, store: Store, item_id: int) -> list[Shown]:
    """The item's photos in their order, the cover first, each with a link that opens it for a few minutes."""
    rows = connection.execute(
        select(item_photos.c.id, item_photos.c.key)
        .where(item_photos.c.item_id == item_id)
        .order_by(item_photos.c.position)
    )
    return [Shown(photo_id, store.link(key)) for photo_id, key in rows]


def move(connection: Connection, item_id: int, photo_id: int, *, earlier: bool) -> None:
    """The photo swaps places with the one before it, or after it. The first goes no earlier, the last no later."""
    order = connection.execute(
        select(item_photos.c.id, item_photos.c.position)
        .where(item_photos.c.item_id == item_id)
        .order_by(item_photos.c.position)
    ).all()
    # A photo not of this item, as from a page left open while it was deleted, has no place to leave.
    ids = [photo for photo, _ in order]
    if photo_id not in ids:
        return
    here = ids.index(photo_id)
    there = here - 1 if earlier else here + 1
    if not 0 <= there < len(order):
        return
    (photo, position), (other, other_position) = order[here], order[there]
    connection.execute(update(item_photos).where(item_photos.c.id == photo).values(position=other_position))
    connection.execute(update(item_photos).where(item_photos.c.id == other).values(position=position))


def remove(connection: Connection, store: Store, item_id: int, photo_id: int) -> None:
    """The photo leaves the item, then the bucket: if the bucket fails, the caller's transaction keeps it."""
    key = connection.execute(
        delete(item_photos)
        .where(item_photos.c.id == photo_id, item_photos.c.item_id == item_id)
        .returning(item_photos.c.key)
    ).scalar_one_or_none()
    if key is not None:
        store.delete(key)


class S3Store:
    def __init__(self, bucket: str, region: str) -> None:
        self._bucket = bucket
        # boto3 reads the key from AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY: the scoped key, from Infisical.
        # Links on the bucket's own Region: by default boto3 writes the global address, which for a bucket
        # created in the last hours answers with a redirect that breaks the signature.
        self._s3 = boto3.client("s3", region_name=region, config=Config(s3={"addressing_style": "virtual"}))

    @classmethod
    def from_environment(cls) -> "S3Store":
        return cls(os.environ["PHOTOS_BUCKET"], os.environ["PHOTOS_REGION"])

    # Sent from its file in one request, never whole in the pod's memory. The type makes the browser show it.
    def put(self, key: str, photo: BinaryIO, content_type: str) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=photo, ContentType=content_type)

    # The bucket keeps versions: S3 hides the photo behind a delete marker and keeps it as a previous version,
    # which docs/photos.md recovers. The app's key cannot delete versions: no mistake of the app destroys a photo.
    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._bucket, Key=key)

    # Signed here with the key, without asking AWS: S3 checks the signature and the expiry when the browser opens it.
    def link(self, key: str) -> str:
        return self._s3.generate_presigned_url(
            "get_object", Params={"Bucket": self._bucket, "Key": key}, ExpiresIn=LINK_SECONDS
        )
