# Qcom, the website

Ten pages and a floating analyst, built from saved outputs only and served on localhost. The site is called Qcom.

```
python scripts/serve_site.py      # http://localhost:8000 (opens the browser; rebuilds first if the sources changed)
start_site.bat                    # the same, by double-click on Windows
./start_site.sh                   # the same on macOS or Linux (start_site.command: double-click in macOS Finder)
python scripts/serve_site.py --lan  # also on phones and tablets on the same Wi-Fi, behind a six-digit code
start_site_lan.bat                # the same, by double-click on Windows
python scripts/build_site.py      # -> outputs/site/index.html, the one file the server serves
python scripts/check_site.py      # visits every page and presses every control under node; exit 1 if anything fails
node scripts/site_browser_check.js  # the same in a real headless browser, with screenshots (the server must be running)
python scripts/run_all.py         # the whole pipeline; rebuilds the site last, once the run log is complete
python scripts/deploy_pages.py    # publish outputs/site to GitHub Pages: https://deepak17kb.github.io/quickcommerce-mi/
python scripts/readme_assets.py   # the README's pictures, cut from the browser check's screenshots
```

`index.html` here is the shell, `app.css` the styles, `app.js` the pages, `analyst.js` the analyst engine, `sw.js` the
service worker (copied beside the page, not inlined).
`build_site.py` inlines all four and embeds the data as JSON blocks, each parsed only when a page needs it. No script
is loaded from anywhere; the only outside resource is the font stylesheet (the page falls back to system fonts offline).

## The server

`serve_site.py` is the Python standard library only. By default it listens on the loopback (127.0.0.1 and ::1) and
refuses a request whose Host is not localhost. Routes:

| Route | What it returns |
|---|---|
| `GET /` | the built site |
| `GET /api/health` | `{"ok": true, "ready": ...}`; the page uses it to tell that the live analyst is there. In Wi-Fi mode, and only to this computer, it also carries the phone address and code |
| `POST /api/ask` with `{"q": "..."}` | the offline analyst's answer object (`src/analyst/agent.py`) |
| `GET`, `POST /api/products`; `PUT`, `DELETE /api/products/<id>`; `GET /api/products/<id>/image` | products you add (below) |
| `GET /manifest.webmanifest`, `/icon-192.png`, `/icon-512.png`, `/apple-touch-icon.png` | the home-screen icon and app name, written by `build_site.py` |
| `POST /api/unlock` | Wi-Fi mode only: checks the six-digit code |
| `GET /sw.js` | the service worker |
| `OPTIONS /api/health`, `/api/ask` | public mode only: the browser's CORS preflight from an allowed origin (the live site) |
| `GET /api/metrics` | uptime, requests by route and status, analyst latency (p50, p95, max), answer-cache hits, rate-limit refusals. Counters only: no question text, no device address |

Every response carries a content security policy (scripts and requests to this server only, fonts from Google Fonts),
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a permissions policy that allows the camera here only. The
page and its files go out gzip-compressed when the browser accepts it, with an ETag (a reload costs a 304). In Wi-Fi
mode, asking and adding products are rate-limited per device (429 with `Retry-After`); the person at this computer is
not. An early answer (403, 404, 413, 429) reads the request body first: closing on an unread body resets the
connection on Windows, and the sender never sees the answer. The analyst is deterministic for a question, so its
answers are kept in a 256-entry LRU cache.

**Public mode** (`--public`, used by `render.yaml`): binds `0.0.0.0` on `$PORT` (`--host` to bind elsewhere, e.g.
127.0.0.1 to try it without opening the machine), answers any Host, writes nothing (the product routes and the code
route answer 403 and the product list is empty), rate-limits every device by the last address the host's proxy put in
`X-Forwarded-For`, and sends CORS headers for `/api/health` and `/api/ask` to the origins in `$QCOM_ALLOW_ORIGIN`
(default the live site) and nowhere else. It serves the site that `scripts/fetch_outputs.py` put in place and never
rebuilds it. The analyst reads the observed rows through `src.load.load_real()`, which keeps the process near 200 MB.

Only the product routes write, and only to `data/user_added/`. No request starts a long job: a question about a
listing with no saved chain is answered "no saved chain", not by running the chain live. If port 8000 is taken, the
next free port is used and printed.

## Phones, tablets and every OS

The page is one file with no build step on the device, so any current browser runs it: Chrome and Edge on Windows,
Android and ChromeOS, Safari on iPhone, iPad and Mac, Firefox and Samsung Internet. The server runs wherever Python 3
does (`start_site.bat` on Windows, `./start_site.sh` on Linux, `start_site.command` from macOS Finder; the first time on
macOS or Linux, `chmod +x` the script).

**Opening it on a phone or tablet.** A phone cannot reach `localhost` on the computer, so the server has a Wi-Fi mode:

1. On the computer, run `start_site_lan.bat` (or `./start_site.sh --lan`). The window prints an address such as
   `http://192.168.1.7:8000/` and a six-digit code. The header shows the same under **On your phone**.
2. The first time, Windows asks whether Python may use networks: allow **private** networks only. Without that the
   phone cannot connect. (Nothing in the project changes the firewall; that choice is the owner's.)
3. On the phone, on the same Wi-Fi, open the address and enter the code. The phone keeps a cookie for a day.
4. Optional: **Add to Home Screen** (Safari's share menu, or Chrome's menu) gives it an icon and opens it full screen.

Wi-Fi mode is off unless asked for. When on: every other device must send the code first; five wrong codes from one
device lock it out for ten minutes; a request whose Host is not this computer's address is refused; the code and the
cookie are new on every start. Close the window and it stops. It is plain http on the home network, so do not run it on
public Wi-Fi.

**What was done for small screens and older browsers:**

- Layouts step down at tablet width (hero and rows stack, tables scroll inside their card) and at phone width; the
  page never scrolls sideways (checked from 360 px to 1920 px wide).
- Touch: tabs, menus and links get larger tap areas, inputs are 16 px so iOS does not zoom on focus, hover effects are
  off on touch screens, the safe areas of notched phones are respected, and the add-product sheet uses the visible
  height (`100dvh`) so the keyboard does not hide it.
- No regular-expression lookbehind in the page's scripts (Safari before 16.4 rejects the whole script);
  `tests/test_site.py` enforces it. Colours built with `color-mix` have a plain fallback, and the frosted header has
  its `-webkit-` form.
- **Take a picture** opens the camera on phones and tablets. On a computer it uses the webcam where the browser
  allows it (over `localhost`); over Wi-Fi mode, which is http, a phone's browser opens its camera app instead.

## Pages

| Page | What it shows | Data it reads |
|---|---|---|
| Home | Price board for one product, the three modes, a shelf of followed listings, the pipeline as an order tracker | counts from `data/raw`, the run log, listing chains |
| Products | One listing through the seven chain stages | `listing_chain` |
| Festive planner | Every festival of the next twelve months with a countdown and a "stock up by" date, what is traditionally bought for each, a month-by-month strip, a product lookup ("handmade diya" -> Diwali, Kartika Purnima ...), and what Blinkit listed for each group on 2026-07-10 | `outputs/festive/festive_planner.json` from `src/seasonal/festive.py` |
| **Simulate** | A price move, promo against list price, an outage, one listing's price ladder | `simulate_grid`, `optimize_promo_frontier`, `simulate_unavailable`, listing chains |
| **Optimize** | Smallest cut for a category target, smallest move for one listing, restock order | the same grid, `optimize_price_cut`, `optimize_restock_lab` |
| **Analyst** | Questions in plain words, answered with tags and sources | the analyst's knowledge base |
| Models | Ten scorecards, each with its baseline and whether the data supports it | each model's `metrics.json` |
| Data & trust | Observed against simulated rows, the five tags, the three audit findings | `real_store_label_audit`, claims ledger |
| Plan the panel | How big a hand-logged panel must be | `collection_planner` |
| Pipeline | Every step of the last full run, with its log tail and the test results | `outputs/run_log/run_all.json` |

Simulate and Optimize read simulations that were run in advance. Nothing is simulated in the browser, and each page
says so. Where a target cannot be reached on the grid that was simulated, the page reports no feasible answer.

## The festive planner, and what it does not claim

`src/seasonal/festive.py` holds three things, each with its own tag: festival dates for Oct 2026 to Oct 2027 from
public panchang and holiday calendars, checked 2026-10-14, with their source links (Public source); which product types
are traditionally bought for each festival, as keyword rules over product names (Method); and the observed rows each
rule matches (Seen 10 Jul). The page says WHEN a product is in season, from the calendar. It never says how much more
sells: the data has no orders, and the one observed day, in July, was not a festival. "Stock up by" is the festival
start minus a lead time the viewer sets. The analyst still turns down "what sells most at Diwali"; its answer links to
the planner. The planner writes to `outputs/festive/`, not `outputs/models/`, so the analyst does not index it. Extend
the calendar in `FESTIVALS` when it runs out (it ends with Diwali 2027).

## Pictures, charts and the dynamic parts

- **Product pictures** are drawn packshots, made in the page from each product's own name, pack and category: a bottle,
  jar, pouch, can, box, tub or tray in the category's colour, with the brand and pack size on the label. They are
  illustrations, not photos (the brands' photos are copyrighted and nothing is downloaded); a product you add can
  carry a real photo instead.
- **Models** is one wide row per model: what it answers, its result and whether the data backs it, beside a chart
  drawn from its own saved metrics (capture and precision curves, calibrated coverage against the promise, a forest
  plot of recovered parameters, recovered-against-planted scatter, a dumbbell of response estimates, recall at k, and
  the matcher's decisions). Gradients, glow and tooltips; a filter shows all, the Lab models or the 10 Jul ones.
- **Dynamic:** the Products page searches, filters by category and sorts (price, delivery time, cheapest of four);
  your products can be edited, appear first on the Home shelf, and in the Festive planner when one is in season; the
  header search suggests products, your products, festivals and festive items as you type, with "Ask the analyst"
  last.

## Products you add

The Products page has **Add a product**: take a picture (the device camera, or a phone's camera app) or upload one,
then fill in the name, brand, pack size, category, the price on each app, stock and delivery time. **Edit** changes
any of it later; a photo is replaced only when a new one is chosen. The photo is shrunk
in the browser (longest side 1000 px, JPEG) before it is sent.

- Served from this machine, products are saved by the server in `data/user_added/` (`products.json` and `images/`),
  through `src/user_products.py`, which checks every field and that a photo really is the JPEG, PNG or WebP it claims.
  Opened from disk, they are kept in the browser.
- They carry the **Added by you** tag. No model, no pipeline step and not the analyst reads them, and they are never
  mixed with the observed or the simulated rows (`tests/test_site.py` checks that nothing in `src/` refers to them).
- A product whose name matches a festive product type shows its next festival ("Diwali in 23 d").
- **Remove** takes two clicks and deletes the entry and its photo.

## Wording: Seen 10 Jul, Lab and checks

The pages do not use the project's two data labels as words, nor "snapshot" (owner's requests, 2026-10-14). A number
observed on Blinkit is tagged **Seen 10 Jul**; one from the simulated panel or fitted to it, **Lab**. A snapshot as a
unit of time is a **check**: one round of prices and stock, morning or evening, so twelve checks are six days. Every
number still carries one of the two tags, so a simulated competitor price is never shown as a market fact. Only the
words changed.

- `plain()` in `app.js` rewords project text (analyst answers, model notes, log lines) when it is drawn. It runs
  after the analyst has verified its claims and never touches a digit.
- A citation is shown by a readable name ("saved result · price forecast lgbm"); the exact file path is in its hover
  title.
- A suggested question is shown in the site's words and asked in the project's (`SUGGESTED_PAIRS` in
  `build_site.py`). A typed question that says "observed", "seen", "10 Jul", "simulated" or "the Lab" gets the
  project's word added for the search; a question the analyst must turn down is passed on untouched.
- `site_smoke.js` fails if either label word, or "snapshot" in any form, reaches a page, a tooltip or a drawn answer.
  What a person typed, shown back to them, is exempt.

This covers the website only. `data_status` values, the raw data, the docs and the command-line analyst are unchanged.

## The analyst in the page

Served from localhost, a question goes to the project's own analyst. Opened from disk, or if the server does not
answer within 30 seconds, the page uses `analyst.js`: a port of the offline engine in `src/analyst`, in the same order
(refusal rules first, then experiment routing, then routing for the observed day, then BM25 search, then tags).

- **Experiment answers are the project analyst's own.** At build time the Python analyst produces and verifies its
  claims for every outage, store-add, promo, headroom, restock and listing question its router can reach. The page
  looks them up. A price move is formatted in the page from the same grid (2,240 cells).
- **Answers about the observed day** come from tables the Python analyst computed at build time.
- **It is scored on the project's own question sets with its saved answers switched off**
  (`scripts/site_analyst_eval.js`, the grading rules of `src/analyst/evaluate.py`). The result is on the Analyst page
  and in `outputs/site/analyst_eval.json`.

What it does not do: run a new simulation, or build a chain for a listing that has no saved one. It says so when asked.

## Basket, go anywhere, motion (2026-10-20)

- **Basket.** The round button on a product's picture puts it in the basket; the cart in the header opens it and shows
  what the whole basket would cost on each of the four apps, the cheapest marked. A followed listing is priced at its
  one Lab check, a product you added at the prices you entered; each line keeps its tag, a basket mixing the two says
  so, and an app without a price for some line is shown but not ranked. Delivery fees and coupons are not included.
  The basket lives in the browser (`localStorage`); nothing is sent anywhere.
- **Go anywhere.** <kbd>Ctrl</kbd> <kbd>K</kbd> (or <kbd>/</kbd>, or the button in the nav) opens a palette over
  every page, followed listing, your products, festival and festive item, the suggested questions and a few actions
  (basket, theme, share). Anything typed can also go to the analyst. Share copies the address of the page you are on
  (on a phone, the system share sheet).
- **Motion.** Hover effects (cards lift, pictures turn, a sheen crosses buttons, a light follows the pointer on the mode
  cards, the Home price board tilts) apply only where the device can hover. Sections ease in as they scroll into view,
  headline numbers count up, and a reading bar runs along the top. Everything that moves stops for anyone whose system
  asks for reduced motion, and for automated browsers, so the checks and screenshots always see the final state.
- **Offline.** On https (the live site) and on localhost, `sw.js` keeps the last page it saw. Network first: an online
  visit always gets the newest build. The browser check confirms the worker starts and holds the page.
- **Live site.** Every build also writes `site_dist/` (tracked in git); `.github/workflows/pages.yml` deploys it to
  GitHub Pages whenever a push to main changes it. `scripts/deploy_pages.py` stages, commits and pushes in one go,
  and `--check site_dist` is what the workflow runs before it deploys. The README's tests, pipeline, contracts,
  analyst and claims badges are `site_dist/badges/*.json`, written from the run each build reads.
- **The analyst behind the live site.** `site/config.json` (`"api"`) may name the project's public Python analyst
  (`render.yaml`: `serve_site.py --public`). The page asks its own server first, then that analyst; while a free host
  sleeps the page answers with its own engine and keeps waking the host, then switches to it. Products go to a server
  only if it keeps them (`/api/health` says `"writes"`); the public server never does.
- **Export / Import** (Products page): your products, photos included, as one JSON file, to move them between browsers
  and devices. Importing skips what is already on the list and anything that does not pass the same checks as the form.

## Checking it

| Check | What it proves | What it cannot |
|---|---|---|
| `python scripts/check_site.py` | Every page and control runs on the embedded data under node; the wording rule holds on every page, tooltip and drawn answer | See the layout |
| `node scripts/site_browser_check.js` | With the server running: headless Chrome or Edge opens every page, presses every tab, asks the analyst from the page, the floating chat and the search box, adds, edits, finds and removes a product, fills and opens the basket, uses Ctrl K, in light, dark, phone and wide widths, then as an iPad (upright and sideways), an Android tablet and a small Android phone with touch on. It fails on a script error, a content-security-policy violation, a sideways scroll, or a service worker that does not start and hold the page, and saves screenshots to `outputs/site/screens` | Judge how it looks: someone has to read the screenshots. It emulates devices in Chrome; it is not Safari on a real iPhone |
| `python -m pytest tests/test_site.py` | The sources, the built file, the refusal port, the wording filter, the server routes, the Wi-Fi code gate and lockout, no lookbehind, the phone and tablet head tags and icons | |

The browser check is not part of the test suite because it needs an installed browser. Nothing is downloaded.
