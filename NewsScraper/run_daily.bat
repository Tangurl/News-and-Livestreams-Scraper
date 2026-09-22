@echo off
:: Batch script to run the master orchestrator for yesterday's data (-d -1) on Windows
:: Redirects all outputs to daily_run.log in the same directory

:: Change directory to the folder containing this batch script
cd /d "%~dp0"

:: Execute the master scraper using the Windows virtual environment python
.venv\Scripts\python.exe run_all.py -d -1 >> daily_run.log 2>&1
