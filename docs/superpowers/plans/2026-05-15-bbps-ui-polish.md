# BBPS Tab Site UI Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the BBPS Rohini Debate Championship tab site functional and easy on the eyes for the live event in less than 24 hours, with zero risk to ballot/draw/admin flows.

**Architecture:** Apply changes only through SCSS variables, base template head, and a tournament preference (`welcome_message`) — three orthogonal, instantly-revertible commits. No view code, no Vue rebuilds outside the Sass step, no template overrides.

**Tech Stack:** Django templates · Bootstrap 4 + custom SCSS · Vite (for the existing Vue admin app, untouched) · Render auto-deploy on push to `develop` · TabbyCat REST API for the preference write.

---

## File Map

| File | Purpose | Touched in |
|---|---|---|
| `tabbycat/templates/base.html` | Loads Google Fonts stylesheet | Task 1 |
| `tabbycat/templates/scss/components/custom.scss` | Font + theme color overrides | Task 1, 2 |
| `tabbycat/templates/scss/components/variables.scss` | Layout color tokens | Task 2 |
| (API call, no file) | Sets `welcome_message` preference with custom HTML | Task 3 |
| `docs/superpowers/specs/2026-05-15-bbps-ui-polish-design.md` | Source-of-truth design | reference |

The first two tasks are SCSS-only; Sass rebuild happens automatically inside `bin/render-compile.sh`. Task 3 hits the live API and changes a DB row; no code deploy needed.

---

## Task 1: Typography swap (Inter → League Spartan + Anton + Cormorant)

**Files:**
- Modify: `tabbycat/templates/base.html` (head section, font preload area around line 33–46)
- Modify: `tabbycat/templates/scss/components/custom.scss` (font family vars, around lines 11–18)

- [ ] **Step 1: Add Google Fonts stylesheet to base.html head**

Open `tabbycat/templates/base.html`. Find the existing font preload block (the line that reads `<link rel="preload" href="{% static 'fonts/Inter-Regular.woff2' %}" as="font" type="font/woff2">`). Add the following three lines IMMEDIATELY above it:

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500&family=League+Spartan:wght@400;500;600;700&display=swap">
```

- [ ] **Step 2: Update SCSS font family variables**

Open `tabbycat/templates/scss/components/custom.scss`. Find the `$font-family-sans-serif` block (currently uses `"Inter-Regular"`). Replace lines 11–18 with:

```scss
// Family
$font-family-sans-serif:  "League Spartan", -apple-system,
  blinkmacsystemfont, "Segoe UI", roboto,
  "Helvetica Neue", arial, sans-serif,
  "Apple Color Emoji", "Segoe UI Emoji",
  "Segoe UI Symbol" !default;
$headings-font-family:    "League Spartan", -apple-system, blinkmacsystemfont,
  "Helvetica Neue", arial, sans-serif;
$display-font-family:     "Anton", "League Spartan", sans-serif;
$accent-font-family:      "Cormorant Garamond", Georgia, serif;
```

- [ ] **Step 3: Commit Task 1**

```bash
cd /Users/tatsam/Desktop/taivas-bootcamp-ops/tabbycat-bbps
git add tabbycat/templates/base.html tabbycat/templates/scss/components/custom.scss
git commit -m "Swap Inter for League Spartan; preload Anton + Cormorant Garamond"
git push origin develop
```

- [ ] **Step 4: Verify deploy succeeded**

Wait ~4 minutes for Render to redeploy, then run:

```bash
RENDER_KEY="rnd_Y7my24UZJn3DVwOVMxlv05QuuI9Y"
SVC="srv-d82mpd8g4nts73b5kmsg"
curl -s -H "Authorization: Bearer $RENDER_KEY" "https://api.render.com/v1/services/$SVC/deploys?limit=1" | python3 -c "import sys,json; d=json.load(sys.stdin)[0]['deploy']; print(d['status'], d['commit']['id'][:8], d['commit']['message'][:50])"
```

Expected: `live <new-sha> Swap Inter for League Spartan...`

- [ ] **Step 5: Verify fonts loaded on live site**

```bash
curl -s https://tabbycat-website-i4nm.onrender.com/bbps2026/ | grep -E "Anton|Cormorant|League"
```

Expected: at least one line that contains all three font names from the Google Fonts URL.

---

## Task 2: Color polish (warm white background, calmer chrome)

**Files:**
- Modify: `tabbycat/templates/scss/components/custom.scss` (Key Colors block + Theme colors block)
- Modify: `tabbycat/templates/scss/components/variables.scss` (Layout Colors block at top)

- [ ] **Step 1: Soften body background and danger color**

Open `tabbycat/templates/scss/components/custom.scss`. Find the existing `$body-bg:` line (currently `#FBF3D9`). Change to:

```scss
$body-bg:                 #FAFAF7; // warm white, easier on eyes during long events
```

In the same file, find `$red:                   #d1185e;` in the Theme colors block. Change to:

```scss
$red:                     #B91C1C; // tomato red, less candy-pink for the danger state
```

- [ ] **Step 2: Update layout color tokens**

Open `tabbycat/templates/scss/components/variables.scss`. Find the Layout Colors block (top of file, around lines 12–18). Replace the relevant lines with:

```scss
// Layout Colors
$alt-bg:                  #fff;                   // table backgrounds, cards
$table-bg-hover:          rgba(107, 15, 26, 0.05); // subtle crimson tint on hover
$sidebar-bg:              #1A1512;                // brand ink (was #333c47)
$sidebar-muted-text:      $gray-400;
$droppable-bg:            $gray-200;
$navbar-light-bg:         $alt-bg;                // footer and top navbar
$navbar-light-border:     #E8E2D0;                // warm gray divider (was $gray-200)
```

- [ ] **Step 3: Commit Task 2**

```bash
cd /Users/tatsam/Desktop/taivas-bootcamp-ops/tabbycat-bbps
git add tabbycat/templates/scss/components/custom.scss tabbycat/templates/scss/components/variables.scss
git commit -m "Color polish: warm-white bg, ink sidebar, calmer danger state"
git push origin develop
```

- [ ] **Step 4: Wait for deploy and verify new colors in compiled CSS**

Wait ~4 minutes, then fetch the compiled stylesheet URL from the live page and grep for the new values:

```bash
CSS_URL=$(curl -s https://tabbycat-website-i4nm.onrender.com/bbps2026/ | grep -oE 'href="[^"]*style\.[0-9a-f]+\.css"' | head -1 | sed 's/href="//; s/"$//')
echo "CSS: $CSS_URL"
curl -s "https://tabbycat-website-i4nm.onrender.com$CSS_URL" | grep -oE "(#FAFAF7|#B91C1C|#1A1512|#E8E2D0)" | sort -u
```

Expected output (order may vary):
```
#1A1512
#B91C1C
#E8E2D0
#FAFAF7
```

If any of the four hexes are missing the SCSS didn't take — open that file and re-check the edit.

---

## Task 3: Public landing welcome message

This is a single API call that sets the `welcome_message` tournament preference. No deploy required — change takes effect immediately.

**Files:**
- (No file edits. Pure API call against the running site.)

- [ ] **Step 1: Confirm the admin session cookie is still valid**

```bash
curl -sS -b /tmp/cookies.txt "https://tabbycat-website-i4nm.onrender.com/api/v1/tournaments/bbps2026/preferences" -H "Accept: application/json" -w "\nHTTP %{http_code}\n" | tail -2
```

Expected: `HTTP 200` plus a JSON array of preferences in the body.

If you see `HTTP 302` or `HTTP 403`, re-login first:

```bash
SITE="https://tabbycat-website-i4nm.onrender.com"
rm -f /tmp/cookies.txt
curl -sS -c /tmp/cookies.txt "$SITE/accounts/login/" -o /tmp/login.html
CSRF=$(awk -F'"' '/csrfmiddlewaretoken/{for(i=1;i<=NF;i++) if($i ~ /value=/){print $(i+1); exit}}' /tmp/login.html)
curl -sS -b /tmp/cookies.txt -c /tmp/cookies.txt \
  -H "Referer: $SITE/accounts/login/" \
  --data-urlencode "csrfmiddlewaretoken=$CSRF" \
  --data-urlencode "username=bbpsadmin" \
  --data-urlencode "password=127BBPS@CAP" \
  "$SITE/accounts/login/" -o /dev/null
```

- [ ] **Step 2: Set the welcome_message preference via the preferences API**

The TabbyCat preferences API uses `PATCH` on the per-tournament preferences endpoint. The identifier is `public_features__welcome_message` (double-underscore between section and name).

```bash
SITE="https://tabbycat-website-i4nm.onrender.com"
CSRF=$(grep csrftoken /tmp/cookies.txt | awk '{print $7}')

WELCOME_HTML='<div class="bbps-landing">
  <style scoped>
    .bbps-landing { padding: 32px 8px 24px; max-width: 760px; margin: 0 auto; }
    .bbps-landing .tag { font-family: "League Spartan", sans-serif; font-weight: 700; font-size: 11px; letter-spacing: 0.3em; color: #6B0F1A; text-transform: uppercase; }
    .bbps-landing h1.hero { font-family: "Anton", sans-serif; font-size: clamp(40px, 7vw, 64px); line-height: 0.95; color: #1A1512; margin: 12px 0 8px; letter-spacing: 0.01em; }
    .bbps-landing .hero em { font-style: normal; color: #6B0F1A; }
    .bbps-landing .tagline { font-family: "Cormorant Garamond", Georgia, serif; font-style: italic; font-size: 18px; color: #555; max-width: 540px; line-height: 1.5; margin-bottom: 24px; }
    .bbps-landing .meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 18px 0; border-top: 1px solid #E8E2D0; border-bottom: 1px solid #E8E2D0; margin-bottom: 22px; }
    @media (max-width: 540px) { .bbps-landing .meta { grid-template-columns: repeat(2, 1fr); } }
    .bbps-landing .meta .k { font-family: "League Spartan", sans-serif; font-weight: 700; font-size: 9px; letter-spacing: 0.22em; color: #999; text-transform: uppercase; display: block; }
    .bbps-landing .meta .v { font-family: "League Spartan", sans-serif; font-weight: 700; font-size: 14px; color: #6B0F1A; margin-top: 2px; }
    .bbps-landing .credit { font-family: "League Spartan", sans-serif; font-size: 12px; color: #888; margin-top: 16px; line-height: 1.6; }
  </style>
  <div class="tag">BBPS Rohini Debate Championship 2026</div>
  <h1 class="hero">Clash ideas.<br><em>Shape minds.</em><br>Lead the future.</h1>
  <p class="tagline">Modified World Schools format. 22 schools. 11 simultaneous debates. One stage in Rohini.</p>
  <div class="meta">
    <div><span class="k">Date</span><span class="v">16 May 2026</span></div>
    <div><span class="k">Format</span><span class="v">Mod-WSDC</span></div>
    <div><span class="k">Teams</span><span class="v">22</span></div>
    <div><span class="k">Rounds</span><span class="v">3</span></div>
  </div>
  <p class="credit">Hosted by Bal Bharati Public School, Rohini.<br>Academic Partner: Taivas Debate Club.</p>
</div>'

python3 -c "
import json, requests
from http.cookiejar import MozillaCookieJar
jar = MozillaCookieJar('/tmp/cookies.txt'); jar.load(ignore_discard=True, ignore_expires=True)
s = requests.Session(); s.cookies = jar
csrf = next(c.value for c in jar if c.name == 'csrftoken')
s.headers.update({'X-CSRFToken': csrf, 'Referer': '$SITE/', 'Content-Type': 'application/json', 'Accept': 'application/json'})

with open('/dev/stdin') as f:
    body = f.read()

r = s.patch(
    '$SITE/api/v1/tournaments/bbps2026/preferences',
    json=[{'identifier': 'public_features__welcome_message', 'value': body}],
)
print('HTTP', r.status_code)
if r.status_code >= 400:
    print(r.text[:400])
else:
    print('Welcome message set.')
" <<<"$WELCOME_HTML"
```

- [ ] **Step 3: Verify the welcome message renders on the live tournament index**

```bash
curl -s https://tabbycat-website-i4nm.onrender.com/bbps2026/ | grep -E "Clash ideas|Shape minds|Lead the future" | head -3
```

Expected: 3 lines, one matching each phrase.

- [ ] **Step 4: Visually verify on phone-size viewport**

Run a quick visual check by opening `https://tabbycat-website-i4nm.onrender.com/bbps2026/` in a browser at 360px width. Confirm:
- The "Clash ideas / Shape minds / Lead the future." hero is readable
- The meta grid (Date / Format / Teams / Rounds) wraps to 2x2 on mobile
- No horizontal scrollbar appears

If the layout breaks, the issue is most likely missing styles inside the `<style scoped>` block — fix the SCSS edits in the welcome HTML and re-run Step 2 with the corrected HTML.

- [ ] **Step 5: Commit a record of the welcome HTML to the repo for replay/recovery**

The HTML lives in the DB now, not in code. Save a copy in the repo so we can re-apply if the DB is restored from a snapshot.

Create `tabbycat/bbps_assets/welcome-message.html` with the EXACT HTML from Step 2 (everything between `WELCOME_HTML='` and the closing `'`):

```bash
mkdir -p /Users/tatsam/Desktop/taivas-bootcamp-ops/tabbycat-bbps/tabbycat/bbps_assets
cat > /Users/tatsam/Desktop/taivas-bootcamp-ops/tabbycat-bbps/tabbycat/bbps_assets/welcome-message.html <<'EOF'
<div class="bbps-landing">
  <style scoped>
    .bbps-landing { padding: 32px 8px 24px; max-width: 760px; margin: 0 auto; }
    .bbps-landing .tag { font-family: "League Spartan", sans-serif; font-weight: 700; font-size: 11px; letter-spacing: 0.3em; color: #6B0F1A; text-transform: uppercase; }
    .bbps-landing h1.hero { font-family: "Anton", sans-serif; font-size: clamp(40px, 7vw, 64px); line-height: 0.95; color: #1A1512; margin: 12px 0 8px; letter-spacing: 0.01em; }
    .bbps-landing .hero em { font-style: normal; color: #6B0F1A; }
    .bbps-landing .tagline { font-family: "Cormorant Garamond", Georgia, serif; font-style: italic; font-size: 18px; color: #555; max-width: 540px; line-height: 1.5; margin-bottom: 24px; }
    .bbps-landing .meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 18px 0; border-top: 1px solid #E8E2D0; border-bottom: 1px solid #E8E2D0; margin-bottom: 22px; }
    @media (max-width: 540px) { .bbps-landing .meta { grid-template-columns: repeat(2, 1fr); } }
    .bbps-landing .meta .k { font-family: "League Spartan", sans-serif; font-weight: 700; font-size: 9px; letter-spacing: 0.22em; color: #999; text-transform: uppercase; display: block; }
    .bbps-landing .meta .v { font-family: "League Spartan", sans-serif; font-weight: 700; font-size: 14px; color: #6B0F1A; margin-top: 2px; }
    .bbps-landing .credit { font-family: "League Spartan", sans-serif; font-size: 12px; color: #888; margin-top: 16px; line-height: 1.6; }
  </style>
  <div class="tag">BBPS Rohini Debate Championship 2026</div>
  <h1 class="hero">Clash ideas.<br><em>Shape minds.</em><br>Lead the future.</h1>
  <p class="tagline">Modified World Schools format. 22 schools. 11 simultaneous debates. One stage in Rohini.</p>
  <div class="meta">
    <div><span class="k">Date</span><span class="v">16 May 2026</span></div>
    <div><span class="k">Format</span><span class="v">Mod-WSDC</span></div>
    <div><span class="k">Teams</span><span class="v">22</span></div>
    <div><span class="k">Rounds</span><span class="v">3</span></div>
  </div>
  <p class="credit">Hosted by Bal Bharati Public School, Rohini.<br>Academic Partner: Taivas Debate Club.</p>
</div>
EOF
cd /Users/tatsam/Desktop/taivas-bootcamp-ops/tabbycat-bbps
git add tabbycat/bbps_assets/welcome-message.html
git commit -m "Record landing-page welcome HTML alongside code (DB stores live copy)"
git push origin develop
```

---

## Task 4: Full smoke test on the live site

This task verifies nothing in the admin / draw / ballot flows regressed after the three previous changes.

**Files:** (none — runs only against the deployed site)

- [ ] **Step 1: Verify admin dashboard still loads**

```bash
curl -sS -L -b /tmp/cookies.txt "https://tabbycat-website-i4nm.onrender.com/bbps2026/admin/" -o /tmp/dash.html -w "HTTP %{http_code}\n"
grep -E "<title>.*Dashboard" /tmp/dash.html | head -1
```

Expected: `HTTP 200` and a `<title>` containing `BBPS 2026 | Dashboard`.

- [ ] **Step 2: Verify Round 1 draw page still renders all 11 pairings**

```bash
curl -sS -L -b /tmp/cookies.txt "https://tabbycat-website-i4nm.onrender.com/bbps2026/admin/draw/round/1/" -o /tmp/draw.html -w "HTTP %{http_code}\n"
grep -oE "Room [0-9]+" /tmp/draw.html | sort -u | wc -l
```

Expected: `HTTP 200` and exactly `11` unique Room references.

- [ ] **Step 3: Verify one judge private URL still works**

```bash
JUDGE_URL=$(grep "Tatsam Lamba" -A1 /Users/tatsam/Desktop/taivas-bootcamp-ops/bbps-tab-backups/judge-urls.txt | grep "Link:" | awk '{print $2}')
echo "URL: $JUDGE_URL"
curl -sS "$JUDGE_URL" | grep -E "<title>.*Private URL|Submit|Tatsam"
```

Expected: at least one line confirming the page rendered. No HTTP error.

- [ ] **Step 4: Verify the landing page hero is visible at the bare tournament URL**

```bash
curl -s https://tabbycat-website-i4nm.onrender.com/bbps2026/ | grep -E "Clash ideas|Shape minds|Lead the future" | head -3
```

Expected: three matching lines.

- [ ] **Step 5: Run the DB backup to capture post-change state**

```bash
cd /Users/tatsam/Desktop/taivas-bootcamp-ops/bbps-tab-backups
python3 backup-python.py 2>&1 | tail -3
```

Expected: line ending with `✅ Saved …json.gz`.

- [ ] **Step 6: Final commit of plan execution log (optional)**

This step is only needed if a previous step printed warnings. Otherwise skip.

---

## Acceptance criteria

The plan is complete when every checkbox above is ticked AND all four of the following are true:

1. `https://tabbycat-website-i4nm.onrender.com/bbps2026/` shows the new landing hero (Anton + crimson "Shape minds")
2. The admin dashboard loads, lists 22 teams, and shows Round 1 with 11 pairings + 11 venues + 11 chairs
3. A judge private URL renders without error and shows the assigned Room
4. A fresh DB snapshot was taken successfully

## Rollback playbook

If anything looks broken after each commit:

```bash
cd /Users/tatsam/Desktop/taivas-bootcamp-ops/tabbycat-bbps
git log --oneline -5                # find the bad sha
git revert <bad-sha> --no-edit
git push origin develop
```

For Task 3 (welcome message lives in DB, not code), revert by setting the preference back to empty:

```bash
python3 -c "
import requests
from http.cookiejar import MozillaCookieJar
jar = MozillaCookieJar('/tmp/cookies.txt'); jar.load(ignore_discard=True, ignore_expires=True)
s = requests.Session(); s.cookies = jar
csrf = next(c.value for c in jar if c.name == 'csrftoken')
s.headers.update({'X-CSRFToken': csrf, 'Referer': 'https://tabbycat-website-i4nm.onrender.com/', 'Content-Type': 'application/json'})
r = s.patch('https://tabbycat-website-i4nm.onrender.com/api/v1/tournaments/bbps2026/preferences', json=[{'identifier': 'public_features__welcome_message', 'value': ''}])
print('HTTP', r.status_code)
"
```
