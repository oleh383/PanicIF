# -*- coding: utf-8 -*-
"""Тести текстів і обробників команд PanicIF Bot.

Тести текстів виконуються завжди. Тести обробників вимагають встановленого
пакета ``python-telegram-bot`` і пропускаються, якщо його немає.
"""

import ast
import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import bot  # noqa: E402
from bot import HELP_MESSAGE, START_MESSAGE, UNKNOWN_MESSAGE  # noqa: E402

try:
    import telegram  # noqa: F401  (перевірка наявності бібліотеки)
    HAVE_TELEGRAM = True
except Exception:  # pragma: no cover - залежить від середовища
    HAVE_TELEGRAM = False


class MessageTextTests(unittest.TestCase):
    def test_start_message_mentions_supported_inputs(self):
        self.assertIsInstance(START_MESSAGE, str)
        self.assertIn("PanicIF", START_MESSAGE)
        for ext in (".ips", ".panic", ".txt", ".log"):
            self.assertIn(ext, START_MESSAGE)
        self.assertIn("JPG", START_MESSAGE)
        self.assertIn("/help", START_MESSAGE)

    def test_help_message_describes_log_and_photo(self):
        self.assertIn(".ips", HELP_MESSAGE)
        self.assertIn("файл", HELP_MESSAGE.lower())
        self.assertIn("фото", HELP_MESSAGE.lower())

    def test_help_message_has_accuracy_disclaimer(self):
        lowered = HELP_MESSAGE.lower()
        self.assertIn("не гарантує", lowered)
        self.assertIn("точності", lowered)

    def test_help_message_warns_about_secrets(self):
        lowered = HELP_MESSAGE.lower()
        self.assertIn("паролі", lowered)
        self.assertIn("секрет", lowered)

    def test_start_and_help_contain_no_token_placeholder(self):
        for text in (START_MESSAGE, HELP_MESSAGE):
            self.assertNotIn("your_bot_token", text)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", text)

    def test_unknown_message_text(self):
        self.assertEqual(UNKNOWN_MESSAGE, "Скористайся /start або /help")


class BotPackageTests(unittest.TestCase):
    def test_package_imports_without_telegram_or_pyqt(self):
        # Пакет bot і модуль config мають бути незалежні від telegram/PyQt6.
        self.assertTrue(hasattr(bot, "__version__"))
        from bot import config as bot_config  # noqa: F401

        self.assertTrue(hasattr(bot_config, "require_bot_token"))

    def test_bot_modules_do_not_import_pyqt(self):
        bot_dir = os.path.join(ROOT, "bot")
        for name in sorted(os.listdir(bot_dir)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(bot_dir, name)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name.lower().startswith("pyqt"),
                            f"{name} імпортує {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom):
                    module = (node.module or "").lower()
                    self.assertFalse(
                        module.startswith("pyqt"),
                        f"{name} імпортує з {node.module}",
                    )


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return None


@unittest.skipUnless(HAVE_TELEGRAM, "python-telegram-bot не встановлено")
class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, handler_name, message):
        from bot import main as bot_main

        handler = getattr(bot_main, handler_name)
        update = SimpleNamespace(message=message)
        await handler(update, None)

    async def test_start_handler_replies_with_start_message(self):
        message = _FakeMessage()
        await self._run("start", message)
        self.assertEqual(message.replies, [START_MESSAGE])

    async def test_help_handler_replies_with_help_message(self):
        message = _FakeMessage()
        await self._run("help_command", message)
        self.assertEqual(message.replies, [HELP_MESSAGE])

    async def test_unknown_handler_replies_with_unknown_message(self):
        message = _FakeMessage()
        await self._run("unknown", message)
        self.assertEqual(message.replies, [UNKNOWN_MESSAGE])

    async def test_handlers_ignore_update_without_message(self):
        from bot import main as bot_main

        update = SimpleNamespace(message=None)
        await bot_main.start(update, None)
        await bot_main.help_command(update, None)
        await bot_main.unknown(update, None)


if __name__ == "__main__":
    unittest.main()
