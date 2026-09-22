#!/bin/bash
# Script to run the master orchestrator for yesterday's data (day -1)
# Redirects all outputs to daily_run.log in the same directory

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Change directory to the workspace root
cd "$SCRIPT_DIR" || exit 1

# Execute the master scraper using the virtual environment python
./.venv/bin/python3 run_all.py -d -1 >> daily_run.log 2>&1
