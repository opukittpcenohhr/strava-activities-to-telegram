"""Route maps from Mapbox's Static Images API.

Strava has no static-map endpoint, but its maps are Mapbox tiles, so this asks
Mapbox for the same picture: the encoded polyline goes into the URL as a path
overlay and comes back drawn on a basemap, one request per new post. Mapbox
renders its own attribution into the image, so nothing is owed on top.

Library exceptions must not escape this module, for the reason they must not
escape `telegram.py`: the access token sits in the URL's query string, and
`requests` puts the URL into the messages it raises.
"""
from dataclasses import dataclass
from urllib.parse import quote

import requests

API = 'https://api.mapbox.com/styles/v1'
TIMEOUT = 30
SIZE = '900x600@2x'      # Mapbox caps a side at 1280 before the @2x doubling
PADDING = 48
TRACE = '5+fc4c02-0.9'   # width + colour - opacity, in Strava's orange


@dataclass
class MapConfig:
    token: str
    style: str

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError('map.token must not be empty')
        if '/' not in self.style.strip('/'):
            raise ValueError("map.style must be owner/style-id, such as mapbox/outdoors-v12")


class MapUnavailable(RuntimeError):
    """Mapbox did not return an image. The post itself is unaffected."""


class Map:
    def __init__(self, config: MapConfig) -> None:
        self.config = config

    def url(self, polyline: str) -> str:
        overlay = f'path-{TRACE}({quote(polyline, safe="")})'
        return (f'{API}/{self.config.style}/static/{overlay}/auto/{SIZE}'
                f'?padding={PADDING}&access_token={self.config.token}')

    def image(self, polyline: str) -> bytes:
        """The route on a basemap, as PNG bytes.

        Failures never quote the URL: the token sits in its query string.
        """
        try:
            response = requests.get(self.url(polyline), timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as error:
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            detail = f'HTTP {status}' if status else 'no response'
            raise MapUnavailable(f'Mapbox returned no image ({detail})') from None
        return response.content
