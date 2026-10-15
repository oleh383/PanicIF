# -*- coding: utf-8 -*-
"""Тести OCR-аналізу фото (розпізнавання + аналіз наявним ядром PanicIF).

Тести рівня сервісу виконуються без telegram. Тести обробників пропускаються
без python-telegram-bot або без OCR-залежностей. Файли не зберігаються.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from bot.services import analyzer  # noqa: E402


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # pragma: no cover
        return False


HAVE_OCR = all(_has_module(m) for m in ("numpy", "cv2", "rapidocr_onnxruntime"))
HAVE_TELEGRAM = _has_module("telegram")

_SAMPLE_IMAGE = None


def _sample_image_bytes():
    """PNG із діагностичним текстом (кешується між тестами)."""
    global _SAMPLE_IMAGE
    if _SAMPLE_IMAGE is None:
        import cv2
        import numpy as np

        img = np.full((220, 1500, 3), 255, dtype=np.uint8)
        cv2.putText(
            img,
            "panic(cpu 0): Prs0 sensor barometer failure",
            (20, 120),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.7,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        path = os.path.join(tempfile.gettempdir(), "panelif_ocr_sample.png")
        cv2.imwrite(path, img)
        with open(path, "rb") as handle:
            _SAMPLE_IMAGE = handle.read()
        os.remove(path)
    return _SAMPLE_IMAGE


def _panelif_temp_files():
    tmp = tempfile.gettempdir()
    return {name for name in os.listdir(tmp) if name.startswith("panelif_")}


class ImageExtensionTests(unittest.TestCase):
    def test_supported_image_extensions(self):
        for name in ("a.png", "b.jpg", "c.jpeg", "D.PNG", "E.JPG"):
            self.assertTrue(analyzer.is_supported_image_extension(name), name)

    def test_unsupported_image_extensions(self):
        for name in ("a.gif", "b.bmp", "c.pdf", "noext", "", "d.ips"):
            self.assertFalse(analyzer.is_supported_image_extension(name), name)


class PhotoTextAnalysisTests(unittest.TestCase):
    def test_non_diagnostic_text_has_no_findings(self):
        report = analyzer.analyze_photo_text("hello world, just random text")
        self.assertIsNotNone(report)
        self.assertEqual(report.findings, [])
        self.assertIn("ключ", report.verdict.lower())

    def test_photo_summary_without_text(self):
        analysis = analyzer.PhotoAnalysis("", None)
        self.assertEqual(analyzer.summarize_photo(analysis), analyzer.OCR_NO_TEXT_MESSAGE)

    def test_photo_summary_uses_core_verdict(self):
        report = analyzer.analyze_photo_text("panic(cpu 0): Prs0 sensor failure")
        analysis = analyzer.PhotoAnalysis("text", report)
        self.assertEqual(analyzer.summarize_photo(analysis), report.verdict)


class ImageBytesEdgeCaseTests(unittest.TestCase):
    def test_empty_data_returns_no_text(self):
        analysis = analyzer.analyze_image_bytes(b"", "photo.png")
        self.assertEqual(analysis.text, "")
        self.assertIsNone(analysis.report)

    def test_non_image_content_rejected(self):
        with self.assertRaises(analyzer.UnsupportedImageError):
            analyzer.analyze_image_bytes(b"hello, not an image at all", "photo.png")

    def test_random_binary_rejected(self):
        with self.assertRaises(analyzer.UnsupportedImageError):
            analyzer.analyze_image_bytes(b"\x00\x01\x02\x03" * 128, "photo.jpg")

    def test_oversized_image_raises(self):
        big = b"a" * (analyzer.MAX_IMAGE_UPLOAD_BYTES + 1)
        with self.assertRaises(analyzer.AnalyzerError):
            analyzer.analyze_image_bytes(big, "photo.png")

    def test_ocr_unavailable_is_wrapped(self):
        original = analyzer.ocr_image_to_text
        analyzer.ocr_image_to_text = lambda path: (_ for _ in ()).throw(
            RuntimeError("no ocr")
        )
        try:
            with self.assertRaises(analyzer.OcrUnavailableError):
                analyzer.analyze_image_bytes(_PNG_SIGNATURE_MIN, "photo.png")
        finally:
            analyzer.ocr_image_to_text = original

    def test_temp_files_cleaned_up_on_rejection(self):
        before = _panelif_temp_files()
        with self.assertRaises(analyzer.UnsupportedImageError):
            analyzer.analyze_image_bytes(b"not an image", "photo.png")
        self.assertEqual(before, _panelif_temp_files())


# Мінімальний валідний PNG (1x1), щоб пройти перевірку сигнатури.
_PNG_SIGNATURE_MIN = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


@unittest.skipUnless(HAVE_OCR, "OCR-залежності (numpy/cv2/rapidocr) не встановлено")
class OcrRecognizeTests(unittest.TestCase):
    def test_recognizes_and_finds_issue(self):
        analysis = analyzer.analyze_image_bytes(_sample_image_bytes(), "photo.png")
        self.assertTrue(analysis.text.strip())
        self.assertIsNotNone(analysis.report)
        self.assertGreaterEqual(len(analysis.report.findings), 1)
        self.assertEqual(analysis.report.source_type, "photo")
        self.assertIn("Нижній шлейф (зарядки)", analyzer.summarize_photo(analysis))

    def test_temp_files_cleaned_up_after_ocr(self):
        before = _panelif_temp_files()
        analyzer.analyze_image_bytes(_sample_image_bytes(), "photo.png")
        self.assertEqual(before, _panelif_temp_files())


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


class _FakePhoto:
    def __init__(self, data=b"", file_size=None, error=None):
        self._data = data
        self.file_size = file_size
        self._error = error

    async def get_file(self):
        return _FakeFile(self._data, self._error)


class _FakeMessage:
    def __init__(self, document=None, photo=None):
        self.document = document
        self.photo = photo
        self.texts = []
        self.documents = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)

    async def reply_document(self, document=None, filename=None, caption=None, **kwargs):
        self.documents.append(
            {"filename": filename, "caption": caption, "bytes": document}
        )


class _ImageHandlerTestsMixin:
    async def _handle_document(self, document):
        from bot import main as bot_main

        message = _FakeMessage(document=document)
        await bot_main.handle_document(SimpleNamespace(message=message), None)
        return message

    async def _handle_photo(self, photo):
        from bot import main as bot_main

        photos = None if photo is None else [photo]
        message = _FakeMessage(photo=photos)
        await bot_main.handle_photo(SimpleNamespace(message=message), None)
        return message


@unittest.skipUnless(HAVE_TELEGRAM, "python-telegram-bot не встановлено")
class ImageHandlerRoutingTests(unittest.IsolatedAsyncioTestCase, _ImageHandlerTestsMixin):
    async def test_image_document_rejected_when_not_real_image(self):
        message = await self._handle_document(
            _FakeDocument("scan.png", b"not an image")
        )
        self.assertEqual(message.texts, [analyzer.UNSUPPORTED_IMAGE_MESSAGE])

    async def test_image_document_too_large_by_metadata(self):
        doc = _FakeDocument(
            "big.png", b"x", file_size=analyzer.MAX_IMAGE_UPLOAD_BYTES + 1
        )
        message = await self._handle_document(doc)
        self.assertEqual(message.texts, [analyzer.TOO_LARGE_IMAGE_MESSAGE])
        self.assertEqual(doc.get_file_calls, 0)

    async def test_unsupported_image_extension_message(self):
        message = await self._handle_document(_FakeDocument("pic.bmp", b"data"))
        self.assertEqual(message.texts, [analyzer.UNSUPPORTED_EXTENSION_MESSAGE])

    async def test_photo_too_large_by_metadata(self):
        photo = _FakePhoto(b"x", file_size=analyzer.MAX_IMAGE_UPLOAD_BYTES + 1)
        message = await self._handle_photo(photo)
        self.assertEqual(message.texts, [analyzer.TOO_LARGE_IMAGE_MESSAGE])

    async def test_photo_download_error_handled(self):
        photo = _FakePhoto(b"", error=RuntimeError("network"))
        message = await self._handle_photo(photo)
        self.assertEqual(message.texts, [analyzer.READ_ERROR_MESSAGE])

    async def test_no_photo_ignored(self):
        message = await self._handle_photo(None)
        self.assertEqual(message.texts, [])


@unittest.skipUnless(
    HAVE_TELEGRAM and HAVE_OCR,
    "потрібні python-telegram-bot та OCR-залежності",
)
class ImageHandlerFlowTests(unittest.IsolatedAsyncioTestCase, _ImageHandlerTestsMixin):
    async def test_photo_with_panic_text_returns_findings(self):
        photo = _FakePhoto(_sample_image_bytes())
        message = await self._handle_photo(photo)
        self.assertEqual(len(message.texts), 1)
        self.assertIn("Нижній шлейф (зарядки)", message.texts[0])

    async def test_image_document_with_panic_text_returns_findings(self):
        message = await self._handle_document(
            _FakeDocument("screenshot.jpg", _sample_image_bytes())
        )
        self.assertEqual(len(message.texts), 1)
        self.assertIn("Нижній шлейф (зарядки)", message.texts[0])

    async def test_photo_without_text_reports_no_text(self):
        import cv2
        import numpy as np

        path = os.path.join(tempfile.gettempdir(), "panelif_blank.png")
        cv2.imwrite(path, np.full((200, 800, 3), 255, dtype=np.uint8))
        with open(path, "rb") as handle:
            blank = handle.read()
        os.remove(path)

        message = await self._handle_photo(_FakePhoto(blank))
        self.assertEqual(message.texts, [analyzer.OCR_NO_TEXT_MESSAGE])

    async def test_temp_files_cleaned_up_after_photo(self):
        before = _panelif_temp_files()
        await self._handle_photo(_FakePhoto(_sample_image_bytes()))
        self.assertEqual(before, _panelif_temp_files())


if __name__ == "__main__":
    unittest.main()
