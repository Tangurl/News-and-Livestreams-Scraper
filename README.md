# 📡 Media & News Intelligence Platform

A comprehensive, unified intelligence platform combining automated television broadcast monitoring, multi-platform live stream view analytics, and multi-portal national news aggregation.

---

## 🌟 Overview & Architecture

This repository consolidates two major automation engines along with an interactive visualization dashboard:

```
BigProject/
├── dashboard.html              # 📊 Interactive Intelligence Dashboard (Live Google Sheet Sync)
├── ViewStatsScraper/           # 🔴 Live Broadcast Link Crawler & Real-Time View Count Scraper
│   ├── view_stats_scraper.py   # View count snapshot engine (Facebook, YouTube, TikTok, X)
│   ├── linkcrawler.py          # Automated live link crawler matching on-air program schedules
│   ├── channels.json           # Registry & URL aliases for all 19 monitored TV stations
│   ├── login_facebook.py       # Stealth Chrome driver for Facebook authenticated sessions
│   ├── test_facebook_session.py# Session validator & auto-relogin tester
│   ├── apps_script/            # Google Apps Script Web App backend (App.gs)
│   ├── genre_classify/         # AI broadcast genre classification (Scikit-Learn ML model)
│   ├── modules/                # Modular crawlers, sheets writer & utilities
│   ├── requirements.txt        # Python dependencies for ViewStatsScraper
│   └── README.md               # Detailed ViewStatsScraper documentation
├── NewsScraper/                # 📰 Multi-Portal Thai News Article Scraper Orchestrator
│   ├── run_all.py              # Master orchestrator triggering 37+ news portals
│   ├── *-scrapers/             # Dedicated scraper directories per news outlet
│   ├── run_daily.sh / .bat     # Automation scripts for macOS/Linux & Windows Server
│   ├── requirements.txt        # Python dependencies for NewsScraper
│   └── README.md               # Detailed NewsScraper deployment guide
├── .gitignore                  # Comprehensive security and cache exclusion rules
└── README.md                   # Platform master documentation
```

---

## 🚀 Recommended Commands & Execution Guide

### 1. Live Link Crawler (`linkcrawler.py`)

> 💡 **Channel Behavior:** Running `python linkcrawler.py` without arguments **scrapes ALL 19 channels by default** (default `--channel all`). It does NOT monitor just a single channel unless explicitly specified via `--channel "<Name>"`.

```bash
python linkcrawler.py --current-only --skip-x-except-thaipbs --workers 5
```

#### Why this is the recommended way:
* `--current-only`: Focuses exclusively on programs that are broadcasting **on-air right now** according to the channel's schedule, completely skipping older ended shows. This keeps the crawling cycle fast and ensures newly started live streams are picked up immediately.
* `--skip-x-except-thaipbs`: Based on extensive observation across Thai digital TV stations, **other channels do not stream their live broadcasts on X (Twitter)**. Searching X for all 19 channels wastes browser resources, causes unnecessary network latency, and increases the risk of rate-limiting. Thai PBS is the primary station that consistently pushes live streams to X.
* `--workers 5`: Enables concurrent multi-worker scraping to process channels in parallel, drastically reducing the total cycle duration.


> #### ⚠️ Strict Concurrency Limit (Workers $\le$ 5)
> `linkcrawler.py` features multi-worker concurrency via `--workers <num>` (or `CRAWLER_CONCURRENCY` in `.env`). **You MUST NOT set this higher than 5 workers.** Exceeding 5 concurrent browser instances significantly raises the chance of being rate-limited, IP-blocked, or hit with anti-bot checkpoints/CAPTCHAs by Facebook and X.

---

### 2. Live View Stats Scraper (`view_stats_scraper.py`)

```bash
python view_stats_scraper.py --loop --interval 300 --refresh-schedules
```

#### Why this is the recommended way:
* `--loop --interval <seconds>` (e.g. `300` for 5 minutes): Runs continuous, automated monitoring cycles directly inside the process without needing external OS schedulers (such as cron or Task Scheduler).
* `--refresh-schedules`: Re-queries Google Sheets at the start of the first cycle. Recommended to be used for the first time of the day to refresh cached schedules.

---

### 3. Multi-Portal News Scraper (`NewsScraper/run_all.py`)

To scrape articles published yesterday. It runs in a daily loop at a designated time (runs once immediately, then waits for designated time e.g. 09:00 Bangkok time)::
```bash
python run_all.py -d -1 --time "09:00"
```

#### Default Behavior:
* **Time Window:** By default, running `python run_all.py` without `-d` only scrapes today's articles (`days=0`). Passing `-d 7` instructs all scrapers to fetch news published over the past 7 days.
* **Auto-Merge & Sheet Update:**  When `run_all.py` completes its scraping run, it automatically triggers `merge_csv_outputs()`, which:
  1. Merges all 37+ news outlet CSV files into `master_scraped_data.csv`.
  2. Deduplicates articles by URL and sorts them chronologically (newest first).
  3. Automatically updates and synchronizes the entire master dataset to your connected Google Sheet (unless `--no-sheet` is explicitly passed).

---

## 📋 Google Sheets Schema & Structure

The platform uses structured Google Sheets for both input schedules and output analytics. Below is the schematic layout of each sheet.

### 1. Channel Schedule Tabs (Input / Crawler Output)
*Tab Name: `<Channel Name>`*

*Each of the 19 TV channels has its own dedicated tab (e.g., `Thai PBS`, `ONE`, `3 HD`, `7 HD`, `Thairath TV`, etc.).*

| Col | Header | Description / Format | Updated By |
|:---:|:---|:---|:---|
| **A** | `วัน` | Date string (e.g., `2026-09-22`) | Schedule / Admin |
| **B** | `เวลา` | Start Time of Live Broadcast (e.g., `07:00`) | Schedule / Admin |
| **C** | `รายการ` | Broadcast / Program Title (e.g., `วันใหม่ไทยพีบีเอส`) | Schedule / Admin |
| **D** | `Facebook Link` | Direct Facebook Live stream URL (or `-`) | `linkcrawler.py` |
| **E** | `Youtube Link` | Direct YouTube Live stream URL (or `-`) | `linkcrawler.py` |
| **F** | `X Link` | Direct X (Twitter) Live stream URL (or `-`) | `linkcrawler.py` |
| **G** | `TikTok Link` | Direct TikTok Live stream URL (or `-`) | `linkcrawler.py` |

---

### 2. View Stats Tab (Peak View Output)
*Tab Name: `View Stats` — captures highest concurrent live viewership per broadcast per platform.*

```
+---+--------------------+---------------------------------------------------------------+
|Col| Header Name        | Example / Description                                         |
+---+--------------------+---------------------------------------------------------------+
| A | วันที่                | 2026-09-22 (Broadcast date)                                   |
| B | ช่อง                | Thai PBS, ONE, 3 HD, 7 HD, etc.                               |
| C | ชื่อรายการ           | Broadcast program title                                       |
| D | หมวดหมู่             | Category / AI Genre (ข่าว, รายการวาไรตี้, ละคร, etc.)            |
| E | เวลาเริ่มในผัง        | Scheduled on-air time (e.g. 06:00)                            |
| F | Facebook           | Latest active Facebook live link                              |
| G | YouTube            | Latest active YouTube live link                               |
| H | TikTok             | Latest active TikTok live link                                |
| I | X (Twitter)        | Latest active X live link                                     |
| J | Facebook Peak Time | Timestamp of Facebook highest peak view (HH:MM:SS)            |
| K | Facebook Peak View | Highest recorded Facebook concurrent view count (Integer)     |
| L | YouTube Peak Time  | Timestamp of YouTube highest peak view (HH:MM:SS)             |
| M | YouTube Peak View  | Highest recorded YouTube concurrent view count (Integer)      |
| N | TikTok Peak Time   | Timestamp of TikTok highest peak view (HH:MM:SS)              |
| O | TikTok Peak View   | Highest recorded TikTok concurrent view count (Integer)       |
| P | X Peak Time        | Timestamp of X highest peak view (HH:MM:SS)                   |
| Q | X Peak View        | Highest recorded X concurrent view count (Integer)            |
+---+--------------------+---------------------------------------------------------------+
```

---

### 3. NewsScraper Master Sheet (Articles Aggregation)
*Tab Name: `Sheet1` (or master target sheet) — updated automatically after `run_all.py` completes.*

| Col | Header Name | Example Content | Description |
|:---:|:---|:---|:---|
| **A** | `date` | `2026-09-22 13:45:00` | Publication timestamp of the news article |
| **B** | `category` | `การเมือง`, `เศรษฐกิจ`, `อาชญากรรม` | News section / category |
| **C** | `channel` | `ThaiPBS`, `Thairath`, `Khaosod`, etc. | News agency or media outlet name |
| **D** | `article title` | `ครม. มีมติเห็นชอบโครงการ...` | Headline / Title of the article |
| **E** | `article link` | `https://www.thaipbs.or.th/news/content/...` | Direct article URL (used for deduplication) |

---

## 🛠️ Environment Configuration & Setup

### 0. Unified Environment Configuration (`.env`)

All modules (`NewsScraper`, `ViewStatsScraper`, and `ProgramScheduleFetcher`) pull their configuration from a single `.env` file located at the repository root.

Copy the template to create your `.env`:
```bash
cp .env.example .env
```

Key configuration variables in root `.env`:
* **`STREAM_STATS_API`**: Deployed Google Apps Script Web App URL (`.../exec`).
* **`GOOGLE_SHEET_ID`**: Target Google Sheet ID for `NewsScraper/run_all.py` (string between `/d/` and `/edit` in your spreadsheet URL).
* **`CRAWLER_CONCURRENCY`**: Concurrency limit for link crawler (Default: `5`).
* **`FB_AUTO_LOGIN`**: Enable automated re-authentication (`true`/`false`).
* **`FB_EMAIL` / `FB_PASSWORD`**: Facebook account credentials for authenticated live stream access.
* **`DTT_URL` / `REQUEST_TIMEOUT` / `APPS_SCRIPT_TIMEOUT`**: DTT Guide API & Apps Script timeout settings.

---

### 1. ProgramScheduleFetcher (Multi-Channel Program Schedule Fetcher & Uploader)

```bash
cd ProgramScheduleFetcher
pip install -r requirements.txt
```
* Deploy `App.gs` Google Apps Script Web App on your Google Sheet, then set `POST_SCRIPT_API` (or `GSHEET_URL`) in the root `.env`.

```bash
python scheduler.py
```

### Purge old records
Instead of `scheduler.py`, run `program.py` directly with `--purge DATE` (`DD-MM-YYYY`). This deletes matching rows immediately — there is no dry-run/preview mode.
```
python program.py --purge 1-9-2026                    # purge every mapped sheet
python program.py --purge 1-9-2026 --sheet "Thai PBS"  # only the given sheet(s)
```
Running `python program.py` with no flags does a single one-off fetch (no loop, no purge).

---

### 2. ViewStatsScraper Setup
```bash
cd ViewStatsScraper
pip install -r requirements.txt
```

#### Facebook Authentication (One-Time Setup)
```bash
python login_facebook.py
```
Opens Chrome with stealth flags. Log in to your Facebook account and press `[Enter]` in the console to save the encrypted session profile.

Validate the session at any time:
```bash
python test_facebook_session.py
```

---

### 3. NewsScraper Setup
```bash
cd NewsScraper
pip install -r requirements.txt
```

Google Sheets Authentication (`token.json`):
`NewsScraper` syncs merged articles to Google Sheets using the Google Sheets & Drive APIs via OAuth 2.0.

* **File Requirement:** Place your authorized `token.json` in either:
  * `NewsScraper/token.json` (recommended root level), OR
  * `NewsScraper/thaipbs-scrapers/token.json`
* **How `token.json` Works:**
  * It stores your authorized OAuth 2.0 credentials (`access_token`, `refresh_token`, client secrets).
  * `run_all.py` automatically refreshes the token using the refresh token when it expires.
* **Generating `token.json` (First-Time Setup):**
  1. Download OAuth 2.0 Client Credentials (`credentials.json`) from [Google Cloud Console](https://console.cloud.google.com/) with **Google Sheets API** and **Google Drive API** enabled.
  2. Place `credentials.json` into `NewsScraper/thaipbs-scrapers/`.
  3. Run any individual scraper (e.g., `python thaipbs-scrapers/ThaiPBS-scraper.py`) once. A browser window will open asking you to sign in with your Google account.
  4. Upon authorization, `token.json` is automatically generated and saved.
* **If `token.json` is Missing:** `run_all.py` will still scrape and generate `master_scraped_data.csv` locally, but will print a warning and skip updating the Google Sheet.

Target Google Sheet Configuration:
In the root `.env`, set:
```env
GOOGLE_SHEET_ID="<YOUR_NEWS_GOOGLE_SHEET_ID>"
```
`run_all.py` automatically reads `GOOGLE_SHEET_ID` from the root `.env`. You can also override it on the fly with `--sheet-id <ID>`.

---

### 4. Interactive Analytics Dashboard (`dashboard.html`) Setup

The dashboard is a single-file, zero-dependency HTML/JavaScript web application that streams data directly from Google Sheets (for news aggregation) and the Apps Script Web App (for live TV stream analytics).

Open `dashboard.html` in an editor and configure the variables at **lines 3290 and 3293**:

```javascript
// Google Sheet Configuration (Line 3290)
const SHEET_ID = "<YOUR_NEWS_GOOGLE_SHEET_ID>";

// Apps Script Web App (.env: POST_SCRIPT_API) — endpoint สำหรับหน้า "Live View Stats" (Line 3293)
const VIEW_STATS_API = "<YOUR_APPS_SCRIPT_WEB_APP_URL>";
```

1. **`SHEET_ID` (Line 3290)**:
   * Paste your **News Google Sheet ID** (the same Sheet ID configured in root `.env`).
   * Ensure the Google Sheet permissions are set to **"Anyone with the link can view"** so the dashboard can query the sheet via the Google Visualization API.

2. **`VIEW_STATS_API` (Line 3293)**:
   * Paste your deployed **Google Apps Script Web App URL** (`https://script.google.com/macros/s/.../exec`).
   * This is **the exact same URL** set in root `.env` under `POST_SCRIPT_API`.
   * Powers real-time live view counts, peak statistics, channel comparisons, and link overrides.

3. **Running the Dashboard**:
   * Simply double-click `dashboard.html` or open it in any web browser (Chrome, Edge, Safari, Firefox).
   * No web server or build step required!

---

## 🔒 Security & Privacy Practices

* **Never commit credentials**: All `.env` files, OAuth tokens (`token.json`), and service credentials are strictly excluded via `.gitignore`.
* **Sample Configurations**: Always distribute configurations using `.env.example`.
* **Profiles & Cache**: Browser profile caches and local storage folders (`LinkScraperAutomate/`, `cache/`) are ignored by version control.