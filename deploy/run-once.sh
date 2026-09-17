#!/bin/bash
# One synchronization pass, scheduled by cron. See "Setup" in README.md.
#
# Cron redirects this script's output to data/cron.log, so everything below writes
# plainly to stdout/stderr and lets the caller decide where that lands.
cd "$(dirname "$0")/.." || exit 1

exec .venv/bin/strava-to-telegram sync
