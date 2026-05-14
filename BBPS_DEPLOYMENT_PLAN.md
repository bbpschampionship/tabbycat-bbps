# BBPS Rohini Debate Championship 2026 — Tab Site

**Event:** 16 May 2026 · Bal Bharati Public School, Rohini · Modified WSDC

## Locked decisions
- **Base:** Fork of TabbyCat (Django + Vue, source-available)
- **Host:** Render — Starter web ($7) + Free Postgres + Free Redis
- **Domain:** `bbps-tab.onrender.com` (Render-provided)
- **Format in TabbyCat:** World Schools (2 prelims + Grand Final)
- **Total cost:** $7 one-time (cancel after event)

## Brand spec
- Primary crimson: `#6B0F1A`
- Accent gold: `#F5C800`
- Background cream: `#FBF3D9`
- Fonts: League Spartan (UI), Cormorant Garamond (display)
- Title: "BBPS Rohini Debate Championship 2026"
- Footer credit: "Academic Partner: Taivas Debate Club"

## Files to modify
| Path | Change |
|---|---|
| `tabbycat/static/logo-16x16.png` | BBPS logo 16×16 |
| `tabbycat/static/logo-32x32.png` | BBPS logo 32×32 |
| `tabbycat/static/logo-social.png` | BBPS social 1200×630 |
| `tabbycat/templates/scss/_variables.scss` | Crimson/gold/cream colors |
| `tabbycat/templates/base.html` | Title + meta |
| `tabbycat/templates/footer.html` | Strip donation, add Taivas credit |

## Three things I need from you
1. Your GitHub username (to fork the repo into)
2. BBPS logo file (any size, I'll resize to the 3 needed)
3. Confirm: create a free Render account at render.com (5 min)

## Execution timeline
- **Today (May 13):** Rebrand locally, push to your fork, connect Render, deploy
- **Tomorrow (May 14):** Configure tournament, import teams/judges/rooms, end-to-end test
- **May 15:** Dress rehearsal, brief tab team
- **May 16:** Run the event
