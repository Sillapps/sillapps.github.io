#!/usr/bin/env python3
"""Placa Hoy: environmental contingency push (Mexico City and Edomex).

The CAMe announces a contingency (Fase I or II) on aire.cdmx.gob.mx with a
communiqué, from the afternoon until about 20:00, and it restricts from 5:00
the next day; while it lasts, a new communiqué keeps it ("se mantiene") each
evening. The workflow .github/workflows/push-placa-hoy.yml runs this every
10 minutes from 10:00 to 22:30 Mexico City time; each new communiqué is sent
once to the topic (the workflow remembers it with a cache key). A lifting
("se suspende") sends nothing, like the app.

The message is the same for everyone (the topic says nothing about the user):
  - Android receives data only (high priority). The app wakes up, reads the
    page itself and shows its usual alert, one line per vehicle ("Mi auto: No
    circula"), once per communiqué. Its background checks stay as a fallback.
  - iOS shows the alert below; the app's notification service extension
    (ios/PlacaAlert) writes the vehicles' answers for that day into it.

The app subscribes to the topic only while its alerts are on (Pro) with a
vehicle in the Mexico City area; debug builds use the test topic. App side:
lib/src/push/ in sillapps-circula-latam. The page reading is the Python twin
of lib/src/contingency/aire_parser.dart there (checked against the same saved
pages by tool/test_push_parser.sh).

    python3 push/placa_hoy.py --check           # prints due=true|false key=...
    python3 push/placa_hoy.py --send [--topic placahoy-test] [--dry-run] [--force]
    python3 push/placa_hoy.py --parse page.html # what the page says (tests)

Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import fcm  # noqa: E402

PAGE = "https://aire.cdmx.gob.mx/default.php"
BASE = "https://aire.cdmx.gob.mx/"
# Mexico City: UTC-6 all year since daylight saving ended in 2022.
MEXICO = timezone(timedelta(hours=-6))
FIRST = (10, 0)
LAST = (22, 30)
TOPIC = "placahoy-contingency"
# Same words as the app (lib/l10n/app_es.arb: notifContingencyTitle,
# contingencyPhaseUnknown, notifContingencyBody).
TITLE = "Contingencia ambiental · {phase}"
PHASE_UNKNOWN = "fase por confirmar"
BODY = "Mañana, de 5:00 a 22:00. Consulta el comunicado en Placa Hoy."
UA = {"User-Agent": "Mozilla/5.0 (compatible; PlacaHoy-push/1.0; +https://sillapps.com/placa-hoy/)"}

NOTE = re.compile(r"contingencias/notas/[^\"'\s>]+\.pdf", re.I)
BANNER = re.compile(r"contingencias/banners/(FASE ?(?:1|2|I{1,2}))/[^\"'\s>]*?(ACTIVA|MANTIENE|CONTINUA|SUSPEN)[^\"'\s>]*", re.I)
CONTINUING = re.compile(r"(SE MANTIENE|CONTIN(U|Ú|&UACUTE;)A) LA (FASE|CONTINGENCIA)", re.I)
ENDING = re.compile(r"SE SUSPENDE LA (FASE|CONTINGENCIA)", re.I)


class _Box(HTMLParser):
    """Links inside div#HNC-HNCS-VV, and the holograma 1 Saturday."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = False
        self.depth = 0
        self.links: list[str] = []
        self._sat = False
        self.saturday = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.depth:
            if tag == "div":
                self.depth += 1
            if tag == "a" and a.get("href"):
                self.links.append(a["href"])
        elif tag == "div" and a.get("id") == "HNC-HNCS-VV":
            self.found = True
            self.depth = 1
        if a.get("id") == "colorhncsH1":
            self._sat = True

    def handle_endtag(self, tag):
        if tag == "div":
            if self.depth:
                self.depth -= 1
            self._sat = False

    def handle_data(self, data):
        if self._sat:
            self.saturday += data


def _absolute(href: str) -> str:
    if href.startswith("http"):
        return href.replace("https://www.", "https://", 1).replace("http://www.", "http://", 1)
    return BASE + re.sub(r"^\.?/", "", href)


def _phase(raw: str) -> str:
    r = raw.upper().replace(" ", "")
    return "FASE II" if r.endswith("2") or r.endswith("II") else "FASE I"


def parse(page: str) -> dict:
    """What the page says. Raises ValueError when it doesn't look like the
    expected page, so a redesign never reads as "no contingency"."""
    box = _Box()
    box.feed(page)
    if not box.found:
        raise ValueError("HNC box not found")
    communique = next((_absolute(h) for h in box.links if NOTE.search(h)), None)
    banner = BANNER.search(page)
    kind = banner.group(2).upper() if banner else None
    ending = kind == "SUSPEN" or bool(ENDING.search(page))
    if communique is None and banner is not None:
        m = NOTE.search(page)
        communique = _absolute(m.group(0)) if m else None
    saturday = box.saturday.strip()
    return {
        "active": communique is not None or banner is not None or ending,
        "continuing": kind in ("MANTIENE", "CONTINUA") or bool(CONTINUING.search(page)),
        "ending": ending,
        "communique": communique,
        "phase": _phase(banner.group(1)) if banner else None,
        "saturday_h1": saturday or None,
    }


def _tls() -> ssl.SSLContext:
    """The site's server offers a 1024-bit Diffie-Hellman key, which OpenSSL 3
    refuses by default (DH_KEY_TOO_SMALL on the Actions runners). Lower the
    security level for this one page; the certificate is still verified."""
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    return ctx


def fetch() -> str:
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(PAGE, headers=UA), timeout=30, context=_tls()) as r:
                # Served as ISO-8859-1 (the page says windows-1252); markers are ASCII.
                return r.read().decode("latin-1")
        except OSError as e:
            if attempt == 2:
                raise
            print(f"page unreachable, retrying: {e}", file=sys.stderr)
            time.sleep(10)
    raise AssertionError


def key(reading: dict, now: datetime) -> str:
    """One per communiqué (a new one each evening while it is kept); a banner
    without a communiqué counts once a day."""
    if reading["communique"]:
        name = reading["communique"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    else:
        name = f"{(reading['phase'] or 'fase').replace(' ', '')}-{now:%Y%m%d}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", name)[:80]


def message(reading: dict, topic: str, now: datetime, day: date) -> dict:
    # The restriction ends at 22:00 the next day: past that, the push is moot.
    end = datetime(day.year, day.month, day.day, 22, tzinfo=MEXICO)
    ttl = max(60, int((end - now).total_seconds()))
    phase = reading["phase"] or ""
    return {
        "topic": topic,
        "data": {"kind": "contingency", "day": day.isoformat(), "phase": phase, "key": key(reading, now)},
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
                    "alert": {"title": TITLE.format(phase=phase or PHASE_UNKNOWN), "body": BODY},
                    "sound": "default",
                    "thread-id": "contingency",
                    "mutable-content": 1,
                    "content-available": 1,
                },
            },
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print due=true and the communiqué key when a contingency is announced")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--parse", metavar="FILE", help="print what a saved page says (ISO-8859-1)")
    ap.add_argument("--topic", default=TOPIC)
    ap.add_argument("--dry-run", action="store_true", help="FCM validates without sending")
    ap.add_argument("--force", action="store_true", help="send a Fase I test message whatever the page says")
    args = ap.parse_args()

    if args.parse:
        with open(args.parse, "rb") as f:
            print(json.dumps(parse(f.read().decode("latin-1")), sort_keys=True))
        return 0

    now = datetime.now(MEXICO)
    day = now.date() + timedelta(days=1)
    in_window = FIRST <= (now.hour, now.minute) <= LAST
    if args.force:
        reading = {"active": True, "continuing": False, "ending": False, "communique": None, "phase": "FASE I"}
    elif not in_window:
        print(f"mexico={now:%Y-%m-%d %H:%M} outside {FIRST[0]}:00-{LAST[0]}:{LAST[1]:02d} due=false")
        return 0
    else:
        try:
            reading = parse(fetch())
        except (OSError, ValueError) as e:
            # Never a push on a doubt; the apps keep checking the page themselves.
            print(f"page not read: {e} due=false", file=sys.stderr)
            print("due=false")
            return 0
    due = reading["active"] and not reading["ending"]
    print(f"mexico={now:%Y-%m-%d %H:%M} day={day} active={str(reading['active']).lower()} "
          f"ending={str(reading['ending']).lower()} phase={reading['phase'] or '-'} due={str(due).lower()} key={key(reading, now)}")
    if args.send:
        if not due:
            print("not due: nothing sent")
            return 0
        name = fcm.send(message(reading, args.topic, now, day), dry_run=args.dry_run)
        print(f"sent to {args.topic}: {name or '(validated)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
