# sillapps.github.io

The Sillapps site, served by GitHub Pages at https://sillapps.com (`CNAME`).
This repo is the **only source of truth** for every public page of the Sillapps apps:
the app repos (`~/Developer/sillapps-*`) keep no copy, they point here (their `CLAUDE.md`).

## Never move or rename

These URLs are used outside the site: keep them exactly where they are.

- `app-ads.txt`: authorized sellers for AdMob (`google.com, pub-9295141541441834, DIRECT, f08c47fec0942fa0`), must stay at https://sillapps.com/app-ads.txt.
- `google13ee2aa53b0a0847.html`: Search Console verification. `robots.txt`, `sitemap.xml` (add every new page).
- `<app>/privacy.html` (and `privacidad.html`): privacy policy URLs declared in the Play Console.
- Data read by installed apps: `placa-hoy/rules.json`, `placa-hoy/rules-v2.json`, `beneficios/calendars.json`.
- `neon-overload/download/`: redirect to Google Play, linked from outside.
- `eco-claims-pocket/`: legacy pages of Hora Barata's package (old name), online but unlisted.

## Layout

- `index.html`: neutral Sillapps home page, one card per app. Each card is themed like its app (`data-app` on the card).
- `<app>/`: app page (`index.html`), privacy policy, `icon-192.png`, `og.jpg` (share image), screenshots.
- `legal.html` (FR/ES/EN legal notice), `impressum.html` (German Impressum): neutral theme.
- `brand/`: Sillapps logo ("A2", chosen 2026-09-30): a white "S" of linked nodes on an ink square, the nodes in app colors (cyan, yellow, pink, green), with a light outline so the square stays visible on dark backgrounds. `mark.svg` (logo), `favicon.svg` (simplified for 16-32 px: thicker S, two nodes; also used for the small "Sillapps" pills), `mark-mono.svg` (one color), `mark-180.png` (apple-touch, full bleed), `mark-512.png` (structured data), `og.jpg` (home share image). `/favicon.ico` (16/32/48) at the root for browsers that ask for it. Name: "Sillapps" in Space Grotesk 700.
- `brand/badges/`: the official Google Play badges (en, es-419, es, de), unmodified, served from here so that showing a badge sends nothing to Google (the link to the store only opens on a click).
- `404.html`: page shown by GitHub Pages for any unknown URL (noindex).
- `fonts/`: the apps' fonts as subset woff2, declared in `fonts/fonts.css`. Served from here on purpose: no Google Fonts, so no visitor IP goes to a third party.
- `styles.css`: shared layout and components, then one theme per app.

## Themes

A page picks its app theme with `<html lang="…" data-app="<slug>">` and loads
`/fonts/fonts.css` then `/styles.css`. The `[data-app="<slug>"]` block of `styles.css` holds the app's
colors, fonts, radius, hero art (`--art`) and top stripe (`--stripe`), copied from the app's
`lib/src/core/theme.dart` (or `lib/shared/neon_palette.dart` for the games). Without `data-app`,
the neutral Sillapps theme applies (light, dark when the device is dark).

Shared components: `.play-badge`, `.soon-badge`, `.chips`, `.shots`, `.shot-wide`, `.faq`,
`.feature-list`, `.data-table`, `.meta-card`, `.notice-card`, `.section`, `.stack`. The app icon sits at the
top right of every page (`.app-mark`). Bump `?v=` on both stylesheet links when `styles.css` changes.

## Generated pages

- `scioperi/index.html`: rebuilt every hour by `scioperi/build_oggi.py` (`.github/workflows/scioperi-oggi.yml`). Edit the script, not the HTML.
- `placa-hoy/<city>/index.html`, the city list of `placa-hoy/index.html` and the city block of `sitemap.xml`: `python3 placa-hoy/build_pages.py`.

## Local preview

```bash
python3 -m http.server 8765 --bind 127.0.0.1
```
