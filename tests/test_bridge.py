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
from strava_to_telegram.sync import SyncConfig, publish_activity, publish_last_activity, sync_once
from strava_to_telegram.telegram import Rejected, Uncertain


ACTIVITY = Activity(id=123, name='Morning run', sport_type='Run', distance=5000,
                    moving_time=1800, start_date=datetime(2026, 9, 16, 8, tzinfo=timezone.utc),
                    start_date_local=datetime(2026, 9, 16, 10, tzinfo=timezone.utc))
CHAT = '-1001234567890'


def sync_config(*, since: datetime | None = None, include_private: bool = False,
                remove_missing: bool = True) -> SyncConfig:
    return SyncConfig(since, include_private, remove_missing)


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = database(Path(self.temp.name) / 'test.db')
        self.db = self.context.__enter__()
        self.telegram = Mock()
        self.telegram.send.return_value = 42

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.temp.cleanup()

    def post(self):
        return self.db.posts.get(ACTIVITY.id, CHAT)

    def test_publish_sends_once_skips_unchanged_and_edits_changed(self) -> None:
        publish_activity(self.db, self.telegram, CHAT, ACTIVITY)
        publish_activity(self.db, self.telegram, CHAT, ACTIVITY)
        publish_activity(self.db, self.telegram, CHAT, replace(ACTIVITY, name='New title'))
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
                    publish_activity(self.db, self.telegram, CHAT, activity)
                post = self.db.posts.get(activity_id, CHAT)
                self.assertEqual(post.status if post else None, stored_status)
                self.telegram.send.side_effect = None
                self.telegram.send.return_value = activity_id
                publish_activity(self.db, self.telegram, CHAT, activity)
                self.assertEqual(self.telegram.send.call_count, 2)

    def test_failed_edit_keeps_old_hash_for_retry(self) -> None:
        publish_activity(self.db, self.telegram, CHAT, ACTIVITY)
        old_hash = self.post().content_hash
        self.telegram.edit.side_effect = Uncertain('timeout')
        with self.assertRaises(Uncertain):
            publish_activity(self.db, self.telegram, CHAT, replace(ACTIVITY, distance=6000))
        self.assertEqual(self.post().content_hash, old_hash)

    def test_sync_applies_cutoff_only_to_new_posts_and_filters_private(self) -> None:
        source = Mock()
        cutoff = datetime(2026, 9, 17, tzinfo=timezone.utc)
        source.activities.return_value = [ACTIVITY, replace(ACTIVITY, id=124, private=True)]
        sync_once(self.db, source, self.telegram, CHAT, sync_config(since=cutoff))
        self.telegram.send.assert_not_called()
        publish_activity(self.db, self.telegram, CHAT, replace(ACTIVITY, name='Old title'))
        source.activities.return_value = [replace(ACTIVITY, name='Updated'),
                                          replace(ACTIVITY, id=124, private=True)]
        sync_once(self.db, source, self.telegram, CHAT, sync_config(since=cutoff))
        self.telegram.edit.assert_called_once()
        self.assertIsNone(self.db.posts.get(124, CHAT))

    def test_missing_posts_are_redacted_only_when_enabled_and_can_reappear(self) -> None:
        publish_activity(self.db, self.telegram, CHAT, ACTIVITY)
        source = Mock()
        source.activities.return_value = []
        sync_once(self.db, source, self.telegram, CHAT, sync_config(remove_missing=False))
        self.telegram.edit.assert_not_called()
        sync_once(self.db, source, self.telegram, CHAT, sync_config(remove_missing=True))
        self.assertIs(self.post().status, PostStatus.REMOVED)
        source.activities.return_value = [ACTIVITY]
        sync_once(self.db, source, self.telegram, CHAT, sync_config())
        self.assertIs(self.post().status, PostStatus.SENT)
        self.assertEqual(self.telegram.send.call_count, 1)

    def test_incomplete_strava_scan_never_redacts(self) -> None:
        publish_activity(self.db, self.telegram, CHAT, ACTIVITY)

        def broken():
            yield ACTIVITY
            raise RuntimeError('network failure')

        source = Mock()
        source.activities.return_value = broken()
        with self.assertRaisesRegex(RuntimeError, 'network failure'):
            sync_once(self.db, source, self.telegram, CHAT, sync_config())
        self.telegram.edit.assert_not_called()

    def test_publish_last_always_sends_without_filters_or_redaction(self) -> None:
        publish_activity(self.db, self.telegram, CHAT, replace(ACTIVITY, id=124))
        source = Mock()
        source.activities.return_value = [replace(ACTIVITY, private=True, visibility='only_me')]
        self.telegram.reset_mock()
        self.telegram.send.side_effect = [43, 44]
        publish_last_activity(self.db, source, self.telegram, CHAT)
        publish_last_activity(self.db, source, self.telegram, CHAT)
        source.activities.assert_called_with(limit=1)
        self.assertEqual(self.telegram.send.call_count, 2)
        self.telegram.edit.assert_not_called()
        self.assertEqual(self.post().message_id, 44)
        self.assertIs(self.db.posts.get(124, CHAT).status, PostStatus.SENT)

    def test_tokens_posts_and_lock_survive_database_use(self) -> None:
        tokens = {'access_token': 'test-token', 'refresh_token': 'refresh', 'expires_at': 12345}
        self.db.tokens.set(tokens)
        publish_activity(self.db, self.telegram, CHAT, ACTIVITY)
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
