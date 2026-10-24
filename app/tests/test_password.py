from cards_warehouse.database import create_database_engine
from cards_warehouse.password import StoredPassword, hash_password
from tests.acceptance.containers import TEST_PASSWORD, TEST_PASSWORD_HASH


def test_a_password_changed_from_the_app_replaces_the_one_from_infisical(database):
    stored = StoredPassword(create_database_engine(), infisical_hash=TEST_PASSWORD_HASH)

    stored.change("a-new-test-password")

    assert stored.verify("a-new-test-password")
    assert not stored.verify(TEST_PASSWORD)


# Forgotten, the password changed from the app: make password-hash and a new PASSWORD_HASH in Infisical open it again.
def test_a_new_hash_put_in_infisical_after_a_change_wins_so_a_forgotten_password_can_be_reset(database):
    engine = create_database_engine()
    StoredPassword(engine, infisical_hash=TEST_PASSWORD_HASH).change("a-forgotten-password")

    after_the_reset = StoredPassword(engine, infisical_hash=hash_password("reset-from-the-pc"))

    assert after_the_reset.verify("reset-from-the-pc")
    assert not after_the_reset.verify("a-forgotten-password")
