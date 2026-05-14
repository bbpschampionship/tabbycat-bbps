# BBPS Tab Site — UI Polish Design

**Date:** 2026-05-15
**Author:** Tatsam Lamba (with Claude)
**Event:** BBPS Rohini Debate Championship 2026 — 16 May 2026 (tomorrow)
**Constraint:** Ship within ~3 hours. Zero regressions in admin / ballot / draw flows.

---

## Goal

Make the BBPS tab site **functional and easy on the eyes** during an 8-hour event.

Pull back from the original "brochure-faithful" direction (heavy crimson, dramatic Anton + Cormorant everywhere). Apply the brochure palette as *restrained accents* over a clean, readable foundation. Judges, parents, and tab staff all stare at this for hours.

## Non-Goals

- Custom judge phone view (TabbyCat's existing template is well-tested; replacing it risks ballot submission bugs less than 24 hours from the event)
- Printable ballot redesign (we will not print ballots; private URLs handle entry)
- Admin dashboard restyle (admin users are us; they don't need polish)
- Logo or favicon changes (already shipped)
- New backend logic or data model changes

## Constraints and risks

- **Event is tomorrow** — every change must be reversible by one git revert
- **Production already serving** — deploy via Render auto-deploy on push to `develop`
- **Vue + Django templates mixed** — the site uses both; restrict changes to Django templates and SCSS (avoid Vue rebuilds where possible)
- **2GB Standard plan** — Vite/Sass rebuild already verified at this size; no headroom risk

---

## Scope (3 work items)

### 1. Typography pass

Swap upstream Inter (utility sans-serif) for a brochure-aligned trio applied conservatively:

| Use | Font | Weight |
|---|---|---|
| Body text, tables, forms | **League Spartan** | 400 |
| Section headings (h2, h3, h4) | **League Spartan** | 700 |
| Page hero / public-landing title | **Anton** | 400 (display only) |
| Decorative tagline / motion quote | **Cormorant Garamond** italic | 500i |
| Monospace (codes, IDs) | system mono | — |

**Files touched**
- `tabbycat/templates/scss/components/custom.scss` — `$font-family-sans-serif`, `$headings-font-family`
- `tabbycat/templates/base.html` — Google Fonts preconnect + stylesheet link

**Approach:** Replace `Inter-Regular` references with `League Spartan` in SCSS. Add a single `<link>` in `base.html` for `family=Anton&family=Cormorant+Garamond&family=League+Spartan`. Keep all weights light to avoid font-loading delay.

### 2. Color polish

Tone down the existing crimson saturation across the chrome. Brochure colors used as **accents**, not dominants.

| Element | Current | New |
|---|---|---|
| Page body background | `#FBF3D9` (cream) | `#FAFAF7` (warm white) |
| Primary buttons / links | `#6B0F1A` ✓ | unchanged |
| Sidebar (admin) | `#333c47` (Jet default) | `#1A1512` (ink) |
| Table row hover | `#e3e3e3` | `rgba(107,15,26,0.05)` |
| Success state | `#2A9D8F` ✓ | unchanged |
| Warning state | `#F5C800` ✓ | unchanged |
| Danger state | `#d1185e` | `#B91C1C` (red-700; less candy-pink) |
| Borders / dividers | `$gray-200` | `#E8E2D0` (warm gray) |
| Card shadows | varied | flat 1px borders, no shadow |

**Files touched**
- `tabbycat/templates/scss/components/custom.scss`
- `tabbycat/templates/scss/components/variables.scss`

### 3. Public landing page

A new template for the unauthenticated landing page (`/` when no user is logged in).

**Content blocks** (top to bottom, single column, max-width 720px, vertical rhythm 32px):

1. **Tag** — `BBPS ROHINI DEBATE CHAMPIONSHIP 2026` in League Spartan 700, letter-spaced, crimson
2. **Hero** — `Clash ideas. Shape minds. Lead the future.` in Anton, dark ink. Drops to one line on mobile, two on desktop.
3. **Tagline** — In Cormorant Garamond italic, ~14pt: `Modified World Schools format. 22 schools. One stage in Rohini.`
4. **Meta strip** — 4 inline data cells (Date / Format / Teams / Rounds), one row on desktop, 2x2 on mobile. League Spartan, small caps labels.
5. **Action row** — Two buttons: `View Draw →` (crimson) and `Live Standings →` (outline). Both link to public TabbyCat URLs.
6. **Hosted-by footer block** — `Hosted by Bal Bharati Public School, Rohini · Academic Partner: Taivas Debate Club` in League Spartan small.

**Files touched**
- New: `tabbycat/templates/bbps/landing.html` (extends base)
- `tabbycat/templates/blank_site_start.html` or `tabbycat/tournaments/templates/public_tournament_index.html` — wire conditional include so logged-out users at `/` see the new landing, logged-in users keep the existing dashboard

**Approach:** Override only the public welcome view. Admin and tournament-internal pages keep their TabbyCat templates unchanged.

---

## Out of scope (deliberately deferred)

- **Big-screen "display" mode redesign** — original spec'd Tier 2 item, dropped to reduce risk. The default TabbyCat display works; we'll style it via the same SCSS color/font pass automatically.
- **Public draws & standings page redesign** — same reasoning; they inherit the new fonts and color tokens, which is enough.
- **Judge phone view redesign** — risky to touch a day before the event.

These can be revisited post-event for future BBPS tournaments.

---

## Testing plan

After each commit:
1. Smoke-test `/bbps2026/admin/` — admin dashboard loads, sidebar/cards visible
2. Smoke-test `/bbps2026/` — public tournament index loads
3. Smoke-test `/bbps2026/privateurls/<key>/` — judge view loads, ballot button present
4. Open page on phone (small viewport) — text legible, no overflow
5. Run `python3 backup-python.py` — DB still reachable (sanity check, unrelated to UI but good hygiene)

Render auto-deploys each push; the test commands above run on the live URL once the deploy reaches `live`.

## Rollback plan

Each change ships as a single commit. To revert: `git revert <sha> && git push`. Render redeploys old version in ~3 minutes.

## Open questions resolved

1. ~~Tone direction?~~ → Functional, easy on eyes (not full brochure)
2. ~~Should Tier 2 items be in scope?~~ → Display screen + public tables dropped; landing page kept
3. ~~Judge phone redesign?~~ → No, too risky day-of

## Acceptance criteria

- [ ] Fonts loaded: League Spartan visible in body, Anton on public hero, Cormorant on tagline
- [ ] No console errors on public landing or admin dashboard
- [ ] Public landing renders cleanly on iPhone-sized viewport
- [ ] Crimson buttons visibly distinct from gray buttons
- [ ] All existing TabbyCat admin functions still work (draw, ballot, standings)
- [ ] Single rollback revert restores pre-polish state
