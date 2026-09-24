@echo off
echo ========================================
echo ThaiPBS News and Views Scraper Installer
echo ========================================

echo Building config.js for dashboard...

cd /d "%~dp0Dashboard"
python make_config.py

if errorlevel 1 (
    echo Failed to build config.js!
    pause
    exit /b 1
) else (
    echo config.js built successfully!
)

cd /d "%~dp0"

