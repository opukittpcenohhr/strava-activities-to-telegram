import fcntl
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from dataclasses import dataclass

from .posts import Posts
from .tokens import Tokens


@dataclass
class StorageConfig:
    database: Path


class Database:
    """Two stores sharing one connection and the command's exclusive lock."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.tokens = Tokens(connection)
        self.posts = Posts(connection)


@contextmanager
def database(path: Path | str) -> Generator[Database]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(str(path) + '.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another command is using this database') from None
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        try:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS tokens (id INTEGER PRIMARY KEY CHECK (id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS posts (
                activity_id INTEGER NOT NULL, chat_id TEXT NOT NULL,
                message_id INTEGER, status TEXT NOT NULL,
                content_hash TEXT, kind TEXT NOT NULL DEFAULT 'text',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(activity_id, chat_id), UNIQUE(chat_id, message_id)
            );
            ''')
            yield Database(db)
        finally:
            db.close()
