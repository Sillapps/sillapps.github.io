# Sillapps brand kit

Everything about the Sillapps logo lives in this folder. Visual index with download links:
**https://sillapps.com/brand/** (`index.html`, noindex). Everything in one file: `sillapps-brand-kit.zip`.

Logo "A2" (chosen 2026-09-30): a white "S" of linked nodes on an ink square, the nodes in app colors
(cyan `#2af6ff`, yellow `#ffd23f`, pink `#ff4fd8`, green `#3ddc97`), with a light outline so the square
stays visible on dark backgrounds. Name: "Sillapps" in Space Grotesk Bold (never "SILL'APPS").

| File | Use |
|---|---|
| `mark.svg` | Icon, main logo (site header, documents). |
| `favicon.svg`, `/favicon.ico` | Simplified icon for 16-32 px (tabs, small pills). |
| `mark-mono.svg` | One-color icon (black), also `logo/sillapps-icon-mono-black.svg`. |
| `logo/sillapps-icon-mono-white.svg` | One-color icon, white, for photos and dark backgrounds. |
| `logo/sillapps-lockup-on-light.svg` / `-on-dark.svg` | Icon + name (text outlined, no font needed), with 2000 px PNGs. |
| `logo/sillapps-wordmark-on-light.svg` / `-on-dark.svg` | Name only, with 2000 px PNGs. |
| `logo/sillapps-icon-1024.png` | Icon PNG, rounded, transparent corners. |
| `mark-180.png` | Apple touch icon (full bleed). `mark-512.png`: logo in the site's structured data. |
| `social/avatar-1080.png` | Profile picture for YouTube, Instagram, TikTok, LinkedIn (full bleed, round crop). |
| `social/youtube-banner-2560x1440.jpg` | YouTube channel art (logo in the 1546×423 safe area). |
| `play/developer-icon-512.png`, `play/developer-header.jpg` | Google Play developer page (uploaded 2026-09-30). |
| `badges/google-play-*.png` | Official Google Play badges, unmodified, served from here. |
| `og.jpg` | Share image of the home page (1200×630). |

Do not move `mark.svg`, `favicon.svg`, `mark-180.png`, `mark-512.png`, `og.jpg` or `badges/`: pages and
structured data point to them. The outlined name comes from `SpaceGrotesk-Bold.ttf` (shaped with
HarfBuzz, letter-spacing -0.035em, as on the site). Rebuild the zip after any change here.
