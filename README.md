# Strava activities to Telegram

A small Python CLI that reads your Strava activities, posts text summaries to a
Telegram channel, and edits those posts when the summary changes.

Activities only. Nothing else in your Strava account — friends, kudos, comments,
segments, clubs — is read or posted.

```bash
uv run --no-sync strava-to-telegram auth      # One-time Strava authorization
uv run --no-sync strava-to-telegram post-last # Post the latest activity, ignoring all filters
uv run --no-sync strava-to-telegram sync      # One synchronization pass
```

Each `sync` is a single pass that exits; cron supplies the schedule, and SQLite
holds the OAuth tokens and the activity-to-message mapping between passes. There
is no daemon and nothing to supervise.

Only the fields in the summary — title, sport, date, distance, moving time —
trigger edits. Activities that disappear from Strava have their post text
replaced with an unavailable notice rather than deleted.

Python 3.12+, Linux or macOS. Built on `uv`, stravalib, pyTelegramBotAPI, Typer,
OmegaConf and SQLite.

## Setup

**1. Install** — `uv sync --locked`.

**2. Configure** — copy `config.example.yaml` to `config.yaml`, replace every `???`, `chmod 600` it.

- It holds your client secret and bot token; keep it and `data/` private and out of chats and issues.
- Every field is required; nullable ones such as `sync.since` need an explicit `null`.
- Relative paths resolve beside the file.
- Any field can be overridden per run: `strava-to-telegram sync sync.since=2026-09-01 logging.level=DEBUG`.

**3. Telegram** — create a bot with [BotFather](https://t.me/BotFather).

- Put its token in `telegram.bot_token`.
- Add the bot to the channel as an administrator that can post and edit.
- Set `telegram.channel_id` to the numeric `-100…` ID, not the username. From a message link `https://t.me/c/<number>/<message>`, it is `-100<number>`.

**4. Strava** — register an app at [Strava API settings](https://www.strava.com/settings/api).

- Use `localhost` as the callback domain; set `strava.client_id` and `strava.client_secret`.
- Run `auth`, open the printed link, approve `activity:read`. A temporary local listener catches the redirect and stores the tokens; your password is only entered on Strava. Refreshes are automatic after that.
- On a VM, tunnel first and run `auth` in that session: `ssh -L 8000:127.0.0.1:8000 user@your-vm`.

**5. Schedule** — set `sync.since` (`null` posts all history), run one `sync` by hand, then `crontab -e`:

```cron
MAILTO=""
*/15 * * * * $HOME/strava-activities-to-telegram/deploy/run-once.sh >> $HOME/strava-activities-to-telegram/data/cron.log 2>&1
```

- The redirect is not optional: with `MAILTO=""` and no MTA, unredirected output is discarded.
- No `flock` needed; overlapping passes exit cleanly on the database lock.
- Every pass is a full scan, costing about `ceil(activities / 200)` Strava reads. At `*/15` that is 96 passes a day — e.g. ~960 reads for 2,000 activities, which was close to the daily cap when this was written. Check the limits on your own app page and drop to `*/30` if it is tight.

## Operating

- `tail -f data/cron.log` — everything a pass printed. A pass with nothing new to post prints nothing, so an empty log is ambiguous on its own.
- `journalctl -u cron --since today` — whether cron fired at all. This is what tells "ran quietly" from "never ran".
- Failures are not caught: the traceback is already in `cron.log` and the pass exits 1.
- For one noisier run, override the level: `.venv/bin/strava-to-telegram sync logging.level=DEBUG`.

## Development

`AGENTS.md` holds the design decisions and constraints that changes must respect.
Read it first.

Running the tests:

```bash
uv run --no-sync pytest
```

`pytest` comes from the `dev` group, which `uv sync --no-dev` skips on the VM.
