from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from strava_to_telegram.formatting import render
from strava_to_telegram.strava import Activity, Strava, StravaConfig


class StravaDateTests(unittest.TestCase):
    def test_dates_are_parsed_before_activities_leave_adapter(self):
        raw = {'id': 123, 'start_date': '2026-09-15T22:30:00Z',
               'start_date_local': '2026-09-16T00:30:00+02:00',
               'name': 'Morning run', 'sport_type': 'Run', 'type': 'Run',
               'distance': 5000, 'moving_time': 1800,
               'private': True, 'visibility': 'only_me', 'unused_api_field': 'ignored'}
        item = Mock()
        item.model_dump.return_value = raw.copy()
        with patch('strava_to_telegram.strava.Client') as client:
            source = Strava(Mock(), StravaConfig(42, 'secret'))
            client.return_value.get_activities.return_value = [item]
            with patch.object(source, 'ready'):
                activity = next(source.activities())
        self.assertIsInstance(activity, Activity)
        self.assertEqual(activity.start_date, datetime(2026, 9, 15, 22, 30, tzinfo=timezone.utc))
        self.assertIsInstance(activity.start_date_local, datetime)
        self.assertIs(activity.private, True)
        self.assertEqual(activity.visibility, 'only_me')
        self.assertEqual(activity.type, 'Run')
        self.assertEqual(render(activity), 'Morning run\nRun · 2026-09-16\n'
                         '5.00 km · 0:30:00\nhttps://www.strava.com/activities/123')

    def test_naive_dates_are_utc_and_missing_local_date_is_allowed(self):
        item = Mock()
        item.model_dump.return_value = {'id': 123, 'start_date': '2026-09-16T08:00:00'}
        with patch('strava_to_telegram.strava.Client') as client:
            source = Strava(Mock(), StravaConfig(42, 'secret'))
            client.return_value.get_activities.return_value = [item]
            with patch.object(source, 'ready'):
                activity = next(source.activities())
        self.assertIsInstance(activity, Activity)
        self.assertEqual(activity.start_date, datetime(2026, 9, 16, 8, tzinfo=timezone.utc))
        self.assertIsNone(activity.private)
        self.assertIsNone(activity.visibility)
        self.assertIsNone(activity.start_date_local)
        self.assertIn('Activity · \n', render(activity))
