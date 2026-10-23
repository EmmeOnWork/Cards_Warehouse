"""The outcome of the last backup, shown on the home page: read from the Backup objects of Velero."""

import json
import ssl
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# The time the page shows: Manuel's, not the UTC of the cluster.
LOCAL_TIME = ZoneInfo("Europe/Rome")
# The schedule runs once a day: an older last backup means a day went by without one.
MAX_AGE = timedelta(days=1)
# The phases a backup ends in. The others mean it is still running, or being deleted once expired.
FINISHED = {"Completed", "PartiallyFailed", "Failed", "FailedValidation"}

# The pod's identity: Kubernetes mounts its token, and the certificate of the API server, here.
SERVICE_ACCOUNT = Path("/var/run/secrets/kubernetes.io/serviceaccount")
# Where Velero keeps its Backup objects (gitops/apps/velero.yaml). The chart lets the app list them, and nothing else.
BACKUPS_URL = "https://kubernetes.default.svc/apis/velero.io/v1/namespaces/velero/backups"


@dataclass(frozen=True)
class Outcome:
    text: str
    # Something to look at: the page shows it in red.
    alarm: bool = True


def last_outcome(read_backups: Callable[[], list[dict]], now: datetime) -> Outcome:
    try:
        backups = read_backups()
    except OSError as error:
        return Outcome(f"Attenzione: stato dei backup non leggibile ({error}).")
    return _outcome(backups, now)


def _outcome(backups: list[dict], now: datetime) -> Outcome:
    finished = [backup for backup in backups if backup["status"].get("phase") in FINISHED]
    if not finished:
        return Outcome("Attenzione: nessun backup finora.")
    last = max(finished, key=_time)
    if last["status"]["phase"] != "Completed":
        return Outcome(f"Attenzione: l'ultimo backup, del {_when(last)}, non è riuscito ({last['status']['phase']}).")
    if now - _time(last) > MAX_AGE:
        return Outcome(f"Attenzione: nessun backup riuscito da più di un giorno. L'ultimo è del {_when(last)}.")
    return Outcome(f"Ultimo backup: {_when(last)}, riuscito.", alarm=False)


def read_from_velero() -> list[dict]:
    """The Backup objects of Velero, listed through the Kubernetes API as the app's service account."""
    # Read at every call: Kubernetes replaces the token before it expires.
    token = (SERVICE_ACCOUNT / "token").read_text()
    request = urllib.request.Request(BACKUPS_URL, headers={"Authorization": f"Bearer {token}"})
    context = ssl.create_default_context(cafile=SERVICE_ACCOUNT / "ca.crt")
    # A slow API delays the home page by 2 s at most.
    with urllib.request.urlopen(request, context=context, timeout=2) as response:
        return json.load(response)["items"]


# When it ended. A backup refused before it started has neither start nor end: the time it was asked for.
def _time(backup: dict) -> datetime:
    status = backup["status"]
    when = status.get("completionTimestamp") or status.get("startTimestamp") or backup["metadata"]["creationTimestamp"]
    return datetime.fromisoformat(when)


def _when(backup: dict) -> str:
    return f"{_time(backup).astimezone(LOCAL_TIME):%d/%m alle %H:%M}"


if __name__ == "__main__":
    # Inside the app's pod, the line the home page shows: the platform's backup test reads it (infra/platform/tests).
    print(last_outcome(read_from_velero, datetime.now(UTC)).text)
