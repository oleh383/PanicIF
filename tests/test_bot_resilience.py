# -*- coding: utf-8 -*-
"""Тести надійності PanicIF Bot: ліміти, помилки Telegram/аналізу, безпечні
повідомлення. Пропускаються без python-telegram-bot. Мережа не використовується.
"""

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot.services import analyzer  # noqa: E402

try:
    import telegram  # noqa: F401
    HAVE_TELEGRAM = True
except Exception:  # pragma: no cover
    HAVE_TELEGRAM = False


VALID_PANIC = (
    '{"panicString":"panic(cpu 0 caller x): Prs0 sensor failure @Eiger.cpp:123",'
    '"panicFlags":"0x2","product":"iPhone14,2"}\n'
).encode("utf-8")


class _User:
    def __init__(self, user_id):
        self.id = user_id


class _FakeFile:
    def __init__(self, data, error=None):
        self._data = data
        self._error = error

    async def download_as_bytearray(self):
        if self._error is not None:
            raise self._error
        return bytearray(self._data)


class _FakeDocument:
    def __init__(self, file_name, data=b"", file_size=None, error=None):
        self.file_name = file_name
        self._data = data
        self.file_size = file_size
        self._error = error

    async def get_file(self):
        return _FakeFile(self._data, self._error)


class _FakeMessage:
    def __init__(self, user_id=None, document=None, photo=None, reply_error=None):
        self.user_id = user_id
        self.from_user = _User(user_id) if user_id is not None else None
        self.chat_id = user_id
        self.document = document
        self.photo = photo
        self.reply_error = reply_error
        self.texts = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        if self.reply_error is not None:
            raise self.reply_error
        self.texts.append(text)

    async def reply_document(self, document=None, filename=None, caption=None, **kwargs):
        self.documents.append({"filename": filename, "caption": caption})


@unittest.skipUnless(HAVE_TELEGRAM, "python-telegram-bot не встановлено")
class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from bot import main as bot_main

        self.bot_main = bot_main
        bot_main._rate_limiter.reset()

    def tearDown(self):
        self.bot_main._rate_limiter.reset()

    async def _document(self, message):
        await self.bot_main.handle_document(SimpleNamespace(message=message), None)

    # --- ліміт частоти -------------------------------------------------
    async def test_rate_limit_blocks_after_max_requests(self):
        limit = self.bot_main._rate_limiter.max_requests
        for _ in range(limit):
            msg = _FakeMessage(user_id=555, document=_FakeDocument("p.ips", VALID_PANIC))
            await self._document(msg)
            self.assertEqual(len(msg.texts), 1)
            self.assertNotIn(analyzer.RATE_LIMIT_MESSAGE, msg.texts)

        blocked = _FakeMessage(user_id=555, document=_FakeDocument("p.ips", VALID_PANIC))
        await self._document(blocked)
        self.assertEqual(blocked.texts, [analyzer.RATE_LIMIT_MESSAGE])

    async def test_rate_limit_is_per_user(self):
        limit = self.bot_main._rate_limiter.max_requests
        for _ in range(limit):
            await self._document(
                _FakeMessage(user_id=1, document=_FakeDocument("p.ips", VALID_PANIC))
            )
        other = _FakeMessage(user_id=2, document=_FakeDocument("p.ips", VALID_PANIC))
        await self._document(other)
        self.assertNotIn(analyzer.RATE_LIMIT_MESSAGE, other.texts)

    async def test_rate_limit_not_applied_without_user(self):
        limit = self.bot_main._rate_limiter.max_requests
        for _ in range(limit + 2):
            msg = _FakeMessage(document=_FakeDocument("p.ips", VALID_PANIC))
            await self._document(msg)
            self.assertNotIn(analyzer.RATE_LIMIT_MESSAGE, msg.texts)

    # --- одночасність --------------------------------------------------
    async def test_busy_message_when_all_slots_taken(self):
        semaphore = self.bot_main._get_analysis_semaphore()
        for _ in range(self.bot_main.MAX_CONCURRENT_ANALYSES):
            await semaphore.acquire()
        try:
            msg = _FakeMessage(user_id=777, document=_FakeDocument("p.ips", VALID_PANIC))
            await self._document(msg)
            self.assertEqual(msg.texts, [analyzer.BUSY_MESSAGE])
        finally:
            for _ in range(self.bot_main.MAX_CONCURRENT_ANALYSES):
                semaphore.release()

    async def test_parallel_requests_all_succeed(self):
        messages = [
            _FakeMessage(user_id=9000 + i, document=_FakeDocument("p.ips", VALID_PANIC))
            for i in range(self.bot_main.MAX_CONCURRENT_ANALYSES)
        ]
        await asyncio.gather(*(self._document(m) for m in messages))
        for msg in messages:
            self.assertEqual(len(msg.texts), 1)
            self.assertIn("Нижній шлейф (зарядки)", msg.texts[0])

    # --- помилки Telegram API / аналізу --------------------------------
    async def test_telegram_reply_error_propagates_to_error_handler(self):
        error = RuntimeError("telegram network down")
        msg = _FakeMessage(
            user_id=321, document=_FakeDocument("p.ips", VALID_PANIC), reply_error=error
        )
        with self.assertRaises(RuntimeError):
            await self._document(msg)

        # Глобальний обробник має надіслати безпечне повідомлення.
        safe = _FakeMessage(user_id=321)
        context = SimpleNamespace(error=error)
        await self.bot_main.on_error(SimpleNamespace(message=safe), context)
        self.assertEqual(safe.texts, [analyzer.GENERIC_ERROR_MESSAGE])

    async def test_on_error_ignores_update_without_message(self):
        context = SimpleNamespace(error=RuntimeError("boom"))
        await self.bot_main.on_error(None, context)
        await self.bot_main.on_error(SimpleNamespace(message=None), context)

    async def test_on_error_send_failure_is_suppressed(self):
        context = SimpleNamespace(error=RuntimeError("boom"))
        broken = _FakeMessage(user_id=1, reply_error=RuntimeError("cannot send"))
        await self.bot_main.on_error(SimpleNamespace(message=broken), context)

    async def test_analysis_error_is_safe(self):
        msg = _FakeMessage(user_id=42, document=_FakeDocument("p.ips", VALID_PANIC))
        with mock.patch.object(
            analyzer, "analyze_log_bytes", side_effect=RuntimeError("internal")
        ):
            await self._document(msg)
        self.assertEqual(msg.texts, [analyzer.ANALYSIS_ERROR_MESSAGE])
        self.assertNotIn("Traceback", msg.texts[0])

    async def test_timeout_returns_safe_message(self):
        def _slow(*_args, **_kwargs):
            import time

            time.sleep(0.3)
            return None

        msg = _FakeMessage(user_id=43, document=_FakeDocument("p.ips", VALID_PANIC))
        with mock.patch.object(self.bot_main, "ANALYSIS_TIMEOUT_SECONDS", 0.05), \
                mock.patch.object(analyzer, "analyze_log_bytes", side_effect=_slow):
            await self._document(msg)
        self.assertEqual(msg.texts, [analyzer.TIMEOUT_MESSAGE])

    # --- безпека повідомлень -------------------------------------------
    def test_user_messages_have_no_technical_leaks(self):
        for name in dir(analyzer):
            if not name.endswith("_MESSAGE"):
                continue
            value = getattr(analyzer, name)
            if not isinstance(value, str):
                continue
            self.assertNotIn("Traceback", value, name)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", value, name)

    # --- збереження робочої поведінки ----------------------------------
    async def test_panic_log_still_analyzed(self):
        msg = _FakeMessage(user_id=44, document=_FakeDocument("p.ips", VALID_PANIC))
        await self._document(msg)
        self.assertEqual(len(msg.texts), 1)
        self.assertIn("ЗВІТ ДІАГНОСТИКИ", msg.texts[0])


if __name__ == "__main__":
    unittest.main()
