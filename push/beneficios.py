#!/usr/bin/env python3
"""Dia do Pagamento (Beneficios): "new dates are out" push, per program.

The app's weekday watch publishes beneficios/calendars.json (tool/publish_site.sh
in sillapps-beneficios). The workflow .github/workflows/push-beneficios.yml
runs on each push of that file: this script compares it with the previous
version and sends one message to the topic of each program that gained
payment dates still to come (Mexico's next bimester, a SASSA month, an SRD
period, a new year in Brazil). It waits until sillapps.com serves the new
file first: the apps fetch it as soon as the push arrives.

The message is the same for everyone who follows the program (the topic says
nothing about the person, no NIS digit, no letter):
  - Android receives data only (high priority). The app wakes up, fetches the
    version named in the message and shows its usual "Saiu a data" alert,
    worded for each person, only when that person's next date was not out yet.
    Its background refresh stays as a fallback.
  - iOS shows the alert below, in the program's country language.

The app joins the topics of the programs it follows while its alerts are on
(Pro or trial); debug builds use the "beneficios-test-" topics. App side:
lib/src/push/ in sillapps-beneficios.

    python3 push/beneficios.py --old OLD.json [--new beneficios/calendars.json]
                               # prints the programs with new dates
    python3 push/beneficios.py --old OLD.json --send [--prefix beneficios-test-] [--dry-run]
    python3 push/beneficios.py --test PROGRAM --send   # one test message, test topic

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import fcm  # noqa: E402

PREFIX = "beneficios-"
TEST_PREFIX = "beneficios-test-"
LIVE = "https://sillapps.com/beneficios/calendars.json"
UA = {"User-Agent": "DiaDoPagamento-push/1.0"}
# A message older than this is moot: the app's own refresh has caught up.
TTL = timedelta(days=2)
# Same voice as the app's own alert ("Saiu a data: Bolsa Família").
TEXTS = {
    "pt": ("Saíram novas datas: {name}", "Veja no app o dia do seu pagamento."),
    "es": ("Ya hay nuevas fechas: {name}", "Mira en la app tu día de pago."),
    "en": ("New dates are out: {name}", "Open the app to see your payment day."),
}


def payment_days(program: dict) -> set[str]:
    """Every payment start day of [program] (ISO dates)."""
    days: set[str] = set()

    def walk(v):
        if isinstance(v, str):
            if len(v) == 10 and v[4] == "-" and v[7] == "-":
                days.add(v)
        elif isinstance(v, dict):
            if "from" in v:
                walk(v["from"])
            else:
                for x in v.values():
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for calendar in program.get("calendars", []):
        for payment in calendar.get("payments", []):
            walk(payment.get("by_key", {}))
            walk(payment.get("all"))
    return days


def programs(book: dict) -> dict[str, tuple[dict, dict]]:
    return {p["id"]: (c, p) for c in book.get("countries", []) for p in c.get("programs", [])}


def new_dates(old: dict, new: dict, now: datetime | None = None) -> list[tuple[dict, dict, list[str]]]:
    """(country, program, new days) for each program with payment days still
    to come (on its country's clock) that the old file didn't have."""
    before = programs(old)
    out = []
    for pid, (country, program) in programs(new).items():
        today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(country["timezone"])).date().isoformat()
        known = payment_days(before[pid][1]) if pid in before else set()
        added = sorted(d for d in payment_days(program) - known if d >= today)
        if added:
            out.append((country, program, added))
    return out


def message(country: dict, program: dict, version: int, prefix: str, now: datetime) -> dict:
    title, body = TEXTS.get(country.get("language", "pt"), TEXTS["pt"])
    topic = prefix + program["id"]
    return {
        "topic": topic,
        "data": {"kind": "new_dates", "program": program["id"], "version": str(version)},
        "android": {"priority": "HIGH", "ttl": f"{int(TTL.total_seconds())}s", "collapse_key": topic},
        "apns": {
            "headers": {
                "apns-priority": "10",
                "apns-push-type": "alert",
                "apns-expiration": str(int((now + TTL).timestamp())),
                "apns-collapse-id": topic,
            },
            "payload": {
                "aps": {
                    "alert": {"title": title.format(name=program["short_name"]), "body": body},
                    "sound": "default",
                    "thread-id": topic,
                    "content-available": 1,
                },
            },
        },
    }


def wait_live(version: int, timeout: float = 900) -> bool:
    """Whether sillapps.com serves [version] (as the apps fetch it: ?v=)."""
    end = time.time() + timeout
    while True:
        try:
            req = urllib.request.Request(f"{LIVE}?v={version}", headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                if json.load(r).get("version") == version:
                    return True
        except (OSError, ValueError):
            pass
        if time.time() > end:
            return False
        time.sleep(20)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", help="previous calendars.json (missing or empty: nothing is new)")
    ap.add_argument("--new", default="beneficios/calendars.json")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--prefix", default=PREFIX)
    ap.add_argument("--dry-run", action="store_true", help="FCM validates without sending")
    ap.add_argument("--test", metavar="PROGRAM", help="one message for PROGRAM to its test topic")
    ap.add_argument("--no-wait", action="store_true", help="don't wait for sillapps.com to serve the file")
    args = ap.parse_args()

    with open(args.new, encoding="utf-8") as f:
        new = json.load(f)
    version = new["version"]
    now = datetime.now(timezone.utc)
    if args.test:
        country, program = programs(new)[args.test]
        due = [(country, program, ["test"])]
        args.prefix = TEST_PREFIX
    else:
        try:
            with open(args.old, encoding="utf-8") as f:
                old = json.load(f)
        except (TypeError, OSError, ValueError):
            # No previous file to compare with: never a push on a doubt.
            print(f"no previous calendars to compare with ({args.old}): due=false")
            return 0
        due = new_dates(old, new, now)
    for country, program, days in due:
        print(f"{program['id']}: {len(days)} new day(s) from {days[0]} ({country['code']})")
    print(f"version={version} due={'true' if due else 'false'}")
    if not args.send or not due:
        return 0
    if not args.no_wait and not args.dry_run and not wait_live(version):
        print(f"sillapps.com doesn't serve calendars {version} yet: nothing sent", file=sys.stderr)
        return 1
    for country, program, _ in due:
        name = fcm.send(message(country, program, version, args.prefix, now), dry_run=args.dry_run)
        print(f"sent to {args.prefix}{program['id']}: {name or '(validated)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
