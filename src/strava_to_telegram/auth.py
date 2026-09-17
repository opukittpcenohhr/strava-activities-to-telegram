"""One-time Strava OAuth callback, reachable through an SSH tunnel on a VM."""
from dataclasses import dataclass
import secrets
import time
from typing import Any, cast, override
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from stravalib import Client

from .strava import StravaConfig
from .storage.database import Database
from .storage.tokens import TokenData


@dataclass
class AuthConfig:
    host: str
    port: int

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError('auth.port must be between 1 and 65535')
        if not self.host.strip():
            raise ValueError('auth.host must not be empty')


def validate_callback(path: str, expected_state: str) -> str:
    parsed = urlsplit(path)
    if parsed.path != '/callback':
        raise ValueError('Unknown callback path')
    query = parse_qs(parsed.query)
    if not secrets.compare_digest(query.get('state', [''])[0], expected_state):
        raise ValueError('Invalid OAuth state')
    if 'error' in query:
        raise ValueError('Authorization denied')
    if 'activity:read' not in query.get('scope', [''])[0].replace(',', ' ').split():
        raise ValueError('Activity read permission is required')
    code = query.get('code', [''])[0]
    if not code:
        raise ValueError('Missing authorization code')
    return code


def authorize(db: Database, config: AuthConfig, strava: StravaConfig) -> None:
    host, port = config.host, config.port
    client = Client()
    state = secrets.token_urlsafe(32)
    code = None

    class Callback(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Request paths contain the authorization code.

        def do_GET(self) -> None:
            nonlocal code
            try:
                value = validate_callback(self.path, state)
            except ValueError as error:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(error).encode())
                return
            code = value
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Authorization received. Check your terminal for completion.')

    with HTTPServer((host, port), Callback) as server:
        server.timeout = 1
        print('Open this link in your browser (expires here in five minutes):', flush=True)
        print(client.authorization_url(
            client_id=strava.client_id,
            redirect_uri=f'http://localhost:{port}/callback',
            scope=['activity:read'], state=state), flush=True)
        deadline = time.monotonic() + 300
        while code is None and time.monotonic() < deadline:
            server.handle_request()
    if code is None:
        raise RuntimeError('Authorization timed out; run auth again')
    tokens = client.exchange_code_for_token(
        client_id=strava.client_id,
        client_secret=strava.client_secret, code=code)
    # Without return_athlete=True, stravalib returns just the token dictionary.
    db.tokens.set(cast(TokenData, tokens))
    print('Strava authorization saved.')
