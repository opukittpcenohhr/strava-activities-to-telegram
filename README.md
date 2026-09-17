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

Each post is an album: a map of the route, rendered by Mapbox, then the
activity's photos, captioned with the sport, name, distance, time, pace or speed
and your description.

Python 3.12+, Linux or macOS. Built on `uv`, stravalib, pyTelegramBotAPI, Typer,
OmegaConf and SQLite.

[Setup](#setup) · [Provisioning credentials](#provisioning-credentials) · [Operating](#operating) · [Limitations](#limitations) · [Development](#development)

## Setup

> **If you are setting up on a VM**, forward the port over SSH and work in that session:
>
> ```bash
> ssh -L 8000:127.0.0.1:8000 user@your-vm
> ```
>
> This is needed because Strava redirects to your local browser.

**1. Get the code** — install [uv](https://docs.astral.sh/uv/) and clone this repo.

**2. Install dependencies** — `uv sync --locked`.

**3. Write the configuration** — copy `config.example.yaml` to `config.yaml`, replace every `???`, `chmod 600` it.

- The `???` values come from [Provisioning credentials](#provisioning-credentials).
- It holds your client secret and bot token; keep it and `data/` private and out of chats and issues.
- Every field is required; nullable ones such as `sync.since` need an explicit `null`.
- `sync.require_photos` (`true` in the example) posts only activities that have photos. It gates the first post only — an activity already in the channel keeps updating even if its photos are deleted.
- `sync.max_updates` caps Telegram writes per pass, oldest activity first, so a backlog drains over several passes instead of flooding the channel.
- Relative paths resolve beside the file.
- Any field can be overridden per run: `strava-to-telegram sync sync.since=2026-09-01 logging.level=DEBUG`.

**4. Authorize Strava** — run `auth`, open the printed link, approve `activity:read`.

```bash
uv run --no-sync strava-to-telegram auth
```

**5. Run it by hand** — check the output before cron does it unattended.

```bash
uv run --no-sync strava-to-telegram post-last   # one post, ignoring every filter
uv run --no-sync strava-to-telegram sync        # one real pass
```

**6. Schedule it** — `crontab -e`:

```cron
MAILTO=""
*/15 * * * * $HOME/strava-activities-to-telegram/deploy/run-once.sh >> $HOME/strava-activities-to-telegram/data/cron.log 2>&1
```

- Use the path your clone actually has; the job fails silently if it points at nothing.
- The redirect is not optional: with `MAILTO=""` and no MTA, unredirected output is discarded.
- No `flock` needed; overlapping passes abort on the database lock.
- Every pass is a full scan; see [Limitations](#limitations) for what that costs against Strava's caps, and when to prefer `*/30`.

## Provisioning credentials

**Strava application** — register an app at [Strava API settings](https://www.strava.com/settings/api).

- Use `localhost` as the callback domain; set `strava.client_id` and `strava.client_secret`.

**Telegram bot** — talk to [BotFather](https://t.me/BotFather).

- Put its token in `telegram.bot_token`.
- Add the bot to the channel as an administrator that can post and edit.
- Set `telegram.channel_id` to the numeric `-100…` ID, not the username. From a message link `https://t.me/c/<number>/<message>`, it is `-100<number>`.

**Mapbox token** — sign up at [account.mapbox.com](https://account.mapbox.com) for the route maps.

- Copy the default public token (`pk.…`) into `map.token`.
- `map.style` picks the look: `mapbox/outdoors-v12` is Strava's, `mapbox/satellite-streets-v12` and `mapbox/dark-v11` also work.

## Operating

- `tail -f data/cron.log` — everything a pass printed. A pass with nothing new to post prints nothing, so an empty log is ambiguous on its own.
- `journalctl -u cron --since today` — whether cron fired at all. This is what tells "ran quietly" from "never ran".
- Failures are not caught: the traceback is already in `cron.log` and the pass exits 1.
- For one noisier run, override the level: `.venv/bin/strava-to-telegram sync logging.level=DEBUG`.

## Limitations

**Updates.** A post is edited only when the title, sport, distance or moving time
changes on Strava.

- The description is sent with the post and refreshed on edits, but never triggers one.
- Photos and the map are set at posting time and never change (see **Telegram**).
- `post-last` reposts the latest activity; the old message stays in the channel.

**Strava.** About 100 reads per 15 minutes, 1,000 per day.

- A pass costs `ceil(activities / 200)` reads for the scan, plus up to `2 × sync.max_updates` for what it posts. `*/15` fits ~2,000 activities; use `*/30` above that.
- Each new post or edit costs 2 more: the description and the photo URLs.
- Deleted or newly private activities get their text replaced with a notice, and only after a full successful scan.

**Mapbox.** 50,000 static images a month free, one per new post.

- A failed map still posts the photos, and logs the error.
- Set a usage limit in the dashboard to cap spend.

**Telegram.** Media is set when the post is sent and never changed.

- Albums cannot grow, so photos added later never show up.
- 10 items per album; the map takes one.
- Captions cap at 1,024 characters, so descriptions are cut at 400.
- Old messages cannot always be deleted, so a removed activity gets rewritten text and keeps its media.
- A crash between sending and saving the message ID can duplicate a post.

## Development

`AGENTS.md` holds the design decisions and constraints that changes must respect.
Read it first.

Running the tests and the style check:

```bash
uv run --no-sync pytest
uv run --no-sync black --check .
```
