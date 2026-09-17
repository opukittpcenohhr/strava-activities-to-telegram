"""Telegram Bot API access through pyTelegramBotAPI.

Library exceptions are never allowed to escape this module. They are raised by
`requests`, whose messages embed the request URL -- and the bot token sits in that
URL's path. Every call below converts them into messages written here and re-raises
with `from None`, so neither a log line nor a traceback can carry the token.
"""
from dataclasses import dataclass

import requests
import telebot
from telebot.apihelper import ApiException, ApiTelegramException
from telebot.types import LinkPreviewOptions


TIMEOUT = 30


@dataclass
class TelegramConfig:
    channel_id: int
    bot_token: str

    def __post_init__(self) -> None:
        if not str(self.channel_id).startswith('-100'):
            raise ValueError('telegram.channel_id must be a numeric channel ID beginning -100')
        if not self.bot_token.strip():
            raise ValueError('telegram.bot_token must not be empty')

    @property
    def chat(self) -> str:
        """Destination as the Bot API wants it: the channel ID as a string."""
        return str(self.channel_id)


class Rejected(RuntimeError):
    """The request definitely did not take effect; safe to record as failed."""


class Uncertain(RuntimeError):
    """The request may have taken effect; retrying a send can create a duplicate."""


def status_of(error: Exception) -> int | None:
    """HTTP status behind a library exception, or None when it does not carry one."""
    if isinstance(error, ApiTelegramException):
        return error.error_code
    return getattr(getattr(error, 'result', None), 'status_code', None)


def failure(error: Exception, uncertain: str) -> Rejected | Uncertain:
    """Map a library exception onto the delivery taxonomy.

    A status Telegram chose to return means the request was seen and refused. A
    server error, an unreadable response, or a network failure all leave delivery
    unknown, so retrying a send can create a duplicate.
    """
    status = status_of(error)
    if status is not None and status < 500:
        return Rejected(f'Telegram rejected request (HTTP {status})')
    return Uncertain(uncertain)


class Telegram:
    def __init__(self, token: str) -> None:
        self.bot = telebot.TeleBot(token, threaded=False)

    def send(self, chat: str, text: str) -> int:
        try:
            message = self.bot.send_message(
                chat, text, timeout=TIMEOUT,
                link_preview_options=LinkPreviewOptions(is_disabled=True))
        except (ApiException, requests.RequestException) as error:
            raise failure(error, 'Telegram response unavailable; delivery may have succeeded') from None
        return message.message_id

    def edit(self, chat: str, message: int, text: str, kind: str) -> None:
        unreadable = 'Telegram edit response unavailable; safe to retry edit'
        try:
            if kind == 'caption':
                self.bot.edit_message_caption(text, chat_id=chat, message_id=message, timeout=TIMEOUT)
            else:
                self.bot.edit_message_text(text, chat_id=chat, message_id=message, timeout=TIMEOUT,
                                           link_preview_options=LinkPreviewOptions(is_disabled=True))
        except ApiTelegramException as error:
            # Telegram reports an identical edit as an error; treat it as successful recovery.
            if error.error_code == 400 and 'message is not modified' in (error.description or ''):
                return
            raise failure(error, unreadable) from None
        except (ApiException, requests.RequestException) as error:
            raise failure(error, unreadable) from None
