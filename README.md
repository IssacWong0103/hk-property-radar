# HK Property Radar 🏙️

A self-updating, always-on web dashboard + AI news pusher that tracks Hong Kong
residential **price and rent** trends across the **18 districts** — framed for a
family buyer/renter. Built for **YR** to open on his iPhone and PC with zero setup.

**$0 recurring cost** except DeepSeek API tokens (a few cents/day). No server to
run or keep awake.

---

## How YR uses it (nothing technical)

1. You send him one link: `https://<your-github-username>.github.io/hk-property-radar/`
2. On **iPhone** (Safari): tap **Share → Add to Home Screen**. It installs as an app
   icon and opens full-screen — no App Store, no login, no "activation".
3. On **PC**: just bookmark the link.

It refreshes itself on a schedule; he always sees the latest.

---

## What's inside

| Tab | Shows |
|---|---|
| **Home** | Headline KPIs (price index, rent, mortgage cost, transactions), price-vs-rent trend, cheapest/priciest districts, latest headlines |
| **Districts** | All **18 districts** ranked by new-launch $/sq.ft, filter by region, sortable detail table |
| **Rent vs Buy** | Price vs rent index by flat size (family sizes), gross rental yield, today's $ levels by region |
| **Market** | Mortgage cost (HIBOR), primary vs secondary volume, new supply, vacancy |
| **News** | AI "Top 3 moves" + a live feed — **every item links to its source** |

English-first UI, light/dark, installable (PWA).

---

## Architecture (the $0 pattern)

```
GitHub Actions (cron)  →  refresh data + AI news  →  commit + deploy
        │                                                   │
        └── the free "server": no host to pay for/keep awake ┘
GitHub Pages  →  always-on static dashboard (Plotly.js renders the JSON)
Cloudflare Worker + KV  →  the email-brief on/off toggle (optional)
```

Data & news are pre-computed by the scheduled job into `site/data/*.json`; the
static site just renders them. Nothing runs live, so nothing sleeps.

---

## Deploy it (~15 min, one time)

Requires a **free GitHub account**. Make the repo **public** so Actions + Pages are free.

```bash
# from this folder
gh repo create hk-property-radar --public --source=. --remote=origin --push
```
(or create the repo on github.com and `git push`.)

Then:

1. **Enable Pages:** repo **Settings → Pages → Build and deployment → Source = GitHub Actions**.
2. **Add the DeepSeek key** (for AI news): **Settings → Secrets and variables → Actions → New repository secret** → name `DEEPSEEK_API_KEY`, value = your key from <https://platform.deepseek.com>. *(Skip and the news feed still works from RSS, just without AI summaries.)*
3. **Run it once:** **Actions → “Refresh & deploy” → Run workflow**. When it finishes, your site is at `https://<username>.github.io/hk-property-radar/`.

That's it — from then on it updates itself (see schedule below).

### Secrets

| Secret | For | Required? |
|---|---|---|
| `DEEPSEEK_API_KEY` | AI news summaries + Top-3 | Recommended |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | sending the email brief | Only for email |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_KV_NAMESPACE_ID` | reading email-brief subscribers | Only for email |

> ⚠️ You set these in GitHub's UI. Never put keys in code. The Gmail value is an
> **App Password** (Google Account → Security → App passwords), not your login password.

---

## How it updates (self-updating)

`.github/workflows/update.yml` runs `pipeline/run_all.py`:

- **Daily 08:00 HKT** — refresh the AI news feed (and, when converters are wired, RVD data).
- **Weekly (Mon)** — heavier data refresh.
- **On demand** — Actions → Run workflow.

Each run rebuilds `site/data/*.json`, commits it (which keeps the schedule alive —
GitHub disables idle crons after 60 days), and redeploys Pages.

---

## Run locally (for development)

```bash
pip install -r requirements.txt
python pipeline/build_figures.py     # data/clean/*.csv  → site/data/*.json
python pipeline/news_rag.py          # → site/data/news.json + top3.json
python -m http.server 8080 --directory site   # open http://localhost:8080
```

---

## Email brief (optional, self-serve)

The in-app **⚙ Settings** panel lets YR turn an emailed "Top 3 moves" on/off himself.
To activate delivery: deploy the tiny Cloudflare Worker in `worker/` (free tier),
put its URL in `WORKER_URL` at the top of `site/app.js`, and add the Gmail +
Cloudflare secrets above. See `worker/README.md`. Until then the toggle saves the
preference and the app tells him delivery isn't connected yet.

---

## Data sources (self-sourced live — no local/CITIC dependency)

`pipeline/fetch_rvd.py` downloads fresh every run and reshapes into `data/clean/`:

- **RVD open data** (`rvd.gov.hk/datagovhk/*.csv`) — price index (**monthly** `1.4M` / quarterly `1.4Q`), rent index (`1.3*`), average price/rent by class × region (`1.2Q`/`1.1Q`), stock/vacancy/completions. Rental **yield is derived** (rent × 12 ÷ price).
- **HKMA open API** (`api.hkma.gov.hk`) — 1-month **HIBOR**, daily.
- **Google News RSS** — buyer-relevant headlines (in `news_rag.py`).

The repo also ships a small `data/clean/` snapshot so it renders before the first fetch; every scheduled run overwrites it with live official data.

**Districts tab:** RVD has **no official 18-district residential price series** (only flat-class × 3 regions — HK Island / Kowloon / NT). So the tab shows the **official RVD 3-region average** live now. The true **18-district new-launch** view (HK$/sq.ft) will come from the government **SRPE first-hand register** — its scraper is scaffolded in `pipeline/fetch_first_hand.py` (API entry points documented there); it drops into the pipeline the moment it lands.

**Transaction volume** (primary/secondary) is temporarily off — it comes from the **Land Registry**, not RVD, and will be wired next.

---

## Repo map

```
pipeline/   build_figures.py (CSV→JSON) · news_rag.py (news) · run_all.py (orchestrator)
            districts_en.py (area→18-district) · make_icons.py · common.py · converters/
site/       index.html · app.js · styles.css · manifest + icons + service-worker · data/*.json
worker/     Cloudflare Worker for the email-brief toggle
data/clean/ seeded cleaned CSVs (the pipeline's input)
.github/workflows/update.yml  the scheduled refresh + deploy
```

## Cost

| | | |
|---|---|---|
| GitHub Actions + Pages (public repo) | **$0** | Cloudflare Worker+KV (free tier) | **$0** |
| Gmail SMTP | **$0** | Google News RSS | **$0** |
| **DeepSeek tokens** | **the only cost** — cents/day | | |
