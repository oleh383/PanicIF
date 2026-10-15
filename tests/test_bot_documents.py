# -*- coding: utf-8 -*-
"""Тести обробника документів Telegram (пропускаються без python-telegram-bot).

Документ-завантаження та мережа не виконуються: використовуються легкі фейки.
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

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
)


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
        self.get_file_calls = 0

    async def get_file(self):
        self.get_file_calls += 1
        return _FakeFile(self._data, self._error)


class _FakeMessage:
    def __init__(self, document=None):
        self.document = document
        self.texts = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)

    async def reply_document(self, document=None, filename=None, caption=None, **kwargs):
        self.documents.append({"filename": filename, "caption": caption, "bytes": document})


def _panelif_temp_files():
    tmp = tempfile.gettempdir()
    return {n for n in os.listdir(tmp) if n.startswith("panelif_")}


@unittest.skipUnless(
    __import__("importlib").util.find_spec("telegram") is not None,
    "python-telegram-bot не встановлено",
)
class DocumentHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def _handle(self, document):
        from bot import main as bot_main

        message = _FakeMessage(document)
        await bot_main.handle_document(SimpleNamespace(message=message), None)
        return message

    async def test_unsupported_extension(self):
        message = await self._handle(_FakeDocument("scan.exe", b"data"))
        self.assertEqual(message.texts, [analyzer.UNSUPPORTED_EXTENSION_MESSAGE])

    async def test_too_large_by_metadata(self):
        doc = _FakeDocument(
            "big.txt", b"x", file_size=analyzer.MAX_UPLOAD_BYTES + 1
        )
        message = await self._handle(doc)
        self.assertEqual(message.texts, [analyzer.TOO_LARGE_MESSAGE])
        self.assertEqual(doc.get_file_calls, 0)

    async def test_valid_panic_log(self):
        message = await self._handle(_FakeDocument("panic.ips", VALID_PANIC.encode("utf-8")))
        self.assertEqual(len(message.texts), 1)
        self.assertIn("Нижній шлейф (зарядки)", message.texts[0])
        self.assertIn("ЗВІТ ДІАГНОСТИКИ", message.texts[0])

    async def test_non_panic_file(self):
        message = await self._handle(_FakeDocument("notes.txt", b"hello world\n"))
        self.assertEqual(message.texts, [analyzer.NON_PANIC_MESSAGE])

    async def test_empty_file(self):
        message = await self._handle(_FakeDocument("empty.txt", b""))
        self.assertEqual(message.texts, [analyzer.NON_PANIC_MESSAGE])

    async def test_download_error_handled(self):
        doc = _FakeDocument("panic.txt", b"", error=RuntimeError("network"))
        message = await self._handle(doc)
        self.assertEqual(message.texts, [analyzer.READ_ERROR_MESSAGE])

    async def test_no_document_ignored(self):
        message = await self._handle(None)
        self.assertEqual(message.texts, [])
        self.assertEqual(message.documents, [])

    async def test_large_report_sent_as_file(self):
        from bot import main as bot_main
        from bot.services import analyzer as analyzer_module

        original = analyzer_module.build_report_text
        analyzer_module.build_report_text = lambda report: "X" * 6000
        try:
            message = await self._handle(
                _FakeDocument("panic.ips", VALID_PANIC.encode("utf-8"))
            )
        finally:
            analyzer_module.build_report_text = original

        self.assertEqual(message.texts, [])
        self.assertEqual(len(message.documents), 1)
        self.assertEqual(message.documents[0]["filename"], analyzer.REPORT_FILENAME)

    async def test_temp_files_cleaned_up(self):
        before = _panelif_temp_files()
        await self._handle(_FakeDocument("panic.ips", VALID_PANIC.encode("utf-8")))
        await self._handle(_FakeDocument("notes.txt", b"random"))
        self.assertEqual(before, _panelif_temp_files())


if __name__ == "__main__":
    unittest.main()
