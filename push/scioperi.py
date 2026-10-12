#!/usr/bin/env python3
"""Scioperi Oggi: "the strike list changed" push.

The MIT adds strikes to its public list, revokes some and removes others,
at any hour of a working day. The workflow .github/workflows/push-scioperi.yml
runs this every 30 minutes from about 7:00 to 21:30 Rome time, with the
previous state of the list (kept in the Actions cache); a run that finds a
strike added, revoked or removed before its start sends one message to the
topic. A strike that simply ends changes nothing.

The message says nothing (the topic says nothing about the user either):
the app alone knows the user's areas, sectors and companies, so it wakes
up and runs its usual check, which notifies "Nuovo sciopero" or "Non più in
elenco" for the user's strikes only, or nothing.
  - Android receives data only (high priority).
  - iOS receives a background push (content-available): delivered when
    iOS allows, not after the user closed the app from the app switcher.
Both keep their background task as a fallback.

The app subscribes to the topic only while its "new and called off strikes"
alert is on (Pro); debug builds use the test topic. App side:
lib/src/push/push.dart in sillapps-strike-it. The list is read by
scioperi/build_oggi.py, the page's own parser (same rules as the app).

    python3 push/scioperi.py --check --state FILE    # prints due=true|false, updates FILE
    python3 push/scioperi.py --send [--topic scioperi-test] [--dry-run]

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "scioperi"))
import build_oggi as mit  # noqa: E402
import fcm  # noqa: E402

TOPIC = "scioperi-list"


def current(strikes: list[dict]) -> dict[str, dict]:
    """The list as the push compares it: id -> start day and whether it is
    called off (revoked, postponed, virtual: no disruption)."""
    return {
        s["id"]: {"start": s["start"].isoformat(), "end": s["end"].isoformat(), "off": bool(mit.status(s))}
        for s in strikes
    }


def changes(before: dict[str, dict] | None, now: dict[str, dict], today: dt.date) -> list[str]:
    """What the app may tell: a new strike not over yet, a strike called off
    or gone before its start. None before (first run): nothing to compare."""
    if before is None:
        return []
    out = []
    for sid, s in now.items():
        old = before.get(sid)
        if old is None and not s["off"] and dt.date.fromisoformat(s.get("end", s["start"])) >= today:
            out.append(f"new {sid} {s['start']}")
        elif old is not None and s["off"] and not old["off"] and dt.date.fromisoformat(s["start"]) >= today:
            out.append(f"called off {sid} {s['start']}")
    for sid, s in before.items():
        if sid not in now and not s["off"] and dt.date.fromisoformat(s["start"]) >= today:
            out.append(f"gone {sid} {s['start']}")
    return out


def read_list() -> list[dict]:
    strikes, _ = mit.parse_rss(mit.fetch(mit.RSS_URL))
    notes = mit.parse_notes(mit.fetch(mit.NOTES_URL))
    for s in strikes:
        s["notes"] = notes.get(mit.note_key(s["start"], s["sector"], s["category"], s["unions"], s["region"]), "")
    if not strikes:
        # The MIT always lists some strikes: an empty list is a failed read.
        raise ValueError("empty list")
    return strikes


def message(topic: str) -> dict:
    return {
        "topic": topic,
        "data": {"kind": "list"},
        # Kept a few hours at most: a later push or the app's own check
        # takes over.
        "android": {"priority": "HIGH", "ttl": "14400s", "collapse_key": topic},
        "apns": {
            "headers": {
                "apns-priority": "5",
                "apns-push-type": "background",
                "apns-collapse-id": topic,
            },
            "payload": {"aps": {"content-available": 1}},
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare with --state, print due=true|false, save the new state")
    ap.add_argument("--state", type=Path, help="JSON state of the previous run (created if missing)")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--topic", default=TOPIC)
    ap.add_argument("--dry-run", action="store_true", help="FCM validates without sending")
    args = ap.parse_args()

    if args.check:
        if args.state is None:
            ap.error("--check needs --state")
        today = dt.datetime.now(mit.ROME).date()
        try:
            now = current(read_list())
        except Exception as err:  # noqa: BLE001 - an unreadable list sends nothing
            print(f"list not readable: {err}", file=sys.stderr)
            print("due=false")
            return 0
        before = json.loads(args.state.read_text()) if args.state.exists() else None
        found = changes(before, now, today)
        for line in found:
            print(line)
        args.state.write_text(json.dumps(now, sort_keys=True))
        print(f"strikes={len(now)} first_run={str(before is None).lower()} due={str(bool(found)).lower()}")
        return 0
    if args.send:
        name = fcm.send(message(args.topic), dry_run=args.dry_run)
        print(f"sent to {args.topic}: {name or '(validated)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
