import traceback
import unittest
from unittest.mock import Mock

import requests
from telebot.apihelper import ApiHTTPException, ApiTelegramException

from strava_to_telegram.telegram import Rejected, Telegram, Uncertain

TOKEN = '123456:SUPERSECRET-BOT-TOKEN'


def api_error(code, description='Bad Request'):
    return ApiTelegramException('sendMessage', Mock(status_code=code),
                                {'error_code': code, 'description': description})


def http_error(code):
    return ApiHTTPException('sendMessage', Mock(status_code=code, reason='x', text='body'))


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.telegram = Telegram(TOKEN)
        self.telegram.bot = Mock()

    def test_refusals_are_rejected_and_server_faults_are_uncertain(self):
        for error, expected in [(api_error(400), Rejected), (api_error(403), Rejected),
                                (api_error(429), Rejected), (api_error(502), Uncertain),
                                (http_error(400), Rejected), (http_error(503), Uncertain),
                                (requests.ConnectionError('boom'), Uncertain),
                                (requests.Timeout('slow'), Uncertain)]:
            with self.subTest(error=type(error).__name__, status=getattr(error, 'error_code', None)):
                self.telegram.bot.send_message.side_effect = error
                with self.assertRaises(expected):
                    self.telegram.send('-100123', 'text')

    def test_library_messages_never_reach_the_caller(self):
        """requests embeds the request URL, and the bot token lives in that path."""
        leaky = requests.ConnectionError(
            f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
        self.telegram.bot.send_message.side_effect = leaky
        with self.assertRaises(Uncertain) as caught:
            self.telegram.send('-100123', 'text')
        self.assertNotIn('SUPERSECRET', str(caught.exception))
        # `from None` keeps __context__ attached but suppresses it everywhere the
        # standard machinery renders a traceback, which is what reaches a log.
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        rendered = ''.join(traceback.format_exception(caught.exception))
        self.assertNotIn('SUPERSECRET', rendered)

    def test_identical_edit_counts_as_success(self):
        self.telegram.bot.edit_message_text.side_effect = api_error(
            400, 'Bad Request: message is not modified')
        self.assertIsNone(self.telegram.edit('-100123', 5, 'text', 'text'))

    def test_caption_edits_use_the_caption_endpoint(self):
        self.telegram.edit('-100123', 5, 'text', 'caption')
        self.telegram.bot.edit_message_caption.assert_called_once()
        self.telegram.bot.edit_message_text.assert_not_called()
