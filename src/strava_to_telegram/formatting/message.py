"""Assembly of the message Telegram receives.

Messages are HTML: Telegram's own flavour, which allows only b/i/u/s/a/code/pre.
Everything interpolated from Strava is escaped, because activity names are free
text and an unescaped `&` is enough to make Telegram reject the whole message.
"""

import hashlib
from html import escape

from ..strava import Activity
from . import sport as sports
from . import units

STRAVA_ACTIVITY = 'https://www.strava.com/activities/{id}'
DESCRIPTION_LIMIT = 400


def render(activity: Activity, description: str | None = None) -> str:
    seconds = int(activity.moving_time or 0)
    km = float(activity.distance or 0) / 1000
    sport = activity.sport_type or activity.type or 'Activity'
    name = str(activity.name or 'Activity')[:200]

    stats = []
    if km > 0:
        stats.append(units.distance(km))
    effort = [units.duration(seconds)] if seconds > 0 else []
    pace = units.effort(sport, km, seconds)
    if pace:
        effort.append(pace)
    if effort:
        stats.append(' · '.join(effort))

    # Blocks are separated by a blank line; lines within one stay together.
    blocks = [f'{sports.emoji(sport)} {escape(sports.label(sport))} — <b>{escape(name)}</b>']
    if stats:
        blocks.append('\n'.join(stats))
    if description:
        blocks.append(f'<i>{escape(description.strip()[:DESCRIPTION_LIMIT])}</i>')
    blocks.append(f'<a href="{STRAVA_ACTIVITY.format(id=activity.id)}">View on Strava</a>')
    return '\n\n'.join(blocks)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
