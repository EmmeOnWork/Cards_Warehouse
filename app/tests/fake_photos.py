"""The photos bucket as the app sees it, in memory: no call to AWS."""

from typing import BinaryIO
from urllib.parse import urlsplit


class FakePhotoStore:
    def __init__(self) -> None:
        self._photos: dict[str, bytes] = {}

    def put(self, key: str, photo: BinaryIO, content_type: str) -> None:
        self._photos[key] = photo.read()

    # As S3: deleting a key that is not there is no error.
    def delete(self, key: str) -> None:
        self._photos.pop(key, None)

    def link(self, key: str) -> str:
        return f"https://photos.test/{key}?expires=300"

    def contents(self) -> list[bytes]:
        """The photos the bucket holds now. The real one keeps the deleted ones as previous versions too."""
        return list(self._photos.values())

    def open(self, link: str) -> bytes:
        """What the browser gets from a link of the page: the photo, while it is in the bucket."""
        return self._photos[urlsplit(link).path.removeprefix("/")]
