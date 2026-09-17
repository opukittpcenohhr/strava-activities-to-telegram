import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from typer.testing import CliRunner
from strava_to_telegram.cli import app, main

from test_config import complete_config


class CliTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.config = complete_config()
        self.config.strava.client_id = 42
        self.db = object()
        self.load = self.mock('load_config', return_value=self.config)
        self.database = self.mock('database', return_value=nullcontext(self.db))
        self.authorize = self.mock('authorize')
        self.strava = self.mock('Strava')
        self.telegram = self.mock('Telegram')
        self.maps = self.mock('Map')
        self.sync_once = self.mock('sync_once')
        self.publish_last_activity = self.mock('publish_last_activity')

    def mock(self, name, **kwargs):
        return self.stack.enter_context(patch('strava_to_telegram.cli.' + name, **kwargs))

    def invoke(self, args):
        return CliRunner().invoke(app, args)

    def test_help_without_config_or_credentials(self):
        self.assertEqual(self.invoke(['--help']).exit_code, 0)
        result = self.invoke(['sync', '--help'])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn('--once', result.output)
        self.assertNotIn('--interval', result.output)
        self.load.assert_not_called()

    def test_auth_and_overrides(self):
        result = self.invoke(['--config', 'custom.yaml', 'auth', 'auth.port=9000'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.load.assert_called_once_with(Path('custom.yaml'), overrides=['auth.port=9000'])
        self.authorize.assert_called_once_with(self.db, self.config.auth, self.config.strava)
        self.strava.assert_not_called()

    def test_test_posts_latest_without_sync(self):
        result = self.invoke(['post-last'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.publish_last_activity.assert_called_once_with(
            self.db, self.strava.return_value, self.maps.return_value, self.telegram.return_value, '-100123'
        )
        self.sync_once.assert_not_called()

    def test_sync_performs_one_pass_with_overrides(self):
        result = self.invoke(['sync', 'auth.port=9000'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.sync_once.assert_called_once_with(
            self.db,
            self.strava.return_value,
            self.maps.return_value,
            self.telegram.return_value,
            '-100123',
            self.config.sync,
        )
        self.load.assert_called_once_with(Path('config.yaml'), overrides=['auth.port=9000'])

    def test_sync_exits_on_failure_and_closes_database(self):
        context = self.stack.enter_context(patch('strava_to_telegram.cli.database'))
        context.return_value.__enter__.return_value = Mock()
        self.sync_once.side_effect = RuntimeError('failed')
        result = self.invoke(['sync'])
        self.assertEqual(result.exit_code, 1)
        self.sync_once.assert_called_once()
        context.return_value.__exit__.assert_called_once()

    def test_invalid_config_fails_before_opening_database(self):
        self.load.side_effect = ValueError('Missing required settings: auth.port')
        self.assertEqual(self.invoke(['post-last']).exit_code, 1)
        self.database.assert_not_called()
        self.assertNotEqual(self.invoke(['sync', '--typo']).exit_code, 0)

    def test_entrypoint_propagates_failures(self):
        """Nothing is swallowed: Python prints the traceback and exits non-zero."""
        self.mock('app', side_effect=ValueError('Missing required settings: auth.port'))
        self.mock('os.umask')
        with self.assertRaisesRegex(ValueError, 'Missing required settings: auth.port'):
            main()
