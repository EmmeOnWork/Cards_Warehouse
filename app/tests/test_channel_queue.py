"""The queue of what a channel with an API did not answer: an update or a close that waits there, asked again by the
worker once its wait is over.

On a real PostgreSQL, through the exposure module, with a channel in memory that stops answering when a test says.
"""

from datetime import UTC, datetime, timedelta

from cards_warehouse import channel_queue, channels, exposure, manual_channels, stock
from cards_warehouse.channel_operations import ByChannel
from cards_warehouse.exposure import Status
from cards_warehouse.manual_channels import ActionKind
from cards_warehouse.stock import Cause
from tests.fake_channel import InMemoryChannel
from tests.test_exposure import a_sealed, channel_ids

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


def test_an_update_the_channel_does_not_answer_waits_in_the_queue_and_is_done_once_it_answers(connection):
    api = InMemoryChannel()
    item = _on_ebay(connection, api, copies=2)
    api.answering = False

    _sold_on_vinted(connection, item, api, copies=1)

    [listing] = exposure.of_item(connection, item)
    assert (listing.status, listing.quantity) == (Status.TO_UPDATE, 1)
    assert [(waiting.kind, waiting.listing.id) for waiting in channel_queue.of_item(connection, item)] == [
        (ActionKind.UPDATE, listing.id)
    ]

    api.answering = True
    channel_queue.retry_next(connection, {"eBay": api}, NOW + timedelta(minutes=1))

    [listing] = exposure.of_item(connection, item)
    assert (listing.status, listing.quantity) == (Status.ACTIVE, 1)
    assert [updated.quantity for updated in api.updated] == [1]
    assert channel_queue.of_item(connection, item) == []


# eBay silent for good: asked again 1, 2, 4, 8, 16 and 32 minutes after each try, an hour in all.
def test_the_wait_before_each_new_try_doubles_from_a_minute(connection):
    api = InMemoryChannel()
    item = _on_ebay(connection, api, copies=2)
    api.answering = False
    _sold_on_vinted(connection, item, api, copies=1)

    waits, tried_at = [], NOW
    for _ in range(6):
        [waiting] = channel_queue.of_item(connection, item)
        waits.append(waiting.retry_at - tried_at)
        tried_at = waiting.retry_at
        channel_queue.retry_next(connection, {"eBay": api}, tried_at)

    assert waits == [timedelta(minutes=minutes) for minutes in (1, 2, 4, 8, 16, 32)]


# The try at the end of the hour unanswered too: the update is Manuel's, an action with why on the listing, and the
# worker asks the channel nothing more. Once he did it on eBay and ticked it, the listing is as he left it.
def test_an_update_the_channel_does_not_answer_for_an_hour_is_left_to_manuel_with_the_reason(connection):
    api = InMemoryChannel()
    item = _on_ebay(connection, api, copies=2)
    api.answering = False
    _sold_on_vinted(connection, item, api, copies=1)

    for _ in range(6):
        [waiting] = channel_queue.of_item(connection, item)
        channel_queue.retry_next(connection, {"eBay": api}, waiting.retry_at)

    assert channel_queue.of_item(connection, item) == []
    assert not channel_queue.retry_next(connection, {"eBay": api}, NOW + timedelta(days=1))
    [action] = manual_channels.of_item(connection, item)
    assert (action.kind, action.listing.status, action.listing.problem) == (
        ActionKind.UPDATE,
        Status.TO_UPDATE,
        "eBay non ha risposto per un'ora: fallo a mano dall'app di eBay, poi spuntalo in Da fare.",
    )
    manual_channels.done(connection, action.id)
    [listing] = exposure.of_item(connection, item)
    assert (listing.status, listing.quantity, listing.problem) == (Status.ACTIVE, 1, None)


# Refused, the same call would be refused again: the close is Manuel's at once, with why, and nothing waits.
def test_a_close_the_channel_refuses_is_left_to_manuel_at_once_with_the_reason(connection):
    api = InMemoryChannel()
    item = _on_ebay(connection, api, copies=1)
    api.refusal = "eBay non accetta più l'autorizzazione: ricollega l'account dal PC con make ebay-connect."

    _sold_on_vinted(connection, item, api, copies=1)

    assert channel_queue.of_item(connection, item) == []
    [action] = manual_channels.of_item(connection, item)
    assert (action.kind, action.listing.status, action.listing.problem) == (
        ActionKind.CLOSE,
        Status.TO_CLOSE,
        "eBay non accetta più l'autorizzazione: ricollega l'account dal PC con make ebay-connect. "
        "Intanto fallo a mano dall'app di eBay, poi spuntalo in Da fare.",
    )


# eBay silent at both sales: the close takes the place of the update, which the channel never gets.
def test_a_close_asked_while_an_update_waits_takes_its_place(connection):
    api = InMemoryChannel()
    item = _on_ebay(connection, api, copies=2)
    api.answering = False
    _sold_on_vinted(connection, item, api, copies=1)
    _sold_on_vinted(connection, item, api, copies=1, at=NOW + timedelta(seconds=30))

    [waiting] = channel_queue.of_item(connection, item)
    assert (waiting.kind, waiting.retry_at) == (ActionKind.CLOSE, NOW + timedelta(seconds=30) + timedelta(minutes=1))

    api.answering = True
    while channel_queue.retry_next(connection, {"eBay": api}, NOW + timedelta(hours=2)):
        pass

    assert (api.updated, len(api.closed)) == ([], 1)
    assert exposure.of_item(connection, item) == []


def _on_ebay(connection, api: InMemoryChannel, copies: int) -> int:
    """An item on sale on eBay, which the app acts on through `api`."""
    item = a_sealed(connection, copies)
    [ebay] = channel_ids(connection, "eBay")
    channels.publish_through_api(connection, ebay, True)
    exposure.put_on_sale(connection, item, [ebay], _operations(api))
    return item


def _sold_on_vinted(connection, item: int, api: InMemoryChannel, copies: int, at: datetime = NOW) -> None:
    [lot] = stock.lots(connection, item)
    stock.unload(connection, lot.id, copies, Cause.SALE)
    exposure.sold(connection, item, *channel_ids(connection, "Vinted"), copies, _operations(api, at))


def _operations(api: InMemoryChannel, at: datetime = NOW) -> ByChannel:
    return ByChannel({"eBay": api}, now=lambda: at)
