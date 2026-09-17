"""Strava API access, including transparent refresh of stored tokens."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
import os
import time

from stravalib import Client

from .storage.database import Database
from .utils.omegaconf_datetime import OmegaConfDateTime

PHOTO_SIZE = 2048
MAX_PHOTOS = 10  # Telegram's album limit


@dataclass(frozen=True)
class Activity:
    """The activity fields used by the bridge, converted at the API boundary."""

    id: int
    start_date: datetime
    name: str | None = None
    sport_type: str | None = None
    type: str | None = None
    distance: float | None = None
    moving_time: int | None = None
    start_date_local: datetime | None = None
    private: bool | None = None
    visibility: str | None = None
    photo_count: int = 0
    polyline: str | None = None

    def is_private(self) -> bool:
        return bool(self.private or self.visibility == 'only_me')


@dataclass
class StravaConfig:
    client_id: int
    client_secret: str

    def __post_init__(self) -> None:
        if self.client_id <= 0:
            raise ValueError('strava.client_id must be positive')
        if not self.client_secret.strip():
            raise ValueError('strava.client_secret must not be empty')


class Strava:
    def __init__(self, db: Database, config: StravaConfig) -> None:
        # stravalib warns on every client construction unless it finds its own
        # environment variables. Tokens are managed here, so the advice does not
        # apply; silencing just this message keeps its other warnings visible.
        os.environ.setdefault('SILENCE_TOKEN_WARNINGS', 'true')
        self.client = Client()
        self.db = db
        self.config = config

    def ready(self) -> None:
        tokens = self.db.tokens.get()
        if not tokens:
            raise RuntimeError('Authorize first: strava-to-telegram auth')
        if tokens['expires_at'] <= time.time() + 300:
            tokens = self.client.refresh_access_token(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                refresh_token=tokens['refresh_token'],
            )
            self.db.tokens.set(tokens)
        self.client.access_token = tokens['access_token']

    def activities(self, limit: int | None = None) -> Iterator[Activity]:
        self.ready()
        # No date window: includes old edits and late uploads. Iterator paginates.
        for item in self.client.get_activities(limit=limit):
            data = item.model_dump(mode='json')
            yield Activity(
                id=data['id'],
                start_date=OmegaConfDateTime.parse(data['start_date'], field='activity.start_date'),
                name=data.get('name'),
                sport_type=data.get('sport_type'),
                type=data.get('type'),
                distance=data.get('distance'),
                moving_time=data.get('moving_time'),
                start_date_local=OmegaConfDateTime.parse(
                    data.get('start_date_local'), field='activity.start_date_local'
                ),
                photo_count=int(data.get('total_photo_count') or 0),
                polyline=(data.get('map') or {}).get('summary_polyline') or None,
                private=data.get('private'),
                visibility=data.get('visibility'),
            )

    def description(self, activity_id: int) -> str | None:
        """The note written under an activity. One API read: the listing omits it."""
        self.ready()
        detail = self.client.get_activity(activity_id).model_dump(mode='json')
        text = (detail.get('description') or '').strip()
        return text or None

    def photos(self, activity_id: int, limit: int = MAX_PHOTOS) -> list[str]:
        """Photo URLs for one activity, largest size first, default photo leading.

        One API read, so call it only when about to post: a full scan touches every
        activity, and paying a read per activity would dwarf the scan itself.
        """
        self.ready()
        items = []
        for photo in self.client.get_activity_photos(activity_id, size=PHOTO_SIZE):
            data = photo.model_dump(mode='json')
            urls = data.get('urls') or {}
            if urls:
                largest = max(urls, key=lambda size: int(size))
                items.append((not data.get('default_photo'), data.get('created_at') or '', urls[largest]))
        items.sort()
        return [url for _, _, url in items[:limit]]
