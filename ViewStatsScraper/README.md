# 📊 Multi-Channel View Stats & Live Link Station (ViewStatsScraper)

A unified standalone toolset for **crawling live broadcast URLs** and **scraping real-time view counts** across **Facebook, YouTube, TikTok, and X (Twitter)** directly integrated with Google Sheets.

---

## 📋 Channel Schedule Schema (Columns A to G)

Data starts at **Row 2** (Row 1 contains headers):

| Col | Letter | Field | Expected Format |
| :---: | :---: | :--- | :--- |
| **1** | **A** | **วัน** | Date in `DD-MM-YY` format (e.g. `03-09-26` or `03-09-2026`) |
| **2** | **B** | **เวลา** | Time (e.g. `18:00`, `18.00`, `12.00-12.30`) |
| **3** | **C** | **รายการ** | Broadcast / Program Title |
| **4** | **D** | **Facebook Link** | Facebook Live URL |
| **5** | **E** | **Youtube Link** | YouTube Live URL |
| **6** | **F** | **X Link** | X (Twitter) Broadcast URL |
| **7** | **G** | **TikTok Link** | TikTok Live URL or profile |

---

## 📊 Target Google Sheet: "View Stats" Schema (Columns A to L)

Snapshots captured over time are appended to the **"View Stats"** tab:

| Col | Letter | Field | Source |
| :---: | :---: | :--- | :--- |
| **1** | **A** | **Date** | Capture date (`YYYY-MM-DD`) |
| **2** | **B** | **Time when capturing** | Timestamp of snapshot (`HH:MM:SS`) |
| **3** | **C** | **Channel's name** | **Extracted from source sheet tab name** |
| **4** | **D** | **Broadcast's name** | Active program title at capture time |
| **5** | **E** | **Facebook's live link** | URL from Column D |
| **6** | **F** | **Youtube's live link** | URL from Column E |
| **7** | **G** | **TikTok's live link** | URL from Column G |
| **8** | **H** | **X's live link** | URL from Column F |
| **9** | **I** | **Facebook's live view count** | Current live view count |
| **10** | **J** | **Youtube's live view count** | Current live view count |
| **11** | **K** | **TikTok's live view count** | Current live view count |
| **12** | **L** | **X's live view count** | Current live view count |

---

## 📁 Directory Structure

```
ViewStatsScraper/
├── view_stats_scraper.py         # View count scraper (Time-aware, multi-platform concurrency)
├── linkcrawler.py                # Automated live link crawler (Finds live URLs by program title)
├── channels.json                 # Base URLs and aliases for all 19 channels
├── modules/
│   ├── __init__.py
│   ├── sheets_writer.py          # Google Apps Script HTTP client (Built with urllib)
│   ├── facebook.py               # Facebook stream matching & scraper
│   ├── youtube.py                # YouTube stream matching & scraper
│   ├── x.py                      # X (Twitter) broadcast matching & scraper
│   └── utilities.py              # Thai text & date utilities
├── apps_script/
│   └── App.gs                    # Google Apps Script code to paste into Google Sheets
├── .env                          # Configuration
├── requirements.txt              # Optional dependencies
└── README.md
```

---

## ⚡ Setup: Google Apps Script

1. Open your Google Sheet -> **Extensions** -> **Apps Script**.
2. Replace the script editor content with the code from `apps_script/App.gs`.
3. Click **Deploy** -> **New deployment** -> Type: **Web app**:
   - **Execute as**: `Me`
   - **Who has access**: `Anyone`
4. Copy the Web app URL (ending in `/exec`) and paste it into `.env` as:
   ```env
   POST_SCRIPT_API="https://script.google.com/macros/s/.../exec"
   ```

---

## 🚀 Usage

### 1. Scrape Live View Counts (`view_stats_scraper.py`)
```bash
# Capture snapshot and append to 'View Stats'
python3 view_stats_scraper.py

# Preview only (Dry run)
python3 view_stats_scraper.py --dry-run

# Run every 5 minutes
python3 view_stats_scraper.py --loop --interval 300

# Custom concurrency per platform (default is 10)
python3 view_stats_scraper.py --concurrency 10
```

### 2. Crawl Live URLs by Program Name (`linkcrawler.py`)
```bash
# Crawl for default channel (Thai PBS)
python3 linkcrawler.py

# Crawl for any specific channel (from the 19 supported channels):
python3 linkcrawler.py --channel "3 HD"
python3 linkcrawler.py --channel "7 HD"
python3 linkcrawler.py --channel "PPTV"
python3 linkcrawler.py --channel "Workpoint TV"
python3 linkcrawler.py --channel "Thairath TV"

# Override custom URLs if needed:
python3 linkcrawler.py --channel "3 HD" --fb-url "https://www.facebook.com/Ch3Thailand/live_videos/"
```
Crawls Facebook, YouTube, and X, matches active streams against program titles in Column C, and writes the live URLs directly into Columns D (FB), E (YT), and F (X).
