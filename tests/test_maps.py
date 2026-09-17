import unittest
from unittest.mock import Mock, patch

import requests

from strava_to_telegram.maps import Map, MapConfig, MapUnavailable

POLYLINE = '_p~iF~ps|U_ulLnnqC_mqNvxq`@'
TOKEN = 'pk.secret-token'


def maps(style: str = 'mapbox/outdoors-v12') -> Map:
    return Map(MapConfig(TOKEN, style))


class MapConfigTests(unittest.TestCase):
    def test_style_must_name_an_owner(self) -> None:
        for style in ('outdoors-v12', '/outdoors-v12', ''):
            with self.subTest(style=style or 'empty'):
                with self.assertRaises(ValueError):
                    MapConfig(TOKEN, style)

    def test_token_must_not_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            MapConfig('  ', 'mapbox/outdoors-v12')


class MapTests(unittest.TestCase):
    def test_url_carries_the_escaped_polyline_and_the_chosen_style(self) -> None:
        url = maps().url(POLYLINE)
        self.assertIn('/styles/v1/mapbox/outdoors-v12/static/', url)
        self.assertIn('%7C', url.replace('|', '%7C'))  # polyline is percent-escaped
        self.assertNotIn('(_p~iF~ps|U', url)  # ...never raw
        self.assertTrue(url.endswith(f'access_token={TOKEN}'))

    def test_image_returns_the_body(self) -> None:
        with patch('strava_to_telegram.maps.requests.get') as get:
            get.return_value = Mock(content=b'PNG-bytes', raise_for_status=Mock())
            self.assertEqual(maps().image(POLYLINE), b'PNG-bytes')

    def test_failures_never_carry_the_token(self) -> None:
        cases = (
            requests.ConnectionError(f'failed for url: ...access_token={TOKEN}'),
            requests.HTTPError(response=Mock(status_code=401)),
        )
        for error in cases:
            with self.subTest(error=type(error).__name__):
                with patch('strava_to_telegram.maps.requests.get', side_effect=error):
                    with self.assertRaises(MapUnavailable) as caught:
                        maps().image(POLYLINE)
                self.assertNotIn(TOKEN, str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
