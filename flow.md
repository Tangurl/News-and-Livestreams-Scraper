# Flow การทำงานของโปรแกรม (News-and-Livestreams-Scraper)

เอกสารนี้สรุปว่าแต่ละส่วนของ project ทำงานอย่างไร และเชื่อมต่อกันอย่างไร
(รายละเอียดคำสั่ง/การตั้งค่าเพิ่มเติมดูได้ที่ `README.md` ของแต่ละโฟลเดอร์)

---

## 1. ภาพรวม

Project นี้มี 4 ระบบหลัก ทำงานแยกกันเป็น process ของใครของมัน แต่ใช้ข้อมูลร่วมกันผ่าน **Google Sheet** (ผ่าน Google Apps Script Web App `Dashboard/App.gs`) และใช้ `.env` ไฟล์เดียวที่ root

```
                     ┌──────────────────────────┐
  ผังรายการ กสชท ─▶  │  ProgramScheduleFetcher  │── ผังรายการ  ──┐
                     └──────────────────────────┘              │
                                                               ▼
                                                  ┌──────────────────────────┐
                                                  │   Google Sheet           │
                                                  │   (ผ่าน App.gs Web App)   │
                                                  │  - แท็บรายช่อง (A–G)       │
                                                  │  - View Stats            │
                                                  │  - Channel_Links /       │
                                                  │    Broadcast_Overrides   │
                                                  └──────────────────────────┘
                                                    ▲        ▲         │
               ลิงก์ Live (FB/YT/X/TikTok) ───────────┘        │         │
          ┌──────────────────────────┐                       │         ▼
          │ ViewStatsScraper/        │   Peak view count ────┘   ┌─────────────┐
          │  - linkcrawler.py        │                           │  Dashboard  │
          │  - view_stats_scraper.py │                           │ (HTML)      │
          └──────────────────────────┘                           └─────────────┘
                                                                         ▲
          ┌──────────────────────────┐       ข่าวที่รวมแล้ว                  │
          │ NewsScraper/run_all.py   │──▶ News Google Sheet ────────────┘
          └──────────────────────────┘   (Google Sheets API + token.json)
```

| ระบบ | หน้าที่ | Input | Output |
|---|---|---|---|
| `ProgramScheduleFetcher/` | ดึงผังรายการทีวีทุกช่อง | DTT Guide API | แท็บรายช่องใน Sheet (คอลัมน์ A–C) |
| `ViewStatsScraper/linkcrawler.py` | หาลิงก์ Live ของรายการที่กำลังออกอากาศ | ผังรายการจาก Sheet | ลิงก์ในคอลัมน์ D–G ของแท็บรายช่อง |
| `ViewStatsScraper/view_stats_scraper.py` | เก็บยอดคนดู Live สูงสุด (Peak) | ผังรายการ + ลิงก์จาก Sheet | แท็บ `View Stats` |
| `NewsScraper/run_all.py` | Scrape ข่าวจากเว็บข่าวไทย 37+ แห่ง | เว็บข่าว | `master_scraped_data.csv` + News Sheet |
| `Dashboard/` | แสดงผลข่าวและสถิติคนดู | News Sheet + App.gs | หน้าเว็บ `dashboard.html` |
| `CredentialsUtility/` | Login/Logout Facebook ลง Chrome Profile | ผู้ใช้ Login เอง | Chrome Profile ที่มี Session |

---

## 2. จุดเริ่มต้น: `Start.bat` (ที่ root)

ดับเบิลคลิก `Start.bat` แล้วจะทำงานตามลำดับนี้

1. **ตรวจ Python** – ถ้าไม่มี `python` ใน PATH จะแจ้งเตือนแล้วหยุด
2. **[1/7] ติดตั้ง dependencies** – `pip install -r requirements.txt` (ไฟล์เดียวที่ root)
3. **[2/7] ตรวจ Facebook Session** – รัน `python login_facebook.py --check` ใน `CredentialsUtility/`
   - ไม่ได้เช็คแค่ว่ามีโฟลเดอร์ Profile แต่เช็คว่ามี cookie `c_user` ที่ใช้ได้ (เพราะโฟลเดอร์ถูกสร้างทันทีที่เปิด Chrome แม้จะไม่ได้ Login)
   - exit code `0` = Login แล้ว → ข้ามไปขั้นต่อไป
   - exit code `1` = ยังไม่ Login → รัน `python login_facebook.py` ให้ผู้ใช้ Login (ดูหัวข้อ 3)
4. **[3/7] สร้าง `Dashboard/config.js`** – รัน `make_config.py` (ดูหัวข้อ 8)
5. **[4/7]–[7/7] เปิดหน้าต่าง cmd แยก 4 หน้าต่าง** ทำงานคู่ขนานกันตลอด
   | หน้าต่าง | คำสั่ง |
   |---|---|
   | Channel Scheduler | `python scheduler.py` |
   | Article Scraper | `python run_all.py -d -1 --time "01:00" -c 2` |
   | View Stats Watcher | `python view_stats_scraper.py --loop --interval 300 --refresh-schedules` |
   | LinkCrawler | `python linkcrawler.py --current-only --skip-x-except-thaipbs --workers 3` |
6. **เปิด `Dashboard/dashboard.html`** ใน browser

นอกจากนี้มี `LoginFacebook.bat` และ `LogoutFacebook.bat` ที่ root ไว้รัน Login/Logout แยกได้โดยไม่ต้องรัน `Start.bat`

---

## 3. CredentialsUtility (Facebook Chrome Profile)

Chrome Profile เก็บไว้ที่ `%LOCALAPPDATA%\LinkScraperAutomate\facebook_profile`
(กำหนดใน `FACEBOOK_PROFILE_DIR` ที่ `ViewStatsScraper/modules/utilities.py` – เก็บนอก repo เพื่อเลี่ยงปัญหา path ยาวเกิน MAX_PATH ของ Windows)

### 3.1 `login_facebook.py` (หรือ `LoginFacebook.bat`)

1. สร้างไฟล์ lock `manual_login.lock` (เก็บ PID) เพื่อบอก crawler ว่ากำลังมีคน Login อยู่ ห้ามเปิด Chrome ด้วย Profile เดียวกันมาชน
2. เปิด Chrome แบบเห็นหน้าจอ (ไม่ headless) ด้วย Profile ข้างบน ไปที่ `https://www.facebook.com/login`
3. ผู้ใช้ Login เอง แล้วกลับมากด **Enter** ที่ terminal
4. ตรวจ cookie `c_user` → แจ้งว่า Login สำเร็จหรือไม่
5. ปิด Chrome (`driver.quit()`) → Session ถูกบันทึกอยู่ใน Profile
6. ปลด lock

โหมด `--check`: ไม่เปิด Chrome แค่อ่าน cookie ใน Profile แล้วคืน exit code (ใช้โดย `Start.bat`)

### 3.2 `logout_facebook.py` (หรือ `LogoutFacebook.bat`)

1. ถ้าไม่มีโฟลเดอร์ Profile → แจ้งว่ายังไม่เคย Login แล้วจบ
2. เปิด Chrome ด้วย Profile นั้น ไปหน้า Facebook แล้วพยายามกด เมนูบัญชี → "ออกจากระบบ / Log Out" ให้อัตโนมัติ (best effort รองรับทั้ง UI ไทย/อังกฤษ)
3. ลบ cookies ทั้งหมด แล้วปิด Chrome
4. ลบโฟลเดอร์ Profile ทิ้งทั้งหมด

---

## 4. ProgramScheduleFetcher (ดึงผังรายการทีวี)

ไฟล์หลัก: `scheduler.py` (loop) เรียก `program.py` (ทำงาน 1 รอบ)

### 4.1 Flow ของ 1 รอบ (`program.run_fetch_cycle()`)

1. โหลด `.env` ที่ root (ถ้าไม่มีไฟล์ `.env` จะหยุดทันที)
2. **ดึงข้อมูล** – POST ไปที่ DTT Guide API (`DTT_URL`) พร้อม retry (`MAX_RETRIES`, `RETRY_WAIT`)
3. **แยก record** – ดึง `channelName`, `pgDate`, `pgBeginTime`, `pgTitle`
4. **Map ชื่อช่อง** – ใช้ `configuration/channels.txt` แปลงชื่อช่องจาก API เป็นชื่อแท็บใน Sheet
   (เช่น `องค์การกระจายเสียงและแพร่ภาพสาธารณะแห่งประเทศไทย > Thai PBS`) ช่องที่ไม่มีใน mapping จะใช้ชื่อตาม API และขึ้น warning
5. **จัดกลุ่ม + เรียงลำดับ** ตามวันที่และเวลา ตัดรายการซ้ำ
6. **ส่งขึ้น Sheet** – เรียก App.gs action `sync_programs_batch` ครั้งเดียวสำหรับทุกช่อง (App.gs จะเพิ่มเฉพาะแถวใหม่ ข้ามแถวที่มีอยู่แล้ว)
7. **คำนวณเวลารอบถัดไป** – หา "รายการสุดท้ายที่รู้" ของแต่ละช่อง แล้วเลือกช่องที่ผังหมดเร็วที่สุด

### 4.2 Loop ของ `scheduler.py`

```
เริ่ม → fetch ทันที → ได้เวลาผังหมดเร็วสุด (min_latest)
      → รอจนถึง min_latest − 10 นาที → fetch ใหม่ → ...
      (ถ้าคำนวณไม่ได้ จะรอ 30 นาทีแล้วลองใหม่)
```

### 4.3 โหมดลบข้อมูลเก่า

`python program.py --purge DD-MM-YYYY [--sheet "ชื่อแท็บ"]` → เรียก App.gs ให้ลบแถวก่อนวันที่กำหนดทันที (ไม่มี preview)

---

## 5. ViewStatsScraper – `linkcrawler.py` (หาลิงก์ Live)

### 5.1 เริ่มต้น

1. อ่าน argument (`--channel` ค่าเริ่มต้น `all`, `--current-only`, `--workers`, `--skip-x-except-thaipbs`, `--no-facebook-login` ฯลฯ)
2. โหลด `channels.json` (URL เริ่มต้นของ 19 ช่อง + ชื่อเรียกแทน)
3. ถ้า `--channel all` → `start_multi_channel_scheduler()` / ถ้าระบุช่อง → `start_live_scheduler()`

### 5.2 Loop หลัก (ทุก `--interval` วินาที ค่าเริ่มต้น 30)

1. **ดึงผังรายการทุกช่อง** จาก Sheet ผ่าน App.gs (มี local cache ใน `cache_manager.py`)
2. **ดึง link config** (`Channel_Links` และ `Broadcast_Overrides` ใน Sheet)
3. **หารายการที่ถึงเวลา** (`process_due_schedules()`)
   - เวลาเริ่มค้นหา = เวลาในผัง + delay 4 นาที (เผื่อทีมขึ้นสตรีม)
   - เวลาจบรายการ = เวลาเริ่มของรายการถัดไป (ไม่เกิน 4 ชม.) หรือ +3 ชม. ถ้าไม่มีรายการถัดไป
   - `--current-only` → เลือกเฉพาะรายการที่กำลังออกอากาศอยู่ตอนนี้
   - ถ้าเคยเจอลิงก์ครบแล้ว หรือรายการจบไปแล้ว → ข้าม
   - เช็ค local cache ก่อน เผื่อเคยเจอลิงก์ในรอบก่อน/ก่อนรีสตาร์ท
4. **เลือก URL เป้าหมาย** (`link_resolver.py`) ตามลำดับความสำคัญ
   1. Broadcast Override (ระบุเฉพาะรายการ)
   2. Channel Links ใน Sheet (ระบุได้หลาย URL)
   3. ค่าเริ่มต้นใน `channels.json`
5. **Crawl แต่ละแพลตฟอร์ม** (ทำหลายช่องพร้อมกันได้สูงสุด `--workers` ช่อง ห้ามเกิน 5)
   - Facebook: `scrape_live_videos()` → `find_matching_video()` (ดูหัวข้อ 6)
   - YouTube: `scrape_youtube_streams()` → `find_matching_youtube_video()`
   - X: `scrape_x_live_videos()` → `find_matching_x_video()` (ข้ามถ้า `--skip-x` หรือ `--skip-x-except-thaipbs` และไม่ใช่ Thai PBS)
   - TikTok: ใช้ลิงก์ profile/live จาก config
   - กรณีพิเศษ "โหนกระแส": ต้องเป็น Live จริง หรือมีคำว่า LIVE/สด ป้องกันไปจับคลิปย้อนหลัง
6. **รอบที่ 2** – refetch หน้าเว็บใหม่เฉพาะแพลตฟอร์มที่ยัง NOT FOUND แล้วจับคู่อีกครั้งเดียว
7. **เขียนผลลง Sheet** – `write_batch_row_results()` อัปเดตคอลัมน์ D (FB), E (YT), F (X), G (TikTok) ของแท็บช่องนั้น และบันทึกลง local cache
8. แสดงนับถอยหลังรายการถัดไป แล้ววนรอบใหม่ (`--once` = ทำรอบเดียวแล้วจบ)

---

## 6. Facebook Session ใน linkcrawler (`modules/facebook.py`)

### 6.1 ตัดสินว่าจะใช้ Chrome Profile ที่ Login ไว้หรือไม่ (`should_use_facebook_login()`)

1. ถ้าสั่ง `--no-facebook-login`, `SKIP_FACEBOOK_LOGIN=true` หรือ `facebook_login_targets.json` มี `"enabled": false` → ใช้ Guest ทุกช่อง
2. ดึง `<x>` จาก URL `https://www.facebook.com/watch/<x>/`
3. ถ้า `<x>.lower().strip()` มีคำใดคำหนึ่งใน `FACEBOOK_LOGIN_PAGE_KEYWORDS` → ใช้ Profile ที่ Login ไว้
   - ค่าปัจจุบัน: `("thaipbs", "thairath", "hks2017", "one")`
   - `hks2017` คือ URL เพจ Live ของโหนกระแสโดยตรง (`https://www.facebook.com/watch/HKS2017/`)
4. นอกนั้น → ใช้ Clean Guest Session (เหมือน Incognito)

### 6.2 ลำดับการ crawl Facebook (`scrape_live_videos()`)

1. ถ้าต้อง Login และเคยหลุดไว้ → `maybe_restore_facebook_session()` ลองกู้ Session ก่อน
2. ใช้ Profile ก็ต่อเมื่อ ต้อง Login **และ** ไม่ได้หลุด Login **และ** ไม่ติด Action Block ในรอบนี้
   (ถ้าใช้หลาย worker จะ clone Profile ให้แต่ละ worker แยกกัน)
3. เปิด Chrome แบบ headless → หน้า Timeline เพจ → หน้า Watch/Videos → fallback ไป `live_videos`
4. ระหว่างโหลด ตรวจสถานะ
   - `check_and_handle_logged_out()` – เจอหน้า Login / Checkpoint / "Continue as..." = หลุด Login
   - `check_and_handle_temporarily_blocked()` – เจอ Action Block → worker อื่นในรอบเดียวกันสลับไปใช้ Guest
5. ดึงรายการวิดีโอ (ชื่อ, คำอธิบาย, สถานะ Live, เวลา) แล้วให้ `find_matching_video()` ให้คะแนนเทียบกับชื่อรายการในผัง

### 6.3 ระบบ Login ซ้ำอัตโนมัติเมื่อหลุด

```
พบว่าหลุด Login
   │
   ├─ FB_AUTO_LOGIN=true และมี FB_EMAIL / FB_PASSWORD ใน .env ?
   │     └─ attempt_facebook_auto_relogin()
   │          - ข้ามถ้ามีหน้าต่าง login_facebook.py เปิดค้างอยู่ (เช็ค manual_login.lock)
   │          - เว้นระยะ FB_LOGIN_COOLDOWN_MINUTES (ค่าเริ่มต้น 30 นาที) ระหว่างแต่ละครั้ง
   │          - เปิด Chrome ด้วย Profile หลัก กรอก email/password แบบพิมพ์ทีละตัว
   │            (รองรับทั้งฟอร์มเต็ม และหน้า "Continue as..." ที่ขอแค่ password)
   │
   ├─ สำเร็จ → กลับมาใช้ Profile ที่ Login ไว้
   └─ ไม่สำเร็จ → ใช้ Guest ต่อไป + แจ้งให้รัน LoginFacebook.bat
         └─ ทุกรอบถัดไป maybe_restore_facebook_session() จะเช็คว่า
              - ไฟล์ Cookies ใน Profile ถูกแก้หลังเวลาที่หลุด (= ผู้ใช้รัน LoginFacebook.bat แล้ว) → กลับมาใช้ Profile
              - หรือพ้น cooldown แล้ว → ลอง Auto Re-Login อีกครั้ง
```

### 6.4 Screenshot

`dismiss_login_popup()` มีพารามิเตอร์ `debug_screenshot_path` ไว้ถ่ายภาพหน้าจอหลังปิด popup แต่มีไว้ **debug ด้วยมือเท่านั้น** โค้ด production ไม่ได้เรียกใช้ และไม่ต้องอ้างอิงถึงในการทำงานจริง

---

## 7. ViewStatsScraper – `view_stats_scraper.py` (เก็บยอดคนดู)

### 7.1 Flow ของ 1 รอบ (`run_scrape_cycle()`)

1. **ดึงผังรายการทุกช่อง** จาก Sheet (`--refresh-schedules` = บังคับดึงใหม่ ไม่ใช้ cache, ถ้าเน็ตล่มจะ fallback ไปใช้ cache เก่า)
2. **อ่าน local cache ของลิงก์** ที่ linkcrawler หาเจอ + ดึง link config (Channel Links / Overrides)
3. **หารายการที่กำลังออกอากาศ** ของแต่ละช่อง (`find_active_program_for_channel()`)
   - รายการ A active ถ้า `เวลาเริ่ม A ≤ ตอนนี้ < เวลาเริ่มรายการถัดไป` (รองรับรูปแบบ `12:00-12:30`)
4. **Scrape ยอดคนดูพร้อมกันหลายช่อง** (`ControlledScraper` จำกัด concurrency แยกต่อแพลตฟอร์ม)
   - Facebook: เรียก embed plugin `facebook.com/plugins/video.php` แล้วอ่าน `viewerCount` (ไม่ต้องเปิด Chrome)
   - YouTube / TikTok / X: ดึงจากหน้าเว็บ/ API ของแต่ละแพลตฟอร์ม
5. **จัดหมวดหมู่รายการ** ด้วยโมเดล ML (`genre_classify/.../genre_clf_newtax.joblib`)
6. **แสดงตารางสรุป** ใน console
7. **เขียนลงแท็บ `View Stats`** – เช็คความจุ Sheet ก่อน (`ensure_capacity`) แล้วเรียก App.gs `append_view_stats` ซึ่งจะ upsert เก็บเฉพาะ **ยอดคนดูสูงสุด (Peak) + เวลาที่ Peak** ของแต่ละรายการ/แพลตฟอร์ม

### 7.2 Loop

`--loop --interval 300` → ทำรอบใหม่ทุก 5 นาที

### 7.3 สคริปต์เสริม

- `backfill_genres.py` – รันครั้งเดียว เติมหมวดหมู่ (คอลัมน์ D) ให้แถวเก่าใน `View Stats` ที่ยังว่าง
- `tests/` – unit test และ `test_facebook_session.py` สำหรับตรวจว่า Session Facebook ยังใช้ได้

---

## 8. NewsScraper – `run_all.py` (รวมข่าว)

### 8.1 Flow ของ 1 รอบ (`run_pipeline()`)

1. **หา scraper** – ค้นทุกไฟล์ใน `*-scrapers/` (หรือเฉพาะ `--channel` ที่ระบุ)
2. **รัน scraper แบบขนาน** – แต่ละไฟล์รันเป็น subprocess แยก (Selenium), จำกัดจำนวนด้วย `-c` และมี timeout ต่อไฟล์ (`-t`)
   - บน Windows ใช้ Job Object ผูก process ลูกไว้ ถ้ากด Ctrl+C จะ kill ทั้งหมด
   - แต่ละ scraper เขียน CSV ของตัวเอง
3. **รวมไฟล์** (`merge_csv_outputs()`)
   - รวม CSV ทุกเว็บเป็น `master_scraped_data.csv`
   - ปรับชื่อหมวดหมู่ให้เป็นมาตรฐาน, แปลงวันที่ไทย
   - ตัดข่าวซ้ำด้วย URL และเรียงจากใหม่ไปเก่า
4. **Sync ขึ้น Google Sheet** (`sync_to_google_sheet()`) ด้วย Google Sheets API + `token.json`
   - Sheet ID จาก `NEWS_SHEET_ID` (หรือ `--sheet-id`)
   - ถ้าไม่มี `token.json` → ทำ CSV ในเครื่องได้ แต่ข้ามการ sync
5. แสดงตารางสรุปและเวลาที่ใช้

### 8.2 ช่วงวันที่และ Loop

- `-d 0` (ค่าเริ่มต้น) = วันนี้, `-d 7` = 7 วันย้อนหลัง, `-d -1` = เมื่อวานเท่านั้น
- `--time "01:00"` = รันทันที 1 ครั้ง แล้วรอรันทุกวันตามเวลาที่กำหนด (เวลาไทย)
- `-m` = รวม CSV ที่มีอยู่อย่างเดียว ไม่ scrape ใหม่

---

## 9. Dashboard

### 9.1 `make_config.py`

อ่าน `.env` ที่ root แล้วสร้าง `Dashboard/config.js` โดย export **เฉพาะ** `NEWS_SHEET_ID` และ `STREAM_STATS_API` (ไม่ใส่ค่าลับอย่าง `FB_EMAIL` / `FB_PASSWORD`) ไฟล์นี้ถูก git-ignore

### 9.2 `dashboard.html`

หน้าเว็บไฟล์เดียว เปิดได้เลยไม่ต้องมี web server มี 2 หน้า
- **ข่าว (`page-news`)** – อ่าน News Sheet ผ่าน Google Visualization API (Sheet ต้องตั้งเป็น "Anyone with the link can view")
- **สถิติคนดู (`page-viewstats`)** – เรียก App.gs (`view_stats`, `get_link_config`, `save_link_config`) แสดงยอดคนดู/Peak เปรียบเทียบช่อง และแก้ไข link override ได้

### 9.3 `App.gs` (Google Apps Script Web App)

เป็นตัวกลางเดียวที่ทุกโปรแกรมใช้อ่าน/เขียน Sheet ผ่าน `doGet` / `doPost` ตาม `action` เช่น

| action | ผู้เรียก | หน้าที่ |
|---|---|---|
| `sync_programs_batch` | ProgramScheduleFetcher | เพิ่มผังรายการใหม่ทุกช่อง |
| `purge_before` / `purge_batch` | ProgramScheduleFetcher | ลบแถวเก่า |
| `get_all` | linkcrawler, view_stats_scraper | ดึงผังรายการทุกช่อง |
| `write_row` / `update_urls` | linkcrawler | เขียนลิงก์ Live ลงแท็บช่อง |
| `get_link_config` / `save_link_config` | ทุกตัว / Dashboard | Channel Links และ Broadcast Overrides |
| `ensure_capacity` | view_stats_scraper | ขยายแถวของ Sheet |
| `append_view_stats` | view_stats_scraper | upsert ยอด Peak ลง `View Stats` |
| `view_stats` | Dashboard | อ่านข้อมูล `View Stats` |
| `set_range` | backfill_genres.py | เขียนค่าลงช่วงที่กำหนด |

---

## 10. ไฟล์ตั้งค่าที่เกี่ยวข้อง

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `.env` (root) | ค่าตั้งค่าทุกระบบ: `STREAM_STATS_API`, `NEWS_SHEET_ID`, `CRAWLER_CONCURRENCY`, `FB_AUTO_LOGIN`, `FB_EMAIL`, `FB_PASSWORD`, `DTT_URL`, timeout ต่างๆ |
| `ProgramScheduleFetcher/configuration/channels.txt` | Map ชื่อช่องจาก API → ชื่อแท็บใน Sheet |
| `ViewStatsScraper/channels.json` | URL เริ่มต้นของ FB/YT/X/TikTok ของ 19 ช่อง |
| `ViewStatsScraper/facebook_login_targets.json` | เปิด/ปิดการใช้บัญชี Facebook ที่ Login ไว้ทั้งระบบ |
| `NewsScraper/.../token.json` | OAuth token สำหรับเขียน News Sheet |
| `%LOCALAPPDATA%\LinkScraperAutomate\facebook_profile` | Chrome Profile ที่มี Facebook Session |
| `%LOCALAPPDATA%\LinkScraperAutomate\manual_login.lock` | Lock ระหว่างผู้ใช้กำลัง Login ด้วยตัวเอง |
