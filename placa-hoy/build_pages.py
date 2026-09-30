#!/usr/bin/env python3
"""Static city pages of Placa Hoy on sillapps.com, generated from rules-v2.json.

One page per city (never one page per date), in Spanish:
    placa-hoy/<slug>/index.html   e.g. placa-hoy/pico-y-placa-medellin/

Each page explains the rule as published in rules.json: restricted digits
per weekday, hours, Saturdays, exemptions, motorcycles, validity, decree,
official source and last verification date. It never computes an answer
for "today" and never shows a dated calendar: that is the app's job (its
engine lives in lib/src/rules/domain/engine.dart of sillapps-circula-latam),
and a second implementation here could give a wrong answer.

The script also rewrites two generated blocks, between the markers
"placa-hoy:cities:start" and "placa-hoy:cities:end":
    - the city list in placa-hoy/index.html,
    - the city URLs in sitemap.xml.
Everything outside these markers is hand-written and left untouched.

The source is placa-hoy/rules-v2.json (schema 2, every city, periods may
have `zones`); placa-hoy/rules.json is the schema-1 copy for older app
versions, without the cities that have zones, and is only a fallback here.

HOW TO RERUN (after every update of placa-hoy/rules-v2.json):
    1. Publish the new rules with tool/publish_rules.sh in the app
       repository (it writes rules-v2.json and rules.json here).
    2. From the root of the site repository:
           python3 placa-hoy/build_pages.py
       (Python 3.9+, standard library only.)
    3. Review the diff (git diff), open one or two pages, commit
       rules.json and the regenerated pages together, then push.
Rerun it also from time to time even without new rules: periods, notices
and overrides that have already ended are left out (relative to the
generation date, see --today), so pages stay current.

Options:
    --today YYYY-MM-DD   generation date (default: today); only affects
                         which ended periods/notices are hidden and the
                         year in titles.
    --check              exit with status 1 if a file would change
                         (nothing is written).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent  # placa-hoy/
SITE = HERE.parent  # site root
BASE_URL = "https://sillapps.com"
APP_URL = f"{BASE_URL}/placa-hoy/"
PLAY_URL = "https://play.google.com/store/apps/details?id=com.sillapps.placahoy"
PLAY_BADGE = "/brand/badges/google-play-es-419.png"
CSS = "/styles.css?v=20260930-3"
FONTS_CSS = "/fonts/fonts.css?v=20260930-1"
START = "placa-hoy:cities:start"
END = "placa-hoy:cities:end"

WARNING = (
    "Fuera de la vigencia indicada, o si hay un cambio anunciado, Placa Hoy "
    "muestra SIN CONFIRMAR: consulta siempre la fuente oficial."
)

# URL slugs and short names used in titles, when the default is not right.
SLUGS = {"cdmx": "hoy-no-circula-cdmx", "edomex-zmvm": "hoy-no-circula-edomex"}
SHORT_NAMES = {"cdmx": "CDMX", "edomex-zmvm": "Estado de México"}
OG_LOCALES = {"CO": "es_CO", "MX": "es_MX", "EC": "es_EC"}

WEEKDAYS = {1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves", 5: "Viernes", 6: "Sábado", 7: "Domingo"}
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]
FUELS = {"electric": "eléctricos", "hybrid": "híbridos", "gas": "a gas"}
ORDINALS = ["1.er", "2.º", "3.er", "4.º", "5.º"]
HOLIDAY_WORDS = {"CO": "festivos", "EC": "feriados"}

PAGE_CSS = """
      .ph-table td.ph-d { color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }
      .ph-table td.ph-free { color: var(--free); }
      .ph-src { font-size: 0.92rem; }
      .nw { white-space: nowrap; }
      .ph-tag { display: inline-block; margin-left: 8px; padding: 0 8px; border-radius: 999px; font-size: 0.72rem;
        font-weight: 800; letter-spacing: 0.06em; vertical-align: middle; color: var(--accent-ink); background: var(--accent); }
      .ph-cities { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
      .section .ph-cities { max-width: none; padding-left: 0; }
      .ph-cities a { display: inline-block; padding: 5px 12px; border: 1px solid var(--line-strong); border-radius: 999px;
        font-size: 0.9rem; color: var(--text); text-decoration: none; }
      .ph-cities a:hover, .ph-cities a:focus-visible { border-color: var(--accent); }
"""


# ---------------------------------------------------------------- helpers

def e(text) -> str:
    return html.escape(str(text), quote=True)


def keep_ranges(escaped: str) -> str:
    """Keeps each time range (6:00–19:00) on one line in narrow tables."""
    return re.sub(r"\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2}", lambda m: f'<span class="nw">{m.group(0)}</span>', escaped)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def day(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


def fmt_date(iso: str) -> str:
    d = day(iso)
    return f"{d.day} de {MONTHS[d.month - 1]} de {d.year}"


def fmt_time(hhmm: str) -> str:
    h, m = hhmm.split(":")
    return f"{int(h)}:{m}"


def join_es(items: list[str]) -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def fmt_windows(windows) -> str:
    return join_es([f"{fmt_time(a)}–{fmt_time(b)}" for a, b in windows or []])


def fmt_digits(digits) -> str:
    return join_es([str(d) for d in digits])


def city_slug(city: dict, country: dict) -> str:
    return SLUGS.get(city["id"]) or f"{slugify(country['scheme'])}-{slugify(city['id'])}"


def scheme_title(country: dict) -> str:
    s = country["scheme"]
    return s[0].upper() + s[1:]


def kinds_label(kinds: list[str], country_id: str) -> str:
    car = "autos particulares" if country_id == "MX" else "carros particulares"
    labels = [car if k == "car" else "motos" for k in sorted(kinds)]
    text = join_es(labels)
    return text[0].upper() + text[1:]


def holidays_free(period: dict, country: dict) -> bool:
    return period.get("holidays", "free") == "free" and country.get("holidays") != "none"


# ---------------------------------------------------------------- periods

def rotation_table(period: dict, country: dict) -> str:
    """Weekday → restricted digits and hours, straight from the period data."""
    ptype = period["type"]
    digit = "primer" if period.get("digit") == "first" else "último"
    days = {int(k): v for k, v in (period.get("days") or {}).items()}
    hours = period.get("hours") or []
    nonlocal_hours = period.get("hours_nonlocal") or []
    sat = period.get("saturday")

    def hours_text() -> str:
        if nonlocal_hours:
            return f"Placas locales: {fmt_windows(hours)}. Otras placas: {fmt_windows(nonlocal_hours)}"
        return fmt_windows(hours)

    rows = []
    if ptype == "parity":
        weekdays = period.get("weekdays") or []
        for wd in range(1, 8):
            if wd in weekdays:
                rows.append((WEEKDAYS[wd],
                             f"Día impar: {fmt_digits(period['odd'])} · Día par: {fmt_digits(period['even'])}",
                             hours_text(), False))
            else:
                rows.append((WEEKDAYS[wd], "Sin pico y placa", "", True))
        head = f"No circulan placas terminadas en ({digit} dígito)"
    elif ptype == "hnc":
        for wd in range(1, 6):
            if wd in days:
                rows.append((WEEKDAYS[wd], fmt_digits(days[wd]), fmt_windows(hours), False))
            else:
                rows.append((WEEKDAYS[wd], "Circulan todos", "", True))
        groups = period.get("saturday_h1") or []
        parts, seen = [], []
        for i, g in enumerate(groups):
            if g in seen:
                continue
            seen.append(g)
            idx = [j for j, h in enumerate(groups) if h == g]
            which = join_es([ORDINALS[j] if j < len(ORDINALS) else f"{j + 1}.º" for j in idx])
            label = f"{which} sábado del mes"
            parts.append(f"{label}: circulan todos" if not g else f"{label}: no circulan {fmt_digits(g)}")
        sat_text = "Holograma 1: " + "; ".join(parts) + ". Holograma 2 y sin holograma: no circulan ningún sábado."
        rows.append((WEEKDAYS[6], sat_text, fmt_windows(hours), False))
        rows.append((WEEKDAYS[7], "Circulan todos", "", True))
        head = "No circulan placas terminadas en (holograma 1, 2 o sin holograma)"
    else:  # weekday
        for wd in range(1, 8):
            if wd == 6 and sat:
                order = " → ".join(fmt_digits(g) for g in sat["groups"])
                rows.append((WEEKDAYS[6], f"Un par de dígitos que rota cada semana: {order} (Placa Hoy te dice cuál toca)",
                             fmt_windows(sat.get("hours")), False))
            elif wd in days:
                rows.append((WEEKDAYS[wd], fmt_digits(days[wd]), hours_text(), False))
            else:
                rows.append((WEEKDAYS[wd], "Sin pico y placa", "", True))
        head = f"No circulan placas con {digit} dígito"

    body = "\n".join(
        f"<tr><td>{e(d)}</td><td class=\"{'ph-free' if free else 'ph-d'}\">{e(what)}</td><td>{keep_ranges(e(h))}</td></tr>"
        for d, what, h, free in rows
    )
    return (
        '<table class="data-table ph-table">\n'
        f'<thead><tr><th scope="col">Día</th><th scope="col">{e(head)}</th><th scope="col">Horario</th></tr></thead>\n'
        f"<tbody>\n{body}\n</tbody>\n</table>"
    )


def period_section(period: dict, city: dict, country: dict) -> str:
    kinds = kinds_label(period["kinds"], country["id"])
    out = [
        f'<section class="section" id="{e(period["id"])}">',
        f"<h2>{e(kinds)}: del {e(fmt_date(period['valid_from']))} al {e(fmt_date(period['valid_to']))}</h2>",
        f"<p>{e(period.get('summary', ''))}</p>",
    ]
    if period["type"] != "none":
        out.append(rotation_table(period, country))
        if period.get("digit") == "first":
            out.append("<p>Ojo: en las motos cuenta el <strong>primer</strong> dígito numérico de la placa, no el último.</p>")
        if period.get("hours_nonlocal") and period.get("local_plate_label"):
            label = period["local_plate_label"]
            out.append(f"<p>Placas locales: {e(label[0].lower() + label[1:])}.</p>")
        if period["type"] == "hnc":
            if period.get("exempt_hologramas"):
                labels = [h if h == "exento" else f"holograma {h}" for h in period["exempt_hologramas"]]
                text = join_es(labels)
                out.append(f"<p><strong>Circulan todos los días:</strong> {e(text)} "
                           "(en contingencia ambiental, ver las notas).</p>")
            if period.get("foreign_hours"):
                out.append(f"<p><strong>Foráneos:</strong> además del día de su engomado y de los sábados, "
                           f"no circulan de lunes a viernes de {e(join_es([f'{fmt_time(a)} a {fmt_time(b)}' for a, b in period['foreign_hours']]))} "
                           f"(ver las notas).</p>")
            if period.get("holidays") == "apply":
                out.append("<p><strong>Festivos:</strong> el programa aplica también en días festivos.</p>")
        elif holidays_free(period, country):
            word = HOLIDAY_WORDS.get(country["id"], "festivos")
            out.append(f"<p><strong>{word.capitalize()}:</strong> no hay pico y placa en los {word} oficiales.</p>")
    if period.get("exempt_fuels"):
        fuels = join_es([FUELS.get(f, f) for f in period["exempt_fuels"]])
        out.append(f"<p><strong>Exentos por combustible:</strong> vehículos {e(fuels)}.</p>")
    if period.get("zone"):
        out.append(f"<p><strong>Dónde aplica:</strong> {e(period['zone'])}</p>")
    for zone in period.get("zones") or []:
        out.append(zone_section(zone, period, country))
    if period.get("notes"):
        out.append("<ul>" + "".join(f"<li>{e(n)}</li>" for n in period["notes"]) + "</ul>")
    out.append(
        f'<p class="ph-src"><strong>Norma:</strong> {e(period["decree"])}.<br />'
        f'<strong>Vigencia:</strong> del {e(fmt_date(period["valid_from"]))} al {e(fmt_date(period["valid_to"]))}.<br />'
        f'<strong>Fuente oficial:</strong> <a href="{e(period["source_url"])}" rel="noopener">{e(source_label(period["source_url"]))}</a><br />'
        f'<strong>Verificado por Placa Hoy el</strong> {e(fmt_date(period["last_verified"]))}.</p>'
    )
    out.append("</section>")
    return "\n".join(out)


def zone_section(zone: dict, period: dict, country: dict) -> str:
    """A zone of the period (schema 2): its own digits and hours, same validity.

    Inside the zone the city-wide rule still applies and the zone adds to it
    (the app's engine takes the union), so the page says so."""
    name = zone["name"]
    table = rotation_table({"type": "weekday", "days": zone.get("days"), "hours": zone.get("hours"),
                            "digit": period.get("digit")}, country)
    return "\n".join([
        f"<h3>En {e(name)}</h3>",
        f"<p><strong>Zona:</strong> {e(zone['area'][0].upper() + zone['area'][1:])}. "
        "Dentro de esta zona también aplica la regla general de arriba: se suman las dos.</p>",
        table,
    ])


def source_label(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    return host.removeprefix("www.")


def parity_explainer(period: dict, city: dict, country: dict) -> str:
    weekdays = period.get("weekdays") or []
    days_text = join_es([WEEKDAYS[w].lower() for w in weekdays])
    never = [WEEKDAYS[w].lower() + "s" for w in (6, 7) if w not in weekdays]
    never = ["los " + n for n in never + (["festivos"] if holidays_free(period, country) else [])]
    never_text = ", ".join(never[:-1]) + " ni " + never[-1] if len(never) > 1 else "".join(never)
    odd, even = fmt_digits(period["odd"]), fmt_digits(period["even"])
    return "\n".join([
        f'<section class="section" id="pares-impares">',
        f"<h2>¿Cómo funciona el pico y placa por fechas pares e impares en {e(city['name'])}?</h2>",
        f"<p>En {e(city['name'])} la restricción no depende del día de la semana, sino del "
        f"<strong>número del día del mes</strong>:</p>",
        "<ul>",
        f"<li>En <strong>fechas impares</strong> (1, 3, 5… 29, 31) no circulan las placas terminadas en {e(odd)}.</li>",
        f"<li>En <strong>fechas pares</strong> (2, 4, 6… 28, 30) no circulan las placas terminadas en {e(even)}.</li>",
        "</ul>",
        f"<p>Por ejemplo, el día 15 de cualquier mes es impar y el día 16 es par, sea cual sea el día de la semana. "
        f"Cuando un mes tiene 31 días, el 31 y el 1 del mes siguiente son dos fechas impares seguidas.</p>",
        f"<p>La medida solo se aplica los {e(days_text)}, en el horario {e(fmt_windows(period.get('hours')))}"
        + (f"; nunca {e(never_text)}." if never_text else ".") + "</p>",
        "<p>Placa Hoy hace la cuenta por ti según la fecha y tu placa.</p>",
        "</section>",
    ])


def dated_items(city: dict, today: dt.date) -> str:
    """Announced notices and overrides from rules.json that have not passed yet."""
    items = []
    for o in city.get("overrides") or []:
        if day(o["date"]) < today:
            continue
        status = "Sin restricción ese día" if o["action"] == "free" else "SIN CONFIRMAR en Placa Hoy"
        items.append((o["date"], status, o.get("note", ""), o.get("source_url")))
    for n in city.get("notices") or []:
        if day(n["date"]) < today:
            continue
        items.append((n["date"], n["title"], n["text"], n.get("source_url")))
    if not items:
        return ""
    items.sort(key=lambda i: i[0])
    lis = []
    for d, title, text, url in items:
        link = f' <a href="{e(url)}" rel="noopener">Fuente</a>.' if url else ""
        lis.append(f"<li><strong>{e(fmt_date(d))} · {e(title)}:</strong> {e(text)}{link}</li>")
    return "\n".join([
        '<section class="section" id="avisos">',
        "<h2>Avisos y excepciones anunciadas</h2>",
        "<p>Fechas especiales publicadas en las reglas de Placa Hoy. Pueden cambiar: confírmalas en la fuente oficial.</p>",
        "<ul>", *lis, "</ul>",
        "</section>",
    ])


def contingency_section(city: dict) -> str:
    if city.get("contingency") != "cdmx":
        return ""
    return "\n".join([
        '<section class="section" id="contingencia">',
        "<h2>Contingencia ambiental</h2>",
        "<p>Cuando se activa una contingencia ambiental (Fase I o II), el Hoy No Circula se amplía y las reglas "
        "de esta página dejan de bastar (ver las notas). Placa Hoy consulta en tu teléfono la página oficial "
        'de calidad del aire (<a href="https://aire.cdmx.gob.mx/" rel="noopener">aire.cdmx.gob.mx</a>) '
        "y lo tiene en cuenta en su respuesta.</p>",
        "</section>",
    ])


def verification_section(rules: dict, city: dict) -> str:
    ver = (rules.get("hnc") or {}).get("verification")
    if not ver or not any(p["type"] == "hnc" for p in city["periods"]):
        return ""

    def months(ms):
        ms = sorted(ms)
        pairs = [ms[i:i + 2] for i in range(0, len(ms), 2)]
        return " y ".join("–".join(MONTHS[m - 1] for m in p) for p in pairs)

    rows = "\n".join(
        f"<tr><td>{e(color.capitalize())}</td><td>{e(months(ms))}</td></tr>"
        for color, ms in ver["months"].items()
    )
    return "\n".join([
        '<section class="section" id="verificacion">',
        "<h2>Calendario de verificación por color de engomado</h2>",
        '<table class="data-table ph-table">',
        '<thead><tr><th scope="col">Engomado</th><th scope="col">Meses para verificar</th></tr></thead>',
        f"<tbody>\n{rows}\n</tbody>",
        "</table>",
        f'<p class="ph-src"><strong>Fuente oficial:</strong> <a href="{e(ver["source_url"])}" rel="noopener">'
        f'{e(source_label(ver["source_url"]))}</a></p>',
        "</section>",
    ])


# ---------------------------------------------------------------- pages

def page_meta(city: dict, country: dict, periods: list[dict], year: int) -> tuple[str, str, str]:
    scheme = scheme_title(country)
    short = SHORT_NAMES.get(city["id"], city["name"])
    title = f"{scheme} en {short} {year}: horarios y placas por día"
    active = [p for p in periods if p["type"] != "none"]
    if active:
        hours = fmt_windows(active[0].get("hours"))
        desc = (f"{scheme} en {city['name']} {year}: qué placas no circulan cada día ({hours}), "
                f"exentos, norma vigente y enlace a la fuente oficial.")
    elif periods:
        desc = f"{periods[0]['summary']} Norma, vigencia y enlace a la fuente oficial."
    else:
        desc = f"{scheme} en {city['name']}: reglas por confirmar. Consulta la fuente oficial."
    return title, desc, short


def other_cities(cities: list[tuple[dict, dict, str]], current: str | None) -> str:
    links = []
    for city, country, slug in cities:
        if city["id"] == current:
            continue
        label = f"{scheme_title(country)} {SHORT_NAMES.get(city['id'], city['name'])}"
        links.append(f'<li><a href="/placa-hoy/{slug}/">{e(label)}</a></li>')
    return '<ul class="ph-cities">\n' + "\n".join(links) + "\n</ul>"


def city_page(rules: dict, city: dict, country: dict, slug: str,
              cities: list[tuple[dict, dict, str]], today: dt.date) -> str:
    periods = [p for p in city["periods"] if day(p["valid_to"]) >= today]
    periods.sort(key=lambda p: (0 if "car" in p["kinds"] else 1, p["valid_from"]))
    title, desc, short = page_meta(city, country, periods, today.year)
    url = f"{APP_URL}{slug}/"
    scheme = scheme_title(country)
    beta = ' <span class="ph-tag">BETA</span>' if city.get("beta") else ""
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Sillapps", "item": f"{BASE_URL}/"},
            {"@type": "ListItem", "position": 2, "name": "Placa Hoy", "item": APP_URL},
            {"@type": "ListItem", "position": 3, "name": f"{scheme} en {short}", "item": url},
        ],
    }

    body = []
    if periods:
        for p in periods:
            body.append(period_section(p, city, country))
        parity = next((p for p in periods if p["type"] == "parity"), None)
        if parity:
            body.insert(0, parity_explainer(parity, city, country))
    else:
        body.append('<section class="section"><h2>Sin regla confirmada</h2>'
                    "<p>Placa Hoy no tiene una regla confirmada para las próximas fechas: la app muestra "
                    "SIN CONFIRMAR hasta que se publique una norma oficial.</p></section>")
    for extra in (dated_items(city, today), contingency_section(city), verification_section(rules, city)):
        if extra:
            body.append(extra)

    beta_text = (
        "<p>Esta ciudad está en <strong>beta</strong> en Placa Hoy: confirma con más atención "
        "en la fuente oficial.</p>" if city.get("beta") else ""
    )
    region = f" ({e(city['region'])})" if city.get("region") and city["region"] != city["name"] else ""

    return f"""<!doctype html>
<html lang="es" data-app="placa-hoy">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#0d1015" />
    <title>{e(title)}</title>
    <meta name="description" content="{e(desc)}" />
    <link rel="canonical" href="{e(url)}" />
    <link rel="icon" type="image/png" href="/placa-hoy/icon-192.png" />
    <meta property="og:type" content="article" />
    <meta property="og:site_name" content="Sillapps" />
    <meta property="og:locale" content="{OG_LOCALES.get(country['id'], 'es_419')}" />
    <meta property="og:title" content="{e(title)}" />
    <meta property="og:description" content="{e(desc)}" />
    <meta property="og:url" content="{e(url)}" />
    <meta property="og:image" content="{APP_URL}og.jpg" />
    <meta property="og:image:width" content="1024" />
    <meta property="og:image:height" content="500" />
    <meta name="twitter:card" content="summary_large_image" />
    <script type="application/ld+json">
{json.dumps(breadcrumb, ensure_ascii=False, indent=2)}
    </script>
    <link rel="stylesheet" href="{FONTS_CSS}" />
    <link rel="stylesheet" href="{CSS}" />
    <style>{PAGE_CSS}    </style>
  </head>
  <body>
    <main>
      <section class="panel hero">
        <div class="panel-inner">
          <div class="nav-row">
            <a class="back-link" href="/placa-hoy/">Placa Hoy</a>
            <a class="back-link" href="/">Sillapps</a>
          </div>

          <div class="masthead">
            <div>
              <p class="eyebrow">Placa Hoy · {e(country['name'])}</p>
              <h1 class="title">{e(scheme)} en {e(short)} {today.year}{beta}</h1>
            </div>
            <img class="app-mark" src="/placa-hoy/icon-192.png" alt="" width="76" height="76" />
          </div>

          <p class="intro">
            Horarios y placas por día del {e(country['scheme'])} en {e(city['name'])}{region}:
            qué placas no circulan cada día, en qué horario y quién está exento, según la norma vigente.
          </p>

          <div class="meta-card">
            <p class="meta-line"><strong>{e(WARNING)}</strong></p>
            <p class="meta-line">Placa Hoy no está afiliada a ninguna alcaldía, gobierno ni autoridad de tránsito.
              Esta página resume las reglas que usa la app; la norma oficial es la que manda.</p>
          </div>
          {beta_text}
          <a class="play-badge" href="{PLAY_URL}&amp;hl=es_419">
            <img src="{PLAY_BADGE}" alt="Disponible en Google Play" width="646" height="250" />
          </a>

          <div class="section-grid">
{chr(10).join(body)}

            <section class="section" id="app">
              <h2>¿Circulo hoy? Pregúntale a Placa Hoy</h2>
              <p>Guarda tu placa una vez y <strong>Placa Hoy</strong> te dice cada día si puedes circular,
                con el horario, la norma y el enlace a la fuente oficial. Sin anuncios, sin cuenta y sin rastreo.
                Con Placa Hoy Pro (pago único): widget en la pantalla de inicio y alertas la noche anterior y la mañana.</p>
              <p><a href="{PLAY_URL}&amp;hl=es_419">Descargar Placa Hoy en Google Play</a> ·
                <a href="/placa-hoy/">Más sobre la app</a></p>
            </section>

            <section class="section" id="ciudades">
              <h2>Otras ciudades</h2>
              {other_cities(cities, city['id'])}
            </section>
          </div>

          <footer class="site-footer">
            <nav aria-label="Enlaces legales">
              <a href="/placa-hoy/">Placa Hoy</a>
              <a href="/placa-hoy/privacidad.html">Política de privacidad</a>
              <a href="/legal.html#es">Aviso legal</a>
              <a href="mailto:contact@sillapps.com">contact@sillapps.com</a>
            </nav>
            <p>Reglas de Placa Hoy versión {e(rules['version'])}, publicadas el {e(fmt_date(rules['published']))}.
              Esta página no usa cookies ni analítica. © {today.year} Sillapps.
              Google Play y el logotipo de Google Play son marcas de Google LLC.</p>
          </footer>
        </div>
      </section>
    </main>
  </body>
</html>
"""


def landing_block(cities: list[tuple[dict, dict, str]], indent: str, today: dt.date) -> str:
    lines = [f'{indent}<ul class="stack">']
    for city, country, slug in cities:
        label = f"{scheme_title(country)} en {SHORT_NAMES.get(city['id'], city['name'])}"
        beta = " (beta)" if city.get("beta") else ""
        sub = f"{country['name']} · {city['region']}" if city.get("region") else country["name"]
        current = [p for p in city["periods"] if day(p["valid_to"]) >= today]
        if current and all(p["type"] == "none" for p in current):
            sub += " · Sin pico y placa para particulares"
        lines.append(
            f'{indent}  <li><a class="stack-link" href="{slug}/"><strong>{e(label)}{beta}</strong>'
            f"<span>{e(sub)}</span></a></li>"
        )
    lines.append(f"{indent}</ul>")
    sources = []
    for city, _, _ in cities:
        urls = []
        for p in city["periods"]:
            if day(p["valid_to"]) >= today and p["source_url"] not in urls:
                urls.append(p["source_url"])
        sources += [f'<a href="{e(u)}" rel="noopener">{e(city["name"])}</a>' for u in urls[:1]]
    lines.append(f'{indent}<p class="note">Fuentes oficiales: {join_es(sources)}.</p>')
    return "\n".join(lines)


def sitemap_block(cities: list[tuple[dict, dict, str]], published: str, indent: str) -> str:
    def lastmod(city: dict) -> str:
        return max([published] + [p["last_verified"] for p in city["periods"]])

    return "\n".join(
        f"{indent}<url>\n{indent}  <loc>{APP_URL}{slug}/</loc>\n{indent}  <lastmod>{lastmod(city)}</lastmod>\n{indent}</url>"
        for city, _, slug in cities
    )


def replace_block(text: str, block: str, path: Path) -> str:
    pattern = re.compile(r"(<!-- " + re.escape(START) + r" -->\n)(.*?)(^[ \t]*<!-- " + re.escape(END) + r" -->)", re.S | re.M)
    if not pattern.search(text):
        raise SystemExit(f"{path}: markers <!-- {START} --> / <!-- {END} --> not found")
    return pattern.sub(lambda m: m.group(1) + block + "\n" + m.group(3), text, count=1)


def marker_indent(text: str) -> str:
    m = re.search(r"^([ \t]*)<!-- " + re.escape(START) + " -->", text, re.M)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    source = HERE / "rules-v2.json"
    if not source.exists():
        source = HERE / "rules.json"
    rules = json.loads(source.read_text(encoding="utf-8"))
    countries = {c["id"]: c for c in rules["countries"]}
    cities = [(c, countries[c["country"]], city_slug(c, countries[c["country"]])) for c in rules["cities"]]
    slugs = [s for _, _, s in cities]
    if len(set(slugs)) != len(slugs):
        raise SystemExit(f"duplicate slugs: {slugs}")

    outputs: dict[Path, str] = {}
    for city, country, slug in cities:
        outputs[HERE / slug / "index.html"] = city_page(rules, city, country, slug, cities, args.today)

    landing = HERE / "index.html"
    text = landing.read_text(encoding="utf-8")
    outputs[landing] = replace_block(text, landing_block(cities, marker_indent(text), args.today), landing)

    sitemap = SITE / "sitemap.xml"
    text = sitemap.read_text(encoding="utf-8")
    outputs[sitemap] = replace_block(text, sitemap_block(cities, rules["published"], marker_indent(text)), sitemap)

    changed = [p for p, c in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
    if args.check:
        for p in changed:
            print(f"would change: {p.relative_to(SITE)}")
        return 1 if changed else 0
    for p in changed:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(outputs[p], encoding="utf-8")
        print(f"wrote {p.relative_to(SITE)}")
    stale = sorted(d.name for d in HERE.iterdir() if d.is_dir() and (d / "index.html").exists() and d.name not in slugs)
    for name in stale:
        print(f"warning: placa-hoy/{name}/ is no longer in rules.json (delete it and redirect if needed)")
    print(f"{len(cities)} city pages, {len(changed)} file(s) changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
