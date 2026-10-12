#!/usr/bin/env python3
"""Hora Barata: "tomorrow's prices are out" push, once a day.

Red Eléctrica publishes the next day's PVPC prices around 20:15 Madrid time.
The workflow .github/workflows/push-hora-barata.yml runs this every few
minutes from 20:05; the first run that finds tomorrow's complete day sends
one message to the topic, and the workflow remembers the day (cache key) so
later runs stop. Nothing is sent after 22:30 (the app's quiet hours start at
23:00).

The PVPC price is the same for everyone, so the message carries tomorrow's
prices themselves (about 25 numbers): the phone words the alert with the
user's own settings (language, taxes, Canary Islands clock) without asking
the network again. The topic says nothing about the user.
  - Android receives data only (high priority). The app wakes up and shows
    its usual alert ("Hora más barata: 14:00 (0,052 €/kWh).") and schedules
    tomorrow's cheap-hour alerts. Its background task stays as a fallback;
    the app tells a day once.
  - iOS shows the alert below, in the phone's language (loc keys of the
    app), rewritten by the app's notification service extension
    (ios/PriceAlert) with the cheapest hour, and wakes the app when iOS
    allows (content-available) to schedule tomorrow's alerts.

The app subscribes to the topic only while Pro and its alerts are on; debug
builds use the test topic. App side: lib/src/push/ in sillapps-elec-es.

    python3 push/hora_barata.py --check           # prints due=true|false
    python3 push/hora_barata.py --send [--topic horabarata-test] [--dry-run]

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import fcm  # noqa: E402

MADRID = ZoneInfo("Europe/Madrid")
REDATA = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
ESIOS = "https://api.esios.ree.es/archives/70/download_json"
FIRST = (20, 5)
LAST = (22, 30)
TOPIC = "horabarata-tomorrow"
UA = {"User-Agent": "HoraBarata-push/1.0", "Accept": "application/json"}


def madrid_now() -> datetime:
    return datetime.now(MADRID)


def madrid_midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=MADRID).astimezone(timezone.utc)


def hours_in(day: date) -> int:
    """23, 24 or 25: the day clocks go forward or back has one hour less or more."""
    return int((madrid_midnight(day + timedelta(days=1)) - madrid_midnight(day)).total_seconds() // 3600)


def _get(url: str) -> tuple[int, bytes] | None:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except OSError as e:
            if attempt == 2:
                print(f"{url.split('?')[0]} unreachable: {e}", file=sys.stderr)
                return None
            time.sleep(10)
    return None


def _complete(day: date, samples: list[tuple[datetime, float]]) -> list[float] | None:
    """Hourly prices (EUR/kWh) from Madrid midnight, quarter hours averaged,
    or None unless every hour of the day is there (the app's completeDay)."""
    groups: dict[datetime, list[float]] = {}
    for start, price in samples:
        groups.setdefault(start.replace(minute=0, second=0, microsecond=0), []).append(price)
    per_hour = 4 if len(samples) > 25 else 1
    n = hours_in(day)
    midnight = madrid_midnight(day)
    hours = [midnight + timedelta(hours=i) for i in range(n)]
    if sorted(groups) != hours or any(len(g) != per_hour for g in groups.values()):
        return None
    return [sum(groups[h]) / per_hour for h in hours]


def redata(day: date) -> list[float] | None:
    d = day.isoformat()
    q = urllib.parse.urlencode({"start_date": f"{d}T00:00", "end_date": f"{d}T23:59", "time_trunc": "hour"})
    res = _get(f"{REDATA}?{q}")
    if not res or res[0] != 200:
        return None
    try:
        for item in json.loads(res[1]).get("included", []):
            if item.get("type") != "PVPC":
                continue
            samples = []
            for v in item["attributes"]["values"]:
                dt = v["datetime"]
                if dt[:10] != d:
                    continue
                samples.append((datetime.fromisoformat(dt).astimezone(timezone.utc), v["value"] / 1000))
            return _complete(day, samples)
    except (ValueError, KeyError, TypeError):
        print("REData: unusable answer", file=sys.stderr)
    return None


def esios(day: date) -> list[float] | None:
    res = _get(f"{ESIOS}?" + urllib.parse.urlencode({"locale": "es", "date": day.isoformat()}))
    if not res or res[0] != 200:
        return None
    try:
        rows = json.loads(res[1]).get("PVPC")
        if not rows or any(r["Dia"] != day.strftime("%d/%m/%Y") for r in rows):
            return None
        prices = [float(r["PCB"].replace(",", ".")) / 1000 for r in rows]
        per_hour = 4 if len(prices) > 25 else 1
        midnight = madrid_midnight(day)
        # Rows are in time order: row i is slot i (labels break on DST days).
        return _complete(day, [(midnight + timedelta(minutes=60 // per_hour * i), p) for i, p in enumerate(prices)])
    except (ValueError, KeyError, TypeError, AttributeError):
        print("ESIOS: unusable answer", file=sys.stderr)
    return None


def prices(day: date) -> list[float] | None:
    return redata(day) or esios(day)


def message(day: date, hourly: list[float], topic: str, now: datetime) -> dict:
    end = now.replace(hour=LAST[0], minute=LAST[1], second=0, microsecond=0)
    if end <= now:  # forced test after the window
        end = now + timedelta(hours=1)
    ttl = max(60, int((end - now).total_seconds()))
    data = {
        "kind": "tomorrow",
        "day": day.isoformat(),
        # Start of the first hour (Madrid midnight, Unix seconds); one price an hour after it.
        "s": str(int(madrid_midnight(day).timestamp())),
        "p": ",".join(f"{p:.5f}" for p in hourly),
    }
    return {
        "topic": topic,
        "data": data,
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
                    # Words of the app (ios/Runner/<lang>.lproj/Localizable.strings),
                    # rewritten with the cheapest hour by ios/PriceAlert.
                    "alert": {"title-loc-key": "push_tomorrow_title", "loc-key": "push_tomorrow_body"},
                    "sound": "default",
                    "thread-id": "tomorrow",
                    "content-available": 1,
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
    ap.add_argument("--force", action="store_true", help="send outside 20:05-22:30 (test topic)")
    ap.add_argument("--day", type=date.fromisoformat, help="another published day (tests, with --force)")
    args = ap.parse_args()

    now = madrid_now()
    day = args.day or now.date() + timedelta(days=1)
    in_window = FIRST <= (now.hour, now.minute) <= LAST
    hourly = prices(day) if (in_window or args.force) else None
    due = hourly is not None
    print(f"madrid={now:%Y-%m-%d %H:%M} day={day} hours={len(hourly) if hourly else 0} due={str(due).lower()}")
    if args.check:
        return 0
    if args.send:
        if not due:
            print("not due: nothing sent")
            return 0
        msg = message(day, hourly, args.topic, now)
        name = fcm.send(msg, dry_run=args.dry_run)
        print(f"sent to {args.topic}: {name or '(validated)'} ({len(json.dumps(msg['data']))} bytes of data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
