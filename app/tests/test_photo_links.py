"""The links to the photos in the real bucket. Signing is done on the spot with the key: no call to AWS."""

from urllib.parse import parse_qs, urlsplit

from cards_warehouse.photos import S3Store


# The bucket is private: a photo opens only through a link signed with the app's key, and only for 5 minutes.
def test_a_link_to_a_photo_is_signed_with_the_app_key_and_expires_after_five_minutes(monkeypatch):
    monkeypatch.setenv("PHOTOS_BUCKET", "emmeonwork-cards-warehouse-photos")
    monkeypatch.setenv("PHOTOS_REGION", "eu-north-1")
    # Plainly fake, so no secret scanner mistakes them for real ones. In the cluster, the key from Infisical.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-access-key")

    link = urlsplit(S3Store.from_environment().link("items/1/front.jpg"))

    query = parse_qs(link.query)
    address = f"https://{link.netloc}{link.path}"
    assert address == "https://emmeonwork-cards-warehouse-photos.s3.eu-north-1.amazonaws.com/items/1/front.jpg"
    assert query["X-Amz-Credential"][0].startswith("test-access-key-id/")
    assert query["X-Amz-Expires"] == ["300"]
    assert query["X-Amz-Signature"]
