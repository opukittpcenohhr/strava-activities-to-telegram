import json
import sqlite3
from typing import TypedDict


class TokenData(TypedDict):
    access_token: str
    refresh_token: str
    expires_at: int


class Tokens:
    """Strava OAuth tokens. Saving commits before returning."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self) -> TokenData | None:
        row = self._connection.execute('SELECT value FROM tokens WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def set(self, tokens: TokenData) -> None:
        with self._connection:
            self._connection.execute('INSERT OR REPLACE INTO tokens(id, value) VALUES (1, ?)',
                                     (json.dumps(tokens),))
