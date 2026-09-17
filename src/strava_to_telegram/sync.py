from dataclasses import dataclass
import logging

from .utils.omegaconf_datetime import OmegaConfDateTime
from .formatting import digest, render
from .maps import Map, MapUnavailable
from .strava import MAX_PHOTOS, Activity, Strava
from .telegram import Rejected, Telegram, Uncertain
from .storage.database import Database


@dataclass
class SyncConfig:
    since: OmegaConfDateTime | None
    include_private: bool
    require_photos: bool
    delete_removed_strava_activities_from_telegram: bool

    def __post_init__(self) -> None:
        self.since = OmegaConfDateTime.parse(self.since, field='sync.since')
        if not isinstance(self.include_private, bool):
            raise ValueError('sync.include_private must be a boolean')
        if not isinstance(self.require_photos, bool):
            raise ValueError('sync.require_photos must be a boolean')
        if not isinstance(self.delete_removed_strava_activities_from_telegram, bool):
            raise ValueError('sync.delete_removed_strava_activities_from_telegram must be a boolean')


log = logging.getLogger(__name__)


def attachments(source: Strava, maps: Map, activity: Activity) -> list[str | bytes]:
    """The route map first, then the activity's own photos, within the album limit."""
    items: list[str | bytes] = []
    if activity.polyline:
        try:
            items.append(maps.image(activity.polyline))
        except MapUnavailable as error:
            # A missing basemap is not worth losing the post over.
            log.warning(f'No map for activity {activity.id}: {error}')
    if activity.photo_count:
        items.extend(source.photos(activity.id, limit=MAX_PHOTOS - len(items)))
    return items


def publish_activity(db: Database, source: Strava, maps: Map, telegram: Telegram, chat: str,
                     activity: Activity, *, force_new: bool = False) -> None:
    aid = activity.id
    row = db.posts.get(aid, chat)
    # The hash covers what the listing carries. The description is fetched, not
    # listed, so like photos it rides along with the post without driving edits.
    hashed = digest(render(activity))
    log.debug(f'Activity {aid} in chat {chat}: old hash={row.content_hash if row else None}, new hash={hashed}')
    if not force_new and row and row.message_id:
        if row.content_hash == hashed:
            log.debug(f'Skipping unchanged activity {aid}')
            return
        text = render(activity, source.description(aid))
        log.debug(f'Editing activity {aid} in message {row.message_id}')
        # Photos are fixed at first post: Telegram cannot add media to a message
        # that was sent without it, and only the caption is editable afterwards.
        telegram.edit(chat, row.message_id, text, row.kind)
        message_id, kind = row.message_id, row.kind
    else:
        text = render(activity, source.description(aid))
        media = attachments(source, maps, activity)
        log.debug(f'Sending activity {aid} to chat {chat} with {len(media)} attachment(s)')
        try:
            message_id, kind = telegram.send(chat, text, media)
        except Rejected:
            if media:
                # A CDN URL Telegram would not fetch must not cost the post itself.
                log.warning(f'Activity {aid} rejected with media; retrying as text')
                message_id, kind = telegram.send(chat, text)
            else:
                if not row or not row.message_id:
                    db.posts.mark_rejected(aid, chat)
                raise
    db.posts.mark_sent(aid, chat, message_id, hashed, kind)
    log.info(f'Synced activity {aid} to message {message_id}')


def publish_last_activity(db: Database, source: Strava, maps: Map, telegram: Telegram,
                          chat: str) -> None:
    """Always send the latest accessible activity as a new post, without sync filters."""
    activity = next(iter(source.activities(limit=1)), None)
    if activity is None:
        log.info('No accessible activities found')
        return
    publish_activity(db, source, maps, telegram, chat, activity, force_new=True)


def sync_once(db: Database, source: Strava, maps: Map, telegram: Telegram, chat: str,
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
        # Only gates the first post. An activity already in the channel keeps its
        # post -- and its updates -- even if its photos are deleted afterwards.
        if not row and config.require_photos and not activity.photo_count:
            log.debug(f'Skipping activity {activity.id}: no photos')
            continue
        try:
            publish_activity(db, source, maps, telegram, chat, activity)
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
