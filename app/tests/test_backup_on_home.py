import html
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from cards_warehouse.main import create_app
from tests.acceptance.containers import TEST_PASSWORD

# The login reads the password from the database: every test has one.
pytestmark = pytest.mark.usefixtures("database")

# 21:30 in Italy, on summer time until the 25th.
NOW = datetime(2026, 10, 23, 19, 30, tzinfo=UTC)


def test_home_shows_when_the_last_backup_finished_and_that_it_succeeded():
    client = signed_in(backups=[backup("Completed", finished=NOW - timedelta(minutes=30))])

    page = home(client)

    assert "Ultimo backup: 23/10 alle 21:00, riuscito." in page


# A day exactly is still on time: the next daily backup is due right then. A second later, it is late.
def test_home_warns_when_no_backup_succeeded_for_more_than_a_day():
    backups = [backup("Completed", finished=NOW - timedelta(days=1))]

    on_time = home(signed_in(backups, now=NOW))
    late = home(signed_in(backups, now=NOW + timedelta(seconds=1)))

    assert "Ultimo backup: 22/10 alle 21:30, riuscito." in on_time
    assert "Attenzione: nessun backup riuscito da più di un giorno. L'ultimo è del 22/10 alle 21:30." in late


# Velero says PartiallyFailed when part of the backup could not be saved: the dump hook failing, for example.
def test_home_warns_when_the_last_backup_failed():
    backups = [
        backup("Completed", finished=NOW - timedelta(hours=2)),
        backup("PartiallyFailed", finished=NOW - timedelta(hours=1)),
    ]

    page = home(signed_in(backups))

    assert "Attenzione: l'ultimo backup, del 23/10 alle 20:30, non è riuscito (PartiallyFailed)." in page


# Every evening, for about a minute, the newest backup is still running: it has no outcome yet.
def test_a_backup_still_running_leaves_the_last_outcome_on_the_home():
    running = backup("InProgress", finished=NOW)
    del running["status"]["completionTimestamp"]

    page = home(signed_in([backup("Completed", finished=NOW - timedelta(days=1)), running]))

    assert "Ultimo backup: 22/10 alle 21:30, riuscito." in page


# Refused before it started, when the bucket cannot be reached for example: Velero gives it no start and no end time.
def test_home_warns_when_the_last_backup_was_refused_before_it_started():
    refused = backup("FailedValidation", finished=NOW - timedelta(hours=1))
    del refused["status"]["startTimestamp"], refused["status"]["completionTimestamp"]

    page = home(signed_in([backup("Completed", finished=NOW - timedelta(hours=2)), refused]))

    assert "Attenzione: l'ultimo backup, del 23/10 alle 20:29, non è riuscito (FailedValidation)." in page


# Silence would look like nothing to worry about: no backup at all is said, as a problem.
def test_home_warns_when_there_is_no_backup():
    page = home(signed_in([]))

    assert "Attenzione: nessun backup finora." in page


# Outside the cluster, or with the Kubernetes API down: the rest of the app keeps working, and the reason is shown.
def test_home_opens_even_when_the_backups_cannot_be_read():
    def unreachable() -> list[dict]:
        raise OSError("connection refused")

    client = TestClient(create_app(read_backups=unreachable))
    client.post("/login", data={"password": TEST_PASSWORD})

    response = client.get("/")

    assert response.status_code == 200
    assert "Attenzione: stato dei backup non leggibile (connection refused)." in html.unescape(response.text)


def signed_in(backups: list[dict], now: datetime = NOW) -> TestClient:
    client = TestClient(create_app(now=lambda: now, read_backups=lambda: backups))
    client.post("/login", data={"password": TEST_PASSWORD})
    return client


# The text the page shows, as read on screen: the page escapes characters such as the apostrophe.
def home(client: TestClient) -> str:
    return html.unescape(client.get("/").text)


def backup(phase: str, finished: datetime) -> dict:
    """A Backup of Velero as the Kubernetes API lists it, with the fields the app reads."""
    started = finished - timedelta(seconds=40)
    return {
        "metadata": {"name": f"velero-daily-{started:%Y%m%d%H%M%S}", "creationTimestamp": kubernetes_time(started)},
        "status": {
            "phase": phase,
            "startTimestamp": kubernetes_time(started),
            "completionTimestamp": kubernetes_time(finished),
        },
    }


def kubernetes_time(moment: datetime) -> str:
    return f"{moment:%Y-%m-%dT%H:%M:%SZ}"
