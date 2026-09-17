import sqlite3
from dataclasses import dataclass
from enum import StrEnum


class PostStatus(StrEnum):
    REJECTED = 'rejected'
    SENT = 'sent'
    REMOVED = 'removed'


@dataclass(frozen=True)
class Post:
    activity_id: int
    chat_id: str
    message_id: int | None
    status: PostStatus
    content_hash: str | None
    kind: str


class Posts:
    """Activity-to-message mappings. Each transition commits before returning."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, activity_id: int, chat: str) -> Post | None:
        row = self._connection.execute(
            '''SELECT activity_id, chat_id, message_id,
            status, content_hash, kind FROM posts WHERE activity_id=? AND chat_id=?''',
            (activity_id, chat),
        ).fetchone()
        return self._post(row) if row else None

    def sent(self, chat: str) -> list[Post]:
        rows = self._connection.execute(
            '''SELECT activity_id, chat_id, message_id,
            status, content_hash, kind FROM posts
            WHERE chat_id=? AND message_id IS NOT NULL AND status='sent' ''',
            (chat,),
        ).fetchall()
        return [self._post(row) for row in rows]

    @staticmethod
    def _post(row: sqlite3.Row) -> Post:
        return Post(
            activity_id=row['activity_id'],
            chat_id=row['chat_id'],
            message_id=row['message_id'],
            status=PostStatus(row['status']),
            content_hash=row['content_hash'],
            kind=row['kind'],
        )

    def clear(self) -> int:
        """Forget every mapping and report how many. Sent messages stay in Telegram."""
        with self._connection:
            return self._connection.execute('DELETE FROM posts').rowcount

    def mark_rejected(self, activity_id: int, chat: str) -> None:
        """Record a send that Telegram definitely rejected."""
        with self._connection:
            self._connection.execute(
                '''INSERT INTO posts(activity_id, chat_id, status)
                VALUES (?, ?, 'rejected') ON CONFLICT(activity_id, chat_id)
                DO UPDATE SET status='rejected', updated_at=CURRENT_TIMESTAMP''',
                (activity_id, chat),
            )

    def mark_sent(self, activity_id: int, chat: str, message_id: int, content_hash: str, kind: str = 'text') -> None:
        with self._connection:
            self._connection.execute(
                '''INSERT INTO posts(activity_id, chat_id, message_id, status, content_hash, kind)
                VALUES (?, ?, ?, 'sent', ?, ?) ON CONFLICT(activity_id, chat_id)
                DO UPDATE SET message_id=excluded.message_id, status='sent',
                content_hash=excluded.content_hash, kind=excluded.kind,
                updated_at=CURRENT_TIMESTAMP''',
                (activity_id, chat, message_id, content_hash, kind),
            )

    def mark_removed(self, activity_id: int, chat: str) -> None:
        with self._connection:
            self._connection.execute(
                '''UPDATE posts SET status='removed', content_hash=NULL,
                updated_at=CURRENT_TIMESTAMP WHERE activity_id=? AND chat_id=?''',
                (activity_id, chat),
            )
