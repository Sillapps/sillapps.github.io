#!/usr/bin/env python3
"""Fuel Tomorrow WA: "tomorrow's prices are out" push, once a day.

FuelWatch publishes the next day's prices at 2:30pm Perth time (UTC+8, no
daylight saving). The workflow .github/workflows/push-fuel-wa.yml runs this
every few minutes from 2:31pm; the first run that finds tomorrow's prices
in the feed sends one message to the topic, and the workflow remembers the
day (cache key) so later runs stop.

The message is the same for everyone (no suburb, no fuel: the topic says
nothing about the user):
  - Android receives data only (high priority). The app wakes up, reads
    the feed for its own suburb, fuel, brands and discounts, and shows its
    usual alert ("ULP in Morley: 4.0c cheaper tomorrow") or nothing on a
    quiet day. Its hourly background task stays as a fallback; the app
    tells a day once.
  - iOS shows the alert below, rewritten on the phone by the app's
    notification service extension ("ULP in Morley: wait, tomorrow is 4.0c
    cheaper"), and refreshes the widget when iOS gives it a moment.

The app subscribes to the topic only while the alert is on (Pro); debug
builds use the test topic. App side: lib/src/push/ in sillapps-fuel-au.

    python3 push/fuel_wa.py --check           # prints due=true|false
    python3 push/fuel_wa.py --send [--topic fuelwa-test] [--dry-run]

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import fcm  # noqa: E402

FEED = "https://www.fuelwatch.wa.gov.au/fuelwatch/fuelWatchRSS"
PERTH = timezone(timedelta(hours=8))
PUBLISH = (14, 30)
# The app's alert window ends at 9pm (kAlertLastHour): later, it stays quiet.
LAST_HOUR = 21
TOPIC = "fuelwa-tomorrow"
TITLE = "Tomorrow's prices are out"
BODY = "See if it's cheaper to fill up today or wait."
UA = {"User-Agent": "FuelTomorrowWA-push/1.0"}


def perth_now() -> datetime:
    return datetime.now(PERTH)


def tomorrow_published(day: date) -> bool:
    """Whether the feed has prices dated [day] (ULP around Perth)."""
    url = FEED + "?" + urllib.parse.urlencode(
        {"Product": 1, "Suburb": "Perth", "Surrounding": "yes", "Day": "tomorrow"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                body = r.read().decode("utf-8-sig")
            break
        except OSError as e:
            if attempt == 2:
                print(f"feed unreachable: {e}", file=sys.stderr)
                return False
            time.sleep(10)
    try:
        channel = ET.fromstring(body.lstrip()).find("channel")
    except ET.ParseError:
        print("feed: not XML", file=sys.stderr)
        return False
    if channel is None:
        return False
    # "13/10/2026 - Perth": the day the feed answers for.
    desc = (channel.findtext("description") or "").split(" - ")[0].strip()
    if desc != day.strftime("%d/%m/%Y"):
        return False
    return any((item.findtext("date") or "").strip() == day.isoformat() for item in channel.findall("item"))


def message(day: date, topic: str, now: datetime) -> dict:
    end = datetime(now.year, now.month, now.day, LAST_HOUR, tzinfo=PERTH)
    ttl = max(60, int((end - now).total_seconds()))
    return {
        "topic": topic,
        "data": {"kind": "tomorrow", "day": day.isoformat()},
        "android": {"priority": "HIGH", "ttl": f"{ttl}s", "collapse_key": topic},
        "apns": {
            "headers": {
                "apns-priority": "10",
                "apns-push-type": "alert",
                "apns-expiration": str(int(end.timestamp())),
                "apns-collapse-id": topic,
            },
            "payload": {
                "aps": {
                    "alert": {"title": TITLE, "body": BODY},
                    "sound": "default",
                    "thread-id": "tomorrow",
                    "content-available": 1,
                    # The app's notification service extension rewrites the
                    # alert for the user's suburb (ios/FuelAlert).
                    "mutable-content": 1,
                },
            },
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print due=true when tomorrow's prices are out")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--topic", default=TOPIC)
    ap.add_argument("--dry-run", action="store_true", help="FCM validates without sending")
    ap.add_argument("--force", action="store_true", help="send even outside 2:30pm-9pm or before publication")
    args = ap.parse_args()

    now = perth_now()
    day = now.date() + timedelta(days=1)
    in_window = PUBLISH <= (now.hour, now.minute) and now.hour < LAST_HOUR
    due = args.force or (in_window and tomorrow_published(day))
    print(f"perth={now:%Y-%m-%d %H:%M} day={day} due={str(due).lower()}")
    if args.check:
        return 0
    if args.send:
        if not due:
            print("not due: nothing sent")
            return 0
        name = fcm.send(message(day, args.topic, now), dry_run=args.dry_run)
        print(f"sent to {args.topic}: {name or '(validated)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
