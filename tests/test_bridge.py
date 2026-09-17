from dataclasses import replace
from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from strava_to_telegram.auth import validate_callback
from strava_to_telegram.storage.database import database
from strava_to_telegram.storage.posts import PostStatus
from strava_to_telegram.strava import Activity
from strava_to_telegram.formatting import render
from strava_to_telegram.maps import MapUnavailable
from strava_to_telegram.sync import SyncConfig, publish_activity, publish_last_activity, sync_once
from strava_to_telegram.telegram import Rejected, Uncertain


ACTIVITY = Activity(id=123, name='Morning run', sport_type='Run', distance=5000,
                    moving_time=1800, start_date=datetime(2026, 9, 16, 8, tzinfo=timezone.utc),
                    start_date_local=datetime(2026, 9, 16, 10, tzinfo=timezone.utc))
CHAT = '-1001234567890'
SAMPLE_POLYLINE = '_p~iF~ps|U_ulLnnqC_mqNvxq`@'


def sync_config(*, since: datetime | None = None, include_private: bool = False,
                require_photos: bool = False, remove_missing: bool = True) -> SyncConfig:
    return SyncConfig(since, include_private, require_photos, remove_missing)


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = database(Path(self.temp.name) / 'test.db')
        self.db = self.context.__enter__()
        self.telegram = Mock()
        self.telegram.send.return_value = (42, 'text')
        self.source = Mock()
        self.source.photos.return_value = []
        self.source.description.return_value = None
        self.maps = Mock()
        self.maps.image.return_value = b'map-png'

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def post(self):
        return self.db.posts.get(ACTIVITY.id, CHAT)

    def test_publish_sends_once_skips_unchanged_and_edits_changed(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, replace(ACTIVITY, name='New title'))
        self.telegram.send.assert_called_once()
        self.telegram.edit.assert_called_once()
        self.assertEqual(self.post().message_id, 42)

    def test_failed_sends_are_retryable(self) -> None:
        for activity_id, error, stored_status in (
                (123, Rejected('forbidden'), PostStatus.REJECTED),
                (124, Uncertain('timeout'), None)):
            with self.subTest(error=type(error).__name__):
                activity = replace(ACTIVITY, id=activity_id)
                self.telegram.reset_mock()
                self.telegram.send.side_effect = error
                with self.assertRaises(type(error)):
                    publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, activity)
                post = self.db.posts.get(activity_id, CHAT)
                self.assertEqual(post.status if post else None, stored_status)
                self.telegram.send.side_effect = None
                self.telegram.send.return_value = (activity_id, 'text')
                publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, activity)
                self.assertEqual(self.telegram.send.call_count, 2)

    def test_failed_edit_keeps_old_hash_for_retry(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)
        old_hash = self.post().content_hash
        self.telegram.edit.side_effect = Uncertain('timeout')
        with self.assertRaises(Uncertain):
            publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, replace(ACTIVITY, distance=6000))
        self.assertEqual(self.post().content_hash, old_hash)

    def test_sync_applies_cutoff_only_to_new_posts_and_filters_private(self) -> None:
        source = Mock()
        source.description.return_value = None
        cutoff = datetime(2026, 9, 17, tzinfo=timezone.utc)
        source.activities.return_value = [ACTIVITY, replace(ACTIVITY, id=124, private=True)]
        sync_once(self.db, source, self.maps, self.telegram, CHAT, sync_config(since=cutoff))
        self.telegram.send.assert_not_called()
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, replace(ACTIVITY, name='Old title'))
        source.activities.return_value = [replace(ACTIVITY, name='Updated'),
                                          replace(ACTIVITY, id=124, private=True)]
        sync_once(self.db, source, self.maps, self.telegram, CHAT, sync_config(since=cutoff))
        self.telegram.edit.assert_called_once()
        self.assertIsNone(self.db.posts.get(124, CHAT))

    def test_missing_posts_are_redacted_only_when_enabled_and_can_reappear(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)
        source = Mock()
        source.description.return_value = None
        source.activities.return_value = []
        sync_once(self.db, source, self.maps, self.telegram, CHAT, sync_config(remove_missing=False))
        self.telegram.edit.assert_not_called()
        sync_once(self.db, source, self.maps, self.telegram, CHAT, sync_config(remove_missing=True))
        self.assertIs(self.post().status, PostStatus.REMOVED)
        source.activities.return_value = [ACTIVITY]
        sync_once(self.db, source, self.maps, self.telegram, CHAT, sync_config())
        self.assertIs(self.post().status, PostStatus.SENT)
        self.assertEqual(self.telegram.send.call_count, 1)

    def test_incomplete_strava_scan_never_redacts(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)

        def broken():
            yield ACTIVITY
            raise RuntimeError('network failure')

        source = Mock()
        source.description.return_value = None
        source.activities.return_value = broken()
        with self.assertRaisesRegex(RuntimeError, 'network failure'):
            sync_once(self.db, source, self.maps, self.telegram, CHAT, sync_config())
        self.telegram.edit.assert_not_called()

    def test_publish_last_always_sends_without_filters_or_redaction(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, replace(ACTIVITY, id=124))
        source = Mock()
        source.description.return_value = None
        source.activities.return_value = [replace(ACTIVITY, private=True, visibility='only_me')]
        self.telegram.reset_mock()
        self.telegram.send.side_effect = [(43, 'text'), (44, 'text')]
        publish_last_activity(self.db, source, self.maps, self.telegram, CHAT)
        publish_last_activity(self.db, source, self.maps, self.telegram, CHAT)
        source.activities.assert_called_with(limit=1)
        self.assertEqual(self.telegram.send.call_count, 2)
        self.telegram.edit.assert_not_called()
        self.assertEqual(self.post().message_id, 44)
        self.assertIs(self.db.posts.get(124, CHAT).status, PostStatus.SENT)

    def test_tokens_posts_and_lock_survive_database_use(self) -> None:
        tokens = {'access_token': 'test-token', 'refresh_token': 'refresh', 'expires_at': 12345}
        self.db.tokens.set(tokens)
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)
        with self.assertRaises(RuntimeError):
            with database(Path(self.temp.name) / 'test.db'):
                pass
        self.context.__exit__(None, None, None)
        self.context = database(Path(self.temp.name) / 'test.db')
        self.db = self.context.__enter__()
        self.assertEqual(self.db.tokens.get(), tokens)
        self.assertEqual(self.post().message_id, 42)

    def test_oauth_callback_requires_state_scope_code_and_path(self) -> None:
        self.assertEqual(validate_callback(
            '/callback?state=secret&scope=read,activity:read&code=abc', 'secret'), 'abc')
        for path in ['/callback?state=wrong&scope=activity:read&code=abc',
                     '/callback?state=secret&scope=read&code=abc',
                     '/callback?state=secret&scope=activity:read',
                     '/other?state=secret&scope=activity:read&code=abc']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_callback(path, 'secret')


if __name__ == '__main__':
    unittest.main()


class PhotoTests(unittest.TestCase):
    """Photos travel with the first post only, and never cost the post itself."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = database(Path(self.temp.name) / 'test.db')
        self.db = self.context.__enter__()
        self.telegram = Mock()
        self.telegram.send.return_value = (42, 'caption')
        self.source = Mock()
        self.source.photos.return_value = ['https://cdn/one.jpg', 'https://cdn/two.jpg']
        self.source.description.return_value = None
        self.maps = Mock()
        self.maps.image.return_value = b'map-png'
        self.activity = replace(ACTIVITY, photo_count=2)

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_photos_are_sent_once_and_the_edit_follows_the_message_kind(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, self.activity)
        self.assertEqual(self.telegram.send.call_args.args[2], self.source.photos.return_value)
        self.assertEqual(self.db.posts.get(ACTIVITY.id, CHAT).kind, 'caption')

        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT,
                         replace(self.activity, name='Renamed'))
        self.telegram.edit.assert_called_once()
        self.assertEqual(self.telegram.edit.call_args.args[3], 'caption')
        # An edit must not re-fetch photos: the scan already pays for the listing.
        self.source.photos.assert_called_once()

    def test_activity_without_photos_never_calls_strava(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, ACTIVITY)
        self.source.photos.assert_not_called()
        self.assertEqual(self.telegram.send.call_args.args[2], [])

    def test_rejected_photo_send_falls_back_to_text(self) -> None:
        self.telegram.send.side_effect = [Rejected('image too big'), (43, 'text')]
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, self.activity)
        self.assertEqual(self.telegram.send.call_count, 2)
        self.assertEqual(self.telegram.send.call_args.args[1:], (render(self.activity),))
        post = self.db.posts.get(ACTIVITY.id, CHAT)
        self.assertEqual((post.message_id, post.kind, post.status), (43, 'text', PostStatus.SENT))

    def test_map_leads_the_album(self) -> None:
        with_route = replace(self.activity, polyline=SAMPLE_POLYLINE)
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, with_route)
        self.maps.image.assert_called_once_with(SAMPLE_POLYLINE)
        self.assertEqual(self.telegram.send.call_args.args[2],
                         [b'map-png'] + self.source.photos.return_value)

    def test_post_survives_an_unavailable_map(self) -> None:
        self.maps.image.side_effect = MapUnavailable('Mapbox returned no image (HTTP 401)')
        with_route = replace(self.activity, polyline=SAMPLE_POLYLINE)
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, with_route)
        self.assertEqual(self.telegram.send.call_args.args[2], self.source.photos.return_value)
        self.assertEqual(self.db.posts.get(ACTIVITY.id, CHAT).status, PostStatus.SENT)

    def test_activity_without_a_track_sends_photos_alone(self) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, self.activity)
        self.assertEqual(self.telegram.send.call_args.args[2], self.source.photos.return_value)


class DescriptionTests(unittest.TestCase):
    """The note under an activity costs a request, so it is stored with the post."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = database(Path(self.temp.name) / 'test.db')
        self.db = self.context.__enter__()
        self.telegram = Mock()
        self.telegram.send.return_value = (42, 'text')
        self.maps = Mock()
        self.source = Mock()
        self.source.photos.return_value = []
        self.source.description.return_value = 'Felt strong & fast'

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def publish(self, activity: Activity = ACTIVITY) -> None:
        publish_activity(self.db, self.source, self.maps, self.telegram, CHAT, activity)

    def test_description_is_rendered_and_escaped(self) -> None:
        self.publish()
        self.assertIn('<i>Felt strong &amp; fast</i>', self.telegram.send.call_args.args[1])

    def test_description_never_drives_an_edit(self) -> None:
        self.publish()
        self.source.description.reset_mock()
        self.source.description.return_value = 'Rewritten afterwards'
        self.publish()
        # Like photos, the description is not part of the change signal, so an
        # otherwise unchanged activity is skipped before anything is fetched.
        self.source.description.assert_not_called()
        self.telegram.edit.assert_not_called()

    def test_an_edit_carries_the_current_description(self) -> None:
        self.publish()
        self.source.description.return_value = 'Rewritten afterwards'
        self.publish(replace(ACTIVITY, name='Renamed'))
        self.assertIn('<i>Rewritten afterwards</i>', self.telegram.edit.call_args.args[2])


class RequirePhotosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = database(Path(self.temp.name) / 'test.db')
        self.db = self.context.__enter__()
        self.telegram = Mock()
        self.telegram.send.return_value = (42, 'caption')
        self.maps = Mock()
        self.source = Mock()
        self.source.photos.return_value = ['https://cdn/one.jpg']
        self.source.description.return_value = None

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def sync(self, activities: list[Activity], **options: bool) -> None:
        self.source.activities.return_value = activities
        sync_once(self.db, self.source, self.maps, self.telegram, CHAT,
                  sync_config(require_photos=True, **options))

    def test_only_activities_with_photos_are_posted(self) -> None:
        with_photos = replace(ACTIVITY, id=1, photo_count=2)
        without = replace(ACTIVITY, id=2, photo_count=0)
        self.sync([with_photos, without])
        self.telegram.send.assert_called_once()
        self.assertIsNone(self.db.posts.get(2, CHAT))

    def test_a_posted_activity_survives_losing_its_photos(self) -> None:
        self.sync([replace(ACTIVITY, id=1, photo_count=2)])
        self.telegram.reset_mock()
        # Photos deleted on Strava: the post keeps its mapping and is not redacted.
        self.sync([replace(ACTIVITY, id=1, photo_count=0, name='Renamed')])
        self.telegram.edit.assert_called_once()
        self.assertEqual(self.db.posts.get(1, CHAT).status, PostStatus.SENT)
