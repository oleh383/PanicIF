# -*- coding: utf-8 -*-
"""Тести конфігурації PanicIF Bot (без потреби у telegram-бібліотеці)."""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot import config as bot_config  # noqa: E402


class BotTokenConfigTests(unittest.TestCase):
    def test_missing_token_returns_none(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(bot_config.get_bot_token())

    def test_blank_token_returns_none(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "   "}, clear=True):
            self.assertIsNone(bot_config.get_bot_token())

    def test_token_is_stripped(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": " 123:ABC "}, clear=True):
            self.assertEqual(bot_config.get_bot_token(), "123:ABC")

    def test_require_raises_when_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(bot_config.BotConfigError):
                bot_config.require_bot_token()

    def test_require_error_message_contains_var_and_no_secret(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(bot_config.BotConfigError) as ctx:
                bot_config.require_bot_token()
        message = str(ctx.exception)
        self.assertIn(bot_config.TOKEN_ENV_VAR, message)
        self.assertNotIn("your_bot_token", message)

    def test_require_returns_token_when_present(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "42:secret"}, clear=True):
            self.assertEqual(bot_config.require_bot_token(), "42:secret")


if __name__ == "__main__":
    unittest.main()
