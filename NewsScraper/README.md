# News Scraper Orchestrator

A multi-portal news scraping project utilizing Python and Selenium to scrape categories (politics, sport, economy, foreign news, etc.) from various Thai news outlets and merge them into a single, unified CSV file.

## 🚀 Windows Server Deployment Guide

Follow these setup steps to deploy the orchestrator to a Windows server:

### Step 1: Install Python & Chrome
1. Download and install **Python 3.10+** for Windows. Make sure to check the box **"Add Python to PATH"** during installation.
2. Install **Google Chrome** on the server.

### Step 2: Extract & Set up Virtual Environment
1. Extract the project ZIP folder on your server.
2. Open **Command Prompt** (cmd) inside the extracted project folder and run:
   ```cmd
   python -m venv .venv
   ```
3. Install the dependencies using the virtual environment's pip manager:
   ```cmd
   .venv\Scripts\pip install -r requirements.txt
   ```

### Step 3: Run the Orchestrator
You can run the script manually or through command scripts:

* **Run all scrapers manually** (merges everything):
  ```cmd
  .venv\Scripts\python run_all.py
  ```
* **Merge existing local CSVs only** (without running Selenium drivers):
  ```cmd
  .venv\Scripts\python run_all.py -m
  ```
* **Scrape specific date boundaries** (e.g. yesterday only):
  ```cmd
  .venv\Scripts\python run_all.py -d -1
  ```
* **Run in a daily loop at a designated time** (runs once immediately, then waits for designated time e.g. 09:00 Bangkok time):
  ```cmd
  .venv\Scripts\python run_all.py -d -1 --time "09:00"
  ```

### Step 4: Schedule Daily Execution
On Windows Server, you can use the built-in **Task Scheduler** to automate runs:
1. Open **Task Scheduler** and click **Create Basic Task**.
2. Set the trigger to **Daily** at your preferred time (e.g., **8:00 AM**).
3. Set the action to **Start a program** and browse to select the **`run_daily.bat`** file from your project directory.

---

## 🛠️ Project Structure
* `run_all.py`: The master orchestrator that triggers individual scrapers and handles merging/deduplication.
* `requirements.txt`: Python package requirements.
* `run_daily.bat`: Windows batch script for automated task scheduling.
* `run_daily.sh` / `com.thaipbs.scraper.daily.plist`: Mac configurations for automated running.
* `master_scraped_data.csv`: Output location of the merged dataset.
* `*-scrapers/`: Subdirectories containing individual scraper scripts for each news outlet.
