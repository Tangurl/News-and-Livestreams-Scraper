# Category Normalization & Channel Mapping Guide

This document defines the strict classification schema and channel-by-channel category resolution rules used across all scrapers in this repository.

---

## 🎯 Target Standard Categories 

All scraped news across all media channels are normalized into the following 7 standard categories:

1. **การเมือง** (Politics & Policy)
2. **เศรษฐกิจ** (Economy, Business, Finance, Wealth, Tech Markets, Real Estate, SME)
3. **สังคม** (Society, Domestic News, Regional, Public Health, Weather, Environment, Disasters)
4. **อาชญากรรม** (Crime, Investigative Journalism, Justice, Fraud, Court Cases)
5. **กีฬา** (Sports & Athletics)
6. **ต่างประเทศ** (World & International News, ASEAN)
7. **อื่นๆ** (Entertainment, Lifestyle, PR/Public Relations, Lottery/Horoscope, General/Special Reports)

---

## 🔄 Global Category Normalization Dictionary

| Original Extracted Category | Standard Target Category | Description & Common Sources |
| :--- | :--- | :--- |
| `การเมือง`, `politics`, `politic`, `policy`, `วิเคราะห์ การเมือง` | **การเมือง** | Political affairs, Parliament, Government, Policy |
| `เศรษฐกิจ`, `economy`, `economic`, `economics` | **เศรษฐกิจ** | Macroeconomics & Policy |
| `Wealth`, `finance`, `banking-finance`, `trading-investment`, `การเงิน` | **เศรษฐกิจ** | Finance, Stock Market, Investment (TNN, Kaohoon, Post Today) |
| `business`, `corporate`, `property`, `real-estate`, `ธุรกิจ`, `สังคมธุรกิจ` | **เศรษฐกิจ** | Corporate, Real Estate, Business News (Prachachat, Post Today) |
| `Smart SME`, `trade`, `Digital-business`, `เกษตร`, `เศรษฐกิจไทย` | **เศรษฐกิจ** | Trade, SME, Agriculture (Nation Thailand, Spring News, NBT) |
| `สังคม`, `ข่าวสังคม`, `social`, `general`, `in-country`, `ในประเทศ` | **สังคม** | Domestic & Society news (CH7, TNews, Banmuang) |
| `ภูมิภาค`, `ทั่วไทย`, `around-thailand`, `Bangkok`, `สกู๊ปสังคม` | **สังคม** | Regional / Bangkok news (Khaosod English, ThaiPBS, Workpoint) |
| `สาธารณภัย`, `ภัยพิบัติ`, `สิ่งแวดล้อม`, `Earth`, `Smart City` | **สังคม** | Disaster, Weather, Environment (TNN, NBT, Post Today) |
| `Health`, `สุขภาพ`, `เกาะติด COVID-19`, `พยากรณ์อากาศ` | **สังคม** | Public health & Weather forecasts (TNN, EJan) |
| `อาชญากรรม`, `crime`, `criminality` | **อาชญากรรม** | Crime & Legal cases |
| `investigative`, `สืบสวนเชิงลึก`, `ลักวิ่งชิงปล้น` | **อาชญากรรม** | Investigative crime & Law enforcement (Next News TH, EJan) |
| `กีฬา`, `sport`, `sports`, `วอลเลย์บอล` | **กีฬา** | All Sports & Competitions (TNews, Daily News, Thairath) |
| `ต่างประเทศ`, `foreign`, `abroad`, `world`, `World`, `international`, `asean` | **ต่างประเทศ** | International & ASEAN News (Khaosod English, TNN) |
| `เศรษฐกิจต่างประเทศ` | **ต่างประเทศ** | Global economic & international market news (Kaohoon) |
| `บันเทิง`, `บันเทิงไทย`, `ข่าวบันเทิง`, `entertainment` | **อื่นๆ** | Entertainment news (Amarin TV, TNews, Workpoint TODAY) |
| `ไลฟ์สไตล์`, `ข่าวไลฟ์สไตล์`, `lifestyle`, `Smart Life`, `AI Today` | **อื่นๆ** | Lifestyle, Tech trends, Gadgets (Post Today, TNN) |
| `หวย`, `หวย ดวง ความเชื่อ`, `ตรวจหวยงวดล่าสุด`, `หวย ตรวจหวย` | **อื่นๆ** | Lottery & Horoscope (TNews, TNN, EJan) |
| `ประชาสัมพันธ์`, `กิจกรรม&ข่าวประชาสัม...`, `รายงานพิเศษ`, `ศิลปะ` | **อื่นๆ** | Public announcements, Special reports, Arts (NBT, TNN) |
| `ท่องเที่ยว`, `tourism`, `travel`, `ยานยนต์` | **อื่นๆ** | Travel & Automotive (Nation Thailand, EJan) |
| `ข่าวในพระราชสำนัก`, `คอลัมนิสต์`, `TNN Exclusive`, `อื่นๆ`, `ทั่วไป`, `-` | **อื่นๆ** | Columnists, Exclusive pieces, General misc. |

---

## 📺 Channel-by-Channel Coverage & Mapping Rules

### 1. Thairath (ไทยรัฐ)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ
- **Rule:** Direct 1-to-1 match.

### 2. MGR Online (ผู้จัดการออนไลน์)
- **Covered:** การเมือง, อาชญากรรม, กีฬา, ต่างประเทศ

### 3. Khaosod (ข่าวสด)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 4. Matichon (มติชน)
- **Covered:** การเมือง, เศรษฐกิจ, อาชญากรรม, กีฬา, ต่างประเทศ
- **Note:** ไม่มีหมวดสังคมแยกเฉพาะ (รวมอยู่ในข่าวทั่วไป/การเมือง)

### 5. Bangkok Biz News (กรุงเทพธุรกิจ)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, กีฬา, ต่างประเทศ
- **Note:** ไม่มีหมวดอาชญากรรมแยกเฉพาะ
- **Mapping:** `Finance / Business / Economics` ➡️ **เศรษฐกิจ**, `ทั่วไป` ➡️ **สังคม**

### 6. PPTV HD 36
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 7. Daily News (เดลินิวส์)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 8. ThaiPBS (ไทยพีบีเอส)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ, ภูมิภาค, ภัยพิบัติ, วิทยาศาสตร์เทคโนโลยี

### 9. CH7 (ช่อง 7HD)
- **Covered:** ในประเทศ, ต่างประเทศ, กีฬา
- **Mapping:** `ในประเทศ` ➡️ **สังคม**

### 10. T-NEWS (ทีนิวส์)
- **Covered:** สังคม, บันเทิง, ดวง, วอลเลย์บอล
- **Note:** ไม่มีอาชญากรรม, ไม่มีเศรษฐกิจ
- **Mapping:** `ข่าวสังคม` ➡️ **สังคม**, `วอลเลย์บอล` ➡️ **กีฬา**, `บันเทิงไทย / หวย ดวง ความเชื่อ` ➡️ **อื่นๆ**

### 11. Bangkok Post
- **Covered:** การเมือง, สังคม, เศรษฐกิจ, อาชญากรรม, กีฬา, ต่างประเทศ
- **Rule:** Direct 1-to-1 English translation (`crime` ➡️ `อาชญากรรม`, `business` ➡️ `เศรษฐกิจ`, etc.).

### 12. Naewna (แนวหน้า)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 13. AMARIN TV (อมรินทร์ทีวี)
- **Covered:** การเมือง, สังคม, อาชญากรรม, กีฬา, บันเทิง
- **Mapping:** `บันเทิง` ➡️ **อื่นๆ**

### 14. Komchadluek (คมชัดลึก)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 15. Thansettakij (ฐานเศรษฐกิจ)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, กีฬา, ต่างประเทศ
- **Note:** ไม่มีหมวดอาชญากรรม

### 16. ThaiPost (ไทยโพสต์)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 17. Kaohoon (ข่าวหุ้นธุรกิจออนไลน์)
- **Covered:** เศรษฐกิจไทย, เศรษฐกิจต่างประเทศ, ทั่วไป
- **Mapping:** `เศรษฐกิจไทย` ➡️ **เศรษฐกิจ**, `เศรษฐกิจต่างประเทศ` ➡️ **ต่างประเทศ**, `ทั่วไป` ➡️ **อื่นๆ**

### 18. Prachachat (ประชาชาติธุรกิจ)
- **Covered:** การเมือง, เศรษฐกิจ, ต่างประเทศ, ทั่วไป
- **Note:** ไม่มีอาชญากรรม, ไม่มีกีฬา
- **Mapping:** `Economic / Finance / Real-estate / Business` ➡️ **เศรษฐกิจ**, `News / ทั่วไป` ➡️ **อื่นๆ**

### 19. EJan (อีจัน)
- **Covered:** อาชญากรรม, สังคม, การเมือง, เศรษฐกิจ, ต่างประเทศ
- **Mapping:** `ลักวิ่งชิงปล้น` ➡️ **อาชญากรรม**, `วิเคราะห์ การเมือง` ➡️ **การเมือง**, `สุขภาพ / ยานยนต์ / หวย` ➡️ **อื่นๆ**

### 20. Nation Thailand
- **Covered:** Politics, Business, Economy, Social, World, Travel, Trade
- **Mapping:**
  - `general / social` ➡️ **สังคม**
  - `business / economy / corporate / trading-investment / banking-finance / property / tech / trade` ➡️ **เศรษฐกิจ**
  - `politics / policy` ➡️ **การเมือง**
  - `world / asean` ➡️ **ต่างประเทศ**
  - `tourism / travel` ➡️ **อื่นๆ**

### 21. Post Today (โพสต์ทูเดย์)
- **Covered:** ธุรกิจ, สังคมธุรกิจ, การเมือง, Smart City, Smart Life, Smart SME, AI Today
- **Note:** ไม่มีกีฬา, ไม่มีอาชญากรรม
- **Mapping:** `ธุรกิจ / สังคมธุรกิจ / Smart SME` ➡️ **เศรษฐกิจ**, `Smart City` ➡️ **สังคม**, `Smart Life / AI Today / ไลฟ์สไตล์` ➡️ **อื่นๆ**

### 22. TNN Thailand
- **Covered:** Wealth, Earth, World, Social, Sports, Tech, Health, Entertainment
- **Mapping:**
  - `Wealth` ➡️ **เศรษฐกิจ**
  - `Earth / Health` ➡️ **สังคม**
  - `World` ➡️ **ต่างประเทศ**
  - `Tech / บันเทิง / ตรวจหวย / TNN Exclusive` ➡️ **อื่นๆ**

### 23. Siamrath (สยามรัฐ)
- **Covered:** การเมือง, สังคม, เศรษฐกิจ, ต่างประเทศ
- **Note:** ไม่มีอาชญากรรม, ไม่มีกีฬา
- **Mapping:** `ภูมิภาค` ➡️ **สังคม**

### 24. Thai News (ไทยนิวส์)
- **Covered:** สังคม, ต่างประเทศ, อาชญากรรม, เศรษฐกิจ, การเมือง

### 25. MCOT (อสมท / สำนักข่าวไทย)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, อาชญากรรม, กีฬา, ต่างประเทศ

### 26. NationTV 22 (เนชั่นทีวี)
- **Covered:** การเมือง, สังคม, เศรษฐกิจ, ต่างประเทศ, กีฬา
- **Note:** ไม่มีอาชญากรรม

### 27. Hone Krasae (โหนกระแส)
- **Covered:** สังคม, อาชญากรรม, การเมือง
- **Note:** ไม่มีเศรษฐกิจ, ไม่มีต่างประเทศ, ไม่มีกีฬา
- **Mapping:** `ภูมิภาค` ➡️ **สังคม**

### 28. Spring News (สปริงนิวส์)
- **Covered:** เศรษฐกิจ, การเมือง, กีฬา
- **Note:** ไม่มีอาชญากรรม, ไม่มีสังคม, ไม่มีต่างประเทศ
- **Mapping:** `Digital-business` ➡️ **เศรษฐกิจ**

### 29. Khaosod English (ข่าวสดภาคภาษาอังกฤษ)
- **Covered:** Politics, Sports, Crime, Business, Bangkok, International/ASEAN
- **Mapping:**
  - `International + ASEAN` ➡️ **ต่างประเทศ**
  - `Business` ➡️ **เศรษฐกิจ**
  - `Bangkok` ➡️ **สังคม**
  - `Politics` ➡️ **การเมือง**
  - `Crime` ➡️ **อาชญากรรม**
  - `Sports` ➡️ **กีฬา**

### 30. Korat Daily (โคราชคนอีสาน)
- **Covered:** การเมือง, เศรษฐกิจ, สังคม, กีฬา
- **Note:** ไม่มีอาชญากรรม, ไม่มีต่างประเทศ

### 31. Workpoint TODAY
- **Covered:** ข่าวบันเทิง, สกู๊ปสังคม, การเงิน, เศรษฐกิจ, ไลฟ์สไตล์
- **Mapping:** `สกู๊ปสังคม` ➡️ **สังคม**, `การเงิน` ➡️ **เศรษฐกิจ**, `ข่าวบันเทิง / ไลฟ์สไตล์` ➡️ **อื่นๆ**

### 32. Chiang Mai News (เชียงใหม่นิวส์)
- **Covered:** อาชญากรรม, เศรษฐกิจ, การเมือง, สังคม, ต่างประเทศ, กีฬา

### 33. Banmuang (บ้านเมือง)
- **Covered:** การเมือง, สังคม, อาชญากรรม, เศรษฐกิจ, กีฬา
- **Note:** ไม่มีต่างประเทศ
- **Mapping:** `ภูมิภาค` ➡️ **สังคม**

### 34. Next News TH
- **Covered:** สืบสวนเชิงลึก, เศรษฐกิจ, ต่างประเทศ
- **Note:** ไม่มีการเมือง, ไม่มีสังคม, ไม่มีกีฬา
- **Mapping:** `สืบสวนเชิงลึก` ➡️ **อาชญากรรม**

### 35. Thai PBS World
- **Covered:** Politics, Economy, Foreign, General, Around Thailand
- **Mapping:** `Around Thailand / General` ➡️ **สังคม**

### 36. NBT Connext (กรมประชาสัมพันธ์)
- **Covered:** สังคม, การเมือง, เศรษฐกิจ, ต่างประเทศ, สาธารณภัย, ประชาสัมพันธ์, เกษตร
- **Mapping:** `สาธารณภัย` ➡️ **สังคม**, `เกษตร` ➡️ **เศรษฐกิจ**, `ประชาสัมพันธ์ / ศิลปะ / ข่าวในพระราชสำนัก / อื่นๆ` ➡️ **อื่นๆ**

---

## ⚙️ Implementation Details
- Standard normalization is executed dynamically during `merge_csv_outputs()` in [`run_all.py`](run_all.py).
- All output datasets (`master_scraped_data.csv`, Google Sheets, and [`dashboard.html`](dashboard.html)) will consistently display only these clean standard categories.
