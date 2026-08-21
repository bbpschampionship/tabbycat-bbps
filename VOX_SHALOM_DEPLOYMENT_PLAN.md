# Vox Debating Championship — Tab Site

**Event:** WSDC-format intra-school debating championship · Shalom Presidency School, Gurugram · organised by Vox Shalom, in collaboration with Taivas

## Locked decisions
- **Base:** Fork of Tabbycat (Django + Vue, source-available) — same fork used for BBPS
- **Host:** Render — reusing the existing BBPS web service ($7 Starter) + Postgres + Redis (overwrite)
- **Deploy branch:** `develop` on `github.com/bbpschampionship/tabbycat-bbps` (push auto-deploys)
- **Format in Tabbycat:** World Schools (WSDC). Opening round → break Top 16 → Pre-Quarters → Quarters → Semis → Grand Final
- **Note:** reusing the BBPS Render service means the **existing database carries over** — the live homepage shows BBPS's post-event archive until a new Shalom tournament is created and its welcome message set.

## Brand spec (from the Vox certificate)
- Primary navy: `#0F2444`
- Accent gold: `#C4A052`
- Background ivory: `#FBF9F3`
- Success (emerald): `#2A7D5B`
- Fonts: League Spartan (UI), Anton (display), Cormorant Garamond (accent)
- Title: "Vox Debating Championship"
- Footer credit: "Organised by Vox Shalom · In collaboration with Taivas"

## Files modified for the rebrand
| Path | Change |
|---|---|
| `tabbycat/static/logo-16x16.png` | Vox Shalom crest on navy tile (16×16) |
| `tabbycat/static/logo-32x32.png` | Vox Shalom crest on navy tile (32×32) |
| `tabbycat/static/logo-social.png` | Navy/gold social card, 1200×630 |
| `tabbycat/templates/scss/components/custom.scss` | Navy / gold / ivory / emerald palette |
| `tabbycat/templates/base.html` | Title + meta + navy mask-icon |
| `tabbycat/templates/footer.html` | Vox Shalom event line + Taivas credit |
| `tabbycat/vox_assets/welcome-message.html` | Pre-event navy/gold landing copy (paste into tournament welcome message) — replaces `bbps_assets/` |

## Post-deploy checklist (tournament config — do in the live admin)
1. Create a new tournament (slug e.g. `vox`), set World Schools preset.
2. Configure the round structure: 1 preliminary (Opening Round) + break to Top 16, then elimination rounds (PQF/QF/SF/GF).
3. Import participants from the finalized Shalom student lists (CSV in ~/Downloads).
4. Paste `vox_assets/welcome-message.html` into the tournament's **welcome message** so the homepage shows Vox branding (not the BBPS archive).
5. Set `TAB_DIRECTOR_EMAIL` / `TIME_ZONE` env on Render if changing from BBPS values.
