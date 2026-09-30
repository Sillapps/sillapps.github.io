#!/usr/bin/env python3
"""The "Sciopero oggi" page of Scioperi Oggi: sillapps.com/scioperi/.

Rebuilt every hour by .github/workflows/scioperi-oggi.yml from the official
MIT strike list (RSS feed + "Note" column of the web table, as the app
does in lib/src/strikes/data of sillapps-strike-it). Writes
scioperi/index.html only; the workflow commits it when it changed, that is
when the list changes or the day changes in Rome.

Never a wrong "nessuno sciopero": if the list cannot be downloaded or read,
the page is left as it is. The page itself tells when it is from another
day (script at the bottom), and the workflow fails (one e-mail a day) when
the list has not been readable for more than a day and a half.

Run by hand: python3 scioperi/build_oggi.py [--rss FILE --notes FILE]
[--today YYYY-MM-DD]. Python 3.9+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

RSS_URL = "https://scioperi.mit.gov.it/mit2/public/scioperi/rss"
NOTES_URL = "https://scioperi.mit.gov.it/mit2/public/scioperi"
SOURCE_URL = "https://scioperi.mit.gov.it/mit2/public/scioperi"
# Set to the Play URL once the app is in production.
PLAY_URL: str | None = None
ROME = ZoneInfo("Europe/Rome")
OUT = Path(__file__).resolve().parent / "index.html"
STALE_AFTER = dt.timedelta(hours=36)

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
REGIONS = ["Abruzzo", "Basilicata", "Calabria", "Campania", "Emilia-Romagna", "Friuli-Venezia Giulia", "Lazio", "Liguria", "Lombardia", "Marche", "Molise", "Piemonte", "Puglia", "Sardegna", "Sicilia", "Toscana", "Trentino-Alto Adige", "Umbria", "Valle d'Aosta", "Veneto"]
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

# MIT "Settore" → what a traveller recognises (same groups as the app).
SECTORS = [
    ("ferroviario", "Treni"),
    ("appalti ferroviari", "Treni"),
    ("trasporto pubblico locale", "Bus, metro e tram"),
    ("aereo", "Aerei"),
    ("marittimo", "Traghetti e porti"),
    ("taxi", "Taxi"),
    ("noleggio con conducente", "NCC"),
    ("autostrade", "Autostrade"),
    ("stradale", "Autostrade"),
    ("generale", "Sciopero generale"),
    ("plurisettoriale", "Plurisettoriale"),
    ("merci", "Trasporto merci"),
    ("autotrasporto", "Trasporto merci"),
    ("elicotteri", "Elisoccorso"),
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if c.isascii() and c.isalnum())


def squeeze(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def parse_date(s: str | None) -> dt.date | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def fetch(url: str) -> str:
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sillapps.com scioperi page (contact@sillapps.com)"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - any network error means "no update"
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def parse_rss(xml: str) -> tuple[list[dict], dt.date | None]:
    """Strikes of the feed. Raises ValueError when it is not the feed."""
    root = ET.fromstring(xml)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS without channel")
    m = re.search(r"data:\s*([\d/]+)", channel.findtext("description") or "")
    list_date = parse_date(m.group(1)) if m else None
    items = channel.findall("item")
    out = []
    for item in items:
        title = squeeze(item.findtext("title") or "")
        fields: dict[str, str] = {}
        for line in re.split(r"<br\s*/?>", item.findtext("description") or "", flags=re.I):
            i = line.find(":")
            if i > 0:
                fields[norm(line[:i])] = squeeze(line[i + 1:])
        start = parse_date((re.search(r"Data inizio:\s*([\d/]+)", title, re.I) or [None, None])[1])
        if start is None:
            continue
        end = parse_date(fields.get("datafine")) or start
        guid = item.findtext("guid") or ""
        m = re.search(r"(\d+)\s*$", guid)
        out.append({
            "id": m.group(1) if m else f"{start}|{fields.get('settore', '')}|{fields.get('regione', '')}|{fields.get('categoriainteressata', '')}",
            "start": start,
            "end": max(end, start),
            "modality": fields.get("modalita", ""),
            "sector": fields.get("settore", ""),
            "relevance": fields.get("rilevanza", ""),
            "region": fields.get("regione", ""),
            "province": fields.get("provincia", ""),
            "unions": fields.get("sindacati", ""),
            "category": fields.get("categoriainteressata", ""),
            "notes": "",
        })
    # Unreadable items mean the format changed: no page rather than a wrong one.
    if items and len(out) * 2 <= len(items):
        raise ValueError(f"unreadable items: {len(items) - len(out)} of {len(items)}")
    return out, list_date


class _Table(HTMLParser):
    """Rows of <table id="scioperiLarge"><tbody>."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.in_body = False
        self.rows: list[list[str]] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.depth or dict(attrs).get("id") == "scioperiLarge":
                self.depth += 1
        elif self.depth == 1 and tag == "tbody":
            self.in_body = True
        elif self.depth == 1 and self.in_body and tag == "tr":
            self.rows.append([])
        elif self.depth == 1 and self.in_body and tag == "td" and self.rows:
            self.cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
        elif tag == "tbody":
            self.in_body = False
        elif tag == "td" and self.cell is not None:
            self.rows[-1].append(squeeze(" ".join(self.cell)))
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def note_key(start: dt.date, sector: str, category: str, unions: str, region: str) -> str:
    return f"{start}|{norm(sector)}|{norm(category)}|{norm(unions)}|{norm(region)}"


def parse_notes(page: str) -> dict[str, str]:
    t = _Table()
    t.feed(page)
    if not t.rows:
        raise ValueError("strike table not found")
    out = {}
    # "", Inizio, Fine, Sindacati, Settore, Categoria, Modalità, Rilevanza,
    # Note, Data proclamazione, Regione, Provincia, Data ricezione.
    for c in t.rows:
        if len(c) < 13:
            continue
        start = parse_date(c[1])
        if start and c[8]:
            out[note_key(start, c[4], c[5], c[3], c[10])] = c[8]
    return out


# Same rules as Strike.revoked / virtual / transportExcluded in the app.
def revoked(s: dict) -> bool:
    n = re.sub(r"\s+", " ", s["notes"].upper()).strip()
    if re.search(r"\b(DAL|DEL|PER|LIMITATAMENTE|PARZIAL)", n):
        return False
    return bool(re.match(r"^(SCIOPERO )?(REVOCATO|REVOCA|DIFFERITO|SOSPESO|ANNULLATO)\b", n))


def virtual(s: dict) -> bool:
    return "VIRTUALE" in f"{s['category']} {s['notes']}".upper()


def transport_excluded(s: dict) -> bool:
    n = s["notes"].upper()
    general = norm(s["sector"]) in ("generale", "plurisettoriale")
    return general and "ESCLUS" in n and all(w in n for w in ("FERROVIARIO", "AEREO")) and ("TRASPORTO PUBBLICO LOCALE" in n or re.search(r"\bTPL\b", n))


def status(s: dict) -> str | None:
    if revoked(s):
        return "Revocato o differito"
    if virtual(s):
        return "Sciopero virtuale: servizio regolare"
    if transport_excluded(s):
        return "Trasporti esclusi"
    return None


def sector_label(raw: str) -> str:
    n = raw.lower()
    for key, label in SECTORS:
        if key in n:
            return label
    return raw.strip().capitalize() or "Altro"


def where(s: dict) -> str:
    region = s["region"].strip()
    if not region or norm(region) == "italia":
        return "Tutta Italia" if norm(s["relevance"]) == "nazionale" else "Italia"
    province = s["province"].strip()
    return f"{region} ({province})" if province and norm(province) not in ("tutte", "") else region


def long_date(d: dt.date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def e(s: str) -> str:
    return html.escape(s, quote=True)


def card(s: dict) -> str:
    st = status(s)
    region = "" if norm(s["region"]) in ("", "italia") else norm(s["region"])
    days = "" if s["start"] == s["end"] else f'<p class="s-days">Dal {s["start"]:%d/%m} al {s["end"]:%d/%m}</p>'
    badge = f'<span class="s-badge">{e(st)}</span>' if st else ""
    notes = f'<p class="s-notes">Note: {e(s["notes"])}</p>' if s["notes"] else ""
    return (
        f'<li class="s{" s-off" if st else ""}" data-region="{e(region)}" data-on="{0 if st else 1}">'
        f'<p class="s-top"><span class="s-sector">{e(sector_label(s["sector"]))}</span> <span class="s-where">{e(where(s))}</span> {badge}</p>'
        f'<p class="s-cat">{e(s["category"])}</p>'
        f'<p class="s-hours">{e(s["modality"])}</p>{days}'
        f'<p class="s-unions">{e(s["unions"])}</p>{notes}</li>'
    )


def section(sid: str, title: str, strikes: list[dict], empty: str) -> str:
    items = "".join(card(s) for s in strikes)
    return (
        f'<section class="day" id="{sid}"><h2>{e(title)}</h2>'
        f'<ul class="list">{items}</ul><p class="empty"{"" if not strikes else " hidden"}>{e(empty)}</p></section>'
    )


def answer_text(n: int, when: str, place: str) -> str:
    if n == 0:
        return f"{when} nessuno sciopero dei trasporti in elenco {place}"
    return f"{when} {'1 sciopero' if n == 1 else f'{n} scioperi'} dei trasporti {place}"


def build(strikes: list[dict], list_date: dt.date | None, today: dt.date) -> str:
    tomorrow = today + dt.timedelta(days=1)
    week_end = today + dt.timedelta(days=7)
    strikes = sorted((s for s in strikes if s["end"] >= today), key=lambda s: (s["start"], sector_label(s["sector"]), where(s)))
    on = lambda d: [s for s in strikes if s["start"] <= d <= s["end"]]  # noqa: E731
    t, tm = on(today), on(tomorrow)
    week = [s for s in strikes if tomorrow < s["start"] <= week_end]
    later = [s for s in strikes if s["start"] > week_end]
    n_today = sum(1 for s in t if not status(s))
    n_tomorrow = sum(1 for s in tm if not status(s))
    # Every region, so nobody thinks theirs is missing; names as the MIT writes them.
    listed = {norm(s["region"]): s["region"].strip() for s in strikes if norm(s["region"]) not in ("", "italia")}
    regions = {norm(r): r for r in REGIONS} | listed
    options = "".join(f'<option value="{k}">{e(v)}</option>' for k, v in sorted(regions.items(), key=lambda kv: kv[0]))

    trains = [s for s in strikes if sector_label(s["sector"]) == "Treni" and not status(s) and s["start"] >= today]
    national_trains = [s for s in trains if norm(s["relevance"]) == "nazionale"]
    next_train = (national_trains or trains or [None])[0]
    if next_train:
        train_answer = f"Il prossimo sciopero {'nazionale ' if national_trains else ''}dei treni in elenco è {long_date(next_train['start'])} ({next_train['modality'].lower()}), {where(next_train)}: {next_train['category']}."
    else:
        train_answer = "Al momento nell'elenco ufficiale non ci sono scioperi dei treni in programma."
    next_general = next((s for s in strikes if norm(s["sector"]) == "generale" and not status(s)), None)
    general_answer = (
        f"Il prossimo sciopero generale in elenco è {long_date(next_general['start'])}: {next_general['modality'].lower()}. Controlla nelle note quali settori sono esclusi."
        if next_general else "Al momento nell'elenco ufficiale non ci sono scioperi generali in programma."
    )
    faq = [
        ("C'è sciopero oggi?", f"{answer_text(n_today, 'Oggi, ' + long_date(today) + ',', 'in Italia')}, secondo l'elenco ufficiale del Ministero delle Infrastrutture e dei Trasporti."),
        ("C'è sciopero domani?", f"{answer_text(n_tomorrow, 'Domani, ' + long_date(tomorrow) + ',', 'in Italia')}."),
        ("Quando è il prossimo sciopero dei treni?", train_answer),
        ("Quando è il prossimo sciopero generale?", general_answer),
        ("Cosa sono le fasce di garanzia?", "Sono le ore in cui i servizi minimi sono garantiti anche durante lo sciopero. Per i treni regionali nei giorni feriali: dalle 6 alle 9 e dalle 18 alle 21. Per bus, metro e tram dipendono dall'azienda locale."),
        ("Da dove vengono i dati?", "Dall'elenco pubblico degli scioperi dell'Osservatorio del Ministero delle Infrastrutture e dei Trasporti (scioperi.mit.gov.it), letto ogni ora. Questa pagina e l'app Scioperi Oggi non sono ufficiali e non sono affiliate al Ministero."),
    ]
    faq_html = "".join(f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in faq)
    ld = [
        {
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq],
        },
        {
            "@context": "https://schema.org", "@type": "MobileApplication", "name": "Scioperi Oggi",
            "operatingSystem": "ANDROID", "applicationCategory": "TravelApplication", "inLanguage": "it",
            "url": "https://sillapps.com/scioperi/", "image": "https://sillapps.com/scioperi/icon-192.png",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            "publisher": {"@type": "Organization", "name": "Sillapps", "url": "https://sillapps.com/"},
            **({"installUrl": PLAY_URL} if PLAY_URL else {}),
        },
    ]
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    cta = (
        f'<a class="play" href="{e(PLAY_URL)}">Scarica Scioperi Oggi su Google Play</a>'
        if PLAY_URL else '<p class="soon">L\'app Android <strong>Scioperi Oggi</strong> arriva presto su Google Play.</p>'
    )
    list_line = f"Elenco ufficiale aggiornato al {list_date:%d/%m/%Y}" if list_date else "Elenco ufficiale"
    stale_list = list_date is not None and (today - list_date).days > 2
    stale_html = f'<p class="warn">L\'elenco ufficiale non risulta aggiornato dal {list_date:%d/%m/%Y}: controlla anche il sito del Ministero.</p>' if stale_list else ""
    desc = f"{answer_text(n_today, 'Oggi', 'in Italia')}. Scioperi di treni, bus, metro, aerei e traghetti oggi, domani e nei prossimi giorni, dall'elenco ufficiale del MIT."
    title = f"Sciopero oggi e domani: treni, bus, aerei · {today.day} {MONTHS[today.month - 1]} {today.year}"
    answer_class = "yes" if n_today else "no"
    return f"""<!doctype html>
<html lang="it" data-app="scioperi">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#0b0f17" />
    <title>{e(title)}</title>
    <meta name="description" content="{e(desc)}" />
    <link rel="canonical" href="https://sillapps.com/scioperi/" />
    <link rel="icon" type="image/png" href="/scioperi/icon-192.png" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Sillapps" />
    <meta property="og:locale" content="it_IT" />
    <meta property="og:title" content="{e(title)}" />
    <meta property="og:description" content="{e(desc)}" />
    <meta property="og:url" content="https://sillapps.com/scioperi/" />
    <meta property="og:image" content="https://sillapps.com/scioperi/og.png" />
    <meta name="twitter:card" content="summary_large_image" />
    {ld_html}
    <link rel="stylesheet" href="/fonts/fonts.css?v=20260930-1" />
    <style>
      :root {{ --bg: #0b0f17; --card: #171e2c; --card-high: #212a3b; --ink: #f3f5f9; --soft: #a9b3c6; --line: rgba(255,255,255,.12); --strike: #ff5a5f; --clear: #2fd27e; --caution: #ffb020; --accent: #4da3ff; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; border-top: 4px solid; border-image: linear-gradient(90deg, #ff5a5f, #ffb020 50%, #2fd27e) 1; background: radial-gradient(circle at 92% -6%, rgba(255,90,95,.18), transparent 38%) no-repeat, radial-gradient(circle at 0% 0%, rgba(77,163,255,.1), transparent 40%) no-repeat, var(--bg); color: var(--ink); font: 16px/1.5 "Manrope", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
      main {{ max-width: 760px; margin: 0 auto; padding: 16px 16px 48px; }}
      a {{ color: var(--accent); }}
      header {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }}
      .brand img {{ width: 40px; height: 40px; border-radius: 10px; }}
      .home {{ display: inline-flex; align-items: center; gap: 8px; min-height: 40px; padding: 6px 14px; border: 1px solid var(--line); border-radius: 999px; color: var(--ink); font-weight: 650; font-size: .92rem; text-decoration: none; }}
      .home img {{ width: 18px; height: 18px; border-radius: 5px; }}
      .brand {{ display: flex; align-items: center; gap: 10px; font-family: "Space Grotesk", "Manrope", sans-serif; font-size: 1.1rem; font-weight: 700; letter-spacing: -.02em; text-decoration: none; color: var(--ink); }}
      h1 {{ font-size: 1.15rem; color: var(--soft); font-weight: 600; margin: 8px 0; }}
      .answer {{ font-family: "Space Grotesk", "Manrope", sans-serif; font-size: clamp(1.7rem, 6.4vw, 2.6rem); line-height: 1.08; letter-spacing: -.03em; font-weight: 700; margin: 4px 0 8px; overflow-wrap: anywhere; }}
      .answer.yes {{ color: var(--strike); }} .answer.no {{ color: var(--clear); }}
      .meta {{ color: var(--soft); font-size: .9rem; margin: 0 0 12px; }}
      .warn {{ background: rgba(255,176,32,.14); border: 1px solid var(--caution); color: var(--ink); border-radius: 12px; padding: 10px 12px; }}
      label {{ display: block; color: var(--soft); font-size: .9rem; margin: 16px 0 4px; }}
      select {{ width: 100%; min-height: 48px; font: inherit; color: var(--ink); background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 8px 12px; }}
      h2 {{ font-family: "Space Grotesk", "Manrope", sans-serif; font-size: 1.25rem; letter-spacing: -.01em; margin: 28px 0 8px; }}
      .list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
      .s {{ background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--strike); border-radius: 14px; padding: 12px 14px; }}
      .s-off {{ border-left-color: var(--soft); opacity: .8; }}
      .s p {{ margin: 2px 0; overflow-wrap: anywhere; }}
      .s-top {{ display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; }}
      .s-sector {{ font-weight: 800; }} .s-where {{ color: var(--soft); }}
      .s-badge {{ background: var(--card-high); border-radius: 8px; padding: 0 8px; font-size: .85rem; }}
      .s-hours {{ font-weight: 600; }} .s-unions, .s-notes, .s-days {{ color: var(--soft); font-size: .9rem; }}
      .empty {{ color: var(--soft); }}
      .cta {{ background: var(--card); border-radius: 16px; padding: 16px; margin-top: 32px; }}
      .cta p {{ margin: 4px 0; }}
      .play {{ display: inline-block; min-height: 48px; padding: 12px 18px; background: var(--accent); color: #06121f; font-weight: 800; border-radius: 12px; text-decoration: none; }}
      details {{ background: var(--card); border-radius: 12px; padding: 10px 14px; margin: 8px 0; }}
      summary {{ cursor: pointer; font-weight: 700; min-height: 28px; }}
      footer {{ color: var(--soft); font-size: .85rem; margin-top: 32px; }}
      footer a {{ display: inline-block; padding: 12px 8px 12px 0; }}
    </style>
  </head>
  <body>
    <main data-day="{today.isoformat()}">
      <header>
        <a class="brand" href="/scioperi/"><img src="/scioperi/icon-192.png" alt="" width="40" height="40" /> Scioperi Oggi</a>
        <a class="home" href="/"><img src="/brand/favicon.svg" alt="" width="18" height="18" /> Sillapps</a>
      </header>
      <p class="warn" id="old" hidden>Questa pagina è di {e(long_date(today))}: l'aggiornamento è in corso. Nel frattempo controlla il <a href="{SOURCE_URL}">sito del Ministero</a>.</p>
      {stale_html}
      <h1>Sciopero oggi, {e(long_date(today))} {today.year}</h1>
      <p class="answer {answer_class}" id="answer" data-n="{n_today}">{e(answer_text(n_today, "Oggi", "in Italia"))}</p>
      <p class="meta">{e(list_line)} · fonte: <a href="{SOURCE_URL}">scioperi.mit.gov.it</a> · pagina non ufficiale, non affiliata al Ministero</p>
      <label for="region">La tua regione (gli scioperi nazionali restano sempre visibili)</label>
      <select id="region"><option value="">Tutta Italia</option>{options}</select>
      {section("oggi", "Oggi, " + long_date(today), t, "Nessuno sciopero in elenco per oggi.")}
      {section("domani", "Domani, " + long_date(tomorrow), tm, "Nessuno sciopero in elenco per domani.")}
      {section("settimana", "Nei prossimi giorni", week, "Nessuno sciopero in elenco nei prossimi 7 giorni.")}
      {section("dopo", "Più avanti", later, "Nessun altro sciopero in elenco.")}
      <section class="cta">
        {cta}
        <p>L'app dice subito se c'è sciopero oggi o domani nella tua regione, con gli orari e le fasce di garanzia. Con Pro: avviso la sera prima e widget.</p>
      </section>
      <h2>Domande frequenti</h2>
      {faq_html}
      <footer>
        Dati: elenco degli scioperi del Ministero delle Infrastrutture e dei Trasporti, riportati senza modifiche. Gli orari e l'adesione possono cambiare: in caso di dubbio fa fede l'azienda di trasporto.
        <br /><a href="privacy.html">Privacy</a> <a href="/legal.html">Note legali</a> <a href="mailto:contact@sillapps.com">contact@sillapps.com</a>
      </footer>
    </main>
    <script>
      (function () {{
        var main = document.querySelector("main");
        try {{
          var p = {{}};
          new Intl.DateTimeFormat("en-CA", {{ timeZone: "Europe/Rome", year: "numeric", month: "2-digit", day: "2-digit" }})
            .formatToParts(new Date()).forEach(function (x) {{ p[x.type] = x.value; }});
          if (p.year + "-" + p.month + "-" + p.day !== main.getAttribute("data-day")) document.getElementById("old").hidden = false;
        }} catch (err) {{}}
        var select = document.getElementById("region"), answer = document.getElementById("answer");
        var names = {{}};
        Array.prototype.forEach.call(select.options, function (o) {{ names[o.value] = o.text; }});
        function apply() {{
          var r = select.value;
          document.querySelectorAll("section.day").forEach(function (sec) {{
            var shown = 0;
            sec.querySelectorAll("li.s").forEach(function (li) {{
              var ok = !r || !li.getAttribute("data-region") || li.getAttribute("data-region") === r;
              li.hidden = !ok;
              if (ok) shown++;
            }});
            sec.querySelector(".empty").hidden = shown > 0;
          }});
          var n = 0;
          document.querySelectorAll("#oggi li.s").forEach(function (li) {{ if (!li.hidden && li.getAttribute("data-on") === "1") n++; }});
          var place = r ? "in " + names[r] : "in Italia";
          answer.textContent = n === 0 ? "Oggi nessuno sciopero dei trasporti in elenco " + place : "Oggi " + (n === 1 ? "1 sciopero" : n + " scioperi") + " dei trasporti " + place;
          answer.className = "answer " + (n ? "yes" : "no");
        }}
        select.addEventListener("change", apply);
      }})();
    </script>
  </body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rss")
    ap.add_argument("--notes")
    ap.add_argument("--today")
    a = ap.parse_args()
    now = dt.datetime.now(ROME)
    today = dt.date.fromisoformat(a.today) if a.today else now.date()
    try:
        rss = Path(a.rss).read_text() if a.rss else fetch(RSS_URL)
        page = Path(a.notes).read_text() if a.notes else fetch(NOTES_URL)
        strikes, list_date = parse_rss(rss)
        notes = parse_notes(page)
    except Exception as err:  # noqa: BLE001
        print(f"[scioperi] list not readable, page left as it is: {err}", file=sys.stderr)
        m = re.search(r'data-day="(\d{4}-\d{2}-\d{2})"', OUT.read_text()) if OUT.exists() else None
        built = dt.datetime.combine(dt.date.fromisoformat(m.group(1)), dt.time(), ROME) if m else None
        # Fail (GitHub e-mails the owner) once a day when it lasts.
        if (built is None or now - built > STALE_AFTER) and now.hour == 9:
            return 1
        return 0
    for s in strikes:
        s["notes"] = notes.get(note_key(s["start"], s["sector"], s["category"], s["unions"], s["region"]), "")
    out = build(strikes, list_date, today)
    if OUT.exists() and OUT.read_text() == out:
        print("[scioperi] unchanged")
    else:
        OUT.write_text(out)
        print(f"[scioperi] written: {len(strikes)} strikes, list of {list_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
