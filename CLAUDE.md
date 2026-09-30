# CLAUDE.md

Read `README.md` first: what must never move (app-ads.txt, verification file, privacy URLs, JSON read by the apps), themes, generated pages.

- Other sessions (one per app) and a bot (hourly Scioperi page) push here: `git pull --rebase` before committing, stage only the files you changed, never `git add -A`.
- A new app: folder `<slug>/`, `<html data-app="<slug>">`, a `[data-app="<slug>"]` theme block in `styles.css` from the app's `theme.dart`, its fonts in `fonts/` if new, a card on `index.html`, its URLs in `sitemap.xml`.
- No third-party fonts, trackers or cookies (the legal notice says so).
