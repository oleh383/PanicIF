# -*- coding: utf-8 -*-
"""Тести сервісу аналізу panic-логів (без потреби у telegram-бібліотеці).

Перевіряють повторне використання ядра PanicIF, обробку крайніх випадків
(порожній/довільний/бінарний файл, ліміт розміру), очищення тимчасових
файлів та відсутність імпорту PyQt6.
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core import diagnostics as core  # noqa: E402
from bot.services import analyzer  # noqa: E402


VALID_PANIC = (
    '{"bug_type":"210","timestamp":"2026-01-01 10:00:00.00 +0000",'
    '"os_version":"iPhone OS 18.0 (22A123)","incident_id":"AAAA-BBBB",'
    '"panicString":"panic(cpu 0 caller 0xfffffff): Prs0 sensor failure '
    '@Eiger.cpp:123","panicFlags":"0x2","product":"iPhone14,2",'
    '"build":"22A123"}\n'
)


def _panelif_temp_files():
    tmp = tempfile.gettempdir()
    return {
        name for name in os.listdir(tmp)
        if name.startswith("panelif_")
    }


class AnalyzeValidLogTests(unittest.TestCase):
    def test_reuses_core_and_finds_issue(self):
        report = analyzer.analyze_log_bytes(VALID_PANIC.encode("utf-8"), "panic-full.ips")
        self.assertIsNotNone(report)
        self.assertTrue(report.is_panic_source)
        self.assertEqual(report.source_type, "panic-full")
        self.assertGreaterEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].component, "Нижній шлейф (зарядки)")

    def test_report_text_comes_from_core(self):
        report = analyzer.analyze_log_bytes(VALID_PANIC.encode("utf-8"), "log.txt")
        text = analyzer.build_report_text(report)
        self.assertIn("ЗВІТ ДІАГНОСТИКИ", text)
        self.assertIn("Нижній шлейф (зарядки)", text)

    def test_summary_mentions_component(self):
        report = analyzer.analyze_log_bytes(VALID_PANIC.encode("utf-8"), "log.txt")
        self.assertIn("Нижній шлейф (зарядки)", analyzer.summarize(report))


class AnalyzeNonPanicTests(unittest.TestCase):
    def test_empty_data_returns_none(self):
        self.assertIsNone(analyzer.analyze_log_bytes(b"", "empty.txt"))

    def test_random_text_returns_none(self):
        self.assertIsNone(
            analyzer.analyze_log_bytes(b"hello world\nnothing to see\n", "notes.txt")
        )

    def test_panic_in_name_without_content_is_not_panic(self):
        self.assertIsNone(
            analyzer.analyze_log_bytes(b"just some random text\n", "crash.panic")
        )

    def test_binary_data_returns_none(self):
        self.assertIsNone(
            analyzer.analyze_log_bytes(b"\x00\x01\x02\xff\xfe" * 64, "photo.bin")
        )

    def test_corrupted_utf8_does_not_crash(self):
        data = VALID_PANIC.encode("utf-8") + b"\xff\xfe\x00broken"
        report = analyzer.analyze_log_bytes(data, "broken.log")
        self.assertIsNotNone(report)


class ExtensionTests(unittest.TestCase):
    def test_supported_extensions(self):
        for name in ("a.ips", "b.panic", "c.txt", "d.log", "E.LOG", "F.IPS"):
            self.assertTrue(analyzer.is_supported_extension(name), name)

    def test_unsupported_extensions(self):
        for name in ("a.exe", "b.pdf", "c.png", "noext", ""):
            self.assertFalse(analyzer.is_supported_extension(name), name)


class SizeLimitTests(unittest.TestCase):
    def test_oversized_data_raises(self):
        big = b"a" * (analyzer.MAX_UPLOAD_BYTES + 1)
        with self.assertRaises(analyzer.AnalyzerError):
            analyzer.analyze_log_bytes(big, "big.txt")


class TempFileCleanupTests(unittest.TestCase):
    def test_no_temp_files_left_after_analysis(self):
        before = _panelif_temp_files()
        analyzer.analyze_log_bytes(VALID_PANIC.encode("utf-8"), "panic-full.ips")
        analyzer.analyze_log_bytes(b"random text", "x.txt")
        after = _panelif_temp_files()
        self.assertEqual(before, after)


class NoPyQt6ImportTests(unittest.TestCase):
    def test_core_does_not_import_real_pyqt6(self):
        code = (
            "import app.core; import sys; "
            "m = sys.modules.get('PyQt6'); "
            "print('ok' if (m is None or getattr(m, '_PANICIF_QT_STUB', False)) else 'fail')"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok", result.stdout + result.stderr)

    def test_core_module_is_the_desktop_source(self):
        self.assertEqual(core.APP_VERSION, "1.2.0")
        self.assertIn(".ips", core.SUPPORTED_LOG_EXTENSIONS)


if __name__ == "__main__":
    unittest.main()
