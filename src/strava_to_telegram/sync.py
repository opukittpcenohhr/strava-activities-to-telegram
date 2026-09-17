from dataclasses import dataclass
import logging

from .utils.omegaconf_datetime import OmegaConfDateTime
from .formatting import digest, render
from .strava import Activity, Strava
from .telegram import Rejected, Telegram, Uncertain
from .storage.database import Database


@dataclass
class SyncConfig:
    since: OmegaConfDateTime | None
    include_private: bool
    delete_removed_strava_activities_from_telegram: bool

    def __post_init__(self) -> None:
        self.since = OmegaConfDateTime.parse(self.since, field='sync.since')
        if not isinstance(self.include_private, bool):
            raise ValueError('sync.include_private must be a boolean')
        if not isinstance(self.delete_removed_strava_activities_from_telegram, bool):
            raise ValueError('sync.delete_removed_strava_activities_from_telegram must be a boolean')


log = logging.getLogger(__name__)


def publish_activity(db: Database, telegram: Telegram, chat: str, activity: Activity,
                     *, force_new: bool = False) -> None:
    aid = activity.id
    row = db.posts.get(aid, chat)
    text = render(activity)
    hashed = digest(text)
    log.debug(f'Activity {aid} in chat {chat}: old hash={row.content_hash if row else None}, new hash={hashed}')
    if not force_new and row and row.message_id:
        if row.content_hash == hashed:
            log.debug(f'Skipping unchanged activity {aid}')
            return
        log.debug(f'Editing activity {aid} in message {row.message_id}')
        telegram.edit(chat, row.message_id, text, row.kind)
        message_id = row.message_id
    else:
        log.debug(f'Sending activity {aid} to chat {chat}')
        try:
            message_id = telegram.send(chat, text)
        except Rejected:
            if not row or not row.message_id:
                db.posts.mark_rejected(aid, chat)
            raise
    db.posts.mark_sent(aid, chat, message_id, hashed)
    log.info(f'Synced activity {aid} to message {message_id}')


def publish_last_activity(db: Database, source: Strava, telegram: Telegram, chat: str) -> None:
    """Always send the latest accessible activity as a new post, without sync filters."""
    activity = next(iter(source.activities(limit=1)), None)
    if activity is None:
        log.info('No accessible activities found')
        return
    publish_activity(db, telegram, chat, activity, force_new=True)


def sync_once(db: Database, source: Strava, telegram: Telegram, chat: str,
              config: SyncConfig) -> None:
    """Synchronize one full scan, including updates and missing-activity redaction."""
    activities = list(source.activities())
    visible_strava_activities_id = set()
    failures = 0
    for activity in reversed(activities):
        if not config.include_private and activity.is_private():
            continue
        visible_strava_activities_id.add(activity.id)
        row = db.posts.get(activity.id, chat)
        if not row and config.since is not None and activity.start_date < config.since:
            continue
        try:
            publish_activity(db, telegram, chat, activity)
        except (Rejected, Uncertain):
            failures += 1
            log.error(f"Could not sync activity {activity.id}; will retry on the next sync")
    if config.delete_removed_strava_activities_from_telegram:
        # Old Telegram posts cannot always be deleted. Redact content by editing instead.
        rows = db.posts.sent(chat)
        for row in rows:
            if row.activity_id in visible_strava_activities_id:
                continue
            assert row.message_id is not None
            try:
                telegram.edit(chat, row.message_id, 'This activity is no longer available.', row.kind)
                db.posts.mark_removed(row.activity_id, chat)
            except (Rejected, Uncertain):
                failures += 1
                log.error(f'Could not redact unavailable activity {row.activity_id}')
    if failures:
        raise RuntimeError(f'{failures} Telegram operations failed; inspect the preceding activity IDs')
