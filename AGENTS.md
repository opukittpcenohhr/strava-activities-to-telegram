# Rules of the project

`README.md` says what this tool does and how to run it. This file is the rules for
changing it. They exist because each one was decided once, with a reason; do not
reverse one silently.

## Design

1. **Start with the simplest thing that works.** Add complexity only when something
   concrete demands it. This is a single-user personal tool: abstractions and
   defences against hypothetical problems cost more to read and maintain than the
   risk they remove.
2. **Lead with the simple option and state what it costs** rather than proposing the
   defensive design with simplicity as a fallback. Raise a risk once, with evidence,
   then implement the decision without relitigating it. A free structural guarantee
   is still worth pointing out; "this could go wrong someday" is not.
3. **cron, not a daemon.** `sync` performs one pass and exits; `deploy/run-once.sh`
   plus a crontab line supplies the schedule. No polling loop, no signal handling,
   no systemd unit, no container.
4. **Credentials live in `config.yaml`**, not in separate files. The trade was
   accepted knowingly: never log or print a config object, and never add a flag that
   dumps the loaded configuration.
5. **Do not sanitise YAML parser errors.** PyYAML reports position and structure
   rather than scalar values, and its line numbers are worth more than its one leak
   shape: an undefined alias, which needs a credential starting with `*`.

## Failure handling

6. **`main()` catches nothing.** Failures propagate, Python prints the traceback, and
   the process exits 1, which is what cron logs. Do not add a handler that reduces
   this to one line.
7. **`pretty_exceptions_enable=False` on the Typer app is load-bearing**, not
   cosmetic. Typer's rich tracebacks render local variables, and those locals hold
   the bot token and client secret loaded from `config.yaml`. Turning it on would
   write both into `cron.log` on every failure.
8. **Library exceptions must not escape `telegram.py`.** It reaches the Bot API
   through `requests`, whose messages embed the request URL, and the bot token is in
   that URL's path. Every call converts them to locally written messages and
   re-raises with `from None`. `tests/test_telegram.py` asserts this.
9. **Failed sends retry automatically.** Post statuses are `rejected`, `sent`, and
   `removed`; do not reintroduce a persisted `uncertain` state or a pre-send write.
   Possible duplicates after an ambiguous failure or crash are an accepted tradeoff.
   `Rejected` and `Uncertain` still describe API outcomes, but neither prevents a
   retry on the next sync.

## Code

10. **Config validation lives with the config definition.** Each section's dataclass
    enforces its own rules in `__post_init__`, in the module that owns it, so an
    invalid section cannot be constructed and `load_config` is what reports it. Do
    not recentralise this into a `validate()` function. `config.py` keeps only what
    no single section can answer.
11. **Every config field is mandatory.** Do not make a credential optional so one
    command can run without it. The example ships `???` for the values a user must
    supply, and `load_config` reports what is missing.
12. **`src/` is fully typed.** `disallow_untyped_defs` is on, so a new function
    without annotations fails the check.
13. **Use f-strings for logging.** Interpolate values directly into log messages
    rather than using `%s` placeholders and separate arguments.
14. **What the listing omits is fetched only when a post is sent or edited, and
    never hashed.** Photo URLs and the description each cost a read, and a full
    scan touches every activity every pass, so paying per activity would dwarf
    the scan and break the daily rate limit. The content hash therefore covers
    only what the listing carries: `digest(render(activity))`, with no
    description. Hashing a fetched value would force a request per activity per
    pass just to decide there was nothing to do.
15. **The map comes from Mapbox's Static Images API, drawn on their side.** The
    encoded polyline goes into the URL as a path overlay, so one GET returns the
    finished image and Mapbox renders its own attribution into it. A locally drawn
    trace was tried first and deliberately replaced: it needed no key, but a bare
    line without a basemap is not what this is for.
16. **`maps.py` must not leak the Mapbox token**, for the same reason as
    `telegram.py`: the token is in the URL's query string and `requests` puts the
    URL in its messages. Convert them and re-raise with `from None`.
    `tests/test_maps.py` asserts this.
17. **Media is never edited after a post is sent.** Telegram allows replacing an
    item of an album but not appending one, and its length is fixed at send time,
    so any update would be partial. Only the caption is rewritten; do not add a
    media-editing path to make photos "catch up".
18. **Tests contact no API.** Keep them offline, and prefer a small number of
    behavior-level tests over exhaustive implementation checks.

## Before finishing

```bash
uv run --no-sync pytest
uv run --no-sync mypy
```
