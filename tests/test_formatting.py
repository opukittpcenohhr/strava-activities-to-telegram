import unittest
from datetime import datetime, timezone

from strava_to_telegram.formatting import render
from strava_to_telegram.strava import Activity


class RenderTests(unittest.TestCase):
    def test_names_are_escaped_and_effort_suits_the_sport(self) -> None:
        ride = Activity(
            id=1,
            name='Tom & Jerry <3',
            sport_type='GravelRide',
            distance=42000,
            moving_time=3600,
            start_date=datetime(2026, 9, 16, 8, tzinfo=timezone.utc),
        )
        text = render(ride)
        self.assertIn('🚵 Gravel Ride — <b>Tom &amp; Jerry &lt;3</b>', text)
        self.assertIn('</b>\n\n42.00 km\n1h 00m · 42.0 km/h\n\n<a', text)

    def test_missing_distance_and_duration_leave_no_empty_stat_line(self) -> None:
        text = render(
            Activity(id=2, name='Yoga', sport_type='Yoga', start_date=datetime(2026, 9, 16, 8, tzinfo=timezone.utc))
        )
        self.assertEqual(
            text, '🧘 Yoga — <b>Yoga</b>\n\n' '<a href="https://www.strava.com/activities/2">View on Strava</a>'
        )
