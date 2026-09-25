@echo off
setlocal
set "ROOT=%~dp0"
title ThaiPBS Launcher

echo ========================================
echo  ThaiPBS News and Views Scraper
echo ========================================

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found! Please install Python and ensure it is in your PATH.
    pause
    exit /b 1
)

rem Facebook Chrome profile (must match FACEBOOK_PROFILE_DIR in ViewStatsScraper\modules\utilities.py)
set "FB_PROFILE=%LOCALAPPDATA%\LinkScraperAutomate\facebook_profile"
if exist "%FB_PROFILE%\Default\" (
    echo [0/5] Facebook Chrome profile found: %FB_PROFILE%
) else (
    echo [0/5] Facebook Chrome profile not found. Please log in to Facebook...
    pushd "%ROOT%CredentialsUtility"
    python login_facebook.py
    popd
)
echo.

echo [1/5] Building config.js for dashboard...
pushd "%ROOT%Dashboard"
python make_config.py
if errorlevel 1 (
    echo Failed to build config.js!
    popd
    pause
    exit /b 1
)
popd
echo config.js built successfully!
echo.

echo [2/5] Starting Channel Scheduler...
start "Channel Scheduler" /D "%ROOT%ProgramScheduleFetcher" cmd /k python scheduler.py

echo [3/5] Starting Article Scraper...
start "Article Scraper" /D "%ROOT%NewsScraper" cmd /k python run_all.py -d -1 --time "01:00" -c 2

echo [4/5] Starting View Stats Watcher (every 5 minutes)...
start "View Stats Watcher" /D "%ROOT%ViewStatsScraper" cmd /k python view_stats_scraper.py --loop --interval 300 --refresh-schedules

echo [5/5] Starting LinkCrawler (5 workers)...
start "LinkCrawler" /D "%ROOT%ViewStatsScraper" cmd /k python linkcrawler.py --current-only --skip-x-except-thaipbs --workers 3

echo.
echo ========================================
echo [DONE!] ThaiPBS News and Views Scraper
echo ========================================
start "" "%ROOT%Dashboard\dashboard.html"