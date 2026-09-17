from dataclasses import asdict
from datetime import datetime, timezone
import tempfile
import unittest

import yaml
from pathlib import Path

from strava_to_telegram.config import Config, from_mapping, load_config, resolve_paths

from strava_to_telegram.auth import AuthConfig
from strava_to_telegram.strava import StravaConfig
from strava_to_telegram.telegram import TelegramConfig
from strava_to_telegram.logs import LoggingConfig
from strava_to_telegram.maps import MapConfig
from strava_to_telegram.storage.database import StorageConfig
from strava_to_telegram.sync import SyncConfig
from strava_to_telegram.utils.omegaconf_datetime import OmegaConfDateTime


def complete_config():
    """Explicit test fixture; production values come only from YAML/overrides."""
    return Config(
        storage=StorageConfig(Path('data/activities.db')),
        strava=StravaConfig(42, 'strava-client-secret'),
        telegram=TelegramConfig(-100123, '123456:telegram-bot-token'),
        map=MapConfig('pk.mapbox-token', 'mapbox/outdoors-v12'),
        sync=SyncConfig(None, False, True, delete_removed_strava_activities_from_telegram=True),
        auth=AuthConfig('127.0.0.1', 8000),
        logging=LoggingConfig('INFO'),
    )


def complete_mapping():
    return asdict(complete_config())


class ConfigValidationTests(unittest.TestCase):
    def test_sections_validate_themselves_on_construction(self):
        """Each dataclass enforces its own invariants, so a bad value cannot exist."""
        for build in [
            lambda: AuthConfig('127.0.0.1', 70000),
            lambda: AuthConfig('   ', 8000),
            lambda: TelegramConfig(123, 'token'),
            lambda: TelegramConfig(-100123, '  '),
            lambda: StravaConfig(-1, 'secret'),
            lambda: StravaConfig(42, ''),
            lambda: LoggingConfig('VERBOSE'),
            lambda: SyncConfig(None, 'false', True, delete_removed_strava_activities_from_telegram=True),
            lambda: SyncConfig('yesterday', False, True, delete_removed_strava_activities_from_telegram=True),
            lambda: SyncConfig(None, False, 'yes', delete_removed_strava_activities_from_telegram=True),
        ]:
            with self.subTest(build=build), self.assertRaises(ValueError):
                build()

    def test_paths_relative_to_config(self):
        config = resolve_paths(complete_config(), Path('/tmp/bridge'))
        self.assertEqual(config.storage.database, Path('/tmp/bridge/data/activities.db').resolve())


class ConfigTests(unittest.TestCase):
    def test_delete_removed_setting_is_required_and_boolean(self):
        key = 'delete_removed_strava_activities_from_telegram'
        data = complete_mapping()
        del data['sync'][key]
        with self.assertRaisesRegex(ValueError, key):
            from_mapping(data, Path('/tmp'))
        config = from_mapping(data, Path('/tmp'), overrides=[f'sync.{key}=false'])
        self.assertIs(config.sync.delete_removed_strava_activities_from_telegram, False)
        with self.assertRaises(ValueError):
            from_mapping(data, Path('/tmp'), overrides=[f'sync.{key}=sometimes'])
        with self.assertRaisesRegex(ValueError, key):
            SyncConfig(None, False, True, 'false')

    def test_since_parses_after_overrides_and_interpolation(self):
        config = from_mapping(complete_mapping(), Path('/tmp'), overrides=['sync.since=2026-09-16T10:00:00+02:00'])
        self.assertIsInstance(config.sync.since, OmegaConfDateTime)
        self.assertEqual(config.sync.since, datetime(2026, 9, 16, 8, tzinfo=timezone.utc))
        data = complete_mapping()
        data['strava']['client_secret'] = '2026-09-01'
        data['sync']['since'] = '${strava.client_secret}'
        self.assertEqual(from_mapping(data, Path('/tmp')).sync.since, datetime(2026, 9, 1, tzinfo=timezone.utc))

    def test_invalid_since_is_rejected_at_config_boundary(self):
        for value in ('yesterday', 123, False, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                data = complete_mapping()
                data['sync']['since'] = value
                from_mapping(data, Path('/tmp'))

    def test_missing_settings_and_sections_fail(self):
        for section, key in [
            ('auth', 'port'),
            ('sync', 'since'),
            ('sync', 'include_private'),
            ('strava', 'client_id'),
            ('strava', 'client_secret'),
            ('telegram', 'bot_token'),
            ('telegram', 'channel_id'),
            ('logging', 'level'),
        ]:
            data = complete_mapping()
            del data[section][key]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, section + r'\.' + key):
                from_mapping(data, Path('/tmp'))
        data = complete_mapping()
        del data['telegram']
        with self.assertRaisesRegex(ValueError, 'telegram'):
            from_mapping(data, Path('/tmp'))

    def test_unknown_fields_invalid_types_and_ranges(self):
        for data in [
            {'auth': {'port': 'not-a-number'}},
            {'auth': {'port': 0}},
            {'sync': {'sinces': '2026-09-01'}},
            {'sync': {'include_private': 'sometimes'}},
            {'telegram': {'bot_token': []}},
            {'telegram': {'bot_token': '   '}},
            {'strava': {'client_secret': ''}},
            {'telegram': {'channel_id': '@example'}},
            {'auth': {'port': 70000}},
            {'strava': {'client_id': -1}},
            {'logging': {'level': 'VERBOSE'}},
            [],
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                merged = complete_mapping()
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, dict):
                            merged[key].update(value)
                        else:
                            merged[key] = value
                else:
                    merged = data
                from_mapping(merged, Path('/tmp'))

    def test_arbitrary_nested_overrides_and_precedence(self):
        data = complete_mapping()
        data['sync']['since'] = '2026-09-01'
        config = from_mapping(
            data,
            Path('/tmp'),
            overrides=['telegram.channel_id=-100456', 'auth.port=9000', 'storage.database=other.db', 'sync.since=null'],
        )
        self.assertEqual(config.telegram.channel_id, -100456)
        self.assertEqual(config.auth.port, 9000)
        self.assertEqual(config.storage.database, Path('/tmp/other.db').resolve())
        self.assertIsNone(config.sync.since)

    def test_interpolation_and_last_override_wins(self):
        config = from_mapping(
            complete_mapping(),
            Path('/tmp'),
            overrides=['auth.port=9000', 'auth.port=9001', 'strava.client_id=${auth.port}'],
        )
        self.assertEqual(config.auth.port, 9001)
        self.assertEqual(config.strava.client_id, 9001)

    def test_bad_override_syntax_and_unknown_fields(self):
        for override in ['sync.since', '=10', 'sync..since=10', 'sync.typo=10', 'auth.port=nope']:
            with self.subTest(override=override), self.assertRaises(ValueError):
                from_mapping(complete_mapping(), Path('/tmp'), overrides=[override])

    def test_yaml_example_and_duplicate_keys(self):
        # The example ships `???` for the five values a user must supply.
        with self.assertRaisesRegex(ValueError, 'Missing required settings'):
            load_config('config.example.yaml')
        filled = [
            'strava.client_id=42',
            'strava.client_secret=s',
            'telegram.channel_id=-100123',
            'telegram.bot_token=t',
            'map.token=pk.t',
        ]
        self.assertEqual(load_config('config.example.yaml', overrides=filled).auth.port, 8000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            path.write_text(Path('config.example.yaml').read_text().replace('since: null', 'since: 2026-09-01'))
            self.assertEqual(load_config(path, overrides=filled).sync.since, datetime(2026, 9, 1, tzinfo=timezone.utc))
            # Malformed YAML is left to PyYAML, whose message names line and column.
            for text in [
                'auth:\n  port: 30\n  port: 60\n',
                '!!python/object/apply:os.system ["exit 1"]',
                'sync: [broken',
            ]:
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(yaml.YAMLError):
                    load_config(path)
            # Well-formed YAML that is not a configuration mapping. OmegaConf reports a
            # wrong top-level scalar type as OSError; a list reaches our own merge.
            for text, expected in [('false', OSError), ('[]', ValueError)]:
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(expected):
                    load_config(path)
